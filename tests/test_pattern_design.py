"""The pattern designer's logic. SPEC.md 12.2, 12.4.

The window is tested in `tests/test_design_pattern_window.py`; everything it decides is here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tatp import config as cfg
from tatp import pattern_design as pd
from tatp.garment import patterns
from tatp.pattern_design import DesignError

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
PROTOTYPE = Path(__file__).resolve().parent / "fixtures" / "prototype"
IDS = (3, 4, 11)


@pytest.fixture(scope="module")
def limits():
    command = cfg.load("sv", "sv").hardware["prototype_command_file"]
    return command["max_steps"], command["max_step_ms"]


def _design(rows, name="trial", interval=100.0, ids=IDS, loop=False, **extras) -> pd.Design:
    return pd.Design(name, interval, tuple(ids), loop, [list(r) for r in rows], dict(extras))


# -- composition modes ----------------------------------------------------------------------


def test_timed_channels_become_rows_ending_at_the_last_offset():
    """The prototype README's timed example: 3 0-500, 4 400-900, 11 800-1300 ms."""
    rows = pd.timed_rows([(3, 0, 500), (4, 400, 900), (11, 800, 1300)], 100, IDS)
    assert len(rows) == 13
    assert [r[0] for r in rows] == [1] * 5 + [0] * 8
    assert [r[1] for r in rows] == [0] * 4 + [1] * 5 + [0] * 4
    assert [r[2] for r in rows] == [0] * 8 + [1] * 5


def test_a_timed_channel_may_have_two_on_periods():
    rows = pd.timed_rows([(3, 0, 100), (3, 200, 300)], 100, (3,))
    assert rows == [[1], [0], [1]]


def test_a_late_first_onset_leaves_leading_rows_off():
    assert pd.timed_rows([(4, 200, 300)], 100, IDS) == [[0, 0, 0], [0, 0, 0], [0, 1, 0]]


def test_sequential_runs_each_channel_in_turn_with_the_delay_after_each():
    spans = pd.ordered_spans([(3, 200), (4, 100)], 100, pd.SEQUENTIAL)
    assert spans == [(3, 0, 200), (4, 300, 400)]
    rows = pd.ordered_rows([(3, 200), (4, 100)], 100, pd.SEQUENTIAL, 100, IDS)
    assert rows == [[1, 0, 0], [1, 0, 0], [0, 0, 0], [0, 1, 0]]


def test_sequential_with_no_delay_is_the_prototype_generate_sequence():
    """`Controller.Stimulus.generate_sequence`: back to back, each for its own hold time."""
    assert pd.ordered_spans([(3, 500), (4, 500)], 0, pd.SEQUENTIAL) == [
        (3, 0, 500), (4, 500, 1000)
    ]


def test_join_hold_starts_each_after_the_delay_and_holds_its_own_time():
    spans = pd.ordered_spans([(3, 300), (4, 300), (11, 100)], 100, pd.JOIN_HOLD)
    assert spans == [(3, 0, 300), (4, 100, 400), (11, 200, 300)]
    rows = pd.ordered_rows([(3, 300), (4, 300), (11, 100)], 100, pd.JOIN_HOLD, 100, IDS)
    assert rows == [[1, 0, 0], [1, 1, 0], [1, 1, 1], [0, 1, 0]]


def test_join_stay_turns_everything_off_together():
    spans = pd.ordered_spans([(3, 300), (4, 300), (11, 100)], 100, pd.JOIN_STAY)
    assert spans == [(3, 0, 400), (4, 100, 400), (11, 200, 400)]
    rows = pd.ordered_rows([(3, 300), (4, 300), (11, 100)], 100, pd.JOIN_STAY, 100, IDS)
    assert rows == [[1, 0, 0], [1, 1, 0], [1, 1, 1], [1, 1, 1]]


def test_the_20_cm_s_sweep_is_expressible_at_75_ms():
    """SPEC.md 12.2: 75 ms between onsets, with one row of overlap."""
    entries = [(cid, 150) for cid in (1, 2, 3, 4, 5)]
    rows = pd.ordered_rows(entries, 75, pd.JOIN_HOLD, 75, (1, 2, 3, 4, 5))
    sweep = patterns.load_pattern(EXAMPLES / "sweep_20cms.csv")
    assert rows == [list(r) for r in sweep.rows]


@pytest.mark.parametrize("onset, offset", [(0, 250), (50, 300)])
def test_a_timing_off_the_grid_is_refused_never_rounded(onset, offset):
    with pytest.raises(DesignError) as raised:
        pd.timed_rows([(3, onset, offset)], 100, IDS)
    assert raised.value.key == "off_grid"
    assert raised.value.values["interval"] == "100"


