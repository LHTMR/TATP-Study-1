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

from PySide6.QtCore import QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
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
# The line sits at a fixed fraction on every scale (UI_PRINCIPLES.md 1.6) and the question is
# close enough above it to be read as one object with it. `QUESTION_Y_FRACTION` is shared with
# the message screens, which top-align their text at the same fraction, so the first line a
# participant reads never moves between screens (UI_PRINCIPLES.md 5.5).
LINE_Y_FRACTION = 0.52
QUESTION_Y_FRACTION = 0.30
QUESTION_POINT_SIZE = 26
# The RSQ scales ask one framing question about a statement that is what the participant
# actually rates (SPEC.md 10.6). The statement is therefore the larger of the two and the
# question is set down to this, so the thing being rated is the thing that reads first
# (UI_PRINCIPLES.md 5.3). Scales with no statement keep the question at QUESTION_POINT_SIZE.
INTRODUCTION_POINT_SIZE = 17
STATEMENT_GAP_PX = 26
# Clear space below the whole text block. The line cannot move down to make room -- it sits at
# LINE_Y_FRACTION on every scale (UI_PRINCIPLES.md 1.6) -- so this is checked rather than
# applied: a text block that reaches into it needs shorter wording or a smaller size, and
# `heading_clearance` is where that is caught.
TEXT_TO_LINE_GAP_PX = 48
ANCHOR_POINT_SIZE = 18
ANCHOR_GAP_PX = 18
ANCHOR_LABEL_GAP_PX = 16  # clear space required between two anchor labels sharing a row
TICK_LABEL_GAP_PX = 6


@dataclass(frozen=True)
class TickStyle:
    """How an anchor tick crosses the line (UI_PRINCIPLES.md 1.4).

    A tick straddles the line rather than hanging beneath it: one that only descends reads as a
    bracket around the label under it and competes with the label rows instead of belonging to
    the line. It is subordinate to the line -- `width_px` is thinner than `LINE_WIDTH_PX`,
    because the line is the scale and the tick is an annotation on it.

    **This is a variant mechanism awaiting one decision and nothing more.** The straddle is
    settled; how far it rises and how heavy it is are a judgement about the rendered pixels, so
    `tools/tick_variants.py` renders the three for S to choose between. When S chooses, collapse
    this to plain constants -- a widget attribute nobody sets is a config option nothing reads.
    """

    rise_px: int  # above the line
    drop_px: int  # below the line, when the label sits directly underneath
    width_px: int


