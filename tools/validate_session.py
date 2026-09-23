"""The end-to-end validator. SPEC.md 17.3.

Two halves, as SPEC.md 17.3 builds it.

**The runner** drives `run_session.py`'s own path -- `run_session.build()`, then the event
loop -- headless, with an accelerated clock, the mock garment, a virtual participant and a
virtual experimenter (`sim/`), into a temporary data folder. It runs the session several times:
a normal participant three times (twice with one seed and once with another, for the seed
check), then each adversarial participant once. An exception anywhere in the run, or a run
that does not finish, is recorded and fails the first check rather than being lost in Qt's
stderr.

**The checker** is a list of named assertions, each declaring what it needs. An assertion whose
precondition is absent is reported `skipped: <reason>` and counted, never passed silently
(SPEC.md 17.3). Some assertions are not written yet because the thing they check does not exist;
those have no body, and **if their precondition ever turns up while they still have none, they
fail** -- so the milestone that builds the thing cannot land without writing the check.

The schema is parsed from `docs/DATA_SCHEMA.md` through `tatp/datafiles.py`, never restated
here, and the SPEC.md 16 text check is `tatp/blinding.py`, the code the unit test runs.

Run it with `make validate`. It exits non-zero on any failure.

Qt must render without a display, exactly as in `tests/conftest.py`, and the platform is set
here rather than on the command line for the same reasons (see `tools/shots.py`).
"""

from __future__ import annotations

import csv
import math
import os
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402 -- the platform must be set before Qt loads
from PySide6.QtWidgets import QApplication  # noqa: E402

import run_session  # noqa: E402
from sim.experimenters import RESUME_AFTER_S, VirtualExperimenter  # noqa: E402
from sim.responders import (  # noqa: E402
    ConfirmsWithoutMarker,
    HoldsAdjustmentAtMaximum,
    StopsAtMaximum,
    StopsMidBlock,
    StopsResponding,
    VirtualParticipant,
)
from tatp import allocation as alloc  # noqa: E402
from tatp import blinding, provenance  # noqa: E402
from tatp import config as cfg  # noqa: E402
from tatp.clock import ISO_FORMAT  # noqa: E402
from tatp.config import CONFIG_DIR, REPO_ROOT, hash_files  # noqa: E402
from tatp.datafiles import parse_schema  # noqa: E402
from tatp.ui.application import application  # noqa: E402
from tatp.units import MS_PER_S, S_PER_MIN  # noqa: E402

# -- the run --------------------------------------------------------------------------------

# Every session-paced interval runs this many times faster. Kept modest because the interval
# check below measures real timers, and the gate runs this alongside the whole test suite.
CLOCK_SPEED = 10.0
SEED = 20260923
PARTICIPANT = "01"
SESSION_NUMBER = 1
EXPERIMENTER = "VE"
PATTERNS = CONFIG_DIR / "patterns" / "examples"
# Real seconds before a run that has not finished is abandoned and reported.
RUN_TIMEOUT_S = 90.0
VALIDATOR_ABORT = "validator: the run did not finish"

# Session seconds from a stop to the resume, for the experimenter who resumes at once. The rate
# limit shapes a restore only when it follows the stop by less than the ceiling divided by the
# rate limit, about 4 s with today's hardware.yaml, less the warning cue's lead.
QUICK_RESUME_S = 1.0

NORMAL = "normal"
SAME_SEED = "normal_same_seed"
OTHER_SEED = "normal_other_seed"
# (name, participant, seed, the experimenter's resume delay in session seconds)
SCENARIOS: tuple[tuple[str, type[VirtualParticipant], int, float], ...] = (
    (NORMAL, VirtualParticipant, SEED, RESUME_AFTER_S),
    (SAME_SEED, VirtualParticipant, SEED, RESUME_AFTER_S),
    (OTHER_SEED, VirtualParticipant, SEED + 1, RESUME_AFTER_S),
    ("confirms_without_marker", ConfirmsWithoutMarker, SEED, RESUME_AFTER_S),
    ("stops_mid_block", StopsMidBlock, SEED, RESUME_AFTER_S),
    ("holds_adjustment_at_maximum", HoldsAdjustmentAtMaximum, SEED, RESUME_AFTER_S),
    ("stops_at_maximum", StopsAtMaximum, SEED, QUICK_RESUME_S),
    ("stops_responding", StopsResponding, SEED, RESUME_AFTER_S),
)
ADVERSARIAL = tuple(scenario[0] for scenario in SCENARIOS[3:])

