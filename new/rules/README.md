# Rule cards

Ten rule cards written by Marfik. They contain **no text from the IATA Live Animals Regulations**:
`source.lar_section` holds a section reference only, to be completed by a licensed reader.

**No invented values.** Rule cards never hard-code a threshold. Thresholds come from the dossier
itself, where each one has a stated origin:
- temperature range (R07, R08): the range declared on the shipping documents, recorded in the entry
  record (`declared.temperature_range_c`);
- shock and light alert levels (R09, R10): the alert thresholds configured on the sensor, recorded
  in the entry record (`sensor.shock_alert_g`, `sensor.light_alert_lux`).

A card whose threshold cannot be resolved for a dossier is reported as `unresolved` and triggers
no decision.

Fields: `id`, `title`, `title_fr`, `phase` (`pre_departure` | `investigation`), `check` (the
machine-readable test), `threshold` (`null` or where to read it in the dossier), `source`,
`evidence_expected`, `action` (`block` | `flag`), `status` (`active` | `disabled`).
