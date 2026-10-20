"""What the garment is commanded to do, channel by channel, in the experimenter window's side
column: in a session and in a demonstration alike (S, 20 Oct 2026; docs/LOG.md N7.F16i).

One row per channel: on or off, and the commanded pressure where the driver sets one per
channel (a bar against the ceiling, and its value); on or off alone for the prototype sleeve,
whose pressure is set by hand. A channel that changes is lit and fades back over
`highlight_s`, so a watcher's eye is drawn to it (S, 15 Oct 2026; N7.F12f). It replaced two
displays that said the same thing two ways: a line of "kPa by channel" in the session, and a
separate Demo controls window's own channel display.

It draws what it is handed (`show_states`), and reads nothing itself:

- **In a session** the experimenter window hands it `experimenter_view()["hardware"]`, which
  withholds the channels while the condition's touch runs (SPEC.md 16), and then it is not
  shown at all.
- **In a demonstration** the Demo controls hand it the garment's own commanded state in every
  phase, which lets a watcher infer the condition during the intervention. S asked for exactly
  that, for a demonstration, on 15 Oct 2026 (open item L16).

What it is handed is the commanded state -- what the software sent, not what a sensor
measured; the prototype has none. A lost link is drawn as what it is: the outputs may still
hold their last state (docs/LOG.md N7.U16), so the last commanded state stays, held in amber
-- not animated as channels switching off, which nothing commanded.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from tatp.ui.widgets import (
    BACKGROUND,
    CONTROL_BORDER,
    DISABLED,
    FOREGROUND,
    SECONDARY,
    SIZE_SMALL,
    TARGET_COLOUR,
    WARNING_COLOUR,
    sized,
)
from tatp.units import MS_PER_S

ROW_PADDING_PX = 3
# The lit row's background at the moment of a change, as an opacity; it fades to nothing.
HIGHLIGHT_OPACITY = 0.35
HIGHLIGHT_OUTLINE_PX = 2
# Between a bar and its reading.
COLUMN_GAP_PX = 4
# The narrowest a bar is drawn: still a bar beside the zone diagram.
MIN_BAR_PX = 50
# How often a lit row is redrawn while it fades: smooth enough to be seen as a fade.
FADE_FRAME_S = 0.05
# A number the fill has covered this much of is drawn dark, to stay legible on the fill.
DARK_NUMBER_FILL = 0.5

# One channel as commanded: on or off, and its pressure where the driver sets one.
State = tuple[bool, float | None]


def states_from_status(status: Mapping, channels: Sequence[int], connected: bool,
                       per_channel_pressure: bool) -> dict[int, State]:
    """Every channel as `GarmentController.status()` reads: all off once disconnected, as the
    driver zeroes its outputs on the way out."""
    on = set(status["channels_on"]) if connected else set()
    return {
        channel: (channel in on,
                  (status["pressure_kpa"].get(channel, 0.0) if connected else 0.0)
                  if per_channel_pressure else None)
        for channel in channels
    }


class GarmentDisplay(QWidget):
    """One row per channel of `channels`, lit for `highlight_s` when it changes. `words` is
    the experimenter text's `hardware` section."""

    def __init__(self, channels: Sequence[int], ceiling_kpa: float, per_channel_pressure: bool,
                 words: dict, highlight_s: float, parent: QWidget | None = None):
        super().__init__(parent)
        sized(self, SIZE_SMALL)
        self.channels = list(channels)
        self.ceiling_kpa = ceiling_kpa
        self.per_channel_pressure = per_channel_pressure
        self.words = words
        self.highlight_s = highlight_s
        self.link_lost = False
        self.states: dict[int, State] = {
            channel: (False, 0.0 if per_channel_pressure else None) for channel in channels
        }
        # When each channel last changed, in `show_states`' seconds; a channel never seen to
        # change is not lit, its first reading included.
        self._changed_at_s: dict[int, float] = {}
        self._seen = False
        self._now_s = 0.0
        self._measure()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Runs only while a row is lit, to fade it.
        self.fade = QTimer(self)
        self.fade.setInterval(int(round(FADE_FRAME_S * MS_PER_S)))
        self.fade.timeout.connect(lambda: self._advance(time.monotonic()))

    # -- what is shown -----------------------------------------------------------------

    def show_states(self, states: Mapping[int, State], link_lost: bool,
                    now_s: float | None = None) -> None:
        """The channels as commanded at `now_s` (monotonic seconds, now by default): every
        channel that changed since the last is lit. With the link lost the last commanded
        state stays, and nothing is lit as if it had changed."""
        now_s = time.monotonic() if now_s is None else now_s
        was = (self.link_lost, self.states)
        self.link_lost = link_lost
        if not link_lost:
            if self._seen:
                for channel, state in states.items():
                    if self.states.get(channel) != state:
                        self._changed_at_s[channel] = now_s
            self.states = dict(states)
            self._seen = True
        self._advance(now_s, changed=(self.link_lost, self.states) != was)

    def _advance(self, now_s: float, changed: bool = False) -> None:
        lit_before = self.lit()
        self._now_s = now_s
        lit = self.lit()
        if lit and not self.fade.isActive():
            self.fade.start()
        elif not lit:
            self.fade.stop()
        if changed or lit or lit_before:
            self.update()

    def lit(self) -> bool:
        return any(self.highlight(channel) > 0 for channel in self._changed_at_s)

    def highlight(self, channel: int) -> float:
        """How lit `channel` is: 1 as it changes, 0 once `highlight_s` on."""
        if channel not in self._changed_at_s:
            return 0.0
        since_s = self._now_s - self._changed_at_s[channel]
        return max(0.0, 1.0 - since_s / self.highlight_s)


    def reading(self, channel: int) -> str:
        """A channel's reading beside its bar: its pressure in whole kPa (the data has every
        decimal), or on or off where the driver sets none, which the fill shows too."""
        on, kpa = self.states[channel]
        if kpa is None:
            return self.words["channel_on" if on else "channel_off"]
        return self.words["channel_pressure"].format(value=f"{kpa:.0f}")

    # -- drawing -----------------------------------------------------------------------
    # One row per channel, beside the zone diagram (LOG N7.F17b): a bar carrying the channel's
    # number, filled from the left to its pressure against the ceiling (or whole when on,
    # where the driver sets no pressure), and the reading after it.

    def _measure(self) -> None:
        """A row's height and the reading's width -- the widest it can be, so nothing moves
        as the readings change. Once: the font and words are fixed."""
        metrics = QFontMetrics(self.font())
        self._row_px = metrics.height() + 2 * ROW_PADDING_PX
        widest = [self.words["channel_pressure"].format(value=f"{self.ceiling_kpa:.0f}"),
                  self.words["channel_on"], self.words["channel_off"]]
        self._reading_px = max(metrics.horizontalAdvance(text) for text in widest)
        self._number_px = max(metrics.horizontalAdvance(str(c)) for c in self.channels) + \
            2 * ROW_PADDING_PX

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        width = self._number_px + MIN_BAR_PX + COLUMN_GAP_PX + self._reading_px
        return QSize(width, self._row_px * len(self.channels))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        row_px = self._row_px
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bar_px = self.width() - self._reading_px - COLUMN_GAP_PX
        # Held at the last command, after a lost link: amber, as uncertain, not as applied.
        on_colour = WARNING_COLOUR if self.link_lost else TARGET_COLOUR
        for index, channel in enumerate(self.channels):
            top = index * row_px
            on, kpa = self.states[channel]
            lit = self.highlight(channel)
            bar = QRectF(0, top + ROW_PADDING_PX / 2, bar_px, row_px - ROW_PADDING_PX)
            if lit > 0:
                glow = QColor(FOREGROUND)
                glow.setAlphaF(lit * HIGHLIGHT_OPACITY)
                painter.fillRect(QRectF(0, top, self.width(), row_px), glow)
            # Against the ceiling where the pressure is commanded; on or off fills it or not.
            fraction = (1.0 if on else 0.0) if kpa is None else min(kpa / self.ceiling_kpa, 1.0)
            # A pressure set on a channel that is off is shown, dimmed: set, not applied.
            fill = QColor(on_colour if on else DISABLED)
            painter.fillRect(bar, QColor(BACKGROUND))
            painter.fillRect(QRectF(bar.x(), bar.y(), bar.width() * fraction, bar.height()),
                             fill)
            outline = QColor(FOREGROUND) if lit > 0 else QColor(CONTROL_BORDER)
            painter.setPen(QPen(outline, HIGHLIGHT_OUTLINE_PX if lit > 0 else 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(bar)
            # The number sits at the bar's start, over the fill once it reaches past it.
            number = QRectF(bar.x(), bar.y(), self._number_px, bar.height())
            covered = on and bar.width() * fraction > self._number_px * DARK_NUMBER_FILL
            painter.setPen(QColor(BACKGROUND if covered else FOREGROUND))
            painter.drawText(number, Qt.AlignCenter, str(channel))
            painter.setPen(QColor(FOREGROUND if on else SECONDARY))
            painter.drawText(QRectF(bar_px + COLUMN_GAP_PX, top, self._reading_px, row_px),
                             Qt.AlignRight | Qt.AlignVCenter, self.reading(channel))
        painter.end()
