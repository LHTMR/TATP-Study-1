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
from tatp import preflight as pre
from tatp.demo import (
    ALLOCATION_NAME,
    DEMO_GARMENT,
    FAST,
    OFF,
    REAL_TIME_SPEED,
    WATCH,
    DemoError,
    check_person,
    demo_config,
    shuffled_allocation,
    worn_garment,
)
from tatp.garment.mock import MockGarment
from tatp.launcher import LauncherWindow
from tatp.remote_keys import ANY_KEYBOARD
from tatp.session import DRIVERS, SessionError

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
# Real seconds a whole demonstration may take with both simulations fast.
FULL_RUN_TIMEOUT_S = 300.0
# Fast enough with Skip the wait, and slow enough that a mapping path or a cue outlasts the
# simulations' look at the screen under the gate's load, as at 1000x it need not.
FULL_RUN_SPEED = "100"
# A garment that is worn: the prototype sleeve, its driver replaced by one with no port.
WORN = "arduino_mosfet"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def loaded(tmp_path):
    loaded = cfg.load("sv", "en")
    hardware = {
        **loaded.hardware,
        # The test's own study folder, whose lock a demonstration takes: not the repository's.
        "data": {**loaded.hardware["data"], "folder": str(tmp_path / "data")},
        "audio": {**loaded.hardware["audio"], "backend": "recording"},
        "screens": {**loaded.hardware["screens"], "participant_screen_index": None,
                    "experimenter_screen_index": None},
    }
    # Under the test's own folder, not the repository's data_demo; and fast enough for a whole
    # session to run inside a test.
    demo = {**loaded.study1["demo"], "data_folder": str(tmp_path / "demo"),
            "max_clock_speed": float(FULL_RUN_SPEED)}
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


def test_a_demonstration_may_use_the_example_patterns(loaded):
    """No pattern folder is defaulted for a session (N6.14); a demonstration records no data."""
    args = run_session.parse_args(["--demo", "--session", "1", "--experimenter", "SM"])
    run_session.demo_session(loaded, args)
    assert args.patterns == cfg.REPO_ROOT / loaded.study1["demo"]["pattern_folder"]
    with pytest.raises(SystemExit):
        run_session.parse_args(["--participant", "01", "--session", "1", "--experimenter",
                                "SM"])


def test_the_simulations_are_for_a_demonstration_only():
    with pytest.raises(SystemExit):
        run_session.parse_args(["--participant", "01", "--session", "1", "--experimenter",
                                "SM", "--patterns", str(EXAMPLES), "--sim-participant", FAST])


@pytest.mark.parametrize("extra", [("--clock-speed", "50"), ("--redcap-form-completed",)])
def test_what_a_demonstration_decides_is_refused_not_overridden(extra):
    """`--garment` is no longer among them: a demonstration may drive any garment, at real
    time on any but the mock (S, 15 Oct 2026; N7.F12f)."""
    with pytest.raises(SystemExit):
        _args(*extra)


def test_a_demonstration_on_a_real_garment_runs_at_real_time_only(loaded):
    """Faster, the rate limit, in session time, would be looser in real time (SPEC.md 13)."""
    with pytest.raises(SystemExit, match="real time"):
        run_session.demo_session(loaded, _args("--garment", "arduino_mosfet",
                                               "--demo-speed", "2"))
    with pytest.raises(DemoError):
        demo_config(loaded, 2.0, "arduino_mosfet")
    args = _args("--garment", "arduino_mosfet")
    config = run_session.demo_session(loaded, args)
    assert config.hardware["garment"]["driver"] == "arduino_mosfet"
    assert args.clock_speed == REAL_TIME_SPEED
    # The mock may still run faster.
    assert demo_config(loaded, 2.0, DEMO_GARMENT).hardware["garment"]["driver"] == DEMO_GARMENT


