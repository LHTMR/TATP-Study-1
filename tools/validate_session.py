"""The end-to-end validator. SPEC.md 17.3.

Two halves, as SPEC.md 17.3 builds it.

**The runner** drives `run_session.py`'s own path -- `run_session.build()`, then the event
loop -- headless, with an accelerated clock, the mock garment, a virtual participant and a
virtual experimenter (`sim/`), each scenario into a temporary data folder of its own. The
normal participant runs one whole session, the full grid of `config/schedule.yaml`, and the
same seed again into the intervention's blocks. Every other scenario runs only as far as its
error path needs and is then ended by the virtual experimenter's abort (`SCENARIO_ENDED`),
because the rest of a session would prove nothing the normal run does not. The adversarial
experimenter's distances need both mapped time points and the session's end, so it runs whole;
session 2 runs in the normal run's folder, to start from its estimate. One scenario crashes
mid-block -- the process stops with the session open -- and the next resumes it from its files
(SPEC.md 15) and runs to the end. The timing scenario, which is also the other seed, runs at
SLOW_CLOCK_SPEED so its intervals can be judged in session seconds. An exception anywhere in a
run, or a run that does not finish, is recorded and fails the first check rather than being
lost in Qt's stderr.

**Speed.** `CLOCK_SPEED` accelerates every session-paced interval. The ceiling on it is the
garment table: every pattern event is a row, appended and flushed (SPEC.md 14.3), and above a
thousand or so times real speed a moving pattern produces rows faster than the disk takes them.
Three settings are then scaled back to real time, because at that speed they would otherwise
describe a different session rather than a faster one: the adjustment time-out (the hand that
adjusts runs in real seconds, `tatp/touchcal.py`), and the choice screen's feedback and gap
(real milliseconds on the screen). The one scenario whose error path *is* the time-out keeps it
as configured.

**The checker** is a list of named assertions, each declaring what it needs. An assertion whose
precondition is absent is reported `skipped: <reason>` and counted, never passed silently
(SPEC.md 17.3). An assertion with no body fails once its precondition turns up.

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
import shutil
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

from PySide6.QtCore import (  # noqa: E402 -- the platform must be set before Qt loads
    QCoreApplication,
    QEvent,
    QTimer,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

import run_session  # noqa: E402
from sim.experimenters import (  # noqa: E402
    RESUME_AFTER_S,
    SCENARIO_ENDED,
    DisconnectsGarment,
    ImplausibleDistances,
    VirtualExperimenter,
)
from sim.responders import (  # noqa: E402
    ConfirmsWithoutMarker,
    F40AboveTop,
    F40BelowBottom,
    HoldsAdjustmentAtMaximum,
    RatesEverythingHundred,
    RatesEverythingZero,
    RatesRandomly,
    StopsAtMaximum,
    StopsMidBlock,
    StopsResponding,
    VirtualParticipant,
)
from tatp import allocation as alloc  # noqa: E402
from tatp import blinding, provenance  # noqa: E402
from tatp import config as cfg  # noqa: E402
from tatp import preflight as pre  # noqa: E402
from tatp.clock import ISO_FORMAT  # noqa: E402
from tatp.config import CONFIG_DIR, REPO_ROOT, hash_files  # noqa: E402
from tatp.datafiles import parse_schema  # noqa: E402
from tatp.pinprick import PAIN_SCALE, prior_for  # noqa: E402
from tatp.ui.application import application  # noqa: E402
from tatp.units import MS_PER_S, S_PER_MIN  # noqa: E402

# -- the run --------------------------------------------------------------------------------

CLOCK_SPEED = 1000.0
SLOW_CLOCK_SPEED = 10.0
SEED = 20260923
PARTICIPANT = "01"
SESSION_NUMBER = 1
EXPERIMENTER = "VE"
PATTERNS = CONFIG_DIR / "patterns" / "examples"
# Real seconds before a run that has not finished is abandoned and reported.
RUN_TIMEOUT_S = 120.0
VALIDATOR_ABORT = "validator: the run did not finish"

# Session seconds from a stop to the resume, for the experimenter who resumes at once. The rate
# limit shapes a restore only when it follows the stop by less than the ceiling divided by the
# rate limit, about 4 s with today's hardware.yaml, less the warning cue's lead.
QUICK_RESUME_S = 1.0

NORMAL = "normal"
SAME_SEED = "normal_same_seed"
OTHER_SEED = "normal_other_seed"
CRASHED = "crashes_mid_block"
RESUMED = "resumed"
DISTANCES = "implausible_distances"
SESSION_TWO = "session_two"
RATES_ZERO = "rates_everything_zero"
RATES_HUNDRED = "rates_everything_hundred"
RATES_RANDOM = "rates_randomly"
DISCONNECTS = "disconnects_garment_then_closes_window"
CLOSED = DISCONNECTS
# The run the timing checks are judged on (docs/LOG.md N7.D15).
TIMING = OTHER_SEED
# Every table a VAS answer is written to.
RATED_TABLES = ("pinprick", "brush", "touch_ratings", "touchcal_estimate")


@dataclass(frozen=True)
class Scenario:
    """One run. The `ends_*` and `crash_*` fields say how a scenario that is not whole ends."""

    name: str
    participant: type[VirtualParticipant] = VirtualParticipant
    seed: int = SEED
    resume_after_s: float = RESUME_AFTER_S
    experimenter: type[VirtualExperimenter] = VirtualExperimenter
    # The experimenter aborts once this stage has completed...
    ends_after_stage: str | None = None
    # ...or once the participant has seen this many adjustment screens.
    ends_after_adjustments: int | None = None
    # The window is closed once this block has started.
    closes_in_block: int | None = None
    # The process stops, leaving the session open, once this block has started.
    crashes_in_block: int | None = None
    # Resume the open session in this scenario's folder instead of starting afresh.
    resumes: str | None = None
    # Keep the adjustment time-out as configured: the scenario that tests it.
    configured_timeout: bool = False
    clock_speed: float = CLOCK_SPEED
    # ...or once the participant has rated this many pinprick applications.
    ends_after_pinprick: int | None = None
    session_number: int = SESSION_NUMBER
    # Run in this scenario's data folder, after it, instead of a folder of its own.
    folder_of: str | None = None
    # study1.yaml sections replaced, key by key, for this scenario only.
    study_overrides: dict = field(default_factory=dict)

    @property
    def ends_early(self) -> bool:
        return (self.ends_after_stage is not None or self.ends_after_adjustments is not None
                or self.ends_after_pinprick is not None)


# The timing scenario's touch calibration, cut to the fewest trials the schema allows: it is
# there only to be got through, at a speed slow enough to time the pinprick intervals by.
QUICK_CALIBRATION = {
    "estimation_n_amplitudes": 3, "channel_match_adjustments": 1,
    "equalisation_pairs_to_flag": 1, "equalisation_readjust_max_passes": 0,
    "pleasantness_adjustments": 1, "evenness_check": False,
}
TIMING_APPLICATIONS = 10

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(NORMAL),
    # Far enough to take in the intervention's blocks; compared with the normal run's prefix.
    Scenario(SAME_SEED, ends_after_stage="block.2"),
    # The other seed, and the timing: slow enough that the configured intervals are tens of
    # milliseconds of real time, so a missing 0.5 s is a measurable 50 ms (docs/LOG.md N7.D15).
    Scenario(OTHER_SEED, seed=SEED + 1, clock_speed=SLOW_CLOCK_SPEED,
             ends_after_pinprick=TIMING_APPLICATIONS,
             study_overrides={"touch_calibration": QUICK_CALIBRATION}),
    Scenario(SESSION_TWO, session_number=2, folder_of=NORMAL,
             ends_after_stage="pre_sensitisation.long"),
    Scenario("confirms_without_marker", ConfirmsWithoutMarker,
             ends_after_stage="pre_sensitisation.brush_primary"),
    Scenario("stops_mid_block", StopsMidBlock, ends_after_stage="block.1"),
    Scenario("holds_adjustment_at_maximum", HoldsAdjustmentAtMaximum, ends_after_adjustments=2),
    # The stop interrupts the first adjustment and its repeat is the second screen. Slower,
    # because the rate limit only shapes a restore that follows the stop closely in session
    # time, and at full speed the event loop's own latency is seconds of it.
    Scenario("stops_at_maximum", StopsAtMaximum, resume_after_s=QUICK_RESUME_S,
             ends_after_adjustments=3, clock_speed=SLOW_CLOCK_SPEED),
    Scenario("stops_responding", StopsResponding, ends_after_adjustments=2,
             configured_timeout=True),
    Scenario("f40_below_bottom", F40BelowBottom, ends_after_stage="pre_sensitisation.long"),
    Scenario("f40_above_top", F40AboveTop, ends_after_stage="pre_sensitisation.long"),
    Scenario(RATES_ZERO, RatesEverythingZero, ends_after_stage="pre_sensitisation.long"),
    Scenario(RATES_HUNDRED, RatesEverythingHundred, ends_after_stage="pre_sensitisation.long"),
    Scenario(RATES_RANDOM, RatesRandomly, ends_after_stage="pre_sensitisation.long"),
    # Disconnects in block 1, reconnects after it, and then the window is closed in block 4:
    # two of SPEC.md 17.5's experimenters in one run.
    Scenario(DISCONNECTS, experimenter=DisconnectsGarment, closes_in_block=4),
    Scenario(DISTANCES, experimenter=ImplausibleDistances),
    Scenario(CRASHED, crashes_in_block=4),
    Scenario(RESUMED, resumes=CRASHED),
)
BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}
FULL = (NORMAL, DISTANCES)
# Normal participants whose trials must all be there, like the normal run's, as far as they go.
LOSSLESS = ("confirms_without_marker", "stops_mid_block", DISTANCES)
# Out of range by design at pre-S, and in which direction.
OUT_OF_RANGE = {"f40_below_bottom": "below", "f40_above_top": "above"}

# Tables a whole normal session may legitimately not write, and why.
MAY_BE_ABSENT = {"discards": "no trial was discarded"}
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
# SESSION seconds a timed interval may be off its configured length. Judged only on the timing
# scenario, at SLOW_CLOCK_SPEED, where this is 25 ms of real time -- above the platform's timer
# resolution, and half of the smallest thing that must not be lost: dropping the 0.5 s between
# the cue and the stimulus moves every interval by 0.5 s and fails. A loaded machine makes a
# timer late, never early, so each check is on the interval the load disturbed least.
TIMING_TOLERANCE_S = 0.25
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
    folder: Path | None = None
    closed: bool = True
    stage_ids: list[str] = field(default_factory=list)

    def events(self) -> list[dict[str, str]]:
        return self.rows.get("log", [])

    @property
    def scenario(self) -> Scenario:
        return BY_NAME.get(self.name, Scenario(self.name))

    def completed_stages(self) -> list[str]:
        return [row["detail"] for row in self.events() if row["event"] == "stage_completed"]


def run_config(loaded: cfg.Config, folder: Path, scenario: Scenario) -> cfg.Config:
    """The configuration a validator run uses: the loaded one, with the harness's changes.

    The data folder is the run's own, the audio is the recording double (there is no sound
    device headless), and the three real-time settings the module docstring names are scaled
    back to real time at `CLOCK_SPEED`.
    """
    hardware = {
        **loaded.hardware,
        "data": {**loaded.hardware["data"], "folder": str(folder)},
        "audio": {**loaded.hardware["audio"], "backend": "recording"},
    }
    speed = scenario.clock_speed
    choice = {key: float(value) / speed for key, value in loaded.study1["choice"].items()}
    touch = dict(loaded.study1["touch_calibration"])
    if not scenario.configured_timeout:
        touch["adjustment_timeout_s"] = float(touch["adjustment_timeout_s"]) * speed
    for key, value in scenario.study_overrides.get("touch_calibration", {}).items():
        touch[key] = value
    study1 = {**loaded.study1, "choice": choice, "touch_calibration": touch}
    return cfg.Config(**{**loaded.__dict__, "hardware": hardware, "study1": study1})


def run_one(scenario: Scenario, folder: Path, loaded: cfg.Config) -> Run:
    """One session, or as much of one as the scenario needs, through `run_session.build()`."""
    config = run_config(loaded, folder, scenario)
    args = run_session.parse_args(
        [
            "--participant", PARTICIPANT,
            "--session", str(scenario.session_number),
            "--experimenter", EXPERIMENTER,
            "--patterns", str(PATTERNS),
            "--participant-language", loaded.participant_language,
            "--experimenter-language", loaded.experimenter_language,
            "--clock-speed", str(scenario.clock_speed),
            "--seed", str(scenario.seed),
        ]
    )
    app = QApplication.instance()
    runner = run_session.build(config, args, lambda _open: scenario.resumes is not None)
    rig, session = runner.rig, runner.session
    participant = scenario.participant(rig.participant, session.garment, config, scenario.seed)

    def ended() -> bool:
        if scenario.ends_after_stage is not None:
            return scenario.ends_after_stage in _completed_now(session)
        if scenario.ends_after_adjustments is not None:
            return participant.adjustments_seen >= scenario.ends_after_adjustments
        if scenario.ends_after_pinprick is not None:
            pain = sum(scale == PAIN_SCALE for scale, _ in participant.ratings)
            return pain >= scenario.ends_after_pinprick
        return False

    experimenter = scenario.experimenter(
        rig, participant, scenario.resume_after_s,
        abort_when=ended if scenario.ends_early else None,
    )
    errors: list[str] = []
    crashed = []

    def on_exception(kind, value, trace) -> None:
        # PySide prints an exception raised in a slot and carries on, which would make a
        # failure a line of stderr and a run that looks fine. Recorded, and the run ends.
        errors.append("".join(traceback.format_exception(kind, value, trace)).strip())
        app.quit()

    def on_timeout() -> None:
        errors.append(f"did not finish within {RUN_TIMEOUT_S:g} s")
        app.quit()

    def watch() -> None:
        # The window closed, or the process gone, mid-block: nothing the software can see
        # coming, so it is the harness that does it.
        if session.block_index is None:
            return
        if session.block_index == scenario.closes_in_block:
            app.quit()
        elif session.block_index == scenario.crashes_in_block:
            crashed.append(True)
            app.quit()

    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(on_timeout)
    watcher = QTimer()
    watcher.setInterval(1)
    watcher.timeout.connect(watch)
    previous_hook = sys.excepthook
    sys.excepthook = on_exception
    try:
        guard.start(int(RUN_TIMEOUT_S * MS_PER_S))
        watcher.start()
        participant.start()
        experimenter.start()
        runner.start()
        app.exec()
    finally:
        sys.excepthook = previous_hook
        guard.stop()
        watcher.stop()
        participant.stop()
        experimenter.stop()
        if crashed:
            # The process dies: everything stops where it is and nothing more is written.
            runner.cancel()
            runner.lock.release()
        elif errors:
            runner.cancel()
            session.close(VALIDATOR_ABORT)
            runner.lock.release()
        else:
            run_session.shut_down(runner)

    made = _read_run(scenario, config, session, runner, participant, experimenter, errors)
    made.closed = session.closed
    # Deleted now rather than whenever the collector gets to them: the rig owns the
    # interruptions and their restore timer, the windows own the choice screen's timers, and a
    # pending one must not reach the next run. `processEvents` does not run deferred deletes.
    for widget in (rig.participant, rig.experimenter):
        widget.close()
    for made_object in (
        participant, experimenter, runner, rig, rig.participant, rig.experimenter
    ):
        made_object.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    return made


def _completed_now(session) -> set[str]:
    path = session.files.path("log")
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["detail"] for row in csv.DictReader(handle)
                if row["event"] == "stage_completed"}


def _read_run(scenario, config, session, runner, participant, experimenter, errors) -> Run:
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
    return Run(
        name=scenario.name,
        seed=scenario.seed,
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
        stats={**participant.stats(), "resumes": experimenter.resumes,
               "aborted": experimenter.aborted},
        folder=session.data_folder,
        stage_ids=[stage.id for stage in runner.stages],
    )


def run_all(loaded: cfg.Config, root: Path) -> dict[str, Run]:
    runs = {}
    for scenario in SCENARIOS:
        folder = root / (scenario.resumes or scenario.folder_of or scenario.name)
        runs[scenario.name] = run_one(scenario, folder, loaded)
    return runs


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
        # The one broad catch in this file, and deliberate. This is a reporting tool, not task
        # code: a check that raises on a malformed cell has found a defect, and the job is to
        # report it as that check's failure and go on to report every other check (SPEC.md
        # 17.1: the gate lists every failure), not to stop at the first.
        try:
            results.append(_evaluate_one(check, runs))
        except Exception:  # deliberately broad, see above
            results.append(Result(check.name, FAILED, [traceback.format_exc().strip()]))
    return results


def _evaluate_one(check: Check, runs: dict[str, Run]) -> Result:
    reason = check.needs(runs)
    if reason is not None:
        return Result(check.name, SKIPPED, [reason])
    if check.run is None:
        return Result(
            check.name,
            FAILED,
            ["its precondition now holds, but the check has not been written"],
        )
    failures = check.run(runs)
    return Result(check.name, FAILED if failures else PASSED, failures)


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


def _closed_runs(runs: dict[str, Run]) -> list[Run]:
    """Every run that ended with its session closed, which is every run but the crash."""
    return [run for run in runs.values() if run.closed]


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


def _logged(run: Run, event: str) -> bool:
    return any(row["event"] == event for row in run.events())


def _left_phases(run: Run) -> set[str]:
    """Phases the run finished and moved on from. An aborted run's last phase is not one."""
    left = []
    for row in run.events():
        if row["event"] == "phase_changed":
            left.append(row["detail"].split(" -> ")[0])
    if run.session.get("abort_reason") and left:
        left.pop()  # the phase the abort closed it out of
    return set(left)


