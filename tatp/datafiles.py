"""Writing the session data files. SPEC.md 14.

The column list is not duplicated here. `docs/DATA_SCHEMA.md` is parsed, so the writer and
`tools/validate_session.py` read the same definition and cannot drift from the documentation or
from each other. Editing the markdown changes both.

Durability (SPEC.md 14.3): every row is opened, appended, flushed and closed as it is produced,
so a crash loses at most the trial in progress. There is no long-lived file handle holding a
buffer that a crash would discard.

This is the one module where a narrow `try`/`except` is permitted (CLAUDE.md), and only for the
case it exists for: a row that has already been collected from a participant must not be lost
because a write failed. `OSError` is caught, the row is held, and it is retried on the next
write and again at close. Nothing else is caught, and the failure is counted rather than
swallowed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tatp.clock import ISO_FORMAT
from tatp.config import REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "docs" / "DATA_SCHEMA.md"

COLUMN_HEADER = ("Column", "Type", "Unit", "Required", "Description")
SESSION_KEY_HEADER = ("Key", "Unit", "Notes")
TYPES = ("str", "int", "float", "bool", "iso8601")

FILENAME_TEMPLATE = "TATP1_{stamp}_P{code}_S{session}_{table}.csv"


class SchemaError(Exception):
    """docs/DATA_SCHEMA.md does not follow its own parsing contract."""


class DataError(Exception):
    """A row does not match the schema. Always fatal -- a wrong column is a wrong data file."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    unit: str
    required: bool


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


def _cells(line: str, count: int) -> list[str]:
    """Split a markdown table row into `count` cells.

    Everything after the last wanted separator stays in the final cell, so a `|` inside a
    description does not shift the columns.
    """
    parts = line.strip().strip("|").split("|", count - 1)
    return [part.strip() for part in parts]


