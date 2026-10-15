"""What the garment is commanded to do, channel by channel: a demonstration's only.

docs/LOG.md N7.F12f. S asked, 15 Oct 2026, that a demonstration show what the garment is
supposed to be doing, with a channel lit up when it changes so it is easily seen. One row per
channel: on or off, and the commanded pressure where the driver sets one per channel (a bar
against the ceiling, and its value); on or off alone for the prototype sleeve, whose pressure is
set by hand. A channel that changes is lit and fades back over `demo.garment_highlight_s`.

It reads the commanded state, `GarmentController.status()` -- what the software sent, not what
a sensor measured; the prototype has none.

**A demonstration's only.** In a session the experimenter screen withholds channel detail
while the condition's own pattern runs (SPEC.md 16; `tatp/ui/experimenter.py`
`BLINDED_PHASES`); this shows it in every phase, and so is built only by the Demo controls
(`tatp/demo.py`), which only a demonstration has. S settled that for a demonstration on 15 Oct
2026 (open item L16). It names channels, never a pattern or a condition.
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
    """One row per channel of `garment`, read every `refresh_s` and lit for `highlight_s` when
    it changes. `words` is the experimenter text's `demo` section."""

    def __init__(self, garment: GarmentController, words: dict, refresh_s: float,
                 highlight_s: float, parent: QWidget | None = None):
        super().__init__(parent)
        sized(self, SIZE_SMALL)
        self.garment = garment
        self.words = words
        self.highlight_s = highlight_s
        self.connected = False
        self.states: dict[int, State] = {}
        # When each channel last changed, in `poll`'s seconds; a channel never seen to change
        # is not lit, its first reading included.
        self._changed_at_s: dict[int, float] = {}
        self._now_s = 0.0
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.poll(time.monotonic())
        self.timer = QTimer(self)
        self.timer.setInterval(int(round(refresh_s * MS_PER_S)))
        self.timer.timeout.connect(lambda: self.poll(time.monotonic()))
        self.timer.start()

    # -- what is shown -----------------------------------------------------------------

    def poll(self, now_s: float) -> None:
        """Read the garment's commanded state at `now_s`, a monotonic reading in seconds, and
        light every channel that changed since the last."""
        status = self.garment.status()
        self.connected = bool(status["connected"])
        on = set(status["channels_on"])
        states = {
            channel: (channel in on,
                      status["pressure_kpa"].get(channel, 0.0)
                      if self.garment.per_channel_pressure else None)
            for channel in self.garment.channels()
        }
        for channel, state in states.items():
            if channel in self.states and self.states[channel] != state:
                self._changed_at_s[channel] = now_s
        self.states = states
        self._now_s = now_s
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

    # -- drawing -----------------------------------------------------------------------

    def _metrics(self) -> tuple[QFontMetrics, int, int, int]:
        """The font's metrics, a row's height, and the caption and reading columns' widths --
        each the widest it can be, so nothing moves as the readings change."""
        metrics = QFontMetrics(self.font())
        row_px = metrics.height() + 2 * ROW_PADDING_PX
        captions = [self.words["garment_channel"].format(channel=channel)
                    for channel in self.garment.channels()]
        widest_kpa = f"{self.garment.limits.pressure_ceiling_kpa:.1f}"
        readings = [
            self.words["garment_pressure"].format(state=self.words[key], value=widest_kpa)
            if self.garment.per_channel_pressure else self.words[key]
            for key in ("garment_on", "garment_off")
        ]
        return (metrics, row_px, max(metrics.horizontalAdvance(c) for c in captions),
                max(metrics.horizontalAdvance(r) for r in readings))

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        metrics, row_px, caption_px, reading_px = self._metrics()
        lines = [self.words["garment_title"], self.words["garment_not_connected"]]
        width = max([caption_px + BAR_WIDTH_PX + reading_px + 2 * ITEM_GAP_PX]
                    + [metrics.horizontalAdvance(line) for line in lines])
        # The title, a row per channel, and the not-connected line, whose space is kept.
        height = row_px * (len(self.garment.channels()) + 2)
        return QSize(width, height)

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        _, row_px, caption_px, reading_px = self._metrics()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(FOREGROUND))
        painter.drawText(QRectF(0, 0, self.width(), row_px), Qt.AlignLeft | Qt.AlignVCenter,
                         self.words["garment_title"])
        bar_x = caption_px + ITEM_GAP_PX
        reading_x = bar_x + BAR_WIDTH_PX + ITEM_GAP_PX
        ceiling_kpa = self.garment.limits.pressure_ceiling_kpa
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
            fill = QColor(TARGET_COLOUR if on else DISABLED)
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
        if not self.connected:
            top = (len(self.garment.channels()) + 1) * row_px
            painter.setPen(QColor(DISCONNECTED_COLOUR))
            painter.drawText(QRectF(0, top, self.width(), row_px),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             self.words["garment_not_connected"])
