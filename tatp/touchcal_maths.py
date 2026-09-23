"""Protocol B's arithmetic, with no Qt. SPEC.md 9, docs/calibration_methods_comparison.md 7.

Everything with a definite right answer lives here, so that it is tested against known inputs
rather than through a window: where the estimation amplitudes sit, the fit and its inversion,
the stage-1 verdict, the catch-trial flag, the channel gains, the equalisation rule and what
each condition delivers. `tatp/touchcal.py` runs the participant through the steps and calls
these.

**The fit is rating on pressure, then inverted** (SPEC.md 9 step 2). Pressure is the controlled
variable and rating the noisy one, so the regression goes that way round, and a target is read
off by solving the fitted line for pressure -- never by regressing pressure on rating, which
gives different and wrong numbers.

**Ratio-scale settings are averaged geometrically** (docs/research/R31). Pressure is a ratio
scale and the fit is in log pressure, so two method-of-adjustment settings, and the gains they
imply, are combined as a geometric mean: the midpoint on the axis the participant's sensation
is linear in.

No literals (SPEC.md 4.2): every threshold is an argument, and its value is in
`config/study1.yaml`.
"""

from __future__ import annotations

import math
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from tatp.units import DECADE

# The largest power of ten a float holds; beyond it DECADE ** x overflows.
MAX_LOG10 = sys.float_info.max_10_exp

LOG_PRESSURE = "log_pressure"
LINEAR_PRESSURE = "linear_pressure"
FIT_FORMS = (LOG_PRESSURE, LINEAR_PRESSURE)

# The reasons a fit fails stage 1, as written to the log.
FLAT = "flat"
NON_MONOTONIC = "non_monotonic"
POOR_RESIDUALS = "poor_residuals"
# A target the fit cannot deliver: not invertible, not finite, at or below zero, above the
# ceiling, or a pleasantness window left empty once held inside [0, ceiling].
UNREACHABLE = "unreachable"
EMPTY_WINDOW = "empty_window"

# Who won a two-alternative comparison (DATA_SCHEMA.md `touchcal_compare.judgement`).
TEST_STRONGER = "test_stronger"
REFERENCE_STRONGER = "reference_stronger"


# -- the pressure axis -------------------------------------------------------------------


def to_axis(pressures_kpa: Sequence[float], fit_form: str) -> np.ndarray:
    """Pressure on the axis the rating is linear in."""
    p = np.asarray(pressures_kpa, dtype=float)
    if fit_form == LOG_PRESSURE:
        if not np.all(p > 0):
            raise ValueError(f"a log-pressure fit needs positive pressures, got {p.tolist()}")
        return np.log10(p)
    if fit_form == LINEAR_PRESSURE:
        return p
    raise ValueError(f"fit form {fit_form!r} is not one of {FIT_FORMS}")


def from_axis(x: float, fit_form: str) -> float:
    """Back from the fit's axis to pressure. Never raises: a value too large for a float is
    infinite, which `RatingFit.invert` reports as unreachable."""
    if fit_form == LOG_PRESSURE:
        if x > MAX_LOG10:
            return math.inf
        return float(DECADE ** x)
    if fit_form == LINEAR_PRESSURE:
        return float(x)
    raise ValueError(f"fit form {fit_form!r} is not one of {FIT_FORMS}")


def bracket_is_usable(bracket_min_kpa: float, bracket_max_kpa: float, fit_form: str) -> bool:
    """Whether the step 1 adjustments leave anything to sample between them.

    A "just noticeable" setting at zero, or one at or above "just uncomfortable", produces no
    range at all; on a log axis zero is not even a position. That is a stage-1 failure before
    the estimation run begins, not a range to invent.
    """
    if bracket_min_kpa >= bracket_max_kpa:
        return False
    return fit_form != LOG_PRESSURE or bracket_min_kpa > 0


