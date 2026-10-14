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
# The VAS training's practice (SPEC.md 10.6) puts its line below the scale it is about,
# top-aligned at this fraction, so the scale above it is drawn exactly as it is rated
# (UI_PRINCIPLES.md 1.6). Set in the question size: it is the one thing on that screen to read.
# `training_clearance` checks it clears the lowest anchor label and the bottom of the screen.
TRAINING_Y_FRACTION = 0.64
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
    """The VAS rules of SPEC.md 10.2, with no Qt and no drawing.

    **A tap and a hold.** Every press is first a tap: it reveals the marker, or moves it one
    step, the moment it goes down. If it is still down `hold_delay_s` later it has become a
    hold, and `tick` moves the marker on continuously at a rate that ramps from
    `hold_rate_initial_pct_s` to `hold_rate_final_pct_s` over `hold_ramp_duration_s` -- the
    shape of the pressure adjustment's control (SPEC.md 10.3, `tatp.touchcal.AdjustmentState`).
    The distance is the ramp's integral in closed form, so it depends on how long the button was
    held and not on how often the timer fired.

    Times are real seconds the caller supplies: the hold is the hand's, not the session's.
    """

    def __init__(self, vas_config: dict, clock: Clock):
        self.start_left_pct = float(vas_config["start_pct_after_left_press"])
        self.start_right_pct = float(vas_config["start_pct_after_right_press"])
        self.step_pct = float(vas_config["move_step_pct"])
        self.hold_delay_s = float(vas_config["hold_delay_s"])
        self.rate_initial_pct_s = float(vas_config["hold_rate_initial_pct_s"])
        self.rate_final_pct_s = float(vas_config["hold_rate_final_pct_s"])
        self.ramp_duration_s = float(vas_config["hold_ramp_duration_s"])
        self.regrip_max_s = float(vas_config["hold_regrip_max_s"])
        self.no_response_warning_s = float(vas_config["no_response_warning_s"])
        # Stage boundary (CLAUDE.md): a ramp of zero length would divide by zero, and a hold
        # that slowed down as it went on is not the accelerating control S asked for.
        assert self.ramp_duration_s > 0, "vas.hold_ramp_duration_s must be positive"
        assert self.rate_final_pct_s >= self.rate_initial_pct_s, (
            "vas.hold_rate_final_pct_s is below vas.hold_rate_initial_pct_s"
        )
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
        self._held: Action | None = None
        self._pressed_s = 0.0
        self._held_travel_s = 0.0
        self._tap_percent = 0.0
        # The last hold that let go, as (action, when): a press soon after it in the same
        # direction is the device repeating, not a new tap.
        self._last_hold: tuple[Action, float] | None = None

    @property
    def held(self) -> Action | None:
        return self._held

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

    def press(self, action: Action, now_s: float | None = None) -> None:
        """A movement button went down. The first press reveals the marker rather than moving
        it; every later one moves it one step.

        With `now_s`, the press may go on to become a hold (`tick`, `release`); without it, it
        is a tap and nothing more. A press soon enough after a hold in the same direction let go
        carries that hold on instead (`vas.hold_regrip_max_s`): the device repeating a held
        button as fresh presses, not the participant tapping.
        """
        if self._cue_s is None:
            raise RuntimeError("the VAS was pressed before it was cued")
        regrip = now_s is not None and self.regrips(action, now_s)
        self._last_hold = None
        if regrip:
            self._held = action
            return
        self._tap(-1 if action is Action.DECREASE else 1)
        if now_s is not None:
            self._held = action
            self._pressed_s = now_s
            self._held_travel_s = 0.0
            self._tap_percent = self.percent

    def regrips(self, action: Action, now_s: float) -> bool:
        """Whether a press of `action` at `now_s` would carry the last hold on."""
        if self._last_hold is None:
            return False
        held, released_s = self._last_hold
        return held is action and 0.0 <= now_s - released_s <= self.regrip_max_s

    def release(self, action: Action, now_s: float) -> None:
        """The button went up. Released inside the hold delay it was a tap, and any hold travel
        a stalled event loop let a tick apply before this release arrived is taken back, so a
        tap is one step however late its release is handled (docs/LOG.md N2.9)."""
        if action is not self._held:
            return
        self._held = None
        if now_s - self._pressed_s < self.hold_delay_s:
            self.percent = self._tap_percent
        else:
            self._last_hold = (action, now_s)

    def tick(self, now_s: float) -> None:
        """Apply the hold's travel owed since the last tick. Nothing unless a button is held."""
        if self._held is None:
            return
        held_s = now_s - self._pressed_s - self.hold_delay_s
        if held_s <= 0:
            return
        travelled = self._travel(held_s) - self._travel(self._held_travel_s)
        self._held_travel_s = held_s
        direction = -1 if self._held is Action.DECREASE else 1
        self.percent = min(max(self.percent + direction * travelled, MIN_PCT), MAX_PCT)

    def rate_pct_s(self, held_s: float) -> float:
        """The hold's rate `held_s` seconds past the delay."""
        if held_s <= 0:
            return 0.0
        fraction = min(held_s / self.ramp_duration_s, 1.0)
        return self.rate_initial_pct_s + fraction * (
            self.rate_final_pct_s - self.rate_initial_pct_s
        )

    def _travel(self, held_s: float) -> float:
        """Distance in the first `held_s` seconds past the delay: `rate_pct_s` integrated."""
        if held_s <= 0:
            return 0.0
        ramped = min(held_s, self.ramp_duration_s)
        gained = self.rate_final_pct_s - self.rate_initial_pct_s
        # The 2 is the area of a triangle, not a study parameter (SPEC.md 4.2).
        distance = self.rate_initial_pct_s * ramped + gained * ramped * ramped / (
            2 * self.ramp_duration_s
        )
        return distance + self.rate_final_pct_s * max(0.0, held_s - self.ramp_duration_s)

    def _tap(self, direction: int) -> None:
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
        """The response, or None if the marker was never shown -- there is nothing to record.
        A hold still in progress ends here: the marker is where it was confirmed."""
        if self._cue_s is None or not self.visible:
            return None
        self._held = None
        self._last_hold = None
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

    **The training screen** (SPEC.md 10.6, `show_explanation`, `show_practice`) is the same
    scale, drawn exactly as it is rated, in two steps. While the experimenter explains the
    anchors and proportionality aloud (`explaining`) it asks for nothing: no marker, and only
    the emergency stop does anything. Then it is a practice rating (`practising`), with the
    practice line below the scale: the marker, the buttons and the hold work exactly as on a
    rating, and ▶ with the marker shown emits `training_confirmed` with the response. **A
    practice never emits `confirmed`**, the signal every rating is recorded from, so it cannot
    become study data whoever is listening. The emergency stop works as on every screen.
    """

    confirmed = Signal(object)
    emergency_stop = Signal()
    pressed_without_marker = Signal()
    training_confirmed = Signal(object)

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
        # The practice line below the scale while the training practises; empty otherwise.
        self.training = ""
        # The training's two steps; both False on a rating.
        self.explaining = False
        self.practising = False

        self.clock = clock
        # The hold is drawn by this timer; how far it has gone is the state's, from the time.
        self._tick = QTimer(self)
        self._tick.setInterval(int(round(float(vas_config["hold_tick_interval_s"]) * MS_PER_S)))
        self._tick.timeout.connect(self._on_tick)
        # (event milliseconds, real seconds) of the press that started the current hold, so its
        # release -- and a device's repeated press -- are placed by the key events' own stamps
        # rather than by when a handler ran (`tatp.touchcal.PressTiming`).
        self._press_stamp: tuple[int, float] | None = None

        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(False)

    def show_scale(self, scale: str, text: dict) -> None:
        """Present one scale. `text` is the `vas.<scale>` block of the participant text file."""
        self._set_scale(scale, text, "")
        self._tick.stop()
        self.state.cue()
        self.update()

    def show_explanation(self, scale: str, text: dict) -> None:
        """The training's first step (SPEC.md 10.6): the scale as `show_scale` draws it,
        uncued and with nothing below it, while the experimenter explains it aloud. Uncued, so
        no reaction time runs and no press can reveal the marker."""
        self._set_scale(scale, text, "")
        self.explaining = True
        self._tick.stop()
        self.state.reset()
        self.update()

    def show_practice(self, scale: str, text: dict, practice: str) -> None:
        """The training's second step: the scale cued as for a rating, `practice` below it."""
        self._set_scale(scale, text, practice)
        self.practising = True
        self._tick.stop()
        self.state.cue()
        self.update()

    def _set_scale(self, scale: str, text: dict, training: str) -> None:
        """One place that says what a scale is drawn from, so the training draws it as rated."""
        self.scale = scale
        self.question = text["question"]
        self.statement = text.get("statement", "")
        self.anchors = list(text["anchors"])
        self.training = training
        self.explaining = False
        self.practising = False

    # -- input -------------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        name = self._names.get(Qt.Key(event.key()))
        if name is None or self.responder.is_ignored(name):
            # Swallowed, not passed on: a key that means nothing here must do nothing at all
            # (SPEC.md 10.1).
            event.accept()
            return
        if event.isAutoRepeat():
            # The operating system's repeat of a held key. The hold is timed here, from the
            # press, so a repeat is never a second press (SPEC.md 10.1).
            event.accept()
            return
        action = self.responder.action_for(name)
        if action is Action.EMERGENCY_STOP:
            self.emergency_stop.emit()
        elif self.explaining:
            # Nothing but the emergency stop means anything while the experimenter explains.
            pass
        elif action is Action.CONFIRM:
            self._confirm()
        elif action in (Action.DECREASE, Action.INCREASE):
            self.state.press(action, self._pressed_s(action, event.timestamp()))
            self._tick.start()
            self.update()
        event.accept()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        if event.isAutoRepeat():
            event.accept()
            return
        name = self._names.get(Qt.Key(event.key()))
        action = None if name is None else self.responder.action_for(name)
        if action is not None and action is self.state.held:
            self.state.release(action, self._stamp_s(event.timestamp()))
            self._tick.stop()
            self.update()
        event.accept()

    def _pressed_s(self, action: Action, stamp_ms: int) -> float:
        """When a press went down, in real seconds.

        A press that carries a hold on is placed by its stamp, measured from the hold's own
        press, so the gap it is judged on is the device's and not however long the handlers
        took. Any other press is placed when its handler runs, and its stamp becomes the
        reference for its release.
        """
        if self.state.held is None and self._press_stamp is not None:
            placed = self._stamp_s(stamp_ms)
            if self.state.regrips(action, placed):
                return placed
        now_s = self.clock.real_elapsed_s()
        self._press_stamp = (stamp_ms, now_s)
        return now_s

    def _stamp_s(self, stamp_ms: int) -> float:
        """A key event's stamp in real seconds, measured from the press that started the hold.
        A counter that wrapped (Windows' does every 49.7 days) falls back to the handler's time
        rather than raising, which would leave the marker moving with nobody holding it."""
        stamp_ms_0, pressed_s = self._press_stamp
        if stamp_ms < stamp_ms_0:
            return self.clock.real_elapsed_s()
        return pressed_s + (stamp_ms - stamp_ms_0) / MS_PER_S

    def _on_tick(self) -> None:
        if self.state.held is None:
            self._tick.stop()
            return
        self.state.tick(self.clock.real_elapsed_s())
        self.update()

    def _confirm(self) -> None:
        response = self.state.confirm()
        if response is None:
            self.pressed_without_marker.emit()
            return
        self._tick.stop()
        (self.training_confirmed if self.practising else self.confirmed).emit(response)

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

    def _draw_training(self, painter: QPainter | None) -> QRect:
        """Lay the training sentence out below the scale, and draw it if a painter is given.

        Returns the rectangle it occupies. Measuring and drawing are one code path, as for
        `_draw_heading`.
        """
        margin = int(self.width() * SIDE_MARGIN_FRACTION)
        top = int(self.height() * TRAINING_Y_FRACTION)
        box = QRect(margin, top, self.width() - 2 * margin, self.height() - top)
        flags = Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap
        font = QFont(self.font())
        font.setPointSize(QUESTION_POINT_SIZE)
        if painter is not None:
            painter.setFont(font)
            painter.setPen(FOREGROUND)
            painter.drawText(box, flags, self.training)
        return QFontMetrics(font).boundingRect(box, flags, self.training)

    def training_clearance(self) -> tuple[float, float]:
        """Pixels from the lowest anchor label to the training text, and from its end to the
        bottom of the screen. `tests/test_vas.py` holds both for every trained scale in both
        languages at the lab window size, for the reason `heading_clearance` gives."""
        line_y = self.height() * LINE_Y_FRACTION
        metrics = QFontMetrics(self._anchor_font())
        bottoms = [line_y]
        for _, _, row, _ in self._anchor_layout(metrics):
            if row >= 0:
                baseline, _ = self._label_geometry(row, metrics, line_y)
                bottoms.append(baseline + metrics.descent())
        drawn = self._draw_training(None)
        return drawn.top() - max(bottoms), self.height() - drawn.bottom()

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

        if self.training:
            self._draw_training(painter)

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
