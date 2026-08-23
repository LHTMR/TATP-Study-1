"""The schedule preview. SPEC.md 7.2.

`render` returns lines rather than printing them so that what the experimenter reads is what a
test reads. What is pinned is that every column SPEC.md 7.2 names appears, that an unset value
prints as a dash rather than as a plausible number, and that the warnings are shown as warnings
that do not block.
"""

from __future__ import annotations

from datetime import datetime

from tests.test_schedule import make
from tools import preview_schedule

T_ZERO = datetime(2026, 8, 23, 9, 30, 0)


def test_the_table_carries_every_column_the_spec_names():
    lines = preview_schedule.render(make(), T_ZERO)
    header = next(line for line in lines if line.startswith("Block"))
    for column in ("Block", "Type", "Offset", "Clock", "Duration"):
        assert column in header


def test_an_unset_duration_prints_as_a_dash_and_not_as_a_number():
    """A guessed duration in a printed table is indistinguishable from a measured one."""
    schedule = make(expected_duration_min={"pinprick": None, "touch": None})
    lines = preview_schedule.render(schedule, T_ZERO)
    row = next(line for line in lines if line.startswith("1  "))
    assert preview_schedule.UNSET in row


def test_an_overridden_block_says_so():
    lines = preview_schedule.render(make(overrides=[{"index": 2, "offset_min": 31.0}]), T_ZERO)
    assert any(line.startswith("2 ") and "override" in line for line in lines)
    assert any(line.startswith("1 ") and "generated" in line for line in lines)


def test_the_windows_and_the_total_are_printed():
    lines = preview_schedule.render(make(), T_ZERO)
    text = "\n".join(lines)
    for name in ("sensitisation", "capsaicin", "rekindle", "intervention"):
        assert name in text
    assert "Schedule runs to" in text


def test_warnings_are_shown_as_not_blocking():
    """SPEC.md 7.3. A preview reading like an error would push someone into 'fixing' a pilot."""
    lines = preview_schedule.render(make(overrides=[{"index": 1, "offset_min": 5.0}]), T_ZERO)
    text = "\n".join(lines)
    assert "None prevents the schedule running" in text
    assert "capsaicin window" in text


def test_a_clean_schedule_says_so():
    assert "No warnings." in preview_schedule.render(make(), T_ZERO)


def test_the_start_time_sets_the_wall_clock_reference():
    now = datetime(2026, 8, 23, 14, 0, 0)
    assert preview_schedule.t_zero_from(None, now) == now
    assert preview_schedule.t_zero_from("09:30", now) == now.replace(hour=9, minute=30)
