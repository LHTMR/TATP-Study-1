"""Protocol B -- touch pressure calibration. SPEC.md 9, 10.3.

Milestone 1 builds the first step end to end: one method-of-adjustment trial on the reference
channel against the mock garment, and one touch intensity rating. The estimation run and its fit
(SPEC.md 9 step 2), the channel matching, the equalisation comparisons and the pleasantness
adjustment are later milestones -- what exists here is the path through every layer, not the
protocol in full.

**The accelerating control (SPEC.md 10.3) is `AdjustmentState`, which imports no Qt and takes
the time as an argument.** Every rule that matters -- a press moves at least one step, a hold
accelerates from the initial rate to the final one over the ramp, the pressure stays inside the
adjustable range -- is then tested at exact times rather than at whatever times a timer happened
to fire.
`Adjustment` is the thin Qt driver around it: it turns the participant window's button signals
into calls, ticks the state, and commands the garment.

**The control runs on real seconds, not on the accelerated clock.** A hold delay and a ramp
rate describe the participant's hand, so scaling them does not make a session faster, it makes
the control different -- at speed 100 every press would be a hold. The one
duration here that *is* scaled is the adjustment time-out, which is the session waiting for the
participant rather than the participant acting.

**Every button-down and button-up is logged** (SPEC.md 10.3), so the search path is recoverable
from the `log` table and not only from the value the participant settled on.

**Minimum exploration is recorded, not enforced.** `min_exploration_kpa` is written to
`min_exploration_met` and left there: refusing a confirm would mean telling the participant why,
and there is no approved wording for that (SPEC.md 10.4 forbids inventing one). If the
requirement should bite rather than be flagged, it needs a string in
`config/text/participant_{sv,en}.yaml` first.

No literals (SPEC.md 4.2): every rate, step and interval comes from `config/hardware.yaml`, and
every target from `config/study1.yaml`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from tatp import touchcal_maths as maths
from tatp.procedure import Procedure
from tatp.responder import Action
from tatp.resume import RECALIBRATION_EVENT, RESUME_CHOICE, ResumeState
from tatp.session import Session
from tatp.touchcal_maths import REFERENCE_STRONGER, TEST_STRONGER, Delivery
from tatp.trials import Choice, Cue, ExperimenterChoice, Ramp, Trial
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import SIDES, ParticipantWindow
from tatp.units import MS_PER_S

# Config keys and controlled-vocabulary values, not wording.
INTENSITY_SCALE = "intensity"
ANCHOR_STAGE = "anchor"
MATCH_STAGE = "channel_match"
PLEASANTNESS_STAGE = "pleasantness"
BELOW = "below"
ABOVE = "above"
TOUCH_CALIBRATION = "touch_calibration"  # the phase, and the fit_preview.procedures entry
# Keys in the participant text file.
MATCH_TARGET = "match"
PLEASANTNESS_TARGET = "most_pleasant"
COMPARISON_CHOICE = "comparison"
EVENNESS_CHOICE = "evenness"
SELF_START_SCREEN = "self_start"
# The introduction before each new kind of task (docs/LOG.md N7.F11c1): participant screen
# keys; the experimenter's line meanwhile is the instruction `touchcal_<key>`, or for a
# channel set again inside step 4, `touchcal_intro_readjust`.
INTRO_BRACKET = "intro_bracket"
INTRO_ESTIMATION = "intro_estimation"
INTRO_MATCH = "intro_match"
INTRO_COMPARE = "intro_compare"
INTRO_PLEASANT = "intro_pleasant"
INTRO_INSTRUCTION = "touchcal_"
INTRO_READJUST_INSTRUCTION = "touchcal_intro_readjust"
# The one experimenter instruction at the start of every touch delivery, in every condition.
TOUCH_START_INSTRUCTION = "touch_start"
MATCH_INSTRUCTION = "touchcal_match"
READJUST_INSTRUCTION = "touchcal_readjust"
EQUALISE_INSTRUCTION = "touchcal_equalise"
# `touchcal_compare.order` and `touchcal_evenness.judgement`.
TEST_FIRST = "test_first"
REFERENCE_FIRST = "reference_first"
EVEN = "even"
UNEVEN = "uneven"
# A stage-1 failure found before any fit: the step 1 settings leave nothing to sample.
BRACKET_UNUSABLE = "bracket_unusable"
# The experimenter's choices, as `ExperimenterChoice` names them.
ACCEPT = "accept"
RERUN = "rerun"
REBALANCE = "rebalance"
PROCEED = "proceed"
# `controls` keys of the other-answer button (review of N7.F16): the fallback after an
# unusable estimate with no re-runs left, and the flagged channel after an undefined gain.
FIT_FALLBACK = "fit_fallback"
GAIN_FALLBACK_CONTROL = "gain_fallback"
# A re-calibration (docs/LOG.md N7.F12a1): the other path beside `REBALANCE`, the trigger
# beside `interruption.EMERGENCY_STOP`, what a restarted run's `touchcal_fit.rerun_reason`
# starts with, and the calibration's steps as the `recalibration` event names the one it
# abandoned (docs/DATA_SCHEMA.md).
RESTART = "restart"
FROM_CONTROLS = "controls"
RERUN_RECALIBRATION = "recalibration"
STEP_TRAINING = "training"
STEP_BRACKET = "step1_bracket"
STEP_ESTIMATION = "step2_estimation"
STEP_FIT_DECISION = "fit_decision"
STEP_MATCH = "step3_match"
STEP_COMPARE = "step4_compare"
STEP_PLEASANTNESS = "step5_pleasantness"
STEP_EVENNESS = "evenness"
STEP_PREFERENCE = "step6_preference"


def recalibration_allowed(session: Session) -> bool:
    """Whether `touch_calibration.recalibrations_max` leaves another; null is no limit."""
    limit = session.config.study1["touch_calibration"]["recalibrations_max"]
    return limit is None or session.recalibrations < limit


def recalibrations_used_up(session: Session) -> bool:
    """Whether a limit there was has been reached -- not a limit of none at all."""
    limit = session.config.study1["touch_calibration"]["recalibrations_max"]
    return bool(limit) and not recalibration_allowed(session)


def log_recalibration(session: Session, choice: str, trigger: str, where: str,
                      reason: str, in_intervention: bool) -> None:
    """The `recalibration` row: how the experimenter went on from a stop where touch was
    being calibrated or delivered, or what they chose from the controls (docs/LOG.md
    N7.F12a1). `<choice>; <trigger>; <where>; <reason>; <count>`. A rebalance or a restart is
    counted, for the limit and, during the intervention, as an intercurrent event -- one
    chosen inside a re-calibration there included."""
    count = ""
    if choice != RESUME_CHOICE:
        session.recalibrations += 1
        count = str(session.recalibrations)
        if in_intervention:
            session.intervention_recalibrations += 1
    session.log(RECALIBRATION_EVENT, origin="experimenter",
                detail=f"{choice}; {trigger}; {where}; {reason}; {count}")


@dataclass(frozen=True)
class AdjustmentPlan:
    """One planned adjustment. Everything the protocol decides; the trial only carries it."""

    stage: str
    channel: int
    target_key: str
    adjustment_index: int
    start_direction: str
    range_min_kpa: float
    range_max_kpa: float
    # Empty for `anchor`: there is nothing to match to until the reference channel is fitted.
    reference_channel: int | None = None
    # The VAS point being produced. Empty for pleasantness, which has no target.
    anchor_percent: float | None = None
    # Where the point is expected to be, when anything is known about it. Steps 3 and 5 chain
    # off the fitted reference values; step 1 has nothing to chain off, so it starts at an end.
    expected_kpa: float | None = None
    # Which run of steps 1 and 2 this adjustment belongs to (a stage-1 re-run starts a new one),
    # and which pass for this channel: a step 3 re-adjustment, a zero-setting repeat or a
    # rebalance each match a channel again, and the earlier pass stays in the data.
    run_index: int = 1
    pass_index: int = 1


def start_pressure_kpa(plan: AdjustmentPlan, start_offset_fraction: float) -> float:
    """Where an adjustment begins, from below or from above.

    With an expected value, the start is `start_offset_fraction` of the adjustable range away
    from it -- the configured meaning of that fraction (SPEC.md 9, `config/study1.yaml`). With
    none, the start is the range end on that side, which is the ordinary method of adjustment
    and the only honest choice for step 1: nothing is yet known about where the anchor lies, and
    a fraction of the range below an invented expectation would be an invented start point.
    """
    if plan.start_direction not in (BELOW, ABOVE):
        raise ValueError(f"start_direction {plan.start_direction!r} is not {BELOW!r}/{ABOVE!r}")
    below = plan.start_direction == BELOW
    if plan.expected_kpa is None:
        return plan.range_min_kpa if below else plan.range_max_kpa
    span = plan.range_max_kpa - plan.range_min_kpa
    offset = start_offset_fraction * span
    start = plan.expected_kpa - offset if below else plan.expected_kpa + offset
    return min(max(start, plan.range_min_kpa), plan.range_max_kpa)


def anchor_plans(config, run_index: int = 1) -> tuple[AdjustmentPlan, ...]:
    """Protocol B step 1: bracket the range on the reference channel (SPEC.md 9).

    One plan per anchor per adjustment, in the order they are run. The adjustable range is the
    whole safe range of the device -- the bracket is what these adjustments produce, so nothing
    narrower is known yet -- and the start direction alternates through `start_directions`, so
    that with two adjustments per anchor one starts below and one above.
    """
    touch = config.study1["touch_calibration"]
    anchors = list(touch["anchors_pct"])
    prompts = list(touch["anchor_prompt_keys"])
    directions = list(touch["start_directions"])
    # Stage boundary (CLAUDE.md): an anchor with no prompt would be a screen with no question.
    assert len(prompts) == len(anchors), (
        f"study1.yaml: touch_calibration has {len(anchors)} anchors_pct but "
        f"{len(prompts)} anchor_prompt_keys"
    )
    assert directions, "study1.yaml: touch_calibration.start_directions is empty"

    ceiling_kpa = float(config.hardware["garment"]["pressure_ceiling_kpa"])
    plans = []
    for anchor_percent, target_key in zip(anchors, prompts, strict=True):
        for index in range(int(touch["adjustments_per_anchor"])):
            plans.append(
                AdjustmentPlan(
                    stage=ANCHOR_STAGE,
                    channel=int(touch["reference_channel"]),
                    target_key=target_key,
                    adjustment_index=index + 1,
                    start_direction=directions[index % len(directions)],
                    range_min_kpa=0.0,
                    range_max_kpa=ceiling_kpa,
                    anchor_percent=float(anchor_percent),
                    run_index=run_index,
                )
            )
    return tuple(plans)


def pressure_control(adjustment_config: dict) -> dict:
    """The accelerating control's settings for a pressure, in kPa (SPEC.md 10.3)."""
    return {
        "tap_step": adjustment_config["tap_step_kpa"],
        "hold_delay_s": adjustment_config["hold_delay_s"],
        "hold_rate_initial_per_s": adjustment_config["hold_rate_initial_kpa_s"],
        "hold_rate_final_per_s": adjustment_config["hold_rate_final_kpa_s"],
        "hold_ramp_duration_s": adjustment_config["hold_ramp_duration_s"],
    }


