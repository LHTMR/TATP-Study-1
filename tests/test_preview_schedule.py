"""The schedule preview. SPEC.md 7.2.

`render` returns lines rather than printing them so that what the experimenter reads is what a
test reads. What is pinned is that every column SPEC.md 7.2 names appears, that an unset value
prints as a dash rather than as a plausible number, and that the warnings are shown as warnings
that do not block.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tatp import config as cfg
from tests.test_schedule import make
from tools import preview_schedule

T_ZERO = datetime(2026, 8, 23, 9, 30, 0)
TEXT = cfg.load("sv", "en").experimenter_text


def test_the_table_carries_every_column_the_spec_names():
    lines = preview_schedule.render(make(), T_ZERO, TEXT)
    header = next(line for line in lines if line.startswith("Block"))
    for column in ("Block", "Type", "Offset", "Clock", "Duration"):
        assert column in header


def test_an_unset_duration_prints_as_a_dash_and_not_as_a_number():
    """A guessed duration in a printed table is indistinguishable from a measured one."""
    schedule = make(expected_duration_min={"pinprick": None, "touch": None})
    lines = preview_schedule.render(schedule, T_ZERO, TEXT)
    row = next(line for line in lines if line.startswith("1  "))
    assert preview_schedule.UNSET in row


def test_an_overridden_block_says_so():
    schedule = make(overrides=[{"index": 2, "offset_min": 31.0}])
    lines = preview_schedule.render(schedule, T_ZERO, TEXT)
    assert any(line.startswith("2 ") and "override" in line for line in lines)
    assert any(line.startswith("1 ") and "generated" in line for line in lines)


def test_the_windows_and_the_total_are_printed():
    lines = preview_schedule.render(make(), T_ZERO, TEXT)
    text = "\n".join(lines).lower()
    for name in ("sensitisation", "capsaicin", "rekindle", "intervention"):
        assert name in text
    assert "schedule runs to" in text


def test_warnings_are_shown_as_not_blocking():
    """SPEC.md 7.3. A preview reading like an error would push someone into 'fixing' a pilot."""
    schedule = make(overrides=[{"index": 1, "offset_min": 5.0}])
    text = "\n".join(preview_schedule.render(schedule, T_ZERO, TEXT)).lower()
    assert "none prevents the schedule running" in text
    assert "capsaicin window" in text


def test_a_clean_schedule_says_so():
    assert "No warnings." in preview_schedule.render(make(), T_ZERO, TEXT)


@pytest.mark.parametrize("language", ("sv", "en"))
def test_every_warning_has_wording_in_both_languages(language):
    """docs/LOG.md N7.U10: a warning key with no wording, or wording asking for a value the
    warning does not carry, would stop the preview. A grid breaking every rule at once."""
    text = cfg.load(language, language).experimenter_text
    schedule = make(
        n_pinprick_blocks=3, n_touch_blocks=1,
        overrides=[{"index": 1, "offset_min": 5.0}, {"index": 3, "offset_min": 30.0}],
        validation={"max_session_duration_min": 10.0},
    )
    unset = make(expected_duration_min={"pinprick": None, "touch": None})
    warnings = schedule.warnings() + unset.warnings()
    assert {w.key for w in warnings} >= {"in_window", "not_alternating", "too_long",
                                         "durations_unset", "out_of_order"}
    for warning in warnings:
        assert warning.describe(text)
    assert set(text["schedule_warnings"]) >= {w.key for w in warnings}


def test_the_start_time_sets_the_wall_clock_reference():
    now = datetime(2026, 8, 23, 14, 0, 0)
    assert preview_schedule.t_zero_from(None, now) == now
    assert preview_schedule.t_zero_from("09:30", now) == now.replace(hour=9, minute=30)
