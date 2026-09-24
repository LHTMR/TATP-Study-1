"""Protocol A -- pinprick and brush. SPEC.md 8.2, 8.3, 10.5, 11, 11.1.

Three layers, each built on the one below.

**The decisions, without Qt.** `LongProtocolState` is the search, the measurement plan and the
fixed-slope estimate of SPEC.md 8.2; `IntolerableCap` is the safety rule; `SiteRotation` names
the next site. They take plain inputs and return plain values, so every rule is tested exactly
and against `docs/calibration_sim.py`, like `AdjustmentState` in `tatp/touchcal.py`. The design
itself is settled in `docs/calibration_methods_comparison.md` section 6 and is not re-derived
here: ascend from an informed prior, 3 adjacent filaments x 3 repetitions in pseudorandom order,
estimate with the slope held fixed.

**One application.** `PinprickTrial` and `BrushTrial` run the visual warning cue, the prompt
telling the experimenter what to apply and where, the rating cue `rating_cue_delay_s` after the
stimulus, and one row. What to apply, where and why is decided by the caller and carried in an
`Application`.

**The protocols.** `LongProtocol`, `ShortProtocol` and `BrushProtocol` are `Procedure`s
(`tatp/procedure.py`): the experimenter launches each, the participant's response advances it,
a jittered interval separates applications, and an interruption repeats the step it abandoned.

**Filaments are named by their gram label** -- `26`, not `5.46` (SPEC.md 8.1). That is what is
printed on the filament and what an experimenter reads off the kit under time pressure, so it
is the identifier here, in `filaments.yaml` and in the data files. The forces are companion
values looked up from it.

**Which force is fitted.** `force_applied_mn` is the force of the filament *actually applied*,
which is not the intended one when the experimenter substitutes (SPEC.md 8.2). It is the weighed
force where there is one and the label force otherwise, so an unweighed set still yields an
estimate -- which piloting needs, since the slope prior is re-estimated from pilot data. Nothing
is hidden by the fallback: `force_measured_mn` is empty on exactly those rows, so a row fitted
on label values is identifiable without reading the session file.

**Discard and repeat** (SPEC.md 11) is accepted in the interval after an application, which is
the only moment "the last trial" is unambiguous. There is an interval after the final
application too, so every trial has the same window. The discarded row stays as written and a
`discards` row points at it; the state rolls back as though the application had not been made,
except in two respects that are deliberate. The application still counts toward
`max_applications`, because the cap bounds what the participant is given, not what is kept. And
a ceiling rating still caps the site, because the participant felt it whatever the delivery.

No literals (SPEC.md 4.2): every interval, force and threshold comes from `config/`.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from tatp.config import Config
from tatp.procedure import Procedure, Rig
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow

# The `vas` block this protocol presents. A config key, not wording.
PAIN_SCALE = "pain"

# Controlled vocabularies of the data files (docs/DATA_SCHEMA.md), not wording.
LONG = "long"
SHORT = "short"
SEARCH = "search"
MEASURE = "measure"
BELOW = "below"
ABOVE = "above"
REGIONS = ("primary", "secondary")
CONFIG_DEFAULT = "config_default"
PREVIOUS_TIMEPOINT = "previous_timepoint"
PINPRICK_TABLE = "pinprick"
BRUSH_TABLE = "brush"

# Which `pinprick` offset shifts the prior into each time point (SPEC.md 8.2). Pre-S of
# session 1 has no previous time point and starts from `start_filament_label_g_session1_pre_s`.
FIRST_SESSION = 1
OFFSET_KEYS = {
    "pre_sensitisation": "expected_offset_steps_between_sessions",
    "post_sensitisation": "expected_offset_steps_pre_to_post_s",
    "post_intervention": "expected_offset_steps_post_s_to_post_i",
}

# The `fit_preview.procedures` entry that names this protocol (SPEC.md 11.1).
FIT_PREVIEW_KEY = "f40"

# The fit is in log10 force (SPEC.md 8.2), so undoing it is a power of ten. Not a parameter.
LOG_BASE = 10.0


# == the decisions, without Qt =================================================================


@dataclass(frozen=True)
class Filament:
    """One held filament, as `filaments.yaml` lists it."""

    label_g: str
    force_nominal_mn: float
    force_measured_mn: float | None

    @property
    def force_mn(self) -> float:
        """What the estimator fits: the weighed force where there is one (SPEC.md 8.1)."""
        if self.force_measured_mn is None:
            return self.force_nominal_mn
        return self.force_measured_mn


def ladder(config: Config) -> tuple[Filament, ...]:
    """Every held filament, lightest first. Whatever is held is the ladder (SPEC.md 8.1)."""
    held = tuple(
        Filament(f["label_g"], float(f["force_nominal_mn"]), f["force_measured_mn"])
        for f in sorted(config.filaments["filaments"], key=lambda f: f["force_nominal_mn"])
    )
    labels = [f.label_g for f in held]
    # Stage boundary (CLAUDE.md): a search steps by index, so two filaments of one force or one
    # label would make "the next filament up" mean nothing.
    assert len(set(labels)) == len(labels), f"filaments.yaml repeats a label: {labels}"
    forces = [f.force_mn for f in held]
    assert all(a < b for a, b in zip(forces, forces[1:], strict=False)), (
        f"filaments.yaml forces do not rise strictly with the ladder: {forces}"
    )
    return held


def ladder_index(filaments: Sequence[Filament], label_g: str) -> int:
    for index, filament in enumerate(filaments):
        if filament.label_g == label_g:
            return index
    raise KeyError(f"filaments.yaml lists no filament labelled {label_g!r} g")


def fixed_slope_f40(
    forces_mn: Sequence[float], ratings: Sequence[float], slope: float, target: float
) -> float:
    """F at which `VAS = m·log10(F) + c` reaches the target, with m held fixed (SPEC.md 8.2).

    With the slope fixed, the least-squares intercept passes through the means, so the solution
    is closed-form -- which is `fit40(..., fixed_slope=m)` in `docs/calibration_sim.py`.
    """
    assert forces_mn and len(forces_mn) == len(ratings), "one rating per force, at least one"
    assert slope > 0, f"the slope prior must be positive, got {slope}"
    mean_log_force = statistics.fmean(math.log10(force) for force in forces_mn)
    return LOG_BASE ** (mean_log_force + (target - statistics.fmean(ratings)) / slope)


def nearest_index(forces_mn: Sequence[float], force_mn: float) -> int:
    """The filament nearest in log force (the ladder is log-spaced); a tie goes lighter."""
    target = math.log10(force_mn)
    return min(range(len(forces_mn)), key=lambda i: abs(math.log10(forces_mn[i]) - target))


def _ranks(values: Sequence[float]) -> list[float]:
    """Ranks from 1, ties sharing their average rank."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    first = 0
    while first < len(order):
        last = first
        while last + 1 < len(order) and values[order[last + 1]] == values[order[first]]:
            last += 1
        for position in range(first, last + 1):
            ranks[order[position]] = (first + last) / 2 + 1
        first = last + 1
    return ranks


