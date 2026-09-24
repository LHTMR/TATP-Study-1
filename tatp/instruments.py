"""Instruments and environment, launcher entry 2. SPEC.md 8.1, 14.2.

Two jobs.

**Filament weighing.** The experimenter enters a precision-balance measurement for each
filament, and the weighing date, and they are written into `config/filaments.yaml`. Only a
re-weighed row's `force_measured_mn` and `weighed_date` change, with the file-level
`weighing_date` (the latest row date) and `weighing_balance`: the file is edited line by line
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
    QGridLayout,
    QHBoxLayout,
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
    label,
    line_edit,
    stylesheet,
)

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
MEASURED_COLUMN_PX = 110
FIELD_PX = 90

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
    balance: str | None,
    path: Path = FILAMENTS_PATH,
) -> int:
    """Write measured forces, by gram label, into `filaments.yaml`. Returns the rows written.

    Only a row whose force differs from what the file holds is written, and it gets
    `weighed_date`: re-saving the dialog does not re-date filaments nobody re-weighed. The
    file-level `weighing_date` becomes the latest row date, which is what the session file
    records and what open item 1 checks. `balance`, if given, replaces `weighing_balance`.

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
    if not changed and (balance is None or balance == old["weighing_balance"]):
        return 0

    dates = [row["weighed_date"] for row in old["filaments"] if row["weighed_date"]]
    if changed:
        dates.append(weighed_date)
    latest = max(dates) if dates else None

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
        if latest is not None:
            body = _set_scalar(body, "weighing_date", json.dumps(latest))
        if balance is not None:
            # JSON's string syntax is valid YAML, and escapes whatever was typed.
            body = _set_scalar(body, "weighing_balance", json.dumps(balance))
        edited.append(body + ending)
    for label_g in changed:
        if matched.get(label_g) != 1:
            raise InstrumentsError(
                f"{path}: filament {label_g!r} matched {matched.get(label_g, 0)} rows, not one"
            )
    new_text = "".join(edited)

    # Stage boundary (CLAUDE.md), before the write: the new file is what was meant.
    new = yaml.safe_load(new_text)
    _validate(old, new, changed, weighed_date, latest, balance)

    handle = tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=f".{path.name}.", suffix=TEMP_SUFFIX, delete=False
    )
    with handle:
        handle.write(new_text.encode(ENCODING))
    os.replace(handle.name, path)
    return len(changed)


def _validate(old: dict, new: dict, changed: Mapping[str, float], weighed_date: str,
              latest: str | None, balance: str | None) -> None:
    cfg.validate_file("filaments.yaml", new)
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
    if balance is not None and new["weighing_balance"] != balance:
        raise InstrumentsError("weighing_balance would not be what was entered")


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

        # Empty, not the last weighing's date: it dates what is weighed now, and an old date
        # carried over would be recorded against a new measurement.
        self.weighing_date = line_edit()
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
            if force is None or not (math.isfinite(force) and force > 0):
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
            parse_date(typed_date)
        except ValueError:
            message = words["invalid_date"].format(value=typed_date)
            self._report(self.forces_status, message, True)
            return False
        balance = self.balance.text().strip() or None
        written = write_filament_forces(forces, typed_date, balance, self.path)
        if not written:
            # Every force typed is what the file already holds: nothing is re-dated.
            self._report(self.forces_status, words["nothing_to_save"], True)
            return False
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


def _field_row(caption: str, field: QLineEdit) -> QHBoxLayout:
    row = QHBoxLayout()
    text = label(SIZE_SMALL, colour=SECONDARY)
    text.setText(caption)
    row.addWidget(text)
    row.addWidget(field, 1)
    return row
