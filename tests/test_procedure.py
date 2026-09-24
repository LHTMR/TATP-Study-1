"""The procedure contract. tatp/procedure.py.

Every protocol is a `Procedure`, so what these tests pin is what an interruption does to any
sequence: the step in progress is abandoned, and the resume repeats it -- a fresh trial built
from the same plan, or a wait started over -- while only the innermost procedure acts.
"""

from __future__ import annotations

import csv
import time

import pytest
import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from tatp import config as cfg
from tatp.clock import Clock
from tatp.procedure import Procedure, Rig
from tatp.responder import Responder
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
CLOCK_SPEED = 100.0
SPIN_TIMEOUT_S = 10.0
WAIT_S = 1.0


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def rig(app, loaded, tmp_path):
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED), rng_seed=7
    )
    session.start()
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    made = Rig(session, participant, experimenter)
    yield made
    session.close()


def _spin(condition) -> None:
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the procedure did not reach the expected state")
        QApplication.processEvents()
        time.sleep(0.001)


def _events(session):
    with session.files.path("log").open(encoding="utf-8", newline="") as handle:
        return [row["event"] for row in csv.DictReader(handle)]


class FakeTrial(QObject):
    """A trial that finishes when told to, and records whether it was cancelled."""

    finished = Signal(object)

    def __init__(self, label: str):
        super().__init__()
        self.label = label
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def respond(self) -> None:
        self.finished.emit(self.label)


class TwoTrials(Procedure):
    """A wait, a trial, then another trial; finishes with the two results."""

    def __init__(self, rig):
        super().__init__(rig)
        self.made: list[FakeTrial] = []
        self.results: list[str] = []

    def begin(self) -> None:
        self.wait(WAIT_S, self._first)

    def _make(self, label: str) -> FakeTrial:
        trial = FakeTrial(label)
        self.made.append(trial)
        return trial

    def _first(self) -> None:
        self.run_trial(lambda: self._make("first"), self._second)

    def _second(self, result) -> None:
        self.results.append(result)
        self.run_trial(lambda: self._make("second"), self._done)

    def _done(self, result) -> None:
        self.results.append(result)
        self.finish(tuple(self.results))


class Parent(Procedure):
    """Runs a `TwoTrials` as a child."""

    def __init__(self, rig):
        super().__init__(rig)
        self.child: TwoTrials | None = None
        self.begun = 0

    def begin(self) -> None:
        self.begun += 1
        self.run_child(self._make_child, self.finish)

    def _make_child(self) -> TwoTrials:
        self.child = TwoTrials(self.rig)
        return self.child


def _collect(procedure):
    done = []
    procedure.finished.connect(done.append)
    return done


# -- the sequence -------------------------------------------------------------------------


def test_the_steps_run_in_order_and_finish_with_the_result(rig):
    procedure = TwoTrials(rig)
    done = _collect(procedure)
    procedure.start()
    _spin(lambda: procedure.made)
    procedure.made[0].respond()
    procedure.made[1].respond()
    assert done == [("first", "second")]
    assert not procedure.running


def test_a_procedure_cannot_be_started_twice(rig):
    procedure = TwoTrials(rig)
    procedure.start()
    with pytest.raises(RuntimeError, match="already running"):
        procedure.start()


def test_cancel_emits_nothing_and_cancels_the_trial(rig):
    procedure = TwoTrials(rig)
    done = _collect(procedure)
    procedure.start()
    _spin(lambda: procedure.made)
    procedure.cancel()
    assert procedure.made[0].cancelled
    procedure.made[0].respond()
    assert done == []
    assert not procedure.running


# -- interruptions ------------------------------------------------------------------------


def test_an_interrupted_trial_is_cancelled_and_rebuilt_on_resume(rig):
    procedure = TwoTrials(rig)
    done = _collect(procedure)
    procedure.start()
    _spin(lambda: procedure.made)
    abandoned = procedure.made[0]

    rig.interruptions.emergency_stop()
    assert abandoned.cancelled
    rig.interruptions.resume()

    assert len(procedure.made) == 2, "a fresh trial, not the half-used one"
    repeated = procedure.made[1]
    assert repeated.label == "first" and repeated.started
    abandoned.respond()
    assert procedure.results == [], "a cancelled trial cannot report late"
    repeated.respond()
    procedure.made[2].respond()
    assert done == [("first", "second")]
    events = _events(rig.session)
    assert events.index("step_abandoned") < events.index("step_repeated")


