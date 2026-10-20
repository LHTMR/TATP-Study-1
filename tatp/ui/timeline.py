"""The session's phases in order, in the experimenter screen's phase row, with the one under
way marked (S, 20 Oct 2026; docs/LOG.md N7.F16h).

One segment per phase. The current one is filled in the target colour and named in full, in
the row's large type, since it is the phase the screen must say at a glance (UI_PRINCIPLES.md
3.1); it takes the width its name needs. The rest share what is left, abbreviated: past ones
filled grey, those to come outlined, so where the session is up to is read without reading
(5.6). Widths are not in time: a 2-minute heat beside a 120-minute intervention would leave
most phases too narrow to name.

**The same in every condition** (SPEC.md 16). The phases are the schedule's, which no
condition changes, and the rekindle is drawn as part of the intervention it falls in. What is
marked is `experimenter_view()["phase"]`, which the window has always shown in words.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from tatp.ui.widgets import (
    BACKGROUND,
    CONTROL_BACKGROUND,
    CONTROL_BORDER,
    FOREGROUND,
    SECONDARY,
    SIZE_LARGE,
    SIZE_SMALL,
    TARGET_COLOUR,
    sized,
)

SEGMENT_GAP_PX = 3
SEGMENT_PADDING_PX = 4
# Above and below the current phase's name: no taller than the phase label it replaced.
SEGMENT_VERTICAL_PADDING_PX = 2
# The phase each of these is drawn as: the rekindle is a step of the intervention.
FOLDED = {"rekindle": "intervention"}
# Phases that come after every segment: the session is over.
AFTER = ("session_end",)


class PhaseTimeline(QWidget):
    """`set_phases` with (key, short label, full name) in session order; `set_current(key)`
    marks one."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        sized(self, SIZE_SMALL)
        self.phases: list[tuple[str, str, str]] = []
        self.current: str | None = None
        self._current_font = QFont(self.font())
        self._current_font.setPointSize(SIZE_LARGE)
        self._current_font.setBold(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(
            QFontMetrics(self._current_font).height() + SEGMENT_VERTICAL_PADDING_PX)

    def set_phases(self, phases: Sequence[tuple[str, str, str]]) -> None:
        self.phases = list(phases)
        self.update()

    def set_current(self, phase: str | None) -> None:
        phase = FOLDED.get(phase, phase)
        if phase != self.current:
            self.current = phase
            self.update()

    def index(self) -> int | None:
        """Where the current phase is: its place in the list, the list's length once the
        session is over, and None for a phase that is neither."""
        keys = [key for key, _, _ in self.phases]
        if self.current in keys:
            return keys.index(self.current)
        return len(keys) if self.current in AFTER else None

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        return QSize(0, self.height())

    def _widths(self) -> list[float]:
        count, current = len(self.phases), self.index()
        room = self.width() - SEGMENT_GAP_PX * (count - 1)
        if current is None or current >= count:
            return [room / count] * count
        full = QFontMetrics(self._current_font).horizontalAdvance(self.phases[current][2])
        own = min(max(room / count, full + 2 * SEGMENT_PADDING_PX), room / 2)
        rest = (room - own) / (count - 1) if count > 1 else 0.0
        return [own if position == current else rest for position in range(count)]

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        if not self.phases:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        current = self.index()
        x = 0.0
        for position, ((_key, short, full), width) in enumerate(
                zip(self.phases, self._widths(), strict=True)):
            box = QRectF(x, 0, width, self.height() - 1)
            x += width + SEGMENT_GAP_PX
            now = position == current
            done = current is not None and position < current
            if now:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(TARGET_COLOUR))
                font = self._current_font
            else:
                if done:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(CONTROL_BORDER))
                else:
                    painter.setPen(QPen(QColor(CONTROL_BORDER), 1))
                    painter.setBrush(QColor(CONTROL_BACKGROUND))
                font = self.font()
            painter.drawRect(box)
            painter.setFont(font)
            painter.setPen(QColor(BACKGROUND if now else FOREGROUND if done else SECONDARY))
            inner = box.adjusted(SEGMENT_PADDING_PX, 0, -SEGMENT_PADDING_PX, 0)
            shown = QFontMetrics(font).elidedText(full if now else short, Qt.ElideRight,
                                                  int(inner.width()))
            painter.drawText(inner, Qt.AlignCenter, shown)
        painter.end()