def _is_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def parse_schema(path: Path = SCHEMA_PATH) -> tuple[dict[str, Table], tuple[str, ...]]:
    """Read the table definitions and the session-key list out of DATA_SCHEMA.md.

    Returns (tables by name, session keys in order). A heading with no table under it, an
    unknown type or a malformed `Required` cell is a SchemaError -- the schema is the contract,
    so a defect in it must stop the program rather than produce a subtly wrong file.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    tables: dict[str, Table] = {}
    session_keys: list[str] = []

    table_name: str | None = None
    in_session_keys = False
    header_seen = False
    columns: list[Column] = []

    def finish() -> None:
        nonlocal table_name, columns, header_seen
        if table_name is not None:
            if not columns:
                raise SchemaError(f"{path.name}: table {table_name!r} has no columns")
            tables[table_name] = Table(table_name, tuple(columns))
        table_name, columns, header_seen = None, [], False

    for number, line in enumerate(lines, start=1):
        if line.startswith("### "):
            finish()
            table_name = line[4:].strip()
            in_session_keys = False
            continue
        if line.startswith("#### "):
            # A subsection ends the table above it; the session-key list is the only one.
            finish()
            in_session_keys = line[5:].strip() == "session keys"
            continue
        if line.startswith("#"):
            finish()
            in_session_keys = False
            continue

        if not _is_row(line):
            continue

        cells = _cells(line, 5 if not in_session_keys else 3)
        if in_session_keys:
            if tuple(cells) == SESSION_KEY_HEADER or set(cells[0]) <= {"-"}:
                continue
            session_keys.append(cells[0].strip("`"))
            continue

        if table_name is None:
            continue
        if tuple(cells) == COLUMN_HEADER:
            header_seen = True
            continue
        if not header_seen or set(cells[0]) <= {"-"}:
            continue
        name, type_name, unit, required = cells[0], cells[1], cells[2], cells[3]
        if type_name not in TYPES:
            raise SchemaError(
                f"{path.name} line {number}: type {type_name!r} is not one of {list(TYPES)}"
            )
        if required not in ("yes", "no"):
            raise SchemaError(
                f"{path.name} line {number}: Required is {required!r}, expected 'yes' or 'no'"
            )
        columns.append(Column(name, type_name, unit, required == "yes"))
    finish()

    # Stage boundary (CLAUDE.md): everything downstream indexes into these.
    assert tables, f"{path.name} defines no tables"
    assert session_keys, f"{path.name} defines no session keys"
    if "session" not in tables:
        raise SchemaError(f"{path.name}: no 'session' table")
    return tables, tuple(session_keys)


def format_value(value: object, column: Column, table_name: str) -> str:
    """One Python value as written to the file. Missing is the empty string (SPEC.md 14)."""
    where = f"{table_name}.{column.name}"
    if value is None or value == "":
        if column.required:
            raise DataError(f"{where} is required, but no value was given")
        return ""

    if column.type == "bool":
        if not isinstance(value, bool):
            raise DataError(f"{where} is {type(value).__name__}, expected bool")
        return "true" if value else "false"
    # bool is a subclass of int, so an accidental True where a number belongs must not pass.
    if isinstance(value, bool):
        raise DataError(f"{where} is bool, expected {column.type}")
    if column.type == "int":
        if not isinstance(value, int):
            raise DataError(f"{where} is {type(value).__name__}, expected int")
        return str(value)
    if column.type == "float":
        if not isinstance(value, (int, float)):
            raise DataError(f"{where} is {type(value).__name__}, expected float")
        return str(float(value))
    if column.type == "iso8601":
        datetime.strptime(str(value), ISO_FORMAT)  # malformed stamps are a defect, not data
        return str(value)
    return str(value)


class DataFileCollection:
    """Every data file for one session. SPEC.md 14.2, 14.3.

    One file per table, created on the first row written to it, named by session start so that
    filenames are unique and an existing file is never overwritten.
    """

    def __init__(
        self,
        folder: Path,
        participant_code: str,
        session_number: int,
        stamp: str,
        schema_path: Path = SCHEMA_PATH,
    ):
        self.tables, self.session_keys = parse_schema(schema_path)
        self.folder = folder
        self.participant_code = participant_code
        self.session_number = session_number
        self.stamp = stamp
        self.write_failures = 0
        self._pending: dict[str, list[list[str]]] = {}
        self._session_keys_written: list[str] = []
        folder.mkdir(parents=True, exist_ok=True)

    def path(self, table_name: str) -> Path:
        if table_name not in self.tables:
            raise DataError(f"no table {table_name!r} in the schema")
        return self.folder / FILENAME_TEMPLATE.format(
            stamp=self.stamp,
            code=self.participant_code,
            session=self.session_number,
            table=table_name,
        )

    def row_values(self, table_name: str, values: dict[str, object]) -> list[str]:
        """Validate a row against the schema and render it. Raises before anything is written.

        Nothing reaches the file unless the whole row is valid.
        """
        table = self.tables.get(table_name)
        if table is None:
            raise DataError(f"no table {table_name!r} in the schema")
        unknown = set(values) - set(table.column_names)
        if unknown:
            raise DataError(
                f"{table_name}: {sorted(unknown)} are not columns of this table. The schema is "
                f"docs/DATA_SCHEMA.md."
            )
        return [format_value(values.get(c.name), c, table_name) for c in table.columns]

    def write(self, table_name: str, **values: object) -> None:
        """Append one row, flushed to disk before returning (SPEC.md 14.3)."""
        row = self.row_values(table_name, values)
        self._append(table_name, row)

    def write_session(self, values: dict[str, object]) -> None:
        """Append session provenance rows, in the order DATA_SCHEMA.md lists the keys.

        The session file is written in two parts -- most keys at session start, the closing ones
        at session end -- so this takes whichever subset is known now. Each key is written
        exactly once across the session.
        """
        unknown = set(values) - set(self.session_keys)
        if unknown:
            raise DataError(
                f"session: {sorted(unknown)} are not session keys. The list is under "
                f"'session keys' in docs/DATA_SCHEMA.md."
            )
        repeated = set(values) & set(self._session_keys_written)
        if repeated:
            raise DataError(f"session: {sorted(repeated)} have already been written")
        for key in self.session_keys:
            if key not in values:
                continue
            self._session_keys_written.append(key)
            self.write("session", key=key, value=_as_text(values[key]))

    def close(self) -> None:
        """Write the session keys still outstanding, then retry anything a failed write held.

        An unknown value is still written, with an empty value: DATA_SCHEMA.md requires that an
        absent row and an empty value never be confusable.
        """
        outstanding = {k: "" for k in self.session_keys if k not in self._session_keys_written}
        if outstanding:
            self.write_session(outstanding)
        for table_name, rows in list(self._pending.items()):
            self._pending[table_name] = []
            for row in rows:
                self._append(table_name, row)

    def _append(self, table_name: str, row: list[str]) -> None:
        path = self.path(table_name)
        held = self._pending.pop(table_name, [])
        try:
            new_file = not path.exists()
            with path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                if new_file:
                    writer.writerow(self.tables[table_name].column_names)
                for earlier in held:
                    writer.writerow(earlier)
                writer.writerow(row)
                handle.flush()
        except OSError:
            # The one permitted catch (CLAUDE.md): a trial already collected from a participant
            # must not be lost because the disk was busy or the folder briefly unavailable.
            # Held rows are retried on the next write and again at close.
            self._pending[table_name] = [*held, row]
            self.write_failures += 1


def _as_text(value: object) -> str:
    """Session values are all written as text, with booleans in the file's convention."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)
