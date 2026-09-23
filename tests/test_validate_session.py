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


def _orders(loaded, *sites):
    rows = {
        name: _run(loaded, name, rows={"pinprick": [_pinprick(
            timestamp_iso="2026-09-23T10:00:00.000", site_index=site
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
