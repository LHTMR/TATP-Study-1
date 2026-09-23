"""The masking check and the emergency stop rehearsal. SPEC.md 10.7, 10.9, 13.

Driven through the real windows by the virtual participant, against the recording audio
double, so the whole of each procedure runs headless (SPEC.md 17.1).
"""

from __future__ import annotations

import csv

import pytest
from PySide6.QtWidgets import QApplication
from virtual_participant import Virtual, make_config, make_rig, press

from tatp import config as cfg
from tatp.audio import amplitude
from tatp.setup_checks import (
    AwaitStop,
    MaskingCheck,
    MaskingResult,
    StopRehearsal,
    StopRehearsalResult,
    noise_control_config,
)
from tatp.touchcal import AdjustmentState
from tatp.trials import Choice


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def rig(app, loaded, tmp_path):
    made = make_rig(make_config(loaded, tmp_path))
    yield made
    made.session.close()


def _rows(session, table):
    path = session.files.path(table)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _events(session, name):
    return [row for row in _rows(session, "log") if row["event"] == name]


def _session_values(session):
    session.close()
    return {row["key"]: row["value"] for row in _rows(session, "session")}


def _answers(*sides):
    """Answer `still_audible` with these sides in turn; anything else on the left."""
    queue = list(sides)

    def choose(key, trial):
        return queue.pop(0) if key == "still_audible" else "left"

    return choose


# -- the noise control ------------------------------------------------------------------


def test_the_noise_control_is_the_pressure_control_in_decibels(loaded):
    control = noise_control_config(loaded.hardware["adjustment"], loaded.hardware["audio"])
    audio = loaded.hardware["audio"]
    state = AdjustmentState(control, audio["white_noise_start_dbfs"],
                            audio["white_noise_max_dbfs"], audio["white_noise_start_dbfs"])
    assert state.tap_step_kpa == audio["white_noise_step_db"]
    assert state.rate_final_kpa_s == audio["noise_hold_rate_final_db_s"]
    assert state.hold_delay_s == loaded.hardware["adjustment"]["hold_delay_s"]
    assert state.range_max_kpa == audio["white_noise_max_dbfs"], "the ceiling tops the control"


# -- the masking check ------------------------------------------------------------------


def test_masking_confirmed_first_time(rig):
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    virtual.choose = _answers("right")
    result = virtual.run()

    assert result == MaskingResult(level_dbfs=-30.0, confirmed=True, attempts=1,
                                   earplugs_used=False)
    assert session.audio.noise_running, "the noise stays on for the session"
    assert session.garment.status()["pattern_name"] is None
    starts = [row for row in _rows(session, "garment") if row["event"] == "pattern_start"]
    fixed = session.config.study1["patterns"]["fixed_ct_pattern"]
    assert [row["pattern_name"] for row in starts] == [fixed], "the fixed pattern, always"
    pressures = {
        float(row["pressure_kpa"]) for row in _rows(session, "garment")
        if row["event"] == "set_pressure" and float(row["pressure_kpa"]) > 0
    }
    assert max(pressures) == session.config.hardware["audio"]["masking_check_pressure_kpa"]
    assert _events(session, "masking_threshold")[0]["detail"].endswith("-45.0 dBFS")
    assert _events(session, "participant_cue_tone"), "the cue sounds over the noise"
    values = _session_values(session)
    assert values["white_noise_level_dbfs"] == "-30.0"
    assert values["masking_confirmed"] == "true"
    assert values["masking_attempts"] == "1"
    assert values["earplugs_used"] == "false"


def test_the_masking_keys_keep_the_schema_order(rig):
    """They are written after the start keys and before the closing ones (DATA_SCHEMA.md)."""
    from tatp.datafiles import parse_schema

    virtual = Virtual(rig, MaskingCheck(rig))
    virtual.choose = _answers("right")
    virtual.run()
    rig.session.close()
    _, keys = parse_schema()
    assert [row["key"] for row in _rows(rig.session, "session")] == list(keys)


def test_still_audible_raises_again_then_escalates_to_earplugs(rig):
    session = rig.session
    attempts = session.config.hardware["audio"]["masking_check_max_attempts"]
    virtual = Virtual(rig, MaskingCheck(rig))
    # Audible on every try of the first round, then masked on the first try with earplugs.
    virtual.choose = _answers(*(["left"] * attempts + ["right"]))
    seen_paused = []

    def watch(trial):
        screens = session.config.participant_text["screens"]
        if rig.participant.message.text == screens["paused"]:
            seen_paused.append(session.audio.noise_running)

    virtual.before_step = watch
    result = virtual.run()

    assert result.earplugs_used and result.confirmed
    assert result.attempts == attempts + 1, "the count carries on across the restart"
    assert seen_paused and not any(seen_paused), "the noise is off for the exchange"
    assert _events(session, "experimenter_alert")
    assert _events(session, "white_noise_stopped")
    assert "experimenter_tone" in [event[0] for event in session.audio.output.events]
    # Restarted from step 1: the noise went back to the start level after earplugs.
    starts = [e for e in session.audio.output.events if e[0] == "start_noise"]
    assert starts[-1] == ("start_noise", amplitude(session.audio.start_dbfs))
    assert len(_events(session, "masking_threshold")) == 2