def estimation_amplitudes(
    bracket_min_kpa: float, bracket_max_kpa: float, n: int, fit_form: str
) -> tuple[float, ...]:
    """`n` amplitudes spanning the bracket, both ends included, evenly spaced on the fit's axis.

    Even spacing on the axis the line is fitted on gives every part of it equal leverage
    (docs/research/R32): log-spaced for the log fit, linear for the linear one.
    """
    assert bracket_is_usable(bracket_min_kpa, bracket_max_kpa, fit_form), (
        f"the bracket {bracket_min_kpa}--{bracket_max_kpa} kPa cannot be sampled"
    )
    lo, hi = to_axis([bracket_min_kpa, bracket_max_kpa], fit_form)
    return tuple(from_axis(x, fit_form) for x in np.linspace(lo, hi, n))


@dataclass(frozen=True)
class EstimationPlan:
    """One presentation of the estimation run (DATA_SCHEMA.md `touchcal_estimate`)."""

    presentation_order: int
    # 1..n by pressure for a sampled amplitude; 0 for a catch trial, which is not one of them.
    amplitude_index: int
    pressure_kpa: float
    catch_trial: bool


def catch_trial_count(n_amplitudes: int, catch_trial_fraction: float) -> int:
    """Catch trials ADDED to the amplitudes, not replacing any (docs/research/R32)."""
    return int(round(n_amplitudes * catch_trial_fraction))


def estimation_plans(
    amplitudes_kpa: Sequence[float], n_catch: int, rng: random.Random
) -> tuple[EstimationPlan, ...]:
    """The amplitudes in random order, with catch trials among them.

    Randomised because an ascending series builds in the sequence effect the fit exists to
    average out (SPEC.md 9). A catch trial is never first -- the participant has nothing to
    compare an absent touch with yet -- and never follows another, because two absent touches
    in a row stop being hidden (docs/research/R32).
    """
    assert n_catch <= len(amplitudes_kpa), "more catch trials than places to hide them"
    order = list(enumerate(amplitudes_kpa, start=1))
    rng.shuffle(order)
    # Each catch trial goes after a distinct amplitude, so none is first and no two touch.
    after = set(rng.sample(range(len(order)), n_catch))
    sequence: list[tuple[int, float, bool]] = []
    for position, (index, pressure) in enumerate(order):
        sequence.append((index, pressure, False))
        if position in after:
            sequence.append((0, 0.0, True))
    return tuple(
        EstimationPlan(number, index, pressure, catch)
        for number, (index, pressure, catch) in enumerate(sequence, start=1)
    )


# -- the fit -----------------------------------------------------------------------------


def _average_ranks(values: np.ndarray) -> np.ndarray:
    """Ranks with ties given their mean rank, as Spearman's rho needs."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values))
    ranks[order] = np.arange(len(values), dtype=float)
    for value in np.unique(values):
        tied = values == value
        ranks[tied] = ranks[tied].mean()
    return ranks


def spearman_rho(x: Sequence[float], y: Sequence[float]) -> float:
    """Rank correlation. Zero when either variable does not vary, which has no order at all."""
    rx, ry = _average_ranks(np.asarray(x, float)), _average_ranks(np.asarray(y, float))
    if np.std(rx) == 0 or np.std(ry) == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


@dataclass(frozen=True)
class RatingFit:
    """`rating ~ a + b·x`, x being log10 pressure or pressure. DATA_SCHEMA.md `touchcal_fit`."""

    fit_form: str
    intercept: float
    slope: float
    r_squared: float
    residual_sd: float
    # The fitted rating change across the sampled bracket, in VAS points: slope times the
    # bracket's width on the axis. What "flat" is judged on, because a slope alone means
    # nothing without the range it acts over.
    span_vas: float
    spearman_rho: float
    bracket_min_kpa: float
    bracket_max_kpa: float

    @property
    def monotonic(self) -> bool:
        return self.slope > 0

    def invert(self, rating_percent: float) -> float | None:
        """The pressure the line predicts for `rating_percent`.

        None if the line never rises, or rises so slowly that the pressure is beyond any number
        -- a nearly flat fit. Never raises.
        """
        if not self.monotonic:
            return None
        pressure = from_axis((rating_percent - self.intercept) / self.slope, self.fit_form)
        return pressure if math.isfinite(pressure) else None

    def extrapolated(self, pressure_kpa: float | None) -> bool:
        """Outside the sampled amplitudes, so read off the line beyond its data (SPEC.md 9)."""
        return pressure_kpa is None or not (
            self.bracket_min_kpa <= pressure_kpa <= self.bracket_max_kpa
        )


def fit_ratings(
    pressures_kpa: Sequence[float], ratings: Sequence[float], fit_form: str
) -> RatingFit:
    """Least squares of rating on pressure. Catch trials are the caller's to leave out."""
    x = to_axis(pressures_kpa, fit_form)
    y = np.asarray(ratings, dtype=float)
    # Stage boundary (CLAUDE.md): a residual SD needs two degrees of freedom left over.
    assert len(x) == len(y) and len(x) > 2, "a fit needs at least three presentations"
    assert np.ptp(x) > 0, "a fit needs more than one pressure"
    slope, intercept = np.polyfit(x, y, 1)
    residuals = y - (intercept + slope * x)
    ss_residual = float(np.sum(residuals**2))
    ss_total = float(np.sum((y - y.mean()) ** 2))
    p = np.asarray(pressures_kpa, dtype=float)
    return RatingFit(
        fit_form=fit_form,
        intercept=float(intercept),
        slope=float(slope),
        # Ratings that do not vary explain nothing, so nothing is explained.
        r_squared=1 - ss_residual / ss_total if ss_total > 0 else 0.0,
        residual_sd=float(np.sqrt(ss_residual / (len(x) - 2))),
        span_vas=float(slope * np.ptp(x)),
        spearman_rho=spearman_rho(x, y),
        bracket_min_kpa=float(p.min()),
        bracket_max_kpa=float(p.max()),
    )


