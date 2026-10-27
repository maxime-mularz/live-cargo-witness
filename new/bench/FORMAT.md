# Dossier format

A dossier is everything Live Cargo Witness knows about one consignment: the entry record, the
shipping documents, the crate photos, the sensor log, the convoy attendant's notes and the ground
handler's recorded answers. This file is the complete specification: anyone can write a valid
dossier from it, by hand or with their own tools, without looking at the generator.

All timestamps are ISO 8601 UTC, written `YYYY-MM-DDTHH:MM:SSZ`.

## Folder layout

```
<DOSSIER_ID>/
  dossier.json                  entry record (below)
  documents/awb.png             air waybill image
  documents/awb.truth.json      what the image shows (offline stand-in for read_document)
  documents/certification.png   Shipper's Certification for Live Animals
  documents/certification.truth.json
  documents/loading_list.png
  documents/loading_list.truth.json
  photos/crate_NN.png           one photo per crate (crate_01, crate_02, ...)
  photos/crate_NN.truth.json    what the photo shows (offline stand-in for segment_crate)
  sensor/curve.csv              sensor log (absent when departure was blocked)
  voice/convoy_notes.json       transcribed notes of the convoy attendant (absent when blocked)
  voice/handler_answers.json    recorded answers of the ground handler (absent when blocked)
  expected.json                 ground truth, read only by the scoring script
```

Images and data must be fictitious and say so: every image carries a visible "SYNTHETIC" or
"FICTITIOUS" mark, every JSON has `"synthetic": true`.

## dossier.json

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Dossier id, same as the folder name |
| `synthetic` | bool | `true` |
| `notice` | string | A sentence stating the dossier is fictitious |
| `route` | object | `origin`, `stopover`, `destination` (3-letter codes, fictitious) |
| `awb_number_declared` | string | Air waybill number, `ddd-dddddddd` |
| `schedule` | object | `loading_start`, `takeoff_1`, `landing_1`, `takeoff_2`, `landing_2`, `unloading_end` |
| `phase_model` | object | `mode: "schedule"`, `takeoff_window_min`, `landing_window_min` (minutes), `source` (text) |
| `declared.species` | string | e.g. `Heifers` |
| `declared.temperature_range_c` | `[low, high]` | Range declared on the air waybill (handling information) |
| `declared.temperature_range_source` | string | Where the range comes from |
| `declared.inspection_windows` | list | `{id: "I1", start, end, reason}` — inspections declared in the entry record |
| `sensor.model` | string | Sensor model, `synthetic` for fictitious logs |
| `sensor.sampling_minutes` | int | Sampling period of the log |
| `sensor.shock_alert_g` | number | Shock alert level configured on the sensor |
| `sensor.light_alert_lux` | number | Light alert level configured on the sensor |
| `sensor.thresholds_source` | string | Where the alert levels come from |
| `documents` | object | `awb`, `certification`, `loading_list` → relative PNG paths |
| `photos` | list | Relative PNG paths of the crate photos |
| `sensor_curve` | string or null | `sensor/curve.csv`, null when departure was blocked |
| `voice_notes` | string or null | `voice/convoy_notes.json`, null when blocked |
| `handler_answers` | string or null | `voice/handler_answers.json`, null when blocked |

## Document truth files

`{"document": "<name>", "synthetic": true, "fields": {"<field>": {"value": ..., "bbox": [x0, y0, x1, y1] or null}}}`

| Document | Fields |
| --- | --- |
| `awb` | `awb_number` (string), `shipper`, `consignee`, `route` (list of codes), `flights` (list), `date` (`YYYY-MM-DD`), `nature_of_goods`, `head_count` (int), `handling_codes` (list of strings, e.g. `["AVI"]`), `handling_information` (string), `temperature_range_c` (`[low, high]`) |
| `certification` | `awb_number`, `species`, `head_count` (int), `shipper`, `date`, `signed` (bool), `signatory` (string or null) |
| `loading_list` | `awb_number`, `head_count` (int, total), `crates` (list of `{crate: "crate_01", head_count: int}`) |