# -- the checks: the data files -------------------------------------------------------------


def check_runs_completed(runs):
    failures = []
    for run in runs.values():
        scenario = run.scenario
        if run.failure:
            failures.append(f"{run.name}: {run.failure}")
            continue
        if run.write_failures:
            failures.append(f"{run.name}: {run.write_failures} data writes failed")
        reason = run.session.get("abort_reason", "")
        if scenario.crashes_in_block is not None:
            if run.closed:
                failures.append(f"{run.name}: the crashed session was closed")
        elif scenario.closes_in_block is not None:
            if reason != run_session.WINDOW_CLOSED:
                failures.append(f"{run.name}: closed with {reason!r}, not the window's reason")
        elif scenario.ends_early:
            if reason != SCENARIO_ENDED:
                failures.append(f"{run.name}: ended with {reason!r}, not the scenario's end")
        elif not run.completed:
            failures.append(f"{run.name}: the session did not reach its end")
        elif reason:
            failures.append(f"{run.name}: aborted ({reason})")
    return failures


def check_all_schema_tables_written(runs):
    failures = []
    for name in FULL:
        run = runs[name]
        for table in SCHEMA:
            if table in run.headers:
                continue
            if table in MAY_BE_ABSENT and not _logged(run, "trial_discarded"):
                continue
            failures.append(f"{run.name}: no {table} file")
    return failures


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


