"""Protocol A driven end to end through Qt. SPEC.md 8.2, 8.3, 11, 11.1, 13.

A virtual participant answers each rating with key presses, as `tests/test_pinprick.py` does,
and a virtual experimenter emits the experimenter-action signals. The clock is accelerated so
a run of a dozen applications costs a fraction of a second; every interval still comes from
config. What is checked is what reached the data files.
"""

from __future__ import annotations

import csv
import math
import time

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from virtual_participant import auto_apply

from tatp import config as cfg
from tatp.clock import Clock
from tatp.pinprick import (
    BrushProtocol,
    IntolerableCap,
    LongProtocol,
    LongResult,
    ShortProtocol,
    ladder_index,
    prior_for,
)
from tatp.procedure import NO_RERUNS_LEFT, Rig
from tatp.responder import Responder
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
CLOCK_SPEED = 1000.0
SPIN_TIMEOUT_S = 20.0
# The virtual participant's own F40, between the 26 g (255 mN) and 60 g (588 mN) filaments.
F40_MN = 400.0
# 75 % after the first right press, then 0.5 % a press: enough to pin the marker at the top.
PRESSES_TO_THE_CEILING = 60


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


def _make_rig(loaded, tmp_path, study1=None, seed=7, trained=True):
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"],
                                            "folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware,
                           "study1": study1 or loaded.study1})
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED), rng_seed=seed
    )
    if trained:
        # The VAS training (SPEC.md 10.6) as already given, so these tests see only the
        # protocol; `test_the_pain_training_comes_before_the_first_application` sees it.
        session.vas_trained.update(session.trained_scales)
    session.start()
    session.set_phase("pre_sensitisation")
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    participant.resize(1280, 800)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    made = Rig(session, participant, experimenter)
    auto_apply(made)
    return made


@pytest.fixture
def rig(app, loaded, tmp_path):
    made = _make_rig(loaded, tmp_path)
    yield made
    made.session.close()


def _spin(condition) -> None:
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the procedure did not reach the expected state")
        QApplication.processEvents()
        time.sleep(0.0005)


def _press(widget, name, times=1) -> None:
    key = QT_KEYS[name]
    for _ in range(times):
        widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
        widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def _rows(session, table):
    path = session.files.path(table)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _events(session):
    return [row["event"] for row in _rows(session, "log")]


def _observer(trial) -> int:
    """How many right presses: one (75 %) at or above the participant's F40, else none."""
    force = trial.session.config.filaments["filaments"]
    applied = next(f for f in force if f["label_g"] == trial.applied_label_g)
    return 1 if applied["force_nominal_mn"] >= F40_MN else 0


def _answer(participant, right_presses: int) -> None:
    if right_presses:
        _press(participant.vas, "pagedown", right_presses)
    else:
        _press(participant.vas, "pageup")
    _press(participant.vas, "f5")


def _drive(procedure, done, respond=_observer, before_answer=None, max_trials=60) -> int:
    """Answer every rating until the procedure finishes. Returns how many were answered."""
    participant = procedure.participant
    answered = 0
    def applying() -> bool:
        return getattr(procedure._trial, "awaits_proceed", False)

    while not done:
        _spin(lambda: done or applying()
              or participant.stack.currentWidget() is participant.vas)
        if done:
            break
        if applying():
            # Applied: the experimenter says so, and the rating is cued from it (N7.F16f).
            procedure.experimenter.proceed_requested.emit()
            continue
        trial = procedure._trial
        if before_answer is not None:
            before_answer(answered, trial)
        _answer(participant, respond(trial))
        answered += 1
        assert answered <= max_trials, "the protocol did not end"
    return answered


def _start(procedure) -> list:
    done: list = []
    procedure.finished.connect(done.append)
    procedure.start()
    procedure.experimenter.proceed_requested.emit()
    return done


def _cap(rig) -> IntolerableCap:
    pinprick = rig.session.config.study1["pinprick"]
    return IntolerableCap(pinprick["intolerable_sites_for_global_cap"])


def _long(rig, cap=None):
    prior = prior_for(rig.session.config, "pre_sensitisation", 1, None)
    return LongProtocol(rig, "secondary", prior, cap or _cap(rig))


# -- the long protocol ---------------------------------------------------------------------


