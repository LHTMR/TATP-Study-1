"""Instruments and environment, launcher entry 2. SPEC.md 8.1, 14.2.

Two jobs.

**Filament weighing.** The experimenter enters a precision-balance measurement for each
filament, and the weighing date, and they are written into `config/filaments.yaml`. Only the
`force_measured_mn` values, `weighing_date` and `weighing_balance` change: the file is edited
line by line rather than re-dumped, because it is mostly comments -- the transcription record
of the manufacturer's chart, which a YAML dump would throw away. Once every filament has a
measured force and the date is set, open item 1 resolves itself on the next start.

**Room temperature and humidity.** Optional (SPEC.md 8.1). They are not configuration and
are not written here: they are handed to the next session start, which records them in the
session file, or records them missing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path

import yaml
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

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
    label,
    line_edit,
    stylesheet,
)

FILAMENTS_PATH = CONFIG_DIR / "filaments.yaml"

# One filament row as filaments.yaml writes it: `- {label_g: "26", ..., force_measured_mn: X}`.
ROW = re.compile(
    r'^(?P<head>\s*-\s*\{\s*label_g:\s*"(?P<label>[^"]+)".*force_measured_mn:\s*)'
    r"(?P<value>[^,}]*?)(?P<tail>\s*\}\s*)$"
)
# A top-level scalar with its trailing comment kept: `weighing_date: null   # ISO date ...`.
SCALAR = r'^(?P<head>{key}:\s*)(?P<value>"[^"]*"|[^#\s]+)(?P<tail>\s*(#.*)?)$'
# The columns shown for each filament before the measured-force field.
SHOWN_KEYS = ("label_g", "size", "force_nominal_mn")
MEASURED_COLUMN_PX = 110
FIELD_PX = 90

DECIMAL_COMMA = ","
DECIMAL_POINT = "."


class InstrumentsError(Exception):
    """The filaments file does not have the shape this module edits. Fatal."""


def parse_number(typed: str) -> float:
    """A number as typed on a Swedish or an English keyboard. Raises ValueError otherwise."""
    return float(typed.strip().replace(DECIMAL_COMMA, DECIMAL_POINT))


def write_filament_forces(
    forces_mn: Mapping[str, float],
    weighing_date: str,
    balance: str | None,
    path: Path = FILAMENTS_PATH,
) -> None:
    """Write measured forces, by gram label, and the weighing record into `filaments.yaml`.

    Every label must name exactly one row, and the date must be an ISO date. Labels not given
    keep what they have. The file is read back afterwards and checked, so a pattern that
    stopped matching the file's layout fails here rather than writing nothing silently.
    """
    date.fromisoformat(weighing_date)  # raises on anything that is not YYYY-MM-DD
    for label_g, force in forces_mn.items():
        if not force > 0:
            raise InstrumentsError(f"filament {label_g} g: a measured force must be above zero")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    matched: dict[str, int] = {}
    edited = []
    for line in lines:
        ending = line[len(line.rstrip("\r\n")):]
        body = line[: len(line) - len(ending)]
        row = ROW.match(body)
        if row and row["label"] in forces_mn:
            matched[row["label"]] = matched.get(row["label"], 0) + 1
            body = f"{row['head']}{forces_mn[row['label']]:g}{row['tail']}"
        body = _set_scalar(body, "weighing_date", json.dumps(weighing_date))
        if balance is not None:
            # JSON's string syntax is valid YAML, and escapes whatever was typed.
            body = _set_scalar(body, "weighing_balance", json.dumps(balance))
        edited.append(body + ending)

    for label_g in forces_mn:
        if matched.get(label_g) != 1:
            raise InstrumentsError(
                f"{path}: filament {label_g!r} matched {matched.get(label_g, 0)} rows, not one"
            )
    path.write_text("".join(edited), encoding="utf-8")

    # Stage boundary (CLAUDE.md): what was meant to be written is what the file now says.
    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert written["weighing_date"] == weighing_date, "weighing_date was not written"
    by_label = {row["label_g"]: row for row in written["filaments"]}
    for label_g, force in forces_mn.items():
        assert by_label[label_g]["force_measured_mn"] == float(f"{force:g}"), label_g
    if balance is not None:
        assert written["weighing_balance"] == balance, "weighing_balance was not written"


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

        grid = QGridLayout()
        grid.setHorizontalSpacing(GROUP_GAP_PX)
        for column, key in enumerate(("label", "size", "nominal", "measured")):
            head = label(SIZE_SMALL, colour=SECONDARY)
            head.setText(words[key])
            grid.addWidget(head, 0, column)
        self.measured: dict[str, QLineEdit] = {}
        for row, filament in enumerate(filaments["filaments"], start=1):
            for column, key in enumerate(SHOWN_KEYS):
                cell = label(SIZE_SMALL)
                cell.setText(f"{filament[key]}")
                grid.addWidget(cell, row, column)
            field = line_edit()
            field.setFixedWidth(MEASURED_COLUMN_PX)
            if filament["force_measured_mn"] is not None:
                field.setText(f"{filament['force_measured_mn']:g}")
            grid.addWidget(field, row, len(SHOWN_KEYS))
            self.measured[filament["label_g"]] = field
        table = QWidget()
        table.setLayout(grid)
        scroll = QScrollArea()
        scroll.setWidget(table)
        scroll.setWidgetResizable(True)

        self.weighing_date = line_edit()
        self.weighing_date.setText(filaments["weighing_date"] or "")
        self.balance = line_edit()
        self.balance.setText(filaments["weighing_balance"] or "")
        self.save_button = button(words["save_forces"], SIZE_BODY)
        self.save_button.clicked.connect(self.save)
        self.forces_status = label(SIZE_SMALL, wrap=True, colour=SECONDARY)

        environment = label(SIZE_BODY)
        environment.setText(words["environment"])
        self.temperature = line_edit()
        self.temperature.setFixedWidth(FIELD_PX)
        self.humidity = line_edit()
        self.humidity.setFixedWidth(FIELD_PX)
        self.environment_button = button(words["use_environment"], SIZE_BODY)
        self.environment_button.clicked.connect(self.hand_on_environment)
        self.environment_status = label(SIZE_SMALL, wrap=True, colour=SECONDARY)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(title)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addWidget(heading)
        layout.addWidget(scroll, 1)
        layout.addLayout(_field_row(words["weighing_date"], self.weighing_date))
        layout.addLayout(_field_row(words["weighing_balance"], self.balance))
        layout.addWidget(self.save_button)
        layout.addWidget(self.forces_status)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addWidget(environment)
        layout.addLayout(_field_row(words["room_temperature"], self.temperature))
        layout.addLayout(_field_row(words["relative_humidity"], self.humidity))
        layout.addWidget(self.environment_button)
        layout.addWidget(self.environment_status)

    def _report(self, target, message: str, problem: bool) -> None:
        target.setText(message)
        target.setStyleSheet(f"color: {DISCONNECTED_COLOUR if problem else SECONDARY};")

    def save(self) -> bool:
        """Validate what was typed and write it. Reports, never raises, on a typing mistake."""
        words = self.text["instruments"]
        forces: dict[str, float] = {}
        for label_g, field in self.measured.items():
            typed = field.text().strip()
            if not typed:
                continue
            try:
                force = parse_number(typed)
            except ValueError:
                force = None
            if force is None or not force > 0:
                self._report(
                    self.forces_status,
                    words["invalid_force"].format(filament=label_g, value=typed),
                    True,
                )
                return False
            forces[label_g] = force
        if not forces:
            self._report(self.forces_status, words["nothing_to_save"], True)
            return False
        typed_date = self.weighing_date.text().strip()
        if not typed_date:
            self._report(self.forces_status, words["date_required"], True)
            return False
        try:
            date.fromisoformat(typed_date)
        except ValueError:
            message = words["invalid_date"].format(value=typed_date)
            self._report(self.forces_status, message, True)
            return False
        balance = self.balance.text().strip() or None
        write_filament_forces(forces, typed_date, balance, self.path)
        self._report(self.forces_status, words["saved"].format(value=len(forces)), False)
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


def _field_row(caption: str, field: QLineEdit) -> QHBoxLayout:
    row = QHBoxLayout()
    text = label(SIZE_SMALL, colour=SECONDARY)
    text.setText(caption)
    row.addWidget(text)
    row.addWidget(field, 1)
    return row
