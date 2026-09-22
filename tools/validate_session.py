#!/usr/bin/env python
"""The end-to-end validator. SPEC.md 17.3.

Two halves, kept separate so the second can grow as the milestones land:

- the **runner** drives the session `run_session.py` runs -- mock garment, a virtual participant
  from `sim/responders.py`, an accelerated clock, a throwaway data folder -- and delivers the
  participant's presses as real key events to `ParticipantWindow`, so what is exercised is the
  key handling a participant actually operates rather than `VasState` called directly;
- the **checker** opens the files that session wrote and runs a list of named checks.

**A check is written only when the thing it checks exists.** SPEC.md 17.3 describes the finished
software, so reading its bullets as a checklist today would produce a validator that is green
because it is empty. Anything whose precondition is not built yet is in `DEFERRED` with the
reason, and is reported and counted as skipped -- never silently passed. "12 passed, 6 skipped"
is the honest version of "18 passed".

There is no virtual experimenter yet (`sim/experimenters.py` is not built). The slice has one
experimenter action, launching the block, and `SliceRunner` performs it.

    make validate
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Headless (SPEC.md 17.1). Set here rather than as a prefix on the command line, which the
# permission rules could not match (CLAUDE.md).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402  -- after the platform is chosen
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import run_session  # noqa: E402
from sim.responders import INTENSITY_SCALE, PAIN_SCALE, Press  # noqa: E402
from sim.responders import Responder as VirtualParticipant  # noqa: E402
from tatp import blinding  # noqa: E402
from tatp import config as cfg  # noqa: E402
from tatp.clock import ISO_FORMAT, Clock  # noqa: E402
from tatp.datafiles import FILENAME_TEMPLATE, parse_schema  # noqa: E402
from tatp.responder import Responder  # noqa: E402
from tatp.session import Session  # noqa: E402
from tatp.ui.application import application  # noqa: E402
from tatp.ui.experimenter import ExperimenterWindow  # noqa: E402
from tatp.ui.participant import ParticipantWindow  # noqa: E402
from tatp.ui.vas import QT_KEYS  # noqa: E402

# Inside `data/`, which is gitignored, so nothing a validation run writes can be committed.
DEFAULT_FOLDER = REPO_ROOT / "data" / "_validate"

# The identity the validated session runs under. Participant 01, session 1 is a row of the
# committed allocation file; the check below reads that file independently to confirm it.
PARTICIPANT = "01"
SESSION = 1
EXPERIMENTER = "VV"
PATTERNS = cfg.CONFIG_DIR / "patterns" / "examples"

CLOCK_SPEED = 100.0
DEFAULT_SEED = 1
# Real seconds the runner waits for the slice to close before calling it hung.
TIMEOUT_S = 30.0
POLL_S = 0.001

# What the slice writes, and what it cannot write yet. Together they must be every table in
# DATA_SCHEMA.md, so a table added to the schema cannot go unexamined by being in neither.
PRODUCED = ("session", "log", "pinprick", "touch_ratings", "touchcal_adjust", "garment")
NOT_YET_PRODUCED = {
    "calibration_pinprick": "Milestone 3 -- the long-protocol search",
    "brush": "Milestone 3",
    "mapping": "Milestone 3 -- secondary hyperalgesia area mapping",
    "sh_area": "Milestone 3",
    "touchcal_estimate": "Milestone 4 -- Protocol B step 2",
    "touchcal_fit": "Milestone 4",
    "touchcal_compare": "Milestone 4 -- the equalisation comparison",
}

# Trial tables compared across two runs with one seed. The rows a participant's answers produce.
TRIAL_TABLES = ("pinprick", "touch_ratings", "touchcal_adjust")

# Session keys that are empty in a correct slice session, each with why. Every other key must
# carry a value. A key moves out of here when the code that fills it lands.
MAY_BE_EMPTY = {
    "screenshot_freeze_sha": "empty until the first screenshot freeze (Milestone 6)",
    "room_temperature_c": "optional; entered through the launcher (Milestone 5)",
    "relative_humidity_pct": "optional; entered through the launcher (Milestone 5)",
    "white_noise_level_dbfs": "set by the masking check (Milestone 5)",
    "masking_confirmed": "set by the masking check (Milestone 5)",
    "filament_calibration_date": "empty until the filaments are weighed (open item 1)",
    "cloud_sync_warning": "empty unless the data folder is in a synced tree",
    "unresolved_open_items": "empty once every open item is resolved",
    "resumed_from_session_file": "empty unless the session was resumed",
    "abort_reason": "empty unless the session was aborted",
}

# SPEC.md 17.3 assertions whose precondition does not exist yet. Reported as skipped.
DEFERRED = {
    "row_counts_match_schedule": "Milestone 5 -- the slice runs one block of the grid",
    "blocks_in_scheduled_order": "Milestone 5 -- the slice runs one block of the grid",
    "planned_vs_actual_offsets_full_grid": "Milestone 5 -- one block's offset is checked "
    "by blocks_record_planned_and_actual",
    "intervals_within_tolerance": "cues.interval_tolerance_s is null -- a value is needed "
    "from S (open item L5)",
    "seed_reproduces_trial_order": "Milestone 3 -- nothing reads session.rng yet, so there is "
    "no trial order for the seed to decide; repeat_run_is_identical checks determinism",
    "out_of_range_set_correctly": "Milestone 3 -- out_of_range has no writer",
    "calibrated_f40_is_a_filament": "Milestone 3 -- there is no calibration to produce an F40; "
    "the applied filament is checked by pinprick_filament_is_listed",
}


# -- the runner --------------------------------------------------------------------------


@dataclass(frozen=True)
class Run:
    folder: Path
    seed: int
    completed: bool


def _key_for(config: cfg.Config, press: Press) -> Qt.Key:
    """The first key the configured device emits for the press's action."""
    name = config.hardware["responder"]["keys"][press.action.value][0]
    return QT_KEYS[name]


