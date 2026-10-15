"""Data file writing. SPEC.md 14.

The schema is parsed from docs/DATA_SCHEMA.md rather than restated, so these tests check the
parse against the real document and then check the writer against the parse.
"""

from __future__ import annotations

import csv
import os

import pytest

from tatp import datafiles
from tatp.datafiles import DataError, DataFileCollection, SchemaError

STAMP = "2026-08-23_14-05-09"
ISO = "2026-08-23T14:05:09.812"

EXPECTED_TABLES = {
    "session",
    "log",
    "pinprick",
    "calibration_pinprick",
    "brush",
    "mapping",
    "sh_area",
    "touch_ratings",
    "touchcal_adjust",
    "touchcal_estimate",
    "touchcal_fit",
    "touchcal_compare",
    "garment",
    # Added during the acceleration push, beyond SPEC.md 14.2's list.
    "blocks",
    "discards",
}


@pytest.fixture(scope="module")
def schema():
    return datafiles.parse_schema()


@pytest.fixture
def files(tmp_path):
    collection = DataFileCollection(tmp_path / "data", "01", 1, STAMP)
    yield collection
    collection.release()


def test_every_table_in_spec_14_2_is_defined(schema):
    tables, _ = schema
    # A subset, not equality: a stream that adds a table adds it here without touching the rest.
    assert EXPECTED_TABLES <= set(tables)


def test_columns_keep_the_order_of_the_document(schema):
    tables, _ = schema
    assert tables["session"].column_names == ("key", "value")
    assert tables["log"].column_names[:3] == ("timestamp_iso", "t_session_s", "phase")
    assert tables["log"].columns[1].required is False
    assert tables["log"].columns[2].required is True
    assert tables["log"].columns[1].unit == "s"


def test_session_keys_are_read_in_order(schema):
    _, keys = schema
    assert keys[0] == "participant_code"
    assert keys[-1] == "abort_reason"
    assert len(keys) == len(set(keys)), "a duplicated session key would be written twice"
    for key in ("condition", "git_sha", "config_sha256", "sensitisation_start_iso"):
        assert key in keys


def test_a_pipe_inside_a_description_does_not_shift_the_columns(tmp_path):
    path = tmp_path / "SCHEMA.md"
    path.write_text(
        "### session\n\n"
        "| Column | Type | Unit | Required | Description |\n"
        "|---|---|---|---|---|\n"
        "| key | str | - | yes | A description with a | pipe in it |\n"
        "| value | str | - | no | Second |\n\n"
        "#### session keys\n\n"
        "| Key | Unit | Notes |\n"
        "|---|---|---|\n"
        "| `only_key` | - | note |\n",
        encoding="utf-8",
    )
    tables, keys = datafiles.parse_schema(path)
    assert tables["session"].column_names == ("key", "value")
    assert keys == ("only_key",)


