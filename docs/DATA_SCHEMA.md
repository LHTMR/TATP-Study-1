# DATA_SCHEMA — TATP Study 1 data files

Authoritative column list for every table in `SPEC.md` §14.2. **This file is parsed**, by
`tatp/datafiles.py` when it opens a table and by `tools/validate_session.py` when it checks one,
so the writer and the validator cannot drift from the documentation. Edit the tables below and
both follow.

Files are named `TATP1_{YYYY-MM-DD_HH-MM-SS}_P{code}_S{session}_{table}.csv`, one per
observational unit (Wickham 2014). Every row is appended and flushed as it is produced (§14.3).

## Parsing contract

- A table begins at a `### <table_name>` heading and is defined by the **first** markdown table
  under it, whose header is exactly `| Column | Type | Unit | Required | Description |`.
- `Type` is one of `str`, `int`, `float`, `bool`, `iso8601`.
- `Required` is `yes` or `no`. A required field must be non-empty in every row.
- `Unit` is `-` where the quantity is dimensionless.
- Column order in the file is the order below.

## Conventions

- **`timestamp_iso`** — wall clock, ISO 8601 local time with milliseconds, e.g.
  `2026-08-23T14:05:09.812`. Written from the same clock for every table.
- **`t_session_s`** — seconds from session t=0, which is the start of heat sensitisation (§7.4).
  Empty before sensitisation begins; that is why it is not required.
- **`phase`** — one of `setup`, `touch_calibration`, `pre_sensitisation`, `sensitisation`,
  `capsaicin`, `post_sensitisation`, `intervention`, `rekindle`, `post_intervention`,
  `session_end`.
- **`bool`** is written as `true` / `false`, never `1` / `0`, so a boolean is never confused with
  a count on inspection.
- **Missing** is the empty string. There is no sentinel number.
- Angles, forces and pressures carry their unit in the column name (§5.3).

---

### session

One row per key/value pair. Provenance for the whole session (§14.2). Written at session start,
appended to at session end.

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| key | str | - | yes | Provenance key; the set is listed under "session keys" below |
| value | str | - | no | Value as written; empty when the item is unresolved or not collected |

#### session keys

Every key below is written exactly once, in this order. A key whose value is unknown is still
written, with an empty value — an absent row and an empty value must not be confusable.

| Key | Unit | Notes |
|---|---|---|
| `participant_code` | - | No direct identifiers anywhere (§14.1) |
| `session_number` | - | 1, 2 or 3 |
| `condition` | - | `participant_preferred`, `ct_targeted` or `sham`. Recorded, never displayed (§16) |
| `limb` | - | `left` or `right`, from the allocation file |
| `experimenter_initials` | - | §11 |
| `experimenter_changed` | - | `true` if these differ from an earlier session for this participant |
| `participant_language` | - | `sv` or `en` |
| `experimenter_language` | - | `sv` or `en` |
| `rng_seed` | - | Integer seed for `numpy.random.Generator` |
| `allocation_file` | - | Path as given |
| `allocation_sha256` | - | Hash of the allocation file |
| `schedule_file` | - | Path as given |
| `schedule_sha256` | - | Hash of `schedule.yaml` |
| `config_sha256` | - | Hash over every loaded config file, in sorted path order |
| `pattern_folder` | - | Path as given |
| `pattern_sha256` | - | Hash over every pattern CSV and sidecar in the folder, sorted |
| `pattern_names` | - | Semicolon-separated, sorted. The *selected* pattern is not written here — it is in `touch_ratings.pattern_name` |
| `software_version` | - | From `tatp/__init__.py` |
| `git_sha` | - | Working-tree commit; suffixed `-dirty` if the tree is modified |
| `git_dirty` | - | `true` or `false` |
| `screenshot_freeze_sha` | - | The SHA recorded at the last screenshot freeze (§17.4); empty until first freeze |
| `python_version` | - | e.g. `3.11.9` |
| `qt_version` | - | Qt runtime version |
| `pyside_version` | - | PySide6 version |
| `package_versions` | - | Resolved env packages, `name=version` semicolon-separated (§3) |
| `platform` | - | OS and release string |
| `hostname` | - | Lab PC identity; not a participant identifier |
| `garment_driver` | - | Driver class name, e.g. `MockGarment` |
| `garment_capabilities` | - | `capabilities()` as `key=value` pairs, semicolon-separated (§12.1) |
| `reduced_capability_device` | - | `true` when `per_channel_pressure` is false (§12.4) |
| `filament_calibration_date` | - | Latest weighing date in `filaments.yaml`; empty if unweighed |
| `filaments_measured` | - | `true` when every listed filament has a measured force |
| `slope_prior_vas_per_log10` | VAS·log₁₀⁻¹ | The fixed slope used by the estimator (§8.2) |
| `room_temperature_c` | °C | Optional (§8.1) |
| `relative_humidity_pct` | % | Optional (§8.1) |
| `data_folder` | - | Resolved absolute path |
| `cloud_sync_warning` | - | The warning text if the data folder is inside a synced tree, else empty (§14.1) |
| `unresolved_open_items` | - | Semicolon-separated §20 item numbers still on placeholders |
| `resumed_from_session_file` | - | Filename resumed from, else empty (§15) |
| `session_start_iso` | - | Process start, wall clock |
| `sensitisation_start_iso` | - | Session t=0; empty until sensitisation begins |
| `session_end_iso` | - | Written at close |
| `abort_reason` | - | Empty unless the session was aborted |

