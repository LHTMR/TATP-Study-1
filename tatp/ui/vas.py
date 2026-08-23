"""The visual analogue scale. SPEC.md 10.2, 10.6.

`VasState` is the whole of the behaviour and imports no Qt, so the rules SPEC.md 10.2 sets out
-- the marker hidden until the first press, the side-dependent start position, the recorded
reaction time, first-press side and direction changes -- are tested directly rather than
through a widget.

`VasWidget` draws it and turns key events into calls on the state. It carries no wording: every
string comes from `config/text/participant_{sv,en}.yaml` (SPEC.md 10.4).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from tatp.clock import Clock
from tatp.responder import Action, Responder
from tatp.units import MS_PER_S

# Layout and colour. Not study parameters (SPEC.md 4.2 lists timings, forces, pressures,
# thresholds, rates and strings) -- these are how the widget draws itself, and the reference
# screenshots are what pins them (SPEC.md 17.4).
BACKGROUND = QColor(20, 20, 20)
FOREGROUND = QColor(235, 235, 235)
LINE_WIDTH_PX = 3
MARKER_HALF_WIDTH_PX = 14
MARKER_HEIGHT_PX = 22
MARKER_GAP_PX = 10
SIDE_MARGIN_FRACTION = 0.12
LINE_Y_FRACTION = 0.58
QUESTION_Y_FRACTION = 0.18
QUESTION_POINT_SIZE = 26
ANCHOR_POINT_SIZE = 18
ANCHOR_GAP_PX = 18

# Key names as `config/hardware.yaml` writes them. A configured key that is not here is a
# startup error rather than a key that silently does nothing.
QT_KEYS: dict[str, Qt.Key] = {
    "pageup": Qt.Key_PageUp,
    "pagedown": Qt.Key_PageDown,
    "period": Qt.Key_Period,
    "f5": Qt.Key_F5,
    "escape": Qt.Key_Escape,
}

MIN_PCT = 0.0
MAX_PCT = 100.0


@dataclass(frozen=True)
class VasResponse:
    """One completed rating, in the column names DATA_SCHEMA.md uses."""

    rating_percent: float
    rt_s: float
    first_press_side: str
    direction_changes: int
    cue_iso: str


class VasState:
    """The VAS rules of SPEC.md 10.2, with no Qt and no drawing."""

    def __init__(self, vas_config: dict, clock: Clock):
        self.start_left_pct = float(vas_config["start_pct_after_left_press"])
        self.start_right_pct = float(vas_config["start_pct_after_right_press"])
        self.step_pct = float(vas_config["move_step_pct"])
        self.no_response_warning_s = float(vas_config["no_response_warning_s"])
        self.clock = clock
        self.reset()

    def reset(self) -> None:
        self.visible = False
        self.percent = 0.0
        self.first_press_side = ""
        self.direction_changes = 0
        self.cue_iso = ""
        self._cue_s: float | None = None
        self._last_direction = 0

    def cue(self) -> None:
        """The rating has been asked for. Starts the reaction-time clock (SPEC.md 10.2)."""
        self.reset()
        self.cue_iso = self.clock.wall_iso()
        self._cue_s = self.clock.elapsed_s()

    @property
    def cued(self) -> bool:
        return self._cue_s is not None

    @property
    def waiting_s(self) -> float:
        """Seconds since the rating was cued. The session warns on this, never auto-advances."""
        if self._cue_s is None:
            return 0.0
        return self.clock.elapsed_s() - self._cue_s

    def press(self, action: Action) -> None:
        """One movement press. The first one reveals the marker rather than moving it."""
        if self._cue_s is None:
            raise RuntimeError("the VAS was pressed before it was cued")
        direction = -1 if action is Action.DECREASE else 1
        if not self.visible:
            self.visible = True
            self.percent = self.start_left_pct if direction < 0 else self.start_right_pct
            self.first_press_side = "left" if direction < 0 else "right"
            # The first press has a direction even though it does not move the marker, so
            # pressing the other button next is a genuine reversal and is counted as one.
            self._last_direction = direction
            return
        if direction != self._last_direction:
            self.direction_changes += 1
            self._last_direction = direction
        self.percent = min(max(self.percent + direction * self.step_pct, MIN_PCT), MAX_PCT)

    def confirm(self) -> VasResponse | None:
        """The response, or None if the marker was never shown -- there is nothing to record."""
        if self._cue_s is None or not self.visible:
            return None
        return VasResponse(
            rating_percent=self.percent,
            rt_s=self.clock.elapsed_s() - self._cue_s,
            first_press_side=self.first_press_side,
            direction_changes=self.direction_changes,
            cue_iso=self.cue_iso,
        )


class VasWidget(QWidget):
    """Draws one scale and turns responder keys into presses.

    `confirmed` carries a VasResponse. A confirm with no marker shown emits nothing, because
    there is no response to emit -- the session logs the press from `pressed_without_marker`.
    """

    confirmed = Signal(object)
    emergency_stop = Signal()
    pressed_without_marker = Signal()

    def __init__(
        self,
        vas_config: dict,
        responder: Responder,
        clock: Clock,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        unknown = [key for key in responder.keys if key not in QT_KEYS]
        unknown += [key for key in responder.ignored if key not in QT_KEYS]
        if unknown:
            raise KeyError(f"{sorted(set(unknown))} are not keys this UI knows how to read")
        self._names = {key: name for name, key in QT_KEYS.items()}

        self.state = VasState(vas_config, clock)
        self.responder = responder
        self.scale = ""
        self.question = ""
        self.statement = ""
        self.anchors: list[dict] = []

        self._repeat_delay_ms = int(round(float(vas_config["hold_repeat_delay_s"]) * MS_PER_S))
        self._repeat_interval_ms = int(
            round(float(vas_config["hold_repeat_interval_s"]) * MS_PER_S)
        )
        self._held: Action | None = None
        self._repeat = QTimer(self)
        self._repeat.setSingleShot(True)
        self._repeat.timeout.connect(self._on_repeat)

        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(False)

    def show_scale(self, scale: str, text: dict) -> None:
        """Present one scale. `text` is the `vas.<scale>` block of the participant text file."""
        self.scale = scale
        self.question = text["question"]
        self.statement = text.get("statement", "")
        self.anchors = list(text["anchors"])
        self.state.cue()
        self.update()

    # -- input -------------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        name = self._names.get(Qt.Key(event.key()))
        if name is None or self.responder.is_ignored(name):
            # Swallowed, not passed on. Qt would otherwise close a window on Escape, which the
            # play button emits alongside its real key (SPEC.md 10.1).
            event.accept()
            return
        if event.isAutoRepeat():
            event.accept()
            return
        action = self.responder.action_for(name)
        if action is Action.EMERGENCY_STOP:
            self.emergency_stop.emit()
        elif action is Action.CONFIRM:
            self._confirm()
        elif action in (Action.DECREASE, Action.INCREASE):
            self._held = action
            self.state.press(action)
            self._repeat.start(self._repeat_delay_ms)
            self.update()
        event.accept()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        if event.isAutoRepeat():
            event.accept()
            return
        name = self._names.get(Qt.Key(event.key()))
        if name is not None and self.responder.action_for(name) is self._held:
            self._held = None
            self._repeat.stop()
        event.accept()

    def _on_repeat(self) -> None:
        if self._held is None:
            return
        self.state.press(self._held)
        self.update()
        self._repeat.start(self._repeat_interval_ms)

    def _confirm(self) -> None:
        response = self.state.confirm()
        if response is None:
            self.pressed_without_marker.emit()
            return
        self._held = None
        self._repeat.stop()
        self.confirmed.emit(response)

    # -- drawing -----------------------------------------------------------------------

    def _x_for(self, percent: float) -> float:
        margin = self.width() * SIDE_MARGIN_FRACTION
        return margin + (self.width() - 2 * margin) * percent / MAX_PCT

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), BACKGROUND)
        painter.setPen(QPen(FOREGROUND, LINE_WIDTH_PX))

        question_font = QFont(self.font())
        question_font.setPointSize(QUESTION_POINT_SIZE)
        painter.setFont(question_font)
        top = int(self.height() * QUESTION_Y_FRACTION)
        margin = int(self.width() * SIDE_MARGIN_FRACTION)
        box = self.rect().adjusted(margin, top, -margin, 0)
        heading = self.question
        if self.statement:
            heading = f"{self.question}\n\n{self.statement}"
        painter.drawText(box, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, heading)

        line_y = self.height() * LINE_Y_FRACTION
        painter.drawLine(
            int(self._x_for(MIN_PCT)), int(line_y), int(self._x_for(MAX_PCT)), int(line_y)
        )

        # No numbers and no tick marks beyond the labelled anchors (SPEC.md 10.2).
        anchor_font = QFont(self.font())
        anchor_font.setPointSize(ANCHOR_POINT_SIZE)
        painter.setFont(anchor_font)
        metrics = painter.fontMetrics()
        for anchor in self.anchors:
            label = str(anchor["label"])
            centre = self._x_for(float(anchor["pct"]))
            width = metrics.horizontalAdvance(label)
            left = min(max(centre - width / 2, 0.0), float(self.width() - width))
            painter.drawText(
                int(left), int(line_y + ANCHOR_GAP_PX + metrics.ascent()), label
            )

        if self.state.visible:
            x = self._x_for(self.state.percent)
            tip_y = line_y - MARKER_GAP_PX
            marker = QPolygonF(
                [
                    QPointF(x, tip_y),
                    QPointF(x - MARKER_HALF_WIDTH_PX, tip_y - MARKER_HEIGHT_PX),
                    QPointF(x + MARKER_HALF_WIDTH_PX, tip_y - MARKER_HEIGHT_PX),
                ]
            )
            painter.setBrush(FOREGROUND)
            painter.drawPolygon(marker)
        painter.end()