def spearman_rho(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation, the ordinal-consistency check (comparison doc 6.7).

    None when either variable does not vary, where a correlation does not exist -- not zero,
    which would read as "inconsistent".
    """
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return statistics.correlation(_ranks(xs), _ranks(ys))


def start_index(
    filaments: Sequence[Filament], previous_f40_mn: float, offset_steps: float
) -> int:
    """The previous estimate's place on the ladder, shifted by a number of ladder steps.

    The place is fractional, interpolated in log force between the two filaments either side,
    so an estimate between two filaments is shifted from where it is rather than from the
    filament it happened to be nearest.
    """
    logs = [math.log10(f.force_mn) for f in filaments]
    x = math.log10(previous_f40_mn)
    if x <= logs[0]:
        position = 0.0
    elif x >= logs[-1]:
        position = float(len(logs) - 1)
    else:
        below = max(i for i, value in enumerate(logs) if value <= x)
        position = below + (x - logs[below]) / (logs[below + 1] - logs[below])
    return min(max(round(position + offset_steps), 0), len(logs) - 1)


@dataclass(frozen=True)
class Prior:
    """Where the search starts, and why. Logged so that bias toward the prior is detectable."""

    start_filament_label_g: str
    source: str


def prior_for(
    config: Config, phase: str, session_number: int, previous_f40_mn: float | None
) -> Prior:
    """The informed prior of SPEC.md 8.2 for this time point.

    `previous_f40_mn` is the previous time point's estimate: this session's pre-S at post-S,
    its post-S at post-I, and the previous session's pre-S at the pre-S of a later session. The
    caller finds it, from the running session or the earlier session's files; it is required
    wherever the spec says the prior is informed, and never quietly replaced by the default.
    """
    pinprick = config.study1["pinprick"]
    if phase == "pre_sensitisation" and session_number == FIRST_SESSION:
        return Prior(pinprick["start_filament_label_g_session1_pre_s"], CONFIG_DEFAULT)
    if phase not in OFFSET_KEYS:
        raise ValueError(f"the long protocol does not run in phase {phase!r}")
    if previous_f40_mn is None:
        raise ValueError(
            f"{phase} in session {session_number} starts from the previous time point's "
            f"estimate (SPEC.md 8.2), and none was given"
        )
    filaments = ladder(config)
    index = start_index(filaments, previous_f40_mn, float(pinprick[OFFSET_KEYS[phase]]))
    return Prior(filaments[index].label_g, PREVIOUS_TIMEPOINT)


@dataclass(frozen=True)
class Planned:
    """What the protocol asks for next: a ladder index and why."""

    index: int
    purpose: str


@dataclass(frozen=True)
class Outcome:
    """One rated application. `applied_index` is what touched the skin, and what is fitted."""

    planned_index: int
    applied_index: int
    rating_percent: float
    purpose: str


@dataclass(frozen=True)
class Estimate:
    f40_mn: float
    chosen_index: int
    out_of_range: str | None
    capped: bool
    n_measure: int
    ordinal_rho: float | None


class LongProtocolState:
    """The search, the measurement plan and the estimate of SPEC.md 8.2. No Qt, no clock.

    **Search.** From the start index, step up after a rating below the target and down after
    one at or above it, until two consecutive applications on adjacent filaments straddle the
    target. The higher of the two is the crossing filament. Steps are taken from the filament
    applied, so a substitution moves the search as well as the fit.

    **Measure.** The crossing filament and the `measure_n_levels - 1` below it,
    `measure_repetitions` times each, shuffled once by `rng`. Near the bottom of the ladder the
    levels are clipped into range exactly as `strat_ascend_local` in `docs/calibration_sim.py`
    clips them, which is what the design was simulated with.

    **Out of range.** The lightest filament rated at or above the target, or the heaviest still
    below it, ends the run on the boundary filament with `out_of_range` set.

    **Trial cap.** `max_applications` counts every application delivered, discarded ones
    included.
    """

    def __init__(
        self,
        n_filaments: int,
        start: int,
        target_pct: float,
        measure_n_levels: int,
        measure_repetitions: int,
        max_applications: int,
        rng: random.Random,
    ):
        assert 0 <= start < n_filaments, f"start {start} is off a {n_filaments}-rung ladder"
        self.n_filaments = n_filaments
        self.start = start
        self.target_pct = target_pct
        self.measure_n_levels = measure_n_levels
        self.measure_repetitions = measure_repetitions
        self.max_applications = max_applications
        self.rng = rng

        self.outcomes: list[Outcome] = []
        self.delivered = 0
        self.crossing: int | None = None
        self.plan: list[int] | None = None
        self.out_of_range: str | None = None

    @property
    def top(self) -> int:
        return self.n_filaments - 1

    @property
    def complete(self) -> bool:
        return self.out_of_range is not None or (self.plan is not None and not self.plan)

    @property
    def capped(self) -> bool:
        return not self.complete and self.delivered >= self.max_applications

    @property
    def finished(self) -> bool:
        return self.complete or self.capped

    @property
    def measuring(self) -> bool:
        return self.plan is not None

    def next(self, ceiling: int | None = None) -> Planned | None:
        """The next application, or None when the run is over.

        `ceiling` is the lightest filament that no site may be given (`IntolerableCap`), if
        there is one. A search step up into it cannot be taken, and brackets the crossing
        instead: the filament there, or one lighter, has already been rated at the top of the
        scale, which is at or above the target by definition.
        """
        if self.finished:
            return None
        if self.plan is not None:
            return Planned(self.plan[0], MEASURE)
        searched = [o for o in self.outcomes if o.purpose == SEARCH]
        if not searched:
            return Planned(self.start, SEARCH)
        last = searched[-1]
        step = 1 if last.rating_percent < self.target_pct else -1
        index = last.applied_index + step
        if step == 1 and ceiling is not None and index >= ceiling:
            self._bracket(index)
            return self.next(ceiling)
        return Planned(index, SEARCH)

    def record(self, outcome: Outcome) -> None:
        assert not self.finished, "an application was recorded after the run ended"
        assert 0 <= outcome.applied_index <= self.top, f"no filament {outcome.applied_index}"
        self.outcomes.append(outcome)
        self.delivered += 1
        if outcome.purpose == MEASURE:
            assert self.plan, "a measurement was recorded with nothing planned"
            self.plan.pop(0)
            return
        at_or_above = outcome.rating_percent >= self.target_pct
        if at_or_above and outcome.applied_index == 0:
            self.out_of_range = BELOW
            return
        if not at_or_above and outcome.applied_index == self.top:
            self.out_of_range = ABOVE
            return
        searched = [o for o in self.outcomes if o.purpose == SEARCH]
        if len(searched) >= 2:
            previous = searched[-2]
            adjacent = abs(previous.applied_index - outcome.applied_index) == 1
            straddle = (previous.rating_percent >= self.target_pct) != at_or_above
            if adjacent and straddle:
                self._bracket(max(previous.applied_index, outcome.applied_index))

    def count_lost_delivery(self) -> None:
        """An application reached the skin but was never rated (an interruption). It counts
        toward `max_applications`, which bounds what the participant is given."""
        self.delivered += 1

    def bar_everything(self) -> None:
        """Not even the lightest filament may be given anywhere: the run ends below range."""
        self.out_of_range = BELOW

    def discard_last(self) -> Outcome:
        """Undo the last application's rating, as though it had not been made (SPEC.md 11)."""
        assert self.outcomes, "there is no application to discard"
        outcome = self.outcomes.pop()
        self.out_of_range = None
        if outcome.purpose == MEASURE:
            assert self.plan is not None
            self.plan.insert(0, outcome.planned_index)
        else:
            # Only the search application that bracketed the crossing can precede a plan, so
            # discarding a search application un-brackets it. A new bracket draws a new order.
            self.plan = None
            self.crossing = None
        return outcome

    def measure_levels(self) -> list[int]:
        assert self.crossing is not None
        low = min(max(self.crossing - (self.measure_n_levels - 1), 0), self.top)
        return [min(max(low + k, 0), self.top) for k in range(self.measure_n_levels)]

    def estimate(self, forces_mn: Sequence[float], slope: float) -> Estimate:
        """F40 from the measurement trials, or the best available when the run was cut short.

        When the trial cap fell before any measurement, every application of the run is
        fitted: they are all that exists, and the flag says so.
        """
        assert self.finished, "the run is not over"
        assert len(forces_mn) == self.n_filaments
        fitted = [o for o in self.outcomes if o.purpose == MEASURE] or self.outcomes
        forces = [forces_mn[o.applied_index] for o in self.outcomes]
        rho = spearman_rho(forces, [o.rating_percent for o in self.outcomes])
        if self.out_of_range is not None:
            boundary = 0 if self.out_of_range == BELOW else self.top
            f40 = forces_mn[boundary]
        else:
            f40 = fixed_slope_f40(
                [forces_mn[o.applied_index] for o in fitted],
                [o.rating_percent for o in fitted],
                slope,
                self.target_pct,
            )
        return Estimate(
            f40_mn=f40,
            chosen_index=nearest_index(forces_mn, f40),
            out_of_range=self.out_of_range,
            capped=self.capped,
            n_measure=sum(o.purpose == MEASURE for o in self.outcomes),
            ordinal_rho=rho,
        )

    def _bracket(self, crossing: int) -> None:
        self.crossing = crossing
        plan = [
            level for level in self.measure_levels() for _ in range(self.measure_repetitions)
        ]
        self.rng.shuffle(plan)
        self.plan = plan


class SiteRotation:
    """Site rotates on every application (SPEC.md 8.2, 8.3). Sites are numbered from 1."""

    def __init__(self, n_sites: int):
        assert n_sites >= 1
        self.n_sites = n_sites
        self.next_site = 1

    def order(self) -> list[int]:
        """Every site, starting with the one due next."""
        return [(self.next_site - 1 + k) % self.n_sites + 1 for k in range(self.n_sites)]

    def take(self, site: int) -> None:
        self.next_site = site % self.n_sites + 1


class IntolerableCap:
    """The safety rule of SPEC.md 8.2: never apply at or above a filament rated intolerable.

    Per site, keyed by region and site, for one time point: whoever runs a time point creates
    one and passes it to every protocol in it, and the next time point gets a fresh one.
    Prospective -- a rating caps what follows it, never itself. Once
    `intolerable_sites_for_global_cap` distinct sites of one region are capped, every site of
    that region is capped at the lowest filament that reached the ceiling in it. Regions are
    kept apart: the primary zone's sensitivity says nothing about the secondary's, and the
    sites of each are a rotation of their own.
    """

    def __init__(self, sites_for_global_cap: int):
        self.sites_for_global_cap = sites_for_global_cap
        self.site_caps: dict[tuple[str, int], int] = {}

    def global_cap(self, region: str) -> int | None:
        caps = [cap for (r, _), cap in self.site_caps.items() if r == region]
        if len(caps) < self.sites_for_global_cap:
            return None
        return min(caps)

    def record(self, region: str, site: int, applied_index: int) -> bool:
        """A ceiling rating at this site. Returns whether it switched the region's cap on."""
        was_global = self.global_cap(region) is not None
        key = (region, site)
        self.site_caps[key] = min(self.site_caps.get(key, applied_index), applied_index)
        return not was_global and self.global_cap(region) is not None

    def cap_for(self, region: str, site: int) -> int | None:
        candidates = (self.site_caps.get((region, site)), self.global_cap(region))
        caps = [c for c in candidates if c is not None]
        return min(caps) if caps else None

    def allows(self, region: str, site: int, index: int) -> bool:
        cap = self.cap_for(region, site)
        return cap is None or index < cap

    def ceiling(self, region: str, n_sites: int) -> int | None:
        """The lightest filament no site in this region may be given; None if there is none."""
        caps = [self.cap_for(region, site) for site in range(1, n_sites + 1)]
        if any(cap is None for cap in caps):
            return None
        return max(caps)


def jittered_isi_s(rng: random.Random, isi_min_s: float, isi_max_s: float) -> float:
    """The interval after an application: uniform over the configured range (SPEC.md 8.3)."""
    seconds = rng.uniform(isi_min_s, isi_max_s)
    assert isi_min_s <= seconds <= isi_max_s
    return seconds


def place(
    cap: IntolerableCap, rotation: SiteRotation, region: str, index: int
) -> tuple[int, int] | None:
    """Where the next application goes: the filament, lowered if the cap bars it everywhere,
    and the first site in rotation order that allows it. None if nothing is allowed at all."""
    ceiling = cap.ceiling(region, rotation.n_sites)
    if ceiling is not None and index >= ceiling:
        index = ceiling - 1
    if index < 0:
        return None
    for site in rotation.order():
        if cap.allows(region, site, index):
            return index, site
    raise AssertionError("a filament below the ceiling must be allowed at some site")


# == one application ==========================================================================


@dataclass(frozen=True)
class Application:
    """One planned application. Everything the protocol decides; the trial only carries it."""

    protocol: str
    region: str
    trial_index: int
    purpose: str
    filament_label_g: str
    site_index: int
    # Empty means the filament asked for is the one applied. The safety rule of SPEC.md 8.2
    # lets the experimenter substitute a lower filament, and the estimator must then fit the
    # applied value -- so which one was applied is recorded, never assumed.
    applied_filament_label_g: str = ""
    # SPEC.md 11.1: 1 unless the long protocol was re-run from the fit preview.
    run_index: int = 1

    @property
    def applied_label_g(self) -> str:
        """The gram label that actually touched the skin."""
        return self.applied_filament_label_g or self.filament_label_g


@dataclass(frozen=True)
class BrushApplication:
    region: str
    trial_index: int
    site_index: int


class _RatedTrial(QObject):
    """Cue, stimulus, rating cue, rating, one row. The sequence both stimuli share (10.5).

    A trial in the sense of `tatp/procedure.py`: an interruption is handled by whatever runs
    it, which calls `cancel()`.
    """

    finished = Signal(object)

    def __init__(
        self,
        session: Session,
        participant: ParticipantWindow,
        experimenter: ExperimenterWindow,
        trial_index: int,
        rating_cue_delay_s: float,
        scale: str,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.session = session
        self.participant = participant
        self.experimenter = experimenter
        self.trial_index = trial_index
        self.rating_cue_delay_s = rating_cue_delay_s
        self.scale = scale

        cues = session.config.study1["cues"]
        self.warning_lead_s = float(cues["warning_lead_s"])
        self.warning_duration_s = float(cues["warning_duration_s"])
        # Stage boundary (CLAUDE.md): the cue precedes the stimulus, so the lead cannot be
        # shorter than the cue itself. Config that says otherwise is a mistake, not a schedule.
        assert self.warning_lead_s >= self.warning_duration_s, (
            f"study1.yaml: cues.warning_lead_s ({self.warning_lead_s} s) is shorter than "
            f"cues.warning_duration_s ({self.warning_duration_s} s)"
        )

        self.cue_onset_iso = ""
        self.rating_cue_iso = ""
        # From `stimulus_due` on, the experimenter has applied the stimulus: an interruption
        # after it has cost the participant a delivery even though no row is written.
        self.stimulus_delivered = False
        self._cue_onset_t_session_s: float | None = None
        self._pending = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        # Precise: a coarse timer on Windows fires on the 15.6 ms system tick, which at the
        # validator's accelerated clock is a large part of the 0.5 s it must be able to time.
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._fire)

    # -- hooks -------------------------------------------------------------------------

    def _instruction(self) -> str:
        raise NotImplementedError

    def _stimulus_detail(self) -> str:
        raise NotImplementedError

    def _write(self, response) -> None:
        raise NotImplementedError

    def _connect_extra(self) -> None:
        """Signals this kind of trial listens to while it runs, besides the rating."""

    def _disconnect_extra(self) -> None:
        pass

    def _rated(self, response) -> None:
        """After the row is written, before `finished`."""

    # -- the sequence ------------------------------------------------------------------

    def start(self) -> None:
        """Show the warning cue and prompt the experimenter. SPEC.md 10.5."""
        # Everything that can fail happens before anything is shown or connected, so a trial
        # naming a filament that is not held stops here rather than half-started.
        instruction = self._instruction()
        self.participant.confirmed.connect(self._on_confirmed)
        self._connect_extra()

        clock = self.session.clock
        self.cue_onset_iso = clock.wall_iso()
        self._cue_onset_t_session_s = clock.t_session_s()
        self.participant.show_warning_cue()
        self.session.log("warning_cue", detail=f"trial {self.trial_index}")

        self.experimenter.set_instruction(instruction)
        # The zone diagram marks where this stimulus goes (SPEC.md 11), and a filament brings
        # the monofilament technique with it.
        self.experimenter.set_target(
            self.application.region,
            self.application.site_index,
            filament=isinstance(self.application, Application),
        )
        self.experimenter.set_status("")
        self.experimenter.refresh()
        self._after(self.warning_duration_s, self._end_cue)

    def _end_cue(self) -> None:
        self.participant.show_blank()
        self._after(self.warning_lead_s - self.warning_duration_s, self._stimulus_due)

    def _stimulus_due(self) -> None:
        self.stimulus_delivered = True
        self.session.log("stimulus_due", detail=self._stimulus_detail())
        self._after(self.rating_cue_delay_s, self._cue_rating)

    def _cue_rating(self) -> None:
        self.rating_cue_iso = self.session.clock.wall_iso()
        self.participant.show_vas(self.scale)
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["await_participant"]
        )
        self.experimenter.refresh()
        self.session.log("rating_cued", detail=self.scale)

    # -- the end of the trial -----------------------------------------------------------

    def _on_confirmed(self, response) -> None:
        self._disconnect()
        self._write(response)
        self.session.log(
            "rating_confirmed",
            origin="participant",
            detail=f"rt {response.rt_s:.3f} s, first press {response.first_press_side}",
        )
        self._rated(response)
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["response_received"]
        )
        self.experimenter.refresh()
        self.participant.show_blank()
        self.finished.emit(response)

    def cancel(self) -> None:
        """Abandoned by an interruption (SPEC.md 13). No rating was given, so no row is written.

        The stop itself -- the garment, the log, the screen -- is `tatp/interruption.py`'s.
        What is recorded here is which trial was lost, so the repeat is traceable to it.
        """
        self._disconnect()
        self.session.log("trial_cancelled", detail=f"trial {self.trial_index}")

    # -- plumbing ----------------------------------------------------------------------

    def _after(self, seconds: float, method) -> None:
        self._pending = method
        self._timer.start(self.session.clock.scaled_ms(seconds))

    def _fire(self) -> None:
        method, self._pending = self._pending, None
        method()

    def _disconnect(self) -> None:
        self._timer.stop()
        self._pending = None
        self.participant.confirmed.disconnect(self._on_confirmed)
        self._disconnect_extra()


