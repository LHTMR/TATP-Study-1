"""One pinprick trial end to end. SPEC.md 8, 10.2, 10.5, 14.

This is the Milestone 1 vertical slice: config, session, clock, data files, both windows, the
responder and the VAS all in one path. It runs on a real Qt event loop with an accelerated clock
(SPEC.md 17.3) and checks the row that reaches disk, not the intention in the code.
"""

from __future__ import annotations

import csv
import time

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.clock import Clock
from tatp.pinprick import Application, PinprickTrial
from tatp.responder import Responder
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"

# The clock is accelerated so the 9 s rating delay costs the suite ~0.1 s of real time. Every
# interval still comes from config; only the clock's speed differs from a real session.
CLOCK_SPEED = 100.0
SPIN_TIMEOUT_S = 10.0
# Wall seconds a data write takes in the slow-write test: a busy disk, or a virus scanner.
SLOW_WRITE_S = 0.02
# One millisecond of real time, which a Qt timer rounds to, in session seconds.
ROUNDED_MS_S = 0.001 * CLOCK_SPEED
# Session seconds a test waits to see that nothing happens without the press.
WAITED_S = 20.0

# The 26 g filament is size 5.46, 255 mN -- the one Bilaga 1 3.6.1 calls "260 mN" (SPEC.md 8.1).
APPLICATION = Application(
    protocol="short",
    region="primary",
    trial_index=1,
    purpose="measure",
    filament_label_g="26",
    site_index=3,
)

# 75 % after the first right press, then 0.5 % a press: enough to pin the marker at the top.
PRESSES_TO_THE_CEILING = 60


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def running(app, loaded, tmp_path):
    """A started session with both windows, ready for a trial."""
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"],
                                            "folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED), rng_seed=7
    )
    session.start()
    session.set_phase("post_sensitisation")
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    participant.resize(1280, 800)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    yield session, participant, experimenter
    session.close()


def _spin(condition) -> None:
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the trial did not reach the expected state")
        QApplication.processEvents()
        time.sleep(0.001)


def _press(widget, name) -> None:
    key = QT_KEYS[name]
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def _rows(session, table):
    with session.files.path(table).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _deliver(experimenter, trial):
    """The experimenter applies the stimulus once asked, and says so with Next step."""
    _spin(lambda: trial.awaits_proceed)
    experimenter.proceed_requested.emit()


def _run_trial(running, application=APPLICATION, presses=2):
    """Cue, wait for the rating to be asked for, answer it, and return the trial."""
    session, participant, experimenter = running
    trial = PinprickTrial(session, participant, experimenter, application)
    done = []
    trial.finished.connect(done.append)

    trial.start()
    assert participant.stack.currentWidget() is participant.cue, "the cue precedes the stimulus"

    _deliver(experimenter, trial)
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    for _ in range(presses):
        _press(participant.vas, "pagedown")
    _press(participant.vas, "f5")
    assert len(done) == 1, "the trial ends when the participant confirms"
    return trial, done[0]


# -- the slice ---------------------------------------------------------------------------


def test_one_trial_writes_one_valid_row(running):
    session, _, _ = running
    trial, response = _run_trial(running)
    rows = _rows(session, "pinprick")
    assert len(rows) == 1
    row = rows[0]

    assert row["protocol"] == "short"
    assert row["region"] == "primary"
    assert row["trial_index"] == "1"
    assert row["purpose"] == "measure"
    assert row["filament_label_g"] == "26"
    assert row["applied_filament_label_g"] == "26"
    assert row["site_index"] == "3"
    assert row["phase"] == "post_sensitisation"
    assert row["substituted"] == "false"
    assert row["intolerable"] == "false"


def test_the_reaction_time_and_first_press_side_are_recorded(running):
    """SPEC.md 10.2: response percent, reaction time, first-press side, direction changes."""
    session, _, _ = running
    trial, response = _run_trial(running)
    row = _rows(session, "pinprick")[0]
    assert row["first_press_side"] == "right"
    assert float(row["rating_percent"]) == response.rating_percent
    assert float(row["rt_s"]) == pytest.approx(response.rt_s)
    assert float(row["rt_s"]) > 0.0
    assert row["direction_changes"] == "0"


