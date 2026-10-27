"""Fields the agent reads on each shipping document, with their types (single source).

Used by ``lcw.models.read_document_image`` to ask the model for exactly these fields and to put
its answer in the right types, and by the consistency tests against ``bench/FORMAT.md`` and the
generator's truth files. Type conversion only changes the *format* of what was read ("12" -> 12,
"true" -> True); a value that cannot be converted becomes ``None`` (unreadable), never a guess.
"""

from __future__ import annotations

import re

AWB_RE = re.compile(r"\b\d{3}-\d{8}\b")

# field -> (type, description given to the model)
DOCUMENT_FIELDS: dict[str, dict[str, tuple[str, str]]] = {
    "awb": {
        "awb_number": ("awb", "air waybill number, digits ddd-dddddddd"),
        "shipper": ("str", "shipper name"),
        "consignee": ("str", "consignee name"),
        "route": ("list_str", "airport codes in order"),
        "flights": ("list_str", "flight numbers in order"),
        "date": ("date", "date, YYYY-MM-DD"),
        "nature_of_goods": ("str", "nature and quantity of goods"),
        "head_count": ("int", "number of animals (heads)"),
        "handling_codes": ("list_str", "special handling codes, e.g. AVI"),
        "handling_information": ("str", "handling information text, verbatim"),
        "temperature_range_c": ("range", "temperature range in degrees C as [low, high]"),
    },
    "certification": {
        "awb_number": ("awb", "air waybill number, digits ddd-dddddddd"),
        "species": ("str", "species"),
        "head_count": ("int", "number of animals (heads)"),
        "shipper": ("str", "shipper name"),
        "date": ("date", "date, YYYY-MM-DD"),
        "signed": ("bool", "true if the shipper's signature box contains a signature"),
        "signatory": ("str", "name written next to the signature, or null"),
    },
    "loading_list": {
        "awb_number": ("awb", "air waybill number, digits ddd-dddddddd"),
        "head_count": ("int", "total number of animals"),
        "crates": ("crates", "list of {crate: 'crate_NN', head_count: int}"),
    },
}

DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:[.,]\d+)?", value)
        if match:
            text = match.group().replace(",", ".")
            return float(text) if "." in text else int(text)
    return None


def coerce(kind: str, value):
    """Convert one read value to its declared type, or None if it cannot be read as such."""
    if value is None:
        return None
    if kind == "str":
        return str(value).strip() or None
    if kind == "int":
        number = _number(value)
        return int(number) if number is not None and float(number).is_integer() else None
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        return {"true": True, "yes": True, "false": False, "no": False}.get(text)
    if kind == "awb":
        match = AWB_RE.search(str(value))
        return match.group() if match else None
    if kind == "date":
        match = DATE_RE.search(str(value))
        return match.group() if match else None
    if kind == "list_str":
        if isinstance(value, str):
            value = [part for part in re.split(r"[,;/\s]+", value) if part]
        return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else None
    if kind == "range":
        if isinstance(value, str):
            value = re.findall(r"-?\d+(?:[.,]\d+)?", value)
        if isinstance(value, list) and len(value) == 2:
            low, high = (_number(v) for v in value)
            if low is not None and high is not None:
                return [float(low), float(high)]
        return None
    if kind == "crates":
        if not isinstance(value, list):
            return None
        crates = []
        for item in value:
            if not isinstance(item, dict):
                return None
            count = coerce("int", item.get("head_count"))
            name = re.search(r"\d+", str(item.get("crate", "")))
            if count is None or name is None:
                return None
            crates.append({"crate": f"crate_{int(name.group()):02d}", "head_count": count})
        return crates
    raise ValueError(f"unknown field type {kind!r}")


def coerce_document(document: str, fields: dict) -> dict:
    """Keep the declared fields of ``document``, converted to their types (missing -> None)."""
    return {name: coerce(kind, fields.get(name)) for name, (kind, _) in DOCUMENT_FIELDS[document].items()}
