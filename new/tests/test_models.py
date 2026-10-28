"""Offline tests of the model adapters: a fake transport stands in for the network and checks
that requests follow the providers' documented formats. Nothing here calls a real service."""
import io
import json
import urllib.error
import urllib.request
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
    assert body["model"] == "meta-models/muse-spark-open" and body["tool_choice"] == "auto"
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
    monkeypatch.delenv("LCW_ORCHESTRATOR", raising=False)
    monkeypatch.setattr(models, "_send", Transport())  # any network call would fail the test
    with pytest.raises(models.ModelError, match="BASETEN_API_KEY"):
        models.chat([{"role": "user", "content": "u"}])


def test_read_document_types_and_regions(keys, monkeypatch):
    folder = dossier_dirs()[0]
    image = folder / "documents" / "awb.png"
    answer = {"fields": {"awb_number": "AWB 000-12345675", "head_count": "12", "handling_codes": "AVI",
                         "temperature_range_c": "2-8 °C", "route": "ORI → STO → DES",
                         "flights": "LCW 101 / LCW 202", "consignee": {"value": "copied object"},
                         "nature_of_goods": "Live animals — heifers"},
              "boxes": {"awb_number": [100, 50, 400, 80], "head_count": "nowhere"}}
    fake = Transport(completion(content="Here it is:\n```json\n" + json.dumps(answer) + "\n```"))
    monkeypatch.setattr(models, "_send", fake)
    read = models.read_document_image(image, "awb")
    assert read["awb_number"] == "000-12345675" and read["head_count"] == 12
    assert read["handling_codes"] == ["AVI"] and read["temperature_range_c"] == [2.0, 8.0]
    assert read["route"] == ["ORI", "STO", "DES"] and read["flights"] == ["LCW101", "LCW202"]
    assert read["shipper"] is None and read["consignee"] is None  # not read -> None, never guessed
    assert set(read) == set(DOCUMENT_FIELDS["awb"]) | {"_regions"}
    assert read["_regions"] == {"awb_number": [100, 44, 400, 71]}  # 1000x890 image, 0-1000 grid
    part = fake.body()["messages"][1]["content"][1]
    assert part["type"] == "image_url" and part["image_url"]["url"].startswith("data:image/png;base64,")


def test_an_empty_document_reading_is_asked_once_more(keys, monkeypatch):
    # Seen live (DEV-11, night run 2026-10-27): a legible loading list read as all-null 1 time in 8.
    image = dossier_dirs()[0] / "documents" / "loading_list.png"
    empty = {"fields": {"awb_number": None, "head_count": None, "crates": None}, "boxes": {}}
    full = {"fields": {"awb_number": "000-1", "head_count": 9, "crates": None}, "boxes": {}}
    fake = Transport(completion(content=json.dumps(empty)), completion(content=json.dumps(full)))
    monkeypatch.setattr(models, "_send", fake)
    read = models.read_document_image(image, "loading_list")
    assert read["head_count"] == 9 and len(fake.requests) == 2


def test_a_document_empty_twice_stays_unread(keys, monkeypatch):
    image = dossier_dirs()[0] / "documents" / "loading_list.png"
    empty = {"fields": {"awb_number": None, "head_count": None, "crates": None}, "boxes": {}}
    fake = Transport(*(completion(content=json.dumps(empty)) for _ in range(2)))
    monkeypatch.setattr(models, "_send", fake)
    read = models.read_document_image(image, "loading_list")
    assert read["head_count"] is None and read["awb_number"] is None  # never guessed
    assert len(fake.requests) == 2  # one more try, not a loop


def test_truth_files_match_the_field_schema():
    for folder in dossier_dirs():
        for document, fields in DOCUMENT_FIELDS.items():
            truth = json.loads((folder / "documents" / f"{document}.truth.json").read_text())
            values = {k: v["value"] for k, v in truth["fields"].items()}
            assert set(values) == set(fields), (folder.name, document)
            assert coerce_document(document, values) == values, (folder.name, document)


def sam_stream(box: str) -> str:
    return "\n".join([
        'data: {"type": "response.created"}',
        'data: {"type": "response.output_text.delta", "delta": "<0f>0<|box;' + box + ';w=900;h=650;c=0.9|>"}',
        'data: {"type": "response.output_text.delta", "delta": "<|mask;x=0;y=0;data=80,270,~abc|>"}',
        'data: {"type": "response.completed", "response": {"usage": {"input_tokens": 7, "output_tokens": 3}}}',
        "",
    ])


LABEL, ARROWS, PLATE = "x1=150;y1=170;x2=460;y2=280", "x1=560;y1=180;x2=730;y2=330", "x1=145;y1=390;x2=590;y2=475"


EMPTY = 'data: {"type": "response.completed", "response": {}}\n'


def sam_concepts(fake):
    return [json.loads(r.data)["input"][0]["content"][0]["text"] for r in fake.requests
            if r.full_url.endswith("/responses")]


