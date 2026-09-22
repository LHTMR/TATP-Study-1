"""Virtual participants. SPEC.md 17.5.

Every press plan is driven into the **real** state machine it will drive in a session --
`VasState` and `AdjustmentState`, not a stand-in -- so what is tested is that the presses
produce the intended rating or pressure through the code a participant actually operates. A
test asserting that `vas_presses` returned a tuple of the length this module expected would
pass while the VAS rules changed underneath it.
"""

from __future__ import annotations

import functools
import math
import random

import pytest

from sim import responders as sim
from tatp import config as cfg
from tatp.clock import Clock
from tatp.responder import Action
from tatp.touchcal import AdjustmentState
from tatp.ui.vas import VasState

SEED = 20260922


class FakeClock(Clock):
    def __init__(self):
        super().__init__()
        self.now = 0.0

    def elapsed_s(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def vas_config(loaded):
    return loaded.study1["vas"]


@pytest.fixture
def adjustment_config(loaded):
    return loaded.hardware["adjustment"]


def play_vas(presses, state: VasState):
    """Deliver a press plan to a VAS exactly as the widget would, and return the response."""
    state.cue()
    for press in presses:
        if press.action is Action.CONFIRM:
            return state.confirm()
        state.press(press.action)
    raise AssertionError("the plan never confirmed, so the participant is still sitting there")


def play_adjustment(presses, state: AdjustmentState):
    """Deliver a press plan to an adjustment. A tap is instantaneous, a hold advances time."""
    now = 0.0
    for press in presses:
        if press.action is Action.CONFIRM:
            return state.pressure_kpa
        state.press(press.action, now)
        now += press.hold_s
        # The trial ticks while a button is down; one tick at the end of the hold is enough,
        # because the travel is a closed-form integral and not a per-tick accumulation
        # (docs/LOG.md N6.23).
        state.tick(now)
        state.release(press.action, now)
    raise AssertionError("the plan never confirmed")


# -- the observer model ----------------------------------------------------------------------


def load_calibration_sim():
    """Import docs/calibration_sim.py by path, executing it. It is a record, not a package.

    Importable at all only since its two driver blocks went under a `__main__` guard (22 Sep
    2026); before that an import ran 4000 iterations and printed. Nothing else about the file
    changed, so its numbers stay traceable to the code as it was run (docs/LOG.md N6.8).
    """
    import importlib.util
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "docs" / "calibration_sim.py"
    spec = importlib.util.spec_from_file_location("calibration_sim", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Cached for the tests that only want the constants, because each execution pays for numpy.
# `load_calibration_sim` stays uncached so that the test asserting the import is silent does a
# real one -- a cached call executes no module code and would pass however loud the file got.
calibration_sim = functools.cache(load_calibration_sim)


def test_the_slope_matches_the_simulation_it_is_taken_from():
    """`SLOPE_VAS_PER_LOG10` is repeated from docs/calibration_sim.py, so it could drift."""
    assert sim.SLOPE_VAS_PER_LOG10 == pytest.approx(calibration_sim().S_FIXED)


def test_the_pain_model_matches_the_simulation_it_is_taken_from():
    """The whole model, not just its slope -- the reason the file is worth importing.

    `rate()` there draws its own noise from a module-level generator, so it is compared at the
    noise the responder would have drawn, supplied to both.
    """
    reference = calibration_sim()
    for force_mn in (98.0, 255.0, 588.0):
        expected = 40 + reference.S_FIXED * (math.log10(force_mn) - math.log10(255.0))
        assert sim.pain_rating_pct(force_mn, 255.0, noise_vas=0.0) == pytest.approx(expected)


def test_importing_the_simulation_runs_nothing(capsys):
    """The guard is what makes the import above cheap. If a driver call ever escapes it, this
    fails rather than the suite quietly growing a 4000-iteration simulation in it."""
    load_calibration_sim()
    assert capsys.readouterr().out == ""


def test_the_rating_at_f40_is_forty_by_definition():
    assert sim.pain_rating_pct(255.0, 255.0, noise_vas=0.0) == pytest.approx(40.0)


def test_doubling_the_force_adds_the_slope_times_log_two():
    """A whole log unit either side of F40 falls off the scale and is clipped, so the slope is
    checked over a step that stays on it -- which is also the only range the study visits."""
    at = sim.pain_rating_pct(255.0, 255.0, noise_vas=0.0)
    doubled = sim.pain_rating_pct(510.0, 255.0, noise_vas=0.0)
    assert doubled - at == pytest.approx(sim.SLOPE_VAS_PER_LOG10 * math.log10(2.0))


def test_ratings_are_clipped_to_the_scale():
    assert sim.pain_rating_pct(0.08, 255.0, noise_vas=0.0) == 0.0
    assert sim.pain_rating_pct(2940.0, 255.0, noise_vas=100.0) == 100.0


def test_the_touch_anchors_land_on_the_percentages_the_scale_labels():
    """The two anchor pressures must map to the two labelled points, or the simulated
    participant is inconsistent with the question it is being asked (SPEC.md 10.4)."""
    anchors = (10.0, 90.0)
    low = sim.intensity_rating_pct(
        sim.JUST_NOTICEABLE_KPA, sim.JUST_NOTICEABLE_KPA, sim.JUST_UNCOMFORTABLE_KPA,
        anchors, noise_vas=0.0,
    )
    high = sim.intensity_rating_pct(
        sim.JUST_UNCOMFORTABLE_KPA, sim.JUST_NOTICEABLE_KPA, sim.JUST_UNCOMFORTABLE_KPA,
        anchors, noise_vas=0.0,
    )
    assert low == pytest.approx(10.0)
    assert high == pytest.approx(90.0)


# -- the press plans, against the real VAS ----------------------------------------------------


@pytest.mark.parametrize("target", [0.0, 7.5, 25.0, 40.0, 62.5, 75.0, 100.0])
def test_a_vas_plan_lands_on_the_target_it_was_given(target, vas_config):
    state = VasState(vas_config, FakeClock())
    response = play_vas(sim.vas_presses(target, vas_config), state)
    step = float(vas_config["move_step_pct"])
    # Within half a step: the reachable points are quantised by `move_step_pct`, and a
    # participant cannot land between two of them.
    assert response.rating_percent == pytest.approx(target, abs=step / 2)


def test_a_vas_plan_starts_on_the_side_nearer_the_target(vas_config):
    """The first press only reveals the marker, so choosing the far side would manufacture a
    direction change that the participant never made (SPEC.md 10.2)."""
    assert sim.vas_presses(5.0, vas_config)[0].action is Action.DECREASE
    assert sim.vas_presses(95.0, vas_config)[0].action is Action.INCREASE


def test_a_target_below_the_left_start_needs_no_direction_change(vas_config):
    state = VasState(vas_config, FakeClock())
    response = play_vas(sim.vas_presses(10.0, vas_config), state)
    assert response.direction_changes == 0


def test_the_normal_responder_rates_a_stronger_stimulus_higher(vas_config):
    """Through the real VAS, not through the model: the presses have to carry the ordering."""
    responder = sim.Responder(random.Random(SEED))
    ratings = []
    for force_mn in (98.0, 255.0, 980.0):
        state = VasState(vas_config, FakeClock())
        plan = responder.vas_actions("pain", force_mn, vas_config)
        ratings.append(play_vas(plan, state).rating_percent)
    assert ratings[0] < ratings[1] < ratings[2]


def test_the_same_seed_gives_the_same_ratings(vas_config):
    """SPEC.md 17.3 asserts a session is reproducible from its seed, which is only true if the
    virtual participant draws from a generator the session owns (docs/LOG.md N6.13)."""
    def run():
        responder = sim.Responder(random.Random(SEED))
        state = VasState(vas_config, FakeClock())
        return play_vas(responder.vas_actions("pain", 255.0, vas_config), state).rating_percent

    assert run() == run()


def test_two_responders_with_different_seeds_differ(vas_config):
    def run(seed):
        responder = sim.Responder(random.Random(seed))
        state = VasState(vas_config, FakeClock())
        return play_vas(responder.vas_actions("pain", 255.0, vas_config), state).rating_percent

    assert run(SEED) != run(SEED + 1)


# -- the adversarial responders ---------------------------------------------------------------


def test_rates_zero_reaches_the_bottom_of_the_scale(vas_config):
    responder = sim.RatesZero(random.Random(SEED))
    state = VasState(vas_config, FakeClock())
    plan = responder.vas_actions("pain", 255.0, vas_config)
    assert play_vas(plan, state).rating_percent == 0.0


def test_rates_maximum_reaches_the_top_of_the_scale(vas_config):
    responder = sim.RatesMaximum(random.Random(SEED))
    state = VasState(vas_config, FakeClock())
    plan = responder.vas_actions("pain", 255.0, vas_config)
    assert play_vas(plan, state).rating_percent == 100.0


def test_rates_maximum_clears_the_intolerable_threshold(loaded, vas_config):
    """The error path this responder exists to fire: the SPEC.md 8.2 flag."""
    responder = sim.RatesMaximum(random.Random(SEED))
    state = VasState(vas_config, FakeClock())
    plan = responder.vas_actions("pain", 255.0, vas_config)
    rating = play_vas(plan, state).rating_percent
    assert rating >= float(loaded.study1["pinprick"]["intolerable_vas_pct"])


def test_confirming_without_moving_produces_no_response(vas_config):
    """docs/LOG.md N6.11: there is nothing to record, so nothing is recorded."""
    responder = sim.ConfirmsWithoutMoving(random.Random(SEED))
    state = VasState(vas_config, FakeClock())
    plan = responder.vas_actions("pain", 255.0, vas_config)
    assert len(plan) == 1
    assert play_vas(plan, state) is None


def test_stopping_mid_rating_presses_the_stop_and_nothing_else(vas_config):
    responder = sim.StopsMidRating(random.Random(SEED))
    plan = responder.vas_actions("pain", 255.0, vas_config)
    assert [press.action for press in plan] == [Action.EMERGENCY_STOP]


# -- the press plans, against the real adjustment ----------------------------------------------


@pytest.mark.parametrize("target", [15.0, 150.0, 200.0])
def test_an_adjustment_plan_lands_on_the_target_from_below(target, adjustment_config):
    state = AdjustmentState(adjustment_config, 0.0, 250.0, start_kpa=0.0)
    plan = sim.adjustment_presses(target, 0.0, float(adjustment_config["tap_step_kpa"]))
    settled = play_adjustment(plan, state)
    assert settled == pytest.approx(target, abs=float(adjustment_config["tap_step_kpa"]))


def test_an_adjustment_plan_lands_on_the_target_from_above(adjustment_config):
    state = AdjustmentState(adjustment_config, 0.0, 250.0, start_kpa=250.0)
    plan = sim.adjustment_presses(15.0, 250.0, float(adjustment_config["tap_step_kpa"]))
    assert play_adjustment(plan, state) == pytest.approx(
        15.0, abs=float(adjustment_config["tap_step_kpa"])
    )


def test_the_normal_responder_settles_at_its_own_anchor_pressures(adjustment_config):
    responder = sim.Responder(random.Random(SEED))
    for target_key, expected in (
        ("just_noticeable", sim.JUST_NOTICEABLE_KPA),
        ("just_uncomfortable", sim.JUST_UNCOMFORTABLE_KPA),
    ):
        state = AdjustmentState(adjustment_config, 0.0, 250.0, start_kpa=0.0)
        plan = responder.adjustment_actions(target_key, 0.0, adjustment_config)
        assert play_adjustment(plan, state) == pytest.approx(
            expected, abs=float(adjustment_config["tap_step_kpa"])
        )


def test_an_unknown_adjustment_target_raises_rather_than_guessing(adjustment_config):
    responder = sim.Responder(random.Random(SEED))
    with pytest.raises(ValueError, match="no simulated pressure"):
        responder.settled_kpa("pleasantness")


def test_tapping_accumulates_the_exploration_the_minimum_is_measured_against(adjustment_config):
    """`min_exploration_kpa` is recorded, not enforced (docs/LOG.md N2.5), so what
    matters is that a normal responder genuinely explores rather than confirming on the spot."""
    state = AdjustmentState(adjustment_config, 0.0, 250.0, start_kpa=0.0)
    responder = sim.Responder(random.Random(SEED))
    plan = responder.adjustment_actions("just_uncomfortable", 0.0, adjustment_config)
    play_adjustment(plan, state)
    assert state.exploration_kpa == pytest.approx(sim.JUST_UNCOMFORTABLE_KPA, abs=1.0)


def test_holding_to_maximum_stops_at_the_range_end(adjustment_config):
    """SPEC.md 13: the participant who does not let go is stopped by the range, not by luck."""
    responder = sim.HoldsToMaximum(random.Random(SEED))
    state = AdjustmentState(adjustment_config, 0.0, 250.0, start_kpa=0.0)
    plan = responder.adjustment_actions("just_uncomfortable", 0.0, adjustment_config)
    assert play_adjustment(plan, state) == 250.0


def test_holding_to_maximum_takes_the_real_seconds_the_ramp_needs(adjustment_config):
    """The hold cannot be accelerated away (docs/LOG.md N6.22), so the validator pays it.
    If this number ever drops to nothing, the hold has stopped being a hold."""
    responder = sim.HoldsToMaximum(random.Random(SEED))
    plan = responder.adjustment_actions("just_uncomfortable", 0.0, adjustment_config)
    assert plan[0].hold_s > 1.0


def test_travel_that_the_range_refused_is_not_exploration(adjustment_config):
    """A hold pressed against the end stop teaches the participant nothing, and the state says
    so. Pinned here because `HoldsToMaximum` is the only responder that reaches an end stop."""
    responder = sim.HoldsToMaximum(random.Random(SEED))
    state = AdjustmentState(adjustment_config, 0.0, 250.0, start_kpa=0.0)
    play_adjustment(responder.adjustment_actions("x", 0.0, adjustment_config), state)
    assert state.exploration_kpa == pytest.approx(250.0)


# -- what is deliberately absent ---------------------------------------------------------------


def test_the_deferred_responders_are_named_with_a_reason():
    """SPEC.md 17.5 names nine adversarial responders and six are built. The other three must
    be recorded as absent with the milestone that will give them an error path to fire --
    otherwise the gap becomes invisible and the validator looks complete."""
    assert set(sim.DEFERRED) == {
        "f40_below_bottom_filament",
        "f40_above_top_filament",
        "stops_responding",
    }
    for name, reason in sim.DEFERRED.items():
        assert "Milestone" in reason, f"{name} does not say when it becomes buildable"


def test_every_built_responder_has_a_distinct_name():
    names = [responder.name for responder in sim.BUILT]
    assert len(names) == len(set(names))