---

### log

One row per event: phase transitions, block boundaries, cue onsets, button events, experimenter
actions, warnings, notes, errors (§14.2).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock |
| t_session_s | float | s | no | Seconds from session t=0 |
| phase | str | - | yes | Current phase |
| block_index | int | - | no | Scheduled block, empty outside a block |
| event | str | - | yes | Event name, `snake_case` |
| origin | str | - | yes | `software`, `experimenter` or `participant` |
| severity | str | - | yes | `info`, `warning` or `error` |
| detail | str | - | no | Free text; experimenter notes land here |

---

### pinprick

One row per monofilament application, both protocols, all phases (§14.2).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock at stimulus cue |
| t_session_s | float | s | no | Seconds from session t=0 |
| phase | str | - | yes | Phase |
| block_index | int | - | no | Scheduled block, empty outside a block |
| protocol | str | - | yes | `long` or `short` (§14.2) |
| region | str | - | yes | `primary` or `secondary` hyperalgesic zone |
| trial_index | int | - | yes | 1-based within the protocol run |
| purpose | str | - | yes | `search` or `measure`; only `measure` enters the estimate (§8.2) |
| filament_size | str | - | yes | Aesthesio size, e.g. `5.46` |
| force_nominal_mn | float | mN | yes | Label value, display only (§8.1) |
| force_measured_mn | float | mN | no | Weighed value; empty until the set is weighed (§20 item 1) |
| force_applied_mn | float | mN | yes | What the estimator fits. The measured force of the filament actually applied, which is not the intended one when the experimenter substitutes (§8.2 safety rule) |
| substituted | bool | - | yes | `true` when the applied filament differs from the one the software asked for |
| site_index | int | - | yes | Rotates on every application (§8.2) |
| cue_onset_iso | iso8601 | - | yes | Visual warning cue onset (§10.5) |
| rating_cue_iso | iso8601 | - | no | When the rating was cued, 9 s post-stimulus (Scheuren et al. 2023) |
| rating_percent | float | % | no | VAS response; empty if the trial was discarded before a response |
| rt_s | float | s | no | From rating cue to confirm |
| first_press_side | str | - | no | `left` or `right`; sets the marker's first position (§10.2) |
| direction_changes | int | - | no | Marker direction reversals |
| intolerable | bool | - | yes | Participant or experimenter marked this application intolerable at this site (§8.2) |
| discarded | bool | - | yes | Experimenter discarded and repeated; the row is retained (§11) |
| notes | str | - | no | Free text |

---

### calibration_pinprick