# -- what the checks compare against ------------------------------------------------------

# The tables the Milestone 1 slice writes. Grows as the runner drives more of the session;
# every table in the schema is required once it drives the whole of it (Milestone 5).
SLICE_TABLES = (
    "session", "log", "blocks", "garment", "touchcal_adjust", "touch_ratings", "pinprick",
)
# What identifies a trial in each trial table, for the seed check: the plan, never the
# response. A pressure the participant produced depends on timer timing, so it is left out.
TRIAL_ORDER_COLUMNS = {
    "pinprick": (
        "phase", "block_index", "protocol", "region", "trial_index", "purpose",
        "filament_label_g", "site_index",
    ),
    "brush": ("phase", "region", "trial_index", "site_index"),
    "touchcal_adjust": (
        "stage", "channel", "reference_channel", "anchor_percent", "adjustment_index",
        "start_direction",
    ),
    "touch_ratings": ("phase", "block_index", "scale"),
    "touchcal_estimate": (
        "channel", "run_index", "presentation_order", "amplitude_index", "catch_trial",
    ),
    "touchcal_compare": (
        "channel", "reference_channel", "comparison_index", "order", "catch_trial",
    ),
}
# A timer-driven interval may run this fraction long or short of its configured length.
INTERVAL_TOLERANCE_FRACTION = 0.2
# Float columns round-trip through text, so equal values compare within this.
FLOAT_TOLERANCE = 1e-6


# -- the runner ---------------------------------------------------------------------------


@dataclass
class Run:
    """One session's files and what the virtual people did in it."""

    name: str
    seed: int
    config: cfg.Config
    completed: bool
    failure: str
    write_failures: int
    headers: dict[str, list[str]]
    rows: dict[str, list[dict[str, str]]]
    ragged: dict[str, int]
    session_keys: list[str]
    session: dict[str, str]
    schedule_offsets_min: dict[int, float]
    participant_seen: set[str]
    experimenter_seen: set[str]
    stats: dict
    # The runner drives the Milestone 1 slice. Set when it drives the whole schedule
    # (Milestone 5), which is what turns the full-grid checks live.
    full_session: bool = False

    def events(self) -> list[dict[str, str]]:
        return self.rows.get("log", [])


def run_one(
    name: str,
    participant_class: type[VirtualParticipant],
    seed: int,
    resume_after_s: float,
    folder: Path,
    loaded: cfg.Config,
) -> Run:
    """One session, start to finish, through `run_session.build()` and the event loop."""
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"], "folder": str(folder)}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    args = run_session.parse_args(
        [
            "--participant", PARTICIPANT,
            "--session", str(SESSION_NUMBER),
            "--experimenter", EXPERIMENTER,
            "--patterns", str(PATTERNS),
            "--participant-language", loaded.participant_language,
            "--experimenter-language", loaded.experimenter_language,
            "--clock-speed", str(CLOCK_SPEED),
            "--seed", str(seed),
        ]
    )
    app = QApplication.instance()
    runner = run_session.build(config, args)
    rig, session = runner.rig, runner.session
    participant = participant_class(rig.participant, session.garment, config, seed)
    experimenter = VirtualExperimenter(rig, participant, resume_after_s)

    errors: list[str] = []

    def on_exception(kind, value, trace) -> None:
        # PySide prints an exception raised in a slot and carries on, which would make a
        # failure a line of stderr and a run that looks fine. Recorded, and the run ends.
        errors.append("".join(traceback.format_exception(kind, value, trace)).strip())
        app.quit()

    def on_timeout() -> None:
        errors.append(f"did not finish within {RUN_TIMEOUT_S:g} s")
        app.quit()

    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(on_timeout)
    previous_hook = sys.excepthook
    sys.excepthook = on_exception
    try:
        guard.start(int(RUN_TIMEOUT_S * MS_PER_S))
        participant.start()
        experimenter.start()
        runner.start()
        app.exec()
    finally:
        sys.excepthook = previous_hook
        guard.stop()
        participant.stop()
        experimenter.stop()
    if not session.closed:
        session.close(VALIDATOR_ABORT)

    headers, rows, ragged = {}, {}, {}
    for table in session.files.tables:
        path = session.files.path(table)
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            lines = list(csv.reader(handle))
        headers[table] = lines[0]
        body = lines[1:]
        ragged[table] = sum(len(line) != len(lines[0]) for line in body)
        rows[table] = [dict(zip(lines[0], line, strict=False)) for line in body]
    session_rows = rows.get("session", [])

    made = Run(
        name=name,
        seed=seed,
        config=config,
        completed=runner.completed,
        failure="\n".join(errors),
        write_failures=session.files.write_failures,
        headers=headers,
        rows=rows,
        ragged=ragged,
        session_keys=[row["key"] for row in session_rows],
        session={row["key"]: row["value"] for row in session_rows},
        schedule_offsets_min={b.index: b.planned_offset_min for b in session.schedule.blocks},
        participant_seen=set(participant.seen_text),
        experimenter_seen=set(experimenter.seen_text),
        stats={**participant.stats(), "resumes": experimenter.resumes},
    )
    for widget in (rig.participant, rig.experimenter):
        widget.close()
        widget.deleteLater()
    app.processEvents()
    return made


