"""The participant window. SPEC.md 10.

One window holding four screens: a block of centred text, the visual warning cue that precedes
every stimulus (SPEC.md 10.5), the VAS, and a two-alternative choice with its buttons drawn
(SPEC.md 10.8). Which of them is showing is the whole of the window's state.

It carries no wording of its own -- every string is looked up in
`config/text/participant_{sv,en}.yaml` by key (SPEC.md 10.4), so a missing key raises where the
screen was asked for rather than showing a participant a blank.

**Input.** The emergency stop must work on every screen, not only while a rating is on display
(SPEC.md 13), so the window handles keys whenever the VAS is not the current screen and
swallows everything else. `escape` is one of the play button's two keys, so it must reach the
window as a confirm and never as Qt's "close this window" (SPEC.md 10.1).

Two screens read more than the emergency stop. The adjustment screen: the pressure adjustment
of SPEC.md 10.3 is press-and-hold, so both the down and the up of every button matter and the
window emits them as they happen. And the choice screen, where the press itself is the response
(SPEC.md 10.8). Neither knows what a press means -- what a button does to the pressure, and what
a choice is a choice between, are `tatp/touchcal.py`, so the participant window stays a display
with no protocol in it.
"""

from __future__ import annotations

import time

import shiboken6
from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tatp.clock import Clock
from tatp.config import Config
from tatp.devices import ON_SCREEN
from tatp.responder import Action, Responder
from tatp.ui.vas import (
    BACKGROUND,
    FOREGROUND,
    QT_KEYS,
    QUESTION_POINT_SIZE,
    QUESTION_Y_FRACTION,
    SIDE_MARGIN_FRACTION,
    VasWidget,
    draw_prose,
)
from tatp.units import MS_PER_S

# How the window draws itself. Not study parameters (SPEC.md 4.2 lists timings, forces,
# pressures, thresholds, rates and strings) -- the reference screenshots are what pin these
# (SPEC.md 17.4).
# The screen every protocol shows after an emergency stop. A key in the participant text file,
# not wording -- it lives here rather than in one protocol because both of them show it.
EMERGENCY_STOP_SCREEN = "emergency_stop"
# The one screen that draws the stop button, because pointing at it is its purpose (SPEC.md
# 10.9). A key in the participant text file, not wording.
STOP_REHEARSAL_SCREEN = "stop_rehearsal"
# The rest screen between parts (SPEC.md 10.5). A key in the participant text file.
STANDBY_SCREEN = "standby"
# The participant text key whose two option labels name the two touches of a pair: the
# comparison's "The first" / "The second", reused on the channel match (docs/LOG.md N7.F11c5).
PAIR_LABELS = "comparison"

MESSAGE_POINT_SIZE = 26

# The drawn response buttons (UI_PRINCIPLES.md 5.8-5.11). Sized and placed to match the remote
# in the participant's hand: two buttons side by side, the left one on the left.
BUTTON_CENTRE_FRACTIONS = (0.30, 0.70)
BUTTON_WIDTH_FRACTION = 0.18
BUTTON_HEIGHT_FRACTION = 0.18
BUTTON_Y_FRACTION = 0.46
BUTTON_RADIUS_PX = 16
BUTTON_LINE_WIDTH_PX = 3
# A stimulus playing thickens its button's outline rather than lighting it up: the emphasis says
# "this is what you are feeling now", and anything brighter starts to read as a recommendation.
BUTTON_EMPHASIS_WIDTH_PX = 9
BUTTON_SYMBOL_POINT_SIZE = 52
# The stop button's sticker disc, as a fraction of the button's shorter side.
STOP_DISC_FRACTION = 0.8
BUTTON_LABEL_POINT_SIZE = 20
BUTTON_LABEL_GAP_PX = 22
# The label may be wider than its button -- it is a phrase, the button is a symbol -- but not so
# wide that two labels meet. The buttons' centres are 0.40 of the width apart, so this leaves a
# gutter between them.
BUTTON_LABEL_WIDTH_FRACTION = 0.34

SIDES = ("left", "right")
# The adjustment screen's confirm sentence sits below the button labels.
ADJUST_CONFIRM_Y_FRACTION = 0.76
# The stop rehearsal's button sits below its three lines of text rather than where the two
# large buttons go, which that text would overlap.
STOP_BUTTON_Y_FRACTION = 0.62
STOP_BUTTON_CENTRE_FRACTION = 0.5
# The channel match's pair labels sit in the gap between the two drawn buttons, one above the
# other, at these fractions of the buttons' height: clear of both, so neither reads as a
# button's own label.
PAIR_ROW_FRACTIONS = (0.3, 0.7)
PAIR_UNDERLINE_GAP_PX = 6
# The on-screen buttons that stand in for the remote (docs/LOG.md N7.F12e4), in a row below the
# screens. Large enough to hit without looking twice.
RESPONSE_BUTTON_POINT_SIZE = 28
RESPONSE_BUTTON_WIDTH_PX = 110
RESPONSE_BUTTON_HEIGHT_PX = 64
RESPONSE_BAR_MARGIN_PX = 12
RESPONSE_BAR_GROUP_GAP_PX = 48