def test_an_unknown_type_in_the_schema_is_fatal(tmp_path):
    path = tmp_path / "SCHEMA.md"
    path.write_text(
        "### session\n\n"
        "| Column | Type | Unit | Required | Description |\n"
        "|---|---|---|---|---|\n"
        "| key | decimal | - | yes | Wrong type |\n\n"
        "#### session keys\n\n"
        "| Key | Unit | Notes |\n"
        "|---|---|---|\n"
        "| `only_key` | - | note |\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="decimal"):
        datafiles.parse_schema(path)


def _read(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_a_row_is_written_with_the_header_and_the_schema_column_order(files):
    files.write(
        "log",
        timestamp_iso=ISO,
        phase="setup",
        event="session_started",
        origin="software",
        severity="info",
    )
    path = files.path("log")
    assert path.name == "TATP1_2026-08-23_14-05-09_P01_S1_log.csv"
    rows = _read(path)
    assert rows[0] == list(files.tables["log"].column_names)
    assert rows[1][0] == ISO
    assert rows[1][1] == "", "t_session_s is empty before sensitisation, not zero"
    assert rows[1][4] == "session_started"
    assert len(rows[1]) == len(rows[0])


def test_rows_append_and_the_header_is_written_once(files):
    for index in range(3):
        files.write(
            "log",
            timestamp_iso=ISO,
            phase="setup",
            event=f"event_{index}",
            origin="software",
            severity="info",
        )
    rows = _read(files.path("log"))
    assert len(rows) == 4
    assert [r[4] for r in rows[1:]] == ["event_0", "event_1", "event_2"]


def test_a_second_collection_appends_rather_than_overwriting(tmp_path):
    """SPEC.md 14.3: the software never overwrites an existing data file."""
    for _ in range(2):
        collection = DataFileCollection(tmp_path / "data", "01", 1, STAMP)
        collection.write(
            "log",
            timestamp_iso=ISO,
            phase="setup",
            event="e",
            origin="software",
            severity="info",
        )
        collection.release()
    rows = _read(tmp_path / "data" / f"TATP1_{STAMP}_P01_S1_log.csv")
    assert len(rows) == 3


def test_booleans_are_words_and_missing_is_empty(files):
    files.write(
        "garment",
        timestamp_iso=ISO,
        phase="setup",
        driver="MockGarment",
        event="set_pressure",
        channel=3,
        pressure_kpa=42.0,
        clamped=False,
    )
    header, row = _read(files.path("garment"))
    written = dict(zip(header, row, strict=True))
    assert written["clamped"] == "false"
    assert written["pressure_kpa"] == "42.0"
    assert written["channel"] == "3"
    assert written["requested_kpa"] == ""
    assert written["detail"] == ""


def test_a_missing_required_value_is_refused(files):
    with pytest.raises(DataError, match="severity is required"):
        files.write(
            "log", timestamp_iso=ISO, phase="setup", event="e", origin="software"
        )
    assert not files.path("log").exists(), "nothing is written when the row is invalid"


def test_a_column_that_is_not_in_the_schema_is_refused(files):
    with pytest.raises(DataError, match="not columns of this table"):
        files.write(
            "log",
            timestamp_iso=ISO,
            phase="setup",
            event="e",
            origin="software",
            severity="info",
            rating_percent=50.0,
        )


def test_a_boolean_where_a_number_belongs_is_refused(files):
    with pytest.raises(DataError, match="expected int"):
        files.write(
            "log",
            timestamp_iso=ISO,
            phase="setup",
            block_index=True,
            event="e",
            origin="software",
            severity="info",
        )


def test_a_malformed_timestamp_is_refused(files):
    with pytest.raises(ValueError):
        files.write(
            "log",
            timestamp_iso="23/08/2026 14:05",
            phase="setup",
            event="e",
            origin="software",
            severity="info",
        )


def test_session_keys_are_written_once_each_and_in_order(files):
    files.write_session(
        {"condition": "sham", "participant_code": "01", "session_number": 1}
    )
    rows = _read(files.path("session"))
    assert [r[0] for r in rows[1:]] == ["participant_code", "session_number", "condition"]
    with pytest.raises(DataError, match="already been written"):
        files.write_session({"condition": "ct_targeted"})
    with pytest.raises(DataError, match="not session keys"):
        files.write_session({"favourite_colour": "blue"})


def test_close_writes_every_remaining_key_with_an_empty_value(files):
    """An absent row and an empty value must not be confusable (DATA_SCHEMA.md)."""
    files.write_session({"participant_code": "01"})
    files.close()
    rows = _read(files.path("session"))
    assert [r[0] for r in rows[1:]] == list(files.session_keys)
    written = dict(zip([r[0] for r in rows[1:]], [r[1] for r in rows[1:]], strict=True))
    assert written["participant_code"] == "01"
    assert written["abort_reason"] == ""


def test_a_write_failure_holds_the_row_and_retries_it(files):
    """CLAUDE.md: a trial already collected from a participant must not be lost."""
    files.write(
        "log", timestamp_iso=ISO, phase="setup", event="first", origin="software",
        severity="info",
    )
    # The file is held open between rows, so a failure has to come from the open handle: closing
    # its descriptor underneath it makes the next flush raise, as a vanished disk would.
    os.close(files._handles["log"].fileno())
    files.write(
        "log", timestamp_iso=ISO, phase="setup", event="lost?", origin="software",
        severity="info",
    )
    assert files.write_failures == 1

    files.write(
        "log", timestamp_iso=ISO, phase="setup", event="third", origin="software",
        severity="info",
    )
    rows = _read(files.path("log"))
    assert [r[4] for r in rows[1:]] == ["first", "lost?", "third"]


def _log(files, event):
    files.write(
        "log", timestamp_iso=ISO, phase="setup", event=event, origin="software",
        severity="info",
    )


def test_each_row_is_on_disk_before_write_returns(files):
    """SPEC.md 14.3: the file stays open, so the flush is what makes a row survive a crash."""
    _log(files, "first")
    assert [r[4] for r in _read(files.path("log"))[1:]] == ["first"]
    _log(files, "second")
    assert [r[4] for r in _read(files.path("log"))[1:]] == ["first", "second"]


def test_a_file_deleted_while_open_is_recreated_with_its_header(files):
    """Reopening per row recreated a deleted file; holding it open must not write into the
    deleted one instead, which macOS allows (docs/LOG.md N7.F13a)."""
    _log(files, "gone")
    files.path("log").unlink()
    _log(files, "after")
    rows = _read(files.path("log"))
    assert rows[0] == list(files.tables["log"].column_names)
    assert [r[4] for r in rows[1:]] == ["after"]


def test_release_closes_the_files_and_a_later_write_reopens_them(files):
    """A session left open for a resume lets its files go (SPEC.md 15) without closing keys."""
    _log(files, "before")
    files.release()
    assert not files._handles
    _log(files, "after")
    rows = _read(files.path("log"))
    assert [r[4] for r in rows[1:]] == ["before", "after"], "the header is written once"
    assert not files.path("session").exists(), "release writes no session keys"
    files.release()
