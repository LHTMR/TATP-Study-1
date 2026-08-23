"""Protocol B -- touch pressure calibration. SPEC.md 9, 10.3.

Milestone 1 builds the first step end to end: one method-of-adjustment trial on the reference
channel against the mock garment, and one touch intensity rating. The estimation run and its fit
(SPEC.md 9 step 2), the channel matching, the equalisation comparisons and the pleasantness
adjustment are later milestones -- what exists here is the path through every layer, not the
protocol in full.

**The accelerating control (SPEC.md 10.3) is `AdjustmentState`, which imports no Qt and takes
the time as an argument.** Every rule that matters -- a tap moves one step, a hold accelerates
from the initial rate to the final one over the ramp, the pressure stays inside the adjustable
range -- is then tested at exact times rather than at whatever times a timer happened to fire.
`Adjustment` is the thin Qt driver around it: it turns the participant window's button signals
into calls, ticks the state, and commands the garment.

**The control runs on real seconds, not on the accelerated clock.** A tap threshold and a ramp
rate describe the participant's hand, so scaling them does not make a session faster, it makes
the control different -- at speed 100 no press could be short enough to be a tap. The one
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

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from tatp.responder import Action
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.units import MS_PER_S

# Config keys and controlled-vocabulary values, not wording.
INTENSITY_SCALE = "intensity"
ANCHOR_STAGE = "anchor"
BELOW = "below"
ABOVE = "above"


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


def anchor_plans(config) -> tuple[AdjustmentPlan, ...]:
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
                )
            )
    return tuple(plans)


class AdjustmentState:
    """The accelerating control of SPEC.md 10.3. No Qt; the caller supplies the time."""

    def __init__(
        self,
        adjustment_config: dict,
        range_min_kpa: float,
        range_max_kpa: float,
        start_kpa: float,
    ):
        self.tap_max_duration_s = float(adjustment_config["tap_max_duration_s"])
        self.tap_step_kpa = float(adjustment_config["tap_step_kpa"])
        self.hold_delay_s = float(adjustment_config["hold_delay_s"])
        self.rate_initial_kpa_s = float(adjustment_config["hold_rate_initial_kpa_s"])
        self.rate_final_kpa_s = float(adjustment_config["hold_rate_final_kpa_s"])
        self.ramp_duration_s = float(adjustment_config["hold_ramp_duration_s"])
        # Stage boundary (CLAUDE.md): the control is described as accelerating, and a ramp of
        # zero length would divide by zero rather than merely being a different control.
        assert self.ramp_duration_s > 0, "adjustment.hold_ramp_duration_s must be positive"
        assert range_min_kpa < range_max_kpa, (
            f"the adjustable range {range_min_kpa}--{range_max_kpa} kPa is empty"
        )

        self.range_min_kpa = float(range_min_kpa)
        self.range_max_kpa = float(range_max_kpa)
        self.pressure_kpa = min(max(float(start_kpa), self.range_min_kpa), self.range_max_kpa)
        self.exploration_kpa = 0.0
        self.button_events = 0

        self._held: Action | None = None
        self._pressed_at_s = 0.0
        self._held_travel_s = 0.0
        self._moved_by_hold = False

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
            self._moved_by_hold = False

    def release(self, action: Action, now_s: float) -> None:
        self.button_events += 1
        if action is not self._held:
            return
        # A press short enough to be a tap moves one step; a press long enough to have moved the
        # pressure already has moved it, and adding a step on release would double the last one.
        if not self._moved_by_hold and now_s - self._pressed_at_s <= self.tap_max_duration_s:
            self._move(self._direction(action) * self.tap_step_kpa)
        self._held = None

    def tick(self, now_s: float) -> None:
        """Apply the movement owed since the last tick. Nothing to do unless a key is held."""
        if self._held is None:
            return
        held_s = now_s - self._pressed_at_s - self.hold_delay_s
        if held_s <= 0:
            return
        travelled = self._travel_kpa(held_s) - self._travel_kpa(self._held_travel_s)
        self._held_travel_s = held_s
        if travelled > 0:
            self._moved_by_hold = True
            self._move(self._direction(self._held) * travelled)

    # -- the ramp ----------------------------------------------------------------------

    def rate_kpa_s(self, held_s: float) -> float:
        """The rate at `held_s` seconds into the hold, past the delay. SPEC.md 10.3."""
        if held_s <= 0:
            return 0.0
        if held_s >= self.ramp_duration_s:
            return self.rate_final_kpa_s
        fraction = held_s / self.ramp_duration_s
        return self.rate_initial_kpa_s + fraction * (
            self.rate_final_kpa_s - self.rate_initial_kpa_s
        )

    def _travel_kpa(self, held_s: float) -> float:
        """Distance travelled in the first `held_s` seconds of a hold.

        The integral of a linear ramp, in closed form rather than accumulated per tick, so the
        distance depends on how long the button was held and not on how often the timer fired.
        """
        if held_s <= 0:
            return 0.0
        ramped = min(held_s, self.ramp_duration_s)
        gained = self.rate_final_kpa_s - self.rate_initial_kpa_s
        # The 2 is the area of a triangle, not a study parameter (SPEC.md 4.2).
        distance = self.rate_initial_kpa_s * ramped + gained * ramped * ramped / (
            2 * self.ramp_duration_s
        )
        return distance + self.rate_final_kpa_s * max(0.0, held_s - self.ramp_duration_s)

    # -- plumbing ----------------------------------------------------------------------

    def _direction(self, action: Action) -> float:
        return -1.0 if action is Action.DECREASE else 1.0

    def _move(self, delta_kpa: float) -> None:
        before = self.pressure_kpa
        self.pressure_kpa = min(
            max(self.pressure_kpa + delta_kpa, self.range_min_kpa), self.range_max_kpa
        )
        # Travel that the range refused is not exploration: the participant learns nothing from
        # pressing against an end stop.
        self.exploration_kpa += abs(self.pressure_kpa - before)


class Adjustment(QObject):
    """One method-of-adjustment trial, driven by the participant's buttons. SPEC.md 9, 10.3.

    `finished` carries the produced pressure in kPa, or None if the trial was stopped.
    """

    finished = Signal(object)

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
            adjustment, plan.range_min_kpa, plan.range_max_kpa, self.start_kpa
        )

        self.start_iso = ""
        self._start_s = 0.0
        self._t_session_s: float | None = None
        self.timed_out = False

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
        # Real seconds: `duration_s` is how long a participant took, which is the FOR_S A3.6
        # measurement and must not be reported scaled.
        self._start_s = clock.real_elapsed_s()
        self._t_session_s = clock.t_session_s()

        self.session.garment.set_pressure(self.plan.channel, self.state.pressure_kpa)
        self.participant.adjust_pressed.connect(self._on_pressed)
        self.participant.adjust_released.connect(self._on_released)
        self.participant.adjust_confirmed.connect(self._on_confirmed)
        self.participant.emergency_stop.connect(self._on_emergency_stop)

        self.participant.show_adjustment(self.plan.target_key)
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["await_participant"]
        )
        self.experimenter.refresh()
        self.session.log(
            "adjustment_started",
            detail=f"{self.plan.stage}, channel {self.plan.channel}, "
            f"from {self.plan.start_direction} at {self.state.pressure_kpa:.1f} kPa",
        )
        self._tick.start()
        self._timeout.start(self.session.clock.scaled_ms(self.timeout_s))

    def _on_pressed(self, action_value: str) -> None:
        self.state.press(Action(action_value), self.session.clock.real_elapsed_s())
        self._log_button("button_down", action_value)

    def _on_released(self, action_value: str) -> None:
        self.state.release(Action(action_value), self.session.clock.real_elapsed_s())
        self._log_button("button_up", action_value)
        self._command()

    def _on_tick(self) -> None:
        self.state.tick(self.session.clock.real_elapsed_s())
        self._command()

    def _command(self) -> None:
        if self.state.pressure_kpa != self.session.garment.pressure_kpa[self.plan.channel]:
            self.session.garment.set_pressure(self.plan.channel, self.state.pressure_kpa)

    # -- the end of the trial -----------------------------------------------------------

    def _on_confirmed(self) -> None:
        self._end()
        self.session.log(
            "adjustment_confirmed",
            origin="participant",
            detail=f"{self.state.pressure_kpa:.1f} kPa after "
            f"{self.state.button_events} button events",
        )
        self._write()
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["response_received"]
        )
        self.experimenter.refresh()
        self.finished.emit(self.state.pressure_kpa)

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
        self.finished.emit(self.state.pressure_kpa)

    def _on_emergency_stop(self) -> None:
        """SPEC.md 13. The garment is stopped by the session; no row is written.

        Nothing was produced, so there is no produced pressure to record. The log carries the
        event and the pressure that was commanded when it happened.
        """
        commanded = self.state.pressure_kpa
        self._end()
        self.session.garment.stop()
        self.participant.show_emergency_stop()
        self.session.log(
            "emergency_stop",
            origin="participant",
            severity="error",
            detail=f"during {self.plan.stage} adjustment at {commanded:.1f} kPa",
        )
        self.finished.emit(None)

    def _write(self) -> None:
        self.session.files.write(
            "touchcal_adjust",
            timestamp_iso=self.start_iso,
            t_session_s=self._t_session_s,
            stage=self.plan.stage,
            channel=self.plan.channel,
            reference_channel=self.plan.reference_channel,
            anchor_percent=self.plan.anchor_percent,
            adjustment_index=self.plan.adjustment_index,
            start_direction=self.plan.start_direction,
            start_pressure_kpa=self.start_kpa,
            produced_pressure_kpa=self.state.pressure_kpa,
            range_min_kpa=self.plan.range_min_kpa,
            range_max_kpa=self.plan.range_max_kpa,
            duration_s=self.session.clock.real_elapsed_s() - self._start_s,
            button_events=self.state.button_events,
            min_exploration_met=self.state.exploration_kpa >= self.min_exploration_kpa,
            timed_out=self.timed_out,
            # SPEC.md 12.4: a device that cannot set pressure per channel produces real timings
            # and unreal pressures, and an adjustment is entirely about the pressure.
            valid_for_analysis=self.session.garment.per_channel_pressure,
        )

    def _log_button(self, event: str, action_value: str) -> None:
        self.session.log(
            event,
            origin="participant",
            detail=f"{action_value} at {self.state.pressure_kpa:.1f} kPa",
        )

    def _end(self) -> None:
        self._tick.stop()
        self._timeout.stop()
        self.participant.adjust_pressed.disconnect(self._on_pressed)
        self.participant.adjust_released.disconnect(self._on_released)
        self.participant.adjust_confirmed.disconnect(self._on_confirmed)
        self.participant.emergency_stop.disconnect(self._on_emergency_stop)


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
    ):
        super().__init__(parent)
        self.session = session
        self.participant = participant
        self.experimenter = experimenter
        self.scale = scale
        self.channel = channel
        self.cue_iso = ""
        self._t_session_s: float | None = None

    def start(self) -> None:
        self.participant.confirmed.connect(self._on_confirmed)
        self.participant.emergency_stop.connect(self._on_emergency_stop)
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

    def _on_emergency_stop(self) -> None:
        """SPEC.md 13. No rating was given, so no row is written."""
        self._end()
        self.session.garment.stop()
        self.participant.show_emergency_stop()
        self.session.log(
            "emergency_stop",
            origin="participant",
            severity="error",
            detail=f"during the {self.scale} rating",
        )
        self.finished.emit(None)

    def _end(self) -> None:
        self.participant.confirmed.disconnect(self._on_confirmed)
        self.participant.emergency_stop.disconnect(self._on_emergency_stop)
