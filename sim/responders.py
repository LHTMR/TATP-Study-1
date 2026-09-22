"""Virtual participants. SPEC.md 17.5.

**A responder is not a rating generator.** The software's only input is four keys on the
Logitech R400 (`tatp/responder.py`), so a responder's output is a sequence of `Press` objects --
what a thumb does -- and the rating or the pressure is whatever the real state machine in
`tatp/ui/vas.py` or `tatp/touchcal.py` produces when those presses are delivered to it. A
responder that returned a number directly would be testing arithmetic this repository does not
contain, and would pass while the thing a participant actually operates was broken.

That split is also what makes the adversarial responders cheap. "Rates everything 0", "confirms
without moving the marker" and "holds the adjustment to maximum" are not three psychophysical
models; they are three press policies over one interface. Only the normal responder needs a
model at all.

**This module imports no Qt**, so every responder is testable without a display, in the same way
`VasState` is separated from `VasWidget` (docs/LOG.md N6.9). Delivering these presses as
key events is the validator runner's job, not this module's.

**What is here and what is not.** SPEC.md 17.5 names one normal responder and nine adversarial
ones. An adversarial responder exists to assert that a specific error path fires, so one whose
error path does not exist yet would assert nothing while looking as though it did -- which is
the failure `docs/LOG.md` records under N6.16 and N6.27 and `SPEC.md` 17.3 builds its rule on. The
six built here are the ones whose path exists in today's code. The three deferred are named in
`DEFERRED` below, with the milestone that will make each of them mean something.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tatp.responder import Action

# -- the observer model ----------------------------------------------------------------------

# From `docs/calibration_sim.py`, which is the record of the simulation behind
# `docs/calibration_methods_comparison.md` section 5.1 and is excluded from ruff so that its
# numbers stay traceable to the code as it was run (docs/LOG.md N6.8). It is repeated
# here rather than imported so that this module depends on no numpy and no file outside the
# package; `tests/test_responders.py` imports that file and fails if the two ever disagree, so
# it is still single-sourced. That import became possible on 22 Sep 2026, when the simulation's
# two driver blocks went under a `__main__` guard -- the only change made to it.
#
# Ng et al. 2024 give a Weber fraction of 0.88 on the hand dorsum, so one JND is log10(1.88) in
# log10 force. In 2AFC that is d' ~ 1, making the mean shift sqrt(2) * sigma_disc; with a
# discrimination sigma of 10 VAS points that is 51.6 VAS points per log10 unit of force.
SLOPE_VAS_PER_LOG10 = math.sqrt(2) / math.log10(1.88) * 10.0

# F40 is *defined* as the force at which the median pain rating is 40, so this is the model's
# definition rather than a tunable (SPEC.md 8).
RATING_AT_F40_PCT = 40.0

# The spread of one reported rating about the model's prediction. 10 VAS points is the
# `sig` the comparison document's headline conditions use.
REPORTING_SIGMA_VAS = 10.0

RATING_MIN_PCT = 0.0
RATING_MAX_PCT = 100.0

# The simulated participant's own body. These are properties of an invented person, not study
# configuration, and nothing the validator asserts depends on their values -- they need only lie
# inside the ranges the software offers, so that a responder exercises the ordinary path rather
# than an end stop. They are deliberately NOT in `config/`: a configurable simulated participant
# would be a config option the study itself never reads (CLAUDE.md).
F40_MN = 255.0  # the 26 g filament, mid-ladder
JUST_NOTICEABLE_KPA = 15.0
JUST_UNCOMFORTABLE_KPA = 150.0

# Which VAS the rating model applies to. `pain` is the pinprick observer model above and
# `intensity` the touch scale, interpolated between the anchor pressures. The other scales --
# pleasantness, relaxation, alertness -- have no stimulus to be a function of, so a normal
# responder answers them from a fixed disposition rather than from a model.
PAIN_SCALE = "pain"
INTENSITY_SCALE = "intensity"
DISPOSITION_PCT = 60.0

# SPEC.md 17.5 names nine adversarial responders. These three have no error path in today's
# code, so they are not built: a responder asserting nothing is worse than an absent one,
# because the validator would count it as a check that passed.
DEFERRED = {
    "f40_below_bottom_filament": "Milestone 3 -- there is no filament search to run off the "
    "bottom of the ladder yet, only one application of the configured starting filament.",
    "f40_above_top_filament": "Milestone 3 -- as above, and `out_of_range` has no writer.",
    "stops_responding": "Milestone 5 -- the adjustment time-out exists, but the no-response "
    "warning it would assert against (`vas.no_response_warning_s`) has no consumer in the "
    "slice, so this would test a timer rather than the software's response to silence.",
}


def pain_rating_pct(force_mn: float, f40_mn: float, noise_vas: float) -> float:
    """rating = 40 + s*(log10 F - log10 F40) + noise, clipped. SPEC.md 17.5.

    `noise_vas` is passed in already drawn rather than drawn here, so a responder owns its own
    generator and two responders sharing a module-level one cannot make each other's sessions
    irreproducible.
    """
    assert force_mn > 0 and f40_mn > 0, "a force of zero has no logarithm"
    rating = (
        RATING_AT_F40_PCT
        + SLOPE_VAS_PER_LOG10 * (math.log10(force_mn) - math.log10(f40_mn))
        + noise_vas
    )
    return min(max(rating, RATING_MIN_PCT), RATING_MAX_PCT)


def intensity_rating_pct(pressure_kpa: float, noticeable_kpa: float, uncomfortable_kpa: float,
                         anchors_pct: tuple[float, float], noise_vas: float) -> float:
    """The touch scale, linear in log pressure between the two anchors the scale names.

    Not the observer model: that one is grounded in a pinprick discrimination study and says
    nothing about garment pressure. This is a plausible monotone mapping that puts the
    participant's two anchor pressures at the two percentages the scale labels (SPEC.md 10.4),
    which is all a virtual participant needs in order to be internally consistent.
    """
    assert pressure_kpa >= 0, "pressure is not negative"
    low_pct, high_pct = anchors_pct
    # Below the noticeable anchor there is no logarithm to take and nothing to interpolate: the
    # participant reports the bottom of the scale.
    if pressure_kpa <= 0:
        return RATING_MIN_PCT
    span = math.log10(uncomfortable_kpa) - math.log10(noticeable_kpa)
    assert span > 0, "the noticeable anchor must sit below the uncomfortable one"
    fraction = (math.log10(pressure_kpa) - math.log10(noticeable_kpa)) / span
    rating = low_pct + fraction * (high_pct - low_pct) + noise_vas
    return min(max(rating, RATING_MIN_PCT), RATING_MAX_PCT)


# -- what a thumb does -----------------------------------------------------------------------


@dataclass(frozen=True)
class Press:
    """One button press. `hold_s` is real seconds held down; 0 is a tap.

    Real, not scaled: the adjustment's tap threshold and ramp describe a hand and are read off
    `Clock.real_elapsed_s()` (docs/LOG.md N6.22). A hold that the accelerated clock
    shortened would be a different control, not a faster session.
    """

    action: Action
    hold_s: float = 0.0


def vas_presses(target_pct: float, vas_config: dict) -> tuple[Press, ...]:
    """The presses that take the hidden marker to the achievable point nearest `target_pct`.

    The first press only reveals the marker, at the start position for the side pressed
    (SPEC.md 10.2), so the side is chosen to be whichever start is nearer the target -- fewer
    presses, and the direction change that a wrong-side start would cause is not manufactured.
    """
    start_left = float(vas_config["start_pct_after_left_press"])
    start_right = float(vas_config["start_pct_after_right_press"])
    step = float(vas_config["move_step_pct"])
    assert step > 0, "vas.move_step_pct must be positive"

    if abs(target_pct - start_left) <= abs(target_pct - start_right):
        first, start = Action.DECREASE, start_left
    else:
        first, start = Action.INCREASE, start_right
    move = Action.DECREASE if target_pct < start else Action.INCREASE
    steps = int(round(abs(target_pct - start) / step))
    return (Press(first),) + tuple(Press(move) for _ in range(steps)) + (Press(Action.CONFIRM),)


def adjustment_presses(target_kpa: float, start_kpa: float, tap_step_kpa: float
                       ) -> tuple[Press, ...]:
    """Taps from the start pressure to the target, then a confirm.

    Taps rather than a hold, because a tap costs no real time while a hold must be held for real
    seconds (N6.22 again) -- and because tapping is what the range end the adjustment
    starts from invites. The exploration this accumulates is the distance travelled, which is
    what `min_exploration_kpa` is measured against (docs/LOG.md N2.5).
    """
    assert tap_step_kpa > 0, "adjustment.tap_step_kpa must be positive"
    action = Action.DECREASE if target_kpa < start_kpa else Action.INCREASE
    taps = int(round(abs(target_kpa - start_kpa) / tap_step_kpa))
    return tuple(Press(action) for _ in range(taps)) + (Press(Action.CONFIRM),)


# -- the responders --------------------------------------------------------------------------


class Responder:
    """The normal responder: the observer model, and presses that reach what it decides.

    `rng` is a `random.Random`, supplied by the caller and never created here, so a simulated
    session is reproducible from the seed the session itself records (docs/LOG.md N6.13).
    """

    name = "normal"

    def __init__(self, rng, f40_mn: float = F40_MN,
                 noticeable_kpa: float = JUST_NOTICEABLE_KPA,
                 uncomfortable_kpa: float = JUST_UNCOMFORTABLE_KPA):
        self.rng = rng
        self.f40_mn = f40_mn
        self.noticeable_kpa = noticeable_kpa
        self.uncomfortable_kpa = uncomfortable_kpa

    # -- what the participant decides ---------------------------------------------------

    def rating_pct(self, scale: str, stimulus: float | None, anchors_pct: tuple[float, float]
                   ) -> float:
        """The rating this participant would give. `stimulus` is mN for pain, kPa for touch."""
        noise = self.rng.gauss(0.0, REPORTING_SIGMA_VAS)
        if scale == PAIN_SCALE:
            assert stimulus is not None, f"the {scale!r} scale rates a force, none was given"
            return pain_rating_pct(stimulus, self.f40_mn, noise)
        if scale == INTENSITY_SCALE:
            assert stimulus is not None, f"the {scale!r} scale rates a pressure, none was given"
            return intensity_rating_pct(
                stimulus, self.noticeable_kpa, self.uncomfortable_kpa, anchors_pct, noise
            )
        # No stimulus to be a function of. A disposition plus noise, not a model.
        return min(max(DISPOSITION_PCT + noise, RATING_MIN_PCT), RATING_MAX_PCT)

    def settled_kpa(self, target_key: str) -> float:
        """The pressure this participant would settle on for an `anchor_prompt_keys` target."""
        if target_key == "just_noticeable":
            return self.noticeable_kpa
        if target_key == "just_uncomfortable":
            return self.uncomfortable_kpa
        raise ValueError(f"no simulated pressure for adjustment target {target_key!r}")

    # -- what the participant does ------------------------------------------------------

    def vas_actions(self, scale: str, stimulus: float | None, vas_config: dict,
                    anchors_pct: tuple[float, float] = (10.0, 90.0)) -> tuple[Press, ...]:
        return vas_presses(self.rating_pct(scale, stimulus, anchors_pct), vas_config)

    def adjustment_actions(self, target_key: str, start_kpa: float,
                           adjustment_config: dict) -> tuple[Press, ...]:
        return adjustment_presses(
            self.settled_kpa(target_key), start_kpa,
            float(adjustment_config["tap_step_kpa"]),
        )


class RatesZero(Responder):
    """Rates everything 0. Asserts the bottom of the scale is reachable and recordable."""

    name = "rates_zero"

    def rating_pct(self, scale, stimulus, anchors_pct) -> float:
        return RATING_MIN_PCT


class RatesMaximum(Responder):
    """Rates everything 100.

    The error path this fires is the intolerable flag of SPEC.md 8.2: every rating clears
    `pinprick.intolerable_vas_pct`, so the row flag and the `intolerable_rating` log event must
    appear. The *cap* those feed is Milestone 3 and is not asserted here.
    """

    name = "rates_maximum"

    def rating_pct(self, scale, stimulus, anchors_pct) -> float:
        return RATING_MAX_PCT


class RatesRandomly(Responder):
    """Rates uniformly at random, ignoring the stimulus.

    Asserts nothing about the numbers -- it exists so that the writers and the fit are exposed
    to ratings carrying no signal, where an estimator that assumes monotonicity will show it.
    """

    name = "rates_randomly"

    def rating_pct(self, scale, stimulus, anchors_pct) -> float:
        return self.rng.uniform(RATING_MIN_PCT, RATING_MAX_PCT)


class ConfirmsWithoutMoving(Responder):
    """Presses confirm with the marker never shown.

    Asserts the path of docs/LOG.md N6.11: `VasState.confirm()` returns None, the widget
    emits `pressed_without_marker` instead of `confirmed`, and the session logs the press rather
    than writing a rating row with an invented value.
    """

    name = "confirms_without_moving"

    def vas_actions(self, scale, stimulus, vas_config, anchors_pct=(10.0, 90.0)
                    ) -> tuple[Press, ...]:
        return (Press(Action.CONFIRM),)


class StopsMidRating(Responder):
    """Presses the emergency stop instead of answering.

    Asserts SPEC.md 13 end to end: the garment stops, the participant screen changes, the event
    is logged with its trial index, and -- docs/LOG.md N6.19 -- no `pinprick` row is
    written, because no rating was given and there is no honest value for those columns.
    """

    name = "stops_mid_rating"

    def vas_actions(self, scale, stimulus, vas_config, anchors_pct=(10.0, 90.0)
                    ) -> tuple[Press, ...]:
        return (Press(Action.EMERGENCY_STOP),)


class HoldsToMaximum(Responder):
    """Holds the adjustment button until the pressure stops rising.

    Asserts the two limits of SPEC.md 13 act on a participant who does not let go: the range end
    stops the travel and the rate limit governs how fast it got there. `hold_s` is real seconds
    and is deliberately long enough to traverse the whole range -- about 6 s at the configured
    ramp -- so a validator running this responder pays that time and cannot accelerate it away.
    """

    name = "holds_to_maximum"

    def adjustment_actions(self, target_key, start_kpa, adjustment_config) -> tuple[Press, ...]:
        return (Press(Action.INCREASE, hold_s=self.hold_s(adjustment_config)),
                Press(Action.CONFIRM))

    def hold_s(self, adjustment_config: dict, range_kpa: float = 250.0) -> float:
        """Long enough for the ramp to cover `range_kpa`, plus the delay before it engages."""
        delay_s = float(adjustment_config["hold_delay_s"])
        ramp_s = float(adjustment_config["hold_ramp_duration_s"])
        initial = float(adjustment_config["hold_rate_initial_kpa_s"])
        final = float(adjustment_config["hold_rate_final_kpa_s"])
        # Distance covered while the ramp is still climbing; the 2 is a triangle, not a study
        # parameter (SPEC.md 4.2).
        ramped_kpa = initial * ramp_s + (final - initial) * ramp_s / 2
        return delay_s + ramp_s + max(0.0, range_kpa - ramped_kpa) / final


BUILT = (Responder, RatesZero, RatesMaximum, RatesRandomly, ConfirmsWithoutMoving,
         StopsMidRating, HoldsToMaximum)
