"""Synthetic dossier generator (EF-18).

Produces fictitious, clearly labelled dossiers for the development bench: fake shipping documents
(PNG + ground-truth JSON), synthetic crate images, a synthetic sensor curve with flight phases and
parametrised peaks, transcribed convoy notes, recorded handler answers and ``expected.json``.

Everything is deterministic for a given seed. Nothing here comes from a real shipment.
Real crate photos and voice recordings are produced on the bench by the apprentice and replace
the synthetic images and transcripts where available.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .deviations import detect
from .dossier import format_ts, write_json
from .phases import phase_at, segment
from .rules import load_rules

NOTICE = ("FICTITIOUS DOSSIER generated for testing Live Cargo Witness. "
          "No real shipper, carrier, handler or shipment. All values are illustrative.")
FOOTER = "Fictitious document generated for testing. Not a real shipment."

# Illustrative values of the fictitious dossiers. They are dossier data (declared by a fictitious
# shipper, configured on a fictitious sensor), never rule-card thresholds.
TEMP_RANGE = (10.0, 24.0)
SHOCK_ALERT_G = 3.0
LIGHT_ALERT_LUX = 50.0
SAMPLING_MIN = 5

SPECIES = "Heifers"
ROUTE = {"origin": "ORI", "stopover": "STO", "destination": "DES"}

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)
BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for candidate in (BOLD_CANDIDATES if bold else FONT_CANDIDATES):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


# --------------------------------------------------------------------------- identifiers

def awb_number(rng: random.Random) -> str:
    """Fictitious air waybill number: prefix 000 + 7-digit serial + mod-7 check digit."""
    serial = rng.randint(1_000_000, 9_999_999)
    return f"000-{serial}{serial % 7}"


# --------------------------------------------------------------------------- documents

def _watermark(image: Image.Image, text: str) -> Image.Image:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _font(56, bold=True)
    draw.text((60, image.size[1] // 2), text, font=font, fill=(200, 60, 60, 60))
    rotated = layer.rotate(25, center=(image.size[0] // 2, image.size[1] // 2))
    return Image.alpha_composite(image.convert("RGBA"), rotated).convert("RGB")


def render_form(title: str, rows: list[tuple[str, str, str]], footer: str | None = None,
                signature: tuple[bool, str] | None = None) -> tuple[Image.Image, dict]:
    """Draw a simple form. ``rows`` = (field_key, label, value). Returns image + field bboxes."""
    width, height = 1000, 260 + 70 * len(rows) + (170 if signature else 0)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, width - 20, height - 20], outline="black", width=3)
    draw.text((50, 45), title, font=_font(30, bold=True), fill="black")
    draw.text((50, 90), "SPECIMEN — FICTITIOUS DOCUMENT FOR TESTING", font=_font(18), fill=(170, 0, 0))
    fields: dict[str, dict] = {}
    y = 150
    label_font, value_font = _font(18), _font(24, bold=True)
    for key, label, value in rows:
        draw.line([40, y - 12, width - 40, y - 12], fill=(200, 200, 200))
        draw.text((50, y), label, font=label_font, fill=(80, 80, 80))
        position = (360, y - 4)
        draw.text(position, value or "—", font=value_font, fill="black")
        bbox = draw.textbbox(position, value or "—", font=value_font)
        fields[key] = {"bbox": [int(v) for v in bbox]}
        y += 70
    if signature is not None:
        signed, signatory = signature
        draw.text((50, y + 10), "Signature of shipper", font=label_font, fill=(80, 80, 80))
        box = [360, y, 760, y + 120]
        draw.rectangle(box, outline="black", width=2)
        if signed:
            points = [(380 + i * 18, y + 60 + int(18 * math.sin(i * 1.3))) for i in range(20)]
            draw.line(points, fill=(20, 40, 140), width=3)
            draw.text((380, y + 92), signatory, font=_font(16), fill="black")
        fields["signature"] = {"bbox": box}
        y += 150
    if footer:
        draw.text((50, height - 60), footer, font=_font(16), fill=(80, 80, 80))
    return _watermark(image, "SPECIMEN · FICTITIOUS"), fields


def build_documents(spec: "DossierSpec") -> dict[str, tuple[Image.Image, dict]]:
    """Render the three shipping documents with their ground truth."""
    documents = {}
    low, high = TEMP_RANGE
    handling = spec.handling_codes
    awb_rows = [
        ("awb_number", "Air waybill number", spec.awb),
        ("shipper", "Shipper", "Fictitious Genetics Ltd"),
        ("consignee", "Consignee", "Fictitious Farms Co."),
        ("route", "Route", f"{ROUTE['origin']} → {ROUTE['stopover']} → {ROUTE['destination']}"),
        ("flights", "Flights / date", f"LCW101 / LCW202 — {spec.date}"),
        ("nature_of_goods", "Nature of goods", f"Live animals — {SPECIES.lower()}"),
        ("head_count", "Number of animals", str(spec.head_counts["awb"])),
        ("handling_codes", "Special handling codes", " ".join(handling)),
        ("handling_information", "Handling information",
         f"Keep between {low:g} °C and {high:g} °C"),
    ]
    image, boxes = render_form("AIR WAYBILL", awb_rows, footer=FOOTER)
    truth_fields = {
        "awb_number": spec.awb, "shipper": "Fictitious Genetics Ltd",
        "consignee": "Fictitious Farms Co.",
        "route": [ROUTE["origin"], ROUTE["stopover"], ROUTE["destination"]],
        "flights": ["LCW101", "LCW202"], "date": spec.date,
        "nature_of_goods": f"Live animals — {SPECIES.lower()}",
        "head_count": spec.head_counts["awb"], "handling_codes": handling,
        "handling_information": f"Keep between {low:g} °C and {high:g} °C",
        "temperature_range_c": [low, high],
    }
    documents["awb"] = (image, _truth("awb", truth_fields, boxes))

    cert_rows = [
        ("awb_number", "Air waybill number", spec.awb),
        ("species", "Species", SPECIES),
        ("head_count", "Number of animals", str(spec.head_counts["certification"])),
        ("shipper", "Shipper", "Fictitious Genetics Ltd"),
        ("date", "Date", spec.date),
    ]
    signatory = "A. Example (fictitious)"
    image, boxes = render_form("SHIPPER'S CERTIFICATION FOR LIVE ANIMALS", cert_rows,
                               footer=FOOTER, signature=(spec.signed, signatory))
    truth_fields = {
        "awb_number": spec.awb, "species": SPECIES, "head_count": spec.head_counts["certification"],
        "shipper": "Fictitious Genetics Ltd", "date": spec.date, "signed": spec.signed,
        "signatory": signatory if spec.signed else None,
    }
    documents["certification"] = (image, _truth("certification", truth_fields, boxes))

    list_rows = [("awb_number", "Air waybill number", spec.awb)]
    for index, count in enumerate(spec.crate_counts, start=1):
        list_rows.append((f"crate_{index:02d}", f"Crate {index:02d}", f"{count} animals"))
    list_rows.append(("head_count", "Total animals", str(spec.head_counts["loading_list"])))
    image, boxes = render_form("LOADING LIST", list_rows, footer=FOOTER)
    truth_fields = {
        "awb_number": spec.awb, "head_count": spec.head_counts["loading_list"],
        "crates": [{"crate": f"crate_{i:02d}", "head_count": c}
                   for i, c in enumerate(spec.crate_counts, start=1)],
    }
    documents["loading_list"] = (image, _truth("loading_list", truth_fields, boxes))
    return documents


def _truth(name: str, values: dict, boxes: dict) -> dict:
    fields = {}
    for key, value in values.items():
        fields[key] = {"value": value, "bbox": boxes.get(key, {}).get("bbox")}
    if "signed" in values:
        fields["signed"]["bbox"] = boxes.get("signature", {}).get("bbox")
    return {"document": name, "synthetic": True, "fields": fields}


# --------------------------------------------------------------------------- crate images

def render_crate(crate_id: str, awb_on_crate: str, label: bool, arrows: str | None,
                 rng: random.Random) -> tuple[Image.Image, dict]:
    """Synthetic drawing of a livestock crate. ``arrows`` is 'up', 'down' or None."""
    image = Image.new("RGB", (900, 650), (150, 150, 145))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 470, 900, 650], fill=(110, 110, 105))
    x0, y0, x1, y1 = 120, 110, 780, 520
    draw.rectangle([x0, y0, x1, y1], fill=(168, 124, 78), outline=(90, 60, 30), width=6)
    for slat in range(y0 + 50, y1, 60):
        draw.line([x0, slat, x1, slat], fill=(120, 85, 50), width=8)
    for gap in range(x0 + 40, x1 - 20, 110):
        draw.rectangle([gap, y0 + 20, gap + 30, y0 + 40], fill=(40, 30, 20))
    features: dict[str, dict] = {}

    if label:
        box = [x0 + 30, y0 + 70, x0 + 330, y0 + 170]
        draw.rectangle(box, fill=(255, 150, 0), outline="black", width=3)
        draw.text((box[0] + 25, box[1] + 30), "LIVE ANIMALS", font=_font(32, bold=True), fill="black")
        features["live_animals_label"] = {"present": True, "bbox": box}
    else:
        features["live_animals_label"] = {"present": False, "bbox": None}

    if arrows:
        box = [x1 - 230, y0 + 60, x1 - 40, y0 + 220]
        for offset in (0, 95):
            cx = box[0] + 45 + offset
            if arrows == "up":
                points = [(cx, box[1] + 10), (cx - 35, box[1] + 60), (cx + 35, box[1] + 60)]
                shaft = [cx - 10, box[1] + 60, cx + 10, box[3] - 10]
            else:
                points = [(cx, box[3] - 10), (cx - 35, box[3] - 60), (cx + 35, box[3] - 60)]
                shaft = [cx - 10, box[1] + 10, cx + 10, box[3] - 60]
            draw.polygon(points, fill="black")
            draw.rectangle(shaft, fill="black")
        features["orientation_arrows"] = {"present": True, "direction": arrows, "bbox": box}
    else:
        features["orientation_arrows"] = {"present": False, "direction": None, "bbox": None}

    plate = [x0 + 30, y1 - 120, x0 + 470, y1 - 50]
    draw.rectangle(plate, fill="white", outline="black", width=2)
    draw.text((plate[0] + 15, plate[1] + 18), f"AWB {awb_on_crate}", font=_font(28, bold=True),
              fill="black")
    features["awb_number"] = {"value": awb_on_crate, "bbox": plate}

    draw.text((20, 20), f"SYNTHETIC IMAGE — {crate_id}", font=_font(20, bold=True), fill=(170, 0, 0))
    jitter = rng.randint(-3, 3)
    image = image.rotate(jitter, fillcolor=(150, 150, 145))
    truth = {"photo": crate_id, "synthetic": True, "features": features,
             "note": "bboxes given before a rotation of %d degrees" % jitter}
    return image, truth


# --------------------------------------------------------------------------- curve

@dataclass
class Incident:
    start: datetime
    minutes: int
    temp_peak: float | None = None
    light_peak: float | None = None
    shock_peak: float | None = None
    tag: str = ""


def generate_curve(schedule: dict, incidents: list[Incident], rng: random.Random) -> list[dict]:
    low, high = TEMP_RANGE
    start = datetime.strptime(schedule["loading_start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    end = datetime.strptime(schedule["unloading_end"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    record = {"schedule": schedule, "phase_model": PHASE_MODEL}
    phases = segment(record)
    spikes = []
    for key, sign in (("takeoff_1", 1), ("takeoff_2", 1), ("landing_1", -1), ("landing_2", -1)):
        moment = datetime.strptime(schedule[key], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        spikes.append(moment + timedelta(minutes=5 * sign))

    rows = []
    moment = start
    while moment <= end:
        stamp = format_ts(moment)
        phase = phase_at(phases, stamp) or "ground_arrival"
        on_ground = phase in ("ground_departure", "stopover", "ground_arrival")
        base = (low + high) / 2 + (1.5 if on_ground else -1.0)
        temperature = base + rng.uniform(-0.4, 0.4)
        light = max(0.0, rng.uniform(-0.3, 1.2))
        shock = abs(rng.gauss(0.15, 0.08))
        if any(abs((moment - spike).total_seconds()) < 1 for spike in spikes):
            shock = rng.uniform(SHOCK_ALERT_G + 0.4, SHOCK_ALERT_G + 1.6)  # normal takeoff/landing jolt
        for incident in incidents:
            offset = (moment - incident.start).total_seconds() / 60
            if 0 <= offset <= incident.minutes:
                fraction = offset / incident.minutes if incident.minutes else 1.0
                if incident.temp_peak is not None:
                    hump = math.sin(math.pi * (0.15 + 0.7 * fraction))
                    limit = high if incident.temp_peak > high else low
                    margin = 0.6 if incident.temp_peak > high else -0.6
                    temperature = limit + margin + (incident.temp_peak - limit - margin) * hump
                if incident.light_peak is not None:
                    light = incident.light_peak * rng.uniform(0.75, 1.0)
                if incident.shock_peak is not None and offset == 0:
                    shock = incident.shock_peak
        rows.append({"timestamp": stamp, "temperature_c": round(temperature, 1),
                     "light_lux": round(light, 1), "shock_g": round(shock, 2)})
        moment += timedelta(minutes=SAMPLING_MIN)
    return rows


def write_curve(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# SYNTHETIC sensor curve — fictitious, generated by lcw.synth (EF-18)",
             "timestamp,temperature_c,light_lux,shock_g"]
    lines += [f"{r['timestamp']},{r['temperature_c']},{r['light_lux']},{r['shock_g']}" for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- dossier specs

PHASE_MODEL = {
    "mode": "schedule",
    "takeoff_window_min": 20,
    "landing_window_min": 20,
    "source": "Marfik configuration parameter (to be validated); used when the sensor does not "
              "measure pressure, acceleration or position",
}


@dataclass
class DossierSpec:
    dossier_id: str
    category: str
    variant: int
    seed: int
    awb: str = ""
    date: str = ""
    crate_counts: list[int] = field(default_factory=list)
    head_counts: dict = field(default_factory=dict)
    handling_codes: list[str] = field(default_factory=lambda: ["AVI"])
    signed: bool = True
    crates: list[dict] = field(default_factory=list)  # per crate: label, arrows, awb_on_crate
    expected_phase1: dict = field(default_factory=dict)


CATEGORIES = [
    ("compliant", 4),
    ("defect_R01", 1), ("defect_R02", 1), ("defect_R03", 1),
    ("defect_R04", 1), ("defect_R05", 1), ("defect_R06", 1),
    ("explained_by_note", 3),
    ("explained_by_handler", 3),
    ("false_positive", 2),
    ("indeterminate", 2),
]


def _schedule(day: datetime, rng: random.Random) -> dict:
    loading = day + timedelta(hours=7, minutes=5 * rng.randint(0, 6))
    takeoff_1 = loading + timedelta(hours=2)
    landing_1 = takeoff_1 + timedelta(hours=3, minutes=5 * rng.randint(0, 6))
    takeoff_2 = landing_1 + timedelta(hours=2)
    landing_2 = takeoff_2 + timedelta(hours=4, minutes=5 * rng.randint(0, 6))
    unloading = landing_2 + timedelta(hours=1, minutes=30)
    return {key: format_ts(value) for key, value in (
        ("loading_start", loading), ("takeoff_1", takeoff_1), ("landing_1", landing_1),
        ("takeoff_2", takeoff_2), ("landing_2", landing_2), ("unloading_end", unloading))}


def _ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def build_dossier(spec: DossierSpec, out_dir: Path, day: datetime) -> dict:
    """Write one dossier folder and return its expected.json content."""
    rng = random.Random(spec.seed)
    spec.awb = awb_number(rng)
    spec.date = day.strftime("%Y-%m-%d")
    crates = rng.choice([2, 3])
    spec.crate_counts = [rng.randint(4, 6) for _ in range(crates)]
    total = sum(spec.crate_counts)
    spec.head_counts = {"awb": total, "certification": total, "loading_list": total}
    spec.crates = [{"label": True, "arrows": "up", "awb": spec.awb} for _ in range(crates)]
    violated: list[str] = []

    category = spec.category
    if category == "defect_R01":
        spec.handling_codes = ["PER"] if spec.variant == 0 else []
        violated = ["R01"]
    elif category == "defect_R02":
        spec.signed = False
        violated = ["R02"]
    elif category == "defect_R03":
        spec.head_counts["certification"] = total - rng.randint(1, 2)
        violated = ["R03"]
    elif category == "defect_R04":
        spec.crates[rng.randrange(crates)]["label"] = False
        violated = ["R04"]
    elif category == "defect_R05":
        spec.crates[rng.randrange(crates)]["arrows"] = "down" if spec.variant == 0 else None
        violated = ["R05"]
    elif category == "defect_R06":
        index = rng.randrange(crates)
        other = awb_number(rng)
        spec.crates[index]["awb"] = other
        violated = ["R06"]
    blocked = bool(violated)
    spec.expected_phase1 = {"decision": "block" if blocked else "go", "violated_rules": violated}

    root = out_dir / spec.dossier_id
    (root / "documents").mkdir(parents=True, exist_ok=True)
    (root / "photos").mkdir(parents=True, exist_ok=True)
    documents = build_documents(spec)
    document_paths = {}
    for name, (image, truth) in documents.items():
        image.save(root / "documents" / f"{name}.png", optimize=True)
        write_json(root / "documents" / f"{name}.truth.json", truth)
        document_paths[name] = f"documents/{name}.png"
    photo_paths = []
    for index, crate in enumerate(spec.crates, start=1):
        crate_id = f"crate_{index:02d}"
        image, truth = render_crate(crate_id, crate["awb"], crate["label"], crate["arrows"], rng)
        image.save(root / "photos" / f"{crate_id}.png", optimize=True)
        write_json(root / "photos" / f"{crate_id}.truth.json", truth)
        photo_paths.append(f"photos/{crate_id}.png")

    schedule = _schedule(day, rng)
    inspection_windows: list[dict] = []
    notes: list[dict] = [{"id": "N1", "time": format_ts(_ts(schedule["loading_start"]) + timedelta(minutes=40)),
                          "text": "Loading complete, all crates secured and strapped.", "audio": None}]
    answers: list[dict] = []
    incidents: list[Incident] = []
    handler_call_expected = False
    status_for_incident = "explained_rule_exceeded"

    if not blocked:
        stop_start = _ts(schedule["landing_1"]) + timedelta(minutes=25)
        arrival = _ts(schedule["landing_2"]) + timedelta(minutes=15)
        departure_ground = _ts(schedule["loading_start"]) + timedelta(minutes=55)
        if category == "explained_by_note":
            where = [stop_start, arrival, departure_ground][spec.variant]
            minutes = rng.choice([20, 25, 30])
            incidents.append(Incident(where, minutes, temp_peak=round(TEMP_RANGE[1] + rng.uniform(3, 7), 1),
                                      tag="note"))
            texts = [
                "Stopover: refuelling delay, cargo door left open, crates in direct sun for about {m} minutes.",
                "Arrival: unloading truck late, crates waited on the apron for about {m} minutes.",
                "Departure: auxiliary power off during loading delay, hold getting warm for about {m} minutes.",
            ]
            notes.append({"id": "N2", "time": format_ts(where + timedelta(minutes=5)),
                          "text": texts[spec.variant].format(m=minutes), "audio": None})
        elif category == "explained_by_handler":
            where = [stop_start, arrival, stop_start + timedelta(minutes=20)][spec.variant]
            minutes = rng.choice([20, 25])
            incidents.append(Incident(where, minutes,
                                      temp_peak=round(TEMP_RANGE[1] + rng.uniform(3, 6), 1),
                                      light_peak=round(rng.uniform(300, 900)),
                                      shock_peak=round(SHOCK_ALERT_G + rng.uniform(0.8, 2.0), 2)
                                      if spec.variant != 1 else None,
                                      tag="handler"))
            if spec.variant == 0:
                notes.append({"id": "N2", "time": format_ts(where + timedelta(minutes=minutes + 20)),
                              "text": "Stopover: no handling of the crates, everything quiet.",
                              "audio": None})
            answers.append({"id": "H1", "start": format_ts(where - timedelta(minutes=10)),
                            "end": format_ts(where + timedelta(minutes=minutes + 10)),
                            "answer": ["The crate was moved out to the apron during the pallet "
                                       "reconfiguration, about {m} minutes, then loaded back.",
                                       "We had to wait for the forklift; the crates stayed outside "
                                       "the warehouse for about {m} minutes.",
                                       "The crate was taken off the aircraft to make room for "
                                       "another pallet, about {m} minutes on the apron."][spec.variant]
                            .format(m=minutes),
                            "audio": None})
            handler_call_expected = True
        elif category == "false_positive":
            where = departure_ground + timedelta(minutes=10)
            minutes = 10
            incidents.append(Incident(where, minutes, light_peak=round(rng.uniform(200, 600)),
                                      tag="inspection"))
            inspection_windows.append({
                "id": "I1", "start": format_ts(where - timedelta(minutes=5)),
                "end": format_ts(where + timedelta(minutes=minutes + 5)),
                "reason": "Border control documentary inspection, crate 02 opened.",
            })
            notes.append({"id": "N2", "time": format_ts(where + timedelta(minutes=minutes + 5)),
                          "text": "Inspection finished, crate 02 closed again.", "audio": None})
            status_for_incident = "false_positive_dismissed"
        elif category == "indeterminate":
            where = [arrival, stop_start][spec.variant]
            minutes = rng.choice([20, 30])
            incidents.append(Incident(where, minutes, temp_peak=round(TEMP_RANGE[1] + rng.uniform(3, 6), 1),
                                      tag="unknown"))
            answers.append({"id": "H1", "start": format_ts(where - timedelta(minutes=10)),
                            "end": format_ts(where + timedelta(minutes=minutes + 10)),
                            "answer": "I was not on shift at that time, I cannot say what happened.",
                            "audio": None})
            handler_call_expected = True
            status_for_incident = "indeterminate"
        notes.append({"id": f"N{len(notes) + 1}",
                      "time": format_ts(_ts(schedule["landing_2"]) + timedelta(minutes=60)),
                      "text": "Arrival: crates handed over to the consignee's team.", "audio": None})
    answers.append({"id": "H0", "default": True,
                    "answer": "I have no information about that period.", "audio": None})

    record = {
        "id": spec.dossier_id,
        "synthetic": True,
        "notice": NOTICE,
        "route": ROUTE,
        "awb_number_declared": spec.awb,
        "schedule": schedule,
        "phase_model": PHASE_MODEL,
        "declared": {
            "species": SPECIES,
            "temperature_range_c": list(TEMP_RANGE),
            "temperature_range_source": "documents/awb.png, field handling_information",
            "inspection_windows": inspection_windows,
        },
        "sensor": {
            "model": "synthetic",
            "sampling_minutes": SAMPLING_MIN,
            "shock_alert_g": SHOCK_ALERT_G,
            "light_alert_lux": LIGHT_ALERT_LUX,
            "thresholds_source": "Alert levels configured on the sensor (fictitious values).",
        },
        "documents": document_paths,
        "photos": photo_paths,
        "sensor_curve": None,
        "voice_notes": None,
        "handler_answers": None,
    }

    investigation = None
    if not blocked:
        curve = generate_curve(schedule, incidents, rng)
        write_curve(root / "sensor" / "curve.csv", curve)
        record["sensor_curve"] = "sensor/curve.csv"
        write_json(root / "voice" / "convoy_notes.json", notes)
        write_json(root / "voice" / "handler_answers.json", answers)
        record["voice_notes"] = "voice/convoy_notes.json"
        record["handler_answers"] = "voice/handler_answers.json"
        found = detect(curve, segment(record), load_rules(), record)["deviations"]
        expected_deviations = []
        for deviation in found:
            matching = [i for i in incidents
                        if i.start - timedelta(minutes=SAMPLING_MIN) <= _ts(deviation["start"])
                        <= i.start + timedelta(minutes=i.minutes + SAMPLING_MIN)]
            if not matching:
                raise AssertionError(f"{spec.dossier_id}: deviation without incident {deviation}")
            expected_deviations.append({
                "rule": deviation["rule"], "start": deviation["start"], "end": deviation["end"],
                "phase": deviation["phase"], "status": status_for_incident,
            })
        if incidents and not expected_deviations:
            raise AssertionError(f"{spec.dossier_id}: injected incident not detected")
        investigation = {"handler_call_expected": handler_call_expected,
                         "deviations": expected_deviations}

    write_json(root / "dossier.json", record)
    expected = {"dossier_id": spec.dossier_id, "category": category, "synthetic": True,
                "phase1": spec.expected_phase1, "investigation": investigation}
    write_json(root / "expected.json", expected)
    return expected


def build_bench(out_dir: Path, seed: int = 20261027, prefix: str = "DEV") -> list[dict]:
    """Generate the development bench (20 dossiers). Ids are shuffled so they reveal nothing."""
    rng = random.Random(seed)
    specs = []
    for category, count in CATEGORIES:
        for variant in range(count):
            specs.append((category, variant))
    rng.shuffle(specs)
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = []
    base_day = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for index, (category, variant) in enumerate(specs, start=1):
        spec = DossierSpec(dossier_id=f"{prefix}-{index:02d}", category=category, variant=variant,
                           seed=seed + index)
        expected.append(build_dossier(spec, out_dir, base_day + timedelta(days=index)))
    return expected