@dataclass(frozen=True)
class Stage1Criteria:
    """What makes a fit fail stage 1 (SPEC.md 9). Values from `touch_calibration.stage1`."""

    min_span_vas: float
    min_spearman_rho: float
    max_residual_sd_vas: float

    @classmethod
    def from_config(cls, stage1: Mapping) -> Stage1Criteria:
        return cls(
            min_span_vas=float(stage1["min_span_vas"]),
            min_spearman_rho=float(stage1["min_spearman_rho"]),
            max_residual_sd_vas=float(stage1["max_residual_sd_vas"]),
        )


def stage1_failures(fit: RatingFit, criteria: Stage1Criteria) -> tuple[str, ...]:
    """Why a fit fails stage 1, empty when it passes: flat, non-monotonic, poor residuals."""
    reasons = []
    if not fit.monotonic or fit.spearman_rho < criteria.min_spearman_rho:
        reasons.append(NON_MONOTONIC)
    if fit.span_vas < criteria.min_span_vas:
        reasons.append(FLAT)
    if fit.residual_sd > criteria.max_residual_sd_vas:
        reasons.append(POOR_RESIDUALS)
    return tuple(reasons)


def catch_felt_fraction(catch_ratings: Sequence[float], felt_min_pct: float) -> float | None:
    """Share of catch trials rated at or above the felt threshold. None with no catch trials.

    "Felt" is a rating at or above the scale's own "just noticeable" anchor (docs/research/R32):
    a rating below it says the participant noticed nothing they would call a touch.
    """
    if not catch_ratings:
        return None
    return sum(rating >= felt_min_pct for rating in catch_ratings) / len(catch_ratings)


def line_through_anchors(
    anchors: Sequence[tuple[float, float]], fit_form: str
) -> RatingFit:
    """The line through the step 1 adjustments, (percent, pressure) pairs.

    Used in timing-only mode only (SPEC.md 12.4), when the estimation run on a device that
    cannot set pressure produced no invertible fit: the session still needs pressures to
    command so its steps run for their real durations, and every row they produce is written
    `valid_for_analysis: false`. Never used on a device that can set pressure.
    """
    (low_pct, low_kpa), (high_pct, high_kpa) = anchors[0], anchors[-1]
    x_low, x_high = to_axis([low_kpa, high_kpa], fit_form)
    slope = (high_pct - low_pct) / (x_high - x_low)
    return RatingFit(
        fit_form=fit_form,
        intercept=float(low_pct - slope * x_low),
        slope=float(slope),
        r_squared=0.0,
        residual_sd=0.0,
        span_vas=float(high_pct - low_pct),
        spearman_rho=0.0,
        bracket_min_kpa=float(low_kpa),
        bracket_max_kpa=float(high_kpa),
    )