class _MessageScreen(QWidget):
    """One block of text on the neutral background. Empty text is a blank screen.

    Horizontally centred, but **top-aligned at the same fraction as the VAS question** and
    inside the same side margins, so the first line sits where the participant is already
    looking whatever screen preceded it (UI_PRINCIPLES.md 5.5). Vertically centring instead
    moves the text with every change of message length, which over roughly 150 rating cycles
    is a search on every one of them.
    """

    def __init__(self, responder: Responder, parent: QWidget | None = None):
        super().__init__(parent)
        self.responder = responder
        self.text = ""
        # Weight rather than wording is what marks the stop screen out from a rest screen
        # (UI_PRINCIPLES.md 5.6). Not colour: an alarming screen is the wrong thing to show
        # someone who has just pressed the button because something was unpleasant.
        self.emphasised = False
        # The stop button's printed symbol, on the stop rehearsal only (SPEC.md 10.9).
        self.stop_symbol: str | None = None
        # The colour printed on that button (`responder.button_symbol_colours`), set by the
        # window from hardware.yaml.
        self.stop_colour = FOREGROUND
        self.stop_disc: QColor | None = None

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        painter.setPen(FOREGROUND)
        font = QFont(self.font())
        font.setPointSize(MESSAGE_POINT_SIZE)
        font.setBold(self.emphasised)
        painter.setFont(font)
        margin = int(self.width() * SIDE_MARGIN_FRACTION)
        top = int(self.height() * QUESTION_Y_FRACTION)
        box = self.rect().adjusted(margin, top, -margin, 0)
        draw_prose(painter, box, self.text, self.responder)
        if self.stop_symbol is not None:
            painter.setRenderHint(QPainter.Antialiasing)
            _draw_symbol_button(
                painter,
                self,
                _stop_button_rect(self),
                self.stop_symbol,
                self.stop_colour,
                self.stop_disc,
            )
        painter.end()


class _CueScreen(QWidget):
    """The visual warning cue: the short `warning_cue` text, alone on the screen.

    Words rather than the filled disc it replaces (S, 15 Oct 2026 pilot): a disc needed the
    welcome screen to explain it, and words explain themselves. Laid out exactly as a message
    -- same margins, wrapping and top position (UI_PRINCIPLES.md 5.5) -- but at the drawn
    button symbols' size, the largest in the participant set (4.3), because it is a signal to
    take in at a glance rather than a sentence to read.
    """

    def __init__(self, text: str, responder: Responder, parent: QWidget | None = None):
        super().__init__(parent)
        self.text = text
        self.responder = responder

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        painter.setPen(FOREGROUND)
        font = QFont(self.font())
        font.setPointSize(BUTTON_SYMBOL_POINT_SIZE)
        painter.setFont(font)
        margin = int(self.width() * SIDE_MARGIN_FRACTION)
        top = int(self.height() * QUESTION_Y_FRACTION)
        box = self.rect().adjusted(margin, top, -margin, 0)
        draw_prose(painter, box, self.text, self.responder)
        painter.end()


