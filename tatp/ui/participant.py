"""The participant window. SPEC.md 10.

One window holding four screens: a block of centred text, the visual warning cue that precedes
every stimulus (SPEC.md 10.5), the VAS, and a two-alternative choice with its buttons drawn
(SPEC.md 10.8). Which of them is showing is the whole of the window's state.

It carries no wording of its own -- every string is looked up in
`config/text/participant_{sv,en}.yaml` by key (SPEC.md 10.4), so a missing key raises where the
screen was asked for rather than showing a participant a blank.

**Input.** The emergency stop must work on every screen, not only while a rating is on display
(SPEC.md 13), so the window handles keys whenever the VAS is not the current screen and
swallows everything else -- including `escape`, which the play button emits and which Qt would
otherwise read as "close this window" (SPEC.md 10.1).

Two screens read more than the emergency stop. The adjustment screen: the pressure adjustment
of SPEC.md 10.3 is press-and-hold, so both the down and the up of every button matter and the
window emits them as they happen. And the choice screen, where the press itself is the response
(SPEC.md 10.8). Neither knows what a press means -- what a button does to the pressure, and what
a choice is a choice between, are `tatp/touchcal.py`, so the participant window stays a display
with no protocol in it.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from tatp.clock import Clock
from tatp.config import Config
from tatp.responder import Action, Responder
from tatp.ui.vas import (
    BACKGROUND,
    FOREGROUND,
    QT_KEYS,
    QUESTION_POINT_SIZE,
    QUESTION_Y_FRACTION,
    SIDE_MARGIN_FRACTION,
    VasWidget,
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

MESSAGE_POINT_SIZE = 26
CUE_RADIUS_FRACTION = 0.09

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


class _MessageScreen(QWidget):
    """One block of text on the neutral background. Empty text is a blank screen.

    Horizontally centred, but **top-aligned at the same fraction as the VAS question** and
    inside the same side margins, so the first line sits where the participant is already
    looking whatever screen preceded it (UI_PRINCIPLES.md 5.5). Vertically centring instead
    moves the text with every change of message length, which over roughly 150 rating cycles
    is a search on every one of them.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.text = ""
        # Weight rather than wording is what marks the stop screen out from a rest screen
        # (UI_PRINCIPLES.md 5.6). Not colour: an alarming screen is the wrong thing to show
        # someone who has just pressed the button because something was unpleasant.
        self.emphasised = False
        # The stop button's printed symbol, on the stop rehearsal only (SPEC.md 10.9).
        self.stop_symbol: str | None = None

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
        painter.drawText(box, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self.text)
        if self.stop_symbol is not None:
            painter.setRenderHint(QPainter.Antialiasing)
            _draw_symbol_button(painter, self, _stop_button_rect(self), self.stop_symbol)
        painter.end()