def check_row_counts_match_schedule(runs):
    """A whole session has exactly the rows its configuration plans (SPEC.md 17.3)."""
    failures = []
    for name in FULL:
        run = runs[name]
        study = run.config.study1
        short_n = int(study["pinprick"]["short_protocol_n_trials"])
        brush_n = int(study["brush"]["n_trials"])
        block = study["touch_block"]
        touch_n = int(block["n_repetitions"]) * len(block["repeated_scales"]) + len(
            block["once_scales"]
        )
        expected: dict[str, int] = {"blocks": len(run.schedule_offsets_min)}
        types = {int(r["block_index"]): r["block_type"] for r in run.rows.get("blocks", [])}
        pinprick = run.rows.get("pinprick", [])
        touch = run.rows.get("touch_ratings", [])
        for index, block_type in types.items():
            got = (sum(r["block_index"] == str(index) for r in pinprick) if block_type ==
                   "pinprick" else sum(r["block_index"] == str(index) for r in touch))
            want = short_n if block_type == "pinprick" else touch_n
            if got != want:
                failures.append(f"{name}: block {index} ({block_type}) has {got} rows, "
                                f"planned {want}")
        time_points = ("pre_sensitisation", "post_sensitisation", "post_intervention")
        primary = [r for r in pinprick if r["region"] == "primary"]
        expected_by = {
            "primary short protocol": (len(primary), short_n * len(time_points)),
            "brush": (len(run.rows.get("brush", [])), brush_n * 2 * len(time_points)),
            "accepted F40 estimates": (
                sum(r["superseded"] == "false"
                    for r in run.rows.get("calibration_pinprick", [])),
                len(time_points),
            ),
            "sh_area time points": (
                len({r["phase"] for r in run.rows.get("sh_area", [])}),
                int(len(time_points) - 1),
            ),
            "mapping paths": (
                len({(r["phase"], r["path_id"]) for r in run.rows.get("mapping", [])}),
                int(study["mapping"]["n_paths"]) * (len(time_points) - 1),
            ),
            "baseline ratings": (
                sum(r["phase"] == "touch_calibration" for r in touch),
                len(block["baseline_scales"]),
            ),
            "blocks": (len(run.rows.get("blocks", [])), expected["blocks"]),
        }
        for what, (got, want) in expected_by.items():
            if got != want:
                failures.append(f"{name}: {got} {what}, planned {want}")
    return failures