def test_segment_crate_uses_sam_then_reads_crops(keys, monkeypatch):
    from PIL import Image
    folder = dossier_dirs()[0]
    image = folder / "photos" / "crate_01.png"
    fake = Transport(sam_stream(LABEL), completion(content='{"live_animals": true}'),
                     sam_stream(ARROWS), completion(content='{"direction": "down"}'),
                     sam_stream(PLATE), completion(content='{"awb_number": "AWB 000-12345675"}'))
    monkeypatch.setattr(models, "_send", fake)
    features = models.segment_crate_image(image)
    sam = [json.loads(r.data) for r in fake.requests if r.full_url == "https://api.meta.ai/v1/responses"]
    assert len(sam) == 3 and sam[0]["model"] == "sam-3.1" and sam[0]["stream"] is True
    assert sam_concepts(fake) == [c[0] for c in models.SAM_CONCEPTS.values()]
    assert sam[0]["input"][0]["content"][1]["type"] == "input_image"
    assert {k: {f: v for f, v in feature.items() if f != "found_by"} for k, feature in features.items()} == {
        "live_animals_label": {"present": True, "bbox": [150, 170, 460, 280]},
        "orientation_arrows": {"present": True, "direction": "down", "bbox": [560, 180, 730, 330]},
        "awb_number": {"value": "000-12345675", "bbox": [145, 390, 590, 475]}}
    assert features["awb_number"]["found_by"].startswith("SAM 3.1 (number plate)")
    # the vision model receives SAM's crop of the plate (with a 12 px margin), not the whole photo
    url = json.loads(fake.requests[5].data)["messages"][1]["content"][1]["image_url"]["url"]
    crop = Image.open(io.BytesIO(__import__("base64").b64decode(url.split(",", 1)[1])))
    assert crop.size == (590 - 145 + 24, 475 - 390 + 24)


def test_rejected_box_moves_on_to_the_next_concept(keys, monkeypatch):
    folder = dossier_dirs()[0]
    fake = Transport(sam_stream(PLATE), completion(content='{"live_animals": false}'),  # "orange label" hit the plate
                     sam_stream(LABEL), completion(content='{"live_animals": true}'))   # "live animals label"
    monkeypatch.setattr(models, "_send", fake)
    label = models._crate_feature(folder / "photos" / "crate_01.png", "live_animals_label")
    assert label["present"] is True and label["bbox"] == [150, 170, 460, 280]
    assert sam_concepts(fake) == models.SAM_CONCEPTS["live_animals_label"][:2]


def test_sam_miss_is_checked_on_the_whole_photo(keys, monkeypatch):
    """The first live run: SAM found no label box, the label was there. Never a violation."""
    folder = dossier_dirs()[0]
    concepts = models.SAM_CONCEPTS["live_animals_label"]
    fake = Transport(*[EMPTY] * len(concepts), completion(content='{"live_animals_label": true}'))
    monkeypatch.setattr(models, "_send", fake)
    label = models._crate_feature(folder / "photos" / "crate_01.png", "live_animals_label")
    assert label["present"] is True and label["bbox"] is None and "whole photo" in label["found_by"]
    last = json.loads(fake.requests[-1].data)["messages"][1]["content"][1]["image_url"]["url"]
    assert len(last) > 10000  # the whole photo, not a crop


def test_unread_crops_are_unreadable_not_violations(keys, monkeypatch):
    from lcw.predeparture import evaluate_rule
    from lcw.rules import load_rules
    folder = dossier_dirs()[0]
    replies = []
    for feature, (answer_key, box) in {"live_animals_label": ("live_animals", LABEL),
                                       "orientation_arrows": ("direction", ARROWS),
                                       "awb_number": ("awb_number", PLATE)}.items():
        for _ in models.SAM_CONCEPTS[feature]:
            replies += [sam_stream(box), completion(content=json.dumps({answer_key: None}))]
        replies.append(completion(content=json.dumps({models.PHOTO_QUESTIONS[feature][1]: None})))
    monkeypatch.setattr(models, "_send", Transport(*replies))
    features = models.segment_crate_image(folder / "photos" / "crate_01.png")
    assert all(feature["readable"] is False for feature in features.values())
    rules = load_rules()
    observations = {"documents": {"awb": {"awb_number": "000-12345675"}}, "crates": {"crate_01": features},
                    "expected_crates": ["crate_01"]}
    for rule_id in ("R04", "R05", "R06"):
        assert evaluate_rule(rules[rule_id], observations)["outcome"] == "unreadable", rule_id


@pytest.mark.parametrize("body", [
    'data: {"type": "response.output_text.delta", "delta": "<0f>"}\n',            # cut before completed
    '{"error": {"message": "overloaded"}}',                                        # JSON body, no stream
    'data: {"type": "response.incomplete", "response": {}}\n',
    "",
])
def test_sam_stream_that_does_not_complete_is_an_error(keys, monkeypatch, body):
    monkeypatch.setattr(models, "_send", Transport(body))
    with pytest.raises(models.ModelError):
        models.sam_boxes(b"png", "arrow")


