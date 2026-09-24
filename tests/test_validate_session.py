"""The validator's checker: how it reports, and a few checks against crafted runs. SPEC.md 17.3.

The runner itself is exercised by `make validate`, which is part of the gate; running whole
sessions here as well would double the cost for no extra coverage. What is tested here is the
part a person trusts without reading: that a skip is reported as a skip, a missing check as a
failure, and that the checks fire on the defects they exist for.
"""

from __future__ import annotations

import pytest

from tatp import config as cfg
from tools import validate_session as vs


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


def _run(loaded, name=vs.NORMAL, **overrides) -> vs.Run:
    fields = dict(
        name=name,
        seed=vs.SEED,
        config=loaded,
        completed=True,
        failure="",
        write_failures=0,
        headers={},
        rows={},
        ragged={},
        session_keys=[],
        session={},
        schedule_offsets_min={},
        participant_seen=set(),
        experimenter_seen=set(),
        stats={},
    )
    fields.update(overrides)
    return vs.Run(**fields)


def _pinprick(**values) -> dict:
    row = dict.fromkeys(vs.SCHEMA["pinprick"].column_names, "")
    row.update(values)
    return row


# -- reporting ------------------------------------------------------------------------------


def test_each_outcome_is_reported_as_what_it_is():
    checks = [
        vs.Check("passes", vs._always, lambda runs: []),
        vs.Check("fails", vs._always, lambda runs: ["it broke"]),
        vs.Check("skips", lambda runs: "nothing to check yet", lambda runs: ["unreached"]),
        vs.Check("unwritten_and_absent", lambda runs: "Milestone 9", None),
    ]
    results = {r.name: r for r in vs.evaluate(checks, {})}
    assert results["passes"].status == vs.PASSED
    assert results["fails"].status == vs.FAILED
    assert results["fails"].detail == ["it broke"]
    assert results["skips"].status == vs.SKIPPED, "a skipped check's body is never run"
    assert results["skips"].detail == ["nothing to check yet"]
    assert results["unwritten_and_absent"].status == vs.SKIPPED


def test_a_check_whose_subject_has_arrived_but_is_not_written_fails():
    """Otherwise the milestone that builds the thing could land without its check."""
    results = vs.evaluate([vs.Check("unwritten", vs._always, None)], {})
    assert results[0].status == vs.FAILED
    assert "not been written" in results[0].detail[0]


def test_a_check_that_raises_fails_alone_and_the_rest_still_run():
    def broken(runs):
        return float("")  # what an empty cell does to a check

    checks = [
        vs.Check("broken", vs._always, broken),
        vs.Check("after", vs._always, lambda runs: []),
    ]
    results = {r.name: r for r in vs.evaluate(checks, {})}
    assert results["broken"].status == vs.FAILED
    assert "ValueError" in results["broken"].detail[0]
    assert results["after"].status == vs.PASSED


def test_the_summary_counts_skips_with_their_reasons():
    results = [
        vs.Result("a", vs.PASSED),
        vs.Result("b", vs.SKIPPED, ["Milestone 5"]),
        vs.Result("c", vs.SKIPPED, ["Milestone 5"]),
        vs.Result("d", vs.SKIPPED, ["Milestone 3"]),
    ]
    assert vs.summary(results) == (
        "1 passed, 3 skipped (Milestone 5 [b, c]; Milestone 3 [d])"
    )
    assert vs.exit_code(results) == 0, "a skip is counted, not failed"


def test_a_failure_is_counted_and_makes_the_exit_non_zero():
    results = [vs.Result("a", vs.PASSED), vs.Result("b", vs.FAILED, ["x"])]
    assert vs.summary(results) == "1 passed, 0 skipped, 1 failed"
    assert vs.exit_code(results) == 1
    assert "FAIL b" in vs.report(results)


# -- checks against crafted runs --------------------------------------------------------------


def test_an_empty_required_value_is_found(loaded):
    run = _run(loaded, rows={"pinprick": [_pinprick(timestamp_iso="2026-09-23T10:00:00.000")]})
    failures = vs.check_required_values_present({vs.NORMAL: run})
    assert any("pinprick.phase" in f for f in failures)


def test_a_value_of_the_wrong_type_is_found(loaded):
    run = _run(loaded, rows={"pinprick": [_pinprick(trial_index="first")]})
    failures = vs.check_values_parse_as_schema_types({vs.NORMAL: run})
    assert any("pinprick.trial_index" in f for f in failures)


def test_a_header_that_is_not_the_schemas_is_found(loaded):
    run = _run(loaded, headers={"pinprick": ["timestamp_iso"]}, ragged={"pinprick": 0})
    assert vs.check_columns_match_schema({vs.NORMAL: run})


def test_an_unknown_filament_is_found(loaded):
    row = _pinprick(filament_label_g="999", applied_filament_label_g="999")
    run = _run(loaded, rows={"pinprick": [row]})
    failures = vs.check_forces_are_listed_filaments({vs.NORMAL: run})
    assert any("'999'" in f for f in failures)


def test_an_empty_provenance_key_needs_its_reason(loaded):
    keys = list(vs.SESSION_KEYS)
    session = dict.fromkeys(keys, "x")
    session["git_sha"] = ""
    session["abort_reason"] = ""
    run = _run(loaded, session_keys=keys, session=session)
    failures = vs.check_provenance_populated({vs.NORMAL: run})
    assert failures == [f"{vs.NORMAL}: session git_sha is empty"], (
        "abort_reason may be empty in a completed run; git_sha may never be"
    )


