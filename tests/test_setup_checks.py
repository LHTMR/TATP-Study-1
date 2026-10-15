"""The masking check and the emergency stop rehearsal. SPEC.md 10.7, 10.9, 13.

Driven through the real windows by the virtual participant, against the recording audio
double, so the whole of each procedure runs headless (SPEC.md 17.1).
"""

from __future__ import annotations

import csv

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from virtual_participant import Virtual, make_config, make_rig, press

from tatp import config as cfg
from tatp.audio import amplitude
from tatp.setup_checks import (
    AwaitStop,
    MaskingCheck,
    MaskingResult,
    NoiseAdjustment,
    StopRehearsal,
    StopRehearsalResult,
    noise_control,
)
from tatp.touchcal import AdjustmentState
from tatp.ui.vas import QT_KEYS


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


def _is_masking_step(trial) -> bool:
    return isinstance(trial, NoiseAdjustment) and trial.screen_key == "mask_level"


def _reports_audible(rig, times: int, also=lambda trial: None):
    """The experimenter's Next step on the first `times` masking steps: the participant has
    said they can still hear the garment (SPEC.md 10.7)."""
    reported = []

    def report(trial):
        also(trial)
        if _is_masking_step(trial) and len(reported) < times and trial not in reported:
            reported.append(trial)
            rig.experimenter.proceed_requested.emit()

    return report


# -- the noise control ------------------------------------------------------------------


def test_the_noise_control_is_the_pressure_control_in_decibels(loaded):
    control = noise_control(loaded.hardware["adjustment"], loaded.hardware["audio"])
    audio = loaded.hardware["audio"]
    state = AdjustmentState(control, audio["white_noise_start_dbfs"],
                            audio["white_noise_max_dbfs"], audio["white_noise_start_dbfs"])
    assert state.tap_step == audio["white_noise_step_db"]
    assert state.rate_final_per_s == audio["noise_hold_rate_final_db_s"]
    assert state.hold_delay_s == loaded.hardware["adjustment"]["hold_delay_s"]
    assert state.range_max == audio["white_noise_max_dbfs"], "the ceiling tops the control"


# -- the masking check ------------------------------------------------------------------


def test_masking_confirmed_first_time(rig):
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
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


def test_there_is_no_separate_still_audible_screen(rig):
    """S, 5 Oct 2026: the question is the masking screen's own instruction, not a screen."""
    virtual = Virtual(rig, MaskingCheck(rig))
    seen = []
    virtual.before_step = lambda trial: seen.append(type(trial).__name__)
    virtual.run()
    assert "Choice" not in seen
    assert "still_audible" not in rig.session.config.participant_text["choices"]


def test_the_setup_keys_keep_the_schema_order(rig):
    """Rehearsal, then masking, after the start keys and before the closing ones
    (DATA_SCHEMA.md), in the order the session runs them."""
    from tatp.datafiles import parse_schema

    Virtual(rig, StopRehearsal(rig)).run()
    Virtual(rig, MaskingCheck(rig)).run()
    rig.session.close()
    _, keys = parse_schema()
    assert [row["key"] for row in _rows(rig.session, "session")] == list(keys)


def test_the_experimenters_next_step_during_the_first_step_does_nothing(rig):
    """Only the masking step takes the report: before the garment runs there is nothing to
    hear."""
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    pressed = []

    def press_next(trial):
        finding = isinstance(trial, NoiseAdjustment) and trial.screen_key == "find_level"
        if finding and not pressed:
            pressed.append(trial)
            rig.experimenter.proceed_requested.emit()

    virtual.before_step = press_next
    result = virtual.run()
    assert pressed and result.confirmed and not result.earplugs_used
    assert not _events(session, "masking_reported_audible")


def test_still_audible_is_reported_and_earplugs_restart_the_check(rig):
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    seen_paused = []

    def watch(trial):
        screens = session.config.participant_text["screens"]
        if rig.participant.message.text == screens["paused"]:
            seen_paused.append(session.audio.noise_running)

    # Audible on the first masking step, then covered with earplugs in.
    virtual.before_step = _reports_audible(rig, 1, also=watch)
    result = virtual.run()

    assert result.earplugs_used and result.confirmed
    assert result.attempts == 2, "the count carries on across the restart"
    assert seen_paused and not any(seen_paused), "the noise is off for the exchange"
    reported = _events(session, "masking_reported_audible")
    assert len(reported) == 1 and reported[0]["origin"] == "experimenter"
    assert _events(session, "masking_escalated")[0]["severity"] == "warning"
    assert _events(session, "white_noise_stopped")
    # Restarted from step 1: the noise went back to the start level after earplugs.
    starts = [e for e in session.audio.output.events if e[0] == "start_noise"]
    assert starts[-1] == ("start_noise", amplitude(session.audio.start_dbfs))
    assert len(_events(session, "masking_threshold")) == 2


