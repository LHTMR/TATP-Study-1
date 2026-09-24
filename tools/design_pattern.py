#!/usr/bin/env python
"""The pattern designer. SPEC.md 4.1 entry 3, 12.2, 12.4.

Compose a garment pattern, preview its activation timeline, play it on the mock garment, and
save it into a pattern folder as the tick-grid CSV and its sidecar. Opened from the launcher,
or on its own:

    conda run -n tatp-study-1 python tools/design_pattern.py [--open <pattern.csv>]

**For S, not for a blinded experimenter** (SPEC.md 16). It shows pattern names and shapes, which
is exactly what the session never shows. The launcher's entry says so, and so does SOP.md.

Every decision is `tatp/pattern_design.py`'s; this file is widgets. A pattern the loader would
refuse is refused here by the loader's own code, and Save and Export are disabled until the
design validates.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer  # noqa: E402  -- after the path insert
from PySide6.QtGui import QColor, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tatp import config as cfg  # noqa: E402
from tatp import pattern_design as pd  # noqa: E402
from tatp.clock import Clock  # noqa: E402
from tatp.garment.base import Limits  # noqa: E402
from tatp.garment.mock import MockGarment  # noqa: E402
from tatp.garment.patterns import Pattern, PatternError  # noqa: E402
from tatp.pattern_design import Design, DesignError  # noqa: E402
from tatp.ui.application import application  # noqa: E402
from tatp.ui.widgets import (  # noqa: E402
    BACKGROUND,
    CONTROL_BACKGROUND,
    CONTROL_BORDER,
    DISCONNECTED_COLOUR,
    FOREGROUND,
    GROUP_GAP_PX,
    ITEM_GAP_PX,
    MARGIN_PX,
    SECONDARY,
    SIZE_BODY,
    SIZE_LARGE,
    SIZE_SMALL,
    TARGET_COLOUR,
    WARNING_COLOUR,
    MessageDialog,
    button,
    label,
    line_edit,
    sized,
    stylesheet,
)

LANGUAGES = ("sv", "en")
DEFAULT_LANGUAGE = "en"

# Presentation only (SPEC.md 4.2).
PARAMETER_COLUMN_PX = 430
CHANNEL_CONTROLS_PX = 380
MODE_HINT_LINES = 3
CHECK_INDICATOR_PX = 14
TIMELINE_HEIGHT_PX = 140
TIMELINE_LABEL_PX = 48
TIMELINE_AXIS_PX = 26
TIMELINE_LANE_GAP_PX = 3
TIMELINE_CURSOR_PX = 2
# A looped pattern's second cycle is drawn fainter, so it reads as the repeat, not as more.
REPEAT_ALPHA = 110
GRID_CELL_PX = 44
ON_MARK = "1"
OFF_MARK = "0"
ID_SEPARATORS = re.compile(r"[,;\s]+")


def designer_stylesheet() -> str:
    """The lab-side look, plus the controls only this window has."""
    return stylesheet() + (
        f"QTableWidget {{ background-color: {BACKGROUND}; color: {FOREGROUND}; "
        f"gridline-color: {CONTROL_BORDER}; }}"
        f"QHeaderView::section {{ background-color: {CONTROL_BACKGROUND}; color: {SECONDARY}; "
        f"border: 1px solid {CONTROL_BORDER}; }}"
        f"QTableCornerButton::section {{ background-color: {CONTROL_BACKGROUND}; }}"
        f"QTabWidget::pane {{ border: 1px solid {CONTROL_BORDER}; }}"
        f"QTabBar::tab {{ background-color: {CONTROL_BACKGROUND}; color: {SECONDARY}; "
        f"padding: {ITEM_GAP_PX}px; border: 1px solid {CONTROL_BORDER}; }}"
        f"QTabBar::tab:selected {{ color: {FOREGROUND}; background-color: {BACKGROUND}; }}"
        # Qt's own indicator is near-invisible on the dark background when unchecked.
        f"QCheckBox::indicator {{ width: {CHECK_INDICATOR_PX}px; "
        f"height: {CHECK_INDICATOR_PX}px; border: 1px solid {SECONDARY}; "
        f"background-color: {CONTROL_BACKGROUND}; }}"
        f"QCheckBox::indicator:checked {{ background-color: {TARGET_COLOUR}; }}"
    )


def number(text: str, field: str) -> int | float:
    """A typed number, with either decimal mark, as the lab's other fields accept.

    A whole number typed without a decimal mark stays an int, so `overlap_rows: 1` is saved
    back as it was written rather than as 1.0.
    """
    typed = text.strip().replace(",", ".")
    if not typed:
        raise DesignError("required", field=field)
    try:
        return int(typed)
    except ValueError:
        pass
    try:
        return float(typed)
    except ValueError:
        raise DesignError("number", field=field, value=text) from None


def _shown(value: object) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def channel_ids(text: str) -> tuple[int, ...]:
    parts = [part for part in ID_SEPARATORS.split(text.strip()) if part]
    if not all(part.lstrip("-").isdigit() for part in parts):
        raise DesignError("channel_ids", value=text)
    return tuple(int(part) for part in parts)


# -- the timeline ---------------------------------------------------------------------------


class Timeline(QWidget):
    """Each channel's on-periods against time: one cycle, or two if the pattern loops."""

    def __init__(self, words: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.words = words
        sized(self, SIZE_SMALL)
        self.setMinimumHeight(TIMELINE_HEIGHT_PX)
        self.pattern: Pattern | None = None
        self.periods: dict[int, list[tuple[float, float]]] = {}
        self.cursor_s: float | None = None
        self.channels_on: set[int] = set()

    def set_pattern(self, pattern: Pattern | None) -> None:
        self.pattern = pattern
        self.periods = pd.on_periods(pattern) if pattern is not None else {}
        self.set_cursor(None)

    @property
    def cycles(self) -> int:
        return 2 if self.pattern is not None and self.pattern.loop else 1

    @property
    def span_s(self) -> float:
        return self.pattern.duration_s * self.cycles if self.pattern is not None else 0.0

    def set_cursor(self, t_s: float | None, channels_on: set[int] | None = None) -> None:
        """Where playback is, within the span drawn, and which channels are on now."""
        self.cursor_s = None if t_s is None else t_s % self.span_s
        self.channels_on = set(channels_on or ())
        self.update()

    def paintEvent(self, event) -> None:
        if self.pattern is None or not self.pattern.channel_ids:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        metrics = painter.fontMetrics()
        area = QRectF(TIMELINE_LABEL_PX, 0, self.width() - TIMELINE_LABEL_PX - MARGIN_PX,
                      self.height() - TIMELINE_AXIS_PX)
        lane = area.height() / len(self.pattern.channel_ids)
        cycle = self.pattern.duration_s

        def x(t_s: float) -> float:
            return area.left() + t_s / self.span_s * area.width()

        for index, channel in enumerate(self.pattern.channel_ids):
            top = area.top() + index * lane
            on_now = channel in self.channels_on
            painter.setPen(QColor(WARNING_COLOUR if on_now else SECONDARY))
            text = str(channel)
            painter.drawText(
                QPointF(area.left() - metrics.horizontalAdvance(text) - ITEM_GAP_PX,
                        top + lane / 2 + metrics.ascent() / 2),
                text,
            )
            painter.setPen(Qt.NoPen)
            for repeat in range(self.cycles):
                colour = QColor(TARGET_COLOUR)
                if repeat:
                    colour.setAlpha(REPEAT_ALPHA)
                painter.setBrush(colour)
                for start, end in self.periods[channel]:
                    offset = repeat * cycle
                    painter.drawRect(QRectF(
                        x(start + offset), top + TIMELINE_LANE_GAP_PX,
                        x(end + offset) - x(start + offset), lane - 2 * TIMELINE_LANE_GAP_PX,
                    ))

        painter.setPen(QPen(QColor(SECONDARY), 1))
        painter.drawLine(area.bottomLeft(), area.bottomRight())
        for repeat in range(self.cycles + 1):
            t_s = repeat * cycle
            if 0 < repeat < self.cycles:
                painter.setPen(QPen(QColor(SECONDARY), 1, Qt.DashLine))
                painter.drawLine(QPointF(x(t_s), area.top()), QPointF(x(t_s), area.bottom()))
                painter.setPen(QPen(QColor(SECONDARY), 1))
            text = self.words["seconds"].format(value=f"{t_s:g}")
            left = min(max(x(t_s) - metrics.horizontalAdvance(text) / 2, area.left()),
                       area.right() - metrics.horizontalAdvance(text))
            painter.drawText(QPointF(left, self.height() - metrics.descent()), text)

        if self.cursor_s is not None:
            painter.setPen(QPen(QColor(WARNING_COLOUR), TIMELINE_CURSOR_PX))
            painter.drawLine(QPointF(x(self.cursor_s), area.top()),
                             QPointF(x(self.cursor_s), area.bottom()))


# -- the column-duration question -----------------------------------------------------------


class ColumnDialog(QDialog):
    """The column duration a prototype CSV does not carry."""

    def __init__(self, words: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(words["column_ms_title"])
        self.setStyleSheet(stylesheet())
        prompt = label(SIZE_BODY, wrap=True)
        prompt.setText(words["column_ms"])
        self.field = line_edit(SIZE_BODY)
        accept = button(words["import"], SIZE_BODY)
        reject = button(words["cancel"], SIZE_BODY)
        accept.clicked.connect(self.accept)
        reject.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(reject)
        buttons.addWidget(accept)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(prompt)
        layout.addWidget(self.field)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addLayout(buttons)


# -- the window -----------------------------------------------------------------------------


class DesignerWindow(QWidget):
    """Compose, preview, play, validate, save, import and export one pattern at a time."""

    def __init__(self, text: dict, hardware: dict, folder: Path | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.words = text["designer"]
        self.errors = self.words["errors"]
        command = hardware["prototype_command_file"]
        self.max_steps, self.max_step_ms = command["max_steps"], command["max_step_ms"]
        self.folder = folder
        self.channel_ids: tuple[int, ...] = ()
        self.rows: list[list[int]] = []
        self.extras: dict = {}
        self.pattern: Pattern | None = None

        # The real playback path, against the mock (SPEC.md 12.1): `play_pattern`, then
        # `advance` from a timer at the session's own tick interval.
        self.clock = Clock()
        self.garment = MockGarment(Limits.from_config(hardware), self.clock)
        self.garment.connect()
        self.timer = QTimer(self)
        tick_s = hardware["garment"]["pattern_tick_interval_s"]
        self.timer.setInterval(self.clock.scaled_ms(tick_s))
        self.timer.timeout.connect(self._tick)
        self._play_start_s: float | None = None

        self.setWindowTitle(self.words["title"])
        self.setStyleSheet(designer_stylesheet())
        self._build()
        self.revalidate()

    # -- layout -------------------------------------------------------------------------

    def _build(self) -> None:
        words = self.words
        title = label(SIZE_LARGE)
        title.setText(words["title"])
        for_s = label(SIZE_SMALL, wrap=True, colour=WARNING_COLOUR)
        for_s.setText(words["for_s_only"])

        self.new_button = button(words["new"])
        self.open_button = button(words["open"])
        self.import_button = button(words["import_reference"])
        self.save_button = button(words["save"])
        self.export_button = button(words["export"])
        self.new_button.clicked.connect(self.clear)
        self.open_button.clicked.connect(self._choose_and_open)
        self.import_button.clicked.connect(self._choose_and_import)
        self.save_button.clicked.connect(self._choose_and_save)
        self.export_button.clicked.connect(self._choose_and_export)
        actions = QHBoxLayout()
        for widget in (self.new_button, self.open_button, self.import_button):
            actions.addWidget(widget)
        actions.addStretch(1)
        actions.addWidget(self.save_button)
        actions.addWidget(self.export_button)

        body = QHBoxLayout()
        body.addWidget(self._parameters())
        self.tabs = QTabWidget()
        sized(self.tabs, SIZE_SMALL)
        self.tabs.addTab(self._grid_tab(), words["tab_grid"])
        self.tabs.addTab(self._ordered_tab(), words["tab_ordered"])
        self.tabs.addTab(self._timed_tab(), words["tab_timed"])
        body.addWidget(self.tabs, 1)

        preview = label(SIZE_SMALL, colour=SECONDARY)
        preview.setText(words["preview"])
        self.timeline = Timeline(words)
        self.play_button = button(words["play"])
        self.stop_button = button(words["stop"])
        self.play_button.clicked.connect(self.play)
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        playback = QHBoxLayout()
        playback.addWidget(preview)
        playback.addStretch(1)
        playback.addWidget(self.play_button)
        playback.addWidget(self.stop_button)
        self.validity = label(SIZE_SMALL, wrap=True)
        self.message = label(SIZE_SMALL, wrap=True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(title)
        layout.addWidget(for_s)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(actions)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(body, 1)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(playback)
        layout.addWidget(self.timeline)
        layout.addWidget(self.validity)
        layout.addWidget(self.message)

    def _caption(self, key: str):
        caption = label(SIZE_SMALL, colour=SECONDARY)
        caption.setText(self.words[key])
        return caption

    def _parameters(self) -> QWidget:
        holder = QWidget()
        holder.setFixedWidth(PARAMETER_COLUMN_PX)
        form = QFormLayout(holder)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setContentsMargins(0, 0, ITEM_GAP_PX, 0)
        form.setVerticalSpacing(ITEM_GAP_PX)
        heading = label(SIZE_BODY)
        heading.setText(self.words["parameters"])
        form.addRow(heading)
        self.name_field = line_edit()
        self.interval_field = line_edit()
        self.ids_field = line_edit()
        self.loop_box = sized(QCheckBox(self.words["loop"]), SIZE_SMALL)
        for key, widget in (("name", self.name_field), ("row_interval_ms", self.interval_field),
                            ("channel_ids", self.ids_field)):
            form.addRow(self._caption(key), widget)
        form.addRow(self.loop_box)
        form.addRow(self._caption("descriptive"))
        self.extra_fields: dict[str, QLineEdit] = {}
        for key in pd.OPTIONAL_FIELDS:
            self.extra_fields[key] = line_edit()
            form.addRow(self._caption(key), self.extra_fields[key])
            self.extra_fields[key].textChanged.connect(self.revalidate)
        self.name_field.textChanged.connect(self.revalidate)
        self.interval_field.textChanged.connect(self._interval_changed)
        self.ids_field.editingFinished.connect(self.apply_channel_ids)
        self.loop_box.toggled.connect(self.revalidate)
        return holder

    def _table(self, headers: list[str]) -> QTableWidget:
        table = sized(QTableWidget(0, len(headers)), SIZE_SMALL)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _row_buttons(self, *pairs) -> QHBoxLayout:
        row = QHBoxLayout()
        for key, action in pairs:
            made = button(self.words[key])
            made.clicked.connect(action)
            row.addWidget(made)
        row.addStretch(1)
        return row

    def _grid_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        hint = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        hint.setText(self.words["grid_hint"])
        self.grid = sized(QTableWidget(0, 0), SIZE_SMALL)
        self.grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.cellClicked.connect(self.toggle)
        layout.addWidget(hint)
        layout.addWidget(self.grid, 1)
        layout.addLayout(self._row_buttons(
            ("add_row", self.add_row), ("duplicate_row", self.duplicate_row),
            ("remove_row", self.remove_row),
        ))
        return tab

    def _ordered_tab(self) -> QWidget:
        self.ordered = self._table([self.words["channel"], self.words["hold_ms"]])
        self.mode = sized(QComboBox(), SIZE_SMALL)
        for mode in pd.MODES:
            self.mode.addItem(self.words["modes"][mode], mode)
        self.mode_hint = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        self.mode.currentIndexChanged.connect(
            lambda _: self.mode_hint.setText(self.words["mode_hints"][self.mode.currentData()])
        )
        self.mode_hint.setText(self.words["mode_hints"][self.mode.currentData()])
        # Reserved, because a wrapped label is otherwise squeezed to fewer lines than it needs.
        self.mode_hint.setMinimumHeight(
            self.mode_hint.fontMetrics().lineSpacing() * MODE_HINT_LINES
        )
        self.delay_field = line_edit()
        controls = QVBoxLayout()
        controls.addWidget(self._caption("mode"))
        controls.addWidget(self.mode)
        controls.addWidget(self.mode_hint)
        controls.addWidget(self._caption("delay_ms"))
        controls.addWidget(self.delay_field)
        return self._channel_tab(self.ordered, controls, self.convert_ordered)

    def _timed_tab(self) -> QWidget:
        self.timed = self._table([self.words[key] for key in ("channel", "onset_ms",
                                                               "offset_ms")])
        return self._channel_tab(self.timed, QVBoxLayout(), self.convert_timed)

    def _channel_tab(self, table: QTableWidget, controls: QVBoxLayout, convert) -> QWidget:
        """A channel table and its buttons on the left; settings and Convert on the right."""
        tab = QWidget()
        layout = QHBoxLayout(tab)
        left = QVBoxLayout()
        left.addWidget(table, 1)
        left.addLayout(self._row_buttons(
            ("add_channel", lambda: self._add_entry(table)),
            ("remove_channel", lambda: self._remove_entry(table)),
        ))
        layout.addLayout(left, 1)
        side = QVBoxLayout()
        side.addLayout(controls)
        side.addStretch(1)
        side.addLayout(self._row_buttons(("to_grid", convert)))
        holder = QWidget()
        holder.setFixedWidth(CHANNEL_CONTROLS_PX)
        holder.setLayout(side)
        layout.addWidget(holder)
        return tab

    # -- the design in the widgets ------------------------------------------------------

    def set_design(self, design: Design) -> None:
        self.stop()
        self.channel_ids = tuple(design.channel_ids)
        self.rows = [list(row) for row in design.rows]
        self.extras = dict(design.extras)
        # Blocked while filled in, so the half-filled form is never validated.
        for field in (self.name_field, self.interval_field, self.ids_field, self.loop_box,
                      *self.extra_fields.values()):
            field.blockSignals(True)
        self.name_field.setText(design.name)
        self.interval_field.setText(f"{design.row_interval_ms:g}")
        self.ids_field.setText(", ".join(str(cid) for cid in design.channel_ids))
        self.loop_box.setChecked(design.loop)
        for key, field in self.extra_fields.items():
            value = design.extras.get(key)
            field.setText("" if value is None else _shown(value))
        for field in (self.name_field, self.interval_field, self.ids_field, self.loop_box,
                      *self.extra_fields.values()):
            field.blockSignals(False)
        self._rebuild_grid()
        self.revalidate()

    def clear(self) -> None:
        """A new pattern: nothing filled in, so nothing is assumed (SPEC.md 12.2)."""
        self.stop()
        self.channel_ids, self.rows, self.extras = (), [], {}
        for field in (self.name_field, self.interval_field, self.ids_field,
                      *self.extra_fields.values()):
            field.blockSignals(True)
            field.clear()
            field.blockSignals(False)
        self.loop_box.setChecked(False)
        for table in (self.ordered, self.timed):
            table.setRowCount(0)
        self.message.clear()
        self._rebuild_grid()
        self.revalidate()

    def interval_ms(self) -> float:
        return number(self.interval_field.text(), self.words["row_interval_ms"])

    def design(self) -> Design:
        """What the widgets hold. Refuses a field that is not a number."""
        extras = dict(self.extras)
        for key, field in self.extra_fields.items():
            typed = field.text().strip()
            extras[key] = number(typed, self.words[key]) if typed else None
        return Design(
            name=self.name_field.text().strip(),
            row_interval_ms=self.interval_ms(),
            channel_ids=self.channel_ids,
            loop=self.loop_box.isChecked(),
            rows=[list(row) for row in self.rows],
            extras=extras,
        )

    def revalidate(self, *_) -> Pattern | None:
        """The design through the loader's rules. Save, Export and Play follow the answer."""
        self.stop()
        try:
            self.pattern = pd.validate(self.design(), self.folder or REPO_ROOT)
        except DesignError as error:
            self.pattern = None
            self.validity.setText(self.explain(error))
            self.validity.setStyleSheet(f"color: {DISCONNECTED_COLOUR};")
        else:
            key = "loads_looped" if self.pattern.loop else "loads"
            self.validity.setText(self.words[key].format(
                rows=len(self.pattern.rows), cycle=f"{self.pattern.duration_s:g}"
            ))
            self.validity.setStyleSheet(f"color: {SECONDARY};")
        self.timeline.set_pattern(self.pattern)
        for control in (self.save_button, self.export_button, self.play_button):
            control.setEnabled(self.pattern is not None)
        return self.pattern

    def explain(self, error: DesignError) -> str:
        return self.errors[error.key].format(**error.values)

    def tell(self, text: str, problem: bool = False) -> None:
        self.message.setText(text)
        self.message.setStyleSheet(f"color: {DISCONNECTED_COLOUR if problem else FOREGROUND};")

    def _interval_changed(self, *_) -> None:
        self._label_rows()
        self.revalidate()

    # -- the grid -----------------------------------------------------------------------

    def apply_channel_ids(self) -> None:
        """The channel list typed, applied: a kept channel keeps its column."""
        try:
            ids = channel_ids(self.ids_field.text())
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return
        if ids == self.channel_ids:
            return
        self.rows = pd.resized(self.rows, self.channel_ids, ids)
        self.channel_ids = ids
        self._rebuild_grid()
        self.revalidate()

    def _rebuild_grid(self) -> None:
        self.grid.clear()
        self.grid.setColumnCount(len(self.channel_ids))
        self.grid.setRowCount(len(self.rows))
        self.grid.setHorizontalHeaderLabels([str(cid) for cid in self.channel_ids])
        for column in range(len(self.channel_ids)):
            self.grid.setColumnWidth(column, GRID_CELL_PX)
        for row_index, row in enumerate(self.rows):
            for column, value in enumerate(row):
                self.grid.setItem(row_index, column, self._cell(value))
        self._label_rows()

    def _label_rows(self) -> None:
        try:
            interval = self.interval_ms()
        except DesignError:
            interval = None
        labels = [
            self.words["row_time"].format(value=f"{index * interval:g}")
            if interval is not None else str(index)
            for index in range(len(self.rows))
        ]
        self.grid.setVerticalHeaderLabels(labels)

    def _cell(self, value: int) -> QTableWidgetItem:
        item = QTableWidgetItem(ON_MARK if value else OFF_MARK)
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setBackground(QColor(TARGET_COLOUR if value else BACKGROUND))
        item.setForeground(QColor(BACKGROUND if value else SECONDARY))
        return item

    def toggle(self, row: int, column: int) -> None:
        self.rows[row][column] = 1 - self.rows[row][column]
        self.grid.setItem(row, column, self._cell(self.rows[row][column]))
        self.revalidate()

    def _current_row(self) -> int:
        current = self.grid.currentRow()
        return current if current >= 0 else len(self.rows) - 1

    def add_row(self) -> None:
        self.rows.insert(self._current_row() + 1, [0] * len(self.channel_ids))
        self._rebuild_grid()
        self.revalidate()

    def duplicate_row(self) -> None:
        if not self.rows:
            return
        at = self._current_row()
        self.rows.insert(at + 1, list(self.rows[at]))
        self._rebuild_grid()
        self.revalidate()

    def remove_row(self) -> None:
        if not self.rows:
            return
        del self.rows[self._current_row()]
        self._rebuild_grid()
        self.revalidate()

    # -- ordered and timed channels -----------------------------------------------------

    def _add_entry(self, table: QTableWidget) -> None:
        table.insertRow(table.rowCount())

    def _remove_entry(self, table: QTableWidget) -> None:
        current = table.currentRow()
        table.removeRow(current if current >= 0 else table.rowCount() - 1)

    def set_entries(self, table: QTableWidget, entries) -> None:
        table.setRowCount(0)
        for entry in entries:
            row = table.rowCount()
            table.insertRow(row)
            for column, value in enumerate(entry):
                table.setItem(row, column, QTableWidgetItem(f"{value:g}"))

    def _entries(self, table: QTableWidget) -> list[tuple]:
        """Each row of a channel table: the channel id, then numbers. Blank rows are skipped."""
        entries = []
        for row in range(table.rowCount()):
            cells = [table.item(row, column) for column in range(table.columnCount())]
            typed = [cell.text().strip() if cell is not None else "" for cell in cells]
            if not any(typed):
                continue
            ids = channel_ids(typed[0])
            if len(ids) != 1:
                raise DesignError("channel_ids", value=typed[0])
            headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
            values = [number(text, headers[column]) for column, text in enumerate(typed)
                      if column]
            entries.append((ids[0], *values))
        return entries

    def convert_ordered(self) -> None:
        self._convert(lambda: pd.ordered_rows(
            self._entries(self.ordered),
            number(self.delay_field.text(), self.words["delay_ms"]),
            self.mode.currentData(), self.interval_ms(), self.channel_ids,
        ))

    def convert_timed(self) -> None:
        self._convert(lambda: pd.timed_rows(
            self._entries(self.timed), self.interval_ms(), self.channel_ids
        ))

    def _convert(self, rows_from) -> None:
        """Replace the grid with a conversion, or say why it was refused and change nothing."""
        self.apply_channel_ids()
        try:
            rows = rows_from()
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return
        self.rows = rows
        self._rebuild_grid()
        self.revalidate()
        self.tell(self.words["converted"].format(value=len(rows)))

    # -- files --------------------------------------------------------------------------

    def open_file(self, path: Path) -> bool:
        try:
            design = pd.open_pattern(path)
        except PatternError as error:
            self.tell(self.explain(DesignError("open_failed", value=str(error))), problem=True)
            return False
        self.folder = path.parent
        self.set_design(design)
        self.message.clear()
        return True

    def import_reference(self, path: Path, column_ms: float) -> bool:
        try:
            design = pd.from_reference_csv(path, column_ms, loop=False)
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return False
        self.set_design(design)
        self.message.clear()
        return True

    def save_to(self, folder: Path) -> Pattern | None:
        """Save into `folder`, asking before anything already there is replaced."""
        try:
            design = self.design()
            pd.validate(design, folder)
            target = pd.csv_path(design, folder)
            exists = target.exists() or target.with_suffix(".yaml").exists()
            if exists and not self.confirm_overwrite(target):
                return None
            saved = pd.save(design, folder, overwrite=exists)
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return None
        self.folder = folder
        self.tell(self.words["saved"].format(value=target.name))
        return saved

    def confirm_overwrite(self, target: Path) -> bool:
        dialog = MessageDialog(
            self.words["overwrite_title"], self.words["overwrite"].format(value=target.name),
            self.words["replace"], self.words["cancel"], parent=self,
        )
        return dialog.exec() == QDialog.DialogCode.Accepted.value

    def export_to(self, path: Path) -> bool:
        """The prototype rig's command file (SPEC.md 12.4), written to `path`."""
        if self.revalidate() is None:
            return False
        try:
            steps = pd.command_steps(self.pattern, self.max_steps, self.max_step_ms)
            text = pd.command_file(self.pattern, self.max_steps, self.max_step_ms)
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return False
        path.write_text(text, encoding="utf-8", newline="")
        self.tell(self.words["exported"].format(steps=len(steps), value=path.name))
        return True

    def _choose_and_open(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, self.words["open"],
                                                str(self.folder or ""), "*.csv")
        if chosen:
            self.open_file(Path(chosen))

    def _choose_and_import(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, self.words["import_reference"],
                                                str(self.folder or ""))
        if not chosen:
            return
        dialog = ColumnDialog(self.words, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted.value:
            return
        try:
            column_ms = number(dialog.field.text(), self.words["column_ms_title"])
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return
        self.import_reference(Path(chosen), column_ms)

    def _choose_and_save(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, self.words["save"],
                                                  str(self.folder or ""))
        if chosen:
            self.save_to(Path(chosen))

    def _choose_and_export(self) -> None:
        if self.pattern is None:
            return
        start = (self.folder or REPO_ROOT) / f"{self.pattern.name}.txt"
        chosen, _ = QFileDialog.getSaveFileName(self, self.words["export"], str(start), "*.txt")
        if chosen:
            self.export_to(Path(chosen))

    # -- playback on the mock garment ---------------------------------------------------

    @property
    def playing(self) -> bool:
        return self._play_start_s is not None

    def play(self) -> bool:
        if self.revalidate() is None:
            return False
        unknown = sorted(set(self.pattern.channel_ids) - set(self.garment.channels()))
        if unknown:
            self.tell(self.explain(DesignError(
                "mock_channels", have=", ".join(map(str, self.garment.channels())),
                value=", ".join(map(str, unknown)),
            )), problem=True)
            return False
        self.garment.play_pattern(self.pattern)
        self._play_start_s = self.clock.elapsed_s()
        self.stop_button.setEnabled(True)
        self.timer.start()
        self._tick()
        return True

    def _tick(self) -> None:
        if not self.playing:
            return
        self.garment.advance()
        elapsed = self.clock.elapsed_s() - self._play_start_s
        if not self.pattern.loop and elapsed >= self.pattern.duration_s:
            self.stop()
            return
        self.show_playback(elapsed, set(self.garment.status()["channels_on"]))

    def show_playback(self, elapsed_s: float, channels_on: set[int]) -> None:
        self.timeline.set_cursor(elapsed_s, channels_on)
        shown = ", ".join(map(str, sorted(channels_on))) or self.words["none_on"]
        self.tell(self.words["playing"].format(value=shown))

    def stop(self) -> None:
        if not self.playing:
            return
        self.timer.stop()
        self._play_start_s = None
        self.stop_button.setEnabled(False)
        self.garment.stop_pattern()
        self.timeline.set_cursor(None)
        self.tell(self.words["stopped"])

    def closeEvent(self, event) -> None:
        self.stop()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--language", default=DEFAULT_LANGUAGE, choices=LANGUAGES)
    parser.add_argument("--open", type=Path, default=None, help="a pattern CSV to open")
    args = parser.parse_args(argv)
    config = cfg.load(args.language, args.language)
    app = QApplication.instance() or application(config.hardware)
    window = DesignerWindow(config.experimenter_text, config.hardware)
    if args.open is not None:
        window.open_file(args.open)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