def check_scheduled_blocks_in_order(runs):
    failures = []
    for name in FULL:
        run = runs[name]
        offsets = run.schedule_offsets_min
        planned = sorted(offsets, key=lambda i: (offsets[i], i))
        blocks = run.rows.get("blocks", [])
        ran = [int(r["block_index"]) for r in
               sorted(blocks, key=lambda r: float(r["started_t_session_s"]))]
        if ran != planned:
            failures.append(f"{name}: blocks ran in the order {ran}, planned {planned}")
        for row in blocks:
            if float(row["lateness_min"]) < -FLOAT_TOLERANCE:
                failures.append(f"{name}: block {row['block_index']} launched before due")
        stages = [r["detail"] for r in run.events()
                  if r["event"] == "stage_started" and r["detail"].startswith("block.")]
        if stages != [f"block.{index}" for index in planned]:
            failures.append(f"{name}: block stages started as {stages}")
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
            # A mapping row is stamped with its path's start and written when its distance is
            # accepted, which can be in any order (docs/DATA_SCHEMA.md).
            if "timestamp_iso" not in SCHEMA[table].column_names or table == "mapping":
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
        # t=0 is set once, or reconstructed once by a resume (SPEC.md 15), or never reached.
        zero = [i for i, row in enumerate(events)
                if row["event"] in ("sensitisation_started", "sensitisation_resumed")]
        if len(zero) > 1:
            failures.append(f"{run.name}: session t=0 set {len(zero)} times")
            continue
        start = zero[0] if zero else len(events)
        early = [row["event"] for row in events[:start] if row["t_session_s"]]
        late = [row["event"] for row in events[start + 1:] if not row["t_session_s"]]
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


def _session_s(run: Run, start_iso: str, end_iso: str) -> float:
    """The session seconds between two wall-clock stamps of one run."""
    real_s = (_iso(end_iso) - _iso(start_iso)).total_seconds()
    return real_s * float(run.session["clock_speed"])


def needs_rated_pinprick_rows(runs):
    if TIMING not in runs:
        return "the timing scenario did not run"
    if not any(row["rating_cue_iso"] for row in runs[TIMING].rows.get("pinprick", [])):
        return "the timing run wrote no pinprick row with a rating cue"
    return None


def check_rating_cue_interval(runs):
    """Warning cue to rating cue: the 1 s cue lead plus the 9 s delay (SPEC.md 10.5, 8), in
    session seconds, within TIMING_TOLERANCE_S, on the application the load disturbed least."""
    run = runs[TIMING]
    study = run.config.study1
    expected_s = (float(study["cues"]["warning_lead_s"])
                  + float(study["pinprick"]["rating_cue_delay_s"]))
    deviations = [
        _session_s(run, row["cue_onset_iso"], row["rating_cue_iso"]) - expected_s
        for row in run.rows.get("pinprick", []) if row["rating_cue_iso"]
    ]
    least_s = min(deviations)
    if abs(least_s) > TIMING_TOLERANCE_S:
        return [f"warning cue to rating cue is {least_s:+.3f} s of session time off its "
                f"configured {expected_s:g} s at best over {len(deviations)} applications, "
                f"beyond +/- {TIMING_TOLERANCE_S} s"]
    return []


def _isi_deviations(run: Run) -> list[tuple[float, float]]:
    """(drawn, measured - drawn) in session seconds for every jittered interval followed by
    its next application's cue. The draw is what the protocol logged as `interval`."""
    events = run.events()
    found = []
    for i, row in enumerate(events):
        if row["event"] != "interval":
            continue
        drawn_s = float(row["detail"].split()[0])
        cue = next((later for later in events[i + 1:] if later["event"] == "warning_cue"), None)
        if cue is None or not cue["detail"].startswith("trial"):
            continue  # the protocol ended; the next cue is another protocol's
        found.append((drawn_s, _session_s(run, row["timestamp_iso"], cue["timestamp_iso"])
                      - drawn_s))
    return found


def needs_two_applications_in_a_run(runs):
    if TIMING not in runs:
        return "the timing scenario did not run"
    if not _isi_deviations(runs[TIMING]):
        return "the timing run has no interval between two applications"
    return None


def check_inter_stimulus_interval(runs):
    """The jittered interval after each application (SPEC.md 8.3): every draw inside the
    configured range, and the interval actually waited equal to the draw, in session seconds,
    within TIMING_TOLERANCE_S on the one the load disturbed least."""
    run = runs[TIMING]
    pinprick = run.config.study1["pinprick"]
    low_s, high_s = float(pinprick["isi_min_s"]), float(pinprick["isi_max_s"])
    found = _isi_deviations(run)
    failures = [f"an interval of {drawn_s} s was drawn outside {low_s:g}-{high_s:g} s"
                for drawn_s, _ in found if not low_s <= drawn_s <= high_s]
    least_s = min(deviation for _, deviation in found)
    if abs(least_s) > TIMING_TOLERANCE_S:
        failures.append(f"the interval waited is {least_s:+.3f} s of session time off the "
                        f"one drawn, at best over {len(found)}, beyond +/- "
                        f"{TIMING_TOLERANCE_S} s")
    return failures


def check_blocks_planned_against_actual(runs):
    failures = []
    for run in runs.values():
        blocks = run.rows.get("blocks", [])
        started = _event_names(run).count("block_started")
        # A crash leaves its last block started and never ended: there is no row for it.
        if len(blocks) != started - (0 if run.closed else 1):
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
    # The other runs are shorter, so each is compared over as far as it goes.
    same, other = orders[1], orders[2]
    if orders[0][: len(same)] == same and orders[0][: len(other)] == other:
        return ("trial order is identical under two different seeds, so nothing the seed "
                "controls is in it yet")
    return None


