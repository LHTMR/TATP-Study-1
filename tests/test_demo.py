"""Demonstration sessions. docs/LOG.md N7.D23, tatp/demo.py.

What a demonstration changes is tested here: that it is quarantined and recorded as one, that
either simulation can run it, Skip the wait, Finish this stage, and the watchable pace. That the
session itself is the real one is the rest of the suite's, and the validator's.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import run_session
from sim.responders import Action
from tatp import config as cfg
from tatp.demo import FAST, OFF, WATCH

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
# Real seconds a whole demonstration may take with both simulations fast.
FULL_RUN_TIMEOUT_S = 120.0
FULL_RUN_SPEED = "1000"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def loaded(tmp_path):
    loaded = cfg.load("sv", "en")
    hardware = {
        **loaded.hardware,
        "audio": {**loaded.hardware["audio"], "backend": "recording"},
        "screens": {**loaded.hardware["screens"], "participant_screen_index": None,
                    "experimenter_screen_index": None},
    }
    # Under the test's own folder, not the repository's data/demo.
    demo = {**loaded.study1["demo"], "data_folder": str(tmp_path / "demo")}
    return cfg.Config(**{**loaded.__dict__, "hardware": hardware,
                         "study1": {**loaded.study1, "demo": demo}})


def _args(*extra: str):
    return run_session.parse_args(
        ["--demo", "--session", "1", "--experimenter", "SM", "--patterns", str(EXAMPLES),
         *extra]
    )


def _demo(app, loaded, *extra: str):
    args = _args(*extra)
    config = run_session.demo_session(loaded, args)
    runner = run_session.build(config, args)
    return runner, run_session.attach_demo(runner, args)


def _session_values(session) -> dict[str, str]:
    with session.files.path("session").open(encoding="utf-8", newline="") as handle:
        return {row["key"]: row["value"] for row in csv.DictReader(handle)}


def _events(session) -> list[dict]:
    with session.files.path("log").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _finish(runner, demo) -> None:
    demo.stop()
    run_session.shut_down(runner)


# -- the command line ------------------------------------------------------------------------


def test_a_demonstration_brings_its_own_participant_code():
    assert _args().participant is None
    with pytest.raises(SystemExit):
        _args("--participant", "01")


def test_the_simulations_are_for_a_demonstration_only():
    with pytest.raises(SystemExit):
        run_session.parse_args(["--participant", "01", "--session", "1", "--experimenter",
                                "SM", "--patterns", str(EXAMPLES), "--sim-participant", FAST])


# -- quarantined, and a whole session run by the two simulations -------------------------------


def test_a_whole_demonstration_runs_quarantined_and_recorded_as_one(app, loaded, tmp_path):
    runner, demo = _demo(app, loaded, "--demo-speed", FULL_RUN_SPEED,
                         "--sim-participant", FAST, "--sim-experimenter", FAST)
    session = runner.session
    runner.start()
    deadline = time.monotonic() + FULL_RUN_TIMEOUT_S
    while not session.closed:
        assert time.monotonic() < deadline, f"the demonstration stalled at {runner.stage_index}"
        QApplication.processEvents()
        time.sleep(0.0005)
    _finish(runner, demo)

    assert runner.completed
    values = _session_values(session)
    assert values["demo"].lower() == "true"
    assert values["participant_code"] == loaded.study1["demo"]["participant_code"]
    allocation = Path(loaded.study1["demo"]["allocation_file"]).name
    assert values["allocation_file"].endswith(allocation)
    assert Path(values["data_folder"]).is_relative_to(tmp_path / "demo")
    modes = [e["detail"] for e in _events(session) if e["event"] == "demo_simulation"]
    assert modes == [f"participant: {FAST}", f"experimenter: {FAST}"]


def test_a_real_session_is_recorded_as_not_a_demonstration(app, loaded, tmp_path):
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"],
                                            "folder": str(tmp_path / "data")}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    args = run_session.parse_args(["--participant", "01", "--session", "1", "--experimenter",
                                   "SM", "--patterns", str(EXAMPLES)])
    runner = run_session.build(config, args)
    assert _session_values(runner.session)["demo"].lower() == "false"
    run_session.shut_down(runner)


# -- Skip the wait -----------------------------------------------------------------------------


def test_skip_the_wait_ends_a_timed_wait_lead_s_before_it_is_due(app, loaded):
    runner, demo = _demo(app, loaded)
    clock = runner.session.clock
    clock.start_session()
    fired = []
    runner._wait_until(600.0, lambda: fired.append(True), lambda: None)
    lead_s = float(loaded.study1["demo"]["skip_lead_s"])

    before_s = clock.t_session_s()
    skipped_s = demo.skip_wait()
    assert skipped_s == pytest.approx(600.0 - lead_s - before_s, abs=1.0)
    assert clock.t_session_s() == pytest.approx(600.0 - lead_s, abs=1.0)
    assert fired == [], "it waits the lead out as normal"
    assert runner.waiting_until_s == 600.0
    assert demo.skip_wait() is None, "less than the lead left: nothing to skip"
    skips = [e for e in _events(runner.session) if e["event"] == "demo_wait_skipped"]
    assert len(skips) == 1
    _finish(runner, demo)


def test_there_is_nothing_to_skip_while_no_timed_wait_runs(app, loaded):
    runner, demo = _demo(app, loaded)
    assert demo.skip_wait() is None
    _finish(runner, demo)


def test_skipping_leaves_the_hands_time_alone(app, loaded):
    """Taps and holds are timed in real seconds (tatp/clock.py); a skip moves session time."""
    runner, demo = _demo(app, loaded)
    clock = runner.session.clock
    real_s, elapsed_s = clock.real_elapsed_s(), clock.elapsed_s()
    clock.skip(300.0)
    assert clock.elapsed_s() - elapsed_s >= 300.0
    assert clock.real_elapsed_s() - real_s < 1.0
    _finish(runner, demo)


# -- who presses ----------------------------------------------------------------------------


def test_finish_this_stage_runs_both_fast_then_hands_back(app, loaded):
    runner, demo = _demo(app, loaded, "--sim-participant", WATCH)
    demo.finish_stage()
    assert (demo.participant_mode, demo.experimenter_mode) == (FAST, FAST)
    assert demo.finishing
    runner.stage_started.emit("the next stage")
    assert (demo.participant_mode, demo.experimenter_mode) == (WATCH, OFF)
    assert not demo.finishing
    _finish(runner, demo)


def test_every_change_of_who_presses_is_logged(app, loaded):
    runner, demo = _demo(app, loaded)
    demo.set_participant(WATCH)
    demo.set_participant(WATCH)  # no change, nothing logged
    demo.set_experimenter(FAST)
    demo.set_participant(OFF)
    modes = [e["detail"] for e in _events(runner.session) if e["event"] == "demo_simulation"]
    assert modes == [f"participant: {WATCH}", f"experimenter: {FAST}", f"participant: {OFF}"]
    _finish(runner, demo)


def test_a_watchable_participant_presses_one_at_a_time(app, loaded):
    runner, demo = _demo(app, loaded, "--sim-participant", WATCH)
    participant = demo.participant
    participant._presses([Action.INCREASE, Action.INCREASE, Action.CONFIRM])
    assert len(participant._queue) == 3, "queued, to be pressed one per look"
    participant.set_pace(0.0, 0.0)
    participant._queue.clear()
    _finish(runner, demo)


def test_a_watchable_experimenter_reads_the_instruction_before_pressing(app, loaded):
    runner, demo = _demo(app, loaded, "--sim-experimenter", WATCH)
    experimenter = runner.rig.experimenter
    pressed = []
    experimenter.proceed_requested.connect(lambda: pressed.append(True))
    experimenter.set_instruction(experimenter.text["instructions"]["ready"])
    demo.experimenter._tick()
    assert pressed == [], "still reading"
    demo.experimenter.reaction_s = 0.0
    demo.experimenter._tick()
    assert pressed == [True]
    _finish(runner, demo)


def test_a_person_at_the_experimenter_screen_is_not_pressed_for(app, loaded):
    runner, demo = _demo(app, loaded, "--sim-participant", FAST)
    experimenter = runner.rig.experimenter
    pressed = []
    experimenter.proceed_requested.connect(lambda: pressed.append(True))
    experimenter.set_instruction(experimenter.text["instructions"]["ready"])
    demo.experimenter._tick()
    assert pressed == []
    _finish(runner, demo)