class _ChoiceScreen(QWidget):
    """A two-alternative choice, with the buttons drawn rather than described.

    The screen renders the two large buttons of the response device carrying the symbols that
    are physically on them, with an option label under each (UI_PRINCIPLES.md 5.8, 5.9). The
    participant does not translate "left button: the first" into a thumb movement on every
    trial; they press the button they can see.

    **The press is the answer** (UI_PRINCIPLES.md 5.12). There is no confirm, because there is
    nothing to adjust in a choice between two options, and so no state in which a participant
    has chosen but not committed.

    Three moments, and the protocol drives all three:

    - `present()` puts the question and both buttons up, accepting nothing.
    - `emphasise(side)` thickens one button's outline while its stimulus plays, which is what
      ties the sensation to the button under the thumb (UI_PRINCIPLES.md 5.11). It is coincident
      with the stimulus rather than a legend shown beforehand.
    - `accept()` makes the next press the response.

    After an accepted press the screen runs itself: the chosen button is held visibly chosen for
    `feedback_s`, then the screen goes blank for `gap_s` and `gap_elapsed` fires. That sequence
    is presentation, so it lives here -- but `chosen` is emitted on the press itself, not at the
    end of it, so a protocol timing the response times the participant and not the animation.
    """

    chosen = Signal(str)  # "left" or "right"
    gap_elapsed = Signal()
    pressed_before_accepting = Signal()

    def __init__(
        self, choice_config: dict, responder: Responder, parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.responder = responder
        self._feedback_ms = int(round(float(choice_config["feedback_s"]) * MS_PER_S))
        self._gap_ms = int(round(float(choice_config["gap_s"]) * MS_PER_S))
        self.question = ""
        self.labels: dict[str, str] = {}
        self.emphasised: str | None = None
        self.selected: str | None = None
        self.accepting = False
        self.blank = False

    # -- the three moments -------------------------------------------------------------

    def present(self, text: dict) -> None:
        """`text` is one entry of the `choices` block: a question and the two option labels."""
        self.question = text["question"]
        self.labels = {side: text[side] for side in SIDES}
        self.emphasised = None
        self.selected = None
        self.accepting = False
        self.blank = False
        self.update()

    def emphasise(self, side: str | None) -> None:
        if side is not None and side not in SIDES:
            raise KeyError(f"{side!r} is not a side of a two-alternative choice")
        self.emphasised = side
        self.update()

    def accept(self) -> None:
        self.emphasised = None
        self.accepting = True
        self.update()

    def press(self, side: str) -> None:
        """One response.

        A press before the screen is accepting is reported rather than swallowed: trying to
        answer before the stimuli are finished is something about the participant, and the
        session logs it the way it logs a VAS confirm with no marker shown.
        """
        if not self.accepting:
            self.pressed_before_accepting.emit()
            return
        self.accepting = False
        self.selected = side
        self.update()
        self.chosen.emit(side)
        # With the screen as the timers' context, so a timer never fires into a screen that has
        # been deleted ("Signal source has been deleted"), and holds its target alive until it
        # fires -- a bare `signal.emit` handed to `singleShot` can be collected first, and then
        # the gap never ends and the procedure waiting on it stalls.
        QTimer.singleShot(self._feedback_ms, self, self._begin_gap)

    def _begin_gap(self) -> None:
        self.blank = True
        self.update()
        QTimer.singleShot(self._gap_ms, self, self._end_gap)

    def _end_gap(self) -> None:
        self.gap_elapsed.emit()

    # -- drawing -----------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), BACKGROUND)
        if self.blank or not self.labels:
            painter.end()
            return
        _draw_top_text(painter, self, self.question)
        for side in SIDES:
            _draw_button(
                painter,
                self,
                self.responder,
                side,
                self.labels[side],
                emphasised=self.emphasised == side,
                pressed=self.selected == side,
            )
        painter.end()


class _ControlScreen(QWidget):
    """An opening line, the two buttons drawn, and a confirm sentence.

    Two screens have this shape: the pressure adjustment (SPEC.md 9, 10.3) and the preference
    selection (SPEC.md 9 step 6). Both draw the buttons for the same reason as the choice screen
    (UI_PRINCIPLES.md 5.8, 5.9) -- the participant presses the button they can see instead of
    translating "left button: weaker" on every one of roughly thirty adjustments.

    **Unlike a choice, both keep a confirm**, because here the press is not the answer: it moves
    something -- a pressure, a position in a list -- that the participant then commits to
    (UI_PRINCIPLES.md 5.12). The confirm stays a sentence rather than a third drawn button,
    because the play button is one of the remote's two small buttons and no screen draws those
    yet; their labels may change (docs/LOG.md N5.11).

    A held button is drawn pressed for exactly as long as it is held (UI_PRINCIPLES.md 5.10).
    On the adjustment that also shows the participant that a hold is registering while the
    pressure ramps, which a sentence cannot.

    **The channel match names its two touches** (`pair`). Its reference and the touch being set
    take turns, and the participant could not tell which one they were feeling. So "The first"
    and "The second" stand between the buttons, and the one playing is set in bold and
    underlined while it plays (`playing`), as the comparison emphasises its button
    (UI_PRINCIPLES.md 5.11): weight, never brightness or colour.
    """

    def __init__(self, responder: Responder, parent: QWidget | None = None):
        super().__init__(parent)
        self.responder = responder
        self.target = ""
        self.labels: dict[str, str] = {}
        self.confirm = ""
        self.held: set[str] = set()
        self.pair: tuple[str, str] | None = None
        self.playing: int | None = None

    def present(self, opening: str, controls: dict,
                pair: tuple[str, str] | None = None) -> None:
        """`opening` goes above the buttons; `controls` is one `participant_controls` entry;
        `pair` names the two alternating touches, on the channel match only."""
        self.target = opening
        self.labels = {side: controls[side] for side in SIDES}
        self.confirm = controls["confirm"]
        self.held.clear()
        self.pair = pair
        self.playing = None
        self.update()

    def emphasise(self, index: int | None) -> None:
        """Mark which of `pair` is playing now; None while neither is."""
        self.playing = index
        self.update()

    def hold(self, side: str) -> None:
        self.held.add(side)
        self.update()

    def release(self, side: str) -> None:
        self.held.discard(side)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), BACKGROUND)
        _draw_top_text(painter, self, self.target)
        for side in SIDES:
            _draw_button(
                painter,
                self,
                self.responder,
                side,
                self.labels[side],
                emphasised=False,
                pressed=side in self.held,
            )
        font = QFont(self.font())
        font.setPointSize(MESSAGE_POINT_SIZE)
        painter.setFont(font)
        painter.setPen(FOREGROUND)
        margin = int(self.width() * SIDE_MARGIN_FRACTION)
        top = int(self.height() * ADJUST_CONFIRM_Y_FRACTION)
        box = self.rect().adjusted(margin, top, -margin, 0)
        draw_prose(painter, box, self.confirm, self.responder)
        if self.pair is not None:
            self._draw_pair(painter)
        painter.end()

    def _draw_pair(self, painter: QPainter) -> None:
        left, right = _button_rect(self, SIDES[0]), _button_rect(self, SIDES[1])
        for index, (label, row) in enumerate(zip(self.pair, PAIR_ROW_FRACTIONS, strict=True)):
            font = QFont(self.font())
            font.setPointSize(BUTTON_LABEL_POINT_SIZE)
            font.setBold(index == self.playing)
            painter.setFont(font)
            painter.setPen(FOREGROUND)
            metrics = QFontMetrics(font)
            centre_y = int(left.top() + left.height() * row)
            box = QRect(left.right(), centre_y - metrics.height() // 2,
                        right.left() - left.right(), metrics.height())
            painter.drawText(box, Qt.AlignCenter, label)
            if index == self.playing:
                width = metrics.horizontalAdvance(label)
                y = box.bottom() + PAIR_UNDERLINE_GAP_PX
                painter.setPen(QPen(FOREGROUND, BUTTON_LINE_WIDTH_PX))
                painter.drawLine(box.center().x() - width // 2, y,
                                 box.center().x() + width // 2, y)


def _draw_top_text(painter: QPainter, widget: QWidget, text: str) -> None:
    """Text top-aligned where every participant screen starts reading (UI_PRINCIPLES.md 5.5)."""
    font = QFont(widget.font())
    font.setPointSize(QUESTION_POINT_SIZE)
    painter.setFont(font)
    painter.setPen(FOREGROUND)
    margin = int(widget.width() * SIDE_MARGIN_FRACTION)
    top = int(widget.height() * QUESTION_Y_FRACTION)
    box = widget.rect().adjusted(margin, top, -margin, 0)
    draw_prose(painter, box, text, widget.responder)


def _button_rect(widget: QWidget, side: str) -> QRect:
    centre = BUTTON_CENTRE_FRACTIONS[SIDES.index(side)]
    width = widget.width() * BUTTON_WIDTH_FRACTION
    height = widget.height() * BUTTON_HEIGHT_FRACTION
    return QRect(
        int(widget.width() * centre - width / 2),
        int(widget.height() * BUTTON_Y_FRACTION),
        int(width),
        int(height),
    )


def _stop_button_rect(widget: QWidget) -> QRect:
    width = widget.width() * BUTTON_WIDTH_FRACTION
    height = widget.height() * BUTTON_HEIGHT_FRACTION
    return QRect(
        int(widget.width() * STOP_BUTTON_CENTRE_FRACTION - width / 2),
        int(widget.height() * STOP_BUTTON_Y_FRACTION),
        int(width),
        int(height),
    )


def _draw_symbol_button(
    painter: QPainter,
    widget: QWidget,
    rect: QRect,
    symbol: str,
    colour: QColor,
    disc: QColor | None = None,
) -> None:
    """A button outline carrying its printed symbol, with no label: the text above names it.

    `disc` is the filled circle the symbol sits on, where the physical button has one -- the
    lab remote's stop is a black "!" on a yellow sticker, and it should look like that.
    """
    painter.setPen(QPen(FOREGROUND, BUTTON_LINE_WIDTH_PX))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect, BUTTON_RADIUS_PX, BUTTON_RADIUS_PX)
    if disc is not None:
        diameter = int(min(rect.width(), rect.height()) * STOP_DISC_FRACTION)
        painter.setPen(Qt.NoPen)
        painter.setBrush(disc)
        painter.drawEllipse(rect.center(), diameter // 2, diameter // 2)
        painter.setBrush(Qt.NoBrush)
    symbol_font = QFont(widget.font())
    symbol_font.setPointSize(BUTTON_SYMBOL_POINT_SIZE)
    symbol_font.setBold(disc is not None)
    # Shrunk to fit if it is wider than the button: a symbol cut off at both edges stops
    # being the symbol.
    room = rect.width() - 2 * BUTTON_RADIUS_PX
    width = QFontMetrics(symbol_font).horizontalAdvance(symbol)
    if width > room:
        symbol_font.setPointSizeF(BUTTON_SYMBOL_POINT_SIZE * room / width)
    painter.setFont(symbol_font)
    painter.setPen(colour)
    painter.drawText(rect, Qt.AlignCenter, symbol)


def _draw_button(
    painter: QPainter,
    widget: QWidget,
    responder: Responder,
    side: str,
    label: str,
    *,
    emphasised: bool,
    pressed: bool,
) -> None:
    """One large button of the remote, carrying its printed symbol, with a label under it."""
    rect = _button_rect(widget, side)
    action = Action.DECREASE if side == "left" else Action.INCREASE

    width = BUTTON_EMPHASIS_WIDTH_PX if emphasised else BUTTON_LINE_WIDTH_PX
    painter.setPen(QPen(FOREGROUND, width))
    painter.setBrush(FOREGROUND if pressed else Qt.NoBrush)
    painter.drawRoundedRect(rect, BUTTON_RADIUS_PX, BUTTON_RADIUS_PX)

    symbol_font = QFont(widget.font())
    symbol_font.setPointSize(BUTTON_SYMBOL_POINT_SIZE)
    painter.setFont(symbol_font)
    painter.setPen(BACKGROUND if pressed else FOREGROUND)
    painter.drawText(rect, Qt.AlignCenter, responder.symbol_for(action))

    label_font = QFont(widget.font())
    label_font.setPointSize(BUTTON_LABEL_POINT_SIZE)
    painter.setFont(label_font)
    painter.setPen(FOREGROUND)
    label_width = int(widget.width() * BUTTON_LABEL_WIDTH_FRACTION)
    label_box = QRect(
        rect.center().x() - label_width // 2,
        rect.bottom() + BUTTON_LABEL_GAP_PX,
        label_width,
        widget.height() - rect.bottom() - BUTTON_LABEL_GAP_PX,
    )
    draw_prose(painter, label_box, label, responder)


class _ResponseButton(QPushButton):
    """One of the remote's buttons on screen, for a mouse or trackpad (docs/LOG.md N7.F12e4).

    Its press and its release are delivered as the remote's key going down and up, stamped
    with the mouse event's own time, exactly as a raw report from the remote is
    (`ParticipantWindow.deliver_remote_key`): the adjustment and the VAS time a hold from those
    stamps. It never takes the focus, which the window or the VAS keeps for the keys.
    """

    def __init__(self, symbol: str, key: str, deliver, parent: QWidget):
        super().__init__(symbol, parent)
        self.key = key
        self._deliver = deliver
        self.setFocusPolicy(Qt.NoFocus)
        font = self.font()
        font.setPointSize(RESPONSE_BUTTON_POINT_SIZE)
        self.setFont(font)
        self.setMinimumSize(RESPONSE_BUTTON_WIDTH_PX, RESPONSE_BUTTON_HEIGHT_PX)
        self.setStyleSheet(
            f"QPushButton {{ color: {FOREGROUND.name()}; "
            f"background-color: {BACKGROUND.name()}; "
            f"border: {BUTTON_LINE_WIDTH_PX}px solid {FOREGROUND.name()}; "
            f"border-radius: {BUTTON_RADIUS_PX}px; }}"
        )

        # The press's own stamp and the real time it came, while it is held.
        self.held: tuple[int, float] | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().mousePressEvent(event)
        self.held = (event.timestamp(), time.monotonic())
        self._deliver(self.key, False, False, event.timestamp())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().mouseReleaseEvent(event)
        if self.held is None:
            return
        self.held = None
        self._deliver(self.key, True, False, event.timestamp())

    def release_stamp(self) -> int:
        """The stamp a release would carry now: the press's, plus the real time held since."""
        press_ms, press_s = self.held
        return press_ms + round((time.monotonic() - press_s) * MS_PER_S)


class ParticipantWindow(QWidget):
    """The participant's screen. Everything shown to a participant goes through here."""

    confirmed = Signal(object)  # a VasResponse
    emergency_stop = Signal()
    pressed_without_marker = Signal()
    # The adjustment screen only (SPEC.md 10.3). Each carries the responder action's value and
    # the key event's own timestamp in milliseconds -- when the button moved, not when a handler
    # ran (tatp.touchcal.PressTiming). `object`, not `int`: a Signal(int) is a 32-bit C int, and
    # a millisecond uptime passes that after 25 days.
    adjust_pressed = Signal(str, object)
    adjust_released = Signal(str, object)
    adjust_confirmed = Signal()
    # The choice screen only (SPEC.md 10.8). `chosen` carries "left" or "right".
    chosen = Signal(str)
    choice_gap_elapsed = Signal()
    pressed_before_accepting = Signal()
    # The play button on a message screen that says "Press ▶ to continue" (SPEC.md 10.9) or
    # asks for the self-start press (SPEC.md 12.3). Emitted on any message screen; what it
    # means is up to whoever is listening, and nothing listens on a screen that asks nothing.
    message_confirmed = Signal()
    # The play button on the VAS training's practice rating (SPEC.md 10.6), with the practice
    # VasResponse. Separate from `confirmed` so a practice can never be recorded as a rating.
    vas_training_confirmed = Signal(object)
    # A play-button press ignored as carried over from the screen before (docs/LOG.md N7.U15).
    confirm_carried_over = Signal()
    # The visual warning cue has just gone up (SPEC.md 10.5). The rig sounds the audible cue
    # from this, so the two cannot come apart.
    warning_cue_shown = Signal()

    def __init__(
        self,
        config: Config,
        responder: Responder,
        clock: Clock,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.text = config.participant_text
        self.responder = responder
        self.clock = clock
        # Real seconds at the start of the latest key press, before anything else runs. The
        # self-start latency is measured from here (SPEC.md 12.3), so it includes the software's
        # own handling rather than starting after it.
        self.last_press_real_s: float | None = None
        self._names = {key: name for name, key in QT_KEYS.items()}
        # When the play button last did something, on the clock's elapsed time: a press within
        # `repeat_confirm_lockout_s` of it belongs to the screen before (docs/LOG.md N7.U15).
        responder_config = config.hardware["responder"]
        self._confirm_lockout_s = float(responder_config["repeat_confirm_lockout_s"])
        self._confirm_accepted_s: float | None = None

        self.message = _MessageScreen(responder)
        self.message.stop_colour = QColor(
            responder_config["button_symbol_colours"]["emergency_stop"]
        )
        self.message.stop_disc = QColor(
            responder_config["button_symbol_discs"]["emergency_stop"]
        )
        self.cue = _CueScreen(self.text["warning_cue"], responder)
        self.vas = VasWidget(config.study1["vas"], responder, clock)
        self.vas.confirmed.connect(self.confirmed)
        self.vas.emergency_stop.connect(self.emergency_stop)
        self.vas.pressed_without_marker.connect(self.pressed_without_marker)
        self.vas.training_confirmed.connect(self.vas_training_confirmed)
        # A rating or a training confirmed on the VAS is a press the next screen must not take.
        self.vas.confirmed.connect(self._confirm_accepted)
        self.vas.training_confirmed.connect(self._confirm_accepted)
        self.control = _ControlScreen(responder)
        self.choice = _ChoiceScreen(config.study1["choice"], responder)
        self.choice.chosen.connect(self.chosen)
        self.choice.gap_elapsed.connect(self.choice_gap_elapsed)
        self.choice.pressed_before_accepting.connect(self.pressed_before_accepting)

        self.stack = QStackedWidget(self)
        for screen in (self.message, self.cue, self.vas, self.control, self.choice):
            self.stack.addWidget(screen)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack)
        # Only when the hardware page chose them, so with the remote the window is the
        # approved screens and nothing else (docs/LOG.md N7.F12e4).
        self.response_buttons: dict[Action, _ResponseButton] = {}
        if responder_config["participant_input"] == ON_SCREEN:
            layout.addWidget(self._response_bar(responder_config))

        self._adjusting = False
        self._choosing = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.show_blank()

    def _response_bar(self, responder_config: dict) -> QWidget:
        """The remote's four buttons, on screen for a mouse or trackpad (docs/LOG.md
        N7.F12e4): the two large ones at the left, where the hand would hold them, ▶ apart, and
        the stop alone at the far right, on its sticker's disc. Each presses and releases the
        key the remote's button sends, at the moment the mouse does, so a hold is a hold."""
        bar = QWidget(self)
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(f"background-color: {BACKGROUND.name()};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(RESPONSE_BAR_MARGIN_PX, RESPONSE_BAR_MARGIN_PX,
                               RESPONSE_BAR_MARGIN_PX, RESPONSE_BAR_MARGIN_PX)
        row.setSpacing(RESPONSE_BAR_MARGIN_PX)
        for action in Action:
            made = _ResponseButton(
                self.responder.symbol_for(action, pointing_at_stop=True),
                self.responder.key_for(action), self.deliver_remote_key, bar,
            )
            if action is Action.EMERGENCY_STOP:
                row.addStretch(1)
                colour = responder_config["button_symbol_colours"][action]
                disc = responder_config["button_symbol_discs"][action]
                made.setStyleSheet(made.styleSheet() + (
                    f"QPushButton {{ color: {colour}; background-color: {disc}; }}"
                ))
            elif action is Action.CONFIRM:
                row.addSpacing(RESPONSE_BAR_GROUP_GAP_PX)
            self.response_buttons[action] = made
            row.addWidget(made)
        return bar

    # -- placement ---------------------------------------------------------------------

    def place(self, screens: dict) -> None:
        """Put the window where `hardware.yaml` says.

        A null screen index means the primary screen, windowed -- right for a development
        machine and wrong for the lab PC, which is why it warns at startup (open item 9). It is
        not silently defaulted to fullscreen on screen 0: a participant window covering the
        experimenter's screen is worse than an obviously wrong small one.
        """
        index = screens["participant_screen_index"]
        if index is None:
            return
        available = QGuiApplication.screens()
        if not 0 <= index < len(available):
            raise IndexError(
                f"hardware.yaml: screens.participant_screen_index is {index}, but this machine "
                f"has {len(available)} screen(s)"
            )
        self.setGeometry(available[index].geometry())
        if screens["participant_fullscreen"]:
            self.showFullScreen()

    # -- screens -----------------------------------------------------------------------

    def show_message(self, key: str) -> None:
        """Show `screens.<key>` from the participant text file."""
        self.message.text = self.text["screens"][key]
        self.message.emphasised = key == EMERGENCY_STOP_SCREEN
        self.message.stop_symbol = (
            self.responder.symbol_for(Action.EMERGENCY_STOP, pointing_at_stop=True)
            if key == STOP_REHEARSAL_SCREEN
            else None
        )
        self._show(self.message)

    def show_blank(self) -> None:
        """Nothing at all -- what the participant sees while a stimulus is being delivered."""
        self.message.text = ""
        self.message.emphasised = False
        self.message.stop_symbol = None
        self._show(self.message)

    def show_level_adjustment(self, key: str) -> None:
        """`audio_setup.<key>`, with the two large buttons moving the noise (SPEC.md 10.7).

        A text screen rather than the drawn-button control: the approved wording names the
        buttons in its own sentences ("Left button: quieter"), and drawing them as well would
        say it twice. The buttons are read exactly as on the pressure adjustment.
        """
        self.message.text = self.text["audio_setup"][key]
        self.message.emphasised = False
        self.message.stop_symbol = None
        self._show(self.message, adjusting=True)

    def show_audio_setup(self, key: str) -> None:
        """`audio_setup.<key>` as a plain text screen, such as `settled`."""
        self.message.text = self.text["audio_setup"][key]
        self.message.emphasised = False
        self.message.stop_symbol = None
        self._show(self.message)

    def show_emergency_stop(self) -> None:
        """What the participant is left looking at after a stop (SPEC.md 13)."""
        self.show_message(EMERGENCY_STOP_SCREEN)

    def show_adjustment(self, target_key: str, paired: bool = False) -> None:
        """The adjustment screen: what to set, above how the buttons work (SPEC.md 9, 10.3).

        `target_key` names an entry in `adjust_targets`, which is always one of the anchors the
        scale labels -- a participant is asked for a sensation the scale names, never for a
        position on a line. `paired` is the channel match, whose two alternating touches are
        named on screen; `emphasise_adjustment` marks the one playing.
        """
        target = self.text["adjust_targets"][target_key]
        labels = self.text["choices"][PAIR_LABELS]
        pair = (labels[SIDES[0]], labels[SIDES[1]]) if paired else None
        self.control.present(target, self.text["participant_controls"]["adjust"], pair)
        self._show(self.control, adjusting=True)

    def emphasise_adjustment(self, index: int | None) -> None:
        """On a paired adjustment, which touch is playing: 0 the first, 1 the second, None
        neither."""
        self.control.emphasise(index)

    def show_preference(self) -> None:
        """The preference selection (SPEC.md 9 step 6): move between patterns, then choose.

        The buttons are read as on the adjustment -- `adjust_pressed` moves between patterns
        and `adjust_confirmed` chooses -- because the shape is the same: a press moves
        something the participant then commits to (UI_PRINCIPLES.md 5.12). Which pattern is
        playing is felt, never shown: a name or a number on screen would be a label.
        """
        controls = self.text["participant_controls"]["preference"]
        self.control.present(controls["intro"], controls)
        self._show(self.control, adjusting=True)

    def show_choice(self, key: str) -> None:
        """Present `choices.<key>` with both buttons drawn, accepting nothing yet.

        The protocol then calls `emphasise_choice` around each stimulus and `accept_choice`
        when the pair is finished. Splitting them is what keeps a press during the first
        stimulus from being read as an answer to a comparison the participant has not heard the
        second half of.
        """
        self.choice.present(self.text["choices"][key])
        self._show(self.choice, choosing=True)

    def emphasise_choice(self, side: str | None) -> None:
        """Mark the button whose stimulus is playing now; `None` clears it."""
        self.choice.emphasise(side)

    def accept_choice(self) -> None:
        """From here the next press is the response (SPEC.md 10.8)."""
        self.choice.accept()

    def show_warning_cue(self) -> None:
        self._show(self.cue)
        self.warning_cue_shown.emit()

    def show_vas(self, scale: str) -> None:
        """Present `vas.<scale>` and start its reaction-time clock."""
        self.vas.show_scale(scale, self.text["vas"][scale])
        self._show(self.vas)

    def show_vas_training(self, scale: str, accepting: bool) -> None:
        """The VAS training for `scale` (SPEC.md 10.6): the scale as it is rated.

        While the experimenter explains the anchors and proportionality aloud, it is the scale
        with `training_listen` below it, and no button but the emergency stop does anything.
        Once they have (`accepting`), it is a practice rating with `training.<scale>` in the
        same place, and ▶ with the marker shown emits `vas_training_confirmed` with the
        practice response -- never `confirmed`.
        """
        if accepting:
            self.vas.show_practice(scale, self.text["vas"][scale], self.text["training"][scale])
        else:
            self.vas.show_explanation(
                scale, self.text["vas"][scale], self.text["training_listen"]
            )
        self._show(self.vas)

    def _show(self, screen: QWidget, adjusting: bool = False, choosing: bool = False) -> None:
        # Set here rather than in the caller so that leaving either interactive screen by any
        # route -- including a blank shown by an emergency stop -- stops the window reading
        # buttons for it.
        self._adjusting = adjusting
        self._choosing = choosing
        self.stack.setCurrentWidget(screen)
        # The screens draw themselves from their own attributes, and switching to the widget
        # already current paints nothing: one message replacing another stayed on the old text
        # in the first lab run (docs/LOG.md N7.F5).
        screen.update()
        # The VAS reads its own keys; every other screen leaves the window holding focus so the
        # emergency stop still works.
        (screen if screen is self.vas else self).setFocus()

    # -- input -------------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self.last_press_real_s = self.clock.real_elapsed_s()
        action = self._action(event)
        if action is Action.EMERGENCY_STOP:
            # The R400's stop button auto-repeats when held (docs/LOG.md N7.F1). The first press
            # has already zeroed the garment, and each repeat would log another stop.
            if not event.isAutoRepeat():
                self.emergency_stop.emit()
        elif (
            action is Action.CONFIRM
            and not self._adjusting
            and not event.isAutoRepeat()
            and self.stack.currentWidget() is self.message
        ):
            # Only a screen that asks for ▶ -- its approved wording spells the symbol -- takes a
            # press, so only its presses start the lockout or are ignored by it. On a blank or
            # standby screen nobody is listening, and a press there is nothing to log.
            if self._message_asks_for_confirm() and self.confirm_would_carry_over():
                self.confirm_carried_over.emit()
            else:
                if self._message_asks_for_confirm():
                    self._confirm_accepted()
                self.message_confirmed.emit()
        elif self._choosing and not event.isAutoRepeat():
            # Auto-repeat cannot make a second choice: the screen stops accepting on the first
            # press, and a held button is one press however long it is held.
            if action is Action.DECREASE:
                self.choice.press("left")
            elif action is Action.INCREASE:
                self.choice.press("right")
            # A confirm press has nothing to confirm here (UI_PRINCIPLES.md 5.12) and is
            # swallowed, so the play button cannot commit a choice that was never made.
        elif self._adjusting and not event.isAutoRepeat():
            # Auto-repeat is the operating system's idea of a held key. The adjustment reads the
            # hold itself, from the interval between the down and the up (SPEC.md 10.3), so a
            # repeat here would be a second press that never happened.
            if action is Action.CONFIRM:
                # Carried over, it would confirm the level the adjustment started at as the
                # participant's answer.
                if self.confirm_would_carry_over():
                    self.confirm_carried_over.emit()
                else:
                    self._confirm_accepted()
                    self.adjust_confirmed.emit()
            elif action is not None:
                self.control.hold("left" if action is Action.DECREASE else "right")
                self.adjust_pressed.emit(action.value, event.timestamp())
        # Everything else is swallowed rather than passed on: off the VAS there is nothing a
        # press can mean, and Qt would close the window on `escape`, one of ▶'s keys (SPEC.md
        # 10.1).
        event.accept()

    def confirm_lockout_remaining_s(self) -> float:
        """Session seconds until a play-button press would be taken as meant for the screen
        now up rather than carried over from the one before (docs/LOG.md N7.U15). The lockout
        is on the clock's elapsed time, not real time as the hand's own durations are: in a
        session the two are the same, and in real time every accelerated validator run would
        wait half a second at each ▶ that follows another."""
        if self._confirm_accepted_s is None:
            return 0.0
        return self._confirm_accepted_s + self._confirm_lockout_s - self.clock.elapsed_s()

    def confirm_would_carry_over(self) -> bool:
        """Whether a play-button press now would be a double tap or a bounce."""
        return self.confirm_lockout_remaining_s() > 0

    def _message_asks_for_confirm(self) -> bool:
        return self.responder.symbol_for(Action.CONFIRM) in self.message.text

    def _confirm_accepted(self, *_response) -> None:
        self._confirm_accepted_s = self.clock.elapsed_s()

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        """An on-screen button held as the window hides -- the shared window's flags changing
        around a dialog hide it for a moment -- loses its mouse release, and a hold with no end
        would ramp the pressure on. So its release is delivered now, at the time held so far,
        as the VAS ends its hold on a hide (spec review of N7.F12e4)."""
        for made in self.response_buttons.values():
            if made.held is not None:
                stamp = made.release_stamp()
                made.held = None
                made.setDown(False)
                QApplication.sendEvent(self.key_target(), remote_key_event(
                    QEvent.KeyRelease, QT_KEYS[made.key], False, stamp))
        super().hideEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        action = self._action(event)
        if (
            self._adjusting
            and not event.isAutoRepeat()
            and action in (Action.DECREASE, Action.INCREASE)
        ):
            self.control.release("left" if action is Action.DECREASE else "right")
            self.adjust_released.emit(action.value, event.timestamp())
        event.accept()

    def _action(self, event) -> Action | None:
        name = self._names.get(Qt.Key(event.key()))
        if name is None or self.responder.is_ignored(name):
            return None
        return self.responder.action_for(name)

    def is_remote_key(self, event) -> bool:
        """A key the response device emits, bound or deliberately ignored (SPEC.md 10.1)."""
        name = self._names.get(Qt.Key(event.key()))
        if name is None:
            return False
        return name in self.responder.keys or self.responder.is_ignored(name)

    def key_target(self) -> QWidget:
        """Where a remote key lands: the VAS reads its own keys, the window the rest."""
        return self.vas if self.stack.currentWidget() is self.vas else self

    def deliver_remote_key(self, name: str, released: bool, repeat: bool, time_ms: int) -> None:
        """One of the remote's key reports, read by Raw Input (`tatp.remote_keys`), as a press.

        Posted rather than sent: this is called from inside the native message handling. Marked
        as the remote's, so the router lets it through (`REMOTE_KEY_MARK`).
        """
        if not shiboken6.isValid(self) or not self.isVisible():
            return
        kind = QEvent.KeyRelease if released else QEvent.KeyPress
        QApplication.postEvent(
            self.key_target(), remote_key_event(kind, QT_KEYS[name], repeat, time_ms)
        )


# Widgets the experimenter types into. Under any_keyboard, a key reaching one of these is the
# experimenter typing, not the participant pressing -- the remote's emergency stop is the full
# stop, which is also typed.
TEXT_ENTRY_WIDGETS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)
# Widgets that act on the arrows, Return and Esc themselves (code review of N7.F12e4). Under
# any_keyboard a key reaching one of these, or any widget in a dialog or a popup, is the
# experimenter's: Return accepting a dialog is not ▶, and an arrow in a list does not move the
# participant's marker. The stop is still forwarded from them: no dialog uses the full stop, and
# a stop is never to be lost.
KEY_USING_WIDGETS = (QComboBox, QAbstractItemView, QAbstractSlider, QMenu)