class AdjustmentState:
    """The accelerating control of SPEC.md 10.3. No Qt; the caller supplies the time.

    Unit-neutral: the value is whatever the caller controls -- kPa for a pressure
    (`pressure_control`), dB for the noise (`tatp.setup_checks.noise_control`) -- and the step
    and rates are in that unit. The hold timings describe the participant's hand.

    **Every press moves at least one step.** A press the hold has not yet carried a full step
    -- released before the hold delay, or just after it, when the ramp has barely begun -- is
    made up to one step on release. An earlier rule moved one step only for a press released
    within a tap threshold (150 ms) and nothing at all between that and the hold delay
    (300 ms), so an ordinary deliberate press on the remote, which often lasts about 200 ms, was
    lost: S's 5 Oct 2026 lab run found the noise "cannot be turned down in the second step",
    where turning down is done by single presses (docs/LOG.md, the audio-calibration fixes).
    """

    def __init__(self, control: dict, range_min: float, range_max: float, start: float):
        self.tap_step = float(control["tap_step"])
        self.hold_delay_s = float(control["hold_delay_s"])
        self.rate_initial_per_s = float(control["hold_rate_initial_per_s"])
        self.rate_final_per_s = float(control["hold_rate_final_per_s"])
        self.ramp_duration_s = float(control["hold_ramp_duration_s"])
        # Stage boundary (CLAUDE.md): the control is described as accelerating, and a ramp of
        # zero length would divide by zero rather than merely being a different control.
        assert self.ramp_duration_s > 0, "adjustment.hold_ramp_duration_s must be positive"
        assert range_min < range_max, f"the adjustable range {range_min}--{range_max} is empty"

        self.range_min = float(range_min)
        self.range_max = float(range_max)
        self.value = min(max(float(start), self.range_min), self.range_max)
        self.exploration = 0.0
        self.button_events = 0

        self._held: Action | None = None
        self._pressed_at_s = 0.0
        self._held_travel_s = 0.0

    @property
    def held(self) -> Action | None:
        return self._held

    # -- input -------------------------------------------------------------------------

    def press(self, action: Action, now_s: float) -> None:
        self.button_events += 1
        if action in (Action.DECREASE, Action.INCREASE):
            self._held = action
            self._pressed_at_s = now_s
            self._held_travel_s = 0.0

    def release(self, action: Action, now_s: float) -> None:
        self.button_events += 1
        if action is not self._held:
            return
        # The hold's travel up to the release itself, not only to the last tick.
        self.tick(now_s)
        # Made up to one step, never more: a hold that has already carried the value a step or
        # further has moved it, and adding a step would double the last one.
        shortfall = self.tap_step - self._travel(self._held_travel_s)
        if shortfall > 0:
            self._move(self._direction(action) * shortfall)
        self._held = None

    def tick(self, now_s: float) -> None:
        """Apply the movement owed since the last tick. Nothing to do unless a key is held."""
        if self._held is None:
            return
        held_s = now_s - self._pressed_at_s - self.hold_delay_s
        # Never backwards: a release timed from its key event's stamp can fall before the last
        # tick, when a stall let that tick run late (`PressTiming`).
        if held_s <= self._held_travel_s:
            return
        travelled = self._travel(held_s) - self._travel(self._held_travel_s)
        self._held_travel_s = held_s
        self._move(self._direction(self._held) * travelled)

    # -- the ramp ----------------------------------------------------------------------

    def rate_per_s(self, held_s: float) -> float:
        """The rate at `held_s` seconds into the hold, past the delay. SPEC.md 10.3."""
        if held_s <= 0:
            return 0.0
        if held_s >= self.ramp_duration_s:
            return self.rate_final_per_s
        fraction = held_s / self.ramp_duration_s
        return self.rate_initial_per_s + fraction * (
            self.rate_final_per_s - self.rate_initial_per_s
        )

    def _travel(self, held_s: float) -> float:
        """Distance travelled in the first `held_s` seconds of a hold.

        The integral of a linear ramp, in closed form rather than accumulated per tick, so the
        distance depends on how long the button was held and not on how often the timer fired.
        """
        if held_s <= 0:
            return 0.0
        ramped = min(held_s, self.ramp_duration_s)
        gained = self.rate_final_per_s - self.rate_initial_per_s
        # The 2 is the area of a triangle, not a study parameter (SPEC.md 4.2).
        distance = self.rate_initial_per_s * ramped + gained * ramped * ramped / (
            2 * self.ramp_duration_s
        )
        return distance + self.rate_final_per_s * max(0.0, held_s - self.ramp_duration_s)

    # -- plumbing ----------------------------------------------------------------------

    def _direction(self, action: Action) -> float:
        return -1.0 if action is Action.DECREASE else 1.0

    def _move(self, delta: float) -> None:
        before = self.value
        self.value = min(max(self.value + delta, self.range_min), self.range_max)
        # Travel that the range refused is not exploration: the participant learns nothing from
        # pressing against an end stop.
        self.exploration += abs(self.value - before)


class PressTiming:
    """When a button went up, in real seconds, from the key events' own timestamps.

    The press handler writes a log row before the release handler can run, so timing a press
    from handler calls would add any stall in that write to the hold -- turning a tap into a
    hold of however long the stall lasted. The press is placed when its handler runs and the
    release that many event milliseconds after it.

    A stall longer than the hold delay can still let a tick run before the release, so the
    press moves as a hold for that long (docs/LOG.md N2.9); `AdjustmentState.tick` never runs
    it backwards when the stamped release then falls before that tick.
    """

    def __init__(self):
        self._presses: dict[Action, tuple[int, float]] = {}

    def pressed(self, action: Action, event_ms: int, now_s: float) -> float:
        self._presses[action] = (event_ms, now_s)
        return now_s

    def released(self, action: Action, event_ms: int, now_s: float) -> float:
        if action not in self._presses:
            # Held down before this screen appeared, so the press never reached it.
            # AdjustmentState ignores a release it holds no press for; the time is irrelevant.
            return now_s
        press_ms, press_s = self._presses.pop(action)
        held_ms = event_ms - press_ms
        if held_ms < 0:
            # The OS's millisecond counter wrapped mid-press (Windows' does every 49.7 days of
            # uptime). Not asserted: an exception in this slot would leave the state held, and
            # the tick would ramp the pressure with nobody touching the button.
            return now_s
        return press_s + held_ms / MS_PER_S


class Adjustment(QObject):
    """One method-of-adjustment trial, driven by the participant's buttons. SPEC.md 9, 10.3.

    `finished` carries the produced pressure in kPa. A trial in the sense of
    `tatp/procedure.py`: an interruption is handled by whatever runs it, which calls `cancel()`.
    """

    finished = Signal(object)
    # Whether the screen names two alternating touches (`MatchAdjustment`).
    paired = False

    def __init__(
        self,
        session: Session,
        participant: ParticipantWindow,
        experimenter: ExperimenterWindow,
        plan: AdjustmentPlan,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.session = session
        self.participant = participant
        self.experimenter = experimenter
        self.plan = plan

        touch = session.config.study1["touch_calibration"]
        adjustment = session.config.hardware["adjustment"]
        self.timeout_s = float(touch["adjustment_timeout_s"])
        self.min_exploration_kpa = float(touch["min_exploration_kpa"])
        self.start_kpa = start_pressure_kpa(plan, float(touch["start_offset_fraction"]))
        self.state = AdjustmentState(
            pressure_control(adjustment), plan.range_min_kpa, plan.range_max_kpa, self.start_kpa
        )

        self.start_iso = ""
        self._start_s = 0.0
        self._press_timing = PressTiming()
        self._t_session_s: float | None = None
        self.timed_out = False
        self._ceiling_logged = False

        self._tick = QTimer(self)
        # Real milliseconds, not scaled: the ramp is in real seconds, so the tick that samples
        # it must be too. `adjustment_timeout_s` below is scaled, because that one is session
        # pacing -- the participant is being waited for -- rather than the participant's hand.
        self._tick.setInterval(int(round(float(adjustment["tick_interval_s"]) * MS_PER_S)))
        self._tick.timeout.connect(self._on_tick)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_timeout)

    # -- the sequence ------------------------------------------------------------------

    def start(self) -> None:
        """Take the channel to the start pressure and hand the buttons to the participant."""
        clock = self.session.clock
        self.start_iso = clock.wall_iso()
        # Real seconds: `duration_s` is how long a participant took, which is the open item 8
        # measurement and must not be reported scaled.
        self._start_s = clock.real_elapsed_s()
        self._t_session_s = clock.t_session_s()

        self._command()
        self.participant.adjust_pressed.connect(self._on_pressed)
        self.participant.adjust_released.connect(self._on_released)
        self.participant.adjust_confirmed.connect(self._on_confirmed)

        self.participant.show_adjustment(self.plan.target_key, self.paired)
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["await_participant"]
        )
        self.experimenter.refresh()
        self.session.log(
            "adjustment_started",
            detail=f"{self.plan.stage}, channel {self.plan.channel}, "
            f"from {self.plan.start_direction} at {self.state.value:.1f} kPa",
        )
        self._tick.start()
        self._timeout.start(self.session.clock.scaled_ms(self.timeout_s))

    def _on_pressed(self, action_value: str, event_ms: int) -> None:
        action = Action(action_value)
        now_s = self.session.clock.real_elapsed_s()
        self.state.press(action, self._press_timing.pressed(action, event_ms, now_s))
        self._log_button("button_down", action_value)

    def _on_released(self, action_value: str, event_ms: int) -> None:
        action = Action(action_value)
        now_s = self.session.clock.real_elapsed_s()
        self.state.release(action, self._press_timing.released(action, event_ms, now_s))
        self._log_button("button_up", action_value)
        self._command()

    def _on_tick(self) -> None:
        self.state.tick(self.session.clock.real_elapsed_s())
        self._command()

    def targets_kpa(self, pressure_kpa: float) -> dict[int, float]:
        """What each channel is commanded to for the pressure the participant has set.

        One channel here. The pleasantness adjustment overrides it to drive every channel of
        the pattern through its gain (SPEC.md 9 step 5).
        """
        return {self.plan.channel: pressure_kpa}

    def _command(self) -> None:
        # Re-commanded until the garment holds it, so a command the rate limit shortened is
        # finished on the following ticks rather than left short (SPEC.md 13).
        garment = self.session.garment
        for channel, kpa in self.targets_kpa(self.state.value).items():
            target = min(kpa, garment.limits.pressure_ceiling_kpa)
            if target < kpa and not self._ceiling_logged:
                self._ceiling_logged = True
                self.session.log(
                    "target_above_ceiling",
                    severity="warning",
                    detail=f"channel {channel}: {kpa:.1f} kPa held at the ceiling",
                )
            if garment.pressure_kpa[channel] != target:
                garment.set_pressure(channel, target)

    # -- the end of the trial -----------------------------------------------------------

    def _on_confirmed(self) -> None:
        self._end()
        self.session.log(
            "adjustment_confirmed",
            origin="participant",
            detail=f"{self.state.value:.1f} kPa after "
            f"{self.state.button_events} button events",
        )
        self._write()
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["response_received"]
        )
        self.experimenter.refresh()
        self.finished.emit(self.state.value)

    def _on_timeout(self) -> None:
        """SPEC.md 9: the method of adjustment has no stopping rule of its own.

        The trial ends at whatever the participant had reached, flagged, rather than waiting
        indefinitely or discarding what they did.
        """
        self.timed_out = True
        self._end()
        self.session.log(
            "adjustment_timed_out",
            severity="warning",
            detail=f"{self.plan.stage}, channel {self.plan.channel}, "
            f"after {self.timeout_s} s",
        )
        self._write()
        self.finished.emit(self.state.value)

    def cancel(self) -> None:
        """Abandoned by an interruption (SPEC.md 13); no row is written.

        Nothing was produced, so there is no produced pressure to record. The garment is already
        at zero -- `tatp/interruption.py` did that before anything else -- and the log carries
        the pressure that was commanded when it happened.
        """
        self._end()
        self.session.log(
            "trial_cancelled",
            detail=f"{self.plan.stage} adjustment at {self.state.value:.1f} kPa",
        )

    def _write(self) -> None:
        self.session.files.write(
            "touchcal_adjust",
            timestamp_iso=self.start_iso,
            t_session_s=self._t_session_s,
            stage=self.plan.stage,
            run_index=self.plan.run_index,
            pass_index=self.plan.pass_index,
            channel=self.plan.channel,
            reference_channel=self.plan.reference_channel,
            anchor_percent=self.plan.anchor_percent,
            adjustment_index=self.plan.adjustment_index,
            start_direction=self.plan.start_direction,
            start_pressure_kpa=self.start_kpa,
            produced_pressure_kpa=self.state.value,
            range_min_kpa=self.plan.range_min_kpa,
            range_max_kpa=self.plan.range_max_kpa,
            duration_s=self.session.clock.real_elapsed_s() - self._start_s,
            button_events=self.state.button_events,
            min_exploration_met=self.state.exploration >= self.min_exploration_kpa,
            timed_out=self.timed_out,
            # SPEC.md 12.4: a device that cannot set pressure per channel produces real timings
            # and unreal pressures, and an adjustment is entirely about the pressure.
            valid_for_analysis=self.session.garment.per_channel_pressure,
        )

    def _log_button(self, event: str, action_value: str) -> None:
        self.session.log(
            event,
            origin="participant",
            detail=f"{action_value} at {self.state.value:.1f} kPa",
        )

    def _end(self) -> None:
        self._tick.stop()
        self._timeout.stop()
        self.participant.adjust_pressed.disconnect(self._on_pressed)
        self.participant.adjust_released.disconnect(self._on_released)
        self.participant.adjust_confirmed.disconnect(self._on_confirmed)