def test_off_grid_is_judged_exactly_not_in_floating_point():
    """0.3 / 0.1 is 2.9999999999999996 in floating point; three rows exactly here."""
    assert pd.row_index(0.3, 0.1) == 3
    with pytest.raises(DesignError):
        pd.row_index(0.35, 0.1)


def test_an_ordered_hold_off_the_grid_is_refused():
    with pytest.raises(DesignError) as raised:
        pd.ordered_rows([(3, 150)], 0, pd.JOIN_HOLD, 100, IDS)
    assert raised.value.key == "off_grid"


def test_a_delay_off_the_grid_is_refused():
    with pytest.raises(DesignError) as raised:
        pd.ordered_rows([(3, 100), (4, 100)], 50, pd.SEQUENTIAL, 100, IDS)
    assert raised.value.key == "off_grid"


@pytest.mark.parametrize("spans, key", [
    ([(3, 100, 100)], "empty_span"),
    ([(3, 200, 100)], "empty_span"),
    ([(3, -100, 100)], "negative"),
    ([(7, 0, 100)], "unknown_channel"),
    ([(3, 0, 200), (3, 100, 300)], "overlap"),
    ([(3, 0, 200), (3, 200, 300)], "overlap"),
    ([], "nothing"),
])
def test_timed_refusals(spans, key):
    with pytest.raises(DesignError) as raised:
        pd.timed_rows(spans, 100, IDS)
    assert raised.value.key == key


@pytest.mark.parametrize("entries, delay, key", [
    ([(3, 0)], 0, "hold"),
    ([(3, 100)], -100, "negative"),
    ([], 0, "nothing"),
])
def test_ordered_refusals(entries, delay, key):
    with pytest.raises(DesignError) as raised:
        pd.ordered_spans(entries, delay, pd.JOIN_HOLD)
    assert raised.value.key == key


def test_a_repeated_ordered_channel_that_overlaps_itself_is_refused():
    with pytest.raises(DesignError) as raised:
        pd.ordered_rows([(3, 300), (3, 300)], 100, pd.JOIN_HOLD, 100, IDS)
    assert raised.value.key == "overlap"


def test_changing_the_channels_keeps_the_columns_that_remain():
    rows = [[1, 0, 1], [0, 1, 0]]
    assert pd.resized(rows, IDS, (11, 5, 3)) == [[1, 0, 1], [0, 0, 0]]


# -- validation, saving, loading ------------------------------------------------------------


def test_a_valid_design_validates_as_the_pattern_it_would_load_as(tmp_path):
    pattern = pd.validate(_design([[1, 0, 0], [0, 1, 1]]), tmp_path)
    assert pattern.rows == ((1, 0, 0), (0, 1, 1))
    assert pattern.source == tmp_path / "trial.csv"


@pytest.mark.parametrize("cell", [2, "0.5", "", "01"])
def test_a_cell_that_is_not_0_or_1_is_refused_by_the_loader_code(tmp_path, cell):
    """SPEC.md 12.4's defect: the refusal comes from `patterns.from_text`, not a second copy."""
    with pytest.raises(DesignError) as raised:
        pd.validate(_design([[1, cell, 0]]), tmp_path)
    assert raised.value.key == "not_loadable"
    assert "is not 0 or 1" in raised.value.values["value"]


@pytest.mark.parametrize("design, key", [
    (_design([[1, 0, 0]], name="two words"), "name"),
    (_design([[1, 0, 0]], name=""), "name"),
    (_design([[1, 0, 0]], interval=0.0), "interval"),
    (_design([], ), "not_loadable"),
    (_design([[1, 0]]), "not_loadable"),
    (_design([[1, 0]], ids=(3, 3)), "not_loadable"),
])
def test_what_would_not_load_is_refused(tmp_path, design, key):
    with pytest.raises(DesignError) as raised:
        pd.validate(design, tmp_path)
    assert raised.value.key == key


