"""The VAS. SPEC.md 10.2, 10.6.

The state machine is tested directly. The widget is tested through real Qt key events under
QT_QPA_PLATFORM=offscreen, which is what SPEC.md 17.1 requires of the whole suite.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.clock import Clock
from tatp.responder import Action, Responder
from tatp.ui.vas import QT_KEYS, VasState, VasWidget


class FakeClock(Clock):
    def __init__(self):
        super().__init__()
        self.now = 0.0

    def elapsed_s(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def state(loaded):
    return VasState(loaded.study1["vas"], FakeClock())


# -- the rules of SPEC.md 10.2 ---------------------------------------------------------


def test_the_marker_is_hidden_until_the_first_press(state):
    state.cue()
    assert not state.visible
    assert state.confirm() is None, "there is no response to record before a press"


def test_the_first_press_puts_the_marker_on_the_side_that_was_pressed(state):
    state.cue()
    state.press(Action.DECREASE)
    assert state.visible
    assert state.percent == state.start_left_pct == 25.0
    assert state.first_press_side == "left"


def test_the_right_button_starts_on_the_right(state):
    state.cue()
    state.press(Action.INCREASE)
    assert state.percent == state.start_right_pct == 75.0
    assert state.first_press_side == "right"


def test_the_first_press_reveals_rather_than_moves(state):
    state.cue()
    state.press(Action.INCREASE)
    state.press(Action.INCREASE)
    assert state.percent == pytest.approx(state.start_right_pct + state.step_pct)


def test_the_marker_cannot_leave_the_line(state):
    state.cue()
    state.press(Action.DECREASE)
    for _ in range(200):
        state.press(Action.DECREASE)
    assert state.percent == 0.0
    for _ in range(400):
        state.press(Action.INCREASE)
    assert state.percent == 100.0


def test_direction_changes_are_counted(state):
    state.cue()
    state.press(Action.INCREASE)
    assert state.direction_changes == 0
    state.press(Action.INCREASE)
    assert state.direction_changes == 0
    state.press(Action.DECREASE)
    # The first press has a direction even though it does not move, so this is a real reversal.
    assert state.direction_changes == 1
    state.press(Action.DECREASE)
    assert state.direction_changes == 1
    state.press(Action.INCREASE)
    assert state.direction_changes == 2


def test_reaction_time_runs_from_the_rating_cue(state):
    state.clock.now = 100.0
    state.cue()
    state.clock.now = 101.5
    state.press(Action.INCREASE)
    state.clock.now = 103.25
    response = state.confirm()
    assert response.rt_s == pytest.approx(3.25)
    assert response.cue_iso == state.cue_iso
    assert response.rating_percent == 75.0


def test_a_press_before_the_cue_is_a_defect_not_a_rating(state):
    with pytest.raises(RuntimeError, match="before it was cued"):
        state.press(Action.INCREASE)


def test_cueing_again_clears_the_previous_response(state):
    state.cue()
    state.press(Action.INCREASE)
    state.cue()
    assert not state.visible
    assert state.direction_changes == 0
    assert state.first_press_side == ""


def test_waiting_time_is_reported_and_never_auto_advances(state):
    state.cue()
    state.clock.now += 90.0
    assert state.waiting_s == pytest.approx(90.0)
    assert state.waiting_s > state.no_response_warning_s
    assert state.confirm() is None, "waiting does not produce a rating"


# -- the widget ------------------------------------------------------------------------


def _press(widget, name, release=True):
    key = QT_KEYS[name]
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    if release:
        widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


@pytest.fixture
def widget(app, loaded):
    made = VasWidget(
        loaded.study1["vas"],
        Responder(loaded.hardware),
        FakeClock(),
    )
    made.resize(1280, 800)
    made.show_scale("pain", loaded.participant_text["vas"]["pain"])
    return made


def test_the_widget_carries_no_wording_of_its_own(widget, loaded):
    """SPEC.md 10.4: no user-facing string in any .py file."""
    assert widget.question == loaded.participant_text["vas"]["pain"]["question"]
    assert [a["label"] for a in widget.anchors] == [
        a["label"] for a in loaded.participant_text["vas"]["pain"]["anchors"]
    ]


def test_confirming_emits_the_response(widget):
    got = []
    widget.confirmed.connect(got.append)
    _press(widget, "pagedown")
    _press(widget, "period")
    assert len(got) == 1
    assert got[0].rating_percent == 75.0
    assert got[0].first_press_side == "right"


def test_confirming_with_no_marker_emits_no_response(widget):
    got, empty = [], []
    widget.confirmed.connect(got.append)
    widget.pressed_without_marker.connect(lambda: empty.append(1))
    _press(widget, "period")
    assert got == []
    assert empty == [1]


def test_escape_is_swallowed(widget):
    """SPEC.md 10.1: it must not reach Qt, which would close the window."""
    event = QKeyEvent(QEvent.KeyPress, QT_KEYS["escape"], Qt.NoModifier)
    widget.keyPressEvent(event)
    assert event.isAccepted()
    assert not widget.state.visible, "escape must not move or reveal the marker"


def test_the_emergency_stop_key_is_wired(widget):
    stops = []
    widget.emergency_stop.connect(lambda: stops.append(1))
    _press(widget, "f5")
    assert stops == [1]


def test_auto_repeat_events_are_ignored(widget):
    """Hold-to-repeat is driven by the widget's own timer, not by the platform's key repeat."""
    _press(widget, "pagedown")
    before = widget.state.percent
    widget.keyPressEvent(
        QKeyEvent(QEvent.KeyPress, QT_KEYS["pagedown"], Qt.NoModifier, autorep=True)
    )
    assert widget.state.percent == before


def test_the_widget_renders_headless(widget):
    """SPEC.md 17.1 and 17.4: the suite runs with no display and grabs real pixmaps."""
    _press(widget, "pageup")
    pixmap = widget.grab()
    assert pixmap.width() == 1280
    assert pixmap.height() == 800
    assert not pixmap.isNull()
