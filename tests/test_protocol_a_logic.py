"""Protocol A's decisions, without Qt. SPEC.md 8.2, 8.3, 17.2.

Tested against `docs/calibration_sim.py`, the simulation the design was chosen on (comparison
doc section 5). The simulation runs its whole study when imported, so its function definitions
are lifted out of the source and executed alone: the functions under test are the ones that
produced the published numbers, not a copy of them.
"""

from __future__ import annotations

import ast
import math
import random

import numpy as np
import pytest

from tatp import config as cfg
from tatp.pinprick import (
    ABOVE,
    BELOW,
    CONFIG_DEFAULT,
    MEASURE,
    PREVIOUS_TIMEPOINT,
    SEARCH,
    Filament,
    IntolerableCap,
    LongProtocolState,
    Outcome,
    Prior,
    SiteRotation,
    fixed_slope_f40,
    jittered_isi_s,
    ladder,
    nearest_index,
    place,
    prior_for,
    spearman_rho,
    start_index,
)

SIM_PATH = cfg.REPO_ROOT / "docs" / "calibration_sim.py"
TARGET = 40.0


def _sim() -> dict:
    """`fit40`, `ascend` and the ladder from the simulation, with a noise-free observer."""
    tree = ast.parse(SIM_PATH.read_text(encoding="utf-8"))
    wanted = {"LAD", "L", "S_FIXED", "fit40", "ascend", "strat_ascend_local"}
    body = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in wanted)
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id in wanted for t in node.targets)
        )
    ]
    namespace = {"np": np}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SIM_PATH), "exec"), namespace)
    # The simulated observer without its noise, so the search is deterministic.
    namespace["rate"] = lambda F, F40, sig, s: float(
        np.clip(40 + s * (np.log10(F) - np.log10(F40)), 0, 100)
    )
    return namespace


SIM = _sim()
FORCES = [float(f) for f in SIM["LAD"]]
# The simulation's own slope, 51.59..., of which config's 51.6 is the rounding.
SLOPE = float(SIM["S_FIXED"])


def _rating(force: float, f40: float) -> float:
    return SIM["rate"](force, f40, 0.0, SIM["S_FIXED"])


def _state(start=0, max_applications=25, seed=1) -> LongProtocolState:
    return LongProtocolState(
        n_filaments=len(FORCES),
        start=start,
        target_pct=TARGET,
        measure_n_levels=3,
        measure_repetitions=3,
        max_applications=max_applications,
        rng=random.Random(seed),
    )


def _run(state: LongProtocolState, f40: float, ceiling=None) -> list[Outcome]:
    """Answer every application as the noise-free observer would."""
    while (planned := state.next(ceiling)) is not None:
        state.record(
            Outcome(planned.index, planned.index, _rating(FORCES[planned.index], f40),
                    planned.purpose)
        )
    return state.outcomes


# -- the estimator -------------------------------------------------------------------------


def test_the_fixed_slope_estimate_is_the_simulations():
    rng = np.random.default_rng(3)
    for _ in range(50):
        forces = list(rng.choice(FORCES, size=9))
        ratings = list(rng.uniform(0, 100, size=9))
        expected = SIM["fit40"](forces, ratings, fixed_slope=SLOPE)
        assert fixed_slope_f40(forces, ratings, SLOPE, TARGET) == pytest.approx(expected)


def test_known_inputs_give_a_known_f40():
    # One slope-unit below the target at 100 mN means the target is one decade up.
    assert fixed_slope_f40([100.0, 100.0], [TARGET - SLOPE] * 2, SLOPE, TARGET) == (
        pytest.approx(1000.0)
    )


def test_identical_ratings_at_the_target_give_the_geometric_mean():
    forces = [98.0, 147.0, 255.0]
    expected = math.prod(forces) ** (1 / 3)
    assert fixed_slope_f40(forces, [TARGET] * 3, SLOPE, TARGET) == pytest.approx(expected)


def test_the_nearest_filament_is_nearest_in_log_force():
    assert nearest_index(FORCES, 255.0) == FORCES.index(255.0)
    # 255 and 588 mN: their geometric mean is the boundary, not their arithmetic mean.
    boundary = math.sqrt(255.0 * 588.0)
    assert FORCES[nearest_index(FORCES, boundary * 0.99)] == 255.0
    assert FORCES[nearest_index(FORCES, boundary * 1.01)] == 588.0