def run_all(loaded: cfg.Config, root: Path) -> dict[str, Run]:
    return {
        name: run_one(name, participant_class, seed, resume_after_s, root / name, loaded)
        for name, participant_class, seed, resume_after_s in SCENARIOS
    }


# -- the checker ----------------------------------------------------------------------------

PASSED, SKIPPED, FAILED = "passed", "skipped", "failed"


@dataclass(frozen=True)
class Check:
    """One named assertion.

    `needs` returns None when its precondition holds, otherwise the reason it does not.
    `run` returns the failures, empty when the check passes. A check with no `run` is one the
    spec asks for whose subject does not exist yet.
    """

    name: str
    needs: Callable[[dict[str, Run]], str | None]
    run: Callable[[dict[str, Run]], list[str]] | None


@dataclass
class Result:
    name: str
    status: str
    detail: list[str] = field(default_factory=list)


def evaluate(checks: list[Check], runs: dict[str, Run]) -> list[Result]:
    results = []
    for check in checks:
        reason = check.needs(runs)
        if reason is not None:
            results.append(Result(check.name, SKIPPED, [reason]))
        elif check.run is None:
            results.append(
                Result(
                    check.name,
                    FAILED,
                    ["its precondition now holds, but the check has not been written"],
                )
            )
        else:
            failures = check.run(runs)
            results.append(Result(check.name, FAILED if failures else PASSED, failures))
    return results


def summary(results: list[Result]) -> str:
    passed = sum(r.status == PASSED for r in results)
    skipped = [r for r in results if r.status == SKIPPED]
    failed = sum(r.status == FAILED for r in results)
    # Grouped by reason, since one missing milestone usually accounts for several checks.
    by_reason: dict[str, list[str]] = {}
    for result in skipped:
        by_reason.setdefault(result.detail[0], []).append(result.name)
    reasons = "; ".join(f"{reason} [{', '.join(names)}]" for reason, names in by_reason.items())
    line = f"{passed} passed, {len(skipped)} skipped"
    if skipped:
        line += f" ({reasons})"
    if failed:
        line += f", {failed} failed"
    return line


def exit_code(results: list[Result]) -> int:
    """Non-zero on any failure. A skip is not a failure; it is counted and printed instead."""
    return 1 if any(r.status == FAILED for r in results) else 0


def report(results: list[Result]) -> str:
    lines = []
    for result in results:
        if result.status == PASSED:
            lines.append(f"PASS {result.name}")
        elif result.status == SKIPPED:
            lines.append(f"SKIP {result.name}: {result.detail[0]}")
        else:
            lines.append(f"FAIL {result.name}")
            lines.extend(
                f"     {line}" for detail in result.detail for line in detail.split("\n")
            )
    lines.append(summary(results))
    return "\n".join(lines)


# -- helpers ----------------------------------------------------------------------------------

SCHEMA, SESSION_KEYS = parse_schema()


def _always(runs) -> None:
    return None


def _normal_runs(runs: dict[str, Run]) -> list[Run]:
    return [runs[name] for name in (NORMAL, SAME_SEED, OTHER_SEED)]


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=FLOAT_TOLERANCE, abs_tol=FLOAT_TOLERANCE)


def _iso(value: str) -> datetime:
    return datetime.strptime(value, ISO_FORMAT)


def _parses(value: str, type_name: str) -> bool:
    if type_name == "int":
        return value.lstrip("-").isdigit()
    if type_name == "float":
        try:  # the one question `float()` can answer only by raising
            return math.isfinite(float(value))
        except ValueError:
            return False
    if type_name == "bool":
        return value in ("true", "false")
    if type_name == "iso8601":
        try:
            _iso(value)
        except ValueError:
            return False
        return True
    return True


