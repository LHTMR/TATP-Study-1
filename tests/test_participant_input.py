"""The participant's input when the remote is missing: the keyboard and the on-screen buttons
(docs/LOG.md N7.F12e4). Both reach the participant window exactly as the remote's keys do, so
everything behind it -- the adjustment's hold, the VAS, the emergency stop -- is unchanged."""

from __future__ import annotations

import dataclasses

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.clock import Clock
from tatp.devices import KEYBOARD, ON_SCREEN, configured
from tatp.responder import Action, Responder
from tatp.session import with_hardware_choices
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

HOLD_MS = 400


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


def _window(config) -> ParticipantWindow:
    window = ParticipantWindow(config, Responder(config.hardware), Clock())
    window.show()
    return window


def _with_input(loaded, participant_input):
    choices = dataclasses.replace(configured(loaded.hardware),
                                  participant_input=participant_input)
    return with_hardware_choices(loaded, choices)


def _record(window):
    seen = []
    window.adjust_pressed.connect(lambda action, ms: seen.append(("pressed", action, ms)))
    window.adjust_released.connect(lambda action, ms: seen.append(("released", action, ms)))
    window.emergency_stop.connect(lambda: seen.append(("stop",)))
    return seen


def test_with_the_remote_there_are_no_buttons_on_screen(app, loaded):
    """The participant screens look as approved when the remote is used."""
    window = _window(loaded)
    assert window.response_buttons == {}


def test_an_on_screen_button_held_is_a_hold_with_the_mouses_own_times(app, loaded):
    window = _window(_with_input(loaded, ON_SCREEN))
    window.show_adjustment(sorted(loaded.participant_text["adjust_targets"])[0])
    seen = _record(window)
    button = window.response_buttons[Action.INCREASE]
    QTest.mousePress(button, Qt.LeftButton)
    QTest.mouseRelease(button, Qt.LeftButton, delay=HOLD_MS)
    QApplication.sendPostedEvents()
    assert [event[:2] for event in seen] == [("pressed", "increase"), ("released", "increase")]
    assert seen[1][2] - seen[0][2] >= HOLD_MS, "the hold is timed from the mouse events"


def test_the_on_screen_stop_stops(app, loaded):
    window = _window(_with_input(loaded, ON_SCREEN))
    window.show_message(sorted(loaded.participant_text["screens"])[0])
    seen = _record(window)
    QTest.mouseClick(window.response_buttons[Action.EMERGENCY_STOP], Qt.LeftButton)
    QApplication.sendPostedEvents()
    assert seen == [("stop",)]


def test_the_on_screen_buttons_never_take_the_focus(app, loaded):
    """The window, or the VAS, keeps it, so the keys still reach them."""
    window = _window(_with_input(loaded, ON_SCREEN))
    assert all(made.focusPolicy() == Qt.NoFocus for made in window.response_buttons.values())


def test_the_keyboards_arrows_are_the_large_buttons(app, loaded):
    window = _window(_with_input(loaded, KEYBOARD))
    window.show_adjustment(sorted(loaded.participant_text["adjust_targets"])[0])
    seen = _record(window)
    for name, kind in (("left", QEvent.KeyPress), ("left", QEvent.KeyRelease),
                       ("escape", QEvent.KeyPress)):
        QApplication.sendEvent(window, QKeyEvent(kind, QT_KEYS[name], Qt.NoModifier))
    assert [event[:2] for event in seen] == [("pressed", "decrease"), ("released", "decrease"),
                                            ("stop",)]


def test_the_remotes_keys_do_nothing_under_the_keyboard(app, loaded):
    window = _window(_with_input(loaded, KEYBOARD))
    window.show_adjustment(sorted(loaded.participant_text["adjust_targets"])[0])
    seen = _record(window)
    QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, QT_KEYS["period"], Qt.NoModifier))
    assert seen == []
