"""Session clock. SPEC.md 3, 7.4, 15, 17.3."""

from __future__ import annotations

import pytest

from tatp.clock import Clock


def test_t_session_is_undefined_before_sensitisation():
    """SPEC.md 7.4: t=0 is the start of heat sensitisation, not the start of the process."""
    clock = Clock()
    assert clock.t_session_s() is None
    assert not clock.session_started
    clock.start_session()
    assert clock.session_started
    assert clock.t_session_s() == pytest.approx(0.0, abs=0.5)


def test_t_zero_is_set_once():
    clock = Clock()
    clock.start_session()
    with pytest.raises(RuntimeError, match="already been set"):
        clock.start_session()


def test_resume_keeps_the_original_t_zero():
    """SPEC.md 15: the rekindle is timed from sensitisation, not from the restart."""
    clock = Clock()
    clock.resume_session(1800.0)
    assert clock.t_session_s() == pytest.approx(1800.0, abs=0.5)


def test_speed_scales_elapsed_time_and_timer_durations():
    """SPEC.md 17.3: the validator runs a whole session on an accelerated clock."""
    fast = Clock(speed=60.0)
    assert fast.scaled_ms(60.0) == 1000
    assert Clock().scaled_ms(60.0) == 60_000
    assert fast.scaled_ms(-1.0) == 0


def test_speed_must_be_positive():
    with pytest.raises(ValueError, match="must be positive"):
        Clock(speed=0)


def test_wall_clock_stamps_are_recorded_in_a_sortable_form():
    clock = Clock()
    assert len(clock.wall_iso()) == len("2026-08-23T12:00:00.000")
    assert clock.wall_iso()[10] == "T"
    assert len(clock.filename_stamp()) == len("2026-08-23_12-00-00")