# -- the search ----------------------------------------------------------------------------


@pytest.mark.parametrize("f40", [45.0, 130.0, 300.0, 600.0, 1500.0])
@pytest.mark.parametrize("start", [0, 2, 4])
def test_an_ascent_finds_the_simulations_crossing_and_levels(f40, start):
    if _rating(FORCES[start], f40) >= TARGET:
        pytest.skip("the simulation only ascends; a start above the crossing descends here")
    sim_index, _, _ = SIM["ascend"](f40, 0.0, SIM["S_FIXED"], start)
    state = _state(start=start)
    _run(state, f40)
    if state.out_of_range:
        pytest.skip("the simulation's ascent has no out-of-range case")
    assert state.crossing == sim_index
    top = len(FORCES) - 1
    lo = int(np.clip(sim_index - 2, 0, top))
    assert state.measure_levels() == [int(np.clip(lo + k, 0, top)) for k in range(3)]


def test_the_search_descends_from_a_start_above_the_crossing():
    state = _state(start=9)
    outcomes = _run(state, 130.0)
    search = [o.applied_index for o in outcomes if o.purpose == SEARCH]
    assert search == sorted(search, reverse=True), "every step is down"
    crossing = state.crossing
    assert _rating(FORCES[crossing], 130.0) >= TARGET > _rating(FORCES[crossing - 1], 130.0)
    assert search[-1] == crossing - 1


def test_a_direction_change_brackets_the_crossing():
    state = _state(start=3)
    for rating in (20.0, 60.0):
        planned = state.next()
        state.record(Outcome(planned.index, planned.index, rating, SEARCH))
    assert state.crossing == 4 and state.measuring


def test_search_trials_do_not_enter_the_estimate():
    state = _state(start=0)
    _run(state, 130.0)
    estimate = state.estimate(FORCES, SLOPE)
    measured = [o for o in state.outcomes if o.purpose == MEASURE]
    assert estimate.n_measure == len(measured) == 9
    expected = fixed_slope_f40(
        [FORCES[o.applied_index] for o in measured], [o.rating_percent for o in measured],
        SLOPE, TARGET,
    )
    assert estimate.f40_mn == pytest.approx(expected)
    assert estimate.f40_mn == pytest.approx(130.0, rel=1e-6), "noise-free ratings recover F40"
    assert FORCES[estimate.chosen_index] == 147.0


def test_the_measurement_is_three_by_three():
    state = _state(start=4)
    _run(state, 300.0)
    measured = [o.planned_index for o in state.outcomes if o.purpose == MEASURE]
    levels = state.measure_levels()
    assert sorted(measured) == sorted(levels * 3)
    assert levels == [state.crossing - 2, state.crossing - 1, state.crossing]


def test_the_same_seed_gives_the_same_order_and_another_seed_a_different_one():
    def order(seed):
        state = _state(start=4, seed=seed)
        _run(state, 300.0)
        return [o.planned_index for o in state.outcomes if o.purpose == MEASURE]

    assert order(11) == order(11)
    assert any(order(11) != order(seed) for seed in range(12, 20))


# -- the edges -----------------------------------------------------------------------------


def test_out_of_range_below_uses_the_lightest_filament():
    state = _state(start=2)
    _run(state, FORCES[0] / 10)
    assert state.out_of_range == BELOW
    estimate = state.estimate(FORCES, SLOPE)
    assert estimate.out_of_range == BELOW and estimate.chosen_index == 0
    assert estimate.f40_mn == FORCES[0]
    assert not any(o.purpose == MEASURE for o in state.outcomes), "no measurement follows"


def test_out_of_range_above_uses_the_heaviest_filament():
    state = _state(start=8)
    _run(state, FORCES[-1] * 10)
    assert state.out_of_range == ABOVE
    estimate = state.estimate(FORCES, SLOPE)
    assert estimate.chosen_index == len(FORCES) - 1 and estimate.f40_mn == FORCES[-1]


def test_the_trial_cap_ends_the_run_with_the_best_estimate_flagged():
    state = _state(start=0, max_applications=4)
    outcomes = _run(state, 1500.0)
    assert len(outcomes) == 4 and state.capped and not state.complete
    estimate = state.estimate(FORCES, SLOPE)
    assert estimate.capped
    # No measurement was reached, so the search trials are all there is to fit.
    expected = fixed_slope_f40(
        [FORCES[o.applied_index] for o in outcomes], [o.rating_percent for o in outcomes],
        SLOPE, TARGET,
    )
    assert estimate.f40_mn == pytest.approx(expected)