def test_the_long_protocol_searches_measures_and_estimates(rig):
    session = rig.session
    protocol = _long(rig)
    done = _start(protocol)
    _drive(protocol, done)
    result = done[0]
    assert isinstance(result, LongResult)

    rows = _rows(session, "pinprick")
    assert [r["purpose"] for r in rows].count("measure") == 9
    assert rows[0]["filament_label_g"] == "26", "the configured prior at pre-S of session 1"
    assert all(r["protocol"] == "long" and r["run_index"] == "1" for r in rows)
    assert [int(r["trial_index"]) for r in rows] == list(range(1, len(rows) + 1))
    # The site rotates on every application.
    sites = [int(r["site_index"]) for r in rows]
    assert all(a != b for a, b in zip(sites, sites[1:], strict=False))

    # Search 26 g (below), then 60 g (at or above): the crossing is 60 g, and the two below.
    measured = {r["filament_label_g"] for r in rows if r["purpose"] == "measure"}
    assert measured == {"15", "26", "60"}

    (calibration,) = _rows(session, "calibration_pinprick")
    assert calibration["start_filament_label_g"] == "26"
    assert calibration["start_source"] == "config_default"
    assert calibration["applications_total"] == str(len(rows))
    assert calibration["superseded"] == "false" and calibration["capped"] == "false"
    assert calibration["out_of_range"] == "false"
    assert float(calibration["f40_mn"]) == pytest.approx(result.f40_mn)
    assert calibration["chosen_filament_label_g"] == result.chosen_filament_label_g
    assert calibration["ordinal_rho"] != ""
    assert "measure_plan" in _events(session)


def test_the_pain_training_comes_before_the_first_application(app, loaded, tmp_path):
    """SPEC.md 10.6: after the experimenter's start and before the first cue, once only."""
    made = _make_rig(loaded, tmp_path, trained=False)
    try:
        participant = made.participant
        protocol = _long(made)
        done = _start(protocol)
        # The session's first practice is introduced first (LOG N7.F14a).
        _spin(lambda: participant.message.text == participant.text["screens"]["practice_intro"])
        participant.message_confirmed.emit()
        _spin(lambda: participant.stack.currentWidget() is participant.vas)
        vas = participant.vas
        assert vas.explaining and vas.scale == "pain" and not vas.practising
        assert "warning_cue" not in _events(made.session), "no stimulus before the training"
        _press(vas, "pagedown")
        _press(vas, "f5")
        assert not vas.state.visible, "a button did something while the experimenter explained"
        assert "vas_training_confirmed" not in _events(made.session), (
            "▶ dismissed the training before the experimenter's go"
        )
        # The anchors explained aloud; the experimenter's go.
        made.experimenter.proceed_requested.emit()
        assert vas.practising
        # The practice: the marker moved and confirmed, as on a rating.
        _press(vas, "pagedown")
        _press(vas, "pagedown")
        _press(vas, "f5")
        _drive(protocol, done)
        events = _events(made.session)
        assert events.count("vas_training_confirmed") == 1
        assert events.count("vas_practice_rating") == 1
        assert events.index("vas_practice_rating") < events.index("vas_training_confirmed")
        # Never a ratings row: one pinprick row per application, each after its own cue.
        assert len(_rows(made.session, "pinprick")) == events.count("warning_cue")
        assert events.index("vas_training_shown") < events.index("vas_training_explained")
        assert events.index("vas_training_explained") < events.index("vas_training_confirmed")
        assert events.index("vas_training_confirmed") < events.index("warning_cue")
    finally:
        made.session.close()


def test_the_same_seed_gives_the_same_sequence(app, loaded, tmp_path):
    def sequence(folder, seed):
        made = _make_rig(loaded, tmp_path / folder, seed=seed)
        protocol = _long(made)
        done = _start(protocol)
        _drive(protocol, done)
        labels = [(r["filament_label_g"], r["site_index"]) for r in _rows(made.session,
                                                                           "pinprick")]
        made.session.close()
        return labels

    assert sequence("a", 11) == sequence("b", 11)


def test_the_run_waits_for_the_experimenter(rig):
    protocol = _long(rig)
    protocol.start()
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline:
        QApplication.processEvents()
    assert rig.participant.stack.currentWidget() is not rig.participant.cue
    # The ready line says what is about to be applied, not only "ready" (LOG N7.F11b7).
    text = rig.experimenter.text
    assert rig.experimenter.instruction.text() == cfg.instruction(
        rig.session.config, "ready_long", region=text["terms"]["regions"][protocol.region],
        filament=protocol.prior.start_filament_label_g,
    )
    protocol.cancel()


def test_a_stop_after_delivery_counts_it_and_repeats_at_the_next_site(rig):
    session, participant, experimenter = rig.session, rig.participant, rig.experimenter
    protocol = _long(rig)
    done = _start(protocol)
    stopped = []

    def stop_once(answered, trial):
        if answered == 3 and not stopped:
            assert trial.stimulus_delivered, "the rating is cued after the stimulus"
            stopped.append((trial.trial_index, trial.application.site_index))
            participant.emergency_stop.emit()
            assert participant.message.text == participant.text["screens"]["emergency_stop"]
            experimenter.resume_requested.emit()
            _spin(lambda: participant.stack.currentWidget() is participant.vas)

    _drive(protocol, done, before_answer=stop_once)
    rows = _rows(session, "pinprick")
    events = _events(session)
    assert stopped and "trial_cancelled" in events and "trial_lost_after_delivery" in events
    lost_index, lost_site = stopped[0]
    # No row for the lost application, but it counts as delivered.
    assert lost_index not in [int(r["trial_index"]) for r in rows]
    assert done[0].applications_total == len(rows) + 1
    repeat = next(r for r in rows if int(r["trial_index"]) == lost_index + 1)
    assert int(repeat["site_index"]) != lost_site, "the lost site was touched; rotate on"
    assert [r["purpose"] for r in rows].count("measure") == 9