class PinprickTrial(_RatedTrial):
    """One monofilament application. `finished` carries the rating."""

    def __init__(
        self,
        session: Session,
        participant: ParticipantWindow,
        experimenter: ExperimenterWindow,
        application: Application,
        parent: QObject | None = None,
    ):
        pinprick = session.config.study1["pinprick"]
        super().__init__(
            session,
            participant,
            experimenter,
            application.trial_index,
            float(pinprick["rating_cue_delay_s"]),
            PAIN_SCALE,
            parent,
        )
        self.application = application
        self.intolerable_vas_pct = float(pinprick["intolerable_vas_pct"])
        self.filaments = ladder(session.config)
        # Changed by the experimenter's substitution while the trial runs (SPEC.md 8.2).
        self.applied_label_g = application.applied_label_g

    def _filament(self, label_g: str) -> Filament:
        return self.filaments[ladder_index(self.filaments, label_g)]

    def _instruction(self) -> str:
        text = self.experimenter.text
        self._filament(self.application.applied_label_g)  # refuses one not held, before the cue
        return text["instructions"]["apply_filament"].format(
            filament=self.application.filament_label_g,
            force_mn=self._filament(self.application.filament_label_g).force_nominal_mn,
            site=self.application.site_index,
            region=text["terms"]["regions"][self.application.region],
        )

    def _stimulus_detail(self) -> str:
        return f"filament {self.application.filament_label_g} g"

    def _connect_extra(self) -> None:
        self.experimenter.substitution_entered.connect(self._on_substitution)

    def _disconnect_extra(self) -> None:
        self.experimenter.substitution_entered.disconnect(self._on_substitution)

    def _on_substitution(self, label_g: str) -> None:
        """The experimenter applied another filament than the one asked for (SPEC.md 8.2).

        Recorded as applied, because the row must describe what touched the skin. An unknown
        label cannot be recorded -- there is no force to fit -- so it is refused and said so.
        One that is not lower than asked for is recorded too, since it was applied, but warned:
        the spec's substitution is a lowering, and anything else is probably a slip.
        """
        warnings = self.experimenter.text["warnings"]
        if label_g not in {f.label_g for f in self.filaments}:
            self.session.log(
                "substitution_unknown", origin="experimenter", severity="warning",
                detail=f"{label_g} g",
            )
            self.experimenter.set_status(warnings["substitution_unknown"].format(filament=label_g))
            self.experimenter.refresh()
            return
        self.applied_label_g = label_g
        asked = self._filament(self.application.filament_label_g).force_nominal_mn
        lower = self._filament(label_g).force_nominal_mn < asked
        self.session.log(
            "substitution_entered",
            origin="experimenter",
            severity="info" if lower else "warning",
            detail=f"asked {self.application.filament_label_g} g, applied {label_g} g",
        )
        if not lower:
            self.experimenter.set_status(
                warnings["substitution_not_lower"].format(filament=label_g)
            )
            self.experimenter.refresh()

    def _rated(self, response) -> None:
        if response.rating_percent >= self.intolerable_vas_pct:
            # SPEC.md 8.2. Logged as well as flagged in the row, so the cap that constrains the
            # following applications is visible in the event stream rather than only derivable.
            self.session.log(
                "intolerable_rating",
                origin="participant",
                severity="warning",
                detail=f"site {self.application.site_index}, {self.applied_label_g} g",
            )

    def _write(self, response) -> None:
        application = self.application
        applied_label = self.applied_label_g
        # Every force column describes the filament that actually touched the skin, so the three
        # of them stay consistent about one object. Which filament was asked for is in
        # `filament_label_g`, and its own forces are a lookup away in filaments.yaml.
        applied = self._filament(applied_label)
        nominal_mn = applied.force_nominal_mn
        measured_mn = applied.force_measured_mn
        self.session.files.write(
            PINPRICK_TABLE,
            timestamp_iso=self.cue_onset_iso,
            t_session_s=self._cue_onset_t_session_s,
            phase=self.session.phase,
            block_index=self.session.block_index,
            protocol=application.protocol,
            region=application.region,
            trial_index=application.trial_index,
            run_index=application.run_index,
            purpose=application.purpose,
            filament_label_g=application.filament_label_g,
            applied_filament_label_g=applied_label,
            force_nominal_mn=nominal_mn,
            force_measured_mn=measured_mn,
            force_applied_mn=applied.force_mn,
            substituted=applied_label != application.filament_label_g,
            site_index=application.site_index,
            cue_onset_iso=self.cue_onset_iso,
            rating_cue_iso=self.rating_cue_iso,
            rating_percent=response.rating_percent,
            rt_s=response.rt_s,
            first_press_side=response.first_press_side,
            direction_changes=response.direction_changes,
            # SPEC.md 8.2: a rating at the top of the scale is the proxy for intolerable. The
            # flag is prospective -- it caps the applications after this one, not this one.
            intolerable=response.rating_percent >= self.intolerable_vas_pct,
        )