def test_a_double_clicked_next_step_does_not_record_earplugs_never_fitted(rig):
    """Review of 9c84769: the second click of a double click must not be taken as "the
    earplugs are in". Within the lockout it is ignored, and the earplugs are recorded only
    by a Next step after it."""
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    after_double = []

    def double_click(trial):
        if _is_masking_step(trial) and not after_double:
            rig.experimenter.proceed_requested.emit()
            rig.experimenter.proceed_requested.emit()
            after_double.append(len(_events(session, "earplugs_fitted")))

    virtual.before_step = double_click
    result = virtual.run()
    assert after_double == [0], "the second click fitted no earplugs"
    assert result.earplugs_used, "the Next step after the lockout did"
    proceeds = [r for r in _events(session, "proceed") if r["detail"] == "MaskingCheck"]
    assert proceeds, "the report goes through the procedure's own Next step, and is logged"


def test_a_next_step_during_a_stop_in_the_masking_step_reports_nothing(rig):
    """The report is the procedure's proceed, so a Next step while interrupted is ignored."""
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    done = []

    def stop_then_next(trial):
        if _is_masking_step(trial) and not done:
            done.append(True)
            press(rig.participant, "period")
            rig.experimenter.proceed_requested.emit()

    virtual.before_step = stop_then_next
    result = virtual.run()
    assert done and not result.earplugs_used
    assert not _events(session, "masking_reported_audible")


def test_a_confirm_at_the_ceiling_is_flagged_in_the_data_and_to_the_experimenter(rig):
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    virtual.noise_levels["mask_level"] = session.audio.max_dbfs
    result = virtual.run()
    assert result.confirmed, "the confirm keeps its meaning"
    flagged = _events(session, "masking_at_ceiling")
    assert len(flagged) == 1 and flagged[0]["severity"] == "warning"
    warning = rig.experimenter.text["warnings"]["masking_at_ceiling"]
    # A warning, apart from the routine status, so the next one does not replace it.
    assert rig.experimenter._warning_text == warning


def test_a_confirm_below_the_ceiling_is_not_flagged(rig):
    Virtual(rig, MaskingCheck(rig)).run()
    assert not _events(rig.session, "masking_at_ceiling")


def test_the_settled_screen_does_not_offer_next_step(rig):
    """15 Oct 2026 pilot review: the masking step's "press Next step if they can still hear"
    stayed up on the closing screen, where Next step does nothing (LOG N7.F11b4)."""
    Virtual(rig, MaskingCheck(rig)).run()
    assert rig.experimenter.instruction.text() == cfg.instruction(
        rig.session.config, "masking_done"
    )


def test_the_earplug_warning_is_cleared_when_the_check_restarts(rig):
    warning = rig.experimenter.text["warnings"]["masking_failed"]
    statuses = []

    def watch(trial):
        if isinstance(trial, NoiseAdjustment):
            statuses.append(rig.experimenter._warning_text)

    virtual = Virtual(rig, MaskingCheck(rig))
    virtual.before_step = _reports_audible(rig, 1, also=watch)
    virtual.run()
    assert warning not in statuses[1:], "gone once the earplugs are in"
    assert rig.experimenter._warning_text != warning


def test_the_experimenter_is_told_what_next_step_does_in_the_masking_step(rig):
    shown = []

    def watch(trial):
        if _is_masking_step(trial):
            shown.append(rig.experimenter._instruction_text)

    virtual = Virtual(rig, MaskingCheck(rig))
    virtual.before_step = _reports_audible(rig, 1, also=watch)
    virtual.run()
    assert shown[0] == cfg.instruction(rig.session.config, "masking_check_mask")
    assert shown[-1] == cfg.instruction(rig.session.config, "masking_check_mask_earplugs")


def test_unmaskable_even_with_earplugs_is_recorded_not_refused(rig):
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    virtual.before_step = _reports_audible(rig, 2)
    result = virtual.run()
    assert not result.confirmed and result.earplugs_used
    assert result.attempts == 2
    assert _events(session, "masking_not_confirmed")[0]["severity"] == "warning"
    assert _session_values(session)["masking_confirmed"] == "false"


