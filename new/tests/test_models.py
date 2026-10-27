"""Offline tests of the model adapters: a fake transport stands in for the network and checks
that requests follow the providers' documented formats. Nothing here calls a real service."""
import io
import json
import urllib.error
import wave

import pytest

from conftest import dossier_dirs
from lcw import models
from lcw.schema import DOCUMENT_FIELDS, coerce_document
from lcw.tools import TOOL_SCHEMAS


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Transport:
    """Replaces ``models._send``: records each request, plays back queued replies."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, dict):
            reply = json.dumps(reply)
        return Reply(reply.encode() if isinstance(reply, str) else reply)

    def body(self, index=-1):
        return json.loads(self.requests[index].data)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "bt-test-key-123456")
    monkeypatch.setenv("META_MODEL_API_KEY", "meta-test-key-123456")
    monkeypatch.delenv("LCW_ORCHESTRATOR", raising=False)
    monkeypatch.setattr(models.time, "sleep", lambda s: None)


def completion(content=None, tool_calls=None, usage=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def test_chat_follows_the_openai_tool_format(keys, monkeypatch):
    fake = Transport(completion(tool_calls=[{"id": "call_1", "type": "function", "function": {
        "name": "read_document", "arguments": '{"document": "awb", "reason": "start"}'}}]))
    monkeypatch.setattr(models, "_send", fake)
    history = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
               {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c0", "name": "lookup_rule", "arguments": {"rule": "R01"}}]},
               {"role": "tool", "tool_call_id": "c0", "name": "lookup_rule", "content": "{}"}]
    reply = models.chat(history, TOOL_SCHEMAS)

    request = fake.requests[0]
    assert request.full_url == "https://inference.baseten.co/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer bt-test-key-123456"
    body = fake.body()
    assert body["model"] == "meta-models/muse-spark-open-1026" and body["tool_choice"] == "auto"
    assert body["tools"][0] == {"type": "function", "function": {
        "name": TOOL_SCHEMAS[0]["name"], "description": TOOL_SCHEMAS[0]["description"],
        "parameters": TOOL_SCHEMAS[0]["parameters"]}}
    replayed = body["messages"][2]["tool_calls"][0]
    assert replayed["type"] == "function" and json.loads(replayed["function"]["arguments"]) == {"rule": "R01"}
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "c0", "content": "{}"}
    assert reply == {"content": None, "tool_calls": [
        {"id": "call_1", "name": "read_document", "arguments": {"document": "awb", "reason": "start"}}]}
    assert models.USAGE[-1]["prompt_tokens"] == 10


def test_bad_arguments_are_passed_through_as_text(keys, monkeypatch):
    fake = Transport(completion(tool_calls=[{"id": "x", "function": {"name": "lookup_rule", "arguments": "{oops"}}]))
    monkeypatch.setattr(models, "_send", fake)
    assert models.chat([{"role": "user", "content": "u"}])["tool_calls"][0]["arguments"] == "{oops"


def test_fallback_orchestrator_uses_muse_spark(keys, monkeypatch):
    monkeypatch.setenv("LCW_ORCHESTRATOR", "spark")
    fake = Transport(completion(content='{"decision": "go"}'))
    monkeypatch.setattr(models, "_send", fake)
    models.chat([{"role": "user", "content": "u"}])
    assert fake.requests[0].full_url == "https://api.meta.ai/v1/chat/completions"
    assert fake.body()["model"] == "muse-spark-1.3"
    assert models.orchestrator_name() == "Muse Spark"


def test_retries_on_429_then_succeeds(keys, monkeypatch):
    busy = urllib.error.HTTPError("u", 429, "busy", {}, io.BytesIO(b"rate limited"))
    fake = Transport(busy, completion(content="ok"))
    monkeypatch.setattr(models, "_send", fake)
    assert models.chat([{"role": "user", "content": "u"}])["content"] == "ok"
    assert len(fake.requests) == 2


def test_client_errors_are_not_retried_and_hide_the_key(keys, monkeypatch):
    bad = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b'{"error": "bad key bt-test-key-123456"}'))
    fake = Transport(bad)
    monkeypatch.setattr(models, "_send", fake)
    with pytest.raises(models.ModelError) as error:
        models.chat([{"role": "user", "content": "u"}])
    assert "bt-test-key-123456" not in str(error.value) and "HTTP 400" in str(error.value)
    assert len(fake.requests) == 1


def test_missing_key_names_the_variable(monkeypatch):
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    with pytest.raises(models.ModelError, match="BASETEN_API_KEY"):
        models.chat([{"role": "user", "content": "u"}])


def test_read_document_types_and_regions(keys, monkeypatch):
    folder = dossier_dirs()[0]
    image = folder / "documents" / "awb.png"
    answer = {"fields": {"awb_number": "AWB 000-12345675", "head_count": "12", "handling_codes": "AVI",
                         "temperature_range_c": "10 °C to 24 °C", "signed": "yes", "route": ["ORI", "DES"]},
              "boxes": {"awb_number": [100, 50, 400, 80], "head_count": "nowhere"}}
    fake = Transport(completion(content="Here it is:\n```json\n" + json.dumps(answer) + "\n```"))
    monkeypatch.setattr(models, "_send", fake)
    read = models.read_document_image(image, "awb")
    assert read["awb_number"] == "000-12345675" and read["head_count"] == 12
    assert read["handling_codes"] == ["AVI"] and read["temperature_range_c"] == [10.0, 24.0]
    assert read["shipper"] is None  # not read -> None, never guessed
    assert set(read) == set(DOCUMENT_FIELDS["awb"]) | {"_regions"}
    assert read["_regions"] == {"awb_number": [100, 44, 400, 71]}  # 1000x890 image, 0-1000 grid
    part = fake.body()["messages"][1]["content"][1]
    assert part["type"] == "image_url" and part["image_url"]["url"].startswith("data:image/png;base64,")


def test_truth_files_match_the_field_schema():
    for folder in dossier_dirs():
        for document, fields in DOCUMENT_FIELDS.items():
            truth = json.loads((folder / "documents" / f"{document}.truth.json").read_text())
            values = {k: v["value"] for k, v in truth["fields"].items()}
            assert set(values) == set(fields), (folder.name, document)
            assert coerce_document(document, values) == values, (folder.name, document)


SAM_STREAM = "\n".join([
    'data: {"type": "response.created"}',
    'data: {"type": "response.output_text.delta", "delta": "<0f>0<|box;x1=30;y1=40;x2=300;y2=120;w=900;h=650;c=0.9|>"}',
    'data: {"type": "response.output_text.delta", "delta": "<|mask;x=0;y=0;data=80,270,~abc|>"}',
    'data: {"type": "response.completed", "response": {"usage": {"input_tokens": 7, "output_tokens": 3}}}',
    "",
])


def test_segment_crate_uses_sam_then_reads_crops(keys, monkeypatch):
    folder = dossier_dirs()[0]
    image = folder / "photos" / "crate_01.png"
    fake = Transport(SAM_STREAM, SAM_STREAM, SAM_STREAM,
                     completion(content='{"live_animals": true}'),
                     completion(content='{"direction": "down"}'),
                     completion(content='{"awb_number": "AWB 000-12345675"}'))
    monkeypatch.setattr(models, "_send", fake)
    features = models.segment_crate_image(image)
    sam = [json.loads(r.data) for r in fake.requests[:3]]
    assert all(r.full_url == "https://api.meta.ai/v1/responses" for r in fake.requests[:3])
    assert [s["input"][0]["content"][0]["text"] for s in sam] == list(models.SAM_CONCEPTS.values())
    assert sam[0]["model"] == "sam-3.1" and sam[0]["stream"] is True
    assert sam[0]["input"][0]["content"][1]["type"] == "input_image"
    assert features == {"live_animals_label": {"present": True, "bbox": [30, 40, 300, 120]},
                        "orientation_arrows": {"present": True, "direction": "down", "bbox": [30, 40, 300, 120]},
                        "awb_number": {"value": "000-12345675", "bbox": [30, 40, 300, 120]}}


def test_sam_finding_nothing_means_absent(keys, monkeypatch):
    folder = dossier_dirs()[0]
    empty = 'data: {"type": "response.completed", "response": {}}\n'
    fake = Transport(empty, empty, empty)
    monkeypatch.setattr(models, "_send", fake)
    features = models.segment_crate_image(folder / "photos" / "crate_01.png")
    assert features["live_animals_label"]["present"] is False
    assert features["orientation_arrows"] == {"present": False, "direction": None, "bbox": None}
    assert features["awb_number"]["value"] is None and len(fake.requests) == 3


def test_transcribe_sends_multipart_wav(keys, monkeypatch, tmp_path):
    audio = tmp_path / "N1.wav"
    with wave.open(str(audio), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * 1600)
    fake = Transport({"transcript": " Crate opened for a check. ", "turns": []})
    monkeypatch.setattr(models, "_send", fake)
    assert models.transcribe(audio) == "Crate opened for a check."
    request = fake.requests[0]
    assert request.full_url == "https://api.meta.ai/v1/asr/transcribe"
    assert request.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert b'name="request"' in request.data and b'"model": "muse-voice-transcribe-1.0"' in request.data
    assert b'name="audio"; filename="audio.wav"' in request.data and b"RIFF" in request.data


def test_transcribe_refuses_unconvertible_audio(keys, monkeypatch, tmp_path):
    audio = tmp_path / "N1.m4a"
    audio.write_bytes(b"not audio")
    monkeypatch.setattr(models.shutil, "which", lambda name: None)
    with pytest.raises(models.ModelError, match="16 kHz mono WAV"):
        models.transcribe(audio)
