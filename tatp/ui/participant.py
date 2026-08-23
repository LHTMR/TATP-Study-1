"""The participant window. SPEC.md 10.

One window holding three screens: a block of centred text, the visual warning cue that precedes
every stimulus (SPEC.md 10.5), and the VAS. Which of them is showing is the whole of the
window's state.

It carries no wording of its own -- every string is looked up in
`config/text/participant_{sv,en}.yaml` by key (SPEC.md 10.4), so a missing key raises where the
screen was asked for rather than showing a participant a blank.

**Input.** The emergency stop must work on every screen, not only while a rating is on display
(SPEC.md 13), so the window handles keys whenever the VAS is not the current screen and
swallows everything else -- including `escape`, which the play button emits and which Qt would
otherwise read as "close this window" (SPEC.md 10.1).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from tatp.clock import Clock
from tatp.config import Config
from tatp.responder import Action, Responder
from tatp.ui.vas import BACKGROUND, FOREGROUND, QT_KEYS, VasWidget

# How the window draws itself. Not study parameters (SPEC.md 4.2 lists timings, forces,
# pressures, thresholds, rates and strings) -- the reference screenshots are what pin these
# (SPEC.md 17.4).
MESSAGE_POINT_SIZE = 26
MESSAGE_MARGIN_PX = 80
CUE_RADIUS_FRACTION = 0.09


class _MessageScreen(QWidget):
    """One block of centred text on the neutral background. Empty text is a blank screen."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.text = ""

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        painter.setPen(FOREGROUND)
        font = QFont(self.font())
        font.setPointSize(MESSAGE_POINT_SIZE)
        painter.setFont(font)
        box = self.rect().adjusted(
            MESSAGE_MARGIN_PX, MESSAGE_MARGIN_PX, -MESSAGE_MARGIN_PX, -MESSAGE_MARGIN_PX
        )
        painter.drawText(box, Qt.AlignCenter | Qt.TextWordWrap, self.text)
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


class ParticipantWindow(QWidget):
    """The participant's screen. Everything shown to a participant goes through here."""

    confirmed = Signal(object)  # a VasResponse
    emergency_stop = Signal()
    pressed_without_marker = Signal()

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
        self._names = {key: name for name, key in QT_KEYS.items()}

        self.message = _MessageScreen()
        self.cue = _CueScreen()
        self.vas = VasWidget(config.study1["vas"], responder, clock)
        self.vas.confirmed.connect(self.confirmed)
        self.vas.emergency_stop.connect(self.emergency_stop)
        self.vas.pressed_without_marker.connect(self.pressed_without_marker)

        self.stack = QStackedWidget(self)
        for screen in (self.message, self.cue, self.vas):
            self.stack.addWidget(screen)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

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
        self._show(self.message)

    def show_blank(self) -> None:
        """Nothing at all -- what the participant sees while a stimulus is being delivered."""
        self.message.text = ""
        self._show(self.message)

    def show_warning_cue(self) -> None:
        self._show(self.cue)

    def show_vas(self, scale: str) -> None:
        """Present `vas.<scale>` and start its reaction-time clock."""
        self.vas.show_scale(scale, self.text["vas"][scale])
        self._show(self.vas)

    def _show(self, screen: QWidget) -> None:
        self.stack.setCurrentWidget(screen)
        # The VAS reads its own keys; every other screen leaves the window holding focus so the
        # emergency stop still works.
        (screen if screen is self.vas else self).setFocus()

    # -- input -------------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        name = self._names.get(Qt.Key(event.key()))
        if name is not None and self.responder.action_for(name) is Action.EMERGENCY_STOP:
            self.emergency_stop.emit()
        # Everything else is swallowed rather than passed on: off the VAS there is nothing a
        # press can mean, and Qt would close the window on `escape` (SPEC.md 10.1).
        event.accept()