One row per completed long protocol — three per session (§8.2).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock at completion |
| t_session_s | float | s | no | Seconds from session t=0 |
| phase | str | - | yes | `pre_sensitisation`, `post_sensitisation` or `post_intervention` |
| region | str | - | yes | `primary` or `secondary` |
| start_filament_size | str | - | yes | Where the ascent began; logged so prior bias is detectable (§8.2) |
| start_source | str | - | yes | `config_default` or `previous_timepoint` |
| applications_total | int | - | yes | Search plus measurement |
| applications_measure | int | - | yes | Measurement trials entering the fit |
| capped | bool | - | yes | `true` if `max_applications` was reached (§8.2) |
| slope_prior_vas_per_log10 | float | VAS·log₁₀⁻¹ | yes | The fixed slope (§8.2) |
| f40_mn | float | mN | yes | The estimate; the continuous dependent variable |
| chosen_filament_size | str | - | yes | Nearest available filament, for the short protocol |
| chosen_force_mn | float | mN | yes | That filament's force |
| out_of_range | bool | - | yes | Set when and only when a boundary filament had to be used (§8.2) |
| out_of_range_direction | str | - | no | `below` or `above`; empty unless `out_of_range` |
| ordinal_rho | float | - | no | Rank correlation of rating against force, the consistency check (comparison doc §6.7) |

---

### brush

One row per brush application — allodynia, primary and secondary regions (§8.3).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock at stimulus cue |
| t_session_s | float | s | no | Seconds from session t=0 |
| phase | str | - | yes | Phase |
| region | str | - | yes | `primary` or `secondary` |
| trial_index | int | - | yes | 1-based |
| site_index | int | - | yes | Rotates on every application |
| cue_onset_iso | iso8601 | - | yes | Visual warning cue onset |
| rating_percent | float | % | no | VAS response |
| rt_s | float | s | no | From rating cue to confirm |
| first_press_side | str | - | no | `left` or `right` |
| direction_changes | int | - | no | Marker direction reversals |
| discarded | bool | - | yes | Discarded and repeated |

---

### mapping

One row per secondary-hyperalgesia mapping path — four per time point (§8.4).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock at path start |
| t_session_s | float | s | no | Seconds from session t=0 |
| phase | str | - | yes | Phase |
| path_id | str | - | yes | Which of the four linear paths |
| step_interval_s | float | s | yes | Pacing cue interval (§8.4) |
| step_size_mm | float | mm | yes | Distance per step |
| steps_counted | int | - | yes | Steps before the participant signalled the change |
| signalled | bool | - | yes | `false` if the path ran out before a signal |
| distance_mm | float | mm | no | Experimenter's measurement; may be entered later and must never block (§8.4) |
| distance_entered_iso | iso8601 | - | no | When it was typed |
| distance_missing | bool | - | yes | `true` if the session closed without it |

---

### sh_area

One row per time point (§8.4).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock when the area was computed |
| t_session_s | float | s | no | Seconds from session t=0 |
| phase | str | - | yes | Phase |
| distance_1_mm | float | mm | no | Path 1 measured distance |
| distance_2_mm | float | mm | no | Path 2 |
| distance_3_mm | float | mm | no | Path 3 |
| distance_4_mm | float | mm | no | Path 4 |
| area_mm2 | float | mm² | no | Computed from the four distances |
| area_missing | bool | - | yes | `true` when any distance is missing, so no area could be computed |

---

### touch_ratings

One row per touch VAS rating — the touch-calibration baseline and each intervention block (§14.2).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock at rating cue |
| t_session_s | float | s | no | Seconds from session t=0 |
| phase | str | - | yes | Phase |
| block_index | int | - | no | Scheduled block, empty outside a block |
| scale | str | - | yes | `intensity`, `pleasantness`, `relaxation` or `alertness` |
| rating_percent | float | % | no | VAS response |
| rt_s | float | s | no | From rating cue to confirm |
| first_press_side | str | - | no | `left` or `right` |
| direction_changes | int | - | no | Marker direction reversals |
| pattern_name | str | - | no | Pattern playing at the time. Recorded, never displayed (§16) |
| commanded_pressure_kpa | float | kPa | no | Reference-channel pressure commanded at the time |
| valid_for_analysis | bool | - | yes | `false` on a reduced-capability device (§12.4) |