def test_an_interrupted_wait_starts_over(rig):
    procedure = TwoTrials(rig)
    procedure.start()
    rig.interruptions.pause()
    time.sleep(WAIT_S * 2 / CLOCK_SPEED)
    QApplication.processEvents()
    assert procedure.made == [], "the wait does not run on while interrupted"
    rig.interruptions.resume()
    _spin(lambda: procedure.made)


def test_only_the_innermost_procedure_handles_an_interruption(rig):
    parent = Parent(rig)
    done = _collect(parent)
    parent.start()
    _spin(lambda: parent.child.made)
    parent.child.made[0].respond()

    rig.interruptions.emergency_stop()
    rig.interruptions.resume()
    assert parent.begun == 1, "the parent did not restart its child"
    assert [t.label for t in parent.child.made] == ["first", "second", "second"]
    parent.child.made[-1].respond()
    assert done == [("first", "second")]


def test_a_finished_procedure_no_longer_answers_interruptions(rig):
    procedure = TwoTrials(rig)
    procedure.start()
    _spin(lambda: procedure.made)
    procedure.made[0].respond()
    procedure.made[1].respond()
    rig.interruptions.emergency_stop()
    rig.interruptions.resume()
    assert len(procedure.made) == 2


# -- the rig ------------------------------------------------------------------------------


def _key(widget, key, kind=None) -> None:
    """A key event delivered the way the operating system delivers it: through the app."""
    for event_type in ((kind,) if kind else (QEvent.KeyPress, QEvent.KeyRelease)):
        QApplication.sendEvent(widget, QKeyEvent(event_type, key, Qt.NoModifier))


def test_the_remote_reaches_the_participant_whichever_window_is_active(rig):
    """The experimenter clicks their own window constantly; the remote must not follow it."""
    rig.participant.show()
    elsewhere = QPushButton()
    elsewhere.show()
    confirmed = []
    rig.participant.message_confirmed.connect(lambda: confirmed.append(1))
    rig.participant.show_message("welcome")

    _key(elsewhere, QT_KEYS["period"])
    assert confirmed == [1], "the confirm reached the participant window"
    _key(elsewhere, QT_KEYS["f5"])
    assert rig.interruptions.active == "emergency_stop", "and so does the emergency stop"


def test_the_remote_drives_the_vas_from_another_window(rig):
    rig.participant.show()
    elsewhere = QPushButton()
    elsewhere.show()
    rig.participant.show_vas("pain")
    _key(elsewhere, QT_KEYS["pagedown"])
    assert rig.participant.vas.state.visible, "the first press showed the marker"


def test_typing_in_an_experimenter_field_is_not_taken_for_the_remote(rig):
    """The confirm key is a full stop, which the experimenter types in notes and distances."""
    rig.participant.show()
    field = QLineEdit()
    field.show()
    confirmed = []
    rig.participant.message_confirmed.connect(lambda: confirmed.append(1))
    rig.participant.show_message("welcome")
    _key(field, QT_KEYS["period"], QEvent.KeyPress)
    assert confirmed == []


def test_a_deleted_participant_window_takes_its_key_router_with_it(app, loaded, tmp_path):
    """docs/LOG.md N7.I3. The router is the window's child, so it cannot outlive it.

    A router that outlived its window was reached by every later key event in the process, and
    touched a deleted C++ object. That was the intermittent worker crash in the test suite.
    """
    import gc

    for attempt in range(3):
        hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / f"d{attempt}"),
                                                "cloud_sync_markers": []},
                    "audio": {**loaded.hardware["audio"], "backend": "recording"}}
        config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
        session = Session(config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED))
        session.start()
        participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
        experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
        made = Rig(session, participant, experimenter)
        router = made._remote_keys
        session.close()
        participant.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not shiboken6.isValid(router), "the router went with its window"
        del made, participant, experimenter, session
        gc.collect()
    elsewhere = QPushButton()
    elsewhere.show()
    _key(elsewhere, QT_KEYS["pagedown"])  # reaches no dead filter, and does not crash


def test_the_rig_plays_patterns(rig):
    """GarmentController.advance() has to be called by something; the rig is that caller."""
    garment = rig.session.garment
    garment.play_pattern(rig.session.patterns["sweep_20cms"])
    _spin(lambda: garment.status()["channels_on"])
