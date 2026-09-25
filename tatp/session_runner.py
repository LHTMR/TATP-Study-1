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

import random
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
from tatp.schedule import Block, Schedule
from tatp.setup_checks import MaskingCheck, StopRehearsal
from tatp.touchcal import (
    SELF_START_SCREEN,
    TOUCH_START_INSTRUCTION,
    DeliveryStart,
    TouchCalibration,
    TouchRating,
)
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


def stage_layout(schedule: Schedule) -> list[tuple[str, str, Upcoming | None]]:
    """Every stage of the session in order: (id, the phase it begins in, what is scheduled).

    A function of the schedule alone, so the launcher's resume offer can say what a crashed
    session had completed without building a session (`run_session.resume_summary`).
    """
    stages: list[tuple[str, str, Upcoming | None]] = []

    def add(stage_id: str, phase: str, upcoming: Upcoming | None = None) -> None:
        stages.append((stage_id, phase, upcoming))

    def time_point(phase: str) -> None:
        # One time point's pain measures, in Bilaga 1 Table 1's order (docs/LOG.md N7.D2).
        add(f"{phase}.long", phase)
        if phase in MAPPED:
            add(f"{phase}.mapping", phase)
        for measure in ("short_primary", "brush_secondary", "brush_primary"):
            add(f"{phase}.{measure}", phase)

    add("setup.garment", SETUP)
    add("setup.welcome", SETUP)
    add("setup.masking_check", SETUP)
    add("setup.stop_rehearsal", SETUP)
    # Its own phase is set by the calibration itself.
    add("touch_calibration", SETUP)
    add("touch_calibration.baseline", TOUCH_CALIBRATION)
    time_point(PRE_S)
    # t=0 is set by the experimenter's press in this stage, so it begins in pre-S.
    add("sensitisation", PRE_S)

    capsaicin = schedule.window(CAPSAICIN)
    add("capsaicin.apply", SENSITISATION,
        Upcoming(PHASE, CAPSAICIN, capsaicin.start_min * S_PER_MIN))
    add("capsaicin.remove", CAPSAICIN, Upcoming(PHASE, POST_S, capsaicin.end_min * S_PER_MIN))
    time_point(POST_S)

    intervention = schedule.window(INTERVENTION)
    add("intervention.start", INTERVENTION,
        Upcoming(PHASE, INTERVENTION, intervention.start_min * S_PER_MIN))
    rekindle = schedule.window(REKINDLE)
    rekindle_at = Upcoming(REKINDLE, REKINDLE, rekindle.start_min * S_PER_MIN)
    # A rekindle outside the intervention divides nothing (SPEC.md 7.1): piloting may run
    # without one.
    rekindle_pending = intervention.start_min <= rekindle.start_min < intervention.end_min
    for block in sorted(schedule.blocks, key=lambda b: (b.planned_offset_min, b.index)):
        if rekindle_pending and block.planned_offset_min >= rekindle.start_min:
            add(REKINDLE, INTERVENTION, rekindle_at)
            rekindle_pending = False
        add(f"{BLOCK}.{block.index}", INTERVENTION,
            Upcoming(BLOCK, BLOCK, block.planned_offset_s, block))
    if rekindle_pending:
        add(REKINDLE, INTERVENTION, rekindle_at)
    add("intervention.end", INTERVENTION,
        Upcoming(PHASE, POST_I, intervention.end_min * S_PER_MIN))
    time_point(POST_I)
    add("session_end", POST_I)
    return stages


class _QuietDeliveryStart(DeliveryStart):
    """`DeliveryStart` that leaves the experimenter screen to the runner (LOG N7.D17).

    The runner shows `touch_start` itself, for the same time in every condition; a delivery
    that did it too would put it back whenever it restarts -- after a stop, or a reconnect --
    which in the participant-preferred condition happens for as long as the press is awaited.
    `prompting` is whether the self-start prompt is up, waiting for the press.
    """

    prompting = False

    def instruct(self, key: str, **values: object) -> None:
        """Nothing on the experimenter screen."""

    def _cued(self) -> None:
        super()._cued()
        self.prompting = not self.ended


