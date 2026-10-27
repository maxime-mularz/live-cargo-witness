"""CA-02 — does the orchestration model call tools correctly and read a document image?

Usage: python new/scripts/test_ca02.py           (needs lcw/models.py wired and keys in .env)

Part A: 5 tool-calling tests with the real TOOL_SCHEMAS. Pass = the model calls the asked tool
with every required argument, the right values, and a JSON object as arguments.
Part B: read_document_image on two fictitious documents, compared with their ground truth.
Threshold (spec, jalon of Oct 27): at least 4/5 in part A and the air waybill read correctly.
Below that, the plan is to orchestrate with Muse Spark (Meta Model API) instead.
"""
import json
import sys
import time
from pathlib import Path

import _path  # noqa: F401
from lcw import BENCH_DIR, models
from lcw.dossier import Dossier, load_json
from lcw.env import load_dotenv, redact
from lcw.tools import TOOL_SCHEMAS

SYSTEM = ("You are being tested on tool calling. Call exactly the tool you are asked to call, "
          "with exactly the arguments given, and a short 'reason'. Do not answer in text.")

CLAIM = {"id": "C1", "kind": "deviation", "rule": "R07", "status": "indeterminate",
         "interval": {"start": "2026-10-03T13:15:00Z", "end": "2026-10-03T13:40:00Z"},
         "statement": "Between 13:15 and 13:40 UTC the temperature was above the declared range.",
         "evidence": [{"type": "curve_segment", "series": "temperature_c",
                       "start": "2026-10-03T13:15:00Z", "end": "2026-10-03T13:40:00Z"},
                      {"type": "dossier_field", "path": "declared.temperature_range_c"},
                      {"type": "handler_answer", "id": "H1"}]}

CASES = [
    ("read_document", {"document": "awb"}, "Read the air waybill."),
    ("segment_crate", {"photo": "crate_02"}, "Segment the photo crate_02."),
    ("get_sensor_curve", {"start": "2026-10-03T13:00:00Z", "end": "2026-10-03T14:00:00Z"},
     "Get the sensor curve between 2026-10-03T13:00:00Z and 2026-10-03T14:00:00Z."),
    ("ask_handler", {"question": "What happened to the crates at the stopover?",
                     "start": "2026-10-03T13:15:00Z", "end": "2026-10-03T13:40:00Z"},
     "Ask the ground handler 'What happened to the crates at the stopover?' about "
     "2026-10-03T13:15:00Z to 2026-10-03T13:40:00Z."),
    ("write_case_file", {"claims": [CLAIM]},
     "Submit this single claim with write_case_file, unchanged: " + json.dumps(CLAIM)),
]


def same(a, b) -> bool:
    """Strict equality: 1 is not 1.0, True is not 1, "3" is not 3 (Python's == says otherwise)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def difference(read, truth) -> str:
    if read == truth and not same(read, truth):
        return f" (type: read {type(read).__name__}, expected {type(truth).__name__})"
    return ""


def part_a() -> int:
    passed = 0
    for name, expected, instruction in CASES:
        started = time.time()
        try:
            reply = models.chat([{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": instruction}], TOOL_SCHEMAS)
            calls = reply.get("tool_calls") or []
            call = calls[0] if calls else None
            problems = []
            if call is None:
                problems.append("no tool call")
            else:
                if call["name"] != name:
                    problems.append(f"called {call['name']}")
                arguments = call.get("arguments")
                if not isinstance(arguments, dict):
                    problems.append("arguments are not a JSON object")
                else:
                    for key, value in expected.items():
                        if not same(arguments.get(key), value):
                            problems.append(f"{key} = {json.dumps(arguments.get(key))[:80]}"
                                            f"{difference(arguments.get(key), value)}")
        except Exception as error:  # report, keep testing
            problems = [f"{type(error).__name__}: {redact(error)}"]
        ok = not problems
        passed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:18s} {time.time() - started:5.1f}s  {'; '.join(problems)}")
    return passed


def compare(dossier_dir: Path, document: str, fields: list[str]) -> bool:
    dossier = Dossier(dossier_dir)
    truth = {k: v["value"] for k, v in dossier.document_truth(document)["fields"].items()}
    image = dossier.path(dossier.record["documents"][document])
    try:
        read = models.read_document_image(image, document)
    except Exception as error:
        print(f"  [FAIL] {dossier.id}/{document}: {type(error).__name__}: {redact(error)}")
        return False
    ok = True
    for field in fields:
        good = same(read.get(field), truth[field])
        ok &= good
        print(f"  [{'ok' if good else 'KO'}] {dossier.id}/{document}.{field}: read {json.dumps(read.get(field))} "
              f"/ truth {json.dumps(truth[field])}{difference(read.get(field), truth[field])}")
    return ok


def main() -> None:
    load_dotenv()
    print("Part A — tool calling (Muse Spark Open)")
    a = part_a()
    print(f"  => {a}/5")
    print("Part B — reading document images")
    dev = BENCH_DIR / "dev"
    signed = next(d for d in sorted(dev.iterdir()) if (d / "dossier.json").exists()
                  and load_json(d / "documents" / "certification.truth.json")["fields"]["signed"]["value"])
    unsigned = next((d for d in sorted(dev.iterdir()) if (d / "dossier.json").exists()
                     and not load_json(d / "documents" / "certification.truth.json")["fields"]["signed"]["value"]),
                    None)
    awb_ok = compare(signed, "awb", ["awb_number", "head_count", "handling_codes", "temperature_range_c"])
    cert_ok = compare(unsigned, "certification", ["head_count", "signed"]) if unsigned else True
    verdict = "PASS" if a >= 4 and awb_ok else "FAIL"
    print(f"\nCA-02: {verdict} (tool calls {a}/5, air waybill {'read' if awb_ok else 'not read'} correctly, "
          f"unsigned certification {'detected' if cert_ok else 'missed'})")
    sys.exit(0 if a >= 4 and awb_ok else 1)


if __name__ == "__main__":
    main()
