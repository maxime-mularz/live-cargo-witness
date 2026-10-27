"""Adapters to Meta's models, written from the providers' public documentation (Oct 27, 2026).

Not yet run against the live services from this repository: validate with
``python new/scripts/test_ca02.py`` before relying on them. Standard library only (urllib),
so the request on the wire is exactly what is written here.

- ``chat``: Muse Spark Open on Baseten, OpenAI-compatible Chat Completions with function tools
  (dev.meta.ai/docs/muse-spark-open/deploy, /docs/tool-calling).
- ``read_document_image``: Muse Spark Open, image input (/docs/image-understanding).
- ``segment_crate_image``: SAM 3.1 on the Meta Model API ``/v1/responses`` finds the label, arrows
  and plate (/docs/sam/segmenting, /docs/sam/reading-segmentation); Muse Spark Open reads the crops.
- ``transcribe``: Muse Voice Transcribe, ``/v1/asr/transcribe`` (/docs/speech-to-text).
- ``write_record_text``: Muse Spark, Meta Model API Chat Completions (/docs/protocols/chat-completions).

Configuration (environment, see ``.env.example``; keys are never printed — errors go through
``lcw.env.redact``):
- ``BASETEN_API_KEY``; ``LCW_OPEN_BASE_URL`` (default ``https://inference.baseten.co/v1``);
  ``LCW_OPEN_MODEL`` (default ``meta-models/muse-spark-open-1026``, the hackathon id).
- ``META_MODEL_API_KEY`` (or ``MODEL_API_KEY``, the name used in Meta's docs); ``LCW_META_BASE_URL``
  (default ``https://api.meta.ai/v1``); ``LCW_SPARK_MODEL`` (default ``muse-spark-1.3``).
- ``LCW_ORCHESTRATOR``: ``open`` (default, Muse Spark Open) or ``spark`` (fallback if CA-02
  fails: Muse Spark on the Meta Model API orchestrates, Spark Open keeps document reading).
- ``LCW_REASONING_EFFORT``: optional, sent as ``reasoning_effort`` when set.

While the Meta account runs on free credits, prompts may be used for product improvement:
never send real client data, only the fictitious bench.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import mimetypes
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

from .env import redact
from .jsonutil import final_json
from .schema import AWB_RE, DOCUMENT_FIELDS, coerce_document

TIMEOUT_S = 180
RETRIES = 4                      # on 429 / 5xx / network errors, with exponential backoff
# SAM 3.1 concept prompts (short noun phrases, one per request), tried in order until a box checks out.
SAM_CONCEPTS = {
    "live_animals_label": ["orange label", "live animals label", "sign"],
    "orientation_arrows": ["arrow"],
    "awb_number": ["number plate", "white plate", "white sign"],
}
MAX_BOXES = 3                    # boxes read per concept, best confidence first
USAGE: list[dict] = []           # one entry per model call: model, tokens, seconds (read by the agent)


class ModelError(RuntimeError):
    """A provider call failed. The message never contains a key."""


# ---------------------------------------------------------------------- configuration

@dataclass(frozen=True)
class Endpoint:
    base_url: str
    model: str
    key_names: tuple[str, ...]
    label: str

    def key(self) -> str:
        for name in self.key_names:
            if os.environ.get(name):
                return os.environ[name]
        raise ModelError(f"no API key for {self.label}: set {' or '.join(self.key_names)} in .env")


def open_endpoint() -> Endpoint:
    return Endpoint(os.environ.get("LCW_OPEN_BASE_URL", "https://inference.baseten.co/v1").rstrip("/"),
                    os.environ.get("LCW_OPEN_MODEL", "meta-models/muse-spark-open-1026"),
                    ("BASETEN_API_KEY",), "Muse Spark Open")


def meta_endpoint(model: str | None = None) -> Endpoint:
    return Endpoint(os.environ.get("LCW_META_BASE_URL", "https://api.meta.ai/v1").rstrip("/"),
                    model or os.environ.get("LCW_SPARK_MODEL", "muse-spark-1.3"),
                    ("META_MODEL_API_KEY", "MODEL_API_KEY"), "Meta Model API")


def orchestrator() -> Endpoint:
    choice = os.environ.get("LCW_ORCHESTRATOR", "open").lower()
    if choice not in ("open", "spark"):
        raise ModelError("LCW_ORCHESTRATOR must be 'open' or 'spark'")
    return open_endpoint() if choice == "open" else meta_endpoint()


def orchestrator_name() -> str:
    return "Muse Spark Open" if os.environ.get("LCW_ORCHESTRATOR", "open").lower() == "open" else "Muse Spark"


# ---------------------------------------------------------------------- HTTP

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would resend the Authorization header to the new host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)


def _send(request: urllib.request.Request):
    """The only function that touches the network (replaced in tests)."""
    return _OPENER.open(request, timeout=TIMEOUT_S)


def _request(endpoint: Endpoint, path: str, body: bytes, content_type: str, accept: str = "application/json"):
    """POST with retries. Returns ``(response, attempts)``; a call that fails for good is
    recorded in ``USAGE`` before ``ModelError`` is raised."""
    url = f"{endpoint.base_url}{path}"
    if not url.startswith("https://"):
        raise ModelError(f"{endpoint.label}: refusing to send the API key to a non-HTTPS URL")
    headers = {"Authorization": f"Bearer {endpoint.key()}", "Content-Type": content_type, "Accept": accept}
    last = None
    for attempt in range(RETRIES + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            return _send(request), attempt + 1
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:500] if error.fp else ""
            last = ModelError(redact(f"{endpoint.label}: HTTP {error.code} on {path}: {detail}"))
            if error.code not in (408, 409, 429) and error.code < 500:
                USAGE.append({"model": endpoint.model, "failed": True, "attempts": attempt + 1})
                raise last from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = ModelError(redact(f"{endpoint.label}: network error on {path}: {error}"))
        if attempt < RETRIES:
            time.sleep(min(30.0, 2 ** attempt) * (0.5 + random.random()))
    USAGE.append({"model": endpoint.model, "failed": True, "attempts": RETRIES + 1})
    raise last


def _json_body(endpoint: Endpoint, response) -> dict:
    raw = response.read().decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ModelError(redact(f"{endpoint.label}: response is not JSON: {raw[:200]}")) from None
    if not isinstance(data, dict):
        raise ModelError(redact(f"{endpoint.label}: unexpected response {raw[:200]}"))
    return data


def _post_json(endpoint: Endpoint, path: str, payload: dict) -> dict:
    started = time.monotonic()
    response, attempts = _request(endpoint, path, json.dumps(payload).encode(), "application/json")
    with response:
        data = _json_body(endpoint, response)
    _note_usage(endpoint, data.get("usage"), time.monotonic() - started, attempts)
    return data


def _note_usage(endpoint: Endpoint, usage, seconds: float | None, attempts: int = 1) -> None:
    usage = usage if isinstance(usage, dict) else {}
    USAGE.append({"model": endpoint.model,
                  "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
                  "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
                  "seconds": None if seconds is None else round(seconds, 2), "attempts": attempts})


def _message(endpoint: Endpoint, data: dict) -> dict:
    """``choices[0].message`` of a Chat Completions response, or a clear error."""
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        message = None
    if not isinstance(message, dict):
        raise ModelError(redact(f"{endpoint.label}: unexpected response {json.dumps(data)[:300]}"))
    return message


# ---------------------------------------------------------------------- chat (orchestration)

def _to_provider_messages(messages: list[dict]) -> list[dict]:
    converted = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            converted.append({"role": "tool", "tool_call_id": message.get("tool_call_id") or "",
                              "content": message.get("content") or ""})
        elif role == "assistant" and message.get("tool_calls"):
            converted.append({"role": "assistant", "content": message.get("content"),
                              "tool_calls": [{"id": call.get("id") or "", "type": "function",
                                              "function": {"name": call.get("name") or "",
                                                           "arguments": _replayed(call.get("arguments"))}}
                                             for call in message["tool_calls"]]})
        else:
            converted.append({"role": role, "content": message.get("content") or ""})
    return converted


def _replayed(arguments) -> str:
    """Arguments as replayed to the provider: the JSON the model sent, or "{}" when it was not
    valid JSON (some servers re-parse replayed arguments and would reject every later turn)."""
    if isinstance(arguments, dict):
        return json.dumps(arguments)
    if isinstance(arguments, str):
        try:
            json.loads(arguments)
            return arguments
        except json.JSONDecodeError:
            return "{}"
    return "{}"


def _from_provider_message(message: dict) -> dict:
    calls = []
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            # left as a string if it is not JSON: the agent reports it to the model as a tool error
            with contextlib.suppress(json.JSONDecodeError):
                arguments = json.loads(arguments) if arguments.strip() else {}
        # One id per call, given here, so the replayed call and its tool result always match.
        call_id = call.get("id")
        if not isinstance(call_id, str) or not call_id:
            call_id = f"call_{uuid.uuid4().hex[:12]}"
        calls.append({"id": call_id, "name": function.get("name"), "arguments": arguments})
    content = message.get("content")
    if isinstance(content, list):  # content parts
        content = "".join(part.get("text") or "" for part in content if isinstance(part, dict))
    elif content is not None and not isinstance(content, str):
        content = None
    return {"content": content, "tool_calls": calls}


def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Muse Spark Open (orchestration), used by ``lcw.agent``.

    ``messages``: ``{"role": "system"|"user"|"assistant"|"tool", "content": str|None}``; assistant
    messages may carry ``tool_calls`` (same shape as returned below); tool messages carry
    ``tool_call_id`` and ``name``. ``tools``: ``lcw.tools.TOOL_SCHEMAS`` entries
    ``{"name", "description", "parameters": <JSON schema>}``.

    Return, normalised whatever the provider format:
    ``{"content": str | None, "tool_calls": [{"id": str, "name": str, "arguments": dict}]}``
    (``arguments`` parsed from JSON when possible; an empty list when the model answers directly).
    """
    endpoint = orchestrator()
    payload = {"model": endpoint.model, "messages": _to_provider_messages(messages)}
    if tools:
        payload["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                              "parameters": t["parameters"]}} for t in tools]
        payload["tool_choice"] = "auto"
    if os.environ.get("LCW_REASONING_EFFORT"):
        payload["reasoning_effort"] = os.environ["LCW_REASONING_EFFORT"]
    data = _post_json(endpoint, "/chat/completions", payload)
    return _from_provider_message(_message(endpoint, data))


# ---------------------------------------------------------------------- images

def _data_url(image: Path | bytes, mime: str | None = None) -> str:
    if isinstance(image, Path):
        mime = mime or mimetypes.guess_type(image.name)[0] or "image/png"
        image = image.read_bytes()
    return f"data:{mime or 'image/png'};base64,{base64.b64encode(image).decode()}"


def _vision_json(endpoint: Endpoint, image: Path | bytes, instruction: str, keys: tuple[str, ...]) -> dict:
    payload = {"model": endpoint.model, "messages": [
        {"role": "system", "content": "You read fictitious test documents and images. Answer with one JSON "
                                      "object only. Use null for anything you cannot read; never guess."},
        {"role": "user", "content": [{"type": "text", "text": instruction},
                                     {"type": "image_url", "image_url": {"url": _data_url(image)}}]}]}
    data = _post_json(endpoint, "/chat/completions", payload)
    text = _from_provider_message(_message(endpoint, data))["content"]
    found = final_json(text, keys)
    if found is None:
        raise ModelError(f"{endpoint.label}: the answer contains no JSON object")
    return found


def read_document_image(image: Path, document: str) -> dict:
    """Muse Spark Open (vision). Return ``{field_name: value}`` for the fields of ``document``
    (``awb``, ``certification`` or ``loading_list``, see ``lcw.schema``), plus
    ``_regions: {field: [x0, y0, x1, y1]}`` in image pixels when the model locates them."""
    fields = DOCUMENT_FIELDS[document]
    listing = "\n".join(f'- "{name}": {description}' for name, (_, description) in fields.items())
    instruction = (f"This image is a shipping document ({document.replace('_', ' ')}). Return a JSON object "
                   f'{{"fields": {{...}}, "boxes": {{...}}}}. "fields" has exactly these keys:\n{listing}\n'
                   'Copy values as printed. "boxes" gives, for each field you read, its box '
                   "[x0, y0, x1, y1] on a 0-1000 grid (0,0 top-left, 1000,1000 bottom-right).")
    answer = _vision_json(open_endpoint(), Path(image), instruction, ("fields",))
    read = coerce_document(document, answer.get("fields") if isinstance(answer.get("fields"), dict) else answer)
    read["_regions"] = _to_pixels(answer.get("boxes"), Path(image))
    return read


def _to_pixels(boxes, image: Path) -> dict:
    if not isinstance(boxes, dict):
        return {}
    from PIL import Image

    with Image.open(image) as picture:
        width, height = picture.size
    regions = {}
    for name, box in boxes.items():
        if isinstance(box, list) and len(box) == 4 and all(isinstance(v, int | float) for v in box):
            x0, y0, x1, y1 = (max(0, min(1000, v)) for v in box)
            regions[name] = [round(x0 * width / 1000), round(y0 * height / 1000),
                             round(x1 * width / 1000), round(y1 * height / 1000)]
    return regions


# ---------------------------------------------------------------------- SAM 3.1

BOX_TOKEN = re.compile(r"<\|box;([^|]*)\|>")


def parse_sam_output(text: str) -> list[dict]:
    """Boxes from SAM 3.1's special-token output (``<0f>0<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>
    <|mask;...|>,1<|box;...|>...``). Masks are not needed here and are ignored."""
    boxes = []
    for match in BOX_TOKEN.finditer(text or ""):
        values = dict(part.split("=", 1) for part in match.group(1).split(";") if "=" in part)
        try:
            box = {"bbox": [int(float(values[k])) for k in ("x1", "y1", "x2", "y2")]}
            if "c" in values:
                box["confidence"] = float(values["c"])
        except (KeyError, ValueError):
            continue
        boxes.append(box)
    return boxes


def _read_sse_text(response, attempts: int = 1, started: float | None = None) -> str:
    """Accumulate ``response.output_text.delta`` events until ``response.completed``. A stream
    that ends any other way is an error: partial output would read as "nothing found"."""
    parts, completed = [], False
    for raw in response:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "response.output_text.delta":
            parts.append(event.get("delta") or "")
        elif kind == "response.completed":
            completed = True
            response_body = event.get("response") if isinstance(event.get("response"), dict) else {}
            seconds = None if started is None else time.monotonic() - started
            _note_usage(Endpoint("", "sam-3.1", (), "SAM 3.1"), response_body.get("usage"), seconds, attempts)
            break
        elif kind in ("error", "response.failed", "response.incomplete"):
            USAGE.append({"model": "sam-3.1", "failed": True, "attempts": attempts})
            raise ModelError(redact(f"SAM 3.1: {json.dumps(event)[:300]}"))
    if not completed:
        USAGE.append({"model": "sam-3.1", "failed": True, "attempts": attempts})
        raise ModelError("SAM 3.1: the stream ended before response.completed (partial result not used)")
    return "".join(parts)


def sam_boxes(image: Path | bytes, concept: str) -> list[dict]:
    """SAM 3.1 concept segmentation: every box matching ``concept`` (a short noun phrase)."""
    endpoint = meta_endpoint("sam-3.1")
    payload = {"model": "sam-3.1", "stream": True, "metadata": {"include_confidence": "true"},
               "input": [{"type": "message", "role": "user", "content": [
                   {"type": "input_text", "text": concept},
                   {"type": "input_image", "image_url": _data_url(image)}]}]}
    started = time.monotonic()
    response, attempts = _request(endpoint, "/responses", json.dumps(payload).encode(), "application/json",
                                  accept="text/event-stream")
    with response:
        return parse_sam_output(_read_sse_text(response, attempts, started))


def _crop(image: Path, box: list[int], margin: int = 12) -> bytes:
    from PIL import Image

    with Image.open(image) as picture:
        x0, y0, x1, y1 = box
        area = picture.crop((max(0, x0 - margin), max(0, y0 - margin),
                             min(picture.width, x1 + margin), min(picture.height, y1 + margin)))
        buffer = io.BytesIO()
        area.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()


def _crate_feature(image: Path, feature: str) -> dict:
    """Find and read one crate feature.

    1. SAM 3.1 looks for it with each concept prompt in turn; each box it returns (best first)
       is cropped and read by Muse Spark Open. The first box that checks out is kept.
    2. If no box checks out, Muse Spark Open looks at the whole photo. Only if it also finds
       nothing is the feature declared absent: absence needs two models to agree, so a concept
       prompt SAM does not match never becomes a deviation in the record.
    3. If the whole-photo answer is null, the feature is ``"readable": False`` (rule unreadable).
    ``found_by`` says which model located the feature, for the journal."""
    crop_question, crop_key = CROP_QUESTIONS[feature]
    for concept in SAM_CONCEPTS[feature]:
        boxes = sorted(sam_boxes(image, concept), key=lambda b: -b.get("confidence", 0))[:MAX_BOXES]
        for box in boxes:
            value = _vision_json(open_endpoint(), _crop(image, box["bbox"]), crop_question, (crop_key,)).get(crop_key)
            reading = _feature_reading(feature, value)
            if reading is not None and reading is not ABSENT:
                return {**reading, "bbox": box["bbox"], "found_by": f"SAM 3.1 ({concept}) + Muse Spark Open"}
    question, key = PHOTO_QUESTIONS[feature]
    value = _vision_json(open_endpoint(), image, question, (key,)).get(key)
    reading = _feature_reading(feature, value)
    if reading is ABSENT:
        return {**EMPTY_FEATURE[feature], "found_by": "nothing found by SAM 3.1 nor Muse Spark Open"}
    if reading is None:
        return {**EMPTY_FEATURE[feature], "present": None, "readable": False,
                "found_by": "Muse Spark Open could not tell (whole photo)"}
    return {**reading, "bbox": None, "found_by": "Muse Spark Open (whole photo; SAM 3.1 found no box)"}


ABSENT = object()
EMPTY_FEATURE = {"live_animals_label": {"present": False, "bbox": None},
                 "orientation_arrows": {"present": False, "direction": None, "bbox": None},
                 "awb_number": {"value": None, "bbox": None}}
CROP_QUESTIONS = {
    "live_animals_label": ('Does this crop show a label reading "LIVE ANIMALS"? '
                           'Return {"live_animals": true|false|null}.', "live_animals"),
    "orientation_arrows": ('These may be orientation arrows on a crate. Return {"direction": "up"|"down"|"none"|null}.',
                           "direction"),
    "awb_number": ('Read the air waybill number on this plate. Return {"awb_number": "ddd-dddddddd"|"none"|null}.',
                   "awb_number"),
}
PHOTO_QUESTIONS = {
    "live_animals_label": ('Is there a label reading "LIVE ANIMALS" on this crate? '
                           'Return {"live_animals_label": true|false|null} (null if you cannot tell).',
                           "live_animals_label"),
    "orientation_arrows": ('Are there orientation arrows on this crate, and which way do they point? '
                           'Return {"orientation_arrows": "up"|"down"|"none"|null} (null if you cannot tell).',
                           "orientation_arrows"),
    "awb_number": ('Is an air waybill number written on this crate? Return {"awb_number": "ddd-dddddddd"} '
                   'if you can read it, {"awb_number": "none"} if there is none, {"awb_number": null} if you '
                   "cannot tell.", "awb_number"),
}


def _feature_reading(feature: str, value):
    """A model's answer about one feature: a feature dict (without bbox), ABSENT, or None (unknown)."""
    if feature == "live_animals_label":
        if value is True:
            return {"present": True}
        return ABSENT if value is False else None
    if feature == "orientation_arrows":
        if value in ("up", "down"):
            return {"present": True, "direction": value}
        return ABSENT if value == "none" else None
    if isinstance(value, str) and value.strip().lower() == "none":
        return ABSENT
    match = AWB_RE.search(str(value or ""))
    return {"value": match.group()} if match else None


def segment_crate_image(image: Path) -> dict:
    """SAM 3.1 finds the label, the arrows and the number plate; Muse Spark Open reads SAM's
    crops, and checks the whole photo before anything is declared absent. Returns
    ``{"live_animals_label": {"present", "bbox"}, "orientation_arrows": {"present", "direction":
    "up"|"down"|None, "bbox"}, "awb_number": {"value", "bbox"}}``, each with ``found_by`` and,
    when it could not be read, ``"readable": False``."""
    image = Path(image)
    return {feature: _crate_feature(image, feature) for feature in SAM_CONCEPTS}


# ---------------------------------------------------------------------- Voice Transcribe

def _wav_ok(path: Path) -> bool:
    try:
        with wave.open(str(path)) as audio:
            return audio.getnchannels() == 1 and audio.getsampwidth() == 2 and audio.getframerate() in (16000, 24000)
    except (wave.Error, EOFError, OSError):
        return False


def _as_wav(audio: Path) -> bytes:
    """Mono 16-bit PCM WAV at 16 kHz, as the API requires (ffmpeg converts other formats)."""
    if _wav_ok(audio):
        return audio.read_bytes()
    if shutil.which("ffmpeg") is None:
        raise ModelError(f"{audio.name}: convert to 16 kHz mono WAV first (ffmpeg not found)")
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "audio.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(audio), "-ac", "1", "-ar", "16000",
                        "-sample_fmt", "s16", str(target)], check=True)
        return target.read_bytes()