class BrushTrial(_RatedTrial):
    """One brush stroke (SPEC.md 8.3): the pinprick sequence with a brush and its own table."""

    def __init__(
        self,
        session: Session,
        participant: ParticipantWindow,
        experimenter: ExperimenterWindow,
        application: BrushApplication,
        parent: QObject | None = None,
    ):
        brush = session.config.study1["brush"]
        super().__init__(
            session,
            participant,
            experimenter,
            application.trial_index,
            float(brush["rating_cue_delay_s"]),
            brush["rating_scale"],
            parent,
        )
        self.application = application

    def _instruction(self) -> str:
        text = self.experimenter.text
        return text["instructions"]["apply_brush"].format(
            site=self.application.site_index,
            region=text["terms"]["regions"][self.application.region],
        )

    def _stimulus_detail(self) -> str:
        return "brush"

    def _write(self, response) -> None:
        self.session.files.write(
            BRUSH_TABLE,
            timestamp_iso=self.cue_onset_iso,
            t_session_s=self._cue_onset_t_session_s,
            phase=self.session.phase,
            region=self.application.region,
            trial_index=self.application.trial_index,
            site_index=self.application.site_index,
            cue_onset_iso=self.cue_onset_iso,
            rating_cue_iso=self.rating_cue_iso,
            rating_percent=response.rating_percent,
            rt_s=response.rt_s,
            first_press_side=response.first_press_side,
            direction_changes=response.direction_changes,
        )


