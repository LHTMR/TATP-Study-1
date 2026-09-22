"""The end-to-end validator. SPEC.md 17.3.

Two things are tested: that a real slice session passes every built check, and that each check
fails on data broken in the way it exists to catch. The second matters more. A check that
cannot fail is the empty-validator failure in another form.
"""

from __future__ import annotations

import csv
import shutil

import pytest

from tools import validate_session as vs

SEED = 3


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("validate")
    first = vs.run(root / "first", SEED)
    second = vs.run(root / "second", SEED)
    assert first.completed and second.completed
    return first, second


@pytest.fixture
def copy(runs, tmp_path):
    """A writable copy of the first run's files, for breaking."""
    target = tmp_path / "broken"
    shutil.copytree(runs[0].folder, target)
    return target


def _file(folder, table):
    [path] = folder.glob(f"*_{table}.csv")
    return path


def _edit(folder, table, change):
    """Rewrite one table through `change(header, rows) -> (header, rows)`."""
    path = _file(folder, table)
    with path.open(encoding="utf-8", newline="") as handle:
        header, *rows = list(csv.reader(handle))
    header, rows = change(header, rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows([header, *rows])


def _set(table_column, value):
    column = table_column

    def change(header, rows):
        index = header.index(column)
        rows[0][index] = value
        return header, rows
    return change


def _set_session(key, value):
    def change(header, rows):
        for row in rows:
            if row[0] == key:
                row[1] = value
        return header, rows
    return change


def _results(runs, folder=None):
    first, second = runs
    tables = vs.Tables.read(folder or first.folder)
    return {r.name: r for r in vs.check(tables, vs.Tables.read(second.folder))}


# -- a real session -------------------------------------------------------------------------


def test_a_real_slice_session_passes_every_built_check(runs):
    results = _results(runs)
    failed = {name: r.messages for name, r in results.items() if r.status == "fail"}
    assert not failed


def test_every_deferred_check_is_reported_as_skipped_and_counted(runs):
    results = _results(runs)
    skipped = {name for name, r in results.items() if r.status == "skip"}
    assert skipped == set(vs.DEFERRED)
    summary = vs.report(list(results.values())).splitlines()[-1]
    assert f"{len(vs.DEFERRED)} skipped" in summary


def test_every_deferral_says_what_it_waits_for():
    for name, reason in vs.DEFERRED.items():
        assert "Milestone" in reason or "open item" in reason, name


def test_the_table_lists_cover_the_schema():
    schema, _ = vs.parse_schema()
    assert set(vs.PRODUCED) | set(vs.NOT_YET_PRODUCED) == set(schema)
    assert not set(vs.PRODUCED) & set(vs.NOT_YET_PRODUCED)


def test_the_folder_it_clears_must_be_under_data(tmp_path):
    with pytest.raises(AssertionError):
        vs._fresh(tmp_path)


# -- each check fails on what it exists to catch --------------------------------------------


def test_a_missing_table_fails(runs, copy):
    _file(copy, "pinprick").unlink()
    results = _results(runs, copy)
    assert results["tables_present"].status == "fail"
    # A check that reads the missing table reports it, rather than crashing the run.
    listed = results["pinprick_filament_is_listed"]
    assert listed.status == "fail"
    assert "pinprick" in listed.messages[0]


def test_reordered_columns_fail(runs, copy):
    _edit(copy, "pinprick", lambda h, r: (h[::-1], [row[::-1] for row in r]))
    assert _results(runs, copy)["columns_match_schema"].status == "fail"


def test_an_empty_required_field_fails(runs, copy):
    _edit(copy, "pinprick", _set("phase", ""))
    assert _results(runs, copy)["required_fields_present"].status == "fail"


def test_a_value_of_the_wrong_type_fails(runs, copy):
    _edit(copy, "pinprick", _set("intolerable", "1"))
    assert _results(runs, copy)["values_match_types"].status == "fail"


def test_a_missing_session_key_fails(runs, copy):
    _edit(copy, "session", lambda h, r: (h, r[1:]))
    results = _results(runs, copy)
    assert results["session_keys_complete"].status == "fail"
    assert results["allocation_matches"].status == "fail"


def test_an_empty_provenance_value_fails(runs, copy):
    _edit(copy, "session", _set_session("git_sha", ""))
    assert _results(runs, copy)["provenance_populated"].status == "fail"


def test_a_declared_optional_key_may_be_empty(runs, copy):
    _edit(copy, "session", _set_session("abort_reason", ""))
    assert _results(runs, copy)["provenance_populated"].status == "pass"


def test_a_limb_that_disagrees_with_the_allocation_fails(runs, copy):
    expected = vs._allocation_row(vs.PARTICIPANT, vs.SESSION)["limb"]
    other = "left" if expected == "right" else "right"
    _edit(copy, "session", _set_session("limb", other))
    assert _results(runs, copy)["allocation_matches"].status == "fail"


def test_a_condition_that_disagrees_with_the_allocation_fails(runs, copy):
    _edit(copy, "session", _set_session("condition", "not_a_condition"))
    assert _results(runs, copy)["allocation_matches"].status == "fail"


def test_a_timestamp_out_of_order_fails(runs, copy):
    _edit(copy, "log", lambda h, r: (h, r[::-1]))
    assert _results(runs, copy)["timestamps_monotonic"].status == "fail"


def test_an_unlisted_filament_fails(runs, copy):
    _edit(copy, "pinprick", _set("applied_filament_label_g", "999"))
    assert _results(runs, copy)["pinprick_filament_is_listed"].status == "fail"


def test_a_force_that_is_not_the_filaments_fails(runs, copy):
    _edit(copy, "pinprick", _set("force_applied_mn", "1.5"))
    assert _results(runs, copy)["pinprick_filament_is_listed"].status == "fail"


def test_a_timed_out_adjustment_fails(runs, copy):
    _edit(copy, "touchcal_adjust", _set("timed_out", "true"))
    assert _results(runs, copy)["no_adjustment_timed_out"].status == "fail"


def test_an_adjustment_one_tap_short_fails(runs, copy):
    """The lost-tap defect the validator found, as it appears in the data."""
    def change(header, rows):
        index = header.index("produced_pressure_kpa")
        rows[0][index] = str(float(rows[0][index]) - 1.0)
        return header, rows
    _edit(copy, "touchcal_adjust", change)
    assert _results(runs, copy)["adjustment_reached_target"].status == "fail"


def test_a_different_rating_under_the_same_seed_fails(runs, copy):
    _edit(copy, "pinprick", _set("rating_percent", "99.0"))
    result = _results(runs, copy)["repeat_run_is_identical"]
    assert result.status == "fail"
    assert "rating_percent" in result.messages[0]


def test_a_difference_only_in_time_is_not_a_reproducibility_failure(runs, copy):
    _edit(copy, "pinprick", _set("rt_s", "123.0"))
    assert _results(runs, copy)["repeat_run_is_identical"].status == "pass"


def test_a_block_without_its_offsets_fails(runs, copy):
    def change(header, rows):
        event, detail = header.index("event"), header.index("detail")
        for row in rows:
            if row[event] == "block_started":
                row[detail] = "pinprick"
        return header, rows
    _edit(copy, "log", change)
    assert _results(runs, copy)["blocks_record_planned_and_actual"].status == "fail"