TICK_STYLES = {
    "shallow": TickStyle(rise_px=4, drop_px=8, width_px=1),
    "even": TickStyle(rise_px=6, drop_px=8, width_px=1),
    "tall": TickStyle(rise_px=8, drop_px=10, width_px=2),
}
DEFAULT_TICK_STYLE = "even"

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
        self.tick_style = TICK_STYLES[DEFAULT_TICK_STYLE]
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

    def _anchor_layout(self, metrics) -> list[tuple[str, float, int, float]]:
        """Each anchor label as (text, left edge, row, tick x), stacking labels that collide.

        A label is centred under its own percentage, which is the whole point of an anchor --
        moving it sideways to make room would put "just noticeable" somewhere other than 10 %.
        So when two labels overlap, the second one drops to a row underneath instead.

        This is not a hypothetical. The `intensity` scale anchors 0/10/90/100 % and the
        `pain` scale anchors 0/10 %, and at those spacings the Swedish labels overlap into
        illegibility at every window size the lab will use -- which the SPEC.md 17.4
        screenshots are what found.

        **The tick x is what makes stacking safe, and is why this returns it.** A row on its
        own relabels the scale: with the labels alone, English `intensity` row 0 reads "no
        sensation at all ... just uncomfortable", which is a complete scale with the wrong top
        anchor. `paintEvent` draws a tick from the line down to each label's own row, so a
        label is tied to its percentage however far it has been clamped or dropped
        (UI_PRINCIPLES.md 1.3).
        """
        placed: list[tuple[str, float, int, float]] = []
        row_right_edges: list[float] = []
        for anchor in sorted(self.anchors, key=lambda a: float(a["pct"])):
            label = str(anchor["label"])
            width = metrics.horizontalAdvance(label)
            centre = self._x_for(float(anchor["pct"]))
            # Clamped so an end label stays on screen; the ends are where clamping bites.
            left = min(max(centre - width / 2, 0.0), float(self.width() - width))
            row = next(
                (
                    index
                    for index, edge in enumerate(row_right_edges)
                    if left >= edge + ANCHOR_LABEL_GAP_PX
                ),
                len(row_right_edges),
            )
            if row == len(row_right_edges):
                row_right_edges.append(0.0)
            row_right_edges[row] = left + width
            placed.append((label, left, row, centre))
        return placed

    def _draw_heading(self, painter: QPainter | None, line_y: float) -> float:
        """Lay the heading out, and draw it if a painter is given.

        Where a scale carries a statement, that statement is what is being rated and the
        question only frames it, so the question is set smaller and the statement takes the
        question size (UI_PRINCIPLES.md 5.3). Both are top-aligned from the same fraction as
        every message screen, so the first line a participant reads never moves.

        Returns the y the block ends at, which is what `heading_clearance` measures against the
        line. Measuring and drawing are the same code deliberately: a clearance computed by a
        second implementation would be a check on that implementation, not on the screen.
        """
        top = float(self.height() * QUESTION_Y_FRACTION)
        margin = int(self.width() * SIDE_MARGIN_FRACTION)
        flags = Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap
        width = self.width() - 2 * margin

        y = top
        for index, (text, point_size) in enumerate(self.heading_blocks()):
            font = QFont(self.font())
            font.setPointSize(point_size)
            box = QRect(margin, int(y), width, int(line_y - y))
            drawn = QFontMetrics(font).boundingRect(box, flags, text)
            if painter is not None:
                painter.setFont(font)
                painter.drawText(box, flags, text)
            y = drawn.bottom() + (STATEMENT_GAP_PX if index == 0 else 0)
        return y

    def heading_blocks(self) -> list[tuple[str, int]]:
        """The heading as text and point size, largest last where there are two."""
        if not self.statement:
            return [(self.question, QUESTION_POINT_SIZE)]
        return [
            (self.question, INTRODUCTION_POINT_SIZE),
            (self.statement, QUESTION_POINT_SIZE),
        ]

    def heading_clearance(self) -> float:
        """Pixels between the bottom of the text and the line.

        The line cannot be pushed down to make room -- it sits at LINE_Y_FRACTION on every scale
        (UI_PRINCIPLES.md 1.6) -- so a heading that crowds it needs shorter wording or a smaller
        size. `tests/test_vas.py` holds this to TEXT_TO_LINE_GAP_PX for every scale in both
        languages, at the lab window size. It is a test rather than an assertion in `paintEvent`
        because Qt prints an exception raised inside a paint handler and carries on, which would
        make a failing layout a line of stderr nobody reads.
        """
        line_y = self.height() * LINE_Y_FRACTION
        return line_y - self._draw_heading(None, line_y)

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), BACKGROUND)
        painter.setPen(FOREGROUND)

        line_y = self.height() * LINE_Y_FRACTION
        self._draw_heading(painter, line_y)

        painter.setPen(QPen(FOREGROUND, LINE_WIDTH_PX))
        painter.drawLine(
            int(self._x_for(MIN_PCT)), int(line_y), int(self._x_for(MAX_PCT)), int(line_y)
        )

        # A tick at every labelled anchor and nowhere else, and no numbers anywhere
        # (SPEC.md 10.2). It straddles the line, and below it runs down to its own label's row,
        # so it is also the leader that ties a stacked label to its percentage.
        style = self.tick_style
        # The marker's tip sits MARKER_GAP_PX above the line, so a tick rising into that gap
        # would be touched by the marker whenever a response lands on an anchor.
        assert style.rise_px < MARKER_GAP_PX, (
            f"a tick rising {style.rise_px} px reaches the marker, which sits "
            f"{MARKER_GAP_PX} px above the line"
        )
        anchor_font = QFont(self.font())
        anchor_font.setPointSize(ANCHOR_POINT_SIZE)
        painter.setFont(anchor_font)
        metrics = painter.fontMetrics()
        for label, left, row, tick_x in self._anchor_layout(metrics):
            tick_bottom = line_y + ANCHOR_GAP_PX + row * metrics.height()
            painter.setPen(QPen(FOREGROUND, style.width_px))
            drawn_to = tick_bottom if row else line_y + style.drop_px
            painter.drawLine(
                int(tick_x), int(line_y - style.rise_px), int(tick_x), int(drawn_to)
            )
            baseline = tick_bottom + TICK_LABEL_GAP_PX + metrics.ascent()
            painter.drawText(int(left), int(baseline), label)

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