# == the protocols ============================================================================


class _Series(Procedure):
    """What the three rated protocols share: the experimenter's launch, the jittered interval
    and discard-and-repeat (SPEC.md 8.3, 11).

    Subclasses implement `begin`, `_next` (the next application or the end), `_rollback`
    (undo the last application's rating, returning whether a repeat will follow) and
    `_count_lost_delivery` (an application delivered but never rated).

    **An interruption during an application** (SPEC.md 13) loses the trial and writes no row.
    Before the stimulus was due, nothing reached the skin, and the same application is
    repeated at the same site. From then on it had, so the delivery is counted and the repeat
    goes to the next site in rotation, like any other application after one delivered there.
    """

    def __init__(self, rig: Rig, isi_min_s: float, isi_max_s: float):
        super().__init__(rig)
        assert 0 < isi_min_s <= isi_max_s, f"ISI {isi_min_s}..{isi_max_s} s is not a range"
        self.isi_min_s = isi_min_s
        self.isi_max_s = isi_max_s
        self.applications = 0
        # (table, the row's timestamp_iso, its trial_index) while a discard is accepted.
        self._discardable: tuple[str, str, int] | None = None

    def connect_actions(self) -> None:
        self.experimenter.discard_requested.connect(self._on_discard)

    def disconnect_actions(self) -> None:
        self.experimenter.discard_requested.disconnect(self._on_discard)

    def wait_to_start(self, then: Callable[[], None]) -> None:
        """The experimenter confirms the start of the block (SPEC.md 8.3)."""

        def prepare() -> None:
            self.participant.show_blank()
            self.experimenter.set_instruction(self.experimenter.text["instructions"]["ready"])
            self.experimenter.refresh()

        self.await_proceed(then, prepare)

    # -- interruptions ------------------------------------------------------------------

    def on_interrupted(self, kind: str) -> None:
        trial = self._trial
        super().on_interrupted(kind)
        if trial is None:
            return
        if trial.stimulus_delivered:
            self._count_lost_delivery()
            self.session.log(
                "trial_lost_after_delivery", severity="warning",
                detail=f"trial {trial.trial_index}; counted, repeated at the next site",
            )
            # The resume plans afresh: the rotation has already moved past this site.
            self._step = self._advance
        else:
            self.session.log(
                "trial_lost_before_delivery",
                detail=f"trial {trial.trial_index}; repeated as planned",
            )

    def _count_lost_delivery(self) -> None:
        raise NotImplementedError

    # -- applications and the interval between them --------------------------------------

    def apply(self, make_trial: Callable[[], _RatedTrial], on_rated) -> None:
        """Run one application; `on_rated(trial, response)` receives it."""
        self._discardable = None
        self.applications += 1
        made: list[_RatedTrial] = []

        def make() -> _RatedTrial:
            made[:] = [make_trial()]
            return made[0]

        self.run_trial(make, lambda response: on_rated(made[0], response))

    def interval(self, table: str, trial: _RatedTrial) -> None:
        """The jittered wait after an application, during which it may be discarded."""
        self._discardable = (table, trial.cue_onset_iso, trial.trial_index)
        self._wait_then_next()

    def _wait_then_next(self) -> None:
        seconds = jittered_isi_s(self.session.rng, self.isi_min_s, self.isi_max_s)
        self.session.log("interval", detail=f"{seconds:.2f} s")

        def begin() -> None:
            # Also what a resume lands on, so the stop screen does not outlast the stop.
            self.participant.show_blank()
            self._after(seconds, self._advance)

        self.step(begin)

    def _advance(self) -> None:
        self._discardable = None
        self._next()

    def _next(self) -> None:
        raise NotImplementedError

    def _rollback(self) -> bool:
        raise NotImplementedError

    # -- discard and repeat (SPEC.md 11) ------------------------------------------------

    def _on_discard(self) -> None:
        if self._discardable is None or self.rig.interruptions.active is not None:
            self.session.log(
                "discard_ignored",
                origin="experimenter",
                severity="warning",
                detail="no completed application is waiting to be discarded",
            )
            return
        table, trial_timestamp_iso, trial_index = self._discardable
        self._discardable = None
        clock = self.session.clock
        self.session.files.write(
            "discards",
            timestamp_iso=clock.wall_iso(),
            t_session_s=clock.t_session_s(),
            phase=self.session.phase,
            block_index=self.session.block_index,
            table=table,
            trial_timestamp_iso=trial_timestamp_iso,
            trial_index=trial_index,
        )
        self.session.log(
            "trial_discarded", origin="experimenter", detail=f"{table} trial {trial_index}"
        )
        # The discard is recorded either way -- the trial was delivered badly whatever follows.
        # At the application cap no repeat can follow, and the status says so.
        repeats = self._rollback()
        status = "discarded" if repeats else "discarded_not_repeated"
        self.experimenter.set_status(self.experimenter.text["status"][status])
        self.experimenter.refresh()
        # The interval restarts in full, so the repeat is as far from the discarded
        # application as any application is from the one before it.
        self._wait_then_next()