def test_a_refused_design_is_not_saved(tmp_path):
    with pytest.raises(DesignError):
        pd.save(_design([[1, 2, 0]]), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_save_and_load_round_trip_identically(tmp_path):
    design = _design([[1, 0, 0], [1, 1, 0], [0, 1, 1], [0, 0, 1], [0, 0, 0]],
                     name="round_trip", interval=75.0, loop=True, nominal_velocity_cm_s=20.0,
                     assumed_channel_spacing_cm=1.5, overlap_rows=1)
    saved = pd.save(design, tmp_path)
    loaded = patterns.load_pattern(tmp_path / "round_trip.csv")
    assert loaded == saved == pd.validate(design, tmp_path)
    assert pd.open_pattern(tmp_path / "round_trip.csv") == design
    assert patterns.expand(loaded) == patterns.expand(saved)
    assert list(patterns.load_folder(tmp_path)) == ["round_trip"]


@pytest.mark.parametrize("stem", ["sweep_01cms", "sweep_03cms", "sweep_20cms", "static_sham"])
def test_every_example_opens_and_saves_back_unchanged(tmp_path, stem):
    original = patterns.load_pattern(EXAMPLES / f"{stem}.csv")
    design = pd.open_pattern(EXAMPLES / f"{stem}.csv")
    saved = pd.save(design, tmp_path)
    assert (saved.name, saved.rows, saved.channel_ids, saved.row_interval_ms, saved.loop) == (
        original.name, original.rows, original.channel_ids, original.row_interval_ms,
        original.loop,
    )
    assert pd.open_pattern(tmp_path / f"{stem}.csv").extras == design.extras


def test_save_never_overwrites_without_being_told(tmp_path):
    pd.save(_design([[1, 0, 0]]), tmp_path)
    with pytest.raises(DesignError) as raised:
        pd.save(_design([[0, 1, 0]]), tmp_path)
    assert raised.value.key == "exists"
    assert patterns.load_pattern(tmp_path / "trial.csv").rows == ((1, 0, 0),)
    pd.save(_design([[0, 1, 0]]), tmp_path, overwrite=True)
    assert patterns.load_pattern(tmp_path / "trial.csv").rows == ((0, 1, 0),)


def test_a_sidecar_alone_counts_as_existing(tmp_path):
    (tmp_path / "trial.yaml").write_text("name: other\n", encoding="utf-8")
    with pytest.raises(DesignError) as raised:
        pd.save(_design([[1, 0, 0]]), tmp_path)
    assert raised.value.key == "exists"


def test_a_name_another_file_already_uses_is_refused(tmp_path):
    """`load_folder` refuses two patterns of one name, so the save would break the folder."""
    pd.save(_design([[1, 0, 0]], name="first"), tmp_path)
    (tmp_path / "first.csv").rename(tmp_path / "renamed.csv")
    (tmp_path / "first.yaml").rename(tmp_path / "renamed.yaml")
    with pytest.raises(DesignError) as raised:
        pd.save(_design([[1, 0, 0]], name="first"), tmp_path)
    assert raised.value.key == "name_taken"


def test_a_malformed_neighbour_is_reported_not_raised_raw(tmp_path):
    (tmp_path / "broken.csv").write_text("1\n2\n", encoding="utf-8")
    with pytest.raises(DesignError) as raised:
        pd.save(_design([[1, 0, 0]]), tmp_path)
    assert raised.value.key == "folder_unreadable"


def test_load_pattern_still_refuses_what_it_refused(tmp_path):
    """`from_text` was split out of `load_pattern`; loading a bad file is refused as before."""
    (tmp_path / "bad.csv").write_text("1,2\n1,2\n", encoding="utf-8")
    (tmp_path / "bad.yaml").write_text(
        "name: bad\nrow_interval_ms: 100\nchannel_ids: [1, 2]\nloop: false\n", encoding="utf-8"
    )
    with pytest.raises(patterns.PatternError, match="bad.csv line 2, channel 2: cell '2'"):
        patterns.load_pattern(tmp_path / "bad.csv")


# -- previewing -----------------------------------------------------------------------------


def test_on_periods_come_from_expand():
    pattern = pd.validate(_design([[1, 0, 0], [1, 1, 0], [0, 0, 0], [1, 0, 0]]), Path("."))
    periods = pd.on_periods(pattern)
    assert list(periods) == [3, 4, 11]
    assert [pytest.approx(p) for p in periods[3]] == [(0.0, 0.2), (0.3, 0.4)]
    assert [pytest.approx(p) for p in periods[4]] == [(0.1, 0.2)]
    assert periods[11] == []


# -- the prototype's horizontal CSV ---------------------------------------------------------


def test_the_prototype_csv_imports_transposed_with_the_column_duration_asked_for():
    design = pd.from_reference_csv(PROTOTYPE / "motion_stim.csv", 1000, loop=False)
    assert design.channel_ids == (3, 28)
    assert design.row_interval_ms == 1000.0
    assert [tuple(r) for r in design.rows] == [(1, 0)] * 3 + [(0, 0)] * 3 + [(0, 1)] * 4
    assert design.name == "motion_stim"


def test_a_tab_separated_prototype_csv_imports(tmp_path):
    path = tmp_path / "tabbed.csv"
    path.write_text("3\t1\t0\n4\t0\t1\n", encoding="utf-8")
    assert pd.from_reference_csv(path, 100, loop=True).rows == [[1, 0], [0, 1]]


def test_a_trailing_delimiter_is_dropped_as_the_prototype_drops_it(tmp_path):
    path = tmp_path / "trailing.csv"
    path.write_text("3,1,0,\n4,0,1,\n", encoding="utf-8")
    assert pd.from_reference_csv(path, 100, loop=False).rows == [[1, 0], [0, 1]]


@pytest.mark.parametrize("text, key", [
    ("3,1,2\n4,0,1\n", "not_loadable"),
    ("3,1,0.5\n4,0,1\n", "not_loadable"),
    ("3,1,,1\n4,0,1,1\n", "not_loadable"),
    ("3,1,0\n4,0\n", "ragged"),
    ("x,1,0\n4,0,1\n", "not_loadable"),
    ("\n", "nothing"),
])
def test_a_prototype_csv_that_would_misplay_is_refused(tmp_path, text, key):
    path = tmp_path / "bad.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(DesignError) as raised:
        pd.from_reference_csv(path, 100, loop=False)
    assert raised.value.key == key


def test_a_column_duration_of_zero_is_refused():
    with pytest.raises(DesignError) as raised:
        pd.from_reference_csv(PROTOTYPE / "motion_stim.csv", 0, loop=False)
    assert raised.value.key == "interval"


# -- the command file -----------------------------------------------------------------------


def _pattern(design: pd.Design):
    return pd.validate(design, Path("."))


def test_export_matches_what_the_prototype_writes_for_its_own_csv(limits):
    """motion_stim.csv at create_stimulus.py's 1000 ms, against the prototype code's output."""
    design = pd.from_reference_csv(PROTOTYPE / "motion_stim.csv", 1000, loop=False)
    expected = (PROTOTYPE / "motion_stim_1000ms.txt").read_text(encoding="utf-8")
    assert pd.command_file(_pattern(design), *limits) == expected


def test_export_matches_the_committed_stim_from_csv(limits):
    design = pd.from_reference_csv(PROTOTYPE / "stim_from_csv_source.csv", 100, loop=False)
    expected = (PROTOTYPE / "stim_from_csv.txt").read_text(encoding="utf-8")
    assert pd.command_file(_pattern(design), *limits) == expected


def test_the_mask_is_lower_case_hex_because_the_sketch_refuses_upper(limits):
    pattern = _pattern(_design([[1, 1, 1]], ids=(3, 5, 31)))
    assert pd.command_file(pattern, *limits) == "clearcode\naddcode:0x80000028/100"


def test_trailing_off_rows_are_kept_so_one_exec_is_one_cycle(limits):
    pattern = _pattern(_design([[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 0, 0]]))
    steps = pd.command_steps(pattern, *limits)
    assert steps == [(0, 100), (8, 100), (0, 200)]
    assert sum(ms for _, ms in steps) == pattern.duration_s * 1000


def test_a_step_longer_than_the_sketch_holds_is_split(limits):
    max_steps, max_step_ms = limits
    pattern = _pattern(_design([[1, 0, 0]], interval=float(max_step_ms + 5)))
    assert pd.command_steps(pattern, max_steps, max_step_ms) == [(8, max_step_ms), (8, 5)]


def test_more_steps_than_the_sketch_stores_are_refused(limits):
    max_steps, max_step_ms = limits
    rows = [[1, 0, 0], [0, 1, 0]] * (max_steps // 2 + 1)
    with pytest.raises(DesignError) as raised:
        pd.command_steps(_pattern(_design(rows)), max_steps, max_step_ms)
    assert raised.value.key == "too_many_steps"


@pytest.mark.parametrize("ids", [(32,), (-1,)])
def test_a_channel_that_is_not_a_mask_bit_is_refused(limits, ids):
    with pytest.raises(DesignError) as raised:
        pd.command_steps(_pattern(_design([[1]], ids=ids)), *limits)
    assert raised.value.key == "bit_range"


def test_a_step_of_a_fraction_of_a_millisecond_is_refused(limits):
    with pytest.raises(DesignError) as raised:
        pd.command_steps(_pattern(_design([[1, 0, 0]], interval=0.5)), *limits)
    assert raised.value.key == "not_whole_ms"


def test_the_sham_example_exports_as_one_step(limits):
    pattern = patterns.load_pattern(EXAMPLES / "static_sham.csv")
    assert pd.command_file(pattern, *limits) == "clearcode\naddcode:0x3e/500"