class TouchRating(QObject):
    """One touch VAS rating while the garment is delivering. SPEC.md 9, 10.2, 10.6.

    The stimulus is whatever the caller has already commanded -- the rating asks about the
    touch that is happening, so this class commands nothing and records what it finds.
    """

    finished = Signal(object)

    def __init__(
        self,
        session: Session,
        participant: ParticipantWindow,
        experimenter: ExperimenterWindow,
        scale: str,
        channel: int,
        parent: QObject | None = None,
        record: bool = True,
    ):
        super().__init__(parent)
        self.session = session
        self.participant = participant
        self.experimenter = experimenter
        self.scale = scale
        self.channel = channel
        # False for a rating whose row belongs in another table -- the estimation run writes
        # `touchcal_estimate`, and the same rating in `touch_ratings` would be counted twice.
        self.record = record
        self.cue_iso = ""
        self._t_session_s: float | None = None

    def start(self) -> None:
        self.participant.confirmed.connect(self._on_confirmed)
        self.cue_iso = self.session.clock.wall_iso()
        self._t_session_s = self.session.clock.t_session_s()
        self.participant.show_vas(self.scale)
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["await_participant"]
        )
        self.experimenter.refresh()
        self.session.log("rating_cued", detail=self.scale)

    def _on_confirmed(self, response) -> None:
        self._end()
        status = self.session.garment.status()
        if self.record:
            self._write(response, status)
        self.session.log(
            "rating_confirmed",
            origin="participant",
            detail=f"{self.scale}, rt {response.rt_s:.3f} s",
        )
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["response_received"]
        )
        self.experimenter.refresh()
        self.participant.show_blank()
        self.finished.emit(response)

    def _write(self, response, status: dict) -> None:
        self.session.files.write(
            "touch_ratings",
            timestamp_iso=self.cue_iso,
            t_session_s=self._t_session_s,
            phase=self.session.phase,
            block_index=self.session.block_index,
            scale=self.scale,
            rating_percent=response.rating_percent,
            rt_s=response.rt_s,
            first_press_side=response.first_press_side,
            direction_changes=response.direction_changes,
            # Recorded, never displayed: the pattern names the condition (SPEC.md 16).
            pattern_name=status["pattern_name"],
            commanded_pressure_kpa=status["pressure_kpa"].get(self.channel),
            valid_for_analysis=self.session.garment.per_channel_pressure,
        )

    def cancel(self) -> None:
        """Abandoned by an interruption (SPEC.md 13). No rating was given, so no row."""
        self._end()
        self.session.log("trial_cancelled", detail=f"the {self.scale} rating")

    def _end(self) -> None:
        self.participant.confirmed.disconnect(self._on_confirmed)


# -- step 3: channel matching ------------------------------------------------------------


class MatchAdjustment(Adjustment):
    """Protocol B step 3: set a channel to feel as strong as the reference (SPEC.md 9).

    The wording asks the participant to set "the second touch so that it feels as strong as
    the first", so the two alternate -- the reference for `hold_s`, a gap, the channel being
    adjusted for `hold_s`, a gap -- for as long as the adjustment runs. The participant
    compares what they are setting against what they are matching it to on every cycle
    rather than against a memory of one presentation. The hold is the comparison's 3 s,
    which clears the inflation transient (comparison doc 7.4). The reference's pressure is
    already set by the caller; this trial switches channels and commands only the one being
    adjusted.

    The screen names the two "The first" and "The second", and marks the one on as it plays
    (docs/LOG.md N7.F11c5), so the participant knows which they are feeling.
    """

    paired = True

    def __init__(self, session, participant, experimenter, plan: AdjustmentPlan):
        super().__init__(session, participant, experimenter, plan)
        touch = session.config.study1["touch_calibration"]
        self.hold_s = float(touch["comparison_hold_s"])
        self.gap_s = float(touch["comparison_gap_s"])
        self._cycle = QTimer(self)
        self._cycle.setSingleShot(True)
        self._cycle.timeout.connect(self._advance)
        self._phase = 0

    def start(self) -> None:
        super().start()
        self._phase = 0
        self._enter()

    def _advance(self) -> None:
        self._phase = (self._phase + 1) % len(self._phases())
        self._enter()

    def _phases(self) -> tuple[tuple[int | None, float], ...]:
        """(channel on, seconds): the reference, a gap, the adjusted channel, a gap."""
        return (
            (self.plan.reference_channel, self.hold_s),
            (None, self.gap_s),
            (self.plan.channel, self.hold_s),
            (None, self.gap_s),
        )

    def _enter(self) -> None:
        on, seconds = self._phases()[self._phase]
        garment = self.session.garment
        for channel in (self.plan.reference_channel, self.plan.channel):
            wanted = channel == on
            if (channel in garment.status()["channels_on"]) != wanted:
                garment.set_channel(channel, wanted)
        playing = {self.plan.reference_channel: 0, self.plan.channel: 1}
        self.participant.emphasise_adjustment(playing.get(on))
        self._cycle.start(self.session.clock.scaled_ms(seconds))

    def _end(self) -> None:
        self._cycle.stop()
        super()._end()


# -- step 5: pleasantness ----------------------------------------------------------------


class PatternAdjustment(Adjustment):
    """Protocol B step 5: the most pleasant level, with the pattern looping (SPEC.md 9).

    The participant moves one level on the reference channel's scale, and every channel
    follows it through its gain, so the balance step 3 set is kept while the overall level
    moves. The range is the fitted [P30, P80], which is both what Bilaga 1 3.9.1 specifies and
    a safety property (comparison doc 7.5). The pattern is started by the caller.
    """

    def __init__(self, session, participant, experimenter, plan, gains: dict[int, float]):
        super().__init__(session, participant, experimenter, plan)
        self.gains = dict(gains)

    def targets_kpa(self, pressure_kpa: float) -> dict[int, float]:
        return {channel: pressure_kpa * g for channel, g in sorted(self.gains.items())}


# -- step 2: one presentation of the estimation run --------------------------------------


class EstimationPresentation(Trial):
    """One amplitude, or a catch trial, and its intensity rating (SPEC.md 9 step 2).

    The pressure is reached first with the channel closed, before the cue, as the comparison
    does: a ramp after onset would take longer the higher the amplitude, and a presentation
    whose scale came up sooner than the others would give the catch trials away. So every
    presentation, catch trials included, runs cue, onset, `estimation_settle_s`, scale -- the
    same timing -- and the stimulus stays on until the participant confirms, because the
    question asks how intense the touch *is* (docs/research/R32). A catch trial commands no
    pressure and switches nothing on: on a device whose channels are on/off at a hand-set
    pressure, switching one on would be a real touch.

    **The off-interval is this trial's, and the ramp runs inside it.** `off_s` is the time from
    the previous presentation's stop to this one's warning cue: the fixed
    `touch_calibration.estimation_window_s` (docs/LOG.md N7.F14e). The pressure is reached
    with the channel closed during it, so the pause is the same whatever comes next, a catch
    trial included. Ramping after the interval made the pause after a response the interval
    plus up to the ceiling over the rate limit -- 4 s more on the prototype, whose pressures
    are not even delivered (docs/LOG.md N7.F8a). A ramp longer than the interval still ends
    before the cue, so the cue waits for it; on a worn garment `TouchCalibration` refuses a
    window shorter than the slowest ramp.

    The interval counts from `stopped_s`, the previous presentation's stop as it reported it,
    so the work between -- a row written, a screen redrawn -- is inside the interval rather
    than added to it. None (the first presentation, or a repeat after an interruption) counts
    from this one's own start. Finishes with (plan, rating, the `elapsed_s` of its own stop).
    """

    def __init__(self, session, participant, experimenter, plan, channel: int, run_index: int,
                 off_s: float, stopped_s: float | None):
        super().__init__(session, participant, experimenter)
        self.plan = plan
        self.channel = channel
        self.run_index = run_index
        self.off_s = off_s
        self.stopped_s = stopped_s
        touch = session.config.study1["touch_calibration"]
        self.settle_s = float(touch["estimation_settle_s"])
        self.onset_iso = ""
        self._t_session_s: float | None = None

    def start(self) -> None:
        clock = self.session.clock
        stopped_s = clock.elapsed_s() if self.stopped_s is None else self.stopped_s
        # The rest since the last presentation, which the rating left blank (LOG N7.F14d).
        self.participant.show_rest(clock.remaining_s(stopped_s, self.off_s))
        # From nothing, whatever an interrupted attempt or a restored garment left behind.
        self.session.garment.stop()
        levels = {} if self.plan.catch_trial else {self.channel: self.plan.pressure_kpa}
        self.ramp_then(
            levels,
            lambda: self.after(
                clock.remaining_s(stopped_s, self.off_s), lambda: self.cue_then(self._onset)
            ),
        )

    def _onset(self) -> None:
        self.onset_iso = self.session.clock.wall_iso()
        self._t_session_s = self.session.clock.t_session_s()
        self.session.log(
            "estimation_presentation",
            detail=f"run {self.run_index}, order {self.plan.presentation_order}, "
            f"{'catch' if self.plan.catch_trial else f'{self.plan.pressure_kpa:.1f} kPa'}",
        )
        if not self.plan.catch_trial:
            self.session.garment.set_channel(self.channel, True)
        self.after(self.settle_s, self._rate)

    def _rate(self) -> None:
        rating = TouchRating(
            self.session,
            self.participant,
            self.experimenter,
            INTENSITY_SCALE,
            self.channel,
            parent=self,
            record=False,
        )
        self.run(rating, self._rated)

    def _rated(self, response) -> None:
        self.session.files.write(
            "touchcal_estimate",
            timestamp_iso=self.onset_iso,
            t_session_s=self._t_session_s,
            channel=self.channel,
            run_index=self.run_index,
            presentation_order=self.plan.presentation_order,
            amplitude_index=self.plan.amplitude_index,
            pressure_kpa=self.plan.pressure_kpa,
            catch_trial=self.plan.catch_trial,
            rating_percent=response.rating_percent,
            reaction_time_s=response.rt_s,
            valid_for_analysis=self.session.garment.per_channel_pressure,
        )
        self.session.garment.stop()
        stopped_s = self.session.clock.elapsed_s()
        self.done((self.plan, response.rating_percent, stopped_s))


# -- step 4: one equalisation comparison -------------------------------------------------


@dataclass(frozen=True)
class ComparisonPlan:
    """One two-alternative comparison of a channel against the reference (SPEC.md 9 step 4)."""

    channel: int
    reference_channel: int
    comparison_index: int
    order: str
    pair_index: int
    pass_index: int
    test_pressure_kpa: float
    reference_pressure_kpa: float