def uses_keys(widget: QWidget) -> bool:
    window = widget.window()
    return (
        isinstance(widget, KEY_USING_WIDGETS)
        or isinstance(window, QDialog)
        or window.windowType() == Qt.Popup
    )

# Set in a key event's native modifiers to mark it as the remote's own, delivered to the
# participant: from its raw report, or forwarded by the router. Bit 31, which Windows' native
# modifiers (Shift, Ctrl, Alt, the Windows key, Caps and Num Lock) never use.
REMOTE_KEY_MARK = 0x80000000


def remote_key_event(kind: QEvent.Type, key: Qt.Key, repeat: bool, time_ms: int) -> QKeyEvent:
    """A key event marked as the remote's, stamped when the button moved. The adjustment times
    a press from these stamps (tatp.touchcal.PressTiming)."""
    event = QKeyEvent(kind, key, Qt.NoModifier, 0, 0, REMOTE_KEY_MARK, "", repeat, 1)
    event.setTimestamp(time_ms)
    return event


class RemoteKeyRouter(QObject):
    """Delivers the response device's keys to the participant window, whichever has focus.

    The remote is a keyboard as far as the operating system is concerned, so its presses go to
    the active window -- and the experimenter makes their own window active every time they
    click Next step. Without this, the participant's next rating, and their emergency stop,
    would land on the experimenter's screen and do nothing (SPEC.md 10.1, 13).

    Installed on the application by the `Rig`, with the session's key source
    (`tatp.remote_keys`). What it does depends on whether the source can tell keyboards apart:

    - **It can** (`raw_input`, the lab): the remote's presses are read from its raw reports and
      reach the participant marked as its own (`ParticipantWindow.deliver_remote_key`),
      whatever has focus, and its ordinary key events never arrive. Every other key event is
      another keyboard's: kept from the participant window, and left to reach anything else as
      typing. The experimenter types full stops and presses Esc freely, and the participant's
      stop always stops (open item L15).
    - **It cannot** (`any_keyboard`): every keyboard is the remote, and its keys are forwarded
      to the participant, except a key typed into an experimenter text field, which is taken as
      the experimenter writing a note or a distance (docs/LOG.md N7.I1). A participant's stop
      pressed while the experimenter is typing then reaches the field. Nor are the other
      buttons' keys forwarded from a dialog, a popup, a list or a combo box, which use them
      (`uses_keys`); the stop still is. So on one screen, with one person playing both parts
      (a MacBook, N7.F12e4), keys pressed over the experimenter window's own surface -- after
      clicking Next step, say -- still reach the participant.
    """

    def __init__(self, participant: ParticipantWindow, source, parent: QObject | None = None):
        super().__init__(parent)
        self.participant = participant
        self.source = source

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt's name
        if event.type() not in (QEvent.KeyPress, QEvent.KeyRelease):
            return False
        participant = self.participant
        # Parented to its window, so it dies with it; this guards the moment in between, when
        # the window's C++ object is gone but a queued event still reaches the filter.
        if not shiboken6.isValid(participant):
            return False
        if (
            not isinstance(watched, QWidget)
            or event.nativeModifiers() & REMOTE_KEY_MARK
            or not participant.is_remote_key(event)
        ):
            return False
        at_participant = isinstance(watched.window(), ParticipantWindow)
        if self.source.distinguishes:
            # Not the remote's, which arrive marked: another keyboard's. Kept from the
            # participant window, and left to reach anything else as typing.
            return at_participant
        if at_participant or not participant.isVisible():
            return False
        if isinstance(watched, TEXT_ENTRY_WIDGETS):
            return False
        if participant._action(event) is not Action.EMERGENCY_STOP and uses_keys(watched):
            return False
        # The native codes go with it, as the remote's own event would carry them.
        forwarded = QKeyEvent(
            event.type(),
            event.key(),
            event.modifiers(),
            event.nativeScanCode(),
            event.nativeVirtualKey(),
            event.nativeModifiers() | REMOTE_KEY_MARK,
            event.text(),
            event.isAutoRepeat(),
            event.count(),
        )
        # A press can start in one window and end in the other, so the stamps go too.
        forwarded.setTimestamp(event.timestamp())
        QApplication.sendEvent(participant.key_target(), forwarded)
        return True