@dataclass(frozen=True)
class LongResult:
    """A completed long protocol, as later phases need it. The record is in the data files."""

    phase: str
    region: str
    run_index: int
    start_filament_label_g: str
    start_source: str
    f40_mn: float
    chosen_filament_label_g: str
    chosen_force_mn: float
    out_of_range: bool
    out_of_range_direction: str
    capped: bool
    applications_total: int
    applications_measure: int
    ordinal_rho: float | None


@dataclass(frozen=True)
class F40Fit:
    """What the fit preview shows (SPEC.md 11.1): the estimate and the points it came from."""

    result: LongResult
    slope_vas_per_log10: float
    target_vas_pct: float
    points: tuple[tuple[float, float], ...]  # (force_applied_mn, rating_percent), measured


class LongProtocol(_Series):
    """The 40 % VAS force (SPEC.md 8.2). `finished` carries a `LongResult`.

    `prior` is where the search starts (`prior_for`). `cap` is the time point's
    `IntolerableCap`, shared with every pinprick protocol at the same time point. It is
    required: the cap's scope is the time point (SPEC.md 8.2), which only the caller knows.

    With the fit preview on (SPEC.md 11.1) the run ends by emitting `fit_ready` with an
    `F40Fit` and waiting for `fit_accepted` or `fit_rerun_requested`. A re-run keeps the
    discarded run's `calibration_pinprick` row with `superseded` true and starts again with
    `run_index` incremented, at most `fit_preview.max_reruns` times.
    """

    fit_ready = Signal(object)

    def __init__(
        self,
        rig: Rig,
        region: str,
        prior: Prior,
        cap: IntolerableCap,
    ):
        assert isinstance(cap, IntolerableCap), "the time point's IntolerableCap is required"
        pinprick = rig.session.config.study1["pinprick"]
        super().__init__(rig, float(pinprick["isi_min_s"]), float(pinprick["isi_max_s"]))
        assert region in REGIONS, f"region {region!r} is not one of {REGIONS}"
        assert prior.source in (CONFIG_DEFAULT, PREVIOUS_TIMEPOINT), prior.source
        self.region = region
        self.prior = prior
        self.pinprick = pinprick
        self.cap = cap
        self.filaments = ladder(self.session.config)
        self.forces_mn = [f.force_mn for f in self.filaments]
        self.start_index = ladder_index(self.filaments, prior.start_filament_label_g)
        self.rotation = SiteRotation(int(pinprick["n_sites"]))
        self.slope = float(pinprick["slope_prior_vas_per_log10"])
        self.target = float(pinprick["target_vas_pct"])
        self.intolerable_vas_pct = float(pinprick["intolerable_vas_pct"])

        fit_preview = self.session.config.study1["fit_preview"]
        self.preview = bool(fit_preview["enabled"]) and FIT_PREVIEW_KEY in fit_preview[
            "procedures"
        ]
        self.max_reruns = int(fit_preview["max_reruns"])
        self.run_index = 1
        self.state: LongProtocolState | None = None
        self._awaiting_fit: LongResult | None = None
        self._last: tuple[Planned, int] | None = None  # the planned application and its site
        self._logged_plan: list[int] | None = None

    def connect_actions(self) -> None:
        super().connect_actions()
        self.experimenter.fit_accepted.connect(self._on_fit_accepted)
        self.experimenter.fit_rerun_requested.connect(self._on_fit_rerun)

    def disconnect_actions(self) -> None:
        super().disconnect_actions()
        self.experimenter.fit_accepted.disconnect(self._on_fit_accepted)
        self.experimenter.fit_rerun_requested.disconnect(self._on_fit_rerun)

    # -- the run -----------------------------------------------------------------------

    def begin(self) -> None:
        pinprick = self.pinprick
        self.applications = 0
        self.state = LongProtocolState(
            n_filaments=len(self.filaments),
            start=self.start_index,
            target_pct=self.target,
            measure_n_levels=int(pinprick["measure_n_levels"]),
            measure_repetitions=int(pinprick["measure_repetitions"]),
            max_applications=int(pinprick["max_applications"]),
            rng=self.session.rng,
        )
        # SPEC.md 8.2: log the start filament, so bias toward the prior is detectable.
        self.session.log(
            "long_protocol_started",
            detail=f"{self.region}, run {self.run_index}, start "
            f"{self.prior.start_filament_label_g} g ({self.prior.source})",
        )
        self.wait_to_start(self._next)

    def _next(self) -> None:
        state = self.state
        ceiling = self.cap.ceiling(self.region, self.rotation.n_sites)
        if ceiling == 0 and not state.finished:
            self.session.log("cap_bars_every_filament", severity="warning", detail=self.region)
            state.bar_everything()
        planned = state.next(ceiling)
        if planned is None:
            self._conclude()
            return
        if state.measuring and state.plan is not self._logged_plan:
            # Identity, not equality: a re-bracket after a discard draws a new list.
            self._logged_plan = state.plan
            order = ", ".join(self.filaments[i].label_g for i in state.plan)
            # The order is a draw from the session RNG; logging it makes the draw auditable
            # without replaying the seed (SPEC.md 8.2).
            self.session.log(
                "measure_plan",
                detail=f"crossing {self.filaments[state.crossing].label_g} g; order {order}",
            )
        placed = place(self.cap, self.rotation, self.region, planned.index)
        assert placed is not None, "a ceiling of zero ends the run before placing"
        index, site = placed
        if index != planned.index:
            self.session.log(
                "cap_lowered",
                severity="warning",
                detail=f"asked {self.filaments[planned.index].label_g} g, capped at every "
                f"site; {self.filaments[index].label_g} g instead",
            )
        self.rotation.take(site)
        self._last = (planned, site)
        application = Application(
            protocol=LONG,
            region=self.region,
            trial_index=self.applications + 1,
            purpose=planned.purpose,
            filament_label_g=self.filaments[index].label_g,
            site_index=site,
            run_index=self.run_index,
        )
        self.apply(
            lambda: PinprickTrial(
                self.session, self.participant, self.experimenter, application
            ),
            self._rated,
        )

    def _rated(self, trial: PinprickTrial, response) -> None:
        planned, site = self._last
        applied = ladder_index(self.filaments, trial.applied_label_g)
        rating = response.rating_percent
        self.state.record(Outcome(planned.index, applied, rating, planned.purpose))
        _record_ceiling(self, trial, response, applied, site)
        self.interval(PINPRICK_TABLE, trial)

    def _rollback(self) -> bool:
        self.state.discard_last()
        return not self.state.finished

    def _count_lost_delivery(self) -> None:
        self.state.count_lost_delivery()

    # -- the end of a run ---------------------------------------------------------------

    def _conclude(self) -> None:
        state = self.state
        estimate = state.estimate(self.forces_mn, self.slope)
        chosen = self.filaments[estimate.chosen_index]
        result = LongResult(
            phase=self.session.phase,
            region=self.region,
            run_index=self.run_index,
            start_filament_label_g=self.prior.start_filament_label_g,
            start_source=self.prior.source,
            f40_mn=estimate.f40_mn,
            chosen_filament_label_g=chosen.label_g,
            chosen_force_mn=chosen.force_mn,
            out_of_range=estimate.out_of_range is not None,
            out_of_range_direction=estimate.out_of_range or "",
            capped=estimate.capped,
            applications_total=state.delivered,
            applications_measure=estimate.n_measure,
            ordinal_rho=estimate.ordinal_rho,
        )
        self._warn(result)
        if not self.preview:
            self._record(result, superseded=False, rerun_reason="")
            self.finish(result)
            return
        points = tuple(
            (self.forces_mn[o.applied_index], o.rating_percent)
            for o in state.outcomes
            if o.purpose == MEASURE
        )
        fit = F40Fit(result, self.slope, self.target, points)

        def begin() -> None:
            self.participant.show_blank()
            self._awaiting_fit = result
            # Accept and Re-run are live exactly while this waits on them (SPEC.md 11.1).
            self.experimenter.set_actions_enabled(fit_decision=True)
            self.fit_ready.emit(fit)

        self.step(begin)

    def _warn(self, result: LongResult) -> None:
        text = self.experimenter.text
        warnings = []
        if result.out_of_range:
            direction = text["terms"]["out_of_range"][result.out_of_range_direction]
            warnings.append(text["warnings"]["out_of_range"].format(value=direction))
            self.session.log(
                "out_of_range", severity="warning",
                detail=f"{result.out_of_range_direction}; boundary "
                f"{result.chosen_filament_label_g} g",
            )
        if result.capped:
            warnings.append(
                text["warnings"]["application_cap"].format(value=self.state.max_applications)
            )
            self.session.log(
                "application_cap_reached", severity="warning",
                detail=f"{result.applications_total} applications; best available estimate",
            )
        rho_min = float(self.pinprick["ordinal_rho_min"])
        # A consistency check only, never a gate (comparison doc 6.7). Logged, not shown: the
        # correlation is computed from ratings, which the lab screen never carries.
        if result.ordinal_rho is None:
            # No variation in force or in rating -- not a low correlation, no correlation.
            self.session.log("ordinal_consistency_undefined", detail="rho has no value")
        elif result.ordinal_rho < rho_min:
            self.session.log(
                "ordinal_consistency_low", severity="warning",
                detail=f"rho {result.ordinal_rho}, threshold {rho_min}",
            )
        self.experimenter.set_status(" ".join(warnings))
        self.experimenter.refresh()

    def _record(self, result: LongResult, superseded: bool, rerun_reason: str) -> None:
        clock = self.session.clock
        self.session.files.write(
            "calibration_pinprick",
            timestamp_iso=clock.wall_iso(),
            t_session_s=clock.t_session_s(),
            phase=result.phase,
            region=result.region,
            run_index=result.run_index,
            superseded=superseded,
            rerun_reason=rerun_reason,
            start_filament_label_g=result.start_filament_label_g,
            start_source=result.start_source,
            applications_total=result.applications_total,
            applications_measure=result.applications_measure,
            capped=result.capped,
            slope_prior_vas_per_log10=self.slope,
            f40_mn=result.f40_mn,
            chosen_filament_label_g=result.chosen_filament_label_g,
            chosen_force_mn=result.chosen_force_mn,
            out_of_range=result.out_of_range,
            out_of_range_direction=result.out_of_range_direction,
            ordinal_rho=result.ordinal_rho,
        )
        self.session.log(
            "f40_estimated",
            detail=f"run {result.run_index}, {result.f40_mn:.1f} mN, "
            f"{result.chosen_filament_label_g} g" + (", superseded" if superseded else ""),
        )

    # -- the fit preview (SPEC.md 11.1) -------------------------------------------------

    def _on_fit_accepted(self) -> None:
        result = self._awaiting_fit
        if result is None or self.rig.interruptions.active is not None:
            return
        self._awaiting_fit = None
        # The decision is taken: the preview closes and its buttons go dead.
        self.experimenter.hide_fit_preview()
        self.session.log("fit_accepted", origin="experimenter", detail=f"run {self.run_index}")
        self._record(result, superseded=False, rerun_reason="")
        self.finish(result)

    def _on_fit_rerun(self, reason: str) -> None:
        result = self._awaiting_fit
        if result is None or self.rig.interruptions.active is not None:
            return
        self._awaiting_fit = None
        self.experimenter.hide_fit_preview()
        if self.run_index - 1 >= self.max_reruns:
            # The bound on the forking path: this estimate is the one used (SPEC.md 11.1).
            self.session.log(
                "fit_rerun_refused", origin="experimenter", severity="warning",
                detail=f"run {self.run_index}; limit {self.max_reruns}. {reason}",
            )
            self.experimenter.set_status(self.experimenter.text["dialogs"]["fit_rerun_exhausted"])
            self.experimenter.refresh()
            self._record(result, superseded=False, rerun_reason="")
            self.finish(result)
            return
        self._record(result, superseded=True, rerun_reason=reason)
        self.session.fit_preview_reruns += 1
        self.session.log(
            "fit_rerun", origin="experimenter", severity="warning",
            detail=f"run {self.run_index} superseded: {reason}",
        )
        self.run_index += 1
        self.begin()