def _trial_order(run: Run) -> list[tuple]:
    for table, columns in TRIAL_ORDER_COLUMNS.items():
        unknown = set(columns) - set(SCHEMA[table].column_names)
        assert not unknown, f"TRIAL_ORDER_COLUMNS[{table!r}] names {sorted(unknown)}"
    trials = [
        (row["timestamp_iso"], table, *(row[c] for c in columns))
        for table, columns in TRIAL_ORDER_COLUMNS.items()
        for row in run.rows.get(table, [])
    ]
    return [trial[1:] for trial in sorted(trials)]


def _event_names(run: Run) -> list[str]:
    return [row["event"] for row in run.events()]


def _counts(run: Run) -> dict[str, int]:
    return {table: len(run.rows.get(table, [])) for table in (*TRIAL_ORDER_COLUMNS, "blocks")}


# -- the checks: the data files -------------------------------------------------------------


def check_runs_completed(runs):
    failures = []
    for run in runs.values():
        if run.failure:
            failures.append(f"{run.name}: {run.failure}")
        elif not run.completed:
            failures.append(f"{run.name}: the session did not reach its end")
        if run.write_failures:
            failures.append(f"{run.name}: {run.write_failures} data writes failed")
        if run.session.get("abort_reason"):
            failures.append(f"{run.name}: aborted ({run.session['abort_reason']})")
    return failures


def check_slice_tables_written(runs):
    return [
        f"{run.name}: no {table} file"
        for run in runs.values()
        for table in SLICE_TABLES
        if table not in run.headers
    ]


def check_columns_match_schema(runs):
    failures = []
    for run in runs.values():
        for table, header in run.headers.items():
            expected = list(SCHEMA[table].column_names)
            if header != expected:
                failures.append(f"{run.name}: {table} columns {header}, schema {expected}")
            if run.ragged[table]:
                failures.append(
                    f"{run.name}: {table} has {run.ragged[table]} rows of the wrong width"
                )
    return failures


def check_required_values_present(runs):
    failures = []
    for run in runs.values():
        for table, rows in run.rows.items():
            for column in SCHEMA[table].columns:
                if not column.required:
                    continue
                empty = [i for i, row in enumerate(rows, start=1) if not row.get(column.name)]
                if empty:
                    failures.append(
                        f"{run.name}: {table}.{column.name} empty in {len(empty)} rows "
                        f"(first: row {empty[0]})"
                    )
    return failures


def check_values_parse_as_schema_types(runs):
    failures = []
    for run in runs.values():
        for table, rows in run.rows.items():
            for column in SCHEMA[table].columns:
                bad = [
                    row[column.name]
                    for row in rows
                    if row.get(column.name) and not _parses(row[column.name], column.type)
                ]
                if bad:
                    failures.append(
                        f"{run.name}: {table}.{column.name} is {column.type}, but holds "
                        f"{bad[0]!r} ({len(bad)} rows)"
                    )
    return failures


def check_condition_and_limb_match_allocation(runs):
    failures = []
    for run in runs.values():
        design = run.config.study1["design"]
        path = Path(design["allocation_file"])
        path = path if path.is_absolute() else REPO_ROOT / path
        allocation = alloc.load(
            path, design["conditions"], design["limbs"], design["n_sessions"]
        )
        assignment = allocation.get(
            run.session["participant_code"], int(run.session["session_number"])
        )
        # Which condition, never: the validator's output is read on the lab PC too (SPEC.md 16).
        if run.session["condition"] != assignment.condition:
            failures.append(f"{run.name}: the condition differs from the allocation file")
        if run.session["limb"] != assignment.limb:
            failures.append(f"{run.name}: the limb differs from the allocation file")
        if run.session["allocation_sha256"] != hash_files([path]):
            failures.append(f"{run.name}: allocation_sha256 is not the file's hash")
    return failures