def test_a_stop_before_delivery_repeats_the_same_application(rig):
    session, participant, experimenter = rig.session, rig.participant, rig.experimenter
    protocol = _long(rig)
    done = _start(protocol)
    _spin(lambda: participant.stack.currentWidget() is participant.cue)
    first = protocol._trial
    assert not first.stimulus_delivered
    participant.emergency_stop.emit()
    experimenter.resume_requested.emit()
    _drive(protocol, done)
    rows = _rows(session, "pinprick")
    assert "trial_lost_before_delivery" in _events(session)
    assert rows[0]["trial_index"] == "1"
    assert rows[0]["site_index"] == str(first.application.site_index)
    assert done[0].applications_total == len(rows)


def test_a_resume_in_the_interval_restores_please_wait(app, loaded, tmp_path):
    """The interval is longer than `cues.please_wait_min_s` (13-17 s), so it says so (LOG
    N7.F14d), and a resume puts that back rather than leaving the stop screen up."""
    # Ten real seconds, so what is left of it at the resume never depends on the machine's load:
    # at the test's clock speed 13-17 s is gone in 17 ms, and the interval runs from the
    # delivery press (LOG N7.F17a).
    interval_s = 10 * CLOCK_SPEED
    pinprick = {**loaded.study1["pinprick"], "isi_min_s": interval_s, "isi_max_s": interval_s}
    rig = _make_rig(loaded, tmp_path, study1={**loaded.study1, "pinprick": pinprick})
    participant, experimenter = rig.participant, rig.experimenter
    please_wait = participant.text["screens"]["please_wait"]
    protocol = _long(rig)
    _start(protocol)
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    _answer(participant, 0)  # now in the interval
    assert participant.message.text == please_wait
    participant.emergency_stop.emit()
    experimenter.resume_requested.emit()
    assert participant.message.text == please_wait, "not the stop screen"
    protocol.cancel()
    rig.session.close()


def test_a_participant_awaited_too_long_is_warned_of_and_logged(rig):
    """SPEC.md 8.3: warned and logged, never auto-advanced. Through the rig's own connection,
    so a broken one fails here (spec review of N7.F17e; CLAUDE.md engineering lesson 1)."""
    experimenter = rig.experimenter
    experimenter.set_no_response_s(0.0)
    experimenter.set_status(experimenter.text["instructions"]["await_participant"])
    experimenter.refresh()
    assert experimenter._no_response_shown is not None
    (row,) = [r for r in _rows(rig.session, "log") if r["event"] == "no_response"]
    assert row["severity"] == "warning"
    experimenter.refresh()
    assert _events(rig.session).count("no_response") == 1, "logged once, not every refresh"


def test_a_rest_no_longer_than_please_wait_min_s_is_blank(rig):
    participant = rig.participant
    threshold_s = rig.session.config.study1["cues"]["please_wait_min_s"]
    participant.show_rest(threshold_s)
    assert participant.message.text == ""
    participant.show_rest(threshold_s + 0.1)
    assert participant.message.text == participant.text["screens"]["please_wait"]


def test_the_interval_shows_the_next_application_counting_down_to_it(app, loaded, tmp_path):
    """The experimenter prepares the next application during the interval (S, 16 Oct 2026;
    LOG N7.F14c). The one just rated is on the status line; its rating never is."""
    # Long enough at the test's clock speed to be read while it runs: about a real second.
    interval_s = CLOCK_SPEED
    pinprick = {**loaded.study1["pinprick"], "isi_min_s": interval_s, "isi_max_s": interval_s}
    rig = _make_rig(loaded, tmp_path, study1={**loaded.study1, "pinprick": pinprick})
    participant, experimenter = rig.participant, rig.experimenter
    config = rig.session.config
    protocol = _long(rig)
    done = _start(protocol)
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    first = protocol._trial
    _answer(participant, 0)
    expected = protocol._expected
    assert expected is not None and expected.trial_index == first.trial_index + 1
    force_mn = next(f["force_nominal_mn"] for f in config.filaments["filaments"]
                    if f["label_g"] == expected.filament_label_g)

    def shown(seconds: int) -> str:
        return cfg.instruction(
            config, "next_filament", seconds=seconds, site=expected.site_index,
            region=experimenter.text["terms"]["regions"][expected.region],
            filament=expected.filament_label_g, force_mn=force_mn,
        )

    def remaining() -> int:
        # To when the application is due: the interval, then the warning cue's lead.
        due_s = protocol._interval_s + config.study1["cues"]["warning_lead_s"]
        return math.ceil(rig.session.clock.remaining_s(protocol._interval_start_s, due_s))

    def redrawn() -> tuple[int, str, list[str]]:
        # The test clock runs fast, so seconds can pass during the redraw itself -- as many as
        # the machine's load makes them: any count from the reading before to the one after.
        before = remaining()
        protocol._show_expected()
        text = experimenter.instruction.text()
        return before, text, [shown(s) for s in range(remaining(), before + 1)]

    try:
        before, text, possible = redrawn()
        assert text in possible, text
        assert experimenter.status.text() == cfg.instruction(
            config, "received_filament", filament=first.applied_label_g,
            site=first.application.site_index,
        )
        rig.session.clock.skip(1.0)
        after, text, possible = redrawn()
        assert after < before and text in possible, "it counts down"
        # Its last seconds under "Prepare", in the words the cue goes on with, so nothing
        # changes for the second the cue lasts (S, 22 Oct 2026).
        lead_s = config.study1["cues"]["experimenter_prepare_lead_s"]
        rig.session.clock.skip(max(0.0, remaining() - lead_s + 0.5))
        protocol._show_expected()
        assert experimenter._heading == "prepare"
        assert experimenter.instruction.text() == cfg.instruction(
            config, "prepare_filament", filament=expected.filament_label_g)
        _spin(lambda: protocol._trial is not None and protocol._trial is not first)
        assert protocol._trial.application == expected, "the one shown is the one given"
        _drive(protocol, done)
    finally:
        protocol.cancel()
        rig.session.close()


