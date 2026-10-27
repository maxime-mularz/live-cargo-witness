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
        "route": ("list_code", "airport codes in order, as a list"),
        "flights": ("list_flight", "flight numbers in order, as a list"),
        "date": ("date", "date, YYYY-MM-DD"),
        "nature_of_goods": ("str", "nature and quantity of goods"),
        "head_count": ("int", "number of animals (heads)"),
        "handling_codes": ("list_code", "special handling codes as a list, e.g. [\"AVI\"]"),
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
# A "-" is a minus sign only when it does not follow a digit: "2-8" is a range, "-5" a number.
NUMBER_RE = re.compile(r"(?:(?<![\d.,])-)?\d+(?:[.,]\d+)?")
ITEM_PATTERNS = {"list_code": re.compile(r"^[A-Z]{3}$"), "list_flight": re.compile(r"^[A-Z0-9]{2,3}\d{1,4}[A-Z]?$")}
LIST_SEPARATORS = re.compile(r"\s*(?:[,;/|→—–]|->)\s*")


def _numbers(text: str) -> list[float | int]:
    found = []
    for match in NUMBER_RE.finditer(text):
        token = match.group().replace(",", ".")
        found.append(float(token) if "." in token else int(token))
    return found


def _number(value):
    """One number, or None. A string holding several numbers ("2 crates, 24 heads") is
    ambiguous and gives None rather than the first one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        found = _numbers(value)
        return found[0] if len(found) == 1 else None
    return None


def _items(kind: str, value) -> list[str] | None:
    if isinstance(value, str):
        value = [part for part in LIST_SEPARATORS.split(value.strip()) if part]
        if kind == "list_code":  # codes may also be separated by spaces: "AVI PER"
            value = [code for part in value for code in part.split()]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    items = [re.sub(r"\s+", "", v) if kind == "list_flight" else v.strip() for v in value]
    return items if all(ITEM_PATTERNS[kind].match(item) for item in items) else None


def coerce(kind: str, value):
    """Convert one read value to its declared type, or None if it cannot be read as such."""
    if value is None:
        return None
    if kind == "str":
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            return None  # e.g. a copied {"value": ...} object is not a printed value
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
    if kind in ITEM_PATTERNS:
        return _items(kind, value)
    if kind == "range":
        numbers = _numbers(value) if isinstance(value, str) else (
            [_number(v) for v in value] if isinstance(value, list) else [])
        if len(numbers) == 2 and None not in numbers and numbers[0] <= numbers[1]:
            return [float(numbers[0]), float(numbers[1])]
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