def check_timestamps_monotonic(runs):
    failures = []
    for run in runs.values():
        for table, rows in run.rows.items():
            if "timestamp_iso" not in SCHEMA[table].column_names:
                continue
            stamps = [_iso(row["timestamp_iso"]) for row in rows]
            backwards = [i for i in range(1, len(stamps)) if stamps[i] < stamps[i - 1]]
            if backwards:
                failures.append(f"{run.name}: {table} timestamp_iso goes back at row "
                                f"{backwards[0] + 1}")
            # The log and the garment table are written as things happen, so their session
            # times run forward too. A trial table is stamped at the trial's start.
            if table in ("log", "garment"):
                times = [float(row["t_session_s"]) for row in rows if row["t_session_s"]]
                if any(b < a for a, b in zip(times, times[1:], strict=False)):
                    failures.append(f"{run.name}: {table} t_session_s goes back")
        events = run.events()
        started = [i for i, row in enumerate(events) if row["event"] == "sensitisation_started"]
        if len(started) != 1:
            failures.append(f"{run.name}: {len(started)} sensitisation_started events")
            continue
        early = [row["event"] for row in events[: started[0]] if row["t_session_s"]]
        late = [row["event"] for row in events[started[0]:] if not row["t_session_s"]]
        if early:
            failures.append(f"{run.name}: t_session_s set before session t=0 on {early[0]}")
        if late:
            failures.append(f"{run.name}: t_session_s empty after session t=0 on {late[0]}")
        for row in run.rows.get("pinprick", []):
            cued = row["rating_cue_iso"]
            if cued and _iso(cued) < _iso(row["cue_onset_iso"]):
                failures.append(f"{run.name}: pinprick rating cued before its warning cue")
    return failures


def needs_pinprick_rows(runs):
    if not runs[NORMAL].rows.get("pinprick"):
        return "the normal run wrote no pinprick rows"
    return None


def check_rating_cue_interval(runs):
    """Warning cue to rating cue: the cue lead plus the 9 s delay (SPEC.md 10.5, 8)."""
    failures = []
    for run in runs.values():
        study = run.config.study1
        expected_s = (
            float(study["cues"]["warning_lead_s"])
            + float(study["pinprick"]["rating_cue_delay_s"])
        ) / float(run.session["clock_speed"])
        for row in run.rows.get("pinprick", []):
            if not row["rating_cue_iso"]:
                continue
            took_s = (_iso(row["rating_cue_iso"]) - _iso(row["cue_onset_iso"])).total_seconds()
            if abs(took_s - expected_s) > INTERVAL_TOLERANCE_FRACTION * expected_s:
                failures.append(
                    f"{run.name}: trial {row['trial_index']} rating cued {took_s:.3f} s after "
                    f"its warning cue, expected {expected_s:.3f} s real"
                )
    return failures


def needs_two_applications_in_a_run(runs):
    runs_of = {}
    for row in runs[NORMAL].rows.get("pinprick", []):
        key = (row["phase"], row["protocol"], row["region"])
        runs_of[key] = runs_of.get(key, 0) + 1
    if not any(count > 1 for count in runs_of.values()):
        return ("no protocol run has two applications yet, so there is no inter-stimulus "
                "interval to time (Milestone 3)")
    return None


def check_blocks_planned_against_actual(runs):
    failures = []
    for run in runs.values():
        blocks = run.rows.get("blocks", [])
        started = _event_names(run).count("block_started")
        if len(blocks) != started:
            failures.append(f"{run.name}: {started} blocks started, {len(blocks)} block rows")
        for row in blocks:
            index = int(row["block_index"])
            planned = float(row["planned_offset_min"])
            start_s, end_s = float(row["started_t_session_s"]), float(row["ended_t_session_s"])
            if index not in run.schedule_offsets_min:
                failures.append(f"{run.name}: block {index} is not in the schedule")
                continue
            if not _close(planned, run.schedule_offsets_min[index]):
                failures.append(f"{run.name}: block {index} planned offset is not the plan's")
            if not _close(float(row["lateness_min"]), start_s / S_PER_MIN - planned):
                failures.append(f"{run.name}: block {index} lateness is not start minus plan")
            if end_s < start_s:
                failures.append(f"{run.name}: block {index} ends before it starts")
            if not _close(float(row["actual_duration_min"]), (end_s - start_s) / S_PER_MIN):
                failures.append(f"{run.name}: block {index} duration is not end minus start")
            if row["aborted"] != "false" and run.completed:
                failures.append(f"{run.name}: block {index} marked aborted in a completed run")
    return failures


def needs_the_seed_to_matter(runs):
    orders = [_trial_order(run) for run in _normal_runs(runs)]
    if not orders[0]:
        return "the normal run recorded no trials"
    if orders[0] == orders[1] == orders[2]:
        return ("trial order is identical under two different seeds, so nothing the seed "
                "controls is in it yet (site rotation, jitter and estimation order: "
                "Milestones 3 and 4)")
    return None