def test_the_cue_and_rating_cue_times_are_recorded(running):
    """SPEC.md 10.5: timestamp every cue onset."""
    session, _, _ = running
    trial, _ = _run_trial(running)
    row = _rows(session, "pinprick")[0]
    assert row["cue_onset_iso"] == trial.cue_onset_iso
    assert row["timestamp_iso"] == trial.cue_onset_iso
    assert row["rating_cue_iso"] == trial.rating_cue_iso
    assert row["rating_cue_iso"] > row["cue_onset_iso"]


def test_the_rating_waits_for_the_experimenter_to_say_the_filament_is_applied(running):
    """S, 20 Oct 2026 (LOG N7.F16f, N7.F17a): the scale is shown only at the experimenter's
    press, at once, and the row records when the press came."""
    session, participant, experimenter = running
    experimenter.set_instruction("ready", "prepare")
    trial = PinprickTrial(session, participant, experimenter, APPLICATION)
    trial.start()
    # The cue's 1 s lead is too short to read: what was up stays (S, 22 Oct 2026); "Now:
    # apply" only with Next step offered.
    prepare = experimenter.instruction.text()
    assert prepare == "ready"
    _spin(lambda: trial.awaits_proceed)
    assert experimenter.instruction.text() != prepare
    assert experimenter.zone.region == APPLICATION.region, "the target stays with it"
    # A stop from here counts the application as delivered, pressed or not (spec review).
    assert trial.stimulus_delivered and trial.stimulus_delivered_iso == ""
    waited_s = session.clock.elapsed_s() + WAITED_S
    _spin(lambda: session.clock.elapsed_s() > waited_s)
    assert participant.stack.currentWidget() is not participant.vas, "no scale before the press"
    experimenter.proceed_requested.emit()
    assert trial.stimulus_delivered and not trial.awaits_proceed
    assert participant.stack.currentWidget() is participant.vas, "the scale, at once"
    assert experimenter.status.text() == experimenter.text["instructions"]["await_participant"]
    _press(participant.vas, "pagedown")
    _press(participant.vas, "f5")
    row = _rows(session, "pinprick")[0]
    assert row["cue_onset_iso"] < row["stimulus_delivered_iso"] <= row["rating_cue_iso"]


def test_a_slow_write_before_the_stimulus_due_does_not_delay_the_prompt(
    running, monkeypatch
):
    """docs/LOG.md N7.U11: the stimulus falls due the cue's lead after the cue onset it is
    timed from, so writing the cue's log row -- 20 ms here, 2 s of session time at this speed
    -- is not added to the lead, and the lead is never shortened either."""
    session, participant, experimenter = running
    real_log = session.log
    cued_at = []

    def slow_log(event, *args, **kwargs):
        if event == "warning_cue":
            cued_at.append(session.clock.elapsed_s())
            time.sleep(SLOW_WRITE_S)
        real_log(event, *args, **kwargs)

    monkeypatch.setattr(session, "log", slow_log)
    trial = PinprickTrial(session, participant, experimenter, APPLICATION)
    trial.start()
    _spin(lambda: trial.awaits_proceed)
    lead_s = session.clock.elapsed_s() - cued_at[0]
    assert lead_s >= trial.warning_lead_s - ROUNDED_MS_S, "the lead was shortened"
    assert lead_s < trial.warning_lead_s + SLOW_WRITE_S * CLOCK_SPEED, (
        "the write after the cue was added to the lead"
    )
    trial.cancel()


def test_the_label_force_is_fitted_while_the_set_is_unweighed(running):
    """SPEC.md 8.1: the fallback is marked, not silent. An empty measured force is the mark."""
    session, _, _ = running
    _run_trial(running)
    row = _rows(session, "pinprick")[0]
    assert row["force_nominal_mn"] == "255.0", "the chart's force for the 26 g, not a rounding"
    assert row["force_measured_mn"] == "", "the set is unweighed (open item 1)"
    assert row["force_applied_mn"] == "255.0", "so the estimator fits the nominal force"