def test_a_demonstration_shortens_its_rests(loaded):
    """S, 16 Oct 2026 (LOG N7.F14b, N7.F14e): the pinprick and brush rests, and the touch
    estimation window on the mock garment only."""
    demo = loaded.study1["demo"]
    study1 = demo_config(loaded, REAL_TIME_SPEED, DEMO_GARMENT).study1
    for series in ("pinprick", "brush"):
        assert study1[series]["isi_min_s"] == study1[series]["isi_max_s"] == demo["rest_s"]
    window_key = "estimation_window_s"
    assert study1["touch_calibration"][window_key] == demo["estimation_window_mock_s"]
    worn = demo_config(loaded, REAL_TIME_SPEED, "arduino_mosfet").study1
    assert worn["touch_calibration"][window_key] == (
        loaded.study1["touch_calibration"][window_key]
    ), "a worn garment keeps the study's window, which covers the slowest ramp"
    assert loaded.study1["pinprick"]["isi_min_s"] != demo["rest_s"], "the study's is untouched"


def test_worn_is_declared_by_the_driver():
    """Not read from the name: a new driver is worn unless it says otherwise."""
    assert worn_garment("arduino_mosfet") and not worn_garment(DEMO_GARMENT)
    assert all(driver.worn for name, driver in DRIVERS.items() if name != DEMO_GARMENT)


@pytest.mark.parametrize("who", ["participant", "experimenter"])
@pytest.mark.parametrize("mode", [WATCH, FAST])
def test_a_demonstration_on_a_real_garment_is_pressed_by_people(loaded, who, mode):
    """A simulated participant raises pressure on whoever wears it, and a simulated
    experimenter presses Next step into garment output with nobody at the screen (N7.F12f;
    S's to revisit)."""
    with pytest.raises(SystemExit, match="person"):
        run_session.demo_session(loaded, _args("--garment", "arduino_mosfet",
                                               f"--sim-{who}", mode))
    with pytest.raises(DemoError):
        check_person("arduino_mosfet", who, mode)
    assert check_person(DEMO_GARMENT, who, mode) == mode
    # Fully manual is allowed.
    run_session.demo_session(loaded, _args("--garment", "arduino_mosfet"))


class _WornGarment(MockGarment):
    """A worn driver with no serial port behind it, under the prototype's name."""

    per_channel_pressure = False
    worn = True


@pytest.fixture
def worn(monkeypatch):
    monkeypatch.setitem(DRIVERS, WORN, _WornGarment)
    return WORN


def test_on_a_real_garment_a_demonstration_is_fully_manual(app, loaded, worn):
    runner, demo = _demo(app, loaded, "--garment", worn)
    try:
        controls = demo.controls
        assert not controls.participant_mode.isEnabled()
        assert not controls.experimenter_mode.isEnabled()
        assert not controls.auto_run_button.isEnabled()
        assert not controls.fast_forward_button.isEnabled()
        assert not controls.worn_note.isHidden()
        with pytest.raises(DemoError):
            demo.fast_forward(runner.phases[-1])
        with pytest.raises(DemoError):
            demo.set_auto_run(True)
        for who in ("participant", "experimenter"):
            with pytest.raises(DemoError):
                demo.choose(who, FAST)
        assert (demo.participant_mode, demo.experimenter_mode) == (OFF, OFF)
    finally:
        _finish(runner, demo)
    runner, demo = _demo(app, loaded)
    assert demo.controls.auto_run_button.isEnabled() and demo.controls.worn_note.isHidden()
    assert demo.controls.experimenter_mode.isEnabled()
    assert demo.controls.fast_forward_button.isEnabled()
    _finish(runner, demo)


def test_a_real_garment_demonstration_is_refused_when_built_with_a_simulation(app, loaded,
                                                                             worn):
    """Stage boundary: past the command line and the launcher, the Demo itself refuses."""
    args = _args("--garment", worn)
    config = run_session.demo_session(loaded, args)
    runner = run_session.build(config, args)
    args.sim_experimenter = WATCH
    try:
        with pytest.raises(DemoError):
            run_session.attach_demo(runner, args)
    finally:
        run_session.shut_down(runner)