def _event(kind: QEvent.Type, key: Qt.Key, stamp_ms: int) -> QKeyEvent:
    event = QKeyEvent(kind, key, Qt.NoModifier)
    event.setTimestamp(stamp_ms)
    return event


def _deliver(widget, key: Qt.Key, hold_s: float) -> None:
    """One press, stamped as the device would stamp it: the release `hold_s` after the press.

    The adjustment times a press from the events' own stamps (tatp/touchcal.py). Stamping the
    release when it is created instead would put however long the press handler took into the
    thumb's hold -- the very error those stamps exist to remove.
    """
    pressed_ms = int(time.monotonic() * 1000)
    widget.keyPressEvent(_event(QEvent.KeyPress, key, pressed_ms))
    # Real seconds, as SPEC.md 17.5 says of a hold: the adjustment reads it off the real clock.
    deadline = time.monotonic() + hold_s
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(POLL_S)
    widget.keyReleaseEvent(
        _event(QEvent.KeyRelease, key, pressed_ms + int(round(hold_s * 1000)))
    )


def _filament_force_mn(config: cfg.Config, label_g: str) -> float:
    for filament in config.filaments["filaments"]:
        if filament["label_g"] == label_g:
            measured = filament["force_measured_mn"]
            return float(filament["force_nominal_mn"] if measured is None else measured)
    raise KeyError(f"filaments.yaml lists no filament labelled {label_g!r} g")


def _answer(runner: run_session.SliceRunner, participant_model: VirtualParticipant,
            config: cfg.Config, answered: set) -> None:
    """If a screen is waiting for the participant and has not been answered, answer it."""
    window = runner.participant
    screen = window.stack.currentWidget()
    presses: tuple[Press, ...] = ()
    target = window

    if screen is window.control and runner.adjustment is not None:
        presentation = ("adjust", id(runner.adjustment))
        if presentation in answered:
            return
        adjustment = runner.adjustment
        presses = participant_model.adjustment_actions(
            adjustment.plan.target_key, adjustment.start_kpa, config.hardware["adjustment"]
        )
    elif screen is window.vas and window.vas.state.cued:
        vas = window.vas
        presentation = ("vas", vas.scale, vas.state.cue_iso)
        if presentation in answered:
            return
        if vas.scale == PAIN_SCALE:
            stimulus = _filament_force_mn(config, runner.trial.application.applied_label_g)
        elif vas.scale == INTENSITY_SCALE:
            stimulus = runner.session.garment.pressure_kpa[runner.channel]
        else:
            stimulus = None
        anchors = tuple(float(a) for a in
                        config.study1["touch_calibration"]["anchors_pct"])
        presses = participant_model.vas_actions(
            vas.scale, stimulus, config.study1["vas"], anchors
        )
        # The VAS reads its own keys while it is shown (ParticipantWindow._show).
        target = vas
    else:
        return

    answered.add(presentation)
    for press in presses:
        _deliver(target, _key_for(config, press), press.hold_s)