class Comparison(Trial):
    """Two 3 s holds, one after the other, and which felt stronger (SPEC.md 9 step 4, 10.8).

    Each stimulus emphasises its own button as it plays -- the first on the left, the second
    on the right -- and the screen accepts nothing until both are over. A press before then is
    logged and not counted. The press that follows is the judgement, with no confirm.

    `readjust_if(judgement)` says whether this judgement completes a mismatch that a
    re-adjustment will follow, which the row records as `readjusted` (docs/research/R33). It
    is the procedure's rule; the trial only writes it down.
    """

    def __init__(self, session, participant, experimenter, plan: ComparisonPlan,
                 readjust_if: Callable[[str], bool]):
        super().__init__(session, participant, experimenter)
        self.plan = plan
        self.readjust_if = readjust_if
        touch = session.config.study1["touch_calibration"]
        self.hold_s = float(touch["comparison_hold_s"])
        self.gap_s = float(touch["comparison_gap_s"])
        test_first = plan.order == TEST_FIRST
        self.sequence = (
            (plan.channel, plan.reference_channel)
            if test_first
            else (plan.reference_channel, plan.channel)
        )
        self.onset_iso = ""
        self._t_session_s: float | None = None

    def start(self) -> None:
        self.session.garment.stop()
        self.ramp_then(
            {
                self.plan.channel: self.plan.test_pressure_kpa,
                self.plan.reference_channel: self.plan.reference_pressure_kpa,
            },
            lambda: self.cue_then(self._first),
        )

    def _first(self) -> None:
        self.onset_iso = self.session.clock.wall_iso()
        self._t_session_s = self.session.clock.t_session_s()
        self.listen(self.participant.pressed_before_accepting, self._early)
        self.participant.show_choice(COMPARISON_CHOICE)
        self._stimulus(0, lambda: self.after(self.gap_s, self._second))

    def _second(self) -> None:
        self._stimulus(1, self._accept)

    def _stimulus(self, index: int, then: Callable[[], None]) -> None:
        channel = self.sequence[index]
        self.session.garment.set_channel(channel, True)
        self.participant.emphasise_choice(SIDES[index])

        def off() -> None:
            self.session.garment.set_channel(channel, False)
            self.participant.emphasise_choice(None)
            then()

        self.after(self.hold_s, off)

    def _accept(self) -> None:
        self.listen(self.participant.chosen, self._chosen)
        self.participant.accept_choice()

    def _early(self) -> None:
        self.session.log(
            "choice_pressed_early",
            origin="participant",
            detail=f"comparison {self.plan.comparison_index}; not counted (SPEC.md 10.8)",
        )

    def _chosen(self, side: str) -> None:
        chosen_channel = self.sequence[SIDES.index(side)]
        judgement = TEST_STRONGER if chosen_channel == self.plan.channel else REFERENCE_STRONGER
        self.session.files.write(
            "touchcal_compare",
            timestamp_iso=self.onset_iso,
            t_session_s=self._t_session_s,
            channel=self.plan.channel,
            reference_channel=self.plan.reference_channel,
            comparison_index=self.plan.comparison_index,
            pass_index=self.plan.pass_index,
            pair_index=self.plan.pair_index,
            order=self.plan.order,
            hold_s=self.hold_s,
            test_pressure_kpa=self.plan.test_pressure_kpa,
            reference_pressure_kpa=self.plan.reference_pressure_kpa,
            # Catch trials live in the estimation run since 23 Aug 2026 (SPEC.md 9).
            catch_trial=False,
            judgement=judgement,
            readjusted=self.readjust_if(judgement),
            valid_for_analysis=self.session.garment.per_channel_pressure,
        )
        self.session.garment.stop()
        self.forget(self.participant.chosen, self._chosen)
        self.listen(self.participant.choice_gap_elapsed, lambda: self.done(judgement))


# -- step 6: the preference selection ----------------------------------------------------


class PreferenceSelection(Trial):
    """Browse the candidate patterns and choose one (SPEC.md 9 step 6).

    The pressures are already set, at the calibrated level on every channel. Each candidate
    plays as the participant reaches it -- Previous and Next wrap round, so every one is
    reachable from every other -- and the play button chooses the one playing. The order is
    shuffled per session, so a position on the list is not a pattern (docs/LOG.md N7.C9).

    Which pattern was chosen is written to `touchcal_preference` and never displayed: in the
    participant-preferred condition it is the condition's pattern (SPEC.md 16).
    """

    def __init__(self, session, participant, experimenter, order: tuple[str, ...],
                 level_kpa: float | None):
        super().__init__(session, participant, experimenter)
        self.order = order
        self.level_kpa = level_kpa
        self.index = 0
        self.moves = 0
        self.visited: list[str] = []
        self.start_iso = ""
        self._t_session_s: float | None = None
        self._start_s = 0.0

    def start(self) -> None:
        self.index = 0
        self.moves = 0
        self.visited = []
        self.start_iso = self.session.clock.wall_iso()
        self._t_session_s = self.session.clock.t_session_s()
        self._start_s = self.session.clock.real_elapsed_s()
        self.listen(self.participant.adjust_pressed, self._pressed)
        self.listen(self.participant.adjust_confirmed, self._confirmed)
        self.participant.show_preference(self.index + 1, len(self.order))
        self._play()

    def _play(self) -> None:
        name = self.order[self.index]
        if name not in self.visited:
            self.visited.append(name)
        garment = self.session.garment
        garment.stop_pattern()
        garment.play_pattern(self.session.patterns[name])
        self.session.log("preference_playing", detail=f"position {self.index + 1}")

    def _pressed(self, action_value: str, _event_ms: int) -> None:
        step = -1 if Action(action_value) is Action.DECREASE else 1
        self.index = (self.index + step) % len(self.order)
        self.moves += 1
        self.participant.show_preference_position(self.index + 1, len(self.order))
        self._play()

    def _confirmed(self) -> None:
        chosen = self.order[self.index]
        self.session.files.write(
            "touchcal_preference",
            timestamp_iso=self.start_iso,
            t_session_s=self._t_session_s,
            presentation_order=";".join(self.order),
            chosen_pattern=chosen,
            chosen_position=self.index + 1,
            moves=self.moves,
            candidates_felt=";".join(self.visited),
            all_felt=len(self.visited) == len(self.order),
            level_kpa=self.level_kpa,
            duration_s=self.session.clock.real_elapsed_s() - self._start_s,
            valid_for_analysis=self.session.garment.per_channel_pressure,
        )
        self.session.log("preference_chosen", origin="participant")
        self.session.garment.stop_pattern()
        self.participant.show_blank()
        self.done(chosen)


# -- starting a touch delivery, SPEC.md 12.3 and 16 --------------------------------------


class DeliveryStart(Trial):
    """Start one condition's touch, looking the same on the experimenter's screen in all.

    **The experimenter screen is identical whatever the condition** (SPEC.md 16). Only the
    participant-preferred condition is self-started, so anything the experimenter saw about the
    self-start -- an instruction, a status, a "waiting for the participant" -- would name the
    condition. This trial shows one neutral instruction, `TOUCH_START_INSTRUCTION`, and no
    status, in every condition, and a test holds it to that. The caller chooses `self_start`
    from `Session.condition`; this trial never reads the condition.

    Both paths: the pressures are commanded first with every channel closed, then the warning
    cue (SPEC.md 10.5). Then either the pattern starts, or the participant is asked to start it
    (`screens.self_start`) and their press starts it with nothing inserted between (SPEC.md
    12.3). The cue comes before the prompt, so it adds nothing after the press.

    `self_start_latency_ms` runs from the window's key-press time to the moment the pattern's
    first device command is issued, and is written on that `pattern_start` row by the garment.
    The trial finishes with it, or with None when the touch was not self-started.
    """

    def __init__(self, session, participant, experimenter, delivery: Delivery,
                 self_start: bool):
        super().__init__(session, participant, experimenter)
        self.delivery = delivery
        self.self_start = self_start

    def start(self) -> None:
        self.session.garment.stop()
        self.instruct(TOUCH_START_INSTRUCTION)
        levels = self.delivery.pressure_kpa or {}
        self.ramp_then(levels, lambda: self.cue_then(self._cued))

    def _cued(self) -> None:
        if not self.self_start:
            self.session.garment.play_pattern(self.session.patterns[self.delivery.pattern_name])
            self.session.garment.advance()
            self.done(None)
            return
        self.listen(self.participant.message_confirmed, self._pressed)
        self.participant.show_message(SELF_START_SCREEN)

    def _pressed(self) -> None:
        garment = self.session.garment
        garment.play_pattern(
            self.session.patterns[self.delivery.pattern_name],
            pressed_at_real_s=self.participant.last_press_real_s,
        )
        latency_ms = garment.self_start_latency_ms
        self.participant.show_blank()
        self.session.log("self_started", origin="participant", detail=f"{latency_ms:.1f} ms")
        self.done(latency_ms)


# -- the result --------------------------------------------------------------------------


@dataclass(frozen=True)
class TouchCalibrationResult:
    """What Protocol B hands the intervention (SPEC.md 9, 12.2).

    Every condition's delivery is here, computed the same way in every session: calibration
    never differs between conditions (SPEC.md 16), so the one that is used is picked by the
    caller from `Session.condition`, with `for_condition`. None of this reaches either screen.
    The same numbers are in `touchcal_channels`, which is what a resumed session reads.

    - `sham`: the sham pattern, static, at P20 on every channel through its gain.
    - `ct_targeted` and `participant_preferred`: at the same level, the geometric mean of the
      two pleasantness settings, so the pattern is the only difference between them
      (docs/research/R31).

    `valid_for_analysis` is false in timing-only mode (SPEC.md 12.4), and whenever a fallback
    stood in for a measured value -- `targets_source` other than `fit`, or a `gain_sources`
    entry of `fallback_unit_gain` -- and when the calibration was `skipped`. The data says
    which.
    """

    run_index: int
    reference_channel: int
    p20_kpa: float
    p30_kpa: float
    p80_kpa: float
    targets_source: str
    match_level_kpa: float
    gains: dict[int, float]
    gain_sources: dict[int, str]
    pleasant_kpa: float
    preferred_pattern: str
    stage1_pass: bool
    # Ended early by the experimenter on a pilot rig (`TouchCalibration._skip`).
    skipped: bool
    valid_for_analysis: bool
    sham: Delivery
    ct_targeted: Delivery
    participant_preferred: Delivery

    def for_condition(self, condition: str) -> Delivery:
        return {
            "sham": self.sham,
            "ct_targeted": self.ct_targeted,
            "participant_preferred": self.participant_preferred,
        }[condition]


@dataclass(frozen=True)
class FitReady:
    """What the fit preview shows the experimenter (SPEC.md 11.1). Milestone 5 draws it.

    Emitted only while the preview is on, because it carries the participant's ratings.
    `fit` is None when the step 1 bracket left nothing to sample.
    """

    run_index: int
    points: tuple[tuple[float, float, bool], ...]  # (pressure kPa, rating %, catch trial)
    fit: maths.RatingFit | None
    r_squared: float | None
    residual_sd: float | None
    monotonic: bool | None
    stage1_pass: bool
    stage1_failures: tuple[str, ...]
    p20_kpa: float | None
    p30_kpa: float | None
    p80_kpa: float | None


# Where the targets and gains came from, as `touchcal_channels` records it.
FROM_FIT = "fit"
FROM_BRACKET_LINE = "bracket_line"
FROM_DEVICE_RANGE = "device_range"
GAIN_REFERENCE = "reference"
GAIN_MATCHED = "matched"
GAIN_FALLBACK = "fallback_unit_gain"
GAIN_SKIPPED = "skipped_unit_gain"


# -- Protocol B in full ------------------------------------------------------------------