class _CueScreen(QWidget):
    """The visual warning cue: a filled disc, centred, on an otherwise empty screen.

    Deliberately wordless. A cue that has to be read is not a cue, and any wording here would be
    participant-facing text outside `config/text/` (SPEC.md 10.4).
    """

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), BACKGROUND)
        painter.setBrush(FOREGROUND)
        painter.setPen(Qt.NoPen)
        radius = min(self.width(), self.height()) * CUE_RADIUS_FRACTION
        painter.drawEllipse(self.rect().center(), int(radius), int(radius))
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
        QTimer.singleShot(self._feedback_ms, self._begin_gap)

    def _begin_gap(self) -> None:
        self.blank = True
        self.update()
        QTimer.singleShot(self._gap_ms, self.gap_elapsed.emit)

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
    """

    def __init__(self, responder: Responder, parent: QWidget | None = None):
        super().__init__(parent)
        self.responder = responder
        self.target = ""
        self.labels: dict[str, str] = {}
        self.confirm = ""
        self.held: set[str] = set()

    def present(self, opening: str, controls: dict) -> None:
        """`opening` goes above the buttons; `controls` is one `participant_controls` entry."""
        self.target = opening
        self.labels = {side: controls[side] for side in SIDES}
        self.confirm = controls["confirm"]
        self.held.clear()
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
        painter.drawText(box, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self.confirm)
        painter.end()


def _draw_top_text(painter: QPainter, widget: QWidget, text: str) -> None:
    """Text top-aligned where every participant screen starts reading (UI_PRINCIPLES.md 5.5)."""
    font = QFont(widget.font())
    font.setPointSize(QUESTION_POINT_SIZE)
    painter.setFont(font)
    painter.setPen(FOREGROUND)
    margin = int(widget.width() * SIDE_MARGIN_FRACTION)
    top = int(widget.height() * QUESTION_Y_FRACTION)
    box = widget.rect().adjusted(margin, top, -margin, 0)
    painter.drawText(box, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, text)


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


def _draw_symbol_button(painter: QPainter, widget: QWidget, rect: QRect, symbol: str) -> None:
    """A button outline carrying its printed symbol, with no label: the text above names it."""
    painter.setPen(QPen(FOREGROUND, BUTTON_LINE_WIDTH_PX))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect, BUTTON_RADIUS_PX, BUTTON_RADIUS_PX)
    symbol_font = QFont(widget.font())
    symbol_font.setPointSize(BUTTON_SYMBOL_POINT_SIZE)
    # Shrunk to fit if it is wider than the button: a symbol cut off at both edges stops
    # being the symbol, and while it is a placeholder (local item L12) it must read as one.
    room = rect.width() - 2 * BUTTON_RADIUS_PX
    width = QFontMetrics(symbol_font).horizontalAdvance(symbol)
    if width > room:
        symbol_font.setPointSizeF(BUTTON_SYMBOL_POINT_SIZE * room / width)
    painter.setFont(symbol_font)
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
    painter.drawText(label_box, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, label)


class ParticipantWindow(QWidget):
    """The participant's screen. Everything shown to a participant goes through here."""

    confirmed = Signal(object)  # a VasResponse
    emergency_stop = Signal()
    pressed_without_marker = Signal()
    # The adjustment screen only (SPEC.md 10.3). Each carries the responder action's value.
    adjust_pressed = Signal(str)
    adjust_released = Signal(str)
    adjust_confirmed = Signal()
    # The choice screen only (SPEC.md 10.8). `chosen` carries "left" or "right".
    chosen = Signal(str)
    choice_gap_elapsed = Signal()
    pressed_before_accepting = Signal()
    # The play button on a message screen that says "Press ▶ to continue" (SPEC.md 10.9) or
    # asks for the self-start press (SPEC.md 12.3). Emitted on any message screen; what it
    # means is up to whoever is listening, and nothing listens on a screen that asks nothing.
    message_confirmed = Signal()
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

        self.message = _MessageScreen()
        self.cue = _CueScreen()
        self.vas = VasWidget(config.study1["vas"], responder, clock)
        self.vas.confirmed.connect(self.confirmed)
        self.vas.emergency_stop.connect(self.emergency_stop)
        self.vas.pressed_without_marker.connect(self.pressed_without_marker)
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
        layout.addWidget(self.stack)

        self._adjusting = False
        self._choosing = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.show_blank()

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

    def show_adjustment(self, target_key: str) -> None:
        """The adjustment screen: what to set, above how the buttons work (SPEC.md 9, 10.3).

        `target_key` names an entry in `adjust_targets`, which is always one of the anchors the
        scale labels -- a participant is asked for a sensation the scale names, never for a
        position on a line.
        """
        target = self.text["adjust_targets"][target_key]
        self.control.present(target, self.text["participant_controls"]["adjust"])
        self._show(self.control, adjusting=True)

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

    def _show(self, screen: QWidget, adjusting: bool = False, choosing: bool = False) -> None:
        # Set here rather than in the caller so that leaving either interactive screen by any
        # route -- including a blank shown by an emergency stop -- stops the window reading
        # buttons for it.
        self._adjusting = adjusting
        self._choosing = choosing
        self.stack.setCurrentWidget(screen)
        # The VAS reads its own keys; every other screen leaves the window holding focus so the
        # emergency stop still works.
        (screen if screen is self.vas else self).setFocus()

    # -- input -------------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self.last_press_real_s = self.clock.real_elapsed_s()
        action = self._action(event)
        if action is Action.EMERGENCY_STOP:
            self.emergency_stop.emit()
        elif (
            action is Action.CONFIRM
            and not self._adjusting
            and not event.isAutoRepeat()
            and self.stack.currentWidget() is self.message
        ):
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
                self.adjust_confirmed.emit()
            elif action is not None:
                self.control.hold("left" if action is Action.DECREASE else "right")
                self.adjust_pressed.emit(action.value)
        # Everything else is swallowed rather than passed on: off the VAS there is nothing a
        # press can mean, and Qt would close the window on `escape` (SPEC.md 10.1).
        event.accept()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        action = self._action(event)
        if (
            self._adjusting
            and not event.isAutoRepeat()
            and action in (Action.DECREASE, Action.INCREASE)
        ):
            self.control.release("left" if action is Action.DECREASE else "right")
            self.adjust_released.emit(action.value)
        event.accept()

    def _action(self, event) -> Action | None:
        name = self._names.get(Qt.Key(event.key()))
        if name is None or self.responder.is_ignored(name):
            return None
        return self.responder.action_for(name)