def test_the_ceiling_escalates_before_the_attempts_run_out(rig):
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    virtual.noise_levels["mask_level"] = session.audio.max_dbfs
    virtual.choose = _answers("left", "right")
    result = virtual.run()
    assert result.earplugs_used and result.attempts == 2
    assert "ceiling" in _events(session, "masking_escalated")[0]["detail"]


def test_unmaskable_even_with_earplugs_is_recorded_not_refused(rig):
    session = rig.session
    attempts = session.config.hardware["audio"]["masking_check_max_attempts"]
    virtual = Virtual(rig, MaskingCheck(rig))
    virtual.choose = _answers(*(["left"] * (2 * attempts)))
    result = virtual.run()
    assert not result.confirmed and result.earplugs_used
    assert result.attempts == 2 * attempts
    assert _events(session, "masking_not_confirmed")[0]["severity"] == "warning"
    assert _session_values(session)["masking_confirmed"] == "false"


def test_a_stop_during_the_masking_check_repeats_the_step(rig):
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    virtual.choose = _answers("right")
    stopped = []

    def stop_once(trial):
        if not stopped and isinstance(trial, Choice):
            stopped.append(True)
            press(rig.participant, "f5")

    virtual.before_step = stop_once
    result = virtual.run()
    assert stopped and result.confirmed
    assert _events(session, "garment_restored"), "the pattern came back after the cue"


# -- the stop rehearsal -----------------------------------------------------------------


def test_the_rehearsal_fires_the_real_stop_and_shows_the_resume(rig, loaded, tmp_path):
    session = rig.session
    screens = session.config.participant_text["screens"]
    seen = []
    virtual = Virtual(rig, StopRehearsal(rig))

    def watch(trial):
        seen.append(rig.participant.message.text)

    virtual.before_step = watch
    result = virtual.run()

    assert result == StopRehearsalResult(press_detected=True)
    stops = _events(session, "emergency_stop")
    assert len(stops) == 1 and stops[0]["origin"] == "participant", "the real path's own event"
    assert _events(session, "stop_rehearsal_press_detected")
    assert _events(session, "resumed")[0]["origin"] == "experimenter"
    assert screens["stop_rehearsal"] in seen
    assert screens["stop_rehearsal_done"] in seen
    assert seen.index(screens["stop_rehearsal"]) < seen.index(screens["stop_rehearsal_done"])
    commands = [row["event"] for row in _rows(session, "garment")]
    assert "stop" in commands
    fixed = session.config.study1["patterns"]["fixed_ct_pattern"]
    starts = [row for row in _rows(session, "garment") if row["event"] == "pattern_start"]
    assert [row["pattern_name"] for row in starts] == [fixed, fixed], "played, then restored"
    values = _session_values(session)
    assert values["stop_rehearsal_ran"] == "true"
    assert values["stop_rehearsal_press_detected"] == "true"


def test_with_no_pressure_set_the_rehearsal_commands_none_and_says_so(app, loaded, tmp_path):
    """Local item L11: the pressure is S's. Nothing is commanded that nobody chose."""
    training = {"stop_rehearsal_pressure_kpa": None}
    rig = make_rig(make_config(loaded, tmp_path, training=training))
    try:
        session = rig.session
        Virtual(rig, StopRehearsal(rig)).run()
        assert _events(session, "stop_rehearsal_no_pressure")[0]["severity"] == "warning"
        assert not [
            row for row in _rows(session, "garment")
            if row["event"] == "set_pressure" and float(row["pressure_kpa"]) > 0
        ]
    finally:
        rig.session.close()


def test_with_a_pressure_set_the_rehearsal_runs_at_it(app, loaded, tmp_path):
    training = {"stop_rehearsal_pressure_kpa": 55.0}
    rig = make_rig(make_config(loaded, tmp_path, training=training))
    try:
        Virtual(rig, StopRehearsal(rig)).run()
        pressures = {
            float(row["pressure_kpa"]) for row in _rows(rig.session, "garment")
            if row["event"] == "set_pressure" and float(row["pressure_kpa"]) > 0
        }
        assert max(pressures) == 55.0
    finally:
        rig.session.close()


def test_the_experimenter_can_move_on_without_a_press(rig):
    session = rig.session
    virtual = Virtual(rig, StopRehearsal(rig))
    virtual.press_stop = False

    def proceed(trial):
        if isinstance(trial, AwaitStop):
            rig.experimenter.proceed_requested.emit()

    virtual.before_step = proceed
    result = virtual.run()
    assert result == StopRehearsalResult(press_detected=False)
    assert _events(session, "stop_rehearsal_no_press")[0]["severity"] == "warning"
    assert _session_values(session)["stop_rehearsal_press_detected"] == "false"


def test_a_pause_before_the_press_is_an_ordinary_interruption(rig):
    session = rig.session
    virtual = Virtual(rig, StopRehearsal(rig))
    paused = []

    def pause_once(trial):
        if not paused and isinstance(trial, AwaitStop):
            paused.append(True)
            rig.experimenter.pause_requested.emit()

    virtual.before_step = pause_once
    result = virtual.run()
    assert result.press_detected, "the screen came back and the stop was then pressed"
    assert len(_events(session, "emergency_stop")) == 1