# -- gains and delivery ------------------------------------------------------------------


def geometric_mean(values: Sequence[float]) -> float:
    v = np.asarray(values, dtype=float)
    assert len(v) and np.all(v > 0), f"a geometric mean needs positive values, got {v.tolist()}"
    return float(np.exp(np.mean(np.log(v))))


def gain(reference_kpa: float, matched_kpa: Sequence[float]) -> float:
    """How much pressure a channel needs to feel like the reference. SPEC.md 9 step 3.

    Scheme B assumes channels differ by a constant multiplicative gain (comparison doc 7.2), so
    one matched level gives the whole anchor set. The two settings from both start points are
    combined geometrically, like any ratio-scale setting.
    """
    assert reference_kpa > 0, "a gain is relative to a reference pressure above zero"
    return geometric_mean(matched_kpa) / reference_kpa


def comparison_winner(judgements: Sequence[str]) -> str | None:
    """The channel judged stronger in every one of `judgements`, else None.

    docs/research/R33: with a forced choice and no "equal", two equal channels plus a
    participant's time-order bias give first/first or second/second -- which a rule on the
    order would read as a difference. So only a channel winning regardless of order counts.
    """
    if judgements and all(j == judgements[0] for j in judgements):
        return judgements[0]
    return None


@dataclass(frozen=True)
class Delivery:
    """What one condition delivers: a pattern, and a pressure for every channel.

    `pressure_kpa` is None in timing-only mode (SPEC.md 12.4), where the device cannot set a
    pressure and the pattern plays at whatever the regulator was set to by hand.
    """

    pattern_name: str
    pressure_kpa: Mapping[int, float] | None


def clamp(value_kpa: float, ceiling_kpa: float) -> float:
    """Inside [0, ceiling], the range the garment can be commanded to (SPEC.md 13)."""
    return min(max(value_kpa, 0.0), ceiling_kpa)


def per_channel(
    level_kpa: float, gains: Mapping[int, float], ceiling_kpa: float
) -> tuple[dict[int, float], tuple[int, ...]]:
    """A reference-scale level on every channel through its gain, held inside [0, ceiling].

    Returns the levels and the channels that had to be clamped, so a clamp is recorded rather
    than hidden. The ceiling is also enforced by the garment (SPEC.md 13); clamping here as
    well means the number recorded as what a condition delivers is the number delivered.
    """
    levels, clamped = {}, []
    for channel, g in sorted(gains.items()):
        wanted = level_kpa * g
        levels[channel] = clamp(wanted, ceiling_kpa)
        if levels[channel] != wanted:
            clamped.append(channel)
    return levels, tuple(clamped)


def usable_targets(
    raw: Mapping[float, float | None],
    sham_pct: float,
    low_pct: float,
    high_pct: float,
    ceiling_kpa: float,
) -> tuple[dict[float, float] | None, tuple[str, ...], tuple[float, ...]]:
    """Whether the fitted targets can be delivered, and at what.

    Returns (the targets held inside [0, ceiling], or None; the reasons they cannot be used;
    the percentages that were clamped). A target that is missing or unreachable, a sham level
    at zero, or a pleasantness window empty once clamped makes the estimate unusable -- a
    stage-1 failure, put to the experimenter (SPEC.md 9).
    """
    if any(value is None for value in raw.values()):
        return None, (UNREACHABLE,), ()
    held = {pct: clamp(value, ceiling_kpa) for pct, value in raw.items()}
    clamped = tuple(pct for pct in sorted(raw) if held[pct] != raw[pct])
    reasons = []
    if held[sham_pct] <= 0:
        reasons.append(UNREACHABLE)
    if held[low_pct] >= held[high_pct]:
        reasons.append(EMPTY_WINDOW)
    return (None if reasons else held), tuple(reasons), clamped