@pytest.mark.parametrize("kind", ["emergency_stop", "pause"])
def test_the_simulated_experimenter_never_resumes_a_real_garment(app, loaded, worn, kind):
    """SPEC.md 10.9: on something that may be worn, a person presses Resume -- after an
    emergency stop above all. The second guard: the simulated experimenter never acts there,
    but made to, it still does not resume. On the mock it resumes by itself."""
    runner, demo = _demo(app, loaded, "--garment", worn)
    try:
        # Recorded as for any session.
        assert _session_values(runner.session)["garment_driver"] == _WornGarment.__name__
        demo.experimenter.set_pace(True, 0.0)  # past the Demo, which refuses it
        interruptions = runner.rig.interruptions
        (interruptions.emergency_stop if kind == "emergency_stop" else interruptions.pause)()
        assert not demo.experimenter._resume_timer.isActive()
        assert interruptions.active is not None
    finally:
        _finish(runner, demo)


def test_the_simulated_experimenter_still_resumes_the_mock(app, loaded):
    runner, demo = _demo(app, loaded, "--sim-experimenter", FAST)
    runner.rig.interruptions.emergency_stop()
    assert demo.experimenter._resume_timer.isActive()
    _finish(runner, demo)


def test_a_demonstration_speed_beyond_the_configured_range_is_refused(loaded):
    too_fast = str(float(loaded.study1["demo"]["max_clock_speed"]) * 2)
    with pytest.raises(SystemExit):
        run_session.demo_session(loaded, _args("--demo-speed", too_fast))


# -- quarantined -------------------------------------------------------------------------------


def test_each_demonstration_shuffles_the_conditions_into_its_own_allocation(loaded, tmp_path):
    """A session number cannot be chosen to see a condition (open item L16)."""
    template = cfg.REPO_ROOT / loaded.study1["demo"]["allocation_file"]
    orders = set()
    for run in range(20):
        path = shuffled_allocation(template, tmp_path / str(run))
        rows = list(csv.DictReader(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.startswith("#")
        ))
        conditions = [row["condition"] for row in rows]
        assert sorted(conditions) == sorted(loaded.study1["design"]["conditions"])
        orders.add(tuple(conditions))
    assert len(orders) > 1, "shuffled, not fixed"


def test_a_demonstration_runs_on_the_mock_garment_with_any_keyboard(loaded):
    config = demo_config(loaded, 1.0, DEMO_GARMENT)
    assert config.hardware["garment"]["driver"] == "mock"
    assert config.hardware["responder"]["key_source"] == ANY_KEYBOARD


def test_a_demonstration_is_refused_while_a_session_holds_the_study_folder(app, loaded,
                                                                          tmp_path):
    study = tmp_path / "study"
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"], "folder": str(study)}}
    loaded = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    held = pre.InstanceLock(study)
    assert held.acquire()
    args = _args()
    config = run_session.demo_session(loaded, args)
    keys = [key for severity, key, _ in run_session.preflight(config, args)
            if severity == pre.REFUSE]
    assert keys == ["preflight.another_instance"]
    with pytest.raises(SessionError, match="another session"):
        run_session.build(config, args)
    held.release()