def check_same_seed_same_trial_order(runs):
    # The same-seed run ends in the intervention, so it is the normal run's prefix that must
    # match, and it must reach the intervention's blocks to count.
    second = _trial_order(runs[SAME_SEED])
    first = _trial_order(runs[NORMAL])[: len(second)]
    if not any(trial[0] == "pinprick" and trial[2] for trial in second):
        return ["the same-seed run never reached an intervention block"]
    if first == second:
        return []
    differ = next(
        (i for i, (a, b) in enumerate(zip(first, second, strict=False)) if a != b),
        min(len(first), len(second)),
    )
    return [f"seed {SEED} gave two trial orders; they differ from trial {differ + 1}: "
            f"{first[differ] if differ < len(first) else None} / "
            f"{second[differ] if differ < len(second) else None}"]


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
        return "the normal run wrote no calibration_pinprick rows"
    return None


def check_out_of_range_when_and_only_when(runs):
    """SPEC.md 8.2: the flag is set exactly when a boundary filament ended the search.

    Derived from the applications themselves, in every run: below when the lightest filament
    was rated at or above the target in the search, above when the heaviest was rated below
    it. The two adversarial participants must produce theirs.
    """
    failures = []
    for run in runs.values():
        pinprick = run.config.study1["pinprick"]
        target = float(pinprick["target_vas_pct"])
        by_force = sorted(run.config.filaments["filaments"],
                          key=lambda f: f["force_nominal_mn"])
        lightest, heaviest = by_force[0]["label_g"], by_force[-1]["label_g"]
        for row in run.rows.get("calibration_pinprick", []):
            search = [
                r for r in run.rows.get("pinprick", [])
                if r["phase"] == row["phase"] and r["protocol"] == "long"
                and r["run_index"] == row["run_index"] and r["purpose"] == "search"
                and r["rating_percent"]
            ]
            below = any(r["applied_filament_label_g"] == lightest
                        and float(r["rating_percent"]) >= target for r in search)
            above = any(r["applied_filament_label_g"] == heaviest
                        and float(r["rating_percent"]) < target for r in search)
            direction = "below" if below else "above" if above else ""
            flagged = row["out_of_range"] == "true"
            if flagged != bool(direction) or row["out_of_range_direction"] != direction:
                failures.append(f"{run.name}: {row['phase']} out_of_range is "
                                f"{row['out_of_range']} {row['out_of_range_direction']!r}, "
                                f"the applications say {direction or 'in range'}")
        wanted = OUT_OF_RANGE.get(run.name)
        if wanted is not None:
            pre_s = [r for r in run.rows.get("calibration_pinprick", [])
                     if r["phase"] == "pre_sensitisation"]
            if not pre_s or pre_s[-1]["out_of_range_direction"] != wanted:
                failures.append(f"{run.name}: the pre-S estimate is not out of range {wanted}")
    return failures


def needs_full_session(runs):
    """Read from the data: every block the schedule plans has a row in `blocks`.

    So these checks go live by themselves the first time the runner drives the whole grid, and
    fail then if they have no body -- nobody has to remember to switch them on.
    """
    run = runs[NORMAL]
    ran = {int(row["block_index"]) for row in run.rows.get("blocks", [])}
    planned = set(run.schedule_offsets_min)
    if not planned or not planned <= ran:
        return (f"the normal run ran {len(ran & planned)} of the {len(planned)} scheduled "
                f"blocks")
    return None


def needs_block_rows(runs):
    if not runs[NORMAL].rows.get("blocks"):
        return "the normal run wrote no blocks rows"
    return None


def needs_trial_rows(runs):
    if not any(runs[NORMAL].rows.get(table) for table in TRIAL_ORDER_COLUMNS):
        return "the normal run wrote no trial rows to compare against"
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
    # The setup procedures write their keys when they end; a session that never ran one writes
    # them empty at close (tatp/session.py). "Never ran" is read from the log, so a procedure
    # that ran and then lost its values still fails.
    **{
        key: ("the masking check has not run",
              lambda run: not _logged(run, "masking_result")
              and not _logged(run, "session_resumed"))
        for key in (
            "white_noise_level_dbfs", "masking_confirmed", "masking_attempts", "earplugs_used"
        )
    },
    **{
        key: ("the stop rehearsal has not run",
              lambda run: not _logged(run, "stop_rehearsal_started")
              and not _logged(run, "session_resumed"))
        for key in ("stop_rehearsal_ran", "stop_rehearsal_press_detected")
    },
    "cloud_sync_warning": (
        "the data folder is not synced",
        lambda run: not provenance.cloud_sync_warning(
            Path(run.session["data_folder"]), run.config.hardware["data"]["cloud_sync_markers"]
        ),
    ),
    "unresolved_open_items": ("every open item is resolved",
                              lambda run: not run.config.unresolved),
    "resumed_from_session_file": ("the run did not resume",
                                  lambda run: run.scenario.resumes is None),
    "sensitisation_start_iso": ("the run ended before session t=0",
                                lambda run: not _logged(run, "sensitisation_started")
                                and not _logged(run, "sensitisation_resumed")),
    "abort_reason": ("the run was not aborted", lambda run: run.completed),
}


def check_provenance_populated(runs):
    failures = []
    stale = set(MAY_BE_EMPTY) - set(SESSION_KEYS)
    if stale:
        failures.append(f"MAY_BE_EMPTY names keys the schema does not have: {sorted(stale)}")
    for run in _closed_runs(runs):
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
        # An empty name would be a substring of every text.
        patterns = [name for name in run.session["pattern_names"].split(";") if name]
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
    for table in ("touch_ratings", "pinprick", "brush"):
        if any(not row["rating_percent"] for row in run.rows.get(table, [])):
            failures.append(f"a {table} row has no rating: an empty confirm was recorded")
    return failures


def check_emergency_stop_mid_block_resumes(runs):
    run = runs["stops_mid_block"]
    failures = []
    if run.stats["stops"] != 1:
        failures.append(f"the participant pressed the stop {run.stats['stops']} times, not 1")
    events = run.events()
    stops = [i for i, row in enumerate(events)
             if row["event"] == "emergency_stop" and row["phase"] == "intervention"]
    if len(stops) != 1:
        return [*failures, f"{len(stops)} emergency_stop events logged in the intervention"]
    stop = events[stops[0]]
    if not stop["block_index"]:
        failures.append("the stop was not logged inside an intervention block")
    if stop["origin"] != "participant":
        failures.append("the stop is not logged as the participant's")
    after = [row["event"] for row in events[stops[0]:]]
    wanted = ["trial_cancelled", "resumed", "step_repeated"]
    positions = [after.index(e) if e in after else -1 for e in wanted]
    if -1 in positions or positions != sorted(positions):
        failures.append(f"after the stop, expected {wanted} in order")
    if "garment_restored" not in after:
        failures.append("the intervention's touch was not restored after the stop")
    # Exactly one resume answers the mid-block stop, and the experimenter pressed Resume once
    # for every stop in the run -- the rehearsal's and this one.
    resumes_after = after.count("resumed")
    if resumes_after != 1:
        failures.append(f"the mid-block stop was resumed {resumes_after} times, not once")
    all_stops = sum(row["event"] == "emergency_stop" for row in events)
    if run.stats["resumes"] != all_stops:
        failures.append(f"the experimenter resumed {run.stats['resumes']} times for "
                        f"{all_stops} stops")
    stop_s = float(stop["t_session_s"])
    zeroed = [row for row in run.rows.get("garment", [])
              if row["event"] == "stop" and row["t_session_s"]
              and float(row["t_session_s"]) <= stop_s]
    if not zeroed:
        failures.append("no garment stop was commanded by the time the stop was logged")
    return failures