def summary_phase(stage_id: str) -> str:
    """The phase a stage belongs to, for saying what a session has completed."""
    prefix = stage_id.split(".")[0]
    return INTERVENTION if prefix in (BLOCK, REKINDLE) else prefix


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

        self.touch_start_display_s = float(config.study1["delivery"]["touch_start_display_s"])
        # Stage boundary (CLAUDE.md). A delivery ramps to its pressures under the rate limit,
        # then cues; the ramp is longer for a higher pressure, and pressure differs by
        # condition. If the experimenter's display ended before the slowest possible delivery
        # had started the touch, when the session moved on would depend on the condition
        # (SPEC.md 16), and a block could begin before its touch.
        garment = config.hardware["garment"]
        slowest_s = float(garment["pressure_ceiling_kpa"]) / float(
            garment["pressure_rate_max_kpa_s"]
        ) + float(config.study1["cues"]["warning_lead_s"])
        assert self.touch_start_display_s >= slowest_s, (
            f"study1.yaml: delivery.touch_start_display_s ({self.touch_start_display_s} s) is "
            f"shorter than the slowest touch start, a full ramp to the ceiling plus the cue "
            f"({slowest_s:.2f} s)"
        )
        # The condition's touch: whether it should be running, and the delivery that is
        # starting it, until the garment is running (docs/LOG.md N7.D17).
        self._touch_on = False
        self._delivery: _QuietDeliveryStart | None = None
        # What the experimenter side does once that delivery has started the touch.
        self._settled_then: Callable[[], None] | None = None
        self._redeliver = False
        self._touch_after_block = False
        # Set for a session resumed after its rekindle heat was launched (LOG N7.D14).
        self._resumed_heat_t_s: float | None = None

        self.experimenter.abort_requested.connect(self.abort)
        # Connected here, before `start` connects the procedure's own handlers, so a pending
        # delivery is cancelled and restarted before any step repeats.
        self.rig.interruptions.interrupted.connect(self._delivery_interrupted)
        self.rig.interruptions.resumed.connect(self._delivery_resumed)

    def connect_actions(self) -> None:
        self.experimenter.garment_disconnect_requested.connect(self._disconnect_garment)
        self.experimenter.garment_connect_requested.connect(self._connect_garment)

    def disconnect_actions(self) -> None:
        self.experimenter.garment_disconnect_requested.disconnect(self._disconnect_garment)
        self.experimenter.garment_connect_requested.disconnect(self._connect_garment)

    # == the plan ==============================================================================

    def _plan(self) -> list[Stage]:
        stages = [
            Stage(stage_id, phase, self._begin_for(stage_id, upcoming), upcoming)
            for stage_id, phase, upcoming in stage_layout(self.session.schedule)
        ]
        # Stage boundary (CLAUDE.md): a resume identifies stages by id.
        ids = [stage.id for stage in stages]
        assert len(set(ids)) == len(ids), f"stage ids repeat: {ids}"
        assert sum(s.id.startswith(BLOCK + ".") for s in stages) == len(
            self.session.schedule.blocks
        )
        return stages

    def _begin_for(self, stage_id: str, at: Upcoming | None) -> Callable[[], None]:
        """What each stage of `stage_layout` does."""
        fixed = {
            "setup.garment": self._fit_garment,
            "setup.welcome": self._welcome,
            "setup.masking_check": lambda: self._protocol(lambda: MaskingCheck(self.rig)),
            "setup.stop_rehearsal": lambda: self._protocol(lambda: StopRehearsal(self.rig)),
            "touch_calibration": self._touch_calibration,
            "touch_calibration.baseline": self._baseline,
            "sensitisation": self._sensitisation,
            "capsaicin.apply": lambda: self._capsaicin_apply(at),
            "capsaicin.remove": lambda: self._capsaicin_remove(at),
            "intervention.start": lambda: self._intervention_start(at),
            REKINDLE: lambda: self._rekindle(at),
            "intervention.end": lambda: self._intervention_end(at),
            "session_end": self._session_end,
        }
        if stage_id in fixed:
            return fixed[stage_id]
        if stage_id.startswith(BLOCK + "."):
            return lambda: self._block(at.block, at)
        phase, measure = stage_id.split(".")
        primary_g = self.pinprick["primary_filament_label_g"]
        return {
            "long": lambda: self._long(phase),
            "mapping": self._mapping,
            "short_primary": lambda: self._protocol(
                lambda: ShortProtocol(self.rig, PRIMARY, primary_g, self._cap(phase))
            ),
            "brush_secondary": lambda: self._protocol(
                lambda: BrushProtocol(self.rig, SECONDARY)
            ),
            "brush_primary": lambda: self._protocol(lambda: BrushProtocol(self.rig, PRIMARY)),
        }[measure]

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
        # Each stage draws from a stream of its own, derived from the seed and the stage id
        # (docs/LOG.md N7.D13). A string seed is hashed the same in every process, unlike
        # `hash()`, so a session is reproducible from its seed alone, and a resume draws for
        # every stage after the crash exactly what an uninterrupted session would have.
        self.session.rng = random.Random(f"{self.session.rng_seed}:{stage.id}")
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
            self._show_between()
            self.experimenter.set_instruction(
                self.experimenter.text["instructions"][instruction]
            )
            self.experimenter.set_status("")
            self.experimenter.refresh()

        return prepare

    def _show_between(self) -> None:
        """The participant's screen between steps: standby, unless the touch is starting.

        A delivery still starting owns the participant's screen -- the cue, then in the
        participant-preferred condition the self-start prompt, which is put back if a block
        took the screen in the meantime (docs/LOG.md N7.D17).
        """
        if self._delivery is None:
            self.participant.show_message(STANDBY_SCREEN)
        elif self._delivery.prompting:
            self.participant.show_message(SELF_START_SCREEN)

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
            self._stop_touch("the intervention has ended")
            self.experimenter.set_instruction(
                self.experimenter.text["instructions"]["intervention_end"]
            )
            self.experimenter.refresh()
            self._stage_done()

        self._wait_until(at.due_s, ended, self._standby("waiting"))

    # == the intervention ======================================================================

    def _deliver(self, then: Callable[[], None]) -> None:
        """Start the condition's touch (SPEC.md 12.3), the same on the experimenter's side in
        every condition (SPEC.md 16, docs/LOG.md N7.D17).

        The experimenter screen shows `touch_start` for `touch_start_display_s`, then the
        session goes on; it never waits for the participant. The delivery runs on the
        participant's side alone: the pressures, the cue, and either the pattern at once or,
        in the participant-preferred condition, the self-start prompt until they press.
        """
        self._touch_on = True
        self._start_delivery()

        def show() -> None:
            self._show_between()
            self.experimenter.set_instruction(
                self.experimenter.text["instructions"][TOUCH_START_INSTRUCTION]
            )
            self.experimenter.set_status("")
            self.experimenter.refresh()
            self._after(self.touch_start_display_s, lambda: self._once_delivery_settles(then))

        self.step(show)

    def _once_delivery_settles(self, then: Callable[[], None]) -> None:
        """Go on once a delivery that is not waiting for the participant has started the touch.

        So a block never begins before the touch it is measured under. Such a delivery ramps
        to its pressures and plays its warning cue, and `touch_start_display_s` is asserted at
        construction to cover the longest possible ramp plus the cue, so at real speed this
        never waits and the experimenter-side timing is the same in every condition. On an
        accelerated clock the two timers can fire in either order, and this fixes the order. A
        self-start delivery is never waited for, since it waits on the participant (N7.D17).
        """
        if self._delivery is not None and not self._delivery.self_start:
            self._settled_then = then
            return
        then()

    def _start_delivery(self) -> None:
        """The two reads of the condition: which delivery, and whether it is self-started."""
        assert self.deliveries is not None, "the touch calibration has not delivered a result"
        self._cancel_delivery()
        condition = self.session.condition
        trial = _QuietDeliveryStart(
            self.session, self.participant, self.experimenter, self.deliveries[condition],
            condition == SELF_STARTED,
        )
        self._delivery = trial
        trial.finished.connect(lambda _latency: self._delivered(trial))
        trial.start()

    def _delivered(self, trial: _QuietDeliveryStart) -> None:
        if trial is not self._delivery:
            return
        self._delivery = None
        self.session.log("garment_activated")
        if self._child is None:
            self.participant.show_message(STANDBY_SCREEN)
        if self._settled_then is not None:
            then, self._settled_then = self._settled_then, None
            then()

    def _cancel_delivery(self) -> None:
        # A step waiting on the cancelled delivery is repeated from its start, not continued.
        self._settled_then = None
        if self._delivery is not None:
            trial, self._delivery = self._delivery, None
            trial.cancel()

    def _delivery_interrupted(self, kind: str) -> None:
        # A delivery is not a step of any procedure, so the interruption's own machinery does
        # not reach it: cancelled here, and started afresh once the session resumes.
        if self._delivery is not None:
            self._cancel_delivery()
            self._redeliver = True

    def _delivery_resumed(self) -> None:
        if self._redeliver:
            self._redeliver = False
            self._restart_touch()

    def _restart_touch(self) -> None:
        """Start the touch again -- at once, or once the block in progress has ended.

        A delivery puts its cue, and any self-start prompt, on the participant's screen, and
        inside a block that screen belongs to the block's own trial. So in a block the touch
        stays off until the block ends, and that is logged (docs/LOG.md N7.D17).
        """
        if self.session.block_index is None:
            self._start_delivery()
            return
        self._touch_after_block = True
        self.session.log(
            "touch_restart_deferred", severity="warning",
            detail=f"block {self.session.block_index} is running; the touch restarts after it",
        )

    def _block_ended(self, _result: object = None) -> None:
        """The block's protocol is done: close the block, restart a deferred touch through the
        same experimenter-side sequence as any touch start, then the next stage."""
        self.session.end_block()
        restart = self._touch_after_block and self._touch_on
        self._touch_after_block = False
        if restart and self.session.garment.connected:
            self._deliver(self._stage_done)
        else:
            self._stage_done()

    def _stop_touch(self, why: str) -> None:
        """The condition's touch off: for the rekindle and at the intervention's end."""
        self._touch_on = False
        self._cancel_delivery()
        if self.session.garment.connected:
            self.session.garment.stop()
        self.session.log("garment_deactivated", detail=why)

    def _disconnect_garment(self) -> None:
        """The experimenter's Disconnect (SPEC.md 11). The session goes on; nothing is lost."""
        garment = self.session.garment
        if not garment.connected:
            return
        pending = self._delivery is not None
        self._cancel_delivery()
        garment.stop()
        garment.disconnect()
        self.session.log(
            "garment_disconnected", origin="experimenter", severity="warning",
            detail="touch was starting" if pending else "",
        )
        self.experimenter.refresh()

    def _connect_garment(self) -> None:
        """The experimenter's Connect. If the condition's touch should be running, it is
        started again, through the delivery, with its cue and any self-start."""
        garment = self.session.garment
        if garment.connected:
            return
        garment.connect()
        self.session.log("garment_connected", origin="experimenter")
        if self._touch_on:
            self._restart_touch()
        self.experimenter.refresh()

    def _block(self, block: Block, at: Upcoming) -> None:
        def armed() -> None:
            self._arm_launch(block)
            if block.type == "pinprick":
                filament = self.chosen_filament_label_g[POST_S]
                self.run_child(
                    lambda: ShortProtocol(
                        self.rig, SECONDARY, filament, self._cap((INTERVENTION, block.index))
                    ),
                    self._block_ended,
                )
            else:
                self.run_child(
                    lambda: TouchBlock(self.rig, self.reference_channel), self._block_ended
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
            if self._delivery is not None and self._delivery.prompting:
                # docs/LOG.md N7.D17: the block runs, its screens take the participant's, and
                # the touch is still not started without the press; the prompt returns after.
                self.session.log(
                    "self_start_pending_at_block", severity="warning",
                    detail=f"block {block.index} began before the touch was started",
                )

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
            self.session.set_phase(REKINDLE)
            self._stop_touch(REKINDLE)
            self.await_proceed(started, self._standby("thermode_rekindle"))

        def started() -> None:
            self._clear_alarms()
            self._launched(at)
            heating(self.session.clock.t_session_s(), "thermode_rekindle")

        def heating(heat_t_s: float, instruction: str) -> None:
            self._show_upcoming(self.stage_index + 1)
            self._wait_until(heat_t_s + duration_s, ended, self._standby(instruction))

        def resumed_after_heat(heat_t_s: float) -> None:
            # docs/LOG.md N7.D14: the heat was already launched before the crash. It is never
            # prompted again; the experimenter confirms, and the garment stays off meanwhile.
            self.session.set_phase(REKINDLE)
            self._stop_touch(REKINDLE)
            self.session.log(
                "rekindle_resumed", severity="warning",
                detail=f"the heat was launched at {heat_t_s / S_PER_MIN:.2f} min, before the "
                "crash; not prompted again, and timed from then",
            )
            def confirmed() -> None:
                self.session.log("rekindle_heat_confirmed", origin="experimenter")
                heating(heat_t_s, "rekindle_resumed")

            self.await_proceed(confirmed, self._standby("rekindle_resumed"))

        def ended() -> None:
            self.session.set_phase(INTERVENTION)

            def reactivated() -> None:
                self.session.log("garment_reactivated", detail="after the rekindle")
                self._stage_done()

            self._deliver(reactivated)

        if self._resumed_heat_t_s is not None:
            heat_t_s, self._resumed_heat_t_s = self._resumed_heat_t_s, None
            resumed_after_heat(heat_t_s)
            return
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
        self._cancel_delivery()
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
        """SPEC.md 15, before t=0 as after it (docs/LOG.md N7.D16): what was completed is
        reloaded, not redone, and the session goes on from the first stage that was not."""
        state = self.resume
        done = state.completed_stages
        self.session.log(
            "session_resumed", severity="warning",
            detail=f"from {state.open.session_file.name}; {len(done)} stages completed",
        )
        if state.in_progress is not None:
            self.session.log(
                "stage_redone", severity="warning",
                detail=f"{state.in_progress} was in progress at the crash; any rows it wrote "
                f"in {state.current_file} are superseded by this session's",
            )
        if state.after_t_zero:
            self.session.resume_sensitisation(
                state.open.sensitisation_start_iso, state.clock_speed
            )
        if "setup.masking_check" in done:
            assert state.masking is not None, "a completed masking check recorded its result"
            self.session.record_masking(*state.masking)
            self.session.audio.start_noise(state.masking[0])
        if "setup.stop_rehearsal" in done and state.stop_rehearsal_press_detected is not None:
            self.session.record_stop_rehearsal(state.stop_rehearsal_press_detected)
        if "touch_calibration" in done:
            assert state.deliveries is not None, "a completed calibration wrote its channels"
            self.deliveries = dict(state.deliveries)
        # Only estimates whose protocol completed: a row written just before the crash, by a
        # stage that is now redone, is not the time point's estimate.
        for phase in (PRE_S, POST_S, POST_I):
            if f"{phase}.long" in done and phase in state.f40_mn:
                self.f40_mn[phase] = state.f40_mn[phase]
                self.chosen_filament_label_g[phase] = state.chosen_filament_label_g[phase]
        filaments = pinprick.ladder(self.session.config)
        for phase, block_index, region, site, label in state.intolerable:
            key = phase if block_index is None else (INTERVENTION, block_index)
            self._cap(key).record(region, site, pinprick.ladder_index(filaments, label))
        for phase, point in state.mapping.items():
            if not point.area_written:
                self.ledger.restore(phase, point.starts, point.distances)
        if self.ledger.time_points:
            self.experimenter.set_mapping_phases([*self.ledger.time_points])

        index = next(i for i, stage in enumerate(self.stages) if stage.id not in done)
        stage = self.stages[index]
        self.session.log("resume_stage", detail=stage.id)
        if stage.id == REKINDLE:
            # The garment stays off until the rekindle completes, and heat already launched is
            # never prompted a second time (docs/LOG.md N7.D14).
            if state.in_progress == REKINDLE:
                self._resumed_heat_t_s = state.rekindle_heat_t_s
            self._run_stage(index)
        elif stage.phase == INTERVENTION and stage.id != "intervention.start":
            # The garment was on when the session crashed; it is started again, with the cue.
            self.session.set_phase(INTERVENTION)
            self._deliver(lambda: self._run_stage(index))
        else:
            self._run_stage(index)