def test_a_substitution_records_the_filament_actually_applied(running):
    """SPEC.md 8.2 safety rule: fit the applied value, not the intended one."""
    session, _, _ = running
    substituted = Application(
        protocol="long",
        region="secondary",
        trial_index=2,
        purpose="search",
        filament_label_g="26",
        site_index=4,
        applied_filament_label_g="15",
    )
    _run_trial(running, substituted)
    row = _rows(session, "pinprick")[0]
    assert row["filament_label_g"] == "26"
    assert row["applied_filament_label_g"] == "15"
    assert row["substituted"] == "true"
    # Every force column describes the filament that actually touched the skin: the 15 g.
    assert row["force_nominal_mn"] == "147.0"
    assert row["force_applied_mn"] == "147.0"


def test_a_ceiling_rating_flags_the_application_as_intolerable(running):
    """SPEC.md 8.2: the top of the pain scale is the proxy; there is no separate control."""
    session, _, _ = running
    _, response = _run_trial(running, presses=PRESSES_TO_THE_CEILING)
    assert response.rating_percent == session.config.study1["pinprick"]["intolerable_vas_pct"]
    row = _rows(session, "pinprick")[0]
    assert row["intolerable"] == "true"
    flagged = [r for r in _rows(session, "log") if r["event"] == "intolerable_rating"]
    assert len(flagged) == 1, "the cap must be visible in the event stream, not only derivable"
    assert flagged[0]["severity"] == "warning"
    assert "26 g" in flagged[0]["detail"]


def test_the_sequence_reaches_the_log(running):
    session, _, _ = running
    _run_trial(running)
    events = [row["event"] for row in _rows(session, "log")]
    assert events.index("warning_cue") < events.index("stimulus_due")
    assert events.index("stimulus_due") < events.index("stimulus_delivered")
    assert events.index("stimulus_delivered") < events.index("rating_cued")
    assert events.index("rating_cued") < events.index("rating_confirmed")


def test_the_experimenter_is_told_what_to_apply_and_never_the_rating(running):
    """Named by its gram label (SPEC.md 8.1), under Prepare and then Now, where it goes on the
    diagram beside it rather than in words (S, 21 Oct 2026)."""
    session, participant, experimenter = running
    text = session.config.experimenter_text
    trial = PinprickTrial(session, participant, experimenter, APPLICATION)
    # A lead long enough to read: "Get ready" with the filament, under Prepare. (The
    # configured 1 s is not, and leaves what was up: `test_the_rating_waits_for_...`.)
    trial._prepare_shown = True
    trial.start()
    headings = text["headings"]
    assert "26 g" in experimenter.instruction.text()
    assert experimenter.alert.text() == headings["prepare"]
    assert (experimenter.zone.region, experimenter.zone.site) == (
        APPLICATION.region, APPLICATION.site_index)
    _spin(lambda: trial.awaits_proceed)
    assert experimenter.instruction.text() == cfg.instruction(
        session.config, "apply_filament", filament="26")
    assert experimenter.alert.text() == headings["now"]
    assert experimenter.zone.site == APPLICATION.site_index
    trial.cancel()
    _run_trial(running)
    assert experimenter.status.text() == text["instructions"]["response_received"]
    assert "40" not in experimenter.status.text(), "a rating never reaches the lab screen"


def test_an_unknown_filament_is_refused_rather_than_guessed(running):
    session, participant, experimenter = running
    unknown = Application(
        protocol="short",
        region="primary",
        trial_index=1,
        purpose="measure",
        filament_label_g="999",
        site_index=1,
    )
    trial = PinprickTrial(session, participant, experimenter, unknown)
    with pytest.raises(KeyError, match="999"):
        trial.start()


def test_a_cancelled_trial_writes_no_row_and_reports_nothing(running):
    """SPEC.md 13. An interruption cancels the trial: no rating was given, none is invented."""
    session, participant, experimenter = running
    trial = PinprickTrial(session, participant, experimenter, APPLICATION)
    done = []
    trial.finished.connect(done.append)
    trial.start()
    trial.cancel()
    _spin(lambda: session.clock.elapsed_s() > WAITED_S)

    assert done == []
    assert not session.files.path("pinprick").exists()
    assert "trial_cancelled" in [row["event"] for row in _rows(session, "log")]
    # Nothing it connected is left behind to answer a later trial's confirm.
    _press(participant.vas, "f5")
    assert done == []