def run(folder: Path, seed: int, participant_cls=VirtualParticipant) -> Run:
    """One slice session, headless, into `folder`. Returns once the session is closed."""
    loaded = cfg.load("sv", "en")
    # The study's fonts, as in a real session, so the slice validated is the lab PC's.
    app = application(loaded.hardware)
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"], "folder": str(folder)}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})

    session = Session(config, PARTICIPANT, SESSION, EXPERIMENTER, PATTERNS,
                      clock=Clock(speed=CLOCK_SPEED), rng_seed=seed)
    session.start()
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    runner = run_session.SliceRunner(session, participant, experimenter)
    # The virtual participant's own generator, seeded from the seed the session records, so the
    # session is reproducible from its data file alone (SPEC.md 17.5).
    participant_model = participant_cls(random.Random(session.rng_seed))

    runner.run()
    answered: set = set()
    deadline = time.monotonic() + TIMEOUT_S
    while not session.closed:
        if time.monotonic() > deadline:
            session.close("validator: the slice did not finish")
            raise RuntimeError(f"the slice did not close within {TIMEOUT_S} s")
        app.processEvents()
        _answer(runner, participant_model, config, answered)
        time.sleep(POLL_S)
    return Run(folder=folder, seed=seed, completed=runner.completed)


# -- the checker -------------------------------------------------------------------------


