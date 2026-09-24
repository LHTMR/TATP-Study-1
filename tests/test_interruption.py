"""The emergency stop, the pause and the resume. SPEC.md 10.9, 11, 13.

One owner for every interruption, so these tests are the ones that say what a stop does in every
phase: the garment to zero first, the event logged with its origin, the screen up, and the
running procedure told once.
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
from tatp.interruption import EMERGENCY_STOP, PAUSE, Interruptions
from tatp.responder import Responder
from tatp.session import Session, SessionError
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
CLOCK_SPEED = 100.0
SPIN_TIMEOUT_S = 10.0
CHANNEL = 3
PRESSURE_KPA = 42.0


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def rigged(app, loaded, tmp_path):
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED), rng_seed=7
    )
    session.start()
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    interruptions = Interruptions(session, participant, experimenter)
    seen = []
    interruptions.interrupted.connect(seen.append)
    interruptions.resumed.connect(lambda: seen.append("resumed"))
    yield session, participant, experimenter, interruptions, seen
    session.close()


def _press(widget, name) -> None:
    key = QT_KEYS[name]
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def _spin(condition) -> None:
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the resume did not complete")
        QApplication.processEvents()
        time.sleep(0.001)


def _events(session, name):
    with session.files.path("log").open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row["event"] == name]


def _deliver(session) -> None:
    session.garment.set_channel(CHANNEL, True)
    session.garment.set_pressure(CHANNEL, PRESSURE_KPA)


# -- the stop -------------------------------------------------------------------------------


def test_the_stop_zeroes_the_garment_logs_it_and_shows_the_stop_screen(rigged):
    session, participant, _, interruptions, seen = rigged
    _deliver(session)
    _press(participant, "f5")

    assert session.garment.pressure_kpa[CHANNEL] == 0.0
    assert session.garment.status()["channels_on"] == []
    stops = _events(session, "emergency_stop")
    assert len(stops) == 1
    assert stops[0]["origin"] == "participant"
    assert stops[0]["severity"] == "error"
    screens = session.config.participant_text["screens"]
    assert participant.message.text == screens["emergency_stop"]
    assert seen == [EMERGENCY_STOP]
    assert interruptions.active == EMERGENCY_STOP


def test_the_stop_works_on_the_vas(rigged):
    session, participant, _, _, seen = rigged
    participant.show_vas("pain")
    _press(participant.vas, "f5")
    assert seen == [EMERGENCY_STOP]


def test_a_second_press_is_logged_and_zeroes_again_but_tells_nobody_twice(rigged):
    session, participant, _, interruptions, seen = rigged
    _press(participant, "f5")
    _press(participant, "f5")
    assert len(_events(session, "emergency_stop")) == 2, "every press is logged (SPEC.md 13)"
    assert seen == [EMERGENCY_STOP]
    assert interruptions.emergency_stops == 2


def test_a_stop_with_the_garment_disconnected_still_works(rigged):
    """The one path that must never fail must not fail for want of a device."""
    session, participant, _, _, seen = rigged
    session.garment.disconnect()
    _press(participant, "f5")
    assert seen == [EMERGENCY_STOP]


# -- the pause ------------------------------------------------------------------------------


def test_the_pause_zeroes_the_garment_and_shows_the_paused_screen(rigged):
    session, participant, experimenter, interruptions, seen = rigged
    _deliver(session)
    experimenter.pause_requested.emit()

    assert session.garment.pressure_kpa[CHANNEL] == 0.0
    assert participant.message.text == session.config.participant_text["screens"]["paused"]
    paused = _events(session, "paused")
    assert paused[0]["origin"] == "experimenter"
    assert seen == [PAUSE]


def test_a_stop_during_a_pause_takes_over_without_a_second_interruption(rigged):
    session, participant, experimenter, interruptions, seen = rigged
    experimenter.pause_requested.emit()
    _press(participant, "f5")
    assert interruptions.active == EMERGENCY_STOP
    assert seen == [PAUSE]


def test_a_pause_while_stopped_changes_nothing(rigged):
    session, participant, experimenter, interruptions, seen = rigged
    _press(participant, "f5")
    experimenter.pause_requested.emit()
    assert interruptions.active == EMERGENCY_STOP
    assert seen == [EMERGENCY_STOP]


# -- the resume -----------------------------------------------------------------------------


def test_a_resume_with_nothing_to_restore_hands_straight_back(rigged):
    session, participant, experimenter, interruptions, seen = rigged
    _press(participant, "f5")
    experimenter.resume_requested.emit()
    assert seen == [EMERGENCY_STOP, "resumed"]
    assert interruptions.active is None
    assert _events(session, "resumed")[0]["origin"] == "experimenter"


def test_a_resume_restores_the_garment_after_the_warning_cue(rigged):
    """SPEC.md 10.9: the resume is shown, and the garment start is preceded by the cue."""
    session, participant, _, interruptions, seen = rigged
    _deliver(session)
    _press(participant, "f5")
    interruptions.resume()

    assert participant.stack.currentWidget() is participant.cue
    assert session.garment.pressure_kpa[CHANNEL] == 0.0, "nothing before the cue has run"
    _spin(lambda: "resumed" in seen)
    assert session.garment.pressure_kpa[CHANNEL] == PRESSURE_KPA
    assert session.garment.status()["channels_on"] == [CHANNEL]
    assert _events(session, "garment_restored")


def test_a_resume_restarts_the_pattern_that_was_playing(rigged):
    session, participant, _, interruptions, seen = rigged
    session.garment.play_pattern(session.patterns["sweep_03cms"])
    _press(participant, "f5")
    assert session.garment.status()["pattern_name"] is None
    interruptions.resume()
    _spin(lambda: "resumed" in seen)
    assert session.garment.status()["pattern_name"] == "sweep_03cms"


def test_a_stop_during_the_resume_cue_cancels_the_restore(rigged):
    session, participant, _, interruptions, seen = rigged
    _deliver(session)
    _press(participant, "f5")
    interruptions.resume()
    _press(participant, "f5")
    deadline = time.monotonic() + (interruptions.warning_lead_s * 2) / CLOCK_SPEED + 0.2
    while time.monotonic() < deadline:
        QApplication.processEvents()
    assert "resumed" not in seen
    assert session.garment.pressure_kpa[CHANNEL] == 0.0
    assert interruptions.active == EMERGENCY_STOP


def test_a_garment_disconnected_during_the_stop_is_not_restored(rigged):
    """The resume still completes; commanding a disconnected garment would raise."""
    session, participant, _, interruptions, seen = rigged
    _deliver(session)
    _press(participant, "f5")
    session.garment.disconnect()
    interruptions.resume()
    _spin(lambda: "resumed" in seen)
    assert _events(session, "restore_skipped_disconnected")
    assert not _events(session, "garment_restored")


def test_a_resume_with_nothing_interrupted_is_a_defect(rigged):
    _, _, _, interruptions, _ = rigged
    with pytest.raises(SessionError, match="nothing is interrupted"):
        interruptions.resume()