def test_a_resume_while_waiting_to_start_restores_the_standby_screen(rig):
    """The wait for the go shows standby, not a blank identical to the one under a stimulus
    (15 Oct 2026 pilot review, LOG N7.F11c8), and a resume puts it back."""
    participant, experimenter = rig.participant, rig.experimenter
    protocol = _long(rig)
    protocol.start()
    standby = participant.text["screens"]["standby"]
    assert participant.message.text == standby
    experimenter.pause_requested.emit()
    assert participant.message.text == participant.text["screens"]["paused"]
    experimenter.proceed_requested.emit()
    assert participant.stack.currentWidget() is not participant.cue, "no start while paused"
    experimenter.resume_requested.emit()
    assert participant.message.text == standby
    protocol.cancel()


def test_a_cap_is_required(rig):
    prior = prior_for(rig.session.config, "pre_sensitisation", 1, None)
    with pytest.raises(AssertionError, match="IntolerableCap"):
        LongProtocol(rig, "secondary", prior, None)
    with pytest.raises(AssertionError, match="IntolerableCap"):
        ShortProtocol(rig, "primary", "26", None)


def test_the_last_application_at_the_cap_ends_the_run_with_no_rest(app, loaded, tmp_path):
    """S, 22 Oct 2026: no rest after a series' last application -- here the cap's -- so
    there is nothing to discard after it, and the run ends at its rating."""
    study1 = {**loaded.study1, "pinprick": {**loaded.study1["pinprick"], "max_applications": 2}}
    rig = _make_rig(loaded, tmp_path, study1=study1)
    protocol = _long(rig)
    done = _start(protocol)
    for _ in range(2):
        _spin(lambda: rig.participant.stack.currentWidget() is rig.participant.vas)
        _answer(rig.participant, 0)
    _spin(lambda: done)
    assert done[0].capped and len(_rows(rig.session, "pinprick")) == 2
    intervals = [e for e in _events(rig.session) if e == "interval"]
    assert len(intervals) == 1, "a rest after the first, none after the last"
    rig.session.close()


def test_a_discard_writes_a_discards_row_and_repeats(rig):
    session, experimenter = rig.session, rig.experimenter
    protocol = _long(rig)
    done = _start(protocol)
    participant = rig.participant
    # Answer the first rating, then discard it during the interval.
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    _answer(participant, _observer(protocol._trial))
    experimenter.discard_requested.emit()
    _drive(protocol, done)

    rows = _rows(session, "pinprick")
    (discard,) = _rows(session, "discards")
    assert discard["table"] == "pinprick"
    assert discard["trial_timestamp_iso"] == rows[0]["timestamp_iso"]
    assert discard["trial_index"] == "1"
    assert rows[1]["filament_label_g"] == rows[0]["filament_label_g"], "the same plan, repeated"
    assert rows[1]["trial_index"] == "2"
    assert done[0].applications_total == len(rows)


def test_discard_is_offered_only_while_there_is_something_to_discard(rig):
    """docs/LOG.md N7.U10: during the interval after a completed application, and not before,
    during the next one, or once the protocol has ended. Hidden rather than disabled when not
    offered, since the 15 Oct 2026 pilot review."""
    experimenter, participant = rig.experimenter, rig.participant
    protocol = _long(rig)
    protocol.start()
    assert not experimenter._awaiting["discard"], "nothing has been applied yet"
    experimenter.proceed_requested.emit()
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    assert not experimenter._awaiting["discard"], "the application is not complete"
    _answer(participant, _observer(protocol._trial))
    assert experimenter._awaiting["discard"], "the interval after a rated application"
    assert experimenter.correct_button.isEnabled()
    experimenter.discard_requested.emit()
    assert not experimenter._awaiting["discard"], "discarded, nothing is left to discard"
    protocol.cancel()
    assert experimenter.correct_button.isHidden(), "the protocol has ended"


