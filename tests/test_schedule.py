"""The session schedule. SPEC.md 7.

Two things are worth pinning here beyond "it generates twelve blocks". First, that validation
**warns and never blocks** (SPEC.md 7.3): a test that asserted the live grid is clean would fail
the day someone edits `schedule.yaml`, which is the file that is meant to change. So the rules
are driven by crafted grids and the live file is only asserted to *generate*.

Second, that a block index is identity rather than position. An override that moves a block does
not renumber it, because `block_index` in an already-written row has to keep meaning the same
block.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tatp import config as cfg
from tatp import schedule as sched

# A grid with the shape of the real one and none of its numbers, so these tests say nothing
# about whether today's `schedule.yaml` is a good schedule.
BASE = {
    "generate": {
        "n_pinprick_blocks": 2,
        "n_touch_blocks": 2,
        "intervention_duration_min": 40.0,
        "intervention_start_offset_min": 20.0,
        "rekindle_offset_min": 40.0,
        "rekindle_duration_min": 5.0,
        "capsaicin_start_offset_min": 2.0,
        "capsaicin_duration_min": 10.0,
        "sensitisation_duration_min": 2.0,
        "first_block_type": "pinprick",
        "expected_duration_min": {"pinprick": 4.0, "touch": 4.0},
    },
    "overrides": [],
    "validation": {
        "max_session_duration_min": 200.0,
        "overdue_alert_margin_s": 60.0,
        "due_alert_lead_s": 30.0,
        "equal_spacing_tolerance_s": 30.0,
    },
}

# BASE generates 25, 35, [rekindle 40-45], 50, 60 -- the same shape as the real grid, a quarter
# the size. Blocks are 4 min long, so there is 1 min of slack before the rekindle and 5 after.
BASE_OFFSETS = [25.0, 35.0, 50.0, 60.0]

# Far outside any intervention these tests configure, so no pause is inserted. For the rules
# that have nothing to do with the rekindle, and would otherwise be read through its arithmetic.
NO_REKINDLE = 999.0

T_ZERO = datetime(2026, 8, 23, 9, 30, 0)


def make(**generate) -> sched.Schedule:
    """The base grid with `generate:` keys replaced. Validation keys via `validation=`."""
    validation = {**BASE["validation"], **generate.pop("validation", {})}
    overrides = generate.pop("overrides", [])
    return sched.generate(
        {
            "generate": {**BASE["generate"], **generate},
            "overrides": overrides,
            "validation": validation,
        }
    )


def evenly(**generate) -> sched.Schedule:
    """Six blocks 10 min apart at 30..80, with no rekindle to widen a gap."""
    return make(
        n_pinprick_blocks=3,
        n_touch_blocks=3,
        intervention_duration_min=60.0,
        rekindle_offset_min=NO_REKINDLE,
        **generate,
    )


# -- generation, SPEC.md 7.1 --------------------------------------------------------------


def test_the_grid_alternates_and_is_evenly_spaced():
    schedule = make()
    assert [b.type for b in schedule.blocks] == ["pinprick", "touch", "pinprick", "touch"]
    assert [b.planned_offset_min for b in schedule.blocks] == BASE_OFFSETS
    assert [b.index for b in schedule.blocks] == [1, 2, 3, 4]
    assert not any(b.overridden for b in schedule.blocks)


def test_the_first_block_type_decides_which_pool_leads():
    assert [b.type for b in make(first_block_type="touch").blocks] == [
        "touch", "pinprick", "touch", "pinprick"
    ]


def test_an_unknown_first_block_type_is_a_configuration_error_not_a_warning():
    """SPEC.md 6. Warn-not-block covers scheduling decisions, not a malformed file."""
    with pytest.raises(cfg.ConfigError, match="first_block_type"):
        make(first_block_type="brush")


def test_unequal_pools_place_the_remainder_at_the_end_and_warn_rather_than_drop_it():
    schedule = make(n_pinprick_blocks=3, n_touch_blocks=1)
    assert [b.type for b in schedule.blocks] == [
        "pinprick", "touch", "pinprick", "pinprick"
    ]
    assert any("does not alternate" in w for w in schedule.warnings())


def test_the_rekindle_takes_its_own_place_in_the_sequence():
    """SPEC.md 7.1. No generated block may land on the rekindle, whatever the parameters."""
    rekindle = make().window("rekindle")
    for schedule in (make(), make(n_touch_blocks=5), make(n_pinprick_blocks=7)):
        assert not any(
            rekindle.start_min <= b.planned_offset_min < rekindle.end_min
            for b in schedule.blocks
        )


def test_the_last_block_lands_on_the_end_of_the_intervention():
    """Which is what delays the first one, and what makes the two halves symmetric."""
    schedule = make()
    intervention = schedule.window("intervention")
    assert schedule.blocks[-1].planned_offset_min == intervention.end_min
    assert schedule.blocks[0].planned_offset_min == intervention.start_min + 5.0
    # Equal clear air either side of the rekindle: 5 min before it, 5 min after.
    rekindle = schedule.window("rekindle")
    assert rekindle.start_min - schedule.blocks[1].planned_offset_min == 5.0
    assert schedule.blocks[2].planned_offset_min - rekindle.end_min == 5.0


def test_a_rekindle_outside_the_intervention_inserts_no_pause():
    """Not an error: piloting may legitimately want a session without one."""
    schedule = evenly()
    assert [b.planned_offset_min for b in schedule.blocks] == [30.0, 40.0, 50.0, 60.0, 70.0,
                                                               80.0]


# -- overrides ------------------------------------------------------------------------------


def test_an_override_replaces_one_block_and_marks_it():
    schedule = make(overrides=[{"index": 2, "offset_min": 33.0, "type": "pinprick"}])
    moved = schedule.block(2)
    assert moved.planned_offset_min == 33.0
    assert moved.type == "pinprick"
    assert moved.overridden
    assert [b.overridden for b in schedule.blocks] == [False, True, False, False]


def test_an_override_takes_the_duration_of_the_type_it_becomes():
    schedule = sched.generate(
        {
            **BASE,
            "generate": {
                **BASE["generate"],
                "expected_duration_min": {"pinprick": 4.0, "touch": 9.0},
            },
            "overrides": [{"index": 1, "type": "touch"}],
        }
    )
    assert schedule.block(1).expected_duration_min == 9.0


def test_an_override_does_not_renumber_the_blocks_it_passes():
    """`block_index` in an already-written row has to keep meaning the same block."""
    schedule = make(overrides=[{"index": 1, "offset_min": 55.0}])
    assert [b.index for b in schedule.blocks] == [1, 2, 3, 4]
    assert schedule.block(1).planned_offset_min == 55.0


def test_an_override_naming_a_block_that_does_not_exist_is_a_configuration_error():
    with pytest.raises(cfg.ConfigError, match="overrides names block"):
        make(overrides=[{"index": 99, "offset_min": 30.0}])


def test_an_override_with_a_nonsense_type_is_a_configuration_error():
    with pytest.raises(cfg.ConfigError, match="not one of"):
        make(overrides=[{"index": 1, "type": "sweep"}])


def test_an_override_with_a_nonnumeric_offset_is_a_configuration_error():
    with pytest.raises(cfg.ConfigError, match="offset_min"):
        make(overrides=[{"index": 1, "offset_min": "soon"}])


# -- validation, SPEC.md 7.3: warn, never block ---------------------------------------------


def test_every_rule_warns_and_none_raises():
    """One grid breaking as much as possible still generates and still returns a Schedule."""
    schedule = make(
        n_pinprick_blocks=3,
        n_touch_blocks=1,
        overrides=[{"index": 3, "offset_min": 5.0}],
        validation={"max_session_duration_min": 10.0},
    )
    assert isinstance(schedule, sched.Schedule)
    assert len(schedule.warnings()) > 1


def test_a_block_inside_the_capsaicin_window_is_named_with_the_rule():
    schedule = make(overrides=[{"index": 1, "offset_min": 5.0}])
    warning = next(w for w in schedule.warnings() if "capsaicin" in w)
    assert "block 1" in warning
    assert "2-12 min" in warning


def test_a_block_overlapping_the_rekindle_is_named_with_the_rule():
    """The generator never does this; an override can, which is what the rule is for."""
    schedule = make(overrides=[{"index": 2, "offset_min": 42.0}])
    warning = next(w for w in schedule.warnings() if "rekindle" in w)
    assert "block 2" in warning


def test_a_block_ending_exactly_at_a_window_start_does_not_warn():
    """A block that finishes as the rekindle begins does not overlap it."""
    schedule = make(overrides=[{"index": 2, "offset_min": 36.0}])
    assert not any("rekindle" in w for w in schedule.warnings())


def test_overlapping_blocks_are_reported_when_the_durations_are_known():
    schedule = make(overrides=[{"index": 2, "offset_min": 27.0}])
    assert any("still running until 29 min" in w for w in schedule.warnings())


def test_a_block_moved_before_its_predecessor_is_reported_as_out_of_order():
    schedule = make(overrides=[{"index": 3, "offset_min": 30.0}])
    assert any("before block 2" in w for w in schedule.warnings())


def test_an_overlap_is_found_between_blocks_that_are_not_adjacent_in_the_numbering():
    """Overlap is a question about time. Block 1 moved to 58 runs 58-62, into block 4 at 60."""
    schedule = make(overrides=[{"index": 1, "offset_min": 58.0}])
    warnings = schedule.warnings()
    assert any("block 4 starts at 60 min" in w and "block 1" in w for w in warnings)
    assert any("before block 1" in w for w in warnings), "and it is still out of order"


def test_a_long_block_catches_a_short_one_nested_inside_it():
    """The comparison is against whatever reaches furthest, not against the previous block."""
    schedule = sched.generate(
        {
            **BASE,
            "generate": {
                **BASE["generate"],
                "expected_duration_min": {"pinprick": 30.0, "touch": 1.0},
            },
            "overrides": [{"index": 4, "offset_min": 36.0}],
        }
    )
    # Block 1 runs 25-55; block 2 is a 1 min touch at 35, block 4 another at 36.
    assert any("block 4 starts at 36 min" in w and "block 1" in w for w in schedule.warnings())


def test_the_total_is_the_end_of_the_latest_thing_scheduled():
    schedule = make()
    assert schedule.total_duration_min == 64.0  # last block starts at 60 and runs 4 min
    assert make(expected_duration_min={"pinprick": None, "touch": None}).total_duration_min == (
        60.0
    )


def test_unknown_durations_disable_the_overlap_check_and_say_so():
    """Better to state that a rule could not run than to answer it on a guessed duration."""
    schedule = make(
        expected_duration_min={"pinprick": None, "touch": None},
        overrides=[{"index": 2, "offset_min": 22.0}],
    )
    warnings = schedule.warnings()
    assert any("durations are not set" in w and "open item 4" in w for w in warnings)
    assert not any("still running" in w for w in warnings)


def test_unequal_spacing_between_same_type_blocks_is_reported():
    """Pinprick blocks 1, 3, 5 sit 20 min apart; moving block 5 from 70 to 75 makes one 25."""
    schedule = evenly(overrides=[{"index": 5, "offset_min": 75.0}])
    assert any("where the others are" in w for w in schedule.warnings())


def test_spacing_within_the_configured_tolerance_does_not_warn():
    """The same move, but 24 s of it -- under the configured 30 s tolerance."""
    schedule = evenly(
        overrides=[{"index": 5, "offset_min": 70.4}],
        validation={"equal_spacing_tolerance_s": 30.0},
    )
    assert not any("where the others are" in w for w in schedule.warnings())


def test_the_rekindle_pause_is_not_counted_as_uneven_spacing():
    """The grid widens one gap on purpose (SPEC.md 7.1); wall clock alone would always fire."""
    schedule = make(n_pinprick_blocks=3, n_touch_blocks=3, intervention_duration_min=60.0)
    pinprick = [b.planned_offset_min for b in schedule.blocks if b.type == "pinprick"]
    gaps = {round(b - a, 6) for a, b in zip(pinprick, pinprick[1:], strict=False)}
    assert len(gaps) > 1, "the gap holding the rekindle really is wider in wall-clock terms"
    assert not any("where the others are" in w for w in schedule.warnings())


def test_a_session_over_the_configured_maximum_is_reported():
    schedule = make(validation={"max_session_duration_min": 30.0})
    warning = next(w for w in schedule.warnings() if "over the configured maximum" in w)
    assert "64" in warning  # the last block starts at 60 and runs 4 min


def test_a_block_outside_the_intervention_window_is_reported():
    schedule = make(overrides=[{"index": 4, "offset_min": 90.0}])
    assert any("lies outside the intervention" in w for w in schedule.warnings())


def test_a_regular_grid_produces_no_warnings():
    """So that the warnings above are the rules firing, not the fixture being untidy."""
    assert make().warnings() == ()


# -- durations and the open item ------------------------------------------------------------


def test_a_grid_declared_settled_with_a_null_duration_is_refused():
    """The two are one question (open item 4), so they cannot be marked resolved separately."""
    with pytest.raises(cfg.ConfigError, match="settled"):
        make(settled=True, expected_duration_min={"pinprick": None, "touch": 4.0})


def test_a_missing_duration_entry_for_a_type_in_the_grid_is_a_configuration_error():
    with pytest.raises(cfg.ConfigError, match="no entry for 'touch'"):
        make(expected_duration_min={"pinprick": 4.0})


def test_expected_duration_must_be_a_mapping():
    with pytest.raises(cfg.ConfigError, match="must be a mapping"):
        make(expected_duration_min=4.0)


def test_a_nonnumeric_duration_names_the_file_and_the_key():
    """SPEC.md 6. These are the fields a human hand-edits the day open item 4 is resolved."""
    with pytest.raises(cfg.ConfigError, match="expected_duration_min.pinprick"):
        make(expected_duration_min={"pinprick": "6", "touch": 4.0})
    with pytest.raises(cfg.ConfigError, match="expected_duration_min.touch"):
        make(expected_duration_min={"pinprick": 4.0, "touch": True})


def test_a_negative_duration_is_refused():
    with pytest.raises(cfg.ConfigError, match="below the minimum 0"):
        make(expected_duration_min={"pinprick": -4.0, "touch": 4.0})


# -- preview, SPEC.md 7.2 -------------------------------------------------------------------


def test_the_preview_carries_every_column_the_spec_names():
    rows = make().preview_rows(T_ZERO)
    assert len(rows) == 4
    assert rows[0] == {
        "index": 1,
        "type": "pinprick",
        "planned_offset_min": 25.0,
        "planned_wall_clock": "09:55:00",
        "expected_duration_min": 4.0,
        "overridden": False,
    }


def test_the_wall_clock_column_is_the_offset_from_t_zero():
    rows = make().preview_rows(T_ZERO)
    assert [r["planned_wall_clock"] for r in rows] == [
        "09:55:00", "10:05:00", "10:20:00", "10:30:00"
    ]


# -- the live configuration -----------------------------------------------------------------


def test_the_configured_schedule_generates_the_blocks_the_study_needs():
    """SPEC.md 2: six pinprick and six touch blocks. Not that they are well placed."""
    schedule = sched.generate(cfg.load("sv", "en").schedule)
    assert len(schedule.blocks) == 12
    assert sum(b.type == "pinprick" for b in schedule.blocks) == 6
    assert sum(b.type == "touch" for b in schedule.blocks) == 6


def test_the_configured_grid_does_not_put_a_block_on_the_rekindle():
    """It did before the pause was added; block 7 landed exactly on it (FOR_S A3.3)."""
    schedule = sched.generate(cfg.load("sv", "en").schedule)
    rekindle = schedule.window("rekindle")
    assert not any(
        rekindle.contains(b.planned_offset_min, b.planned_end_min) for b in schedule.blocks
    )
    assert not any("rekindle" in w for w in schedule.warnings())