@dataclass
class Tables:
    """Every data file in one folder, read back as the analyst would read it."""

    folder: Path
    headers: dict[str, list[str]]
    rows: dict[str, list[dict[str, str]]]

    @classmethod
    def read(cls, folder: Path) -> Tables:
        headers, rows = {}, {}
        schema, _ = parse_schema()
        for name in schema:
            pattern = FILENAME_TEMPLATE.format(
                stamp="*", code=PARTICIPANT, session=SESSION, table=name
            )
            found = sorted(folder.glob(pattern))
            assert len(found) <= 1, f"{len(found)} files for table {name!r} in {folder}"
            if not found:
                continue
            with found[0].open(encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                headers[name] = next(reader)
                rows[name] = [dict(zip(headers[name], r, strict=True)) for r in reader]
        return cls(folder, headers, rows)

    def session_values(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self.rows["session"]}


def check_tables_present(tables: Tables, **_) -> list[str]:
    schema, _ = parse_schema()
    failures = []
    unaccounted = set(schema) - set(PRODUCED) - set(NOT_YET_PRODUCED)
    if unaccounted:
        failures.append(f"schema tables in neither PRODUCED nor NOT_YET_PRODUCED: "
                        f"{sorted(unaccounted)}")
    failures += [f"{name}: not written" for name in PRODUCED if name not in tables.rows]
    # One that appears early means the code landed and the list here is stale -- move it.
    failures += [f"{name}: written, but listed as not yet produced ({why})"
                 for name, why in NOT_YET_PRODUCED.items() if name in tables.rows]
    return failures


def check_columns_match_schema(tables: Tables, **_) -> list[str]:
    schema, _ = parse_schema()
    return [
        f"{name}: columns {header} != schema {list(schema[name].column_names)}"
        for name, header in tables.headers.items()
        if header != list(schema[name].column_names)
    ]


def check_required_fields_present(tables: Tables, **_) -> list[str]:
    schema, _ = parse_schema()
    failures = []
    for name, rows in tables.rows.items():
        required = [c.name for c in schema[name].columns if c.required]
        for number, row in enumerate(rows, start=2):
            failures += [f"{name} line {number}: {column} is empty"
                         for column in required if row.get(column, "") == ""]
    return failures


def _parses(value: str, type_name: str) -> bool:
    if type_name == "int":
        return value.lstrip("-").isdigit()
    if type_name == "float":
        try:
            float(value)
        except ValueError:
            return False
        return True
    if type_name == "bool":
        return value in ("true", "false")
    if type_name == "iso8601":
        try:
            datetime.strptime(value, ISO_FORMAT)
        except ValueError:
            return False
        return True
    return True


def check_values_match_types(tables: Tables, **_) -> list[str]:
    schema, _ = parse_schema()
    failures = []
    for name, rows in tables.rows.items():
        for number, row in enumerate(rows, start=2):
            for column in schema[name].columns:
                value = row.get(column.name, "")
                if value and not _parses(value, column.type):
                    failures.append(f"{name} line {number}: {column.name}={value!r} is not "
                                    f"{column.type}")
    return failures


def check_session_keys_complete(tables: Tables, **_) -> list[str]:
    _, keys = parse_schema()
    written = [row["key"] for row in tables.rows["session"]]
    if written == list(keys):
        return []
    missing = [k for k in keys if k not in written]
    extra = [k for k in written if k not in keys]
    repeated = sorted({k for k in written if written.count(k) > 1})
    return [f"session keys differ from DATA_SCHEMA.md: missing {missing}, extra {extra}, "
            f"repeated {repeated}, or out of order"]


def check_provenance_populated(tables: Tables, **_) -> list[str]:
    return [f"session.{key} is empty" for key, value in tables.session_values().items()
            if value == "" and key not in MAY_BE_EMPTY]


def _allocation_row(participant: str, session: int) -> dict[str, str]:
    """Read independently of `tatp/allocation.py`, so the check is not the code it checks."""
    loaded = cfg.load("sv", "en")
    path = Path(loaded.study1["design"]["allocation_file"])
    if not path.is_absolute():
        path = REPO_ROOT / path
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if not line.startswith("#")]
    matches = [row for row in csv.DictReader(lines)
               if row["participant_code"] == participant
               and row["session_number"] == str(session)]
    assert len(matches) == 1, f"{path.name}: {len(matches)} rows for P{participant} S{session}"
    return matches[0]


def check_allocation_matches(tables: Tables, **_) -> list[str]:
    values = tables.session_values()
    fields = ("participant_code", "session_number", "condition", "limb")
    missing = [f for f in fields if f not in values]
    if missing:
        return [f"session: {missing} not written, so there is nothing to compare"]
    expected = _allocation_row(values["participant_code"], int(values["session_number"]))
    return [f"session.{field} is {values[field]!r}, allocation file says {expected[field]!r}"
            for field in ("condition", "limb") if values[field] != expected[field]]


def check_timestamps_monotonic(tables: Tables, **_) -> list[str]:
    failures = []
    for name, rows in tables.rows.items():
        if name == "session":
            continue
        stamps = [row["timestamp_iso"] for row in rows]
        # ISO_FORMAT sorts lexically in time order, which is what makes a string compare valid.
        failures += [f"{name} line {i + 3}: {later} is before {earlier}"
                     for i, (earlier, later) in enumerate(zip(stamps, stamps[1:], strict=False))
                     if later < earlier]
    offsets = [float(r["t_session_s"]) for r in tables.rows["log"] if r["t_session_s"]]
    failures += [f"log: t_session_s goes back from {a} to {b}"
                 for a, b in zip(offsets, offsets[1:], strict=False) if b < a]
    return failures


def check_pinprick_filament_is_listed(tables: Tables, **_) -> list[str]:
    loaded = cfg.load("sv", "en")
    failures = []
    for number, row in enumerate(tables.rows["pinprick"], start=2):
        try:
            force = _filament_force_mn(loaded, row["applied_filament_label_g"])
        except KeyError as error:
            failures.append(f"pinprick line {number}: {error}")
            continue
        applied = row["force_applied_mn"]
        if float(applied) != force:
            failures.append(f"pinprick line {number}: force_applied_mn {applied} is not the "
                            f"{row['applied_filament_label_g']} g filament's {force}")
    return failures


