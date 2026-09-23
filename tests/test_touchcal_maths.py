"""Protocol B's arithmetic. SPEC.md 9, 17.2.

Tested against the observer model of `docs/calibration_sim.py` -- rating linear in log stimulus,
passing through a known point, with Gaussian noise, clipped to the scale. That file runs its
whole simulation when imported, so the model is lifted out of it by name (`S_FIXED` and
`rate`) rather than imported, and nothing in it is reformatted (docs/LOG.md N6.8).
"""

from __future__ import annotations

import ast
import random

import numpy as np
import pytest

from tatp import touchcal_maths as maths
from tatp.config import REPO_ROOT

SIM_PATH = REPO_ROOT / "docs" / "calibration_sim.py"


@pytest.fixture(scope="module")
def observer():
    """`rate(F, F40, sig)` and `S_FIXED` from calibration_sim.py, and nothing else from it."""
    tree = ast.parse(SIM_PATH.read_text(encoding="utf-8"))
    wanted = [
        node for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name == "rate")
        or (isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "S_FIXED" for t in node.targets))
    ]
    assert len(wanted) == 2, "calibration_sim.py no longer defines rate and S_FIXED"
    namespace = {"np": np, "rng": np.random.default_rng(20260822)}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SIM_PATH), "exec"), namespace)
    return namespace


# -- amplitudes and plans ---------------------------------------------------------------


def test_amplitudes_span_the_bracket_evenly_in_log_pressure():
    amps = maths.estimation_amplitudes(10.0, 160.0, 5, maths.LOG_PRESSURE)
    assert amps[0] == pytest.approx(10.0) and amps[-1] == pytest.approx(160.0)
    assert np.allclose(np.diff(np.log10(amps)), np.log10(2.0))


def test_amplitudes_are_linear_for_the_linear_fit():
    amps = maths.estimation_amplitudes(10.0, 50.0, 5, maths.LINEAR_PRESSURE)
    assert amps == pytest.approx((10.0, 20.0, 30.0, 40.0, 50.0))


@pytest.mark.parametrize("low, high", [(0.0, 100.0), (50.0, 50.0), (80.0, 20.0)])
def test_a_bracket_with_nothing_to_sample_is_refused(low, high):
    assert not maths.bracket_is_usable(low, high, maths.LOG_PRESSURE)
    with pytest.raises(AssertionError):
        maths.estimation_amplitudes(low, high, 10, maths.LOG_PRESSURE)


def test_a_zero_floor_is_usable_on_a_linear_axis():
    assert maths.bracket_is_usable(0.0, 100.0, maths.LINEAR_PRESSURE)


def test_catch_trials_are_added_not_substituted():
    assert maths.catch_trial_count(10, 0.2) == 2


@pytest.mark.parametrize("seed", range(40))
def test_the_plan_is_random_hides_catch_trials_and_keeps_every_amplitude(seed):
    amps = maths.estimation_amplitudes(10.0, 160.0, 10, maths.LOG_PRESSURE)
    plans = maths.estimation_plans(amps, 2, random.Random(seed))
    assert [p.presentation_order for p in plans] == list(range(1, 13))
    assert sorted(p.pressure_kpa for p in plans if not p.catch_trial) == sorted(amps)
    catches = [i for i, p in enumerate(plans) if p.catch_trial]
    assert len(catches) == 2
    assert 0 not in catches, "a catch trial is never first"
    assert catches[1] - catches[0] > 1, "and never follows another"
    assert all(p.pressure_kpa == 0.0 and p.amplitude_index == 0 for p in plans if p.catch_trial)


def test_the_same_seed_gives_the_same_order():
    amps = maths.estimation_amplitudes(10.0, 160.0, 10, maths.LOG_PRESSURE)
    first = maths.estimation_plans(amps, 2, random.Random(3))
    assert first == maths.estimation_plans(amps, 2, random.Random(3))
    assert first != maths.estimation_plans(amps, 2, random.Random(4))


