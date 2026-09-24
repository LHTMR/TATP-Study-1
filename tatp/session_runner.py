"""The whole session, in order. SPEC.md 2, 7.4, 8, 9, 10.5, 12.3, 15.

`SessionRunner` is the outermost `Procedure` (`tatp/procedure.py`): it runs every protocol as a
child with `run_child`, so an interruption is always handled by the innermost procedure and the
runner itself only ever repeats one of its own waits.

**The session is a list of stages**, each one protocol at a time point, one scheduled block,
the rekindle, or one timed step. `_plan` builds it once from the configuration, and a stage logs
`stage_completed` with its id when it ends. That log line is what "completed" means for a
resume (`tatp/resume.py`): a resumed session starts at the first stage it does not find there.

1. **Setup** -- the garment fitted, the welcome screen, the masking check (SPEC.md 10.7) and the
   stop rehearsal (10.9).
2. **Touch calibration** (9), then the baseline relaxation and alertness ratings (Bilaga 1
   Table 2).
3. **Pre-sensitisation** -- the long protocol on the secondary region, the short protocol on the
   primary region at the fixed 26 g, then brush, secondary and primary (Bilaga 1 Table 1).
4. **Sensitisation** -- session t=0 is the experimenter's press when the thermode starts.
   **Capsaicin** is prompted when due and timed to its end.
5. **Post-sensitisation** -- the same measures, with the area mapping after the long protocol.
   The white noise is off for the mapping (8.4, 10.5) and its pacing cue is an audible tick.
6. **The intervention** -- the garment delivers the condition's touch from the intervention's
   start; the scheduled blocks run in planned order; the rekindle deactivates the garment and
   it is reactivated after (7.4, 12.3). Pinprick blocks are the short protocol on the secondary
   region at the post-S filament; touch blocks are `TouchBlock`.
7. **Post-intervention** -- once the intervention window has closed, the measures once more.
8. **Session end** -- outstanding mapping distances are prompted for once (8.4), then close.

**Timing** (SPEC.md 7.4). The software times and the experimenter launches. A scheduled step is
*armed* at its planned time -- it waits, never skips and never launches itself -- and its
lateness is recorded when the experimenter launches it. An audible lab-side alert sounds
`due_alert_lead_s` before a step is due and again `overdue_alert_margin_s` after, and every
alert is logged (`Audio.experimenter_alert`). The countdown the experimenter screen shows is
`Session.set_upcoming`.

**Blinding** (SPEC.md 16). The runner reads `Session.condition` twice, to choose the delivery
and whether the participant starts it, and hands both to `DeliveryStart`, which shows the same
screen in every condition. Nothing else here depends on the condition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from tatp import pinprick
from tatp import resume as resumption
from tatp.mapping import AreaMapping, MappingLedger
from tatp.pinprick import (
    BrushProtocol,
    IntolerableCap,
    LongProtocol,
    LongResult,
    Prior,
    ShortProtocol,
    prior_for,
)
from tatp.procedure import Procedure, Rig
from tatp.schedule import Block
from tatp.setup_checks import MaskingCheck, StopRehearsal
from tatp.touchcal import DeliveryStart, TouchCalibration, TouchRating
from tatp.touchcal_maths import Delivery
from tatp.trials import MessageConfirm
from tatp.units import S_PER_MIN

# Keys in config/text/participant_*.yaml, not wording.
WELCOME_SCREEN = "welcome"
STANDBY_SCREEN = "standby"
END_SCREEN = "session_end"
# Controlled vocabularies (docs/DATA_SCHEMA.md), not wording.
PRIMARY, SECONDARY = pinprick.REGIONS
SETUP = "setup"
TOUCH_CALIBRATION = "touch_calibration"
PRE_S = "pre_sensitisation"
SENSITISATION = "sensitisation"
CAPSAICIN = "capsaicin"
POST_S = "post_sensitisation"
INTERVENTION = "intervention"
REKINDLE = "rekindle"
POST_I = "post_intervention"
MAPPED = (POST_S, POST_I)
# The one condition the participant starts themselves (SPEC.md 12.3).
SELF_STARTED = "participant_preferred"
# `Session.set_upcoming` kinds.
BLOCK, PHASE = "block", "phase"
FIRST_SESSION = 1


@dataclass(frozen=True)
class Upcoming:
    """A scheduled moment the experimenter screen counts down to."""

    kind: str
    label_key: str
    due_s: float
    block: Block | None = None


@dataclass(frozen=True)
class Stage:
    """One step of the session. `id` is what the log records and a resume reads."""

    id: str
    phase: str
    begin: Callable[[], None]
    upcoming: Upcoming | None = None


class TouchBlock(Procedure):
    """A touch-rating block (SPEC.md 2, Bilaga 1 3.9): ratings of the touch being delivered.

    Launched by the experimenter like every block. Then each repeated scale in turn,
    `n_repetitions` times, and each once-only scale once, all rated while the garment delivers.
    The same in every condition: what differs is the touch, which this class never looks at.
    """

    def __init__(self, rig: Rig, channel: int):
        super().__init__(rig)
        touch_block = self.session.config.study1["touch_block"]
        repeated = list(touch_block["repeated_scales"])
        self.plan = repeated * int(touch_block["n_repetitions"]) + list(
            touch_block["once_scales"]
        )
        self.channel = channel
        self.done_count = 0

    def begin(self) -> None:
        def prepare() -> None:
            self.participant.show_blank()
            self.experimenter.set_instruction(self.experimenter.text["instructions"]["ready"])
            self.experimenter.refresh()

        self.await_proceed(self._next, prepare)

    def _next(self) -> None:
        if self.done_count == len(self.plan):
            self.finish(None)
            return
        self.experimenter.set_instruction(
            self.experimenter.text["instructions"]["touch_block"]
        )
        scale = self.plan[self.done_count]
        self.run_trial(
            lambda: TouchRating(
                self.session, self.participant, self.experimenter, scale, self.channel
            ),
            self._rated,
        )

    def _rated(self, _response) -> None:
        self.done_count += 1
        self._next()


class SessionRunner(Procedure):
    """SPEC.md 2 from the garment fitting to the closing screen. See the module docstring."""

    def __init__(self, rig: Rig, resume: resumption.ResumeState | None = None):
        super().__init__(rig)
        config = self.session.config
        self.resume = resume
        self.completed = False
        # Held by `run_session.build`, released when the session closes.
        self.lock = None

        validation = config.schedule["validation"]
        self.due_lead_s = float(validation["due_alert_lead_s"])
        self.overdue_margin_s = float(validation["overdue_alert_margin_s"])
        self.pinprick = config.study1["pinprick"]
        self.reference_channel = int(config.study1["touch_calibration"]["reference_channel"])

        self.ledger = MappingLedger(self.session, self.experimenter, self)
        self.caps: dict[object, IntolerableCap] = {}
        self.f40_mn: dict[str, float] = {}
        self.chosen_filament_label_g: dict[str, str] = {}
        self.deliveries: dict[str, Delivery] | None = None

        self.stages = self._plan()
        self.stage_index = 0
        self._launch: Callable[[], None] | None = None
        self._alarms: list[tuple[float, str]] = []
        self._alarm_timer = QTimer(self)
        self._alarm_timer.setSingleShot(True)
        self._alarm_timer.timeout.connect(self._fire_alarm)

        self.experimenter.abort_requested.connect(self.abort)

    # == the plan ==============================================================================

    def _plan(self) -> list[Stage]:
        schedule = self.session.schedule
        stages: list[Stage] = []

        def add(stage_id, phase, begin, upcoming=None) -> None:
            stages.append(Stage(stage_id, phase, begin, upcoming))

        add("setup.garment", SETUP, self._fit_garment)
        add("setup.welcome", SETUP, self._welcome)
        add("setup.masking_check", SETUP,
            lambda: self._protocol(lambda: MaskingCheck(self.rig)))
        add("setup.stop_rehearsal", SETUP,
            lambda: self._protocol(lambda: StopRehearsal(self.rig)))
        # Its own phase is set by the calibration itself.
        add("touch_calibration", SETUP, self._touch_calibration)
        add("touch_calibration.baseline", TOUCH_CALIBRATION, self._baseline)
        self._time_point(add, PRE_S)
        # t=0 is set by the experimenter's press in this stage, so it begins in pre-S.
        add("sensitisation", PRE_S, self._sensitisation)

        capsaicin = schedule.window(CAPSAICIN)
        apply_at = Upcoming(PHASE, CAPSAICIN, capsaicin.start_min * S_PER_MIN)
        remove_at = Upcoming(PHASE, POST_S, capsaicin.end_min * S_PER_MIN)
        add("capsaicin.apply", SENSITISATION, lambda: self._capsaicin_apply(apply_at), apply_at)
        add("capsaicin.remove", CAPSAICIN, lambda: self._capsaicin_remove(remove_at), remove_at)
        self._time_point(add, POST_S)

        intervention = schedule.window(INTERVENTION)
        start_at = Upcoming(PHASE, INTERVENTION, intervention.start_min * S_PER_MIN)
        add("intervention.start", INTERVENTION,
            lambda: self._intervention_start(start_at), start_at)

        rekindle = schedule.window(REKINDLE)
        rekindle_at = Upcoming(REKINDLE, REKINDLE, rekindle.start_min * S_PER_MIN)
        # A rekindle outside the intervention divides nothing (SPEC.md 7.1): piloting may run
        # without one.
        rekindle_pending = intervention.start_min <= rekindle.start_min < intervention.end_min
        for block in sorted(schedule.blocks, key=lambda b: (b.planned_offset_min, b.index)):
            if rekindle_pending and block.planned_offset_min >= rekindle.start_min:
                add("rekindle", INTERVENTION, lambda: self._rekindle(rekindle_at), rekindle_at)
                rekindle_pending = False
            at = Upcoming(BLOCK, BLOCK, block.planned_offset_s, block)
            add(f"block.{block.index}", INTERVENTION,
                lambda block=block, at=at: self._block(block, at), at)
        if rekindle_pending:
            add("rekindle", INTERVENTION, lambda: self._rekindle(rekindle_at), rekindle_at)

        end_at = Upcoming(PHASE, POST_I, intervention.end_min * S_PER_MIN)
        add("intervention.end", INTERVENTION, lambda: self._intervention_end(end_at), end_at)
        self._time_point(add, POST_I)
        add("session_end", POST_I, self._session_end)

        # Stage boundary (CLAUDE.md): a resume identifies stages by id.
        ids = [stage.id for stage in stages]
        assert len(set(ids)) == len(ids), f"stage ids repeat: {ids}"
        assert sum(s.id.startswith("block.") for s in stages) == len(schedule.blocks)
        return stages

    def _time_point(self, add, phase: str) -> None:
        """One time point's pain measures, in Bilaga 1 Table 1's order (docs/LOG.md N7.D2)."""
        primary_g = self.pinprick["primary_filament_label_g"]
        add(f"{phase}.long", phase, lambda: self._long(phase))
        if phase in MAPPED:
            add(f"{phase}.mapping", phase, lambda: self._mapping())
        add(f"{phase}.short_primary", phase, lambda: self._protocol(
            lambda: ShortProtocol(self.rig, PRIMARY, primary_g, self._cap(phase))
        ))
        add(f"{phase}.brush_secondary", phase,
            lambda: self._protocol(lambda: BrushProtocol(self.rig, SECONDARY)))
        add(f"{phase}.brush_primary", phase,
            lambda: self._protocol(lambda: BrushProtocol(self.rig, PRIMARY)))

    # == running the stages ====================================================================

    def begin(self) -> None:
        if self.resume is None:
            self._run_stage(0)
        else:
            self._resume()

    def _run_stage(self, index: int) -> None:
        self.stage_index = index
        stage = self.stages[index]
        if self.session.phase != stage.phase:
            self.session.set_phase(stage.phase)
        self.session.log("stage_started", detail=stage.id)
        self._show_upcoming(index)
        stage.begin()

    def _stage_done(self, _result: object = None) -> None:
        stage = self.stages[self.stage_index]
        self.session.log("stage_completed", detail=stage.id)
        self._run_stage(self.stage_index + 1)

    def _protocol(self, make: Callable[[], Procedure], then=None) -> None:
        """Run a protocol as this stage; `then(result)` before the next stage begins."""

        def done(result: object) -> None:
            if then is not None:
                then(result)
            self._stage_done()

        self.run_child(make, done)

    def _standby(self, instruction: str) -> Callable[[], None]:
        def prepare() -> None:
            self.participant.show_message(STANDBY_SCREEN)
            self.experimenter.set_instruction(
                self.experimenter.text["instructions"][instruction]
            )
            self.experimenter.set_status("")
            self.experimenter.refresh()

        return prepare

    # == setup and touch calibration ===========================================================

    def _fit_garment(self) -> None:
        self.await_proceed(self._stage_done, self._standby("fit_garment"))

    def _welcome(self) -> None:
        self.experimenter.set_instruction(
            self.experimenter.text["instructions"]["await_participant"]
        )
        self.experimenter.refresh()
        self.run_trial(
            lambda: MessageConfirm(
                self.session, self.participant, self.experimenter,
                lambda: self.participant.show_message(WELCOME_SCREEN), WELCOME_SCREEN,
            ),
            self._stage_done,
        )

    def _touch_calibration(self) -> None:
        def make() -> TouchCalibration:
            calibration = TouchCalibration(self.rig)
            self._preview(calibration)
            return calibration

        def calibrated(result) -> None:
            # Every condition's delivery, computed identically; which one is used is decided
            # only when the intervention starts (SPEC.md 16).
            self.deliveries = {
                condition: result.for_condition(condition)
                for condition in self.session.config.study1["design"]["conditions"]
            }

        self._protocol(make, calibrated)

    def _baseline(self) -> None:
        """Bilaga 1 Table 2's baseline relaxation and alertness, with the garment off."""
        self.session.garment.stop()
        scales = list(self.session.config.study1["touch_block"]["baseline_scales"])
        self.experimenter.set_instruction(
            self.experimenter.text["instructions"]["baseline_ratings"]
        )
        self.experimenter.refresh()

        def rate(index: int) -> None:
            if index == len(scales):
                self._stage_done()
                return
            self.run_trial(
                lambda: TouchRating(
                    self.session, self.participant, self.experimenter, scales[index],
                    self.reference_channel,
                ),
                lambda _: rate(index + 1),
            )

        rate(0)

    # == the pain measures =====================================================================

    def _cap(self, key: object) -> IntolerableCap:
        """One per time point, and each intervention block is one (SPEC.md 8.2)."""
        if key not in self.caps:
            sites = int(self.pinprick["intolerable_sites_for_global_cap"])
            self.caps[key] = IntolerableCap(sites)
        return self.caps[key]

    def _prior(self, phase: str) -> Prior:
        config, number = self.session.config, self.session.session_number
        if phase == PRE_S and number == FIRST_SESSION:
            return prior_for(config, phase, number, None)
        if phase == PRE_S:
            previous = resumption.previous_session_f40(
                self.session.data_folder, self.session.participant_code, number - 1, PRE_S
            )
            if previous is None:
                # docs/LOG.md N7.D8. The prior only sets where the search starts, and the
                # search runs both ways, so the estimate is still measured; what is lost is the
                # shorter search. Recorded as a config-default start, and warned.
                self.session.log(
                    "no_previous_session_estimate", severity="warning",
                    detail=f"session {number - 1} has no pre-sensitisation estimate; the "
                    "search starts from the configured filament",
                )
                start = self.pinprick["start_filament_label_g_session1_pre_s"]
                return Prior(start, pinprick.CONFIG_DEFAULT)
            return prior_for(config, phase, number, previous)
        previous_phase = PRE_S if phase == POST_S else POST_S
        return prior_for(config, phase, number, self.f40_mn[previous_phase])

    def _long(self, phase: str) -> None:
        prior = self._prior(phase)

        def make() -> LongProtocol:
            protocol = LongProtocol(self.rig, SECONDARY, prior, self._cap(phase))
            self._preview(protocol)
            return protocol

        def estimated(result: LongResult) -> None:
            self.f40_mn[phase] = result.f40_mn
            self.chosen_filament_label_g[phase] = result.chosen_filament_label_g

        self._protocol(make, estimated)

    def _mapping(self) -> None:
        """SPEC.md 8.4, 10.5: the noise stops for the verbal exchange and resumes after it."""
        self.session.audio.stop_noise("area mapping")
        phases = [*self.ledger.time_points]
        if self.session.phase not in phases:
            phases.append(self.session.phase)
        # The distances can be entered from now on, for this time point and any earlier one.
        self.experimenter.set_mapping_phases(phases)

        def make() -> AreaMapping:
            mapping = AreaMapping(self.rig, self.ledger)
            mapping.pacing_cue.connect(self._pacing_tick)
            return mapping

        self._protocol(make, lambda _: self.session.audio.resume_noise("area mapping ended"))

    def _pacing_tick(self, path: int, cue: int) -> None:
        self.session.audio.pacing_tick(f"path {path}, cue {cue}")
        if cue == 1:
            # The mapping walks the secondary zone towards the primary. Set on the path's first
            # cue, because the path's own instruction clears the diagram's target.
            self.experimenter.set_target(SECONDARY, filament=True)

    def _preview(self, procedure) -> None:
        """SPEC.md 11.1. The procedures take the preview down themselves once decided."""
        if self.session.fit_preview_enabled:
            procedure.fit_ready.connect(self.experimenter.show_fit_preview)

    # == the timed phases ======================================================================

    def _sensitisation(self) -> None:
        if self.session.clock.session_started:
            # A resume that lands here found t=0 already set; the stage only records it.
            self._stage_done()
            return

        def started() -> None:
            self.session.start_sensitisation()
            self._stage_done()

        self.await_proceed(started, self._standby("thermode_start"))

    def _capsaicin_apply(self, at: Upcoming) -> None:
        def applied() -> None:
            self.session.set_phase(CAPSAICIN)
            self._stage_done()

        self._arm(at, "capsaicin_apply", applied)

    def _capsaicin_remove(self, at: Upcoming) -> None:
        self._arm(at, "capsaicin_remove", self._stage_done)

    def _intervention_start(self, at: Upcoming) -> None:
        self._arm(at, "intervention_start", lambda: self._deliver(self._stage_done))

    def _intervention_end(self, at: Upcoming) -> None:
        def ended() -> None:
            self.session.garment.stop()
            self.session.log("garment_deactivated", detail="the intervention has ended")
            self.experimenter.set_instruction(
                self.experimenter.text["instructions"]["intervention_end"]
            )
            self.experimenter.refresh()
            self._stage_done()

        self._wait_until(at.due_s, ended, self._standby("waiting"))

    # == the intervention ======================================================================

    def _deliver(self, then: Callable[[], None]) -> None:
        """Start the condition's touch (SPEC.md 12.3). The two reads of the condition."""
        assert self.deliveries is not None, "the touch calibration has not delivered a result"
        condition = self.session.condition
        delivery = self.deliveries[condition]
        self_start = condition == SELF_STARTED

        def started(_latency) -> None:
            self.session.log("garment_activated")
            self.participant.show_message(STANDBY_SCREEN)
            then()

        self.run_trial(
            lambda: DeliveryStart(
                self.session, self.participant, self.experimenter, delivery, self_start
            ),
            started,
        )

    def _block(self, block: Block, at: Upcoming) -> None:
        def armed() -> None:
            self._arm_launch(block)
            if block.type == "pinprick":
                filament = self.chosen_filament_label_g[POST_S]
                self._protocol(
                    lambda: ShortProtocol(
                        self.rig, SECONDARY, filament, self._cap((INTERVENTION, block.index))
                    ),
                    lambda _: self.session.end_block(),
                )
            else:
                self._protocol(
                    lambda: TouchBlock(self.rig, self.reference_channel),
                    lambda _: self.session.end_block(),
                )

        self._set_alarms(at, f"block {block.index}")
        self._wait_until(at.due_s, armed, self._standby("waiting"))

    def _arm_launch(self, block: Block) -> None:
        """The experimenter's go on the armed block both launches it and starts its protocol.

        Connected before the child is started, so it runs before the child's own handler and
        every row of the block is written inside it (SPEC.md 7.4).
        """

        def launched() -> None:
            if self.rig.interruptions.active is not None:
                return  # the child ignores this press too; the next one counts
            self._disarm()
            self._clear_alarms()
            self._show_upcoming(self.stage_index + 1)
            self.session.start_block(block)

        self._launch = launched
        self.experimenter.proceed_requested.connect(launched)

    def _disarm(self) -> None:
        if self._launch is not None:
            self.experimenter.proceed_requested.disconnect(self._launch)
            self._launch = None

    def _rekindle(self, at: Upcoming) -> None:
        duration_s = self.session.schedule.window(REKINDLE).duration_min * S_PER_MIN

        def armed() -> None:
            # SPEC.md 7.4, 12.3: deactivated for the rekindle, logged.
            self.session.garment.stop()
            self.session.set_phase(REKINDLE)
            self.session.log("garment_deactivated", detail="rekindle")
            self.await_proceed(started, self._standby("thermode_rekindle"))

        def started() -> None:
            self._clear_alarms()
            self._launched(at)
            end_s = self.session.clock.t_session_s() + duration_s
            self._show_upcoming(self.stage_index + 1)
            self._wait_until(end_s, ended, self._standby("thermode_rekindle"))

        def ended() -> None:
            self.session.set_phase(INTERVENTION)

            def reactivated() -> None:
                self.session.log("garment_reactivated", detail="after the rekindle")
                self._stage_done()

            self._deliver(reactivated)

        self._set_alarms(at, REKINDLE)
        self._wait_until(at.due_s, armed, self._standby("waiting"))

    # == the end ===============================================================================

    def _session_end(self) -> None:
        self.session.clear_upcoming()
        if self.ledger.close():
            self._finish_session()
            return

        def closing() -> None:
            self.ledger.close()
            self._finish_session()

        # The ledger has put its once-only prompt up; the next go closes the session with
        # whatever is still missing flagged (SPEC.md 8.4).
        self.await_proceed(closing, lambda: self.participant.show_message(STANDBY_SCREEN))

    def _finish_session(self) -> None:
        self.session.log("stage_completed", detail=self.stages[self.stage_index].id)
        self.completed = True
        self.participant.show_message(END_SCREEN)
        self.finish(None)
        self._close("")

    def abort(self, reason: str) -> None:
        """The experimenter's abort (SPEC.md 11). Everything collected so far is kept."""
        self.cancel()
        # Distances still missing are written as missing, without the end-of-session prompt.
        self.ledger.prompted = True
        self.ledger.close()
        self._close(reason)

    def cancel(self) -> None:
        self._disarm()
        self._clear_alarms()
        super().cancel()

    def _close(self, abort_reason: str) -> None:
        self._clear_alarms()
        self.experimenter.refresh()
        self.session.close(abort_reason)
        if self.lock is not None:
            self.lock.release()
        QApplication.instance().quit()

    # == waiting, arming and alerts (SPEC.md 7.4) ==============================================

    def _wait_until(self, t_session_s: float, then, prepare) -> None:
        """A step that waits until a session time; repeated after an interruption, it waits
        only for what is left."""

        def check() -> None:
            # A timer can fire a little early -- its milliseconds are rounded -- and a step
            # armed early could be launched before it is due, so the clock has the last word.
            remaining_s = t_session_s - self.session.clock.t_session_s()
            if remaining_s <= 0:
                then()
            else:
                self._after(remaining_s, check)

        def begin() -> None:
            prepare()
            check()

        self.step(begin)

    def _arm(self, at: Upcoming, instruction: str, then: Callable[[], None]) -> None:
        """Wait until due, then wait for the experimenter's go, alerting either side of due."""

        def go() -> None:
            self._clear_alarms()
            self._launched(at)
            then()

        self._set_alarms(at, at.label_key)
        self._wait_until(
            at.due_s,
            lambda: self.await_proceed(go, self._standby(instruction)),
            self._standby("waiting"),
        )

    def _launched(self, at: Upcoming) -> None:
        started_min = self.session.clock.t_session_s() / S_PER_MIN
        planned_min = at.due_s / S_PER_MIN
        self.session.log(
            "scheduled_step_started", origin="experimenter",
            detail=f"{at.label_key}; planned {planned_min:g} min, started {started_min:.2f} "
            f"min, {started_min - planned_min:+.2f} min against plan",
        )

    def _show_upcoming(self, from_index: int) -> None:
        if self.session.clock.session_started:
            for stage in self.stages[from_index:]:
                if stage.upcoming is not None:
                    at = stage.upcoming
                    self.session.set_upcoming(at.kind, at.label_key, at.due_s, at.block)
                    self.experimenter.refresh()
                    return
        self.session.clear_upcoming()
        self.experimenter.refresh()

    def _set_alarms(self, at: Upcoming, what: str) -> None:
        """The due alert ahead of time and the overdue one after. One already past sounds now,
        and only the latest of those, so a late arrival is not a burst of alerts."""
        now_s = self.session.clock.t_session_s()
        alarms = [
            (at.due_s - self.due_lead_s, f"{what} due"),
            (at.due_s + self.overdue_margin_s, f"{what} overdue"),
        ]
        past = [alarm for alarm in alarms if alarm[0] <= now_s]
        self._alarms = [alarm for alarm in alarms if alarm[0] > now_s]
        if past:
            # Now, not on a timer: a step already late may be launched before a timer fires.
            self.session.audio.experimenter_alert(past[-1][1])
        self._schedule_alarm()

    def _schedule_alarm(self) -> None:
        self._alarm_timer.stop()
        if self._alarms:
            wait_s = max(0.0, self._alarms[0][0] - self.session.clock.t_session_s())
            self._alarm_timer.start(self.session.clock.scaled_ms(wait_s))

    def _fire_alarm(self) -> None:
        _, reason = self._alarms.pop(0)
        self.session.audio.experimenter_alert(reason)
        self.experimenter.refresh()
        self._schedule_alarm()

    def _clear_alarms(self) -> None:
        self._alarms = []
        self._alarm_timer.stop()

    # == resume (SPEC.md 15) ===================================================================

    def _resume(self) -> None:
        state = self.resume
        stages_done = state.completed_stages
        self.session.log(
            "session_resumed", severity="warning",
            detail=f"from {state.open.session_file.name}; {len(stages_done)} stages completed; "
            f"RNG re-seeded from the recorded seed {state.rng_seed}",
        )
        if not state.after_t_zero:
            # No clock to keep and nothing scheduled yet: the session starts again (LOG N7.D9).
            self.session.log(
                "resume_restarts_setup", severity="warning",
                detail="the crash came before session t=0, so setup and calibration run again",
            )
            self._run_stage(0)
            return
        assert state.deliveries is not None, "a session past t=0 has a touch calibration"
        assert state.masking is not None, "a session past t=0 has run the masking check"
        self.session.resume_sensitisation(state.open.sensitisation_start_iso, state.clock_speed)
        self.session.record_masking(*state.masking)
        if state.stop_rehearsal_press_detected is not None:
            self.session.record_stop_rehearsal(state.stop_rehearsal_press_detected)
        self.session.audio.start_noise(state.masking[0])
        self.deliveries = dict(state.deliveries)
        self.f40_mn = dict(state.f40_mn)
        self.chosen_filament_label_g = dict(state.chosen_filament_label_g)
        filaments = pinprick.ladder(self.session.config)
        for phase, block_index, region, site, label in state.intolerable:
            key = phase if block_index is None else (INTERVENTION, block_index)
            self._cap(key).record(region, site, pinprick.ladder_index(filaments, label))
        for phase, point in state.mapping.items():
            if not point.area_written:
                self.ledger.restore(phase, point.starts, point.distances)
        if self.ledger.time_points:
            self.experimenter.set_mapping_phases([*self.ledger.time_points])

        index = next(i for i, stage in enumerate(self.stages) if stage.id not in stages_done)
        stage = self.stages[index]
        self.session.log("resume_stage", detail=stage.id)
        if stage.phase == INTERVENTION and stage.id != "intervention.start":
            # The garment was on when the session crashed; it is started again, with the cue.
            self.session.set_phase(INTERVENTION)
            self._deliver(lambda: self._run_stage(index))
        else:
            self._run_stage(index)