def check_adjustment_held_at_maximum_stops_at_ceiling(runs):
    run = runs["holds_adjustment_at_maximum"]
    ceiling = float(run.config.hardware["garment"]["pressure_ceiling_kpa"])
    failures = []
    holds = run.stats["ceiling_holds_s"]
    if not holds or min(holds) < HoldsAdjustmentAtMaximum.OVERHOLD_S:
        failures.append("the participant never held the button at the ceiling")
    adjusted = run.rows.get("touchcal_adjust", [])
    if not adjusted:
        return [*failures, "no touchcal_adjust rows"]
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
    first = [row for row in run.rows.get("touchcal_adjust", []) if row["stage"] == "anchor"]
    if len(first) != 1:
        failures.append("the repeated adjustment did not write exactly one row")
    return failures


def check_silent_adjustment_times_out(runs):
    run = runs["stops_responding"]
    failures = []
    if run.stats["ignored_adjustments"] != 1:
        failures.append("the participant did not ignore the adjustment")
    adjusted = run.rows.get("touchcal_adjust", [])
    if not adjusted or adjusted[0]["timed_out"] != "true":
        failures.append("the ignored adjustment did not write a timed_out row")
    if "adjustment_timed_out" not in _event_names(run):
        failures.append("the time-out was not logged")
    return failures


def check_adversaries_lose_no_data(runs):
    """Every trial the normal run has in a phase, a normal participant has too, however the
    session was provoked -- as far as the scenario went (SPEC.md 17.5: "no data is lost")."""
    failures = []
    expected = runs[NORMAL]
    for name in LOSSLESS:
        run = runs[name]
        left = _left_phases(run) & _left_phases(expected)
        for table in TRIAL_ORDER_COLUMNS:
            if "phase" in SCHEMA[table].column_names:
                def count(r, table=table, left=left):
                    return sum(row["phase"] in left for row in r.rows.get(table, []))
            elif "touch_calibration" in left:
                def count(r, table=table):
                    return len(r.rows.get(table, []))
            else:
                continue
            if count(run) != count(expected):
                failures.append(f"{name}: {count(run)} {table} rows in the phases it finished, "
                                f"where the normal run has {count(expected)}")
    return failures


# -- the checks: the adversarial experimenters -----------------------------------------------


def check_implausible_distances_are_queried_and_missing_ones_flagged(runs):
    run = runs[DISTANCES]
    study = run.config.study1["mapping"]
    low = float(study["distance_plausible_min_mm"])
    high = float(study["distance_plausible_max_mm"])
    failures = []
    queried = [row for row in run.events() if row["event"] == "distance_queried"]
    implausible = [v for v in ImplausibleDistances.IMPLAUSIBLE_MM if not low <= v <= high]
    if len(queried) != len(implausible):
        failures.append(f"{len(queried)} distances queried, {len(implausible)} implausible "
                        f"entered")
    accepted = [float(r["distance_mm"]) for r in run.rows.get("mapping", [])
                if r["distance_mm"]]
    if any(not low <= value <= high for value in accepted):
        failures.append(f"an implausible distance was accepted unconfirmed: {accepted}")
    areas = {row["phase"]: row for row in run.rows.get("sh_area", [])}
    first, last = "post_sensitisation", "post_intervention"
    if first not in areas or areas[first]["area_missing"] != "false":
        failures.append("the corrected distances gave no area")
    if last not in areas or areas[last]["area_missing"] != "true":
        failures.append("the unentered time point was not closed with its area flagged missing")
    missing = [r for r in run.rows.get("mapping", [])
               if r["phase"] == last and r["distance_missing"] == "true"]
    if len(missing) != int(study["n_paths"]):
        failures.append(f"{len(missing)} paths flagged missing at the end, not "
                        f"{study['n_paths']}")
    if _event_names(run).count("distances_outstanding") != 1:
        failures.append("the outstanding distances were not prompted for exactly once")
    return failures


def check_preflight_refuses_and_warns(runs):
    """SPEC.md 17.5's launch-time experimenters, against a data folder holding one completed
    session 1 (the adversarial experimenter's), and one holding an aborted attempt followed by
    a completed session."""
    run = runs[DISTANCES]
    config, folder = run.config, run.folder
    failures = []

    # An aborted file listed before a completed one: every file is read, not the first.
    mixed = folder.parent / "preflight_aborted_then_completed"
    mixed.mkdir()
    closed_file, completed_file = _session_path(runs[CLOSED]), _session_path(run)
    shutil.copy(closed_file, mixed / closed_file.name.replace("TATP1_", "TATP1_0000_"))
    shutil.copy(completed_file, mixed / completed_file.name.replace("TATP1_", "TATP1_9999_"))
    ordered = sorted(mixed.glob("*_session.csv"))
    if "0000" not in ordered[0].name:
        failures.append("the aborted file is not listed first, so the case tests nothing")
    found = {(f.severity, f.text_key)
             for f in pre.preflight(config, PARTICIPANT, SESSION_NUMBER, EXPERIMENTER, mixed)}
    if (pre.REFUSE, "preflight.session_completed") not in found:
        failures.append(f"an aborted attempt then a completed session: not refused, {found}")

    def keys(code, number, initials):
        return {(f.severity, f.text_key)
                for f in pre.preflight(config, code, number, initials, folder)}

    cases = {
        "a completed session": (keys(PARTICIPANT, SESSION_NUMBER, EXPERIMENTER),
                                (pre.REFUSE, "preflight.session_completed")),
        "an unallocated code": (keys("999", SESSION_NUMBER, EXPERIMENTER),
                                (pre.REFUSE, "preflight.code_not_allocated")),
        "session 3 before 2": (keys(PARTICIPANT, 3, EXPERIMENTER),
                               (pre.WARN, "preflight.previous_session_missing")),
        "other initials": (keys(PARTICIPANT, 2, "XX"),
                           (pre.WARN, "warnings.experimenter_changed")),
    }
    lock = pre.InstanceLock(folder)
    assert lock.acquire(), "the run left its data folder locked"
    cases["a second instance"] = (keys(PARTICIPANT, 2, EXPERIMENTER),
                                  (pre.REFUSE, "preflight.another_instance"))
    lock.release()
    for what, (found, wanted) in cases.items():
        if wanted not in found:
            failures.append(f"{what}: {wanted} not among {sorted(found)}")
    if (pre.REFUSE, "preflight.another_instance") in keys(PARTICIPANT, 2, EXPERIMENTER):
        failures.append("the instance lock was not released with the session")
    return failures


