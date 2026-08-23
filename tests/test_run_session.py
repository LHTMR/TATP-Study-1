"""The entry point. SPEC.md 4.1.

`run_session.py` is what makes the Milestone 1 slice something that runs rather than something
only the test suite reaches, so what is tested here is the wiring: the arguments, the terminal
warnings, and that driving the runner to a confirmed rating leaves a closed session with one
valid row in it.

The `QApplication.exec()` loop itself is not entered -- the runner is driven by the same
accelerated clock and synthetic key presses as `tests/test_pinprick.py`, so the test stays
headless and finishes in milliseconds.
"""

from __future__ import annotations

import csv
import time

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

import run_session
from tatp import config as cfg
from tatp.clock import Clock
from tatp.responder import Responder
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"

CLOCK_SPEED = 100.0
SPIN_TIMEOUT_S = 10.0

ARGV = [
    "--participant", "01",
    "--session", "1",
    "--experimenter", "SM",
    "--patterns", str(EXAMPLES),
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def runner(app, loaded, tmp_path):
    """A started session with both windows and a runner, ready to run the slice."""
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED), rng_seed=7
    )
    session.start()
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    session.set_phase("pre_sensitisation")
    made = run_session.SliceRunner(session, participant, experimenter)
    yield made
    session.close()


def _spin(condition) -> None:
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the slice did not reach the expected state")
        QApplication.processEvents()
        time.sleep(0.001)


def _press(widget, name) -> None:
    key = QT_KEYS[name]
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def _rows(session, table):
    with session.files.path(table).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _answer_vas(participant) -> None:
    _press(participant.vas, "pagedown")
    _press(participant.vas, "period")


def _run_slice(runner) -> None:
    """Adjust, rate the touch, then rate one pinprick application -- the whole slice."""
    participant = runner.participant
    runner.run()
    _press(participant, "pagedown")
    _press(participant, "period")

    # The touch intensity rating follows the adjustment immediately; the pinprick rating waits
    # out the warning cue and the configured delay, which the accelerated clock compresses.
    _answer_vas(participant)
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    _answer_vas(participant)


# -- arguments and warnings ---------------------------------------------------------------


def test_the_pattern_folder_has_no_default():
    """Defaulting it would silently substitute the provisional mockups (FOR_S A3.2)."""
    with pytest.raises(SystemExit):
        run_session.parse_args([a for a in ARGV if a not in ("--patterns", str(EXAMPLES))])


def test_the_arguments_carry_the_identity_and_the_development_switches():
    args = run_session.parse_args([*ARGV, "--clock-speed", "50", "--seed", "7"])
    assert args.participant == "01"
    assert args.session == 1
    assert args.experimenter == "SM"
    assert args.clock_speed == 50.0
    assert args.seed == 7
    # A real session is Swedish for the participant and English for the experimenter.
    assert args.participant_language == "sv"
    assert args.experimenter_language == "en"


def test_unresolved_open_items_are_printed_before_the_windows_open(loaded):
    """SPEC.md 20: warn, never block. The banner is not visible until a window exists."""
    lines = run_session.warnings_for(loaded)
    assert len(lines) == len(loaded.unresolved) + (1 if loaded.has_placeholder_text() else 0)
    for item in loaded.unresolved:
        assert any(line.startswith(f"[{item.number}]") for line in lines)


# -- the slice ----------------------------------------------------------------------------


def test_the_slice_writes_every_table_it_touches_and_closes_the_session(runner):
    _run_slice(runner)
    assert runner.completed
    assert runner.session.closed

    adjust = _rows(runner.session, "touchcal_adjust")
    assert len(adjust) == 1
    assert adjust[0]["stage"] == "anchor"
    touch = _rows(runner.session, "touch_ratings")
    assert len(touch) == 1
    assert touch[0]["scale"] == "intensity"
    assert float(touch[0]["commanded_pressure_kpa"]) > 0.0, "the touch was being delivered"

    rows = _rows(runner.session, "pinprick")
    assert len(rows) == 1
    assert rows[0]["filament_label_g"] == (
        runner.session.config.study1["pinprick"]["start_filament_label_g_session1_pre_s"]
    )
    assert rows[0]["phase"] == "pre_sensitisation"


def test_the_participant_is_left_on_the_closing_screen(runner):
    _run_slice(runner)
    text = runner.session.config.participant_text["screens"][run_session.END_SCREEN]
    assert runner.participant.message.text == text
    assert runner.participant.stack.currentWidget() is runner.participant.message


def test_an_emergency_stop_closes_the_session_as_aborted(runner):
    """SPEC.md 13. A one-trial session has nothing to resume to, so it stops and records why."""
    runner.run()
    _press(runner.participant, "f5")

    assert not runner.completed
    assert runner.session.closed
    assert runner.session.aborted_reason == run_session.ABORT_EMERGENCY_STOP
    aborts = [r for r in _rows(runner.session, "log") if r["event"] == "session_aborted"]
    assert len(aborts) == 1
    assert aborts[0]["severity"] == "warning"
