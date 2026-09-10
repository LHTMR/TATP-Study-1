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
# Clear space between the text block and the highest thing the scale draws -- a label above the
# line, or the marker's top. The line cannot move down to make room -- it sits at
# LINE_Y_FRACTION on every scale (UI_PRINCIPLES.md 1.6) -- so this is checked rather than
# applied: a text block that reaches into it needs shorter wording or a smaller size, and
# `heading_clearance` is where that is caught.
TEXT_TO_SCALE_GAP_PX = 24
ANCHOR_POINT_SIZE = 18
ANCHOR_GAP_PX = 18
ANCHOR_LABEL_GAP_PX = 16  # clear space required between two anchor labels sharing a row
TICK_LABEL_GAP_PX = 6


# The anchor tick (UI_PRINCIPLES.md 1.4). It straddles the line rather than hanging below it --
# one that only descends reads as a bracket around the label under it -- and it is thinner than
# the line, because the line is the scale and the tick annotates it. The tallest of three
# rendered candidates, chosen by S on 10 Sep 2026. It stays below the marker's tip
# (MARKER_GAP_PX), so a rating landing on an anchor never touches its tick.
TICK_RISE_PX = 8
TICK_DROP_PX = 10
TICK_WIDTH_PX = 2


@dataclass(frozen=True)
class AnchorLayout:
    """Where the anchor labels go.

    `interior_above` is the study's layout (S, 10 Sep 2026) and the only one a session uses.
    End labels sit centred on their ends, below the line, on the row nearest it. Interior
    anchors -- 10 % and 90 % -- sit above the line, raised clear of the marker's whole height so
    a rating near an anchor can never cover its name, with the tick run up to them as a leader.

    `ends_outside` is kept so S can show colleagues the alternative, and is rendered only by
    `make layouts`. Every label is below the line, and each end label hangs outwards so only
    `end_inside_fraction` of it sits inside the line -- which needs a shorter line, or the long
    Swedish end labels run into the screen edge.
    """

    line_margin_fraction: float
    interior_above: bool
    end_inside_fraction: float | None  # None centres an end label on its end


LAYOUTS = {
    "interior_above": AnchorLayout(
        line_margin_fraction=SIDE_MARGIN_FRACTION, interior_above=True, end_inside_fraction=None
    ),
    "ends_outside": AnchorLayout(
        line_margin_fraction=0.16, interior_above=False, end_inside_fraction=0.15
    ),
}
STUDY_LAYOUT = "interior_above"

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
        self.layout = LAYOUTS[STUDY_LAYOUT]
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
        margin = self.width() * self.layout.line_margin_fraction
        return margin + (self.width() - 2 * margin) * percent / MAX_PCT

    def _anchor_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSize(ANCHOR_POINT_SIZE)
        return font

    def _anchor_layout(self, metrics) -> list[tuple[str, float, int, float]]:
        """Each anchor label as (text, left edge, row, tick x).

        Rows count outwards from the line: 0, 1, 2 below it, -1, -2 above. **The two end labels
        always share row 0**, the one nearest the line, so the extremes of the scale read as a
        pair at the same height (S, 10 Sep 2026). Interior anchors never take row 0: they go to
        row -1 in the study layout and row 1 in the alternative, and move further out only if
        they collide with a label already on that row.

        A label is never moved sideways to make room -- that would put "just noticeable"
        somewhere other than 10 %. The labels on the `intensity` and `pain` scales do collide
        at every window size the lab will use, which the SPEC.md 17.4 screenshots found.

        **The tick x is what makes a label off row 0 safe, and is why this returns it.** A row
        of labels on its own relabels the scale -- English `intensity` would read "no sensation
        at all ... just uncomfortable", a complete scale with the wrong top anchor. `paintEvent`
        runs every tick to its own label's row, so each label is tied to its percentage
        (UI_PRINCIPLES.md 1.3).
        """
        placed: list[tuple[str, float, int, float]] = []
        right_edges: dict[int, float] = {}
        inside = self.layout.end_inside_fraction
        for anchor in sorted(self.anchors, key=lambda a: float(a["pct"])):
            label = str(anchor["label"])
            width = metrics.horizontalAdvance(label)
            pct = float(anchor["pct"])
            centre = self._x_for(pct)
            left = centre - width / 2
            if inside is not None and pct == MIN_PCT:
                left = centre - (1 - inside) * width
            elif inside is not None and pct == MAX_PCT:
                left = centre - inside * width
            # Clamped so an end label stays on screen; the ends are where clamping bites.
            left = min(max(left, 0.0), float(self.width() - width))

            if pct in (MIN_PCT, MAX_PCT):
                row, step = 0, 1
            elif self.layout.interior_above:
                row, step = -1, -1
            else:
                row, step = 1, 1
            while left < right_edges.get(row, float("-inf")) + ANCHOR_LABEL_GAP_PX:
                row += step
            right_edges[row] = left + width
            placed.append((label, left, row, centre))
        return placed

    def _label_geometry(self, row: int, metrics, line_y: float) -> tuple[float, float]:
        """The baseline of a label on `row`, and the y its tick runs to.

        Above the line, row -1 sits clear of the marker's whole height (MARKER_GAP_PX plus
        MARKER_HEIGHT_PX), so the marker can never cover an interior anchor's name.
        """
        if row < 0:
            bottom = (
                line_y
                - MARKER_GAP_PX
                - MARKER_HEIGHT_PX
                - 2 * TICK_LABEL_GAP_PX
                + (row + 1) * metrics.height()
            )
            return bottom - metrics.descent(), bottom + TICK_LABEL_GAP_PX
        top = line_y + ANCHOR_GAP_PX + row * metrics.height()
        tick_end = top if row else line_y + TICK_DROP_PX
        return top + TICK_LABEL_GAP_PX + metrics.ascent(), tick_end

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
        """Pixels between the bottom of the text and the highest thing the scale draws.

        That is an interior label above the line where there is one, otherwise the top of the
        marker, which can appear anywhere along the line. The line cannot be pushed down to make
        room -- it sits at LINE_Y_FRACTION on every scale (UI_PRINCIPLES.md 1.6) -- so a heading
        that crowds the scale needs shorter wording or a smaller size. `tests/test_vas.py` holds
        this to TEXT_TO_SCALE_GAP_PX for every scale in both languages, at the lab window size.
        It is a test rather than an assertion in `paintEvent` because Qt prints an exception
        raised inside a paint handler and carries on, which would make a failing layout a line
        of stderr nobody reads.
        """
        line_y = self.height() * LINE_Y_FRACTION
        metrics = QFontMetrics(self._anchor_font())
        tops = [line_y - MARKER_GAP_PX - MARKER_HEIGHT_PX]
        for _, _, row, _ in self._anchor_layout(metrics):
            if row < 0:
                baseline, _ = self._label_geometry(row, metrics, line_y)
                tops.append(baseline - metrics.ascent())
        return min(tops) - self._draw_heading(None, line_y)

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
        # (SPEC.md 10.2). It straddles the line and runs on to its own label's row, so it is
        # also the leader tying a label off row 0 to its percentage.
        anchor_font = self._anchor_font()
        painter.setFont(anchor_font)
        painter.setPen(QPen(FOREGROUND, TICK_WIDTH_PX))
        metrics = QFontMetrics(anchor_font)
        for label, left, row, tick_x in self._anchor_layout(metrics):
            baseline, tick_end = self._label_geometry(row, metrics, line_y)
            tick_start = line_y + TICK_DROP_PX if row < 0 else line_y - TICK_RISE_PX
            painter.drawLine(int(tick_x), int(tick_start), int(tick_x), int(tick_end))
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