def _block_rows(*indices) -> list[dict]:
    return [{"block_index": str(index)} for index in indices]


def test_the_full_grid_checks_go_live_when_every_scheduled_block_has_run(loaded):
    """Read from the data, so Milestone 5 turns them on without anyone flipping a flag."""
    planned = {1: 0.0, 2: 10.0, 3: 20.0}
    partial = _run(loaded, schedule_offsets_min=planned, rows={"blocks": _block_rows(1)})
    assert "1 of the 3 scheduled blocks" in vs.needs_full_session({vs.NORMAL: partial})
    whole = _run(loaded, schedule_offsets_min=planned, rows={"blocks": _block_rows(1, 2, 3)})
    assert vs.needs_full_session({vs.NORMAL: whole}) is None
    # Milestone 5 wrote them: every full-grid check now has a body.
    full_grid = [c for c in vs.CHECKS if c.needs is vs.needs_full_session]
    assert len(full_grid) == 3 and all(c.run is not None for c in full_grid)
    assert all(c.run is not None for c in vs.CHECKS), "no check is left unwritten"


def test_an_out_of_range_flag_the_applications_do_not_support_fails(loaded):
    lightest = min(loaded.filaments["filaments"], key=lambda f: f["force_nominal_mn"])
    search = _pinprick(phase="pre_sensitisation", protocol="long", run_index="1",
                       purpose="search", applied_filament_label_g=lightest["label_g"],
                       rating_percent="55.0")
    calibration = dict.fromkeys(vs.SCHEMA["calibration_pinprick"].column_names, "")
    calibration.update(phase="pre_sensitisation", run_index="1", out_of_range="false")
    run = _run(loaded, rows={"pinprick": [search], "calibration_pinprick": [calibration]})
    failures = vs.check_out_of_range_when_and_only_when({vs.NORMAL: run})
    assert failures and "below" in failures[0]
    calibration.update(out_of_range="true", out_of_range_direction="below")
    assert vs.check_out_of_range_when_and_only_when({vs.NORMAL: run}) == []


def test_checks_that_measure_rows_skip_when_there_are_none(loaded):
    """A check that passes on zero rows has checked nothing (SPEC.md 17.3)."""
    empty = {vs.NORMAL: _run(loaded)}
    assert vs.needs_rated_pinprick_rows(empty)
    assert vs.needs_block_rows(empty)
    assert vs.needs_trial_rows(empty)
    unrated = {vs.NORMAL: _run(loaded, rows={"pinprick": [_pinprick()]})}
    assert vs.needs_rated_pinprick_rows(unrated), "a row with no rating cue has no interval"


def test_an_empty_pattern_list_does_not_match_every_screen(loaded):
    run = _run(
        loaded,
        session={"pattern_names": ""},
        participant_seen={"Welcome"},
        experimenter_seen={"Phase: setup"},
    )
    assert vs.check_screens_showed_nothing_forbidden({vs.NORMAL: run}) == []


def _timed(loaded, rating_cue_ms: int) -> dict:
    """A timing run at the slow speed with one application, its rating cued this many real
    milliseconds after its warning cue."""
    rows = [
        _pinprick(cue_onset_iso="2026-09-23T10:00:00.000",
                  rating_cue_iso=f"2026-09-23T10:00:{rating_cue_ms // 1000:02d}."
                                 f"{rating_cue_ms % 1000:03d}", trial_index="1")
    ]
    speed = str(vs.SLOW_CLOCK_SPEED)
    return {vs.TIMING: _run(loaded, vs.TIMING, rows={"pinprick": rows},
                            session={"clock_speed": speed})}


def test_the_rating_interval_is_judged_in_session_seconds(loaded):
    # 1 s lead plus 9 s delay: 10 s of session time, 1000 ms real at 10x.
    assert vs.check_rating_cue_interval(_timed(loaded, 1000)) == []
    assert vs.check_rating_cue_interval(_timed(loaded, 1015)) == [], "a timer 15 ms late"


def test_a_missing_half_second_warning_lead_fails(loaded):
    """The 0.5 s between the cue and the stimulus, left out: 50 ms real at 10x."""
    assert vs.check_rating_cue_interval(_timed(loaded, 950))


def test_a_rating_interval_off_by_the_configured_delay_fails(loaded):
    assert vs.check_rating_cue_interval(_timed(loaded, 100))


def _orders(loaded, *sites):
    rows = {
        name: _run(loaded, name, rows={"pinprick": [_pinprick(
            timestamp_iso="2026-09-23T10:00:00.000", site_index=site, block_index="1"
        )]})
        for name, site in zip((vs.NORMAL, vs.SAME_SEED, vs.OTHER_SEED), sites, strict=True)
    }
    return rows


def test_the_seed_check_skips_while_the_seed_changes_nothing(loaded):
    runs = _orders(loaded, "1", "1", "1")
    assert "identical under two different seeds" in vs.needs_the_seed_to_matter(runs)


def test_the_seed_check_passes_when_only_the_other_seed_differs(loaded):
    runs = _orders(loaded, "1", "1", "5")
    assert vs.needs_the_seed_to_matter(runs) is None
    assert vs.check_same_seed_same_trial_order(runs) == []


def test_the_seed_check_fails_when_one_seed_gives_two_orders(loaded):
    runs = _orders(loaded, "1", "2", "5")
    assert vs.needs_the_seed_to_matter(runs) is None
    assert vs.check_same_seed_same_trial_order(runs)