def check_closing_the_window_mid_block_loses_nothing(runs):
    run = runs[CLOSED]
    failures = []
    blocks = run.rows.get("blocks", [])
    if [r["aborted"] for r in blocks] != ["false"] * (len(blocks) - 1) + ["true"]:
        failures.append(f"the block the window closed in is not the one marked aborted: "
                        f"{[(r['block_index'], r['aborted']) for r in blocks]}")
    if run.session.get("abort_reason") != run_session.WINDOW_CLOSED:
        failures.append("the session file does not say the window was closed")
    normal_blocks = [r for r in runs[NORMAL].rows.get("pinprick", [])
                     if r["block_index"] == "1"]
    closed_blocks = [r for r in run.rows.get("pinprick", []) if r["block_index"] == "1"]
    if len(closed_blocks) != len(normal_blocks):
        failures.append("the block completed before the close lost rows")
    return failures


def check_a_crashed_session_resumes_where_it_stopped(runs):
    crashed, resumed = runs[CRASHED], runs[RESUMED]
    failures = []
    if crashed.session.get("session_end_iso"):
        failures.append("the crashed session file was closed")
    if resumed.session.get("resumed_from_session_file") != _session_file_name(crashed):
        failures.append("the resumed session does not name the file it resumed from")
    zero = [r["detail"] for r in crashed.events() if r["event"] == "sensitisation_started"]
    if not zero or resumed.session.get("sensitisation_start_iso") != zero[0]:
        failures.append("the resumed session did not keep the original t=0")
    if resumed.session.get("rng_seed") != crashed.session.get("rng_seed"):
        failures.append("the resumed session did not reload the RNG seed")
    completed = [int(r["block_index"]) for run in (crashed, resumed)
                 for r in run.rows.get("blocks", []) if r["aborted"] == "false"]
    if sorted(completed) != sorted(resumed.schedule_offsets_min):
        failures.append(f"blocks across the crash: {completed}")
    started = [r["detail"] for r in resumed.events() if r["event"] == "stage_started"]
    crashed_in = f"block.{BY_NAME[CRASHED].crashes_in_block}"
    if not started or started[0] != crashed_in:
        failures.append(f"the resume started at {started[:1]}, not {crashed_in}")
    if any(s.startswith(("setup.", "touch_calibration")) for s in started):
        failures.append("the resume redid setup or calibration")
    post_i = [r for r in resumed.rows.get("calibration_pinprick", [])
              if r["phase"] == "post_intervention"]
    if not post_i or post_i[-1]["start_source"] != "previous_timepoint":
        failures.append("post-I did not start from the reloaded post-S estimate")
    if not resumed.completed:
        failures.append("the resumed session did not reach its end")
    # SPEC.md 15, docs/LOG.md N7.D13: every stage from the crash on draws exactly what the
    # uninterrupted session with the same seed drew -- here, every jittered interval of every
    # block, the redone one included.
    normal = runs[NORMAL]
    for index in sorted(resumed.schedule_offsets_min):
        if index < BY_NAME[CRASHED].crashes_in_block:
            continue
        drawn = _drawn_intervals(resumed, index)
        if drawn != _drawn_intervals(normal, index):
            failures.append(f"block {index} drew {drawn} after the resume, "
                            f"{_drawn_intervals(normal, index)} uninterrupted")
    return failures


def _drawn_intervals(run: Run, block_index: int) -> list[str]:
    return [row["detail"] for row in run.events()
            if row["event"] == "interval" and row["block_index"] == str(block_index)]


def check_every_rating_given_is_recorded(runs):
    """SPEC.md 17.5, "no data is lost": every VAS the rating adversaries answered is a row."""
    failures = []
    for name in (RATES_ZERO, RATES_HUNDRED, RATES_RANDOM):
        run = runs[name]
        given = len(run.stats["ratings"])
        rows = sum(len(run.rows.get(table, [])) for table in RATED_TABLES)
        if given != rows:
            failures.append(f"{name}: {given} ratings given, {rows} rows")
    return failures


def check_rating_everything_zero_falls_back_and_runs_off_the_top(runs):
    run = runs[RATES_ZERO]
    failures = []
    fits = run.rows.get("touchcal_fit", [])
    if not fits or any(r["stage1_pass"] == "true" for r in fits):
        failures.append("a flat touch calibration was not failed at stage 1")
    channels = run.rows.get("touchcal_channels", [])
    if not channels or any(r["targets_source"] == "fit" for r in channels):
        failures.append("the unusable fit was not replaced by a recorded fallback")
    if any(r["valid_for_analysis"] == "true" for r in channels):
        failures.append("a fallback calibration is marked valid for analysis")
    pre_s = [r for r in run.rows.get("calibration_pinprick", [])
             if r["phase"] == "pre_sensitisation"]
    if not pre_s or pre_s[-1]["out_of_range_direction"] != "above":
        failures.append("every rating 0: the pre-S estimate is not out of range above")
    return failures


def check_rating_everything_hundred_caps_every_site(runs):
    """SPEC.md 8.2: no filament at or above one rated intolerable, at that site and, once
    enough sites are capped, anywhere -- within the time point."""
    run = runs[RATES_HUNDRED]
    pinprick = run.config.study1["pinprick"]
    order = [f["label_g"] for f in sorted(run.config.filaments["filaments"],
                                          key=lambda f: f["force_nominal_mn"])]
    global_after = int(pinprick["intolerable_sites_for_global_cap"])
    failures = []
    rows = [r for r in run.rows.get("pinprick", []) if r["phase"] == "pre_sensitisation"]
    if not rows or any(r["intolerable"] != "true" for r in rows):
        failures.append("a rating at the top of the scale was not flagged intolerable")
    caps: dict[tuple[str, str], int] = {}
    for row in rows:
        label = row["applied_filament_label_g"]
        key, index = (row["region"], row["site_index"]), order.index(label)
        region_caps = [cap for (region, _), cap in caps.items() if region == row["region"]]
        ceiling = min(region_caps) if len(region_caps) >= global_after else None
        if key in caps and index >= caps[key]:
            failures.append(f"site {row['site_index']} was given {label} g after its cap")
        if ceiling is not None and index >= ceiling:
            failures.append(f"{label} g was given after every site was capped")
        caps[key] = min(caps.get(key, index), index)
    if "intolerable_global_cap" not in _event_names(run):
        failures.append("the cap never escalated to every site")
    return failures


def check_random_ratings_are_flagged_inconsistent_when_and_only_when(runs):
    """The consistency check (comparison doc 6.7) warns exactly when rho is below the floor."""
    run = runs[RATES_RANDOM]
    floor = float(run.config.study1["pinprick"]["ordinal_rho_min"])
    failures = []
    rows = run.rows.get("calibration_pinprick", [])
    if not rows:
        return ["the random rater produced no estimate"]
    low = sum(1 for r in rows if r["ordinal_rho"] and float(r["ordinal_rho"]) < floor)
    warned = _event_names(run).count("ordinal_consistency_low")
    if low != warned:
        failures.append(f"{low} estimates below the rho floor, {warned} warnings")
    return failures