def test_run_a_demo_in_the_launcher_asks_for_a_demonstration(app, loaded):
    seen = []
    launcher = LauncherWindow(loaded, preflight=lambda config, args: [],
                              build=lambda config, args: seen.append((config, args)))
    dialog = launcher.session_dialog(demo=True)
    assert dialog.participant.isReadOnly()
    dialog.experimenter.setText("SM")
    for combo, value in ((dialog.session_number, 1), (dialog.participant_language, "sv"),
                         (dialog.experimenter_language, "en")):
        combo.setCurrentIndex(combo.findData(value))
    dialog.sim_participant.setCurrentIndex(dialog.sim_participant.findData(WATCH))
    args = dialog.args()
    assert (args.demo, args.participant, args.sim_participant, args.sim_experimenter) == (
        True, loaded.study1["demo"]["participant_code"], WATCH, OFF
    )
    # The mock unless another is chosen (N7.F12f): no longer fixed.
    assert args.garment == DEMO_GARMENT and dialog.garment.isEnabled()
    assert not args.redcap_form_completed
    design = dialog.config(args).study1["design"]
    assert Path(design["allocation_file"]).name == ALLOCATION_NAME


def test_run_a_demo_holds_a_real_garment_to_real_time_and_people(app, loaded):
    """Where the command line refuses, the dialog sets and holds; the mock's speed comes back
    when the mock is chosen again."""
    launcher = LauncherWindow(loaded, preflight=lambda config, args: [],
                              build=lambda config, args: None)
    dialog = launcher.session_dialog(demo=True)
    dialog.experimenter.setText("SM")
    for combo, value in ((dialog.participant_language, "sv"),
                         (dialog.experimenter_language, "en")):
        combo.setCurrentIndex(combo.findData(value))
    dialog.demo_speed.setValue(10.0)
    dialog.sim_participant.setCurrentIndex(dialog.sim_participant.findData(FAST))
    dialog.sim_experimenter.setCurrentIndex(dialog.sim_experimenter.findData(WATCH))
    dialog.garment.setCurrentIndex(dialog.garment.findData("arduino_mosfet"))
    assert dialog.demo_speed.value() == REAL_TIME_SPEED
    assert not dialog.demo_speed.isEnabled()
    assert not dialog.sim_participant.isEnabled()
    assert not dialog.sim_experimenter.isEnabled()
    args = dialog.args()
    assert (args.garment, args.clock_speed, args.sim_participant, args.sim_experimenter) == (
        "arduino_mosfet", REAL_TIME_SPEED, OFF, OFF)
    assert dialog.config(args).hardware["garment"]["driver"] == "arduino_mosfet"
    dialog.garment.setCurrentIndex(dialog.garment.findData(DEMO_GARMENT))
    assert dialog.demo_speed.isEnabled() and dialog.sim_participant.isEnabled()
    assert dialog.sim_experimenter.isEnabled()
    assert dialog.demo_speed.value() == 10.0


# -- what the garment is doing, a demonstration's only ----------------------------------------


def test_only_a_demonstration_shows_the_garment_while_the_condition_runs(app, loaded,
                                                                         tmp_path):
    """SPEC.md 16: a session's experimenter screen withholds the channels in the intervention
    and the rekindle; a demonstration hands its display the garment in every phase (S, 15 Oct
    2026; open item L16; LOG N7.F16i)."""
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"],
                                            "folder": str(tmp_path / "data")}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    args = run_session.parse_args(["--participant", "01", "--session", "1", "--experimenter",
                                   "SM", "--patterns", str(EXAMPLES)])
    runner = run_session.build(config, args)
    window = runner.rig.experimenter
    assert not window.garment_fed_elsewhere
    runner.session.set_phase("intervention")
    window.refresh()
    assert not window.garment_display.isVisibleTo(window)
    run_session.shut_down(runner)

    runner, demo = _demo(app, loaded)
    window = runner.rig.experimenter
    assert window.garment_fed_elsewhere
    runner.session.set_phase("intervention")
    window.refresh()
    garment = runner.session.garment
    channel = garment.channels()[0]
    garment.set_channel(channel, True)
    demo._feed_garment()
    assert window.garment_display.isVisibleTo(window)
    assert window.garment_display.states[channel][0] is True
    assert window.garment_display.highlight(channel) > 0
    _finish(runner, demo)
    assert not demo._garment_timer.isActive(), "stopped with the demonstration"


