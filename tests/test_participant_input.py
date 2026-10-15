"""The participant's input when the remote is missing: the keyboard and the on-screen buttons
(docs/LOG.md N7.F12e4). Both reach the participant window exactly as the remote's keys do, so
everything behind it -- the adjustment's hold, the VAS, the emergency stop -- is unchanged."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLineEdit,
    QListWidget,
    QPushButton,
    QWidget,
)

from tatp import config as cfg
from tatp.clock import Clock
from tatp.devices import KEYBOARD, ON_SCREEN, configured
from tatp.remote_keys import AnyKeyboard
from tatp.responder import Action, Responder
from tatp.session import with_hardware_choices
from tatp.ui.participant import ParticipantWindow, RemoteKeyRouter, uses_keys
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
                       ("period", QEvent.KeyPress)):
        QApplication.sendEvent(window, QKeyEvent(kind, QT_KEYS[name], Qt.NoModifier))
    assert [event[:2] for event in seen] == [("pressed", "decrease"), ("released", "decrease"),
                                            ("stop",)]


def test_the_remotes_other_keys_do_nothing_under_the_keyboard(app, loaded):
    """Esc above all: it closes dialogs, so it is no key of the keyboard input (code review)."""
    window = _window(_with_input(loaded, KEYBOARD))
    window.show_adjustment(sorted(loaded.participant_text["adjust_targets"])[0])
    seen = _record(window)
    for name in ("pageup", "escape", "f5"):
        QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, QT_KEYS[name], Qt.NoModifier))
    assert seen == []


@pytest.fixture
def routed(app, loaded):
    """The keyboard input routed as a session routes it, beside an experimenter window and a
    dialog of the experimenter's."""
    window = _window(_with_input(loaded, KEYBOARD))
    window.show_adjustment(sorted(loaded.participant_text["adjust_targets"])[0])
    router = RemoteKeyRouter(window, AnyKeyboard(), window)
    QApplication.instance().installEventFilter(router)
    experimenter = QWidget()
    surface = QPushButton("Next step", experimenter)
    experimenter.show()
    dialog = QDialog()
    accept = QPushButton("OK", dialog)
    dialog.show()
    yield SimpleNamespace(window=window, seen=_record(window), surface=surface, accept=accept,
                          combo=QComboBox(experimenter))
    QApplication.instance().removeEventFilter(router)


def _key(widget, name, kind=QEvent.KeyPress):
    QApplication.sendEvent(widget, QKeyEvent(kind, QT_KEYS[name], Qt.NoModifier))


def test_keys_over_the_experimenter_windows_surface_reach_the_participant(routed):
    """One person playing both parts on one screen presses the arrows after Next step."""
    _key(routed.surface, "left")
    assert [event[:2] for event in routed.seen] == [("pressed", "decrease")]


def test_return_or_an_arrow_in_a_dialog_or_a_list_is_the_experimenters(routed):
    """Code review: Return accepting a dialog is not ▶, an arrow in a combo box does not move
    the participant's control."""
    _key(routed.accept, "return")
    _key(routed.accept, "left")
    assert routed.seen == []
    # A key a list or a combo box uses is its own; one it leaves goes on to the window's
    # surface, as Qt passes it, and is the participant's from there.
    assert uses_keys(routed.combo) and uses_keys(QListWidget())
    assert not uses_keys(routed.surface)


def test_the_stop_is_forwarded_even_from_a_dialog(routed):
    """No dialog uses the full stop, and a stop is never to be lost."""
    _key(routed.accept, "period")
    assert routed.seen == [("stop",)]


def test_a_full_stop_typed_into_a_text_field_is_typed_not_a_stop(routed):
    """Pinned, so a change is deliberate: under any_keyboard a full stop in a note, a distance
    or the abort dialog's reason is the experimenter typing (open item L15, docs/LOG.md N7.I1).
    Only raw_input removes it; the on-screen "!" is a button, not a key."""
    reason = QLineEdit(routed.accept.window())
    reason.show()
    QApplication.sendEvent(reason, QKeyEvent(QEvent.KeyPress, QT_KEYS["period"], Qt.NoModifier,
                                             "."))
    assert reason.text() == "."
    assert routed.seen == []


def test_a_hold_on_screen_is_released_when_the_window_hides(app, loaded):
    """Spec review: the shared window's flags changing around a dialog hide it for a moment,
    and the button's mouse release is then lost; the hold must still end, at the time held."""
    window = _window(_with_input(loaded, ON_SCREEN))
    window.show_adjustment(sorted(loaded.participant_text["adjust_targets"])[0])
    seen = _record(window)
    button = window.response_buttons[Action.DECREASE]
    QTest.mousePress(button, Qt.LeftButton)
    QApplication.sendPostedEvents()
    window.hide()
    assert [event[:2] for event in seen] == [("pressed", "decrease"), ("released", "decrease")]
    assert seen[1][2] >= seen[0][2]
    assert button.held is None and not button.isDown()