def check_same_seed_same_trial_order(runs):
    first, second = _trial_order(runs[NORMAL]), _trial_order(runs[SAME_SEED])
    if first == second:
        return []
    differ = next(
        (i for i, (a, b) in enumerate(zip(first, second, strict=False)) if a != b),
        min(len(first), len(second)),
    )
    return [f"seed {SEED} gave two trial orders; they differ from trial {differ + 1}"]


def check_forces_are_listed_filaments(runs):
    failures = []
    for run in runs.values():
        filaments = {f["label_g"]: f for f in run.config.filaments["filaments"]}
        for row in run.rows.get("pinprick", []):
            for column in ("filament_label_g", "applied_filament_label_g"):
                if row[column] not in filaments:
                    failures.append(f"{run.name}: pinprick {column} {row[column]!r} is not "
                                    f"in filaments.yaml")
            applied = filaments.get(row["applied_filament_label_g"])
            if applied is None:
                continue
            measured = applied["force_measured_mn"]
            if not _close(float(row["force_nominal_mn"]), applied["force_nominal_mn"]):
                failures.append(f"{run.name}: pinprick force_nominal_mn is not the filament's")
            if (row["force_measured_mn"] or None) != (None if measured is None else str(
                float(measured)
            )):
                failures.append(f"{run.name}: pinprick force_measured_mn is not the filament's")
            fitted = applied["force_nominal_mn"] if measured is None else measured
            if not _close(float(row["force_applied_mn"]), fitted):
                failures.append(f"{run.name}: pinprick force_applied_mn is not the filament's")
        for row in run.rows.get("calibration_pinprick", []):
            chosen = filaments.get(row["chosen_filament_label_g"])
            if chosen is None:
                failures.append(f"{run.name}: calibrated filament "
                                f"{row['chosen_filament_label_g']!r} is not in filaments.yaml")
                continue
            forces = [chosen["force_nominal_mn"], chosen["force_measured_mn"]]
            if not any(f is not None and _close(float(row["chosen_force_mn"]), f)
                       for f in forces):
                failures.append(f"{run.name}: calibrated chosen_force_mn is not the "
                                f"filament's force")
    return failures


def needs_calibration_rows(runs):
    if not runs[NORMAL].rows.get("calibration_pinprick"):
        return "no calibration_pinprick rows: the long protocol is Milestone 3"
    return None


def needs_full_session(runs):
    if not runs[NORMAL].full_session:
        return ("the runner drives the Milestone 1 slice, one block, not the full schedule "
                "(Milestone 5)")
    return None


# A session key may be empty only when its reason holds for the run. Every other key must have
# a value. The reasons are the validator's, and each is checked rather than assumed.
MAY_BE_EMPTY: dict[str, tuple[str, Callable[[Run], bool]]] = {
    "screenshot_freeze_sha": (
        "no screenshot freeze yet", lambda run: not provenance.screenshot_freeze_sha()
    ),
    "filament_calibration_date": (
        "the set is unweighed", lambda run: run.config.filaments["weighing_date"] is None
    ),
    "room_temperature_c": ("optional, and the runner enters none", lambda run: True),
    "relative_humidity_pct": ("optional, and the runner enters none", lambda run: True),
    "white_noise_level_dbfs": (
        "the masking check has not run", lambda run: run.session["masking_attempts"] == "0"
    ),
    "masking_confirmed": (
        "the masking check has not run", lambda run: run.session["masking_attempts"] == "0"
    ),
    "cloud_sync_warning": (
        "the data folder is not synced",
        lambda run: not provenance.cloud_sync_warning(
            Path(run.session["data_folder"]), run.config.hardware["data"]["cloud_sync_markers"]
        ),
    ),
    "unresolved_open_items": ("every open item is resolved",
                              lambda run: not run.config.unresolved),
    "resumed_from_session_file": ("the runner never resumes", lambda run: True),
    "abort_reason": ("the run was not aborted", lambda run: run.completed),
}


def check_provenance_populated(runs):
    failures = []
    stale = set(MAY_BE_EMPTY) - set(SESSION_KEYS)
    if stale:
        failures.append(f"MAY_BE_EMPTY names keys the schema does not have: {sorted(stale)}")
    for run in runs.values():
        if run.session_keys != list(SESSION_KEYS):
            failures.append(f"{run.name}: session keys are not every schema key once, in order")
        for key in SESSION_KEYS:
            if run.session.get(key):
                continue
            allowed = MAY_BE_EMPTY.get(key)
            if allowed is None:
                failures.append(f"{run.name}: session {key} is empty")
            elif not allowed[1](run):
                failures.append(f"{run.name}: session {key} is empty, but not because "
                                f"{allowed[0]}")
    return failures