def test_the_order_is_not_ascending_for_most_seeds():
    amps = maths.estimation_amplitudes(10.0, 160.0, 10, maths.LOG_PRESSURE)
    ascending = sum(
        [p.amplitude_index for p in maths.estimation_plans(amps, 0, random.Random(s))]
        == list(range(1, 11))
        for s in range(50)
    )
    assert ascending == 0


# -- the fit ----------------------------------------------------------------------------


def test_an_exact_line_is_recovered_and_inverted():
    pressures = [10.0, 20.0, 40.0, 80.0, 160.0]
    ratings = [5 + 30 * np.log10(p) for p in pressures]
    fit = maths.fit_ratings(pressures, ratings, maths.LOG_PRESSURE)
    assert fit.intercept == pytest.approx(5.0)
    assert fit.slope == pytest.approx(30.0)
    assert fit.r_squared == pytest.approx(1.0)
    assert fit.residual_sd == pytest.approx(0.0, abs=1e-9)
    assert fit.spearman_rho == pytest.approx(1.0)
    assert fit.span_vas == pytest.approx(30 * np.log10(16))
    assert fit.invert(5 + 30 * np.log10(50.0)) == pytest.approx(50.0)


def test_the_fit_is_rating_on_pressure_not_the_reverse():
    """SPEC.md 9: the other direction gives different numbers, and is wrong here."""
    pressures = [10.0, 20.0, 40.0, 80.0, 160.0]
    ratings = [12.0, 18.0, 45.0, 52.0, 81.0]
    fit = maths.fit_ratings(pressures, ratings, maths.LOG_PRESSURE)
    x = np.log10(pressures)
    b, a = np.polyfit(x, ratings, 1)
    assert fit.slope == pytest.approx(b) and fit.intercept == pytest.approx(a)
    reverse_b, reverse_a = np.polyfit(ratings, x, 1)
    assert fit.invert(50.0) != pytest.approx(10 ** (reverse_a + reverse_b * 50.0), rel=1e-3)


def test_a_falling_fit_cannot_be_inverted():
    fit = maths.fit_ratings([10.0, 20.0, 40.0], [60.0, 40.0, 20.0], maths.LOG_PRESSURE)
    assert not fit.monotonic
    assert fit.invert(30.0) is None
    assert fit.extrapolated(None)


def test_ratings_that_do_not_vary_explain_nothing():
    fit = maths.fit_ratings([10.0, 20.0, 40.0], [30.0, 30.0, 30.0], maths.LOG_PRESSURE)
    assert fit.r_squared == 0.0
    assert fit.spearman_rho == 0.0


def test_extrapolation_is_outside_the_sampled_bracket():
    fit = maths.fit_ratings([10.0, 20.0, 40.0], [10.0, 50.0, 90.0], maths.LOG_PRESSURE)
    assert not fit.extrapolated(20.0)
    assert fit.extrapolated(9.0) and fit.extrapolated(41.0)


def test_ties_get_average_ranks():
    assert maths.spearman_rho([1, 2, 3, 4], [1, 2, 2, 3]) == pytest.approx(0.9486833)


@pytest.mark.parametrize("sigma", [5.0, 10.0])
def test_the_calibration_sim_observer_is_recovered(observer, sigma):
    """P20, P30 and P80 read off the fit land on the observer's true points."""
    rate, slope = observer["rate"], observer["S_FIXED"]
    rng = random.Random(1)
    errors = []
    for _ in range(300):
        p40 = 10 ** rng.uniform(1.2, 1.9)
        # The bracket a participant producing 10 % and 90 % would set, before noise.
        low = p40 * 10 ** ((10 - 40) / slope)
        high = p40 * 10 ** ((90 - 40) / slope)
        amps = maths.estimation_amplitudes(low, high, 10, maths.LOG_PRESSURE)
        ratings = [rate(p, p40, sigma) for p in amps]
        fit = maths.fit_ratings(amps, ratings, maths.LOG_PRESSURE)
        for pct in (20.0, 30.0, 80.0):
            true = p40 * 10 ** ((pct - 40) / slope)
            errors.append(np.log10(fit.invert(pct)) - np.log10(true))
    errors = np.asarray(errors)
    assert abs(errors.mean()) < 0.02, "the inverted targets are not biased"
    # Precision scales with the rating noise. About 0.1 log10 (a factor of 1.26) at the
    # simulation's sigma of 10 is what ten points and a free slope give; a broken inversion
    # is out by far more.
    assert np.sqrt((errors**2).mean()) < 0.012 * sigma