def _stamped_press(window, name: str, held_ms: int) -> None:
    """A press of `held_ms` by the key events' own stamps, as the remote's arrive."""
    for kind, stamp_ms in ((QEvent.KeyPress, 1000), (QEvent.KeyRelease, 1000 + held_ms)):
        event = QKeyEvent(kind, QT_KEYS[name], Qt.NoModifier)
        event.setTimestamp(stamp_ms)
        (window.keyPressEvent if kind == QEvent.KeyPress else window.keyReleaseEvent)(event)


def test_an_ordinary_press_turns_the_noise_down_while_the_garment_plays(rig):
    """S's 5 Oct 2026 lab run: "the noise cannot be turned down in the second step".

    A deliberate press on the remote lasts about 200 ms. That fell between the old tap
    threshold and the hold delay, where a press moved nothing, and turning down is done by
    single presses. Here each button gets that press in the masking step.
    """
    session = rig.session
    step_db = session.config.hardware["audio"]["white_noise_step_db"]
    held_ms = int(round(session.config.hardware["adjustment"]["hold_delay_s"] * 2 / 3 * 1000))
    virtual = Virtual(rig, MaskingCheck(rig))
    moved = []

    def press_each_way(trial):
        if _is_masking_step(trial) and not moved:
            start = session.audio.noise_level_dbfs
            _stamped_press(rig.participant, "pageup", held_ms)
            down = session.audio.noise_level_dbfs
            _stamped_press(rig.participant, "pagedown", held_ms)
            moved.append((start - down, session.audio.noise_level_dbfs - down))

    virtual.before_step = press_each_way
    virtual.run()
    assert moved == [(step_db, step_db)]


def test_a_stop_during_the_masking_check_repeats_the_step(rig):
    session = rig.session
    virtual = Virtual(rig, MaskingCheck(rig))
    stopped = []

    def stop_once(trial):
        if not stopped and _is_masking_step(trial):
            stopped.append(True)
            press(rig.participant, "period")

    virtual.before_step = stop_once
    result = virtual.run()
    assert stopped and result.confirmed and result.attempts == 1, "the same attempt, repeated"
    assert _events(session, "garment_restored"), "the pattern came back after the cue"


@pytest.mark.parametrize("screen_key", ["find_level", "mask_level"])
def test_a_stop_during_audio_setup_is_shown_to_the_participant(rig, app, monkeypatch,
                                                               screen_key):
    """S's 5 Oct 2026 lab run: a stop pressed during audio setup was not acknowledged.

    Both noise screens and the stop screen are the same message widget, which before
    docs/LOG.md N7.F5 was never repainted when one message replaced another: the participant
    kept looking at the instruction. Checked painted, not only set.
    """
    participant = rig.participant
    painted = []
    paint = participant.message.paintEvent
    monkeypatch.setattr(
        participant.message, "paintEvent", lambda event: (painted.append(1), paint(event))
    )
    participant.show()
    virtual = Virtual(rig, MaskingCheck(rig))
    seen = []

    def stop_once(trial):
        if not seen and isinstance(trial, NoiseAdjustment) and trial.screen_key == screen_key:
            app.processEvents()
            painted.clear()
            press(participant, "period")
            app.processEvents()
            seen.append((participant.message.text, bool(painted)))

    virtual.before_step = stop_once
    virtual.run()
    participant.close()
    stop_text = rig.session.config.participant_text["screens"]["emergency_stop"]
    assert seen == [(stop_text, True)]


# -- the stop rehearsal -----------------------------------------------------------------


def test_the_rehearsal_fires_the_real_stop_and_shows_the_resume(rig, loaded, tmp_path):
    session = rig.session
    screens = session.config.participant_text["screens"]
    seen = []
    instructions = []
    real = rig.experimenter.set_instruction
    rig.experimenter.set_instruction = lambda text: (instructions.append(text), real(text))
    virtual = Virtual(rig, StopRehearsal(rig))

    def watch(trial):
        seen.append(rig.participant.message.text)

    virtual.before_step = watch
    result = virtual.run()

    assert result == StopRehearsalResult(press_detected=True)
    # After the press, what to say and then Resume; after the Resume, not Resume again
    # (LOG N7.F11b3).
    done = cfg.instruction(session.config, "stop_rehearsal_done")
    resume = cfg.instruction(session.config, "stop_rehearsal_resume")
    assert instructions.index(resume) < instructions.index(done)
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
    training = {**loaded.study1["training"], "stop_rehearsal_pressure_kpa": None}
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
    training = {**loaded.study1["training"], "stop_rehearsal_pressure_kpa": 55.0}
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