def check_a_garment_disconnected_mid_block_loses_nothing(runs):
    run = runs[DISCONNECTS]
    failures = []
    names = _event_names(run)
    if "garment_disconnected" not in names or "garment_connected" not in names:
        return ["the disconnect and the reconnect were not both logged"]
    off = next(r for r in run.events() if r["event"] == "garment_disconnected")
    if off["block_index"] != str(DisconnectsGarment.BLOCK):
        failures.append("the garment was not disconnected mid-block")
    commands = [r["event"] for r in run.rows.get("garment", [])]
    if "disconnect" not in commands or "connect" not in commands[commands.index("disconnect"):]:
        failures.append("the garment table does not show the disconnect and the reconnect")
    later = names[names.index("garment_connected"):]
    if "garment_activated" not in later:
        failures.append("the touch was not started again after the reconnect")
    block = str(DisconnectsGarment.BLOCK)
    expected = [r for r in runs[NORMAL].rows.get("pinprick", []) if r["block_index"] == block]
    got = [r for r in run.rows.get("pinprick", []) if r["block_index"] == block]
    if len(got) != len(expected):
        failures.append(f"the block the garment was disconnected in has {len(got)} rows, "
                        f"not {len(expected)}")
    return failures


def check_session_two_starts_from_session_ones_estimate(runs):
    """SPEC.md 8.2: a later session's pre-S search starts from the previous session's pre-S."""
    run, first = runs[SESSION_TWO], runs[NORMAL]
    session_one = [r for r in first.rows.get("calibration_pinprick", [])
                   if r["phase"] == "pre_sensitisation" and r["superseded"] == "false"]
    rows = [r for r in run.rows.get("calibration_pinprick", [])
            if r["phase"] == "pre_sensitisation"]
    if not session_one or not rows:
        return ["no pre-S estimate in session 1 or session 2"]
    prior = prior_for(run.config, "pre_sensitisation", 2, float(session_one[-1]["f40_mn"]))
    failures = []
    if rows[0]["start_source"] != "previous_timepoint":
        failures.append(f"session 2 started from {rows[0]['start_source']}")
    if rows[0]["start_filament_label_g"] != prior.start_filament_label_g:
        failures.append(f"session 2 started at {rows[0]['start_filament_label_g']} g, the "
                        f"prior is {prior.start_filament_label_g} g")
    return failures


def _session_path(run: Run) -> Path:
    """The run's own session file: the one holding its seed and start time."""
    for path in sorted(run.folder.glob(f"TATP1_*_P{PARTICIPANT}_S*_session.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            values = {row["key"]: row["value"] for row in csv.DictReader(handle)}
        if values.get("session_start_iso") == run.session.get("session_start_iso"):
            return path
    raise AssertionError(f"{run.name}: its session file is not in {run.folder}")


def _session_file_name(run: Run) -> str:
    stamp_rows = [p for p in run.folder.glob(
        f"TATP1_*_P{PARTICIPANT}_S{SESSION_NUMBER}_session.csv")]
    for path in sorted(stamp_rows):
        with path.open(encoding="utf-8", newline="") as handle:
            values = {row["key"]: row["value"] for row in csv.DictReader(handle)}
        if values.get("rng_seed") == run.session.get("rng_seed") and not values.get(
            "resumed_from_session_file"
        ):
            return path.name
    return ""


def _needs(name):
    def needs(runs):
        return None if name in runs else f"the {name} scenario did not run"

    return needs


CHECKS: list[Check] = [
    Check("runs_completed", _always, check_runs_completed),
    Check("all_schema_tables_written", needs_full_session, check_all_schema_tables_written),
    Check("columns_match_schema", _always, check_columns_match_schema),
    Check("required_values_present", _always, check_required_values_present),
    Check("values_parse_as_schema_types", _always, check_values_parse_as_schema_types),
    Check("row_counts_match_schedule", needs_full_session, check_row_counts_match_schedule),
    Check("scheduled_blocks_in_order", needs_full_session, check_scheduled_blocks_in_order),
    Check("condition_and_limb_match_allocation", _always,
          check_condition_and_limb_match_allocation),
    Check("timestamps_monotonic", _always, check_timestamps_monotonic),
    Check("rating_cue_interval_within_tolerance", needs_rated_pinprick_rows,
          check_rating_cue_interval),
    Check("inter_stimulus_interval_within_tolerance", needs_two_applications_in_a_run,
          check_inter_stimulus_interval),
    Check("blocks_planned_against_actual", needs_block_rows,
          check_blocks_planned_against_actual),
    Check("same_seed_same_trial_order", needs_the_seed_to_matter,
          check_same_seed_same_trial_order),
    Check("forces_are_listed_filaments", needs_pinprick_rows,
          check_forces_are_listed_filaments),
    Check("out_of_range_when_and_only_when", needs_calibration_rows,
          check_out_of_range_when_and_only_when),
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
    Check("adversaries_lose_no_data", needs_trial_rows, check_adversaries_lose_no_data),
    Check("implausible_distances_queried_and_missing_flagged", _needs(DISTANCES),
          check_implausible_distances_are_queried_and_missing_ones_flagged),
    Check("preflight_refuses_and_warns", _needs(NORMAL), check_preflight_refuses_and_warns),
    Check("closing_the_window_mid_block_loses_nothing", _needs(CLOSED),
          check_closing_the_window_mid_block_loses_nothing),
    Check("a_crashed_session_resumes_where_it_stopped", _needs(RESUMED),
          check_a_crashed_session_resumes_where_it_stopped),
    Check("every_rating_given_is_recorded", _always, check_every_rating_given_is_recorded),
    Check("rating_everything_zero_falls_back_and_runs_off_the_top", _needs(RATES_ZERO),
          check_rating_everything_zero_falls_back_and_runs_off_the_top),
    Check("rating_everything_hundred_caps_every_site", _needs(RATES_HUNDRED),
          check_rating_everything_hundred_caps_every_site),
    Check("random_ratings_flagged_inconsistent_when_and_only_when", _needs(RATES_RANDOM),
          check_random_ratings_are_flagged_inconsistent_when_and_only_when),
    Check("a_garment_disconnected_mid_block_loses_nothing", _needs(DISCONNECTS),
          check_a_garment_disconnected_mid_block_loses_nothing),
    Check("session_two_starts_from_session_ones_estimate", _needs(SESSION_TWO),
          check_session_two_starts_from_session_ones_estimate),
]


def main() -> int:
    loaded = cfg.load("sv", "en")
    application(loaded.hardware)
    began_s = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="tatp_validate_") as root:
        runs = run_all(loaded, Path(root))
        ran_s = time.monotonic() - began_s
        results = evaluate(CHECKS, runs)
    print(report(results))
    print(f"validate: {len(runs)} sessions at {CLOCK_SPEED:g}x in {ran_s:.0f} s")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