def test_the_cap_falling_during_measurement_fits_what_was_measured():
    state = _state(start=4, max_applications=12)
    _run(state, 300.0)
    estimate = state.estimate(FORCES, SLOPE)
    assert estimate.capped and 0 < estimate.n_measure < 9


def test_a_run_that_completes_on_the_cap_is_not_flagged():
    state = _state(start=4)
    _run(state, 300.0)
    exact = len(state.outcomes)
    state = _state(start=4, max_applications=exact)
    _run(state, 300.0)
    assert state.complete and not state.capped


# -- discard -------------------------------------------------------------------------------


def test_discarding_a_measurement_replans_it():
    state = _state(start=4)
    _run(state, 300.0)
    last = state.outcomes[-1]
    assert state.complete
    state.discard_last()
    assert not state.finished
    assert state.next().index == last.planned_index
    assert state.delivered == len(state.outcomes) + 1, "the discarded one still counts"


def test_discarding_the_bracketing_search_trial_unbrackets():
    state = _state(start=3)
    for rating in (20.0, 60.0):
        planned = state.next()
        state.record(Outcome(planned.index, planned.index, rating, SEARCH))
    state.discard_last()
    assert state.crossing is None and not state.measuring
    assert state.next().index == 4 and state.next().purpose == SEARCH


def test_discarding_an_out_of_range_trial_resumes_the_search():
    state = _state(start=0)
    planned = state.next()
    state.record(Outcome(planned.index, planned.index, 90.0, SEARCH))
    assert state.out_of_range == BELOW
    state.discard_last()
    assert state.out_of_range is None and state.next().index == 0


# -- substitution --------------------------------------------------------------------------


def test_the_search_steps_from_the_filament_applied():
    state = _state(start=5)
    planned = state.next()
    state.record(Outcome(planned.index, 3, 10.0, SEARCH))  # the experimenter went lighter
    assert state.next().index == 4


def test_the_estimate_fits_the_applied_filament():
    state = _state(start=3)
    for rating in (20.0, 60.0):
        planned = state.next()
        state.record(Outcome(planned.index, planned.index, rating, SEARCH))
    applied = []
    while (planned := state.next()) is not None:
        index = max(planned.index - 1, 0)
        applied.append(index)
        state.record(Outcome(planned.index, index, 40.0, MEASURE))
    estimate = state.estimate(FORCES, SLOPE)
    expected = fixed_slope_f40([FORCES[i] for i in applied], [40.0] * 9, SLOPE, TARGET)
    assert estimate.f40_mn == pytest.approx(expected)


# -- the intolerable cap --------------------------------------------------------------------


def test_the_cap_is_per_site_and_prospective():
    cap = IntolerableCap(sites_for_global_cap=4)
    assert cap.allows("primary", 1, 7)
    cap.record("primary", 1, 7)
    assert not cap.allows("primary", 1, 7) and not cap.allows("primary", 1, 8)
    assert cap.allows("primary", 1, 6)
    assert cap.allows("primary", 2, 9), "another site is not capped"
    assert cap.allows("secondary", 1, 9), "nor is the same site number in the other region"


def test_a_lower_ceiling_at_a_site_replaces_a_higher_one():
    cap = IntolerableCap(sites_for_global_cap=4)
    cap.record("primary", 1, 7)
    cap.record("primary", 1, 5)
    cap.record("primary", 1, 6)
    assert cap.cap_for("primary", 1) == 5


def test_enough_capped_sites_cap_every_site_at_the_lowest():
    cap = IntolerableCap(sites_for_global_cap=3)
    assert not cap.record("primary", 1, 8)
    assert not cap.record("primary", 2, 6)
    assert cap.record("primary", 3, 7), "the third site switches the global cap on"
    assert cap.global_cap("primary") == 6
    assert not cap.allows("primary", 5, 6) and cap.allows("primary", 5, 5)
    assert not cap.record("primary", 4, 9), "already on"