---

### touchcal_adjust

One row per adjustment — Protocol B steps 1, 3 and 5 (§9).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock at adjustment start |
| t_session_s | float | s | no | Seconds from session t=0 |
| stage | str | - | yes | `anchor`, `channel_match` or `pleasantness` |
| channel | int | - | yes | Channel adjusted |
| reference_channel | int | - | no | Empty for `anchor` |
| anchor_percent | float | % | no | Target VAS point: 10, 30 or 80. Empty for `pleasantness`, which has no target |
| adjustment_index | int | - | yes | 1 or 2 — the two start points (§9) |
| start_direction | str | - | yes | `below` or `above` |
| start_pressure_kpa | float | kPa | yes | Where the adjustment began |
| produced_pressure_kpa | float | kPa | yes | Where the participant settled |
| range_min_kpa | float | kPa | yes | Lower bound of the adjustable range; [P30, P80] for pleasantness (§9) |
| range_max_kpa | float | kPa | yes | Upper bound |
| duration_s | float | s | yes | Adjustment start to confirm; the §20 item 8 measurement |
| button_events | int | - | yes | Down and up events; the full path is in `log` (§10.3) |
| min_exploration_met | bool | - | yes | Whether the minimum-exploration requirement was satisfied (comparison doc §7.3) |
| timed_out | bool | - | yes | Whether the adjustment time-out fired |
| verification_rating_percent | float | % | no | Rating of the produced pressure, step 2. Empty for stages that do not verify |
| valid_for_analysis | bool | - | yes | `false` on a reduced-capability device (§12.4) |

---

### touchcal_compare

One row per equalisation comparison, including catch trials (§9 step 4).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock at the first stimulus of the pair |
| t_session_s | float | s | no | Seconds from session t=0 |
| channel | int | - | yes | Test channel |
| reference_channel | int | - | yes | The reference, channel 3 (§9) |
| comparison_index | int | - | yes | 1-based |
| order | str | - | yes | `test_first` or `reference_first` — both orders are run (§9) |
| hold_s | float | s | yes | Hold per stimulus (§7.4 of the comparison doc) |
| test_pressure_kpa | float | kPa | yes | Commanded on the test channel; 0 on a catch trial |
| reference_pressure_kpa | float | kPa | yes | Commanded on the reference |
| catch_trial | bool | - | yes | Zero-pressure catch trial (§9) |
| judgement | str | - | no | `test_stronger`, `reference_stronger` or `equal` |
| felt | bool | - | no | Catch trials only: whether anything was reported felt |
| readjusted | bool | - | yes | Whether a re-adjustment was prompted and run |
| valid_for_analysis | bool | - | yes | `false` on a reduced-capability device (§12.4) |

---

### garment

One row per command issued to the garment (§14.2). The mock driver writes this exactly as a real
driver does, so a mock session and a real one are comparable line for line (§18.2).

| Column | Type | Unit | Required | Description |
|---|---|---|---|---|
| timestamp_iso | iso8601 | - | yes | Wall clock at the command |
| t_session_s | float | s | no | Seconds from session t=0 |
| phase | str | - | yes | Phase |
| block_index | int | - | no | Scheduled block, empty outside a block |
| driver | str | - | yes | Driver class name |
| event | str | - | yes | `connect`, `disconnect`, `set_pressure`, `pattern_start`, `pattern_stop`, `channel_on`, `channel_off`, `stop`, `fault` |
| channel | int | - | no | Empty for whole-device events |
| pressure_kpa | float | kPa | no | Commanded pressure after clamping |
| requested_kpa | float | kPa | no | What was asked for before clamping |
| clamped | bool | - | yes | `true` when the ceiling or rate limit altered the command (§13) |
| pattern_name | str | - | no | Pattern involved, for pattern events |
| detail | str | - | no | Fault text or other free detail |</invoke>