def check_text_files_blinding(runs):
    return blinding.violations()


def check_screens_showed_nothing_forbidden(runs):
    """What the virtual people actually read off both screens during every run (SPEC.md 16)."""
    failures = []
    labels = blinding.conditions()
    forbidden = blinding.forbidden_terms()
    for run in runs.values():
        if not run.participant_seen or not run.experimenter_seen:
            failures.append(f"{run.name}: a virtual person read nothing off the screen")
        patterns = run.session["pattern_names"].split(";")
        both = [t.lower() for t in labels + patterns]
        for role, seen, terms in (
            ("participant", run.participant_seen, both + [t.lower() for t in forbidden]),
            ("experimenter", run.experimenter_seen, both),
        ):
            for text in sorted(seen):
                hits = [term for term in terms if term in text.lower()]
                if hits:
                    failures.append(f"{run.name}: the {role} screen showed {hits} in {text!r}")
    return failures


# -- the checks: the adversarial participants ------------------------------------------------


def check_confirm_without_marker_is_logged(runs):
    run = runs["confirms_without_marker"]
    pressed = run.stats["empty_confirms"]
    logged = [row for row in run.events() if row["event"] == "confirm_without_marker"]
    failures = []
    if not pressed:
        failures.append("the participant never confirmed without a marker")
    if len(logged) != pressed:
        failures.append(f"{pressed} confirms without a marker, {len(logged)} logged")
    if any(row["origin"] != "participant" for row in logged):
        failures.append("a confirm_without_marker row is not of participant origin")
    for table in ("touch_ratings", "pinprick"):
        if any(not row["rating_percent"] for row in run.rows.get(table, [])):
            failures.append(f"a {table} row has no rating: an empty confirm was recorded")
    return failures


def check_emergency_stop_mid_block_resumes(runs):
    run = runs["stops_mid_block"]
    failures = []
    if run.stats["stops"] != 1:
        failures.append(f"the participant pressed the stop {run.stats['stops']} times, not 1")
    events = run.events()
    stops = [i for i, row in enumerate(events) if row["event"] == "emergency_stop"]
    if len(stops) != 1:
        return [*failures, f"{len(stops)} emergency_stop events logged"]
    stop = events[stops[0]]
    if not stop["block_index"] or stop["phase"] != "intervention":
        failures.append("the stop was not logged inside the intervention block")
    if stop["origin"] != "participant":
        failures.append("the stop is not logged as the participant's")
    after = [row["event"] for row in events[stops[0]:]]
    wanted = ["trial_cancelled", "resumed", "step_repeated"]
    positions = [after.index(e) if e in after else -1 for e in wanted]
    if -1 in positions or positions != sorted(positions):
        failures.append(f"after the stop, expected {wanted} in order")
    stop_s = float(stop["t_session_s"])
    zeroed = [row for row in run.rows.get("garment", [])
              if row["event"] == "stop" and row["t_session_s"]
              and float(row["t_session_s"]) <= stop_s]
    if not zeroed:
        failures.append("no garment stop was commanded by the time the stop was logged")
    if run.stats["resumes"] != 1:
        failures.append(f"the experimenter resumed {run.stats['resumes']} times, not 1")
    return failures


def check_adjustment_held_at_maximum_stops_at_ceiling(runs):
    run = runs["holds_adjustment_at_maximum"]
    ceiling = float(run.config.hardware["garment"]["pressure_ceiling_kpa"])
    failures = []
    if run.stats["held_at_ceiling_s"] < HoldsAdjustmentAtMaximum.OVERHOLD_S:
        failures.append("the participant never held the button at the ceiling")
    adjusted = run.rows.get("touchcal_adjust", [])
    if len(adjusted) != 1:
        return [*failures, f"{len(adjusted)} touchcal_adjust rows"]
    produced = float(adjusted[0]["produced_pressure_kpa"])
    if not _close(produced, ceiling):
        failures.append(f"held at maximum, the adjustment produced {produced} kPa, "
                        f"not the {ceiling} kPa ceiling")
    over = [row for row in run.rows.get("garment", [])
            if row["pressure_kpa"] and float(row["pressure_kpa"]) > ceiling]
    if over:
        failures.append(f"{len(over)} garment commands above the ceiling")
    return failures