def test_a_recalibration_in_the_protocols_place_withdraws_discard_and_gives_it_back(rig):
    """Code review of N7.F12a1: while a re-calibration runs in the protocol's place
    (`Procedure.detour`), Discard is not offered, and a press is ignored rather than starting
    the interval under the calibration; the abandoned interval gets it back."""
    experimenter, participant = rig.experimenter, rig.participant
    protocol = _long(rig)
    protocol.start()
    experimenter.proceed_requested.emit()
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    _answer(participant, _observer(protocol._trial))
    held = protocol._discardable
    assert held is not None and experimenter._awaiting["discard"]
    protocol.suspend_offers()
    assert not experimenter._awaiting["discard"]
    experimenter.discard_requested.emit()
    assert "discard_ignored" in _events(rig.session)
    assert _rows(rig.session, "discards") == []
    protocol.restore_offers()
    assert protocol._discardable == held and experimenter._awaiting["discard"]
    # The correction comes back with it (code review of N7.F18y).
    assert protocol._correctable is not None and experimenter._awaiting["substitution"]
    protocol.cancel()


def test_a_correction_is_offered_from_the_applied_press_until_the_next_cue(rig):
    """S, 22 Oct 2026: one control, Correct last application…, for the filament applied
    instead and for discard and repeat: offered once there is an application to correct,
    listing the set's other filaments, Discard greyed until the rating is in."""
    experimenter, participant = rig.experimenter, rig.participant
    protocol = _long(rig)
    assert experimenter.correct_button.isHidden()
    protocol.start()
    experimenter.proceed_requested.emit()  # the go: the first application's cue
    _spin(lambda: protocol._trial is not None and protocol._trial.awaits_proceed)
    assert experimenter.correct_button.isHidden(), "not before it is applied"
    experimenter.proceed_requested.emit()  # applied
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    correct = experimenter.correct_button
    assert not correct.isHidden() and correct.isEnabled()
    dialog = experimenter.correction_dialog()
    asked = protocol._trial.application.filament_label_g
    assert list(dialog.filaments) == [f.label_g for f in protocol.filaments
                                      if f.label_g != asked], "the set's others, lightest first"
    assert not dialog.discard.isEnabled(), "not until it is rated"
    dialog.deleteLater()
    _answer(participant, _observer(protocol._trial))
    dialog = experimenter.correction_dialog()
    assert dialog.discard.isEnabled() and dialog.filaments, "in the rest: both"
    dialog.deleteLater()
    _spin(lambda: protocol._trial is not None and not protocol._trial.delivered_elapsed_s)
    assert not experimenter._awaiting["discard"] and not experimenter._awaiting["substitution"]
    protocol.cancel()
    assert experimenter.correct_button.isHidden(), "the protocol has ended"


def test_the_dialog_records_what_is_chosen_only_on_confirming(rig):
    window = rig.experimenter
    filaments, discards = _emitted_args(window.substitution_entered), []
    window.discard_requested.connect(lambda: discards.append(True))
    window.set_filaments(["8", "15"])
    window.set_actions_enabled(substitution=True, discard=True)
    dialog = window.open_correction_dialog()
    dialog.filaments["15"].click()
    assert not filaments, "nothing until confirmed"
    dialog.confirm.click()
    assert filaments == [("15",)]
    dialog = window.open_correction_dialog()
    dialog.discard.click()
    dialog.confirm.click()
    assert discards == [True]
    dialog = window.open_correction_dialog()
    dialog.filaments["8"].click()
    window.set_actions_enabled(substitution=False, discard=False)  # the next cue meanwhile
    dialog.confirm.click()
    assert filaments == [("15",)], "too late: nothing recorded"
    assert window.substitution_message.text() == window.text["warnings"]["correction_too_late"]


def _emitted_args(signal) -> list:
    seen = []
    signal.connect(lambda *args: seen.append(args))
    return seen


def test_a_correction_after_the_rating_is_a_row_of_its_own_and_replans(rig):
    """The rated row stays as written; the correction points at it, as a discard does, and the
    search steps from the filament applied (S, 22 Oct 2026)."""
    session, experimenter = rig.session, rig.experimenter
    protocol = _long(rig)
    done = _start(protocol)
    _spin(lambda: rig.participant.stack.currentWidget() is rig.participant.vas)
    first = protocol._trial
    _answer(rig.participant, 0)  # below the target: the search would step up from 26 g
    assert protocol._correctable is first and experimenter._awaiting["substitution"]
    stepped_up = protocol._expected.filament_label_g
    experimenter.substitution_entered.emit("15")
    (row,) = _rows(session, "pinprick")
    assert row["applied_filament_label_g"] == "26", "the rated row as written"
    (correction,) = _rows(session, "corrections")
    assert correction["trial_timestamp_iso"] == row["timestamp_iso"]
    assert correction["applied_filament_label_g"] == "15"
    assert correction["substituted"] == "true"
    assert "substitution_corrected" in _events(session)
    # Below the target at 15 g: the next step is up from 15 g, which is 26 g, not past it.
    assert protocol._expected.filament_label_g == "26" != stepped_up
    assert protocol.state.outcomes[-1].applied_index == ladder_index(protocol.filaments, "15")
    assert protocol.state.delivered == 1, "corrected, not delivered again"
    protocol.cancel()
    assert not done