def _record_ceiling(protocol, trial: PinprickTrial, response, applied: int, site: int) -> None:
    """Feed a ceiling rating to the cap, and log what it now bars.

    Logged only, never shown. With the ceiling at the top of the scale, "site N is capped"
    would tell the experimenter the participant rated 100 there, and the lab screen never
    carries a rating (SPEC.md 11). The software enforces the cap itself (docs/LOG.md N7.B11).
    """
    if response.rating_percent < protocol.intolerable_vas_pct:
        return
    went_global = protocol.cap.record(protocol.region, site, applied)
    label = protocol.filaments[protocol.cap.cap_for(protocol.region, site)].label_g
    protocol.session.log(
        "intolerable_site_cap", severity="warning", detail=f"site {site}, {label} g"
    )
    if went_global:
        lowest = protocol.filaments[protocol.cap.global_cap(protocol.region)].label_g
        protocol.session.log(
            "intolerable_global_cap", severity="warning",
            detail=f"{protocol.region}, every site at {lowest} g",
        )


@dataclass(frozen=True)
class RatingSeriesResult:
    """A completed short or brush protocol: the median, and the ratings it came from."""

    region: str
    stimulus: str  # the filament's gram label, or `brush`
    # None only when the intolerable cap barred every filament before any rating was taken.
    median_rating_percent: float | None
    ratings_percent: tuple[float, ...]


