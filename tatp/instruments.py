"""Instruments and environment, launcher entry 2. SPEC.md 8.1, 14.2.

Two jobs.

**Filament weighing.** The experimenter enters a precision-balance reading for each filament,
in grams as the balance shows it, and the weighing date. The force, at the chart's own
`MN_PER_G`, is written into `config/filaments.yaml`. Only a re-weighed row's
`force_measured_mn` and `weighed_date` change, with the file-level `weighing_date` (the latest
row date). The balance is not asked for (S, 24 Sep 2026), so `weighing_balance` keeps what the
file holds. The file is edited line by line
rather than re-dumped, because it is mostly comments -- the transcription record of the
manufacturer's chart, which a YAML dump would throw away. The new text is validated in full
before the file is touched, then swapped in whole. Once every filament has a measured force,
open item 1 resolves itself on the next start.

**Room temperature and humidity.** Optional (SPEC.md 8.1). They are not configuration and
are not written here: they are handed to the next session start, which records them in the
session file, or records them missing.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path

import yaml
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tatp import config as cfg
from tatp.config import CONFIG_DIR
from tatp.ui.widgets import (
    DISCONNECTED_COLOUR,
    GROUP_GAP_PX,
    ITEM_GAP_PX,
    MARGIN_PX,
    SECONDARY,
    SIZE_BODY,
    SIZE_LARGE,
    SIZE_SMALL,
    button,
    fit_to_screen,
    label,
    line_edit,
    stylesheet,
)
from tatp.units import MN_PER_G

FILAMENTS_PATH = CONFIG_DIR / "filaments.yaml"

# One filament row as filaments.yaml writes it:
# `- {label_g: "26", ..., force_measured_mn: X, weighed_date: D}`.
ROW = re.compile(
    r'^(?P<head>\s*-\s*\{\s*label_g:\s*"(?P<label>[^"]+)".*force_measured_mn:\s*)'
    r"(?P<value>[^,}]*?)(?P<middle>\s*,\s*weighed_date:\s*)(?P<date>[^,}]*?)"
    r"(?P<tail>\s*\}\s*)$"
)
# YYYY-MM-DD and nothing else: date.fromisoformat also takes 20260924 and week dates, which
# are not what a person typing the date meant to be recorded.
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A top-level scalar with its trailing comment kept: `weighing_date: null   # ISO date ...`.
SCALAR = r'^(?P<head>{key}:\s*)(?P<value>"[^"]*"|[^#\s]+)(?P<tail>\s*(#.*)?)$'
# The columns shown for each filament before the measured-force field.
SHOWN_KEYS = ("label_g", "size", "force_nominal_mn")
MEASURED_COLUMN_PX = 100
FIELD_PX = 90
COLUMN_GAP_PX = 16
DATE_FIELD_PX = 160
FILAMENT_COLUMNS = 2
INSTRUMENTS_WIDTH_PX = 1240
INSTRUMENTS_HEIGHT_PX = 720

DECIMAL_COMMA = ","
DECIMAL_POINT = "."
POSITIONAL = ".15f"
ENCODING = "utf-8"
TEMP_SUFFIX = ".tmp"


class InstrumentsError(Exception):
    """The filaments file does not have the shape this module edits. Fatal."""


def parse_number(typed: str) -> float:
    """A number as typed on a Swedish or an English keyboard. Raises ValueError otherwise."""
    return float(typed.strip().replace(DECIMAL_COMMA, DECIMAL_POINT))


def parse_date(typed: str) -> str:
    """A weighing date, strictly YYYY-MM-DD. Raises ValueError otherwise."""
    typed = typed.strip()
    if not ISO_DATE.match(typed):
        raise ValueError(f"{typed!r} is not a date in the form YYYY-MM-DD")
    date.fromisoformat(typed)  # and a real one: no 2026-02-30
    return typed


def yaml_number(value: float) -> str:
    """`value` spelled so YAML reads it back as the same float.

    PyYAML reads `1e-05` as a string -- its float needs a decimal point -- so an exponent is
    spelled out in positional form instead.
    """
    spelled = repr(float(value))
    if "e" in spelled:
        spelled = format(value, POSITIONAL).rstrip("0")
    if spelled.endswith(DECIMAL_POINT):
        spelled += "0"
    return spelled


def write_filament_forces(
    forces_mn: Mapping[str, float],
    weighed_date: str,
    path: Path = FILAMENTS_PATH,
) -> int:
    """Write measured forces, by gram label, into `filaments.yaml`. Returns the rows written.

    Only a row whose force differs from what the file holds is written, and it gets
    `weighed_date`: re-saving the dialog does not re-date filaments nobody re-weighed. The
    file-level `weighing_date` becomes the latest row date, which is what the session file
    records and what open item 1 checks.

    Nothing touches the file until the new text has been built, parsed and validated -- by the
    rules `config.load` applies and by the checks below -- and it is then written to a
    temporary file in the same folder and moved into place, so a failure at any point leaves
    the old file exactly as it was.
    """
    weighed_date = parse_date(weighed_date)
    for label_g, force in forces_mn.items():
        if not (math.isfinite(force) and force > 0):
            raise InstrumentsError(f"filament {label_g} g: {force!r} is not a force above zero")

    # Bytes, so the file's own line endings are kept whatever the platform.
    old_text = path.read_bytes().decode(ENCODING)
    old = yaml.safe_load(old_text)
    old_rows = {row["label_g"]: row for row in old["filaments"]}
    unknown = sorted(set(forces_mn) - set(old_rows))
    if unknown:
        raise InstrumentsError(f"{path}: no filament labelled {unknown}")
    changed = {
        label_g: force
        for label_g, force in forces_mn.items()
        if old_rows[label_g]["force_measured_mn"] is None
        or float(yaml_number(force)) != float(old_rows[label_g]["force_measured_mn"])
    }
    if not changed:
        return 0

    latest = max([row["weighed_date"] for row in old["filaments"] if row["weighed_date"]]
                 + [weighed_date])

    matched: dict[str, int] = {}
    edited = []
    for line in old_text.splitlines(keepends=True):
        ending = line[len(line.rstrip("\r\n")):]
        body = line[: len(line) - len(ending)]
        row = ROW.match(body)
        if row and row["label"] in changed:
            matched[row["label"]] = matched.get(row["label"], 0) + 1
            body = (
                f"{row['head']}{yaml_number(changed[row['label']])}{row['middle']}"
                f"{json.dumps(weighed_date)}{row['tail']}"
            )
        body = _set_scalar(body, "weighing_date", json.dumps(latest))
        edited.append(body + ending)
    for label_g in changed:
        if matched.get(label_g) != 1:
            raise InstrumentsError(
                f"{path}: filament {label_g!r} matched {matched.get(label_g, 0)} rows, not one"
            )
    new_text = "".join(edited)

    # Stage boundary (CLAUDE.md), before the write: the new file is what was meant.
    new = yaml.safe_load(new_text)
    _validate(old, new, changed, weighed_date, latest)

    handle = tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=f".{path.name}.", suffix=TEMP_SUFFIX, delete=False
    )
    with handle:
        handle.write(new_text.encode(ENCODING))
    os.replace(handle.name, path)
    return len(changed)


def _validate(old: dict, new: dict, changed: Mapping[str, float], weighed_date: str,
              latest: str) -> None:
    cfg.validate_file("filaments.yaml", new)
    if {**new, "filaments": None, "weighing_date": None} != {
        **old, "filaments": None, "weighing_date": None
    }:
        raise InstrumentsError("the rewrite changed a file-level field other than the date")
    old_rows = [dict(row) for row in old["filaments"]]
    new_rows = [dict(row) for row in new["filaments"]]
    if [row["label_g"] for row in old_rows] != [row["label_g"] for row in new_rows]:
        raise InstrumentsError("the rewrite changed which filaments are listed")
    for before, after in zip(old_rows, new_rows, strict=True):
        label_g = after["label_g"]
        measured, dated = after["force_measured_mn"], after["weighed_date"]
        if label_g in changed:
            expected = {**before, "force_measured_mn": float(yaml_number(changed[label_g])),
                        "weighed_date": weighed_date}
        else:
            expected = before
        if after != expected:
            raise InstrumentsError(f"filament {label_g}: the rewrite would write {after}")
        if measured is not None and not (
            isinstance(measured, float) and math.isfinite(measured) and measured > 0
        ):
            raise InstrumentsError(f"filament {label_g}: {measured!r} is not a force")
        if (measured is None) != (dated is None):
            raise InstrumentsError(f"filament {label_g}: a force and its date go together")
        if dated is not None:
            parse_date(dated)
    if new["weighing_date"] != latest:
        raise InstrumentsError(f"weighing_date would be {new['weighing_date']!r}, not {latest}")


def _set_scalar(body: str, key: str, value: str) -> str:
    match = re.match(SCALAR.format(key=re.escape(key)), body)
    if match is None:
        return body
    return f"{match['head']}{value}{match['tail']}"


class InstrumentsDialog(QDialog):
    """Weigh the filaments; note the room. `on_environment(temperature_c, humidity_pct)` is
    called with either left None when the experimenter hands the room reading on."""

    def __init__(
        self,
        text: dict,
        filaments: dict,
        on_environment: Callable[[float | None, float | None], None],
        path: Path = FILAMENTS_PATH,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.text = text
        self.path = path
        self.on_environment = on_environment
        words = text["instruments"]
        self.setWindowTitle(words["title"])
        self.setStyleSheet(stylesheet())

        title = label(SIZE_LARGE)
        title.setText(words["title"])
        heading = label(SIZE_BODY)
        heading.setText(words["filaments"])
        hint = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        hint.setText(words["filaments_hint"])
        filaments_head = QHBoxLayout()
        filaments_head.setSpacing(GROUP_GAP_PX)
        filaments_head.addWidget(heading)
        filaments_head.addWidget(hint, 1)

        # The ladder in side-by-side halves, lightest first down the left, so all twenty rows
        # are in view at once rather than scrolled through while weighing.
        rows = filaments["filaments"]
        half = math.ceil(len(rows) / FILAMENT_COLUMNS)
        halves = QHBoxLayout()
        halves.setSpacing(GROUP_GAP_PX * FILAMENT_COLUMNS)
        self.measured: dict[str, QLineEdit] = {}
        self.as_force: dict[str, QLabel] = {}
        # What each field showed on opening. Only a field changed since is saved, because a
        # force shown back in grams need not convert to the stored float exactly, and an
        # untouched row must never be re-dated.
        self.shown_g: dict[str, str] = {}
        for start in range(0, len(rows), half):
            halves.addLayout(self._filament_grid(rows[start:start + half]))
        halves.addStretch(1)
        table = QWidget()
        table.setLayout(halves)
        # Scrolls only on a screen smaller than any the lab has.
        self.filament_scroll = scroll = QScrollArea()
        scroll.setWidget(table)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        # Empty, not the last weighing's date: it dates what is weighed now, and an old date
        # carried over would be recorded against a new measurement.
        self.weighing_date = line_edit()
        self.weighing_date.setFixedWidth(DATE_FIELD_PX)
        self.save_button = button(words["save_forces"], SIZE_BODY)
        self.save_button.clicked.connect(self.save)
        self.forces_status = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        weighing = _controls_row(
            _caption(words["weighing_date"]), self.weighing_date, self.save_button,
            self.forces_status,
        )

        environment = label(SIZE_BODY)
        environment.setText(words["environment"])
        self.temperature = line_edit()
        self.temperature.setFixedWidth(FIELD_PX)
        self.humidity = line_edit()
        self.humidity.setFixedWidth(FIELD_PX)
        self.environment_button = button(words["use_environment"], SIZE_BODY)
        self.environment_button.clicked.connect(self.hand_on_environment)
        self.environment_status = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        room = _controls_row(
            environment, _caption(words["room_temperature"]), self.temperature,
            _caption(words["relative_humidity"]), self.humidity, self.environment_button,
            self.environment_status,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(title)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(filaments_head)
        layout.addWidget(scroll, 1)
        layout.addLayout(weighing)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addLayout(room)
        fit_to_screen(self, INSTRUMENTS_WIDTH_PX, INSTRUMENTS_HEIGHT_PX)

    def _filament_grid(self, rows: list[dict]) -> QGridLayout:
        words = self.text["instruments"]
        grid = QGridLayout()
        grid.setHorizontalSpacing(COLUMN_GAP_PX)
        # The fields' own padding separates the rows.
        grid.setVerticalSpacing(0)
        for column, key in enumerate(("label", "size", "nominal", "measured", "measured_mn")):
            head = label(SIZE_SMALL, colour=SECONDARY)
            head.setText(words[key])
            grid.addWidget(head, 0, column)
        for row, filament in enumerate(rows, start=1):
            for column, key in enumerate(SHOWN_KEYS):
                cell = label(SIZE_SMALL)
                cell.setText(f"{filament[key]}")
                grid.addWidget(cell, row, column)
            label_g = filament["label_g"]
            field = line_edit()
            field.setFixedWidth(MEASURED_COLUMN_PX)
            if filament["force_measured_mn"] is not None:
                field.setText(f"{filament['force_measured_mn'] / MN_PER_G:g}")
            self.shown_g[label_g] = field.text().strip()
            as_force = label(SIZE_SMALL, colour=SECONDARY)
            field.textChanged.connect(lambda typed, shown=as_force: _show_force(shown, typed))
            _show_force(as_force, field.text())
            grid.addWidget(field, row, len(SHOWN_KEYS))
            grid.addWidget(as_force, row, len(SHOWN_KEYS) + 1)
            self.measured[label_g] = field
            self.as_force[label_g] = as_force
        return grid

    def _report(self, target, message: str, problem: bool) -> None:
        target.setText(message)
        target.setStyleSheet(f"color: {DISCONNECTED_COLOUR if problem else SECONDARY};")

    def save(self) -> bool:
        """Validate what was typed and write it. Reports, never raises, on a typing mistake."""
        words = self.text["instruments"]
        forces: dict[str, float] = {}
        for label_g, field in self.measured.items():
            typed = field.text().strip()
            if not typed or typed == self.shown_g[label_g]:
                continue
            try:
                weighed_g = parse_number(typed)
            except ValueError:
                weighed_g = None
            if weighed_g is None or not (math.isfinite(weighed_g) and weighed_g > 0):
                self._report(
                    self.forces_status,
                    words["invalid_force"].format(filament=label_g, value=typed),
                    True,
                )
                return False
            forces[label_g] = weighed_g * MN_PER_G
        if not forces:
            self._report(self.forces_status, words["nothing_to_save"], True)
            return False
        typed_date = self.weighing_date.text().strip()
        if not typed_date:
            self._report(self.forces_status, words["date_required"], True)
            return False
        try:
            parse_date(typed_date)
        except ValueError:
            message = words["invalid_date"].format(value=typed_date)
            self._report(self.forces_status, message, True)
            return False
        written = write_filament_forces(forces, typed_date, self.path)
        if not written:
            # Every force typed is what the file already holds: nothing is re-dated.
            self._report(self.forces_status, words["nothing_to_save"], True)
            return False
        for label_g, field in self.measured.items():
            self.shown_g[label_g] = field.text().strip()
        self._report(self.forces_status, words["saved"].format(value=written), False)
        return True

    def hand_on_environment(self) -> bool:
        """Pass the room reading to the next session. Either may be left blank (SPEC.md 8.1)."""
        words = self.text["instruments"]
        values: list[float | None] = []
        for field in (self.temperature, self.humidity):
            typed = field.text().strip()
            if not typed:
                values.append(None)
                continue
            try:
                values.append(parse_number(typed))
            except ValueError:
                self._report(
                    self.environment_status, words["invalid_number"].format(value=typed), True
                )
                return False
        temperature, humidity = values
        self.on_environment(temperature, humidity)
        missing = self.text["fit_preview"]["missing"]
        self._report(
            self.environment_status,
            self.text["launcher"]["environment_entered"].format(
                temperature=missing if temperature is None else f"{temperature:g}",
                humidity=missing if humidity is None else f"{humidity:g}",
            ),
            False,
        )
        return True


def _show_force(target: QLabel, typed: str) -> None:
    """A weighing in grams, shown beside it as the force that will be saved; blank if none."""
    try:
        weighed_g = parse_number(typed)
    except ValueError:
        target.clear()
        return
    target.setText(f"{weighed_g * MN_PER_G:g}" if math.isfinite(weighed_g) else "")


def _caption(text: str) -> QLabel:
    made = label(SIZE_SMALL, colour=SECONDARY)
    made.setText(text)
    return made


def _controls_row(*widgets: QWidget) -> QHBoxLayout:
    """One line of controls; the last widget, a status line, takes the rest of the width."""
    row = QHBoxLayout()
    row.setSpacing(GROUP_GAP_PX)
    for widget in widgets[:-1]:
        row.addWidget(widget)
    row.addWidget(widgets[-1], 1)
    return row