def check_restore_after_stop_is_rate_limited(runs):
    run = runs["stops_at_maximum"]
    ceiling = float(run.config.hardware["garment"]["pressure_ceiling_kpa"])
    failures = []
    if run.stats["stops"] != 1:
        failures.append(f"the participant pressed the stop {run.stats['stops']} times, not 1")
    if "restore_rate_limited" not in _event_names(run):
        failures.append("the restore after the stop was not logged as rate limited")
    limited = [row for row in run.rows.get("garment", [])
               if row["event"] == "set_pressure" and row["clamped"] == "true"
               and _close(float(row["requested_kpa"]), ceiling)
               and float(row["pressure_kpa"]) < ceiling]
    if not limited:
        failures.append("no garment command shows the restore to the ceiling clamped")
    if len(run.rows.get("touchcal_adjust", [])) != 1:
        failures.append("the repeated adjustment did not write exactly one row")
    return failures


def check_silent_adjustment_times_out(runs):
    run = runs["stops_responding"]
    failures = []
    if run.stats["ignored_adjustments"] != 1:
        failures.append("the participant did not ignore the adjustment")
    adjusted = run.rows.get("touchcal_adjust", [])
    if len(adjusted) != 1 or adjusted[0]["timed_out"] != "true":
        failures.append("the ignored adjustment did not write one timed_out row")
    if "adjustment_timed_out" not in _event_names(run):
        failures.append("the time-out was not logged")
    return failures


def check_adversaries_lose_no_data(runs):
    expected = _counts(runs[NORMAL])
    return [
        f"{name}: {counts} rows, where the normal run has {expected}"
        for name in ADVERSARIAL
        if (counts := _counts(runs[name])) != expected
    ]


CHECKS: list[Check] = [
    Check("runs_completed", _always, check_runs_completed),
    Check("slice_tables_written", _always, check_slice_tables_written),
    Check("all_schema_tables_written", needs_full_session, None),
    Check("columns_match_schema", _always, check_columns_match_schema),
    Check("required_values_present", _always, check_required_values_present),
    Check("values_parse_as_schema_types", _always, check_values_parse_as_schema_types),
    Check("row_counts_match_schedule", needs_full_session, None),
    Check("scheduled_blocks_in_order", needs_full_session, None),
    Check("condition_and_limb_match_allocation", _always,
          check_condition_and_limb_match_allocation),
    Check("timestamps_monotonic", _always, check_timestamps_monotonic),
    Check("rating_cue_interval_within_tolerance", needs_pinprick_rows,
          check_rating_cue_interval),
    Check("inter_stimulus_interval_within_tolerance", needs_two_applications_in_a_run, None),
    Check("blocks_planned_against_actual", _always, check_blocks_planned_against_actual),
    Check("same_seed_same_trial_order", needs_the_seed_to_matter,
          check_same_seed_same_trial_order),
    Check("forces_are_listed_filaments", needs_pinprick_rows,
          check_forces_are_listed_filaments),
    Check("out_of_range_when_and_only_when", needs_calibration_rows, None),
    Check("provenance_populated", _always, check_provenance_populated),
    Check("text_files_blinding", _always, check_text_files_blinding),
    Check("screens_showed_nothing_forbidden", _always, check_screens_showed_nothing_forbidden),
    Check("confirm_without_marker_is_logged", _always, check_confirm_without_marker_is_logged),
    Check("emergency_stop_mid_block_resumes", _always, check_emergency_stop_mid_block_resumes),
    Check("adjustment_held_at_maximum_stops_at_ceiling", _always,
          check_adjustment_held_at_maximum_stops_at_ceiling),
    Check("restore_after_stop_is_rate_limited", _always,
          check_restore_after_stop_is_rate_limited),
    Check("silent_adjustment_times_out", _always, check_silent_adjustment_times_out),
    Check("adversaries_lose_no_data", _always, check_adversaries_lose_no_data),
]


def main() -> int:
    loaded = cfg.load("sv", "en")
    application(loaded.hardware)
    began_s = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="tatp_validate_") as root:
        runs = run_all(loaded, Path(root))
        results = evaluate(CHECKS, runs)
    print(report(results))
    print(f"validate: {len(runs)} sessions in {time.monotonic() - began_s:.0f} s")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