def _multipart(parts: list[tuple[str, str | None, str, bytes]]) -> tuple[bytes, str]:
    boundary = f"lcw-{uuid.uuid4().hex}"
    body = io.BytesIO()
    for name, filename, content_type, data in parts:
        disposition = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        body.write(f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
                   f"Content-Type: {content_type}\r\n\r\n".encode())
        body.write(data)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


def transcribe(audio: Path) -> str:
    """Muse Voice Transcribe (batch). Return the transcript of a recorded note or answer."""
    endpoint = meta_endpoint("muse-voice-transcribe-1.0")
    settings = {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV",
                "languageBias": ["English", "French"]}
    body, content_type = _multipart([("request", None, "application/json", json.dumps(settings).encode()),
                                     ("audio", "audio.wav", "audio/wav", _as_wav(Path(audio)))])
    started = time.monotonic()
    response, attempts = _request(endpoint, "/asr/transcribe", body, content_type)
    with response:
        data = _json_body(endpoint, response)
    _note_usage(endpoint, None, time.monotonic() - started, attempts)
    transcript = data.get("transcript")
    if not isinstance(transcript, str):
        raise ModelError("Muse Voice Transcribe: no transcript in the response")
    return transcript.strip()


# ---------------------------------------------------------------------- Muse Spark (record text)

def write_record_text(facts: dict, language: str = "en") -> str:
    """Muse Spark. Turn verified facts into readable record text. Every sentence it returns goes
    back through ``lcw.verifier`` before it can enter the record."""
    endpoint = meta_endpoint()
    payload = {"model": endpoint.model, "messages": [
        {"role": "system", "content": "Write short factual sentences for a shared handover record. Use only the "
                                      "facts given; copy every number, time and date exactly. Never comment on "
                                      "the animals' condition."},
        {"role": "user", "content": f"Language: {language}. Facts (JSON):\n{json.dumps(facts, ensure_ascii=False)}"}]}
    data = _post_json(endpoint, "/chat/completions", payload)
    return (_from_provider_message(_message(endpoint, data))["content"] or "").strip()
