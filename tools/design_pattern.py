#!/usr/bin/env python
"""The pattern designer. SPEC.md 4.1 entry 3, 12.2, 12.4.

Compose a garment pattern, preview its activation timeline, play it on the mock garment or the
prototype sleeve, and save it into a pattern folder as the tick-grid CSV and its sidecar.
Opened from the launcher, or on its own:

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

import serial  # noqa: E402  -- after the path insert, with the rest
import yaml  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tatp import config as cfg  # noqa: E402
from tatp import pattern_design as pd  # noqa: E402
from tatp.clock import Clock  # noqa: E402
from tatp.garment.base import GarmentController, GarmentError, Limits  # noqa: E402
from tatp.garment.patterns import Pattern, PatternError  # noqa: E402
from tatp.pattern_design import Design, DesignError  # noqa: E402
from tatp.session import DRIVERS  # noqa: E402
from tatp.ui.application import application  # noqa: E402
from tatp.ui.widgets import (  # noqa: E402
    BACKGROUND,
    CONTROL_BACKGROUND,
    CONTROL_BORDER,
    DISCONNECTED_COLOUR,
    FOREGROUND,
    GROUP_GAP_PX,
    ITEM_GAP_PX,
    LABEL_GAP_PX,
    MARGIN_PX,
    SECONDARY,
    SIZE_BODY,
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
# Where Open, Save as and Import start: the folder the pattern folders live in.
PATTERNS_DIR = cfg.CONFIG_DIR / "patterns"
# The garment Play uses until another is chosen: the one with nothing to wake.
DEFAULT_GARMENT = "mock"

# Presentation only (SPEC.md 4.2).
NAME_FIELD_PX = 180
IDS_FIELD_PX = 140
NUMBER_FIELD_PX = 80
CHANNEL_TABLE_PX = 320
CHECK_INDICATOR_PX = 14
TIMELINE_HEIGHT_PX = 120
TIMELINE_LABEL_PX = 48
TIMELINE_AXIS_PX = 26
TIMELINE_LANE_GAP_PX = 3
TIMELINE_CURSOR_PX = 2
# A looped pattern's second cycle is drawn fainter, so it reads as the repeat, not as more.
REPEAT_ALPHA = 110
# Compact rows, so a long pattern is mostly in view, and columns that share the width. The
# cells carry no digits: on or off is the fill, which reads at a glance where a 1 among 0s
# did not (S, 24 Sep 2026).
GRID_ROW_PX = 22
GRID_SELECTION = "rgba(224, 161, 42, 70)"
ID_SEPARATORS = re.compile(r"[,;\s]+")
# What a user-chosen pattern file can raise on the way in (`DesignerWindow.open_file`).
FILE_ERRORS = (PatternError, yaml.YAMLError, ValueError, TypeError, KeyError, OSError)
# What waking a real garment can raise: no such port, a port in use, a device that does not
# answer. Reported in the window; nothing is played.
CONNECT_ERRORS = (GarmentError, serial.SerialException)


def designer_stylesheet() -> str:
    """The lab-side look, plus the controls only this window has."""
    return stylesheet() + (
        f"QTableWidget {{ background-color: {BACKGROUND}; color: {FOREGROUND}; "
        f"gridline-color: {SECONDARY}; selection-background-color: {GRID_SELECTION}; }}"
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
        f"QRadioButton::indicator {{ width: {CHECK_INDICATOR_PX}px; "
        f"height: {CHECK_INDICATOR_PX}px; border: 1px solid {SECONDARY}; "
        f"border-radius: {CHECK_INDICATOR_PX // 2}px; "
        f"background-color: {CONTROL_BACKGROUND}; }}"
        f"QRadioButton::indicator:checked {{ background-color: {TARGET_COLOUR}; }}"
    )


def channel_ids(text: str) -> tuple[int, ...]:
    parts = [part for part in ID_SEPARATORS.split(text.strip()) if part]
    if not all(part.lstrip("-").isdigit() for part in parts):
        raise DesignError("channel_ids", value=text)
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        # Python refuses to convert an integer string of thousands of digits.
        raise DesignError("channel_ids", value=text) from None


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
        self.garment_names = text["terms"]["garments"]
        self.hardware = hardware
        self.command_limits = hardware["prototype_command_file"]
        # The sleeve's channel-to-bit wiring, which import and export translate through.
        self.bit_for = pd.wiring(hardware["garment"]["prototype"]["channel_bits"])
        self.folder = folder
        self.channel_ids: tuple[int, ...] = ()
        self.rows: list[list[int]] = []
        # The file the design was opened from or last saved to, and its sidecar's text, so
        # Save writes back there and keeps what the author wrote (`pattern_design`).
        self.path: Path | None = None
        self.sidecar_source: str | None = None
        self.pattern: Pattern | None = None
        self.convert_buttons = []

        # The real playback path (SPEC.md 12.1): `play_pattern`, then `advance` from a timer at
        # the session's own tick interval, through whichever driver is chosen. A real garment
        # is woken on the first Play, not on opening, and let go on closing, so the window
        # never holds the serial port a session is about to open.
        self.clock = Clock()
        self.garment: GarmentController = self._make_garment(DEFAULT_GARMENT)
        self.timer = QTimer(self)
        tick_s = hardware["garment"]["pattern_tick_interval_s"]
        self.timer.setInterval(self.clock.scaled_ms(tick_s))
        self.timer.timeout.connect(self._tick)
        self._play_start_s: float | None = None

        self.setWindowTitle(self.words["title"])
        self.setStyleSheet(designer_stylesheet())
        self._build()
        self.revalidate()

    def _make_garment(self, driver: str) -> GarmentController:
        return DRIVERS[driver](Limits.from_config(self.hardware), self.clock,
                               hardware=self.hardware)

    # -- layout -------------------------------------------------------------------------

    def _build(self) -> None:
        words = self.words
        # No title line: the window's own title bar names it, and every line of height is
        # needed on a laptop screen.
        for_s = label(SIZE_SMALL, wrap=True, colour=WARNING_COLOUR)
        for_s.setText(words["for_s_only"])

        self.new_button = button(words["new"])
        self.open_button = button(words["open"])
        self.import_button = button(words["import_reference"])
        self.save_button = button(words["save"])
        self.save_as_button = button(words["save_as"])
        self.export_button = button(words["export"])
        self.new_button.clicked.connect(self.clear)
        self.open_button.clicked.connect(self._choose_and_open)
        self.import_button.clicked.connect(self._choose_and_import)
        self.save_button.clicked.connect(self._save)
        self.save_as_button.clicked.connect(self._choose_and_save_as)
        self.export_button.clicked.connect(self._choose_and_export)
        actions = QHBoxLayout()
        for widget in (self.new_button, self.open_button, self.import_button):
            actions.addWidget(widget)
        actions.addStretch(1)
        actions.addWidget(self.save_button)
        actions.addWidget(self.save_as_button)
        actions.addWidget(self.export_button)

        # The pattern's fields in two strips above the tabs, so the tabs -- the grid above all
        # -- have the whole width, and the window fits a laptop screen (S, 24 Sep 2026).
        self.tabs = QTabWidget()
        sized(self.tabs, SIZE_SMALL)
        self.tabs.addTab(self._grid_tab(), words["tab_grid"])
        self.tabs.addTab(self._ordered_tab(), words["tab_ordered"])
        self.tabs.addTab(self._timed_tab(), words["tab_timed"])

        self.timeline = Timeline(words)
        self.garment_choice = sized(QComboBox(), SIZE_SMALL)
        for driver in sorted(DRIVERS):
            self.garment_choice.addItem(self.garment_names[driver], driver)
        self.garment_choice.setCurrentIndex(self.garment_choice.findData(DEFAULT_GARMENT))
        # A method, not a lambda: PySide disconnects a dead window's methods, and a lambda
        # left connected rebuilds a garment inside a window being destroyed.
        self.garment_choice.currentIndexChanged.connect(self._garment_chosen)
        self.play_button = button(words["play"])
        self.stop_button = button(words["stop"])
        self.play_button.clicked.connect(self.play)
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        # Where and whether it plays, on the tab bar's own line, which is otherwise empty.
        playback = QWidget()
        playback_row = QHBoxLayout(playback)
        playback_row.setContentsMargins(0, 0, 0, LABEL_GAP_PX)
        playback_row.setSpacing(ITEM_GAP_PX)
        for control in (self._caption("play_on"), self.garment_choice, self.play_button,
                        self.stop_button):
            playback_row.addWidget(control)
        self.tabs.setCornerWidget(playback, Qt.TopRightCorner)
        self.validity = label(SIZE_SMALL, wrap=True)
        self.message = label(SIZE_SMALL, wrap=True)
        # Under the timeline: whether it loads, and what the last action did.
        status = QVBoxLayout()
        status.setSpacing(0)
        status.addWidget(self.validity)
        status.addWidget(self.message)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, ITEM_GAP_PX, MARGIN_PX, ITEM_GAP_PX)
        layout.setSpacing(ITEM_GAP_PX)
        layout.addWidget(for_s)
        layout.addLayout(actions)
        layout.addLayout(self._parameters())
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.timeline)
        layout.addLayout(status)

    def _caption(self, key: str):
        caption = label(SIZE_SMALL, colour=SECONDARY)
        caption.setText(self.words[key])
        return caption

    def _parameters(self) -> QVBoxLayout:
        """The pattern's own fields in one strip, the descriptive ones in a second."""
        self.name_field = line_edit()
        self.name_field.setMinimumWidth(NAME_FIELD_PX)
        self.interval_field = line_edit()
        self.interval_field.setFixedWidth(NUMBER_FIELD_PX)
        self.ids_field = line_edit()
        self.ids_field.setMinimumWidth(IDS_FIELD_PX)
        self.loop_box = sized(QCheckBox(self.words["loop"]), SIZE_SMALL)
        essential = self._strip(self._caption("name"), self.name_field,
                                self._caption("row_interval_ms"), self.interval_field,
                                self._caption("channel_ids"), self.ids_field, self.loop_box)
        self.extra_fields: dict[str, QLineEdit] = {}
        descriptive = [self._caption("descriptive")]
        for key in pd.OPTIONAL_FIELDS:
            self.extra_fields[key] = line_edit()
            self.extra_fields[key].setFixedWidth(NUMBER_FIELD_PX)
            descriptive += [self._caption(key), self.extra_fields[key]]
            self.extra_fields[key].textChanged.connect(self.revalidate)
        strips = QVBoxLayout()
        strips.setSpacing(ITEM_GAP_PX)
        strips.addLayout(essential)
        strips.addLayout(self._strip(*descriptive))
        self.name_field.textChanged.connect(self.revalidate)
        self.interval_field.textChanged.connect(self._interval_changed)
        # Applied on Enter or leaving the field, not per keystroke: "1, 2, 3" passes through
        # "1, 2" on the way to "1, 2, 4", and applying that would drop channel 3's column. In
        # between, the typed ids and the grid disagree, so revalidation refuses everything.
        self.ids_field.editingFinished.connect(self.apply_channel_ids)
        self.ids_field.textChanged.connect(self.revalidate)
        self.loop_box.toggled.connect(self.revalidate)
        return strips

    @staticmethod
    def _strip(*widgets: QWidget) -> QHBoxLayout:
        """One row of fields, each caption close to its field and a wider gap between pairs."""
        row = QHBoxLayout()
        row.setSpacing(ITEM_GAP_PX)
        for index, widget in enumerate(widgets):
            if index and isinstance(widget, QLabel | QCheckBox):
                row.addSpacing(GROUP_GAP_PX)
            row.addWidget(widget)
        row.addStretch(1)
        return row

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
        layout.setContentsMargins(ITEM_GAP_PX, ITEM_GAP_PX, ITEM_GAP_PX, ITEM_GAP_PX)
        hint = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        hint.setText(self.words["grid_hint"])
        self.grid = sized(QTableWidget(0, 0), SIZE_SMALL)
        self.grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.grid.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.grid.verticalHeader().setDefaultSectionSize(GRID_ROW_PX)
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
        # Every mode with what it does, all in view, so they can be compared before one is
        # chosen. A drop-down showed only the chosen one's (S, 24 Sep 2026).
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QRadioButton] = {}
        controls = QVBoxLayout()
        controls.setSpacing(LABEL_GAP_PX)
        for mode in pd.MODES:
            choice = sized(QRadioButton(self.words["modes"][mode]), SIZE_SMALL)
            hint = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
            hint.setText(self.words["mode_hints"][mode])
            hint.setContentsMargins(CHECK_INDICATOR_PX + ITEM_GAP_PX, 0, 0, 0)
            self.mode_group.addButton(choice)
            self.mode_buttons[mode] = choice
            controls.addWidget(choice)
            controls.addWidget(hint)
        self.mode_buttons[pd.MODES[0]].setChecked(True)
        self.delay_field = line_edit()
        self.delay_field.setFixedWidth(NUMBER_FIELD_PX)
        delay = QHBoxLayout()
        delay.addWidget(self._caption("delay_ms"))
        delay.addWidget(self.delay_field)
        delay.addSpacing(GROUP_GAP_PX)
        controls.addSpacing(ITEM_GAP_PX)
        controls.addLayout(delay)
        controls.addStretch(1)
        return self._channel_tab(self.ordered, self.convert_ordered, controls, delay)

    @property
    def mode(self) -> str:
        return next(mode for mode, choice in self.mode_buttons.items() if choice.isChecked())

    def set_mode(self, mode: str) -> None:
        self.mode_buttons[mode].setChecked(True)

    def _timed_tab(self) -> QWidget:
        self.timed = self._table([self.words[key] for key in ("channel", "onset_ms",
                                                               "offset_ms")])
        convert_row = QHBoxLayout()
        side = QVBoxLayout()
        side.addLayout(convert_row)
        side.addStretch(1)
        return self._channel_tab(self.timed, self.convert_timed, side, convert_row)

    def _channel_tab(self, table: QTableWidget, convert, side: QVBoxLayout,
                     convert_row: QHBoxLayout) -> QWidget:
        """A channel table and its buttons; beside them, `side`, whose `convert_row` ends with
        Convert."""
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(ITEM_GAP_PX, ITEM_GAP_PX, ITEM_GAP_PX, ITEM_GAP_PX)
        layout.setSpacing(GROUP_GAP_PX)
        left = QVBoxLayout()
        left.addWidget(table, 1)
        left.addLayout(self._row_buttons(
            ("add_channel", lambda: self._add_entry(table)),
            ("remove_channel", lambda: self._remove_entry(table)),
        ))
        convert_button = button(self.words["to_grid"])
        convert_button.clicked.connect(convert)
        self.convert_buttons.append(convert_button)
        convert_row.addWidget(convert_button)
        convert_row.addStretch(1)
        holder = QWidget()
        holder.setFixedWidth(CHANNEL_TABLE_PX)
        holder.setLayout(left)
        layout.addWidget(holder)
        layout.addLayout(side, 1)
        return tab

    # -- the design in the widgets ------------------------------------------------------

    def set_design(self, design: Design) -> None:
        self.stop()
        self.channel_ids = tuple(design.channel_ids)
        self.rows = [list(row) for row in design.rows]
        self.path, self.sidecar_source = design.path, design.sidecar_source
        # Blocked while filled in, so the half-filled form is never validated.
        for field in (self.name_field, self.interval_field, self.ids_field, self.loop_box,
                      *self.extra_fields.values()):
            field.blockSignals(True)
        self.name_field.setText(design.name)
        # Lossless, so a re-save writes back the interval that was loaded (`pd.shown`).
        self.interval_field.setText(pd.shown(design.row_interval_ms))
        self.ids_field.setText(", ".join(str(cid) for cid in design.channel_ids))
        self.loop_box.setChecked(design.loop)
        for key, field in self.extra_fields.items():
            value = design.extras.get(key)
            field.setText("" if value is None else pd.shown(value))
        for field in (self.name_field, self.interval_field, self.ids_field, self.loop_box,
                      *self.extra_fields.values()):
            field.blockSignals(False)
        self._rebuild_grid()
        self.revalidate()

    def clear(self) -> None:
        """A new pattern: nothing filled in, so nothing is assumed (SPEC.md 12.2)."""
        self.stop()
        self.channel_ids, self.rows = (), []
        self.path, self.sidecar_source = None, None
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

    def interval_ms(self) -> int | float:
        return pd.parse_number(self.interval_field.text(), self.words["row_interval_ms"])

    def ids_problem(self) -> DesignError | None:
        """Why the typed channel ids are not the grid's, or None when they are."""
        try:
            typed = channel_ids(self.ids_field.text())
        except DesignError as error:
            return error
        return None if typed == self.channel_ids else DesignError("ids_pending")

    def design(self) -> Design:
        """What the widgets hold. Refuses a field that is not a number, and stale ids."""
        problem = self.ids_problem()
        if problem is not None:
            raise problem
        extras = {}
        for key, field in self.extra_fields.items():
            typed = field.text().strip()
            extras[key] = pd.parse_number(typed, self.words[key]) if typed else None
        return Design(
            name=self.name_field.text().strip(),
            row_interval_ms=self.interval_ms(),
            channel_ids=self.channel_ids,
            loop=self.loop_box.isChecked(),
            rows=[list(row) for row in self.rows],
            extras=extras,
            path=self.path,
            sidecar_source=self.sidecar_source,
        )

    def revalidate(self, *_) -> Pattern | None:
        """The design through the loader's rules. Save, Export and Play follow the answer.

        Convert follows the channel ids alone: it is how an empty grid gets its rows, so it
        must work while the design is otherwise incomplete, but never against stale ids.
        """
        self.stop()
        for control in self.convert_buttons:
            control.setEnabled(self.ids_problem() is None)
        try:
            design = self.design()
            self.pattern = pd.validate(design, pd.target_of(design, self.folder or REPO_ROOT))
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
        for control in (self.save_button, self.save_as_button, self.export_button,
                        self.play_button):
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
        """The channel list typed, applied: a kept channel keeps its column.

        Ids that do not parse change nothing, and `revalidate` shows why and keeps Save,
        Export, Play and Convert disabled until they do.
        """
        try:
            ids = channel_ids(self.ids_field.text())
        except DesignError:
            self.revalidate()
            return
        if ids == self.channel_ids:
            self.revalidate()
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
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setBackground(QColor(TARGET_COLOUR if value else CONTROL_BACKGROUND))
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
                table.setItem(row, column, QTableWidgetItem(pd.shown(value)))

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
            values = [pd.parse_number(text, headers[column])
                      for column, text in enumerate(typed) if column]
            entries.append((ids[0], *values))
        return entries

    def convert_ordered(self) -> None:
        self._convert(lambda: pd.ordered_rows(
            self._entries(self.ordered),
            pd.parse_number(self.delay_field.text(), self.words["delay_ms"]),
            self.mode, self.interval_ms(), self.channel_ids,
        ))

    def convert_timed(self) -> None:
        self._convert(lambda: pd.timed_rows(
            self._entries(self.timed), self.interval_ms(), self.channel_ids
        ))

    def _convert(self, rows_from) -> None:
        """Replace the grid with a conversion, or say why it was refused and change nothing."""
        self.apply_channel_ids()
        # Never against stale ids: the conversion would build columns the grid does not have.
        problem = self.ids_problem()
        if problem is not None:
            self.tell(self.explain(problem), problem=True)
            return
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

    def _open_failed(self, path: Path, error: Exception) -> None:
        self.tell(self.explain(DesignError(
            "open_failed", file=path.name, value=str(error) or type(error).__name__
        )), problem=True)

    def open_file(self, path: Path) -> bool:
        """Open one of our patterns. On any failure the design shown stays as it was."""
        try:
            design = pd.open_pattern(path)
        # The one place a file the user chose enters the designer, so every way such a file
        # can fail to load is caught here, narrowly, and reported rather than raised: the
        # loader's refusals, malformed YAML, a value of the wrong type, bytes that are not
        # UTF-8 (a ValueError), a missing key, a file that cannot be read. Nothing past this
        # point sees an unchecked file, so fail-fast still holds everywhere else.
        except FILE_ERRORS as error:
            self._open_failed(path, error)
            return False
        self.folder = path.parent
        self.set_design(design)
        self.message.clear()
        return True

    def import_reference(self, path: Path, column_ms: float) -> bool:
        """Import the prototype's horizontal CSV. On failure the design shown is kept."""
        try:
            design = pd.from_reference_csv(path, column_ms, False, self.bit_for)
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return False
        # The same file boundary as `open_file`.
        except (ValueError, OSError) as error:
            self._open_failed(path, error)
            return False
        self.set_design(design)
        self.message.clear()
        return True

    def save(self) -> Pattern | None:
        """Save back to the file the pattern came from, whatever its file is called."""
        assert self.path is not None, "Save needs a file; a new pattern is saved with Save As"
        return self._save_at(self.path)

    def save_as(self, folder: Path) -> Pattern | None:
        """Save into `folder` as a new file named after the pattern."""
        if self.pattern is None:
            return None
        return self._save_at(pd.csv_path(self.design(), folder))

    def _save_at(self, target: Path) -> Pattern | None:
        """Write to `target`, asking before anything already there is replaced.

        The design is validated once, by `pd.save`. `self.pattern` being set says the widgets
        held a valid design at the last change, which is what enables Save at all.
        """
        if self.pattern is None:
            return None
        try:
            design = self.design()
            exists = target.exists() or target.with_suffix(".yaml").exists()
            if exists and not self.confirm_overwrite(target):
                return None
            saved = pd.save(design, target, overwrite=exists)
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return None
        self.path, self.sidecar_source = design.path, design.sidecar_source
        self.folder = target.parent
        self.pattern = saved
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
        if self.pattern is None:
            return False
        try:
            steps = pd.command_steps(self.pattern, self.command_limits, self.bit_for)
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return False
        path.write_text(pd.command_file(steps), encoding="utf-8", newline="")
        self.tell(self.words["exported"].format(steps=len(steps), value=path.name))
        return True

    @property
    def start_folder(self) -> Path:
        """Where a file dialog opens: the folder last used, else where patterns are kept."""
        return self.folder or PATTERNS_DIR

    def _choose_and_open(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, self.words["open"],
                                                str(self.start_folder), "*.csv")
        if chosen:
            self.open_file(Path(chosen))

    def _choose_and_import(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, self.words["import_reference"],
                                                str(self.start_folder))
        if not chosen:
            return
        dialog = ColumnDialog(self.words, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted.value:
            return
        try:
            column_ms = pd.parse_number(dialog.field.text(), self.words["column_ms_title"])
        except DesignError as error:
            self.tell(self.explain(error), problem=True)
            return
        self.import_reference(Path(chosen), column_ms)

    def _save(self) -> None:
        if self.path is None:
            self._choose_and_save_as()
        else:
            self.save()

    def _choose_and_save_as(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, self.words["save_as"],
                                                  str(self.start_folder))
        if chosen:
            self.save_as(Path(chosen))

    def _choose_and_export(self) -> None:
        if self.pattern is None:
            return
        start = self.start_folder / f"{self.pattern.name}.txt"
        chosen, _ = QFileDialog.getSaveFileName(self, self.words["export"], str(start), "*.txt")
        if chosen:
            self.export_to(Path(chosen))

    # -- playback on the chosen garment ------------------------------------------------

    @property
    def playing(self) -> bool:
        return self._play_start_s is not None

    @property
    def garment_name(self) -> str:
        return self.garment_names[self.garment_choice.currentData()]

    def _garment_chosen(self, _index: int) -> None:
        self.choose_garment(self.garment_choice.currentData())

    def choose_garment(self, driver: str) -> None:
        """Play on another garment from now on. The one in use is stopped and let go first."""
        self.stop()
        self.release_garment()
        self.garment = self._make_garment(driver)
        self.message.clear()

    def release_garment(self) -> None:
        if self.garment.connected:
            self.garment.disconnect()

    def play(self) -> bool:
        if self.revalidate() is None:
            return False
        unknown = sorted(set(self.pattern.channel_ids) - set(self.garment.channels()))
        if unknown:
            self.tell(self.explain(DesignError(
                "garment_channels", garment=self.garment_name,
                have=", ".join(map(str, self.garment.channels())),
                value=", ".join(map(str, unknown)),
            )), problem=True)
            return False
        if not self.garment.connected:
            self.tell(self.words["connecting"].format(garment=self.garment_name))
            # Shown before the wait: opening the prototype's port resets its board.
            QApplication.processEvents()
            try:
                self.garment.connect()
            except CONNECT_ERRORS as error:
                self.tell(self.explain(DesignError(
                    "connect_failed", garment=self.garment_name, value=str(error),
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
        self.tell(self.words["playing"].format(garment=self.garment_name, value=shown))

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
        # The port is the session's the moment this window closes (launcher._start_session).
        self.release_garment()
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
    # The whole screen, whatever it is: sized for a desktop, the window opened on the lab
    # laptop with its lower half off the screen (S, 24 Sep 2026).
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