def test_the_demo_controls_are_in_the_experimenter_window(app, loaded):
    """S, 20 Oct 2026: "the demo controls should be integrated into the main window"."""
    runner, demo = _demo(app, loaded)
    assert demo.controls.window() is runner.rig.experimenter
    assert not demo.controls.isWindow()
    _finish(runner, demo)


def test_each_demo_control_says_what_it_would_do_now(app, loaded):
    """S, 20 Oct 2026: "Skip buttons should be contextual and informative" (LOG N7.F16j)."""
    runner, demo = _demo(app, loaded)
    controls, words = demo.controls, loaded.experimenter_text["demo"]
    assert controls.skip_button.text() == words["skip_none"]
    assert not controls.skip_button.isEnabled()
    assert controls.skip_button.toolTip()
    assert controls.auto_run_button.text() == words["auto_run"]
    assert not controls.auto_run_button.isChecked()
    phases = [controls.fast_forward.itemData(i) for i in range(controls.fast_forward.count())]
    assert phases == runner.phases[1:], "every phase still to come"
    clock = runner.session.clock
    clock.start_session()
    runner.session.set_upcoming("phase", "capsaicin", 600.0)
    runner._wait_until(600.0, lambda: None, lambda: None)
    controls.sync()
    assert controls.skip_button.isEnabled()
    assert loaded.experimenter_text["phases"]["capsaicin"] in controls.skip_button.text()
    _finish(runner, demo)


def test_fast_forward_runs_fast_to_the_phase_then_hands_back(app, loaded):
    runner, demo = _demo(app, loaded, "--sim-participant", WATCH)
    target = runner.phases[2]
    demo.fast_forward(target)
    assert (demo.participant_mode, demo.experimenter_mode) == (FAST, FAST)
    assert not demo.auto_running, "a fast-forward is not an auto-run"
    runner.stage_started.emit("a stage in between")
    assert demo.fast_forward_to == target, "not there yet"
    runner.session.set_phase(target)
    runner.stage_started.emit("the first stage there")
    assert demo.fast_forward_to is None
    assert (demo.participant_mode, demo.experimenter_mode) == (WATCH, OFF)
    _finish(runner, demo)


def test_run_a_session_in_the_launcher_is_never_a_demonstration(app, loaded):
    launcher = LauncherWindow(loaded, preflight=lambda config, args: [],
                              build=lambda config, args: None)
    dialog = launcher.session_dialog()
    dialog.experimenter.setText("SM")
    args = dialog.args()
    assert (args.demo, args.sim_participant, args.sim_experimenter, args.clock_speed) == (
        False, OFF, OFF, 1.0
    )


# -- quarantined, and a whole session run by the two simulations -------------------------------


def test_a_whole_demonstration_runs_quarantined_and_recorded_as_one(app, loaded, tmp_path):
    runner, demo = _demo(app, loaded, "--demo-speed", FULL_RUN_SPEED,
                         "--sim-participant", FAST, "--sim-experimenter", FAST)
    session = runner.session
    runner.start()
    deadline = time.monotonic() + FULL_RUN_TIMEOUT_S
    skips = 0
    try:
        while not session.closed:
            assert time.monotonic() < deadline, (
                f"the demonstration stalled at {runner.stages[runner.stage_index].id}: "
                f"{runner.rig.experimenter.instruction.text()!r}"
            )
            QApplication.processEvents()
            # As someone showing the software would: every long wait skipped.
            skips += demo.skip_wait() is not None
            time.sleep(0.0005)
    finally:
        # Stopped either way: a session left running keeps the test from ever ending.
        _finish(runner, demo)

    assert runner.completed
    assert skips > 0, "a whole session has waits to skip"
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


