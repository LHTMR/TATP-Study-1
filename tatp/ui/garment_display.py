"""What the garment is commanded to do, channel by channel: a demonstration's only.

docs/LOG.md N7.F12f. S asked, 15 Oct 2026, that a demonstration show what the garment is
supposed to be doing, with a channel lit up when it changes so it is easily seen. One row per
channel: on or off, and the commanded pressure where the driver sets one per channel (a bar
against the ceiling, and its value); on or off alone for the prototype sleeve, whose pressure is
set by hand. A channel that changes is lit and fades back over `demo.garment_highlight_s`.

It reads the commanded state, `GarmentController.status()` -- what the software sent, not what
a sensor measured; the prototype has none. Two states are drawn as what they are rather than
as the status reads:

- **Disconnected** by hand: every channel off, as the driver zeroes its outputs on the way out.
- **Link lost**: the outputs may still hold their last state (docs/LOG.md N7.U16), so the last
  commanded state stays, held and marked, with the warning under it -- not animated as
  channels switching off, which nothing commanded.

**A demonstration's only.** In a session the experimenter screen withholds channel detail
while the condition's own pattern runs (SPEC.md 16; `tatp/ui/experimenter.py`
`BLINDED_PHASES`), because which channels a pattern uses differs by condition. This shows it
in every phase, and so lets a watcher infer the condition during the intervention. S asked for
exactly that, for a demonstration, on 15 Oct 2026 (open item L16); it is built only by the
Demo controls (`tatp/demo.py`), which only a demonstration has, and names channels, never a
pattern or a condition.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from tatp.garment.base import GarmentController
from tatp.ui.widgets import (
    BACKGROUND,
    CONTROL_BORDER,
    DISABLED,
    DISCONNECTED_COLOUR,
    FOREGROUND,
    ITEM_GAP_PX,
    SECONDARY,
    SIZE_SMALL,
    TARGET_COLOUR,
    WARNING_COLOUR,
    sized,
)
from tatp.units import MS_PER_S

BAR_WIDTH_PX = 180
ROW_PADDING_PX = 3
# The lit row's background at the moment of a change, as an opacity; it fades to nothing.
HIGHLIGHT_OPACITY = 0.35
HIGHLIGHT_OUTLINE_PX = 2

# One channel as commanded: on or off, and its pressure where the driver sets one.
State = tuple[bool, float | None]


class GarmentDisplay(QWidget):
    """One row per channel of `garment`, read every `refresh_s` while shown and lit for
    `highlight_s` when it changes. `words` is the experimenter text's `demo` section."""

    def __init__(self, garment: GarmentController, words: dict, refresh_s: float,
                 highlight_s: float, parent: QWidget | None = None):
        super().__init__(parent)
        sized(self, SIZE_SMALL)
        self.garment = garment
        self.words = words
        self.highlight_s = highlight_s
        self.connected = False
        self.link_lost = False
        self.states: dict[int, State] = {}
        # When each channel last changed, in `poll`'s seconds; a channel never seen to change
        # is not lit, its first reading included.
        self._changed_at_s: dict[int, float] = {}
        self._now_s = 0.0
        self._measure()
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.poll(time.monotonic())
        # Runs only while the display is shown (`showEvent`, `hideEvent`).
        self.timer = QTimer(self)
        self.timer.setInterval(int(round(refresh_s * MS_PER_S)))
        self.timer.timeout.connect(lambda: self.poll(time.monotonic()))

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().showEvent(event)
        self.timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().hideEvent(event)
        self.timer.stop()

    # -- what is shown -----------------------------------------------------------------

    def _read(self) -> dict[int, State]:
        """Every channel as the garment is now commanded: all off once disconnected."""
        status = self.garment.status()
        on = set(status["channels_on"]) if self.connected else set()
        return {
            channel: (channel in on,
                      (status["pressure_kpa"].get(channel, 0.0) if self.connected else 0.0)
                      if self.garment.per_channel_pressure else None)
            for channel in self.garment.channels()
        }

    def poll(self, now_s: float) -> None:
        """Read the garment's commanded state at `now_s`, a monotonic reading in seconds, light
        every channel that changed since the last, and redraw only if anything is different."""
        was = (self.connected, self.link_lost, self.states)
        lit_before = any(self.highlight(c) > 0 for c in self._changed_at_s)
        self.connected = bool(self.garment.connected)
        self.link_lost = bool(self.garment.link_lost)
        # A lost link held the outputs where they were, as far as anyone knows: the last
        # commanded state stays, and nothing is lit as if it had changed.
        if not self.link_lost:
            states = self._read()
            for channel, state in states.items():
                if channel in self.states and self.states[channel] != state:
                    self._changed_at_s[channel] = now_s
            self.states = states
        self._now_s = now_s
        if lit_before or (self.connected, self.link_lost, self.states) != was:
            self.update()

    def highlight(self, channel: int) -> float:
        """How lit `channel` is at the last poll: 1 as it changes, 0 once `highlight_s` on."""
        if channel not in self._changed_at_s:
            return 0.0
        since_s = self._now_s - self._changed_at_s[channel]
        return max(0.0, 1.0 - since_s / self.highlight_s)

    def reading(self, channel: int) -> str:
        """A channel's state in words, as its row shows it."""
        on, kpa = self.states[channel]
        state = self.words["garment_on" if on else "garment_off"]
        if kpa is None:
            return state
        return self.words["garment_pressure"].format(state=state, value=f"{kpa:.1f}")

    def notice(self) -> str:
        """The line under the channels: the link lost, not connected, or nothing."""
        if self.link_lost:
            return self.words["garment_link_lost"]
        return "" if self.connected else self.words["garment_not_connected"]

    # -- drawing -----------------------------------------------------------------------

    def _measure(self) -> None:
        """A row's height, and the caption and reading columns' widths -- each the widest it
        can be, so nothing moves as the readings change. Once: the font and words are fixed."""
        metrics = QFontMetrics(self.font())
        self._row_px = metrics.height() + 2 * ROW_PADDING_PX
        captions = [self.words["garment_channel"].format(channel=channel)
                    for channel in self.garment.channels()]
        widest_kpa = f"{self.garment.limits.pressure_ceiling_kpa:.1f}"
        readings = [
            self.words["garment_pressure"].format(state=self.words[key], value=widest_kpa)
            if self.garment.per_channel_pressure else self.words[key]
            for key in ("garment_on", "garment_off")
        ]
        self._caption_px = max(metrics.horizontalAdvance(c) for c in captions)
        self._reading_px = max(metrics.horizontalAdvance(r) for r in readings)
        lines = [self.words[key] for key in
                 ("garment_title", "garment_not_connected", "garment_link_lost")]
        self._width_px = max(
            [self._caption_px + BAR_WIDTH_PX + self._reading_px + 2 * ITEM_GAP_PX]
            + [metrics.horizontalAdvance(line) for line in lines]
        )

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        # The title, a row per channel, and the notice line, whose space is kept.
        return QSize(self._width_px, self._row_px * (len(self.garment.channels()) + 2))

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        row_px, caption_px, reading_px = self._row_px, self._caption_px, self._reading_px
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(FOREGROUND))
        painter.drawText(QRectF(0, 0, self.width(), row_px), Qt.AlignLeft | Qt.AlignVCenter,
                         self.words["garment_title"])
        bar_x = caption_px + ITEM_GAP_PX
        reading_x = bar_x + BAR_WIDTH_PX + ITEM_GAP_PX
        ceiling_kpa = self.garment.limits.pressure_ceiling_kpa
        # Held at the last command, after a lost link: amber, as uncertain, not as applied.
        on_colour = WARNING_COLOUR if self.link_lost else TARGET_COLOUR
        for row, channel in enumerate(self.garment.channels(), start=1):
            top = row * row_px
            on, kpa = self.states[channel]
            lit = self.highlight(channel)
            if lit > 0:
                glow = QColor(FOREGROUND)
                glow.setAlphaF(lit * HIGHLIGHT_OPACITY)
                painter.fillRect(QRectF(0, top, reading_x + reading_px, row_px), glow)
            painter.setPen(QColor(FOREGROUND if on else SECONDARY))
            painter.drawText(QRectF(0, top, caption_px, row_px), Qt.AlignLeft | Qt.AlignVCenter,
                             self.words["garment_channel"].format(channel=channel))
            bar = QRectF(bar_x, top + ROW_PADDING_PX, BAR_WIDTH_PX, row_px - 2 * ROW_PADDING_PX)
            # Against the ceiling where the pressure is commanded; on or off fills it or not.
            fraction = (1.0 if on else 0.0) if kpa is None else min(kpa / ceiling_kpa, 1.0)
            # A pressure set on a channel that is off is shown, dimmed: set, not applied.
            fill = QColor(on_colour if on else DISABLED)
            # Its own background under a lit row, so the bar reads the same lit or not.
            painter.fillRect(bar, QColor(BACKGROUND))
            painter.fillRect(QRectF(bar.x(), bar.y(), bar.width() * fraction, bar.height()),
                             fill)
            outline = QColor(FOREGROUND) if lit > 0 else QColor(CONTROL_BORDER)
            painter.setPen(QPen(outline, HIGHLIGHT_OUTLINE_PX if lit > 0 else 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(bar)
            painter.setPen(QColor(FOREGROUND if on else SECONDARY))
            painter.drawText(QRectF(reading_x, top, reading_px, row_px),
                             Qt.AlignLeft | Qt.AlignVCenter, self.reading(channel))
        top = (len(self.garment.channels()) + 1) * row_px
        painter.setPen(QColor(DISCONNECTED_COLOUR))
        painter.drawText(QRectF(0, top, self.width(), row_px), Qt.AlignLeft | Qt.AlignVCenter,
                         self.notice())