def test_a_correction_that_ends_the_run_ends_the_rest_with_it(rig):
    """Code review of N7.F18y: corrected to the lightest filament, a rating at or above the
    target puts the run out of range below, so nothing follows: the run ends there, as after
    a last application, rather than the rest counting down to nothing."""
    protocol = _long(rig)
    done = _start(protocol)
    _spin(lambda: rig.participant.stack.currentWidget() is rig.participant.vas)
    _answer(rig.participant, 1)  # 75 %: at or above the target
    assert protocol._expected is not None
    rig.experimenter.substitution_entered.emit(protocol.filaments[0].label_g)
    _spin(lambda: done)
    assert done[0].out_of_range and done[0].out_of_range_direction == "below"


def test_a_substitution_corrected_back_is_said_as_the_one_asked_for(rig):
    window = rig.experimenter
    protocol = _long(rig)
    _start(protocol)
    _spin(lambda: rig.participant.stack.currentWidget() is rig.participant.vas)
    asked = protocol._trial.application.filament_label_g
    window.substitution_entered.emit("15")
    window.substitution_entered.emit(asked)
    assert window.substitution_message.text() == window.text["warnings"][
        "substitution_asked"].format(filament=asked)
    assert protocol._trial.applied_label_g == asked
    protocol.cancel()


def test_the_stop_withdraws_the_correction_offer(rig):
    experimenter, participant = rig.experimenter, rig.participant
    protocol = _long(rig)
    _start(protocol)
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    assert experimenter._awaiting["substitution"]
    participant.emergency_stop.emit()
    assert not experimenter._awaiting["substitution"]
    experimenter.resume_requested.emit()
    protocol.cancel()


def test_a_discard_with_nothing_to_discard_is_ignored_and_logged(rig):
    protocol = _long(rig)
    protocol.start()
    rig.experimenter.discard_requested.emit()
    assert "discard_ignored" in _events(rig.session)
    assert _rows(rig.session, "discards") == []
    protocol.cancel()


def test_a_substitution_is_fitted_as_applied(rig):
    session, experimenter = rig.session, rig.experimenter
    protocol = _long(rig)
    done = _start(protocol)

    def substitute_first(answered, trial):
        if answered == 0:
            experimenter.substitution_entered.emit("15")

    _drive(protocol, done, before_answer=substitute_first)
    first = _rows(session, "pinprick")[0]
    assert first["filament_label_g"] == "26" and first["applied_filament_label_g"] == "15"
    assert first["substituted"] == "true" and first["force_applied_mn"] == "147.0"
    # The search steps from the filament applied: 15 g was below, so 26 g comes next.
    assert _rows(session, "pinprick")[1]["filament_label_g"] == "26"
    assert "substitution_entered" in _events(session)


def test_a_label_outside_the_set_cannot_reach_a_trial(rig):
    """The choice lists the set and nothing else; a label from anywhere else is a defect."""
    protocol = _long(rig)
    _start(protocol)
    _spin(lambda: rig.participant.stack.currentWidget() is rig.participant.vas)
    with pytest.raises(AssertionError, match="999"):
        protocol._trial._on_substitution("999")
    protocol.cancel()


def test_what_became_of_a_substitution_is_said_beside_it(rig):
    """S, 21 Oct 2026: "Filament correction should have a message when it is received and
    recorded"; and beside the choice, not on the warning line."""
    window = rig.experimenter
    warnings = window.text["warnings"]
    protocol = _long(rig)
    done = _start(protocol)
    _spin(lambda: rig.participant.stack.currentWidget() is rig.participant.vas)
    window.substitution_entered.emit("15")
    assert window.substitution_message.text() == warnings["substitution_recorded"].format(
        filament="15")
    window.substitution_entered.emit("300")
    assert window.substitution_message.text() == warnings["substitution_not_lower"].format(
        filament="300"), "recorded, but not lower than asked for"
    assert window._warning_text == ""
    protocol.cancel()
    assert not done


def test_a_rerun_takes_down_the_warning_about_the_run_it_discards(app, loaded, tmp_path):
    """Code review of N7.F11b16: the first run's application-cap warning stayed up under the
    re-run. Another stage's warning is left alone by a first run."""
    study1 = {**loaded.study1,
              "pinprick": {**loaded.study1["pinprick"], "max_applications": 2},
              "fit_preview": {**loaded.study1["fit_preview"], "enabled": True}}
    rig = _make_rig(loaded, tmp_path, study1=study1)
    window = rig.experimenter
    window.set_warning("from the stage before")
    protocol = _long(rig)
    _start(protocol)
    assert window._warning_text == "from the stage before"
    for _ in range(2):
        _spin(lambda: rig.participant.stack.currentWidget() is rig.participant.vas)
        _answer(rig.participant, 0)
    _spin(lambda: protocol._awaiting_fit is not None)
    capped = window.text["warnings"]["application_cap"].format(value=2)
    assert capped in window._warning_text
    window.fit_rerun_requested.emit("again")
    assert capped not in window._warning_text
    protocol.cancel()
    rig.session.close()