class _RatingSeries(_Series):
    """N ratings at a fixed stimulus, median taken (SPEC.md 8.3).

    The experimenter confirms the start of the block, which triggers the first warning cue;
    from then the participant's response advances to the next application after a jittered
    interval, and the site rotates on every application.
    """

    TABLE = ""

    def __init__(self, rig: Rig, region: str, n_trials: int, n_sites: int, isi: tuple):
        super().__init__(rig, *isi)
        assert region in REGIONS, f"region {region!r} is not one of {REGIONS}"
        self.region = region
        self.n_trials = n_trials
        self.rotation = SiteRotation(n_sites)
        self.ratings: list[float] = []

    def begin(self) -> None:
        self.session.log("series_started", detail=f"{type(self).__name__}, {self.region}")
        self.wait_to_start(self._next)

    def _next(self) -> None:
        if len(self.ratings) == self.n_trials:
            self.finish(
                RatingSeriesResult(
                    region=self.region,
                    stimulus=self._stimulus(),
                    median_rating_percent=(
                        statistics.median(self.ratings) if self.ratings else None
                    ),
                    ratings_percent=tuple(self.ratings),
                )
            )
            return
        self._apply_next()

    def _on_rated(self, trial: _RatedTrial, response) -> None:
        self.ratings.append(response.rating_percent)
        self.interval(self.TABLE, trial)

    def _rollback(self) -> bool:
        self.ratings.pop()
        return True  # a fixed number of ratings, and no application cap

    def _count_lost_delivery(self) -> None:
        pass  # the series counts ratings, not deliveries; the log records the loss

    def _stimulus(self) -> str:
        raise NotImplementedError

    def _apply_next(self) -> None:
        raise NotImplementedError


class ShortProtocol(_RatingSeries):
    """Median pinprick pain at a fixed filament (SPEC.md 8.3). `finished` carries a
    `RatingSeriesResult`. `cap` is the time point's `IntolerableCap`, as for `LongProtocol`."""

    TABLE = PINPRICK_TABLE

    def __init__(
        self,
        rig: Rig,
        region: str,
        filament_label_g: str,
        cap: IntolerableCap,
    ):
        assert isinstance(cap, IntolerableCap), "the time point's IntolerableCap is required"
        pinprick = rig.session.config.study1["pinprick"]
        super().__init__(
            rig,
            region,
            int(pinprick["short_protocol_n_trials"]),
            int(pinprick["n_sites"]),
            (float(pinprick["isi_min_s"]), float(pinprick["isi_max_s"])),
        )
        self.filaments = ladder(self.session.config)
        self.index = ladder_index(self.filaments, filament_label_g)
        self.filament_label_g = filament_label_g
        self.cap = cap
        self.intolerable_vas_pct = float(pinprick["intolerable_vas_pct"])
        self._site = 0

    def _stimulus(self) -> str:
        return self.filament_label_g

    def _apply_next(self) -> None:
        placed = place(self.cap, self.rotation, self.region, self.index)
        if placed is None:
            # Not even the lightest filament may be given: the series stops with what it has.
            self.session.log("cap_bars_every_filament", severity="warning", detail=self.region)
            self.n_trials = len(self.ratings)
            self._next()
            return
        index, site = placed
        if index != self.index:
            self.session.log(
                "cap_lowered", severity="warning",
                detail=f"asked {self.filament_label_g} g, capped at every site; "
                f"{self.filaments[index].label_g} g instead",
            )
        self.rotation.take(site)
        self._site = site
        application = Application(
            protocol=SHORT,
            region=self.region,
            trial_index=self.applications + 1,
            purpose=MEASURE,
            filament_label_g=self.filaments[index].label_g,
            site_index=site,
        )
        self.apply(
            lambda: PinprickTrial(
                self.session, self.participant, self.experimenter, application
            ),
            self._rated,
        )

    def _rated(self, trial: PinprickTrial, response) -> None:
        applied = ladder_index(self.filaments, trial.applied_label_g)
        _record_ceiling(self, trial, response, applied, self._site)
        self._on_rated(trial, response)


class BrushProtocol(_RatingSeries):
    """Brush allodynia (SPEC.md 8.3): the short protocol's structure with a soft brush.
    `finished` carries a `RatingSeriesResult` whose `stimulus` is `brush`."""

    TABLE = BRUSH_TABLE

    def __init__(self, rig: Rig, region: str):
        brush = rig.session.config.study1["brush"]
        super().__init__(
            rig,
            region,
            int(brush["n_trials"]),
            int(brush["n_sites"]),
            (float(brush["isi_min_s"]), float(brush["isi_max_s"])),
        )

    def _stimulus(self) -> str:
        return BRUSH_TABLE

    def _apply_next(self) -> None:
        site = self.rotation.order()[0]
        self.rotation.take(site)
        application = BrushApplication(self.region, self.applications + 1, site)
        self.apply(
            lambda: BrushTrial(self.session, self.participant, self.experimenter, application),
            self._on_rated,
        )