# -- stage 1 ----------------------------------------------------------------------------


CRITERIA = maths.Stage1Criteria(
    min_span_vas=40.0, min_spearman_rho=0.56, max_residual_sd_vas=25.0
)


def _fit(ratings):
    pressures = maths.estimation_amplitudes(10.0, 160.0, len(ratings), maths.LOG_PRESSURE)
    return maths.fit_ratings(pressures, ratings, maths.LOG_PRESSURE)


def test_a_good_fit_passes():
    assert maths.stage1_failures(_fit([10, 22, 28, 40, 47, 55, 66, 70, 82, 90]), CRITERIA) == ()


def test_a_flat_fit_fails_as_flat():
    reasons = maths.stage1_failures(_fit([40, 42, 41, 44, 45, 44, 46, 47, 48, 49]), CRITERIA)
    assert maths.FLAT in reasons


def test_a_falling_fit_fails_as_non_monotonic():
    reasons = maths.stage1_failures(_fit([90, 82, 70, 66, 55, 47, 40, 28, 22, 10]), CRITERIA)
    assert maths.NON_MONOTONIC in reasons


def test_a_scattered_fit_fails_on_rank_order_and_residuals():
    reasons = maths.stage1_failures(_fit([10, 95, 5, 90, 20, 85, 30, 99, 15, 95]), CRITERIA)
    assert maths.POOR_RESIDUALS in reasons
    assert maths.NON_MONOTONIC in reasons


def test_the_criteria_come_from_config():
    criteria = maths.Stage1Criteria.from_config(
        {"min_span_vas": 1, "min_spearman_rho": 0.5, "max_residual_sd_vas": 9}
    )
    assert criteria == maths.Stage1Criteria(1.0, 0.5, 9.0)


# -- catch trials -----------------------------------------------------------------------


def test_catch_trials_count_as_felt_at_the_just_noticeable_anchor():
    assert maths.catch_felt_fraction([0.0, 10.0], 10.0) == 0.5
    assert maths.catch_felt_fraction([0.0, 9.9], 10.0) == 0.0
    assert maths.catch_felt_fraction([], 10.0) is None


# -- gains, the comparison rule and delivery --------------------------------------------


def test_a_gain_is_the_geometric_mean_setting_over_the_reference():
    assert maths.gain(50.0, [40.0, 90.0]) == pytest.approx(60.0 / 50.0)


def test_a_gain_needs_a_reference_above_zero():
    with pytest.raises(AssertionError):
        maths.gain(0.0, [10.0, 20.0])


def test_only_an_order_free_winner_is_a_mismatch():
    """docs/research/R33: first/first is what equal channels plus a time-order bias give."""
    s, r = maths.TEST_STRONGER, maths.REFERENCE_STRONGER
    assert maths.comparison_winner([s, s, s, s]) == s
    assert maths.comparison_winner([r, r]) == r
    assert maths.comparison_winner([s, r]) is None
    assert maths.comparison_winner([]) is None


def test_every_channel_gets_the_level_through_its_gain_under_the_ceiling():
    levels = maths.per_channel(100.0, {1: 1.2, 3: 1.0, 5: 3.0}, 250.0)
    assert levels == {1: pytest.approx(120.0), 3: 100.0, 5: 250.0}


def test_the_timing_only_stand_in_passes_through_the_step_1_settings():
    line = maths.line_through_anchors([(10.0, 20.0), (90.0, 180.0)], maths.LOG_PRESSURE)
    assert line.invert(10.0) == pytest.approx(20.0)
    assert line.invert(90.0) == pytest.approx(180.0)