def test_absent_only_when_both_models_agree(keys, monkeypatch):
    folder = dossier_dirs()[0]
    replies = []
    for feature in models.SAM_CONCEPTS:
        replies += [EMPTY] * len(models.SAM_CONCEPTS[feature])
        none = {"live_animals_label": False, "orientation_arrows": "none", "awb_number": "none"}[feature]
        replies.append(completion(content=json.dumps({models.PHOTO_QUESTIONS[feature][1]: none})))
    fake = Transport(*replies)
    monkeypatch.setattr(models, "_send", fake)
    features = models.segment_crate_image(folder / "photos" / "crate_01.png")
    assert {k: {f: v for f, v in feature.items() if f != "found_by"} for k, feature in features.items()} == {
        "live_animals_label": {"present": False, "bbox": None},
        "orientation_arrows": {"present": False, "direction": None, "bbox": None},
        "awb_number": {"value": None, "bbox": None}}
    assert all("nothing found" in feature["found_by"] for feature in features.values())
    assert not fake.replies


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


def test_tool_calls_without_id_get_one_id_used_on_both_sides(keys, monkeypatch):
    fake = Transport(completion(tool_calls=[{"type": "function", "function": {"name": "lookup_rule",
                                                                             "arguments": "{oops"}}]))
    monkeypatch.setattr(models, "_send", fake)
    call = models.chat([{"role": "user", "content": "u"}])["tool_calls"][0]
    assert call["id"].startswith("call_")
    replay = models._to_provider_messages([{"role": "assistant", "content": None, "tool_calls": [call]},
                                           {"role": "tool", "tool_call_id": call["id"], "content": "{}"}])
    assert replay[0]["tool_calls"][0]["id"] == replay[1]["tool_call_id"] == call["id"]
    assert replay[0]["tool_calls"][0]["function"]["arguments"] == "{}"  # malformed JSON never replayed


def test_key_never_leaves_over_http_or_a_redirect(keys, monkeypatch):
    monkeypatch.setenv("LCW_OPEN_BASE_URL", "http://inference.example/v1")
    monkeypatch.setattr(models, "_send", Transport())
    with pytest.raises(models.ModelError, match="non-HTTPS"):
        models.chat([{"role": "user", "content": "u"}])
    request = urllib.request.Request("https://api.meta.ai/v1/x", headers={"Authorization": "Bearer k"})
    with pytest.raises(urllib.error.HTTPError):
        models._NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://elsewhere.example/")


@pytest.mark.parametrize("reply", [
    {"error": {"message": "bad"}}, {"choices": []}, {"choices": [{"message": None}]}, "not json", "[1, 2]",
])
def test_unexpected_provider_responses_raise_model_errors(keys, monkeypatch, reply):
    monkeypatch.setattr(models, "_send", Transport(reply))
    with pytest.raises(models.ModelError):
        models.chat([{"role": "user", "content": "u"}])


def test_content_parts_with_null_text_and_bad_confidence():
    message = {"content": [{"type": "text", "text": None}, {"text": "ok"}]}
    assert models._from_provider_message(message)["content"] == "ok"
    assert models.parse_sam_output("<|box;x1=1;y1=2;x2=3;y2=4;c=high|>,1<|box;x1=5;y1=6;x2=7;y2=8|>") == [
        {"bbox": [5, 6, 7, 8]}]


def test_live_mode_refuses_a_dossier_not_marked_synthetic(tmp_path):
    import shutil

    from lcw.dossier import Dossier
    from lcw.tools import Toolset
    folder = tmp_path / "REAL-01"
    shutil.copytree(dossier_dirs()[0], folder)
    record = json.loads((folder / "dossier.json").read_text())
    record["synthetic"] = False
    (folder / "dossier.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="not marked synthetic"):
        Toolset(Dossier(folder), backend="live")
    Toolset(Dossier(folder), backend="offline")  # offline stays possible: nothing is sent


def test_usage_is_counted_per_model_and_cost_is_a_labelled_lower_bound(monkeypatch):
    from lcw.agent import usage_summary
    from lcw.score import cost_metrics
    usage = usage_summary([
        {"model": "open", "prompt_tokens": 1000, "completion_tokens": 100, "attempts": 2},
        {"model": "open", "failed": True, "attempts": 5},
        {"model": "muse-voice-transcribe-1.0", "prompt_tokens": None, "completion_tokens": None},
    ], 12.0)
    assert usage["by_model"]["open"] == {"calls": 2, "failed": 1, "attempts": 7, "prompt_tokens": 1000,
                                         "completion_tokens": 100, "calls_without_tokens": 0}
    assert usage["by_model"]["muse-voice-transcribe-1.0"]["calls_without_tokens"] == 1
    monkeypatch.setenv("LCW_PRICES", json.dumps({"open": [1.0, 10.0]}))
    metrics = cost_metrics([usage, usage])
    assert metrics["CA-12 mean cost per dossier (USD, lower bound)"] == 0.002
    assert metrics["CA-12 models without a price"] == "muse-voice-transcribe-1.0"