def test_a_ceiling_rating_caps_the_site(rig):
    session = rig.session
    cap = IntolerableCap(99)
    protocol = _long(rig, cap=cap)
    done = _start(protocol)

    def respond(trial):
        # Intolerable at the first application, then an ordinary observer.
        return PRESSES_TO_THE_CEILING if trial.trial_index == 1 else _observer(trial)

    _drive(protocol, done, respond=respond)
    rows = _rows(session, "pinprick")
    assert rows[0]["intolerable"] == "true"
    site = int(rows[0]["site_index"])
    assert cap.cap_for("secondary", site) == 15, "the 26 g is index 15 of the held ladder"
    assert "intolerable_site_cap" in _events(session)
    # Logged, never shown: at a ceiling of 100, naming the capped site names the rating.
    warnings = rig.experimenter.text["warnings"]
    assert "intolerable_cap" not in warnings and "intolerable_global_cap" not in warnings
    held = session.config.filaments["filaments"]
    forces = {f["label_g"]: f["force_nominal_mn"] for f in held}
    for row in rows[1:]:
        if int(row["site_index"]) == site:
            assert forces[row["applied_filament_label_g"]] < forces["26"]


def test_the_fit_preview_rerun_keeps_the_superseded_run(app, loaded, tmp_path):
    study1 = {**loaded.study1, "fit_preview": {**loaded.study1["fit_preview"], "enabled": True}}
    rig = _make_rig(loaded, tmp_path, study1=study1)
    session, experimenter = rig.session, rig.experimenter
    protocol = _long(rig)
    fits = []
    protocol.fit_ready.connect(fits.append)
    done = _start(protocol)

    _spin(lambda: fits or (rig.participant.stack.currentWidget() is rig.participant.vas))
    while not fits:
        _answer(rig.participant, _observer(protocol._trial))
        _spin(lambda: fits or (rig.participant.stack.currentWidget() is rig.participant.vas))
    assert len(fits[0].points) == 9
    experimenter.fit_rerun_requested.emit("filament slipped")
    experimenter.proceed_requested.emit()
    while len(fits) < 2:
        _spin(lambda: len(fits) > 1 or (
            rig.participant.stack.currentWidget() is rig.participant.vas))
        if len(fits) < 2:
            _answer(rig.participant, _observer(protocol._trial))
    experimenter.fit_accepted.emit()
    assert done and done[0].run_index == 2

    first, second = _rows(session, "calibration_pinprick")
    assert (first["run_index"], first["superseded"], first["rerun_reason"]) == (
        "1", "true", "filament slipped")
    assert (second["run_index"], second["superseded"]) == ("2", "false")
    assert {r["run_index"] for r in _rows(session, "pinprick")} == {"1", "2"}
    assert session.fit_preview_reruns == 1
    session.close()


def test_the_f40_preview_enables_the_choice_and_closes_on_it(app, loaded, tmp_path):
    """SPEC.md 11.1: Accept and Re-run are live while the run waits, and dead after."""
    study1 = {**loaded.study1, "fit_preview": {**loaded.study1["fit_preview"], "enabled": True}}
    rig = _make_rig(loaded, tmp_path, study1=study1)
    experimenter = rig.experimenter
    protocol = _long(rig)
    fits = []
    protocol.fit_ready.connect(fits.append)
    protocol.fit_ready.connect(experimenter.show_fit_preview)
    done = _start(protocol)
    while not fits:
        _spin(lambda: fits or (rig.participant.stack.currentWidget() is rig.participant.vas))
        if not fits:
            assert experimenter.fit_accept_button.isHidden()
            _answer(rig.participant, _observer(protocol._trial))
    assert not experimenter.fit_accept_button.isHidden()
    assert experimenter.fit_accept_button.isEnabled()
    assert experimenter.fit_preview.isVisible()
    experimenter.fit_accept_button.click()
    assert done
    assert not experimenter.fit_preview.isVisible()
    assert experimenter.fit_preview.plot.points == ()
    assert experimenter.fit_accept_button.isHidden()
    assert experimenter.fit_rerun_button.isHidden()
    rig.session.close()


def test_the_fit_preview_rerun_is_bounded(app, loaded, tmp_path):
    study1 = {**loaded.study1, "fit_preview": {**loaded.study1["fit_preview"], "enabled": True,
                                                "max_reruns": 0}}
    rig = _make_rig(loaded, tmp_path, study1=study1)
    protocol = _long(rig)
    fits = []
    protocol.fit_ready.connect(fits.append)
    protocol.fit_ready.connect(rig.experimenter.show_fit_preview)
    done = _start(protocol)
    while not fits:
        _spin(lambda: fits or (rig.participant.stack.currentWidget() is rig.participant.vas))
        if not fits:
            _answer(rig.participant, _observer(protocol._trial))
    # At the limit Re-run is not offered -- not even by the preview opening over it -- and the
    # instruction says so before any press (reviews of N7.F16, N7.F17e), not after a refused
    # one.
    experimenter = rig.experimenter
    for rerun in (experimenter.fit_rerun_button, experimenter.fit_preview.rerun_button):
        assert rerun.isHidden() or not rerun.isEnabled()
    assert experimenter._instruction_text == cfg.instruction(
        rig.session.config, f"f40_fit_review{NO_RERUNS_LEFT}")
    experimenter.fit_accepted.emit()
    assert done and done[0].run_index == 1
    (row,) = _rows(rig.session, "calibration_pinprick")
    assert row["superseded"] == "false"
    rig.session.close()