class TouchCalibration(Procedure):
    """Protocol B, steps 1 to 6 and the evenness check (SPEC.md 9). Finishes with the result.

    Identical in every condition and every session (SPEC.md 16): nothing here reads the
    condition. Each step is a trial run by `run_trial`, so an interruption repeats the trial it
    interrupted and nothing already written is touched (docs/LOG.md N7.1).

    **The stage-1 gate** (SPEC.md 9) is decided before step 3, because every later step is
    built on the fit. A fit fails when it is flat, non-monotonic or noisy, and also when the
    targets it gives cannot be delivered: not invertible, at or below zero, or a pleasantness
    window left empty once held inside [0, ceiling]. A failing fit is put to the experimenter,
    and so is every fit when the fit preview is on (SPEC.md 11.1). Every run keeps its fit row;
    a re-run marks the discarded one `superseded`.

    - A usable estimate can be accepted, flagged, or re-run.
    - An unusable one can only be re-run until `fit_preview.max_reruns` is used up. Then the
      experimenter can accept, which continues on a **fallback** -- the targets read off the
      line through the participant's own step 1 settings, or off the device's range if those
      settings left no range -- or abort the session. A fallback is logged, recorded in
      `touchcal_channels.targets_source`, and makes the calibration `valid_for_analysis: false`.

    **Timing-only mode** (SPEC.md 12.4). On a device that cannot set pressure per channel,
    every step runs with its real interaction and duration, every row is written
    `valid_for_analysis: false`, and the gate never stops the session: an unusable estimate
    goes straight to the fallback, because the pressures are not delivered anyway.

    **The skip, on a pilot rig only** (`GarmentController.pilot_rig`: the mock and the
    prototype). After `pilot_skip_min_ratings` estimation ratings the experimenter can end the
    calibration and move on to the next event; see `_skip`. Never on the study garment.

    **Re-calibration** (S, 15 Oct 2026, docs/LOG.md N7.F12a1). At any point the experimenter
    may rebalance the channels (steps 3 and 4 and the evenness check again, then on; once a
    fit is accepted) or restart the calibration (a new run from step 1). The session runner
    owns the choice and its record; this takes the path (`recalibrate`). During the
    intervention the runner runs this same procedure again, from the path chosen
    (`recalibrate_on_start`), so its runs, passes and counts go on from where the calibration
    in use left them, and step 6 is not asked again; each finish writes a new set of
    `touchcal_channels`.

    `fit_ready` carries the estimate to the fit preview, when the preview is on.
    """

    fit_ready = Signal(object)
    # What it can offer for a re-calibration has changed (`recalibration_offers`).
    recalibration_changed = Signal()

    def __init__(self, rig, resumed: ResumeState | None = None) -> None:
        super().__init__(rig)
        config = self.session.config
        self.touch = config.study1["touch_calibration"]
        self.pattern_config = config.study1["patterns"]
        self.preview = bool(config.study1["fit_preview"]["enabled"]) and (
            TOUCH_CALIBRATION in config.study1["fit_preview"]["procedures"]
        )
        self.max_reruns = int(config.study1["fit_preview"]["max_reruns"])
        garment = self.session.garment
        self.real = garment.per_channel_pressure
        self.valid = self.real
        self.ceiling_kpa = garment.limits.pressure_ceiling_kpa
        # Stage boundary (CLAUDE.md). The next presentation's ramp runs inside the fixed
        # estimation window; one that outlasted it would delay the cue by an amount that
        # grows with the pressure, and a catch trial, with no ramp, would never be delayed:
        # the pause would tell the participant what is coming (LOG N7.F14e). On the mock
        # garment nobody feels the touch and nothing recorded is data, so a demonstration may
        # run it shorter (`demo.estimation_window_mock_s`).
        if garment.worn:
            window_s = float(self.touch["estimation_window_s"])
            # A ramp re-checks the rate limit once a tick, so it can end up to a tick late.
            slowest_s = self.ceiling_kpa / garment.limits.pressure_rate_max_kpa_s + float(
                config.hardware["adjustment"]["tick_interval_s"]
            )
            assert window_s >= slowest_s, (
                f"study1.yaml: touch_calibration.estimation_window_s ({window_s} s) is shorter "
                f"than the slowest ramp, the ceiling at the rate limit plus a tick "
                f"({slowest_s:.2f} s)"
            )
        self.reference = int(self.touch["reference_channel"])
        self.others = tuple(c for c in garment.channels() if c != self.reference)
        assert self.reference in garment.channels(), (
            f"touch_calibration.reference_channel {self.reference} is not a channel of "
            f"{garment.driver_name}"
        )
        self.fit_form = self.touch["estimation_fit"]
        self.criteria = maths.Stage1Criteria.from_config(self.touch["stage1"])
        self.fixed_pattern = self.session.patterns[self.pattern_config["fixed_ct_pattern"]]
        self.derived_pct = tuple(float(p) for p in self.touch["derived_pct"])
        low_pct, high_pct = (float(p) for p in self.touch["pleasantness_range_anchors"])
        sham_pct = float(self.touch["sham_target_intensity_pct"])
        # Stage boundary (CLAUDE.md): everything the result needs must be read off the fit.
        assert {low_pct, high_pct, sham_pct} <= set(self.derived_pct), (
            "study1.yaml: pleasantness_range_anchors and sham_target_intensity_pct must be "
            "among touch_calibration.derived_pct"
        )
        self.low_pct, self.high_pct, self.sham_pct = low_pct, high_pct, sham_pct

        # The session's numbering, which a resumed session continues from the files it
        # resumes (`resumed`, SPEC.md 15), so the chain never has two runs, evenness questions
        # or comparisons of one number (docs/LOG.md N7.F12a1).
        self.run_index = 0 if resumed is None else resumed.touchcal_runs
        self.reruns = 0
        self._run_warning: str | None = None
        self.rebalances = 0
        # Numbers `touchcal_evenness.check_index`: a rebalance or a re-calibration asks again.
        self.evenness_checks = 0 if resumed is None else resumed.evenness_checks
        self.comparisons = 0 if resumed is None else resumed.comparisons
        # Re-calibration (docs/LOG.md N7.F12a1). `step_name` is where the calibration is, as
        # the runner logs it; `_entry`, the path and reason a re-calibration during the
        # intervention starts with, and `_kept_preference` the step 6 choice it keeps;
        # `_used_run_index`, the run whose result governed the touch, never superseded since
        # it was used.
        self.step_name = STEP_TRAINING
        self._entry: tuple[str, str] | None = None
        self._kept_preference: str | None = None
        self._used_run_index: int | None = None
        # The stage-1 reasons of the fit accepted, for its row again if a restart supersedes it.
        self._accepted_reasons: tuple[str, ...] = ()
        self.fit: maths.RatingFit | None = None
        self.raw_targets: dict[float, float | None] = {}
        self.targets: dict[float, float] = {}
        self.targets_clamped: tuple[float, ...] = ()
        self.targets_source = FROM_FIT
        self.inverse: maths.RatingFit | None = None
        self.match_level_kpa = 0.0
        self.gains: dict[int, float] = {self.reference: 1.0}
        self.gain_sources: dict[int, str] = {self.reference: GAIN_REFERENCE}
        self.match_settings: dict[int, list[float]] = {}
        self.match_passes: dict[int, int] = {}
        # None until step 5 sets it: a measured 0 kPa is a level, not the absence of one.
        self.pleasant_kpa: float | None = None
        self.stage1_pass = False
        # The stage-1 reasons of a fit put to the experimenter and not yet accepted or re-run;
        # None when no decision is pending.
        self.pending_reasons: tuple[str, ...] | None = None

        # Counted within the current run (`len(self.estimates)`), at least 1 (config.py).
        self.skip_min_ratings = int(self.touch["pilot_skip_min_ratings"])
        self.skipped = False
        # This run's (plan, rating) pairs; reset by `_start_run`.
        self.estimates: list[tuple[maths.EstimationPlan, float]] = []

    def connect_actions(self) -> None:
        self.experimenter.skip_calibration_requested.connect(self._skip)

    def disconnect_actions(self) -> None:
        self.experimenter.skip_calibration_requested.disconnect(self._skip)
        self.experimenter.set_actions_enabled(skip_calibration=False)

    # -- re-calibration, docs/LOG.md N7.F12a1 ---------------------------------------------
    # The session runner owns it: what is offered, the choice, its record, and the
    # interruption it ends or makes. This procedure says what it can offer and takes the path.

    def recalibration_offers(self) -> tuple[bool, bool]:
        """(rebalance, restart) as the calibration stands: Rebalance channels once a fit is
        accepted, since steps 3 and 4 are built on its targets; Restart calibration once a run
        has begun. `recalibration_changed` says when this changes."""
        return bool(self.targets), self.run_index > 0

    def recalibrate_on_start(self, choice: str, reason: str, preference: str) -> None:
        """Run again, from `choice`, when next started: a re-calibration during the
        intervention, which keeps the touch calibration's `preference` (S, via the integrator,
        15 Oct 2026): step 6 is not asked again, so the participant-preferred condition's
        pattern cannot change mid-intervention."""
        assert not self.running, "a re-calibration set up on a calibration still running"
        assert choice != REBALANCE or self.targets, "a rebalance with no targets"
        self._entry = (choice, reason)
        self._kept_preference = preference

    def recalibrate(self, choice: str, reason: str) -> None:
        """Take `choice` now, once the runner has zeroed the garment and abandoned the step in
        progress (`Interruptions.take_over`) or ended the stop unrestored
        (`end_without_restore`). Nothing of the abandoned step goes on: its trial and timer
        went with it, its repeat is never run, and a go it waited for is withdrawn. The path
        starts as any run of it does, introduced to the participant (docs/LOG.md N7.F11c1) and
        with its own cue before the garment starts. Identical in every condition: nothing
        here reads it (SPEC.md 16)."""
        # Stage boundary (CLAUDE.md): the runner offers only what this said it could take.
        assert self.running and self.rig.interruptions.active is None, (
            f"a {choice} while {self.rig.interruptions.active} is in force"
        )
        rebalance, restart = self.recalibration_offers()
        assert rebalance if choice == REBALANCE else restart, f"{choice} was not offered"
        self.on_proceed(None)
        self.experimenter.set_status("")
        self._take(choice, reason)

    def _take(self, choice: str, reason: str) -> None:
        """The path chosen. A rebalance is the N7.C8 path: steps 3 and 4 for every test
        channel, then the evenness check, then on; a pleasantness level already set stands
        (`_after_equalisation`)."""
        assert choice in (REBALANCE, RESTART), choice
        if choice == REBALANCE:
            self._match_all(self._equalise_all)
        else:
            self._restart(reason)

    def _restart(self, reason: str) -> None:
        """A new run from step 1; the scale training is not given again (`begin`).

        A run never used is kept, as a re-run keeps it (SPEC.md 11.1): a fit awaiting the
        experimenter's decision gets its row, `superseded`; an accepted one gets a second row,
        the same but `superseded`, since its first cannot be rewritten; a run stopped before
        its fit has no fit row, and its per-step rows show how far it got. The run whose
        calibration governed the touch is not superseded: `touchcal_channels` says when it did.
        Everything built on the run is discarded: targets, gains and any pleasantness level.
        """
        rerun_reason = f"{RERUN_RECALIBRATION}: {reason}"
        self.experimenter.hide_fit_preview()
        if self.pending_reasons is not None:
            self._write_fit(superseded=True, reasons=self.pending_reasons,
                            rerun_reason=rerun_reason)
        elif self.inverse is not None and self.run_index != self._used_run_index:
            self._write_fit(superseded=True, reasons=self._accepted_reasons,
                            rerun_reason=rerun_reason)
        self.pending_reasons = None
        self.inverse = None
        self.targets = {}
        self.targets_source = FROM_FIT
        self.match_level_kpa = 0.0
        self.gains = {self.reference: 1.0}
        self.gain_sources = {self.reference: GAIN_REFERENCE}
        self.match_settings = {}
        self.match_passes = {}
        self.pleasant_kpa = None
        self.stage1_pass = False
        self.valid = self.real
        self.skipped = False
        self._start_run()

    # -- the experimenter's skip, on a pilot rig only ----------------------------------

    def _offer_skip(self) -> None:
        """Offer the skip once `pilot_skip_min_ratings` ratings are in, on a pilot rig only.

        S, 5 Oct 2026: with the mock or the prototype, the experimenter can move on after a
        few ratings; with the study garment it must be impossible. The button is never shown
        there, and `_skip` asserts it besides, so a hidden button is not the only guard.
        """
        if self.session.garment.pilot_rig and len(self.estimates) >= self.skip_min_ratings:
            self.experimenter.set_actions_enabled(skip_calibration=True)

    def _skip(self) -> None:
        """End the calibration now, on what it has, recorded as skipped (docs/LOG.md N7.F8b).

        Targets come from an accepted fit if there is one, else from the fallback line through
        this run's step 1 settings -- the skip is offered only once this run has its own
        ratings, so never on an earlier run's bracket. A fit awaiting the experimenter's
        decision keeps its `touchcal_fit` row, written superseded because it was not accepted,
        and its verdict does not become the calibration's. A channel not yet matched is
        delivered at the reference's pressure; a level not yet set is the geometric mean of P30
        and P80; and with no preference made, the participant-preferred condition uses the
        fixed pattern. Every `touchcal_channels` row says `skipped` and is not valid for
        analysis, so a skipped calibration can never pass for a full one. Identical in every
        condition (SPEC.md 16).
        """
        garment = self.session.garment
        # Stage boundary (CLAUDE.md): the study garment never skips a calibration. Asserted
        # here, where the skip takes effect, and not only by the button's absence.
        assert garment.pilot_rig, (
            f"{garment.driver_name} is the study garment: touch calibration cannot be skipped"
        )
        answered = len(self.estimates)
        assert answered >= self.skip_min_ratings, (
            f"a skip after {answered} ratings in run {self.run_index}; it is offered after "
            f"{self.skip_min_ratings}"
        )
        assert self.rig.interruptions.active is None, "a skip while the session is interrupted"
        self._halt()
        garment.stop()
        # Whatever the cancelled trial had up is taken down, as at the end of any step.
        self.participant.show_blank()
        self.experimenter.set_status("")
        self.experimenter.hide_fit_preview()
        self.experimenter.refresh()
        self.skipped = True
        self.valid = False
        self.session.log(
            "touchcal_skipped", origin="experimenter", severity="warning",
            detail=f"run {self.run_index}, after {answered} ratings; not valid for analysis",
        )
        if self.pending_reasons is not None:
            self._write_fit(superseded=True, reasons=self.pending_reasons)
            self.pending_reasons = None
        if self.inverse is None:
            # No fit was accepted, so no stage-1 verdict is the calibration's.
            self.stage1_pass = False
            self._fallback(("skipped",))
            self._set_targets()
        for channel in self.others:
            if channel not in self.gains:
                self.gains[channel] = 1.0
                self.gain_sources[channel] = GAIN_SKIPPED
        if self.pleasant_kpa is None:
            self.pleasant_kpa = maths.geometric_mean(
                [self.targets[self.low_pct], self.targets[self.high_pct]]
            )
        # A re-calibration during the intervention keeps the preference it had.
        self._finish_calibration(self._kept_preference
                                 or self.pattern_config["fixed_ct_pattern"])

    # -- steps 1 and 2 -----------------------------------------------------------------

    def begin(self) -> None:
        self.session.set_phase(TOUCH_CALIBRATION)
        if self._entry is not None:
            # A re-calibration during the intervention: straight to the path chosen, the
            # garment already at zero (`recalibrate_on_start`).
            (choice, reason), self._entry = self._entry, None
            self._take(choice, reason)
            return
        # SPEC.md 10.6, Bilaga 1 3.9: the training for the touch scales, during touch
        # calibration, before step 1 -- whose adjustments already ask for the intensity scale's
        # anchors, so that is the scale's first use. The touch scales are the touch block's
        # repeated ones, in their order, that have a training sentence; `TouchBlock` asserts
        # none is left untrained. The garment is off for it. A re-run of steps 1 and 2 finds it
        # already given.
        touch_scales = [
            scale for scale in self.session.config.study1["touch_block"]["repeated_scales"]
            if scale in self.session.trained_scales
        ]
        self.session.garment.stop()
        self.train_then(touch_scales, self._start_run)

    def _start_run(self) -> None:
        self.run_index += 1
        self.step_name = STEP_BRACKET
        self.recalibration_changed.emit()
        # A warning about the run a re-run discards is not about the one now starting.
        if self._run_warning is not None:
            self.experimenter.clear_warning(self._run_warning)
            self._run_warning = None
        self.session.log("touch_calibration_run", detail=f"run {self.run_index}")
        self.anchor_settings: dict[float, list[float]] = {}
        self.fit = None
        self.raw_targets = {}
        self.targets_clamped = ()
        self.estimates = []
        self.catch_fraction: float | None = None
        self.catch_flag = False
        # A new run has no ratings of its own yet, so nothing to skip on.
        self.experimenter.set_actions_enabled(skip_calibration=False)
        plans = list(anchor_plans(self.session.config, self.run_index))
        self._anchor_count = len(plans)
        self._introduce(INTRO_BRACKET, lambda: self._anchor(plans))

    def _introduce(self, key: str, then: Callable[[], None], readjust: bool = False) -> None:
        """`Procedure.introduce`, with the experimenter told which step comes: `touchcal_<key>`,
        or for a channel set again inside step 4 (`readjust`), step 4's own line."""
        instruction = INTRO_READJUST_INSTRUCTION if readjust else f"{INTRO_INSTRUCTION}{key}"
        self.introduce(key, self.instruction_text(instruction), then)

    def _anchor(self, plans: list[AdjustmentPlan]) -> None:
        if not plans:
            self._estimate()
            return
        plan = plans[0]

        def adjusted(kpa: float) -> None:
            self.session.garment.stop()
            self.anchor_settings.setdefault(plan.anchor_percent, []).append(kpa)
            self._anchor(plans[1:])

        def on(_) -> None:
            self.session.garment.set_channel(plan.channel, True)
            self.run_trial(lambda: Adjustment(*self._windows(), plan), adjusted)
        # Which anchor, so the experimenter can tell the two apart (review of N7.F16).
        self.experimenter.set_instruction(self.instruction_text(
            "touchcal_bracket", index=self._anchor_count - len(plans) + 1,
            count=self._anchor_count,
            target=self.experimenter.text["terms"]["anchor_targets"][plan.target_key]))
        self.run_trial(lambda: Cue(*self._windows()), on)

    def _estimate(self) -> None:
        self.step_name = STEP_ESTIMATION
        percents = sorted(self.anchor_settings)
        # The bracket only sets where the run samples, and a setting can be zero, so the
        # settings at one anchor are averaged arithmetically here.
        low = sum(self.anchor_settings[percents[0]]) / len(self.anchor_settings[percents[0]])
        high = sum(self.anchor_settings[percents[-1]]) / len(self.anchor_settings[percents[-1]])
        self.bracket = (low, high)
        if not maths.bracket_is_usable(low, high, self.fit_form):
            self.session.log(
                "bracket_unusable",
                severity="warning",
                detail=f"{low:.1f}--{high:.1f} kPa cannot be sampled on a {self.fit_form} axis",
            )
            if self.real:
                self._gate((BRACKET_UNUSABLE,), usable=False)
                return
            # Timing-only: the pressures are not delivered anyway (SPEC.md 12.4). Sample the
            # device's whole range so the run still takes its real time.
            self.bracket = self._device_range()
        amplitudes = maths.estimation_amplitudes(
            *self.bracket, int(self.touch["estimation_n_amplitudes"]), self.fit_form
        )
        n_catch = maths.catch_trial_count(
            len(amplitudes), float(self.touch["catch_trial_fraction"])
        )
        plans = list(maths.estimation_plans(amplitudes, n_catch, self.session.rng))
        self._introduce(
            INTRO_ESTIMATION,
            # The whole window before the first presentation too, counted from its own start:
            # a first one cued as soon as its ramp ended would give a catch trial away by its
            # pause (spec-review, LOG N7.F14e).
            lambda: self._present(plans, off_s=float(self.touch["estimation_window_s"]),
                                  stopped_s=None),
        )

    def _device_range(self) -> tuple[float, float]:
        return (float(self.session.config.hardware["adjustment"]["tap_step_kpa"]),
                self.ceiling_kpa)

    def _present(self, plans: list[maths.EstimationPlan], off_s: float,
                 stopped_s: float | None) -> None:
        """The next presentation, `off_s` after the last one's stop at `stopped_s`."""
        if not plans:
            self._fit()
            return
        # "x/N answered" (S, 5 Oct 2026): the same count in every condition, and never what
        # was answered (SPEC.md 16).
        self.experimenter.set_instruction(
            self.experimenter.text["instructions"]["touchcal_estimation"].format(
                answered=len(self.estimates), total=len(self.estimates) + len(plans)
            )
        )
        self.experimenter.refresh()

        def presented(outcome) -> None:
            plan, rating, stopped_s = outcome
            self.estimates.append((plan, rating))
            self._offer_skip()
            if len(plans) == 1:
                self._fit()
                return
            self._present(plans[1:], float(self.touch["estimation_window_s"]), stopped_s)

        # The last stop anchors the first attempt only: one repeated after an interruption
        # waits the whole interval again from its own start, as a repeated wait did.
        anchors = [stopped_s]

        self.run_trial(
            lambda: EstimationPresentation(
                *self._windows(), plans[0], self.reference, self.run_index, off_s,
                anchors.pop() if anchors else None,
            ),
            presented,
        )

    def _fit(self) -> None:
        rated = [(plan.pressure_kpa, rating) for plan, rating in self.estimates
                 if not plan.catch_trial]
        catches = [rating for plan, rating in self.estimates if plan.catch_trial]
        fit = maths.fit_ratings([p for p, _ in rated], [r for _, r in rated], self.fit_form)
        self.fit = fit
        self.raw_targets = {pct: fit.invert(pct) for pct in self.derived_pct}
        held, target_reasons, self.targets_clamped = maths.usable_targets(
            self.raw_targets, self.sham_pct, self.low_pct, self.high_pct, self.ceiling_kpa
        )
        reasons = maths.stage1_failures(fit, self.criteria)
        reasons += tuple(r for r in target_reasons if r not in reasons)
        self.catch_fraction = maths.catch_felt_fraction(
            catches, float(self.touch["catch_felt_min_pct"])
        )
        self.catch_flag = self.catch_fraction is not None and self.catch_fraction > float(
            self.touch["catch_felt_warn_fraction"]
        )
        # Logged when computed, so a crash before the decision loses nothing the estimate
        # rows could not also rebuild.
        verdict = f"fails: {', '.join(reasons)}" if reasons else "passes"
        self.session.log(
            "touchcal_fit",
            severity="warning" if reasons else "info",
            detail=f"run {self.run_index}: a={fit.intercept:.3f} b={fit.slope:.3f} "
            f"r2={fit.r_squared:.3f} sd={fit.residual_sd:.2f} rho={fit.spearman_rho:.3f} "
            f"span={fit.span_vas:.1f}; stage 1 {verdict}",
        )
        if self.targets_clamped:
            self.session.log(
                "targets_clamped", severity="warning",
                detail="held inside [0, ceiling]: "
                + ", ".join(f"p{pct:g}" for pct in self.targets_clamped),
            )
        if self.catch_flag:
            felt = round(self.catch_fraction * len(catches))
            self.session.log(
                "catch_trials_felt", severity="warning",
                detail=f"{felt} of {len(catches)} catch trials felt",
            )
            self._run_warning = self.experimenter.text["warnings"]["catch_trials_felt"].format(
                value=f"{felt}/{len(catches)}"
            )
            self.experimenter.set_warning(self._run_warning)
        self._gate(reasons, usable=held is not None)

    def _gate(self, reasons: tuple[str, ...], usable: bool) -> None:
        self.stage1_pass = not reasons
        self.pending_reasons = reasons
        if self.preview:
            self.fit_ready.emit(self._fit_ready(reasons))
        if self.preview or (reasons and self.real):
            self._decide(usable, reasons)
        else:
            self._accept(reasons, usable)

    def _fit_ready(self, reasons: tuple[str, ...]) -> FitReady:
        fit = self.fit
        return FitReady(
            run_index=self.run_index,
            points=tuple((p.pressure_kpa, r, p.catch_trial) for p, r in self.estimates),
            fit=fit,
            r_squared=fit.r_squared if fit else None,
            residual_sd=fit.residual_sd if fit else None,
            monotonic=fit.monotonic if fit else None,
            stage1_pass=not reasons,
            stage1_failures=reasons,
            p20_kpa=self.raw_targets.get(self.sham_pct),
            p30_kpa=self.raw_targets.get(self.low_pct),
            p80_kpa=self.raw_targets.get(self.high_pct),
        )

    def _decide(self, usable: bool, reasons: tuple[str, ...]) -> None:
        """Put the estimate to the experimenter: accept it, or re-run steps 1 and 2.

        Every instruction says truthfully what each choice will do from here.
        """
        self.step_name = STEP_FIT_DECISION
        terms = self.experimenter.text["terms"]["stage1"]
        value = ", ".join(terms[r] for r in reasons)
        exhausted = self.reruns >= self.max_reruns
        if not reasons:
            instruction = "touchcal_fit_review"
        elif usable:
            instruction = "touchcal_stage1_failed"
        elif exhausted:
            instruction = "touchcal_stage1_exhausted"
        else:
            instruction = "touchcal_stage1_unusable"

        def decided(outcome) -> None:
            name, args = outcome
            # Only what is offered below can arrive, so nothing here is refused (review of
            # N7.F16: a refused press put the same estimate up again with nothing to say why).
            assert name in actions, f"{name} was not offered"
            self.experimenter.hide_fit_preview()
            if name == RERUN:
                self._rerun(reasons, args[0] if args else "")
            else:
                self._accept(reasons, usable)

        # Only the choices that will be taken are offered (review of N7.F16): no Accept while
        # the estimate cannot be used and re-runs remain, no Re-run once they are used up, and
        # the fallback then on a button that says it is one.
        window = self.experimenter
        if usable or not reasons:
            actions = {ACCEPT: window.fit_accepted}
            if not exhausted:
                actions[RERUN] = window.fit_rerun_requested
            alternative = None
        elif exhausted:
            actions, alternative = {ACCEPT: window.alternative_requested}, FIT_FALLBACK
        else:
            actions, alternative = {RERUN: window.fit_rerun_requested}, None

        self.run_trial(
            lambda: ExperimenterChoice(
                *self._windows(),
                actions,
                instruction,
                show=self.rig.show_between,
                alternative=alternative,
                value=value,
            ),
            decided,
        )

    def _rerun(self, reasons: tuple[str, ...], reason: str) -> None:
        self.reruns += 1
        # Only a re-run chosen from the fit preview counts as one (SPEC.md 11.1); a stage-1
        # re-run with the preview off is its own event.
        if self.preview:
            self.session.fit_preview_reruns += 1
        else:
            self.session.log(
                "touchcal_stage1_rerun", origin="experimenter", severity="warning",
                detail=f"run {self.run_index}: {reason}",
            )
        self.pending_reasons = None
        self._write_fit(superseded=True, reasons=reasons, rerun_reason=reason)
        self._start_run()

    def _write_fit(
        self, superseded: bool, reasons: tuple[str, ...], rerun_reason: str = ""
    ) -> None:
        """Every run's fit row, including one with no fit at all (SPEC.md 11.1)."""
        fit = self.fit
        raw = self.raw_targets
        extrapolated = [
            f"p{pct:g}" for pct, kpa in sorted(raw.items()) if fit and fit.extrapolated(kpa)
        ]
        self.session.files.write(
            "touchcal_fit",
            timestamp_iso=self.session.clock.wall_iso(),
            t_session_s=self.session.clock.t_session_s(),
            channel=self.reference,
            run_index=self.run_index,
            superseded=superseded,
            rerun_reason=rerun_reason,
            fit_form=self.fit_form,
            intercept=fit.intercept if fit else None,
            slope=fit.slope if fit else None,
            r_squared=fit.r_squared if fit else None,
            residual_sd=fit.residual_sd if fit else None,
            monotonic=fit.monotonic if fit else None,
            spearman_rho=fit.spearman_rho if fit else None,
            span_vas=fit.span_vas if fit else None,
            stage1_pass=not reasons,
            stage1_failures=";".join(reasons),
            bracket_min_kpa=fit.bracket_min_kpa if fit else self.bracket[0],
            bracket_max_kpa=fit.bracket_max_kpa if fit else self.bracket[1],
            p20_kpa=raw.get(self.sham_pct),
            p30_kpa=raw.get(self.low_pct),
            p80_kpa=raw.get(self.high_pct),
            extrapolated=",".join(extrapolated),
            targets_clamped=",".join(f"p{pct:g}" for pct in self.targets_clamped),
            catch_felt_fraction=self.catch_fraction,
            catch_flag=self.catch_flag,
            valid_for_analysis=self.real,
        )

    def _accept(self, reasons: tuple[str, ...], usable: bool) -> None:
        self.pending_reasons = None
        self._accepted_reasons = reasons
        self._write_fit(superseded=False, reasons=reasons)
        if usable:
            self.inverse = self.fit
            self.targets_source = FROM_FIT
        else:
            self._fallback(reasons)
        self._set_targets()
        self.recalibration_changed.emit()
        self._match_all(self._equalise_all)

    def _set_targets(self) -> None:
        """Every target, and the match level, off whichever line `inverse` holds."""
        self.targets = {
            pct: maths.clamp(self.inverse.invert(pct), self.ceiling_kpa)
            for pct in self.derived_pct
        }
        # docs/research/R31: matched, and checked, at P50 -- inside the range every condition
        # is delivered in, so the gain is measured where it is used.
        self.match_level_kpa = maths.clamp(
            self.inverse.invert(float(self.touch["channel_match_pct"])), self.ceiling_kpa
        )

    def _fallback(self, reasons: tuple[str, ...]) -> None:
        """Targets that are not the fit, stated as such (the procedure's docstring)."""
        # The configured anchors, not this run's settings: a skip at the start of a re-run
        # comes here before the run has set any (`_skip`).
        percents = sorted(float(p) for p in self.touch["anchors_pct"])
        if maths.bracket_is_usable(*self.bracket, self.fit_form):
            self.targets_source, (low, high) = FROM_BRACKET_LINE, self.bracket
        else:
            self.targets_source, (low, high) = FROM_DEVICE_RANGE, self._device_range()
        self.inverse = maths.line_through_anchors(
            [(percents[0], low), (percents[-1], high)], self.fit_form
        )
        self.valid = False
        self.session.log(
            "touchcal_fallback", severity="warning",
            detail=f"run {self.run_index}: {', '.join(reasons)}; targets read off the "
            f"{self.targets_source.replace('_', ' ')}, not valid for analysis",
        )

    # -- step 3 ------------------------------------------------------------------------

    def _match_all(self, then: Callable[[], None]) -> None:
        self.step_name = STEP_MATCH
        self._introduce(
            INTRO_MATCH, lambda: self._match_each(list(self.others), then)
        )

    def _match_each(self, channels: list[int], then: Callable[[], None]) -> None:
        if not channels:
            then()
            return
        self._match_channel(channels[0], lambda: self._match_each(channels[1:], then))

    def _channel_instruction(self, key: str, channel: int) -> None:
        """A step 3 or 4 instruction, with which of the other channels this is."""
        self.experimenter.set_instruction(
            self.experimenter.text["instructions"][key].format(
                channel=channel, index=self.others.index(channel) + 1, count=len(self.others)
            )
        )

    def _match_channel(self, channel: int, then: Callable[[], None], zero_retries: int = 0,
                       readjust: bool = False):
        """Both start points, then the gain. A 0 kPa setting is matched again, not guessed.

        `readjust` is a match repeated inside step 4, for a channel that still felt different,
        which the experimenter is told as such rather than as step 3 again.
        """
        self.step_name = STEP_COMPARE if readjust else STEP_MATCH
        self.match_passes[channel] = self.match_passes.get(channel, 0) + 1
        directions = list(self.touch["start_directions"])
        plans = [
            AdjustmentPlan(
                stage=MATCH_STAGE,
                channel=channel,
                target_key=MATCH_TARGET,
                adjustment_index=index + 1,
                start_direction=directions[index % len(directions)],
                range_min_kpa=0.0,
                range_max_kpa=self.ceiling_kpa,
                reference_channel=self.reference,
                # Equal until shown otherwise: the gain the design assumes is 1.
                expected_kpa=self.match_level_kpa,
                run_index=self.run_index,
                pass_index=self.match_passes[channel],
            )
            for index in range(int(self.touch["channel_match_adjustments"]))
        ]
        settings: list[float] = []
        self._channel_instruction(READJUST_INSTRUCTION if readjust else MATCH_INSTRUCTION,
                                  channel)

        def next_plan() -> None:
            if len(settings) == len(plans):
                matched(settings)
                return
            plan = plans[len(settings)]

            def adjusted(kpa: float) -> None:
                self.session.garment.stop()
                settings.append(kpa)
                next_plan()

            self.run_trial(
                lambda: Ramp(*self._windows(), {self.reference: self.match_level_kpa}),
                lambda _: self.run_trial(
                    lambda: Cue(*self._windows()),
                    lambda _: self.run_trial(
                        lambda: MatchAdjustment(*self._windows(), plan), adjusted
                    ),
                ),
            )

        def matched(values: list[float]) -> None:
            self.match_settings[channel] = list(values)
            if all(kpa > 0 for kpa in values) and self.match_level_kpa > 0:
                self.gains[channel] = maths.gain(self.match_level_kpa, values)
                self.gain_sources[channel] = GAIN_MATCHED
                self.session.log(
                    "channel_gain", detail=f"channel {channel}: {self.gains[channel]:.3f}"
                )
                then()
                return
            # A setting of 0 kPa has no gain: the channel felt as strong as the reference with
            # nothing on it, which the design cannot represent. Matched again, then asked.
            self.session.log(
                "gain_undefined", severity="warning",
                detail=f"channel {channel}, pass {self.match_passes[channel]}: a 0 kPa setting",
            )
            if zero_retries < int(self.touch["channel_match_zero_retries"]):
                self._match_channel(channel, then, zero_retries + 1, readjust)
            else:
                self._ask_about_gain(channel, then, readjust)

        next_plan()

    def _ask_about_gain(self, channel: int, then: Callable[[], None], readjust: bool) -> None:
        def decided(outcome) -> None:
            name, _ = outcome
            if name == REBALANCE:
                # Back to matching after a wait on the experimenter: introduced again.
                self._introduce(
                    INTRO_MATCH,
                    lambda: self._match_channel(channel, then, readjust=readjust),
                    readjust=readjust,
                )
                return
            # The experimenter's explicit choice, recorded as a fallback and never as a match.
            self.gains[channel] = 1.0
            self.gain_sources[channel] = GAIN_FALLBACK
            self.valid = False
            self.session.log(
                "gain_fallback", origin="experimenter", severity="warning",
                detail=f"channel {channel}: delivered at the reference's pressure (gain 1); "
                "not valid for analysis",
            )
            then()

        self.run_trial(
            lambda: ExperimenterChoice(
                *self._windows(),
                {REBALANCE: self.experimenter.rebalance_requested,
                 PROCEED: self.experimenter.alternative_requested},
                "touchcal_gain_undefined",
                show=self.rig.show_between,
                alternative=GAIN_FALLBACK_CONTROL,
                channel=channel,
            ),
            decided,
        )

    # -- step 4 ------------------------------------------------------------------------

    def _equalise_all(self) -> None:
        self.step_name = STEP_COMPARE
        self._introduce(
            INTRO_COMPARE,
            lambda: self._equalise(list(self.others), self._after_equalisation),
        )

    def _equalise(self, channels: list[int], then: Callable[[], None]) -> None:
        if not channels:
            then()
            return
        self._check_channel(channels[0], 1, lambda: self._equalise(channels[1:], then))

    def _check_channel(self, channel: int, pass_index: int, then: Callable[[], None]) -> None:
        """docs/research/R33: pairs in both orders, flagged only on an order-free winner."""
        pairs_to_flag = int(self.touch["equalisation_pairs_to_flag"])
        max_passes = 1 + int(self.touch["equalisation_readjust_max_passes"])
        judgements: list[str] = []
        self._channel_instruction(EQUALISE_INSTRUCTION, channel)

        def pair(pair_index: int) -> None:
            orders = [TEST_FIRST, REFERENCE_FIRST]
            self.session.rng.shuffle(orders)
            compare(pair_index, orders)

        def compare(pair_index: int, orders: list[str]) -> None:
            if not orders:
                pair_done(pair_index)
                return
            self.comparisons += 1
            plan = ComparisonPlan(
                channel=channel,
                reference_channel=self.reference,
                comparison_index=self.comparisons,
                order=orders[0],
                pair_index=pair_index,
                pass_index=pass_index,
                test_pressure_kpa=maths.clamp(
                    self.match_level_kpa * self.gains[channel], self.ceiling_kpa
                ),
                reference_pressure_kpa=self.match_level_kpa,
            )
            last = pair_index == pairs_to_flag and len(orders) == 1

            def readjust_if(judgement: str) -> bool:
                return (
                    last
                    and pass_index < max_passes
                    and maths.comparison_winner([*judgements, judgement]) is not None
                )

            def judged(judgement: str) -> None:
                judgements.append(judgement)
                compare(pair_index, orders[1:])

            self.run_trial(lambda: Comparison(*self._windows(), plan, readjust_if), judged)

        def pair_done(pair_index: int) -> None:
            winner = maths.comparison_winner(judgements)
            if winner is None:
                then()
            elif pair_index < pairs_to_flag:
                pair(pair_index + 1)
            elif pass_index < max_passes:
                self.session.log(
                    "equalisation_mismatch", severity="warning",
                    detail=f"channel {channel}, pass {pass_index}: {winner} in every "
                    "comparison; re-adjusting",
                )
                # Back to matching, then to comparing: each introduced again (N7.F11c1).
                def compare_again() -> None:
                    self._introduce(
                        INTRO_COMPARE,
                        lambda: self._check_channel(channel, pass_index + 1, then),
                    )

                self._introduce(
                    INTRO_MATCH,
                    lambda: self._match_channel(channel, compare_again, readjust=True),
                    readjust=True,
                )
            else:
                self.session.log(
                    "equalisation_mismatch", severity="warning",
                    detail=f"channel {channel}: still {winner} after re-adjustment; continuing",
                )
                self.experimenter.set_warning(
                    self.experimenter.text["warnings"]["equalisation_mismatch"].format(
                        channel=channel
                    )
                )
                then()

        pair(1)

    def _after_equalisation(self) -> None:
        if self.pleasant_kpa is not None:
            # A rebalance: the pleasantness level is on the reference's scale, which the
            # gains do not touch, so it stands (docs/LOG.md N7.C8).
            self._evenness()
        else:
            self.step_name = STEP_PLEASANTNESS
            self._introduce(INTRO_PLEASANT, self._pleasantness)

    # -- step 5 ------------------------------------------------------------------------

    def _pleasantness(self) -> None:
        low, high = self.targets[self.low_pct], self.targets[self.high_pct]
        # Stage boundary (CLAUDE.md): `usable_targets` refuses an empty window and the
        # fallback lines cannot produce one, so reaching here with one is a defect.
        assert low < high, f"the pleasantness window {low:.1f}--{high:.1f} kPa is empty"
        directions = list(self.touch["start_directions"])
        plans = [
            AdjustmentPlan(
                stage=PLEASANTNESS_STAGE,
                channel=self.reference,
                target_key=PLEASANTNESS_TARGET,
                adjustment_index=index + 1,
                start_direction=directions[index % len(directions)],
                range_min_kpa=low,
                range_max_kpa=high,
                run_index=self.run_index,
            )
            for index in range(int(self.touch["pleasantness_adjustments"]))
        ]
        settings: list[float] = []
        self.experimenter.set_instruction(
            self.experimenter.text["instructions"]["touchcal_pleasantness"]
        )

        def next_plan() -> None:
            if len(settings) == len(plans):
                self.pleasant_kpa = maths.geometric_mean(settings)
                self.session.log("pleasant_level", detail=f"{self.pleasant_kpa:.1f} kPa")
                self._evenness()
                return
            plan = plans[len(settings)]

            def adjusted(kpa: float) -> None:
                self.session.garment.stop()
                settings.append(kpa)
                next_plan()

            def play(_) -> None:
                self.session.garment.play_pattern(self.fixed_pattern)
                self.run_trial(
                    lambda: PatternAdjustment(*self._windows(), plan, self.gains), adjusted
                )

            self.run_trial(lambda: Cue(*self._windows()), play)

        next_plan()

    # -- the evenness check ------------------------------------------------------------

    def _levels(self, level_kpa: float, what: str) -> dict[int, float]:
        levels, clamped = maths.per_channel(level_kpa, self.gains, self.ceiling_kpa)
        if clamped:
            self.session.log(
                "delivery_clamped", severity="warning",
                detail=f"{what}: channels {', '.join(map(str, clamped))} held inside "
                "[0, ceiling]",
            )
        return levels

    def _evenness(self) -> None:
        self.step_name = STEP_EVENNESS
        if not self.touch["evenness_check"]:
            self._after_evenness()
            return
        levels = self._levels(self.pleasant_kpa, "evenness check")
        self.experimenter.set_instruction(
            self.experimenter.text["instructions"]["touchcal_evenness"]
        )

        def answered(side: str) -> None:
            self.session.garment.stop()
            even = side == SIDES[0]  # the affirmative is on the left (SPEC.md 10.7)
            allowed = int(self.touch["evenness_max_rebalances"])
            rebalance = not even and self.rebalances < allowed
            self.evenness_checks += 1
            self.session.files.write(
                "touchcal_evenness",
                timestamp_iso=self.session.clock.wall_iso(),
                t_session_s=self.session.clock.t_session_s(),
                check_index=self.evenness_checks,
                level_kpa=self.pleasant_kpa,
                judgement=EVEN if even else UNEVEN,
                rebalance_offered=rebalance,
                valid_for_analysis=self.real,
            )
            if not rebalance:
                self._after_evenness()
                return
            self.run_trial(
                lambda: ExperimenterChoice(
                    *self._windows(),
                    {REBALANCE: self.experimenter.rebalance_requested,
                     PROCEED: self.experimenter.proceed_requested},
                    "touchcal_uneven",
                    show=self.rig.show_between,
                ),
                decided,
            )

        def decided(outcome) -> None:
            name, _ = outcome
            if name == REBALANCE:
                self.rebalances += 1
                self.session.log("rebalance", origin="experimenter",
                                 detail=f"rebalance {self.rebalances}")
                self._match_all(self._equalise_all)
            else:
                self._after_evenness()

        def ask(_) -> None:
            self.run_trial(lambda: Choice(*self._windows(), EVENNESS_CHOICE), answered)

        self.run_trial(
            lambda: Ramp(*self._windows(), levels),
            lambda _: self.run_trial(
                lambda: Cue(*self._windows()),
                lambda _: (self.session.garment.play_pattern(self.fixed_pattern), ask(None)),
            ),
        )

    # -- step 6 ------------------------------------------------------------------------

    def _after_evenness(self) -> None:
        """Step 6, except in a re-calibration during the intervention, which keeps the
        touch calibration's choice: asked again, it could change the participant-preferred
        condition's pattern mid-intervention (docs/LOG.md N7.F12a1). Logged, without the
        pattern, which is recorded in `touchcal_channels` and never displayed."""
        if self._kept_preference is None:
            self._preference()
            return
        self.session.log("preference_kept",
                         detail="re-calibration during the intervention: step 6 not asked")
        self._finish_calibration(self._kept_preference)

    def _preference(self) -> None:
        self.step_name = STEP_PREFERENCE
        order = list(self.pattern_config["preference_candidates"])
        self.session.rng.shuffle(order)
        levels = self._levels(self.pleasant_kpa, "preference selection")
        self.experimenter.set_instruction(
            self.experimenter.text["instructions"]["touchcal_preference"]
        )

        def chosen(name: str) -> None:
            self.session.garment.stop()
            self._finish_calibration(name)

        self.run_trial(
            lambda: Ramp(*self._windows(), levels),
            lambda _: self.run_trial(
                lambda: Cue(*self._windows()),
                lambda _: self.run_trial(
                    lambda: PreferenceSelection(
                        *self._windows(), tuple(order), self.pleasant_kpa
                    ),
                    chosen,
                ),
            ),
        )

    # -- the end -----------------------------------------------------------------------

    def _finish_calibration(self, preferred: str) -> None:
        conditions = self.pattern_config["condition_pattern"]
        sham_kpa = self.targets[self.sham_pct]
        plan = {
            "sham": (conditions["sham"], sham_kpa),
            "ct_targeted": (conditions["ct_targeted"], self.pleasant_kpa),
            "participant_preferred": (preferred, self.pleasant_kpa),
        }
        levels, clamped = {}, {}
        for condition, (_, level_kpa) in plan.items():
            levels[condition], clamped[condition] = maths.per_channel(
                level_kpa, self.gains, self.ceiling_kpa
            )
            if clamped[condition]:
                self.session.log(
                    "delivery_clamped", severity="warning",
                    detail=f"a delivery: channels {', '.join(map(str, clamped[condition]))} "
                    "held inside [0, ceiling]",
                )
        self._used_run_index = self.run_index
        self._kept_preference = None
        self._write_channels(preferred, levels, clamped)
        deliveries = {
            condition: Delivery(pattern, levels[condition] if self.real else None)
            for condition, (pattern, _) in plan.items()
        }
        result = TouchCalibrationResult(
            run_index=self.run_index,
            reference_channel=self.reference,
            p20_kpa=sham_kpa,
            p30_kpa=self.targets[self.low_pct],
            p80_kpa=self.targets[self.high_pct],
            targets_source=self.targets_source,
            match_level_kpa=self.match_level_kpa,
            gains=dict(self.gains),
            gain_sources=dict(self.gain_sources),
            pleasant_kpa=self.pleasant_kpa,
            preferred_pattern=preferred,
            stage1_pass=self.stage1_pass,
            skipped=self.skipped,
            valid_for_analysis=self.valid,
            **deliveries,
        )
        self.session.log(
            "touch_calibration_done",
            severity="info" if self.valid else "warning",
            detail=f"run {self.run_index}"
            + ("; skipped" if self.skipped else "")
            + ("" if self.valid else "; not valid for analysis"),
        )
        self.experimenter.set_instruction("")
        self.finish(result)

    def _write_channels(self, preferred: str, levels: dict, clamped: dict) -> None:
        """One row per channel: what a resumed session needs to deliver (SPEC.md 15).

        Recorded, never displayed: the per-condition pressures and the preferred pattern are
        data, and a screen that showed them would name the condition (SPEC.md 16). Each set is
        numbered, so a re-calibration during the intervention adds one, governing the touch
        from its time on (docs/LOG.md N7.F12a1).
        """
        stamp, t_session_s = self.session.clock.wall_iso(), self.session.clock.t_session_s()
        self.session.calibrations_used += 1
        for channel in sorted(self.gains):
            self.session.files.write(
                "touchcal_channels",
                timestamp_iso=stamp,
                t_session_s=t_session_s,
                calibration_index=self.session.calibrations_used,
                run_index=self.run_index,
                channel=channel,
                reference_channel=self.reference,
                gain=self.gains[channel],
                gain_source=self.gain_sources[channel],
                match_settings_kpa=";".join(
                    f"{kpa:.3f}" for kpa in self.match_settings.get(channel, [])
                ),
                match_level_kpa=self.match_level_kpa,
                targets_source=self.targets_source,
                p20_kpa=self.targets[self.sham_pct],
                p30_kpa=self.targets[self.low_pct],
                p80_kpa=self.targets[self.high_pct],
                pleasant_kpa=self.pleasant_kpa,
                sham_kpa=levels["sham"][channel],
                ct_targeted_kpa=levels["ct_targeted"][channel],
                participant_preferred_kpa=levels["participant_preferred"][channel],
                participant_preferred_pattern=preferred,
                clamped=";".join(c for c in levels if channel in clamped[c]),
                skipped=self.skipped,
                valid_for_analysis=self.valid,
            )

    # -- plumbing ----------------------------------------------------------------------

    def _windows(self) -> tuple:
        return self.session, self.participant, self.experimenter