def test_escalation_is_per_region():
    cap = IntolerableCap(sites_for_global_cap=2)
    cap.record("primary", 1, 4)
    cap.record("secondary", 2, 6)
    assert cap.global_cap("primary") is None and cap.global_cap("secondary") is None, (
        "one site in each region is not two sites in either"
    )
    assert cap.record("primary", 3, 5)
    assert cap.global_cap("primary") == 4
    assert cap.allows("secondary", 1, 9), "a primary-zone ceiling never caps the secondary"
    assert cap.global_cap("secondary") is None


def test_placing_skips_a_capped_site_and_lowers_only_when_every_site_is_capped():
    cap = IntolerableCap(sites_for_global_cap=10)
    rotation = SiteRotation(3)
    cap.record("primary", 1, 5)
    assert place(cap, rotation, "primary", 5) == (5, 2), "site 1 is capped; site 2 is next"
    cap.record("primary", 2, 5)
    cap.record("primary", 3, 4)
    # Every site is capped, the loosest at 5: filament 4 is barred at 3 but not at 1 or 2.
    assert place(cap, rotation, "primary", 6) == (4, 1)
    assert place(cap, rotation, "primary", 3) == (3, 1)


def test_nothing_is_placed_when_even_the_lightest_is_barred():
    cap = IntolerableCap(sites_for_global_cap=1)
    cap.record("primary", 1, 0)
    assert place(cap, SiteRotation(2), "primary", 3) is None


def test_a_barred_step_up_brackets_instead_of_climbing_into_the_cap():
    state = _state(start=3)
    planned = state.next()
    state.record(Outcome(planned.index, planned.index, 10.0, SEARCH))
    planned = state.next(ceiling=4)
    assert state.crossing == 4 and planned.purpose == MEASURE


# -- rotation, rank correlation, the interval, the prior ------------------------------------


def test_the_site_rotates_on_every_application():
    rotation = SiteRotation(3)
    taken = []
    for _ in range(7):
        site = rotation.order()[0]
        rotation.take(site)
        taken.append(site)
    assert taken == [1, 2, 3, 1, 2, 3, 1]
    rotation.take(2)  # a capped site 1 was skipped
    assert rotation.order() == [3, 1, 2]


def test_the_rank_correlation_is_spearmans():
    assert spearman_rho([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman_rho([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    # Ties share their average rank: ranks (1.5, 1.5, 3) against (1, 2, 3).
    assert spearman_rho([5, 5, 9], [1, 2, 3]) == pytest.approx(math.sqrt(3) / 2)
    assert spearman_rho([1, 1, 1], [1, 2, 3]) is None, "undefined, not zero"


def test_the_jittered_interval_stays_in_its_range_and_varies():
    rng = random.Random(4)
    draws = [jittered_isi_s(rng, 13.0, 17.0) for _ in range(500)]
    assert min(draws) >= 13.0 and max(draws) <= 17.0
    assert max(draws) - min(draws) > 3.0, "jittered, not fixed"


def _ladder(*forces):
    return [Filament(str(f), float(f), None) for f in forces]


def test_the_start_shifts_the_previous_estimate_by_ladder_steps():
    filaments = _ladder(10, 100, 1000, 10000)
    assert start_index(filaments, 1000.0, 0.0) == 2
    assert start_index(filaments, 1000.0, -2.0) == 0
    # Half-way between 100 and 1000 in log force is position 1.5; -0.6 steps lands on 1.
    assert start_index(filaments, math.sqrt(1e5), -0.6) == 1
    assert start_index(filaments, 1000.0, -9.0) == 0, "clipped onto the ladder"
    assert start_index(filaments, 1e6, 0.0) == 3


def test_the_prior_is_the_default_only_at_pre_s_of_session_one():
    config = cfg.load("sv", "en")
    pinprick = config.study1["pinprick"]
    first = prior_for(config, "pre_sensitisation", 1, None)
    assert first == Prior(pinprick["start_filament_label_g_session1_pre_s"], CONFIG_DEFAULT)
    post = prior_for(config, "post_sensitisation", 1, 588.0)
    assert post.source == PREVIOUS_TIMEPOINT
    filaments = ladder(config)
    expected = start_index(filaments, 588.0, pinprick["expected_offset_steps_pre_to_post_s"])
    assert post.start_filament_label_g == filaments[expected].label_g
    with pytest.raises(ValueError, match="previous time point"):
        prior_for(config, "post_intervention", 1, None)
    with pytest.raises(ValueError, match="does not run"):
        prior_for(config, "intervention", 1, 100.0)