def _without_time(tables: Tables, name: str) -> list[dict[str, str]]:
    """The rows without any column that measures time: stamps, and anything in seconds."""
    schema, _ = parse_schema()
    timed = {c.name for c in schema[name].columns if c.type == "iso8601" or c.unit == "s"}
    return [{k: v for k, v in row.items() if k not in timed} for row in tables.rows[name]]


def check_repeat_run_is_identical(tables: Tables, repeat: Tables, **_) -> list[str]:
    """Two runs with one seed write the same trial rows, times aside.

    Not SPEC.md 17.3's seed check: nothing in the software draws from `session.rng` yet, so the
    only randomness is the virtual participant's. What this catches is nondeterminism -- the
    lost tap in tatp/touchcal.py showed up here first.
    """
    seed = tables.session_values()["rng_seed"]
    failures = []
    for name in TRIAL_TABLES:
        first, second = _without_time(tables, name), _without_time(repeat, name)
        if len(first) != len(second):
            failures.append(f"{name}: {len(first)} rows, then {len(second)}, with seed {seed}")
            continue
        for number, (a, b) in enumerate(zip(first, second, strict=True), start=2):
            failures += [f"{name} line {number}: {column} {a[column]!r} then {b[column]!r} "
                         f"with seed {seed}" for column in a if a[column] != b[column]]
    return failures


def check_no_adjustment_timed_out(tables: Tables, **_) -> list[str]:
    """The normal responder always confirms, so a time-out means the runner was too slow.

    The time-out is session pacing and is scaled by the clock, so at CLOCK_SPEED the runner has
    a small fraction of it in real seconds. A run that hit it would still be valid data, but not
    the session this validator means to check, and its produced pressure would differ from a
    repeat run's.
    """
    return [f"touchcal_adjust line {number}: timed out"
            for number, row in enumerate(tables.rows["touchcal_adjust"], start=2)
            if row["timed_out"] == "true"]


def check_adjustment_reached_target(tables: Tables, **_) -> list[str]:
    """Each adjustment ends where the virtual participant pressed for.

    The participant taps from the start to the pressure it settles on, so the control must
    deliver exactly that. A lost tap shows here as a pressure one step short -- which is how a
    tap timed by handler calls rather than by its events first showed up (tatp/touchcal.py).
    """
    loaded = cfg.load("sv", "en")
    touch = loaded.study1["touch_calibration"]
    step_kpa = float(loaded.hardware["adjustment"]["tap_step_kpa"])
    key_for = {float(pct): key for pct, key in
               zip(touch["anchors_pct"], touch["anchor_prompt_keys"], strict=True)}
    model = VirtualParticipant(random.Random())
    failures = []
    for number, row in enumerate(tables.rows["touchcal_adjust"], start=2):
        settled = model.settled_kpa(key_for[float(row["anchor_percent"])])
        start = float(row["start_pressure_kpa"])
        # Where whole taps land: the participant cannot tap to a point between steps.
        target = start + round((settled - start) / step_kpa) * step_kpa
        if float(row["produced_pressure_kpa"]) != target:
            failures.append(f"touchcal_adjust line {number}: produced "
                            f"{row['produced_pressure_kpa']} kPa, the participant pressed for "
                            f"{target}")
    return failures


def check_blinding_text(**_) -> list[str]:
    return blinding.violations()


def check_blocks_record_planned_and_actual(tables: Tables, **_) -> list[str]:
    started = [r for r in tables.rows["log"] if r["event"] == "block_started"]
    if not started:
        return ["log: no block_started event"]
    return [f"log: block {r['block_index']} started without planned and actual offsets: "
            f"{r['detail']!r}" for r in started
            if "planned" not in r["detail"] or "against plan" not in r["detail"]]