# -- the short protocol and the brush -------------------------------------------------------


def test_the_short_protocol_takes_the_median_at_a_fixed_filament(rig):
    session = rig.session
    protocol = ShortProtocol(rig, "primary", "60", _cap(rig))
    done = _start(protocol)
    presses = iter([1, 0, 1, 1, 0])
    _drive(protocol, done, respond=lambda trial: next(presses))
    result = done[0]
    rows = _rows(session, "pinprick")
    n_trials = session.config.study1["pinprick"]["short_protocol_n_trials"]
    assert len(rows) == n_trials
    assert {r["filament_label_g"] for r in rows} == {"60"}
    assert all(r["protocol"] == "short" and r["purpose"] == "measure" for r in rows)
    assert [int(r["site_index"]) for r in rows] == list(range(1, n_trials + 1))
    assert result.median_rating_percent == 75.0
    assert result.ratings_percent == (75.0, 25.0, 75.0, 75.0, 25.0)


def test_the_short_protocol_intervals_are_jittered_within_range(rig):
    session = rig.session
    protocol = ShortProtocol(rig, "primary", "26", _cap(rig))
    done = _start(protocol)
    _drive(protocol, done)
    pinprick = session.config.study1["pinprick"]
    intervals = [
        float(r["detail"].split()[0]) for r in _rows(session, "log") if r["event"] == "interval"
    ]
    # One rest between each two, none after the last (S, 22 Oct 2026).
    assert len(intervals) == pinprick["short_protocol_n_trials"] - 1
    assert all(pinprick["isi_min_s"] <= s <= pinprick["isi_max_s"] for s in intervals)
    assert len(set(intervals)) > 1


def test_the_diagram_draws_only_the_sites_a_short_series_uses(rig):
    """S, 22 Oct 2026: "more sites are shown on the diagram than are actually used". Five
    applications use five of the figure's sites; the end of the series gives the zone back."""
    zone = rig.experimenter.zone
    protocol = ShortProtocol(rig, "primary", "26", _cap(rig))
    done = _start(protocol)
    n_trials = rig.session.config.study1["pinprick"]["short_protocol_n_trials"]
    used = []
    _drive(protocol, done,
           before_answer=lambda answered, trial: zone.region is not None
           and used.append(zone.drawn_sites()))
    assert n_trials < zone.sites("primary"), "the figure has more"
    assert used and set(used) == {n_trials}, used
    assert "primary" not in zone.in_use, "given back at the series' end"


def test_the_brush_writes_the_brush_table(rig):
    session = rig.session
    protocol = BrushProtocol(rig, "secondary")
    done = _start(protocol)
    _drive(protocol, done, respond=lambda trial: 0)
    rows = _rows(session, "brush")
    assert len(rows) == session.config.study1["brush"]["n_trials"]
    assert all(r["region"] == "secondary" and r["rating_cue_iso"] for r in rows)
    assert _rows(session, "pinprick") == []
    assert done[0].stimulus == "brush" and done[0].median_rating_percent == 25.0


def test_a_brush_discard_points_at_the_brush_table(rig):
    session = rig.session
    protocol = BrushProtocol(rig, "primary")
    done = _start(protocol)
    _spin(lambda: rig.participant.stack.currentWidget() is rig.participant.vas)
    _answer(rig.participant, 0)
    rig.experimenter.discard_requested.emit()
    _drive(protocol, done, respond=lambda trial: 0)
    rows = _rows(session, "brush")
    (discard,) = _rows(session, "discards")
    assert discard["table"] == "brush"
    assert discard["trial_timestamp_iso"] == rows[0]["timestamp_iso"]
    n_trials = session.config.study1["brush"]["n_trials"]
    assert len(rows) == n_trials + 1 and len(done[0].ratings_percent) == n_trials


def test_the_experimenter_never_sees_a_rating(rig):
    protocol = ShortProtocol(rig, "primary", "26", _cap(rig))
    done = _start(protocol)
    seen = []

    # The status line is where the response is acknowledged, so it is where a rating would
    # leak. (The instruction names the filament's force, which is not a rating.)
    def watch(answered, trial):
        seen.append(rig.experimenter.status.text())

    _drive(protocol, done, before_answer=watch)
    seen.append(rig.experimenter.status.text())
    assert not any("75" in text or "25" in text for text in seen)
    assert math.isfinite(done[0].median_rating_percent)
