"""Adapters to Meta's models — TO BE WIRED on the machine that holds the API keys.

The signatures below are the contract used by ``lcw.tools`` in ``live`` mode. The bodies raise
``NotImplementedError`` on purpose: the request formats of the Meta Model API, Baseten and Modal
must be taken from each provider's documentation, not guessed. Keys come from the environment
(see ``.env.example``); never hard-code them.

Hackathon notes:
- Muse Spark Open on Baseten: model id ``meta-models/muse-spark-open-1026`` (not the id in the
  public docs). Used for orchestration (tool calling) and for reading document images.
- SAM 3.1: crate segmentation (labels, arrows, AWB plate).
- Muse Voice Transcribe: convoy notes and handler answers.
- Muse Spark (Meta Model API): writing the handover record text in English (French optional).
- While the Meta account runs on free credits, prompts may be used for product improvement:
  never send real client data, only the fictitious bench.
"""

from __future__ import annotations

from pathlib import Path


def read_document_image(image: Path, document: str) -> dict:
    """Muse Spark Open (vision). Return ``{field_name: value}`` for the fields of ``document``
    (``awb``, ``certification`` or ``loading_list``), plus ``_regions: {field: [x0, y0, x1, y1]}``.
    Expected keys per document: see ``documents/*.truth.json`` in any bench dossier."""
    raise NotImplementedError("wire Muse Spark Open (Baseten) here")


def segment_crate_image(image: Path) -> dict:
    """SAM 3.1. Return ``{"live_animals_label": {"present", "bbox"},
    "orientation_arrows": {"present", "direction": "up"|"down"|None, "bbox"},
    "awb_number": {"value", "bbox"}}``. Text on the plate may need Muse Spark Open after SAM."""
    raise NotImplementedError("wire SAM 3.1 (+ text reading) here")


def transcribe(audio: Path) -> str:
    """Muse Voice Transcribe. Return the transcript of a recorded note or answer."""
    raise NotImplementedError("wire Muse Voice Transcribe here")


def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Muse Spark Open (orchestration), used by ``lcw.agent``.

    ``messages``: ``{"role": "system"|"user"|"assistant"|"tool", "content": str|None}``; assistant
    messages may carry ``tool_calls`` (same shape as returned below); tool messages carry
    ``tool_call_id`` and ``name``. ``tools``: ``lcw.tools.TOOL_SCHEMAS`` entries
    ``{"name", "description", "parameters": <JSON schema>}`` — convert them to the provider's
    tool-calling format here.

    Return, normalised whatever the provider format:
    ``{"content": str | None, "tool_calls": [{"id": str, "name": str, "arguments": dict}]}``
    (``arguments`` already parsed from JSON; an empty list when the model answers directly).
    """
    raise NotImplementedError("wire Muse Spark Open tool calling here")


def write_record_text(facts: dict, language: str = "en") -> str:
    """Muse Spark. Turn verified facts into readable record text. Every sentence it returns goes
    back through ``lcw.verifier`` before it can enter the record."""
    raise NotImplementedError("wire Muse Spark (Meta Model API) here")