def test_a_skip_carries_a_playing_pattern_on_rather_than_replaying_it(app, loaded):
    """Every cycle the skip passed, delivered in one tick, would flood the garment."""
    runner, demo = _demo(app, loaded)
    session = runner.session
    session.clock.start_session()
    garment = session.garment
    garment.play_pattern(next(iter(session.patterns.values())))
    per_cycle = len(garment._pattern_events)
    delivered = []
    deliver = garment._deliver
    garment._deliver = lambda event: (delivered.append(event), deliver(event))
    runner._wait_until(3600.0, lambda: None, lambda: None)
    demo.skip_wait()
    garment.advance()
    # At most a cycle's worth either side of the skip, where replay would be ~an hour's.
    assert len(delivered) <= 2 * per_cycle
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


def test_auto_run_runs_both_fast_until_switched_off(app, loaded):
    """S, 20 Oct 2026 (LOG N7.F17d): switched on and off at any moment, across stages."""
    runner, demo = _demo(app, loaded, "--sim-participant", WATCH)
    controls = demo.controls
    controls.auto_run_button.click()
    assert demo.auto_running and controls.auto_run_button.isChecked()
    assert (demo.participant_mode, demo.experimenter_mode) == (FAST, FAST)
    runner.stage_started.emit("the next stage")
    assert demo.auto_running, "on until switched off, whatever stage begins"
    controls.auto_run_button.click()
    assert not demo.auto_running
    assert (demo.participant_mode, demo.experimenter_mode) == (WATCH, OFF)
    _finish(runner, demo)


def test_who_presses_switches_at_any_moment(app, loaded):
    runner, demo = _demo(app, loaded)
    switch = demo.controls.participant_mode
    switch.buttons[FAST].click()
    assert demo.participant_mode == FAST and switch.mode() == FAST
    switch.buttons[OFF].click()
    assert demo.participant_mode == OFF
    _finish(runner, demo)


def test_demo_vs_session_names_each_difference_with_the_sessions_value(app, loaded):
    runner, demo = _demo(app, loaded)
    shown = demo.controls.differences_dialog().message.text()
    pinprick = runner.session.config.study1["pinprick"]
    assert f"{float(pinprick['isi_min_s']):g}" in shown, "the session's own interval"
    assert f"{float(runner.session.config.study1['demo']['rest_s']):g}" in shown
    _finish(runner, demo)


def test_every_change_of_who_presses_is_logged(app, loaded):
    runner, demo = _demo(app, loaded)
    demo.set_participant(WATCH)
    demo.set_participant(WATCH)  # no change, nothing logged
    demo.set_experimenter(FAST)
    demo.set_participant(OFF)
    modes = [e["detail"] for e in _events(runner.session) if e["event"] == "demo_simulation"]
    assert modes == [f"participant: {OFF}", f"experimenter: {OFF}", f"participant: {WATCH}",
                     f"experimenter: {FAST}", f"participant: {OFF}"]
    _finish(runner, demo)


def test_a_mode_chosen_during_auto_run_is_kept_and_the_other_handed_back(app, loaded):
    """The person who takes the remote mid-run keeps it; the experimenter still goes back."""
    runner, demo = _demo(app, loaded, "--sim-participant", WATCH)
    demo.set_auto_run(True)
    demo.choose("participant", OFF)
    demo.set_auto_run(False)
    assert (demo.participant_mode, demo.experimenter_mode) == (OFF, OFF)
    _finish(runner, demo)


def test_checking_a_demonstration_writes_nothing(loaded, tmp_path):
    """Its folder and allocation are made when it starts, so a refused or cancelled check
    leaves no empty folder behind."""
    args = _args()
    config = run_session.demo_session(loaded, args)
    run_session.preflight(config, args)
    assert not (tmp_path / "demo").exists()


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
    # Any instruction that waits on Next step.
    experimenter.set_instruction(cfg.instruction(runner.session.config, "rekindle_remove"))
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
    experimenter.set_instruction(cfg.instruction(runner.session.config, "rekindle_remove"))
    demo.experimenter._tick()
    assert pressed == []
    _finish(runner, demo)