CHECKS = {
    "tables_present": check_tables_present,
    "columns_match_schema": check_columns_match_schema,
    "required_fields_present": check_required_fields_present,
    "values_match_types": check_values_match_types,
    "session_keys_complete": check_session_keys_complete,
    "provenance_populated": check_provenance_populated,
    "allocation_matches": check_allocation_matches,
    "timestamps_monotonic": check_timestamps_monotonic,
    "pinprick_filament_is_listed": check_pinprick_filament_is_listed,
    "no_adjustment_timed_out": check_no_adjustment_timed_out,
    "adjustment_reached_target": check_adjustment_reached_target,
    "repeat_run_is_identical": check_repeat_run_is_identical,
    "blinding_text": check_blinding_text,
    "blocks_record_planned_and_actual": check_blocks_record_planned_and_actual,
}


# The tables each check reads. Every one is in PRODUCED, so an absent one is a failure of that
# check -- reported against it, not a crash that hides every check after it.
NEEDS = {
    "session_keys_complete": ("session",),
    "provenance_populated": ("session",),
    "allocation_matches": ("session",),
    "timestamps_monotonic": ("log",),
    "pinprick_filament_is_listed": ("pinprick",),
    "no_adjustment_timed_out": ("touchcal_adjust",),
    "adjustment_reached_target": ("touchcal_adjust",),
    "repeat_run_is_identical": TRIAL_TABLES,
    "blocks_record_planned_and_actual": ("log",),
}


# Checks run once rather than per run: one compares the two runs, the other reads configuration
# rather than data.
ONCE = ("repeat_run_is_identical", "blinding_text")


@dataclass(frozen=True)
class Result:
    name: str
    status: str  # "pass", "fail" or "skip"
    messages: tuple[str, ...]


def check(tables: Tables, repeat: Tables) -> list[Result]:
    assert not set(CHECKS) & set(DEFERRED), "a check cannot be both built and deferred"
    assert set(NEEDS) <= set(CHECKS), f"NEEDS names unknown checks: {set(NEEDS) - set(CHECKS)}"
    # The deferral's reason is that the value is null. Once S sets it, the skip would be a lie.
    tolerance = cfg.load("sv", "en").study1["cues"]["interval_tolerance_s"]
    assert tolerance is None or "intervals_within_tolerance" not in DEFERRED, (
        "cues.interval_tolerance_s is set, so intervals_within_tolerance must now be written"
    )
    runs = (("first run", tables), ("repeat run", repeat))
    results = []
    for name, function in CHECKS.items():
        absent = [f"{where}: needs table {table!r}, which was not written"
                  for table in NEEDS.get(name, ())
                  for where, read in runs
                  if table not in read.rows]
        if absent:
            failures = absent
        elif name in ONCE:
            failures = function(tables=tables, repeat=repeat)
        else:
            # Both runs are sessions, and a defect that shows in one of them only is still one.
            failures = [f"{where}: {message}" for where, read in runs
                        for message in function(tables=read)]
        results.append(Result(name, "fail" if failures else "pass", tuple(failures)))
    results += [Result(name, "skip", (reason,)) for name, reason in DEFERRED.items()]
    return results


def report(results: list[Result]) -> str:
    lines = []
    for result in results:
        lines.append(f"{result.status.upper():4}  {result.name}")
        lines += [f"      {message}" for message in result.messages]
    counts = {status: sum(r.status == status for r in results)
              for status in ("pass", "fail", "skip")}
    lines.append(f"{len(results)} checks: {counts['pass']} passed, {counts['fail']} failed, "
                 f"{counts['skip']} skipped")
    return "\n".join(lines)


# -- entry point -------------------------------------------------------------------------


def _fresh(folder: Path) -> Path:
    # The folder is deleted wholesale, so it must be one this tool owns.
    assert folder.resolve().is_relative_to((REPO_ROOT / "data").resolve()), (
        f"{folder} is not under data/; refusing to clear it"
    )
    if folder.exists():
        shutil.rmtree(folder)
    return folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the slice headless and check its data.")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER,
                        help="where to write; cleared first, and must be under data/")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    _fresh(args.folder)
    first = run(args.folder / "first", args.seed)
    second = run(args.folder / "second", args.seed)
    if not (first.completed and second.completed):
        print("FAIL  the slice ended without completing (emergency stop or abort)")
        return 1

    results = check(Tables.read(first.folder), Tables.read(second.folder))
    print(report(results))
    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