## Crate photo truth files

```json
{"photo": "crate_01", "synthetic": true, "features": {
  "live_animals_label": {"present": true, "bbox": [x0, y0, x1, y1]},
  "orientation_arrows": {"present": true, "direction": "up", "bbox": [x0, y0, x1, y1]},
  "awb_number": {"value": "000-12345675", "bbox": [x0, y0, x1, y1]}}}
```

`direction` is `"up"`, `"down"` or `null` (no arrows).

## Sensor log — sensor/curve.csv

First line: a comment starting with `# SYNTHETIC` for fictitious logs. Then:

```
timestamp,temperature_c,light_lux,shock_g
2026-10-03T07:10:00Z,18.6,0.4,0.12
```

One row every `sampling_minutes`, from `loading_start` to `unloading_end` included.

## Voice files

`convoy_notes.json`: `[{"id": "N1", "time": "...", "text": "...", "audio": null}]`

`handler_answers.json`: `[{"id": "H1", "start": "...", "end": "...", "answer": "...", "audio": null},
..., {"id": "H0", "default": true, "answer": "...", "audio": null}]`. Asking the handler about an
interval returns the first non-default answer whose `[start, end]` overlaps it, else the default.

Recordings: put the audio of a note or answer in `voice/audio/<id>.m4a` (or `.mp3`, `.wav`,
`.ogg`, `.webm`), e.g. `voice/audio/N2.m4a`, or set its `audio` field to a relative path. In live
mode the recording is transcribed by Muse Voice Transcribe instead of using the stored text.

## Flight phases (schedule mode)

| Phase | From | To (excluded) |
| --- | --- | --- |
| `ground_departure` | `loading_start` | `takeoff_1` |
| `takeoff` | `takeoff_N` | `takeoff_N + takeoff_window_min` |
| `cruise` | end of takeoff | `landing_N − landing_window_min` |
| `landing` | `landing_N − landing_window_min` | `landing_N` |
| `stopover` | `landing_1` | `takeoff_2` |
| `ground_arrival` | last landing | `unloading_end` (included) |

## Deviations

The rule cards are in `new/rules/`. For each investigation rule (R07–R10), a **deviation** is a
maximal run of samples that break the rule, in a phase where the rule applies, all in the same
phase, each at most one sampling period after the previous one. Its `start` and `end` are the
timestamps of the first and last breaking samples; its `phase` is the phase of that run. The
threshold of each rule is read in the dossier (see each card's `threshold.path`). Shocks during
`takeoff` and `landing` never count for R09.

## expected.json

```json
{"dossier_id": "RES-01", "category": "explained_by_handler", "synthetic": true,
 "phase1": {"decision": "go", "violated_rules": []},
 "investigation": {"handler_call_expected": true,
                   "deviations": [{"rule": "R07", "start": "...", "end": "...",
                                   "phase": "stopover", "status": "explained_rule_exceeded"}]}}
```

- `phase1.decision` is `block` when any of R01–R06 is violated. A blocked consignment does not fly:
  no sensor log, no voice files, `investigation: null`.
- A deviation is **explained** (`explained_rule_exceeded`, or `explained_compliant` when the
  explanation shows the rule did not apply) by a convoy note dictated during the deviation or
  within 10 minutes of it, or by a recorded handler answer covering it that explains it.
- A deviation inside a declared inspection window is `false_positive_dismissed`.
- A deviation with no note and no inspection window requires asking the handler
  (`handler_call_expected: true`); if the answer explains nothing, it is `indeterminate`.
- `category` is free text; usual values: `compliant`, `defect_R01` … `defect_R06`,
  `explained_by_note`, `explained_by_handler`, `false_positive`, `indeterminate`, `mixed`.
