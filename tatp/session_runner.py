"""The whole session, in order. SPEC.md 2, 7.4, 8, 9, 10.5, 12.3, 15.

`SessionRunner` is the outermost `Procedure` (`tatp/procedure.py`): it runs every protocol as a
child with `run_child`, so an interruption is always handled by the innermost procedure and the
runner itself only ever repeats one of its own waits.

**The session is a list of stages**, each one protocol at a time point, one scheduled block,
the rekindle, or one timed step. `_plan` builds it once from the configuration, and a stage logs
`stage_completed` with its id when it ends. That log line is what "completed" means for a
resume (`tatp/resume.py`): a resumed session starts at the first stage it does not find there,
and skips any later stage it does find.

1. **Setup** -- the garment fitted, the welcome screen, the stop rehearsal (SPEC.md 10.9) and
   the masking check (10.7).
2. **Touch calibration** (9), then the baseline relaxation and alertness ratings (Bilaga 1
   Table 2).
3. **Pre-sensitisation** -- the primary zone marked on the skin, then the long protocol on
   the secondary region, the short protocol on the
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
8. **Session end** -- outstanding mapping distances are prompted for once (8.4), then close;
   the program ends on the experimenter's last Next step.

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
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QApplication

from tatp import pinprick, touchcal
from tatp import resume as resumption
from tatp.clock import time_of
from tatp.interruption import EMERGENCY_STOP, PAUSED_SCREEN
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
from tatp.session import CONDITION_PHASES
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
from tatp.ui.experimenter import NOW, WAIT
from tatp.ui.participant import STANDBY_SCREEN
from tatp.units import MIN_PER_H, S_PER_MIN

# Keys in config/text/participant_*.yaml, not wording.
WELCOME_SCREEN = "welcome"
SESSION_STARTING_SCREEN = "session_starting"
END_SCREEN = "session_end"
BASELINE_INTRO_SCREEN = "intro_baseline"
# The rest between the intervention's blocks (S, 21 Oct 2026).
STANDBY_INTERVENTION_SCREEN = "standby_intervention"
# An experimenter text key, not wording: the last instruction, once the files are closed.
SESSION_COMPLETE_INSTRUCTION = "session_complete"
SESSION_ABORTED_INSTRUCTION = "session_aborted"
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
# The `log` event an experimenter's note is written as (docs/DATA_SCHEMA.md).
NOTE_EVENT = "experimenter_note"
# The `log` event of an error nothing caught (`stop_on_error`).
SOFTWARE_ERROR_EVENT = "software_error"
# `Session.set_upcoming` kinds.
BLOCK, PHASE = "block", "phase"
# What the countdown names, and the log calls the step, while the capsaicin is on and while the
# rekindle heat is on: keys of the experimenter text's `phases`, not phases of the session.
CAPSAICIN_REMOVAL = "capsaicin_removal"
REKINDLE_END = "rekindle_end"
# Keys in the experimenter text's `instructions`, not wording.
READY_TOUCH_BLOCK = "ready_touch_block"
# The stage that marks the skin before pre-sensitisation's measures (docs/LOG.md N7.F16l).
MARK_ZONE_STAGE = f"{PRE_S}.mark_zone"
SESSION_END_STAGE = "session_end"
LINE_BREAK = "\n"
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


def session_phases(schedule: Schedule) -> list[str]:
    """The session's phases in order, for the experimenter's timeline (docs/LOG.md N7.F16h):
    those the stages begin in, the rekindle drawn as part of the intervention. The schedule's,
    the same in every condition."""
    return list(dict.fromkeys(
        phase for _, phase, _ in stage_layout(schedule) if phase != REKINDLE
    ))


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
    # The stop is rehearsed before the masking check (S, 5 Oct 2026; SPEC.md 10.9).
    add("setup.stop_rehearsal", SETUP)
    add("setup.masking_check", SETUP)
    # Its own phase is set by the calibration itself.
    add("touch_calibration", SETUP)
    add("touch_calibration.baseline", TOUCH_CALIBRATION)
    # The skin the heat and the capsaicin will go on, marked before anything is measured
    # there (S, 20 Oct 2026; docs/LOG.md N7.F16l).
    add(MARK_ZONE_STAGE, PRE_S)
    time_point(PRE_S)
    # t=0 is set by the experimenter's press in this stage, so it begins in pre-S.
    add("sensitisation", PRE_S)

    capsaicin = schedule.window(CAPSAICIN)
    add("capsaicin.apply", SENSITISATION,
        Upcoming(PHASE, CAPSAICIN, capsaicin.start_min * S_PER_MIN))
    # Counted down as the capsaicin's removal, which is what is due then, not as the phase
    # after it (15 Oct 2026 pilot review).
    add("capsaicin.remove", CAPSAICIN,
        Upcoming(PHASE, CAPSAICIN_REMOVAL, capsaicin.end_min * S_PER_MIN))
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


def stage_key(stage_id: str) -> str:
    """A stage's key in the experimenter text's `stages`: what it is, whichever time point."""
    if stage_id.startswith(BLOCK + "."):
        return BLOCK
    if stage_id in (TOUCH_CALIBRATION, SENSITISATION, REKINDLE, SESSION_END_STAGE):
        return stage_id
    prefix, _, rest = stage_id.partition(".")
    return stage_id.replace(".", "_") if prefix in (CAPSAICIN, INTERVENTION) else rest


def stage_group(stage_id: str, phase: str) -> str:
    """The phase a stage is shown under, in the row of a phase's steps and in Jump to: the
    phase it begins in (`stage_layout`), as the phase row above it shows -- but the touch
    calibration's own, which it sets as it begins."""
    return TOUCH_CALIBRATION if stage_id == TOUCH_CALIBRATION else phase


def stage_names(stage_id: str, text: dict, schedule: Schedule) -> tuple[str, str]:
    """(short, full) for a stage, from the experimenter text's `stages_short` and `stages`."""
    key = stage_key(stage_id)
    values = {}
    if key == BLOCK:
        block = next(b for b in schedule.blocks if f"{BLOCK}.{b.index}" == stage_id)
        values = {"block": block.index, "type": text["terms"]["block_types"][block.type]}
    return text["stages_short"][key].format(**values), text["stages"][key].format(**values)


def stage_plan(schedule: Schedule, text: dict) -> dict[str, list[tuple[str, str, str]]]:
    """Every phase's stages in order, (id, short, full): the schedule's, the same in every
    condition (SPEC.md 16)."""
    plan: dict[str, list[tuple[str, str, str]]] = {}
    for stage_id, phase, _at in stage_layout(schedule):
        plan.setdefault(stage_group(stage_id, phase), []).append(
            (stage_id, *stage_names(stage_id, text, schedule)))
    return plan


class _QuietDeliveryStart(DeliveryStart):
    """`DeliveryStart` that leaves the experimenter screen to the runner (LOG N7.D17).

    The runner shows `touch_start` itself, for the same time in every condition; a delivery
    that did it too would put it back whenever it restarts -- after a stop, or a reconnect --
    which in the participant-preferred condition happens for as long as the press is awaited.
    `prompting` is whether the self-start prompt is up, waiting for the press. `cueing` is
    whether it has reached its warning cue: from then on the participant's screen is its own
    (the cue, the blank before the touch, the prompt), and before then -- while it ramps -- it
    shows nothing of its own.
    """

    prompting = False
    cueing = False

    def instruct(self, key: str, heading: str | None = None, **values: object) -> None:
        """Nothing on the experimenter screen."""

    def cue_then(self, then) -> None:
        self.cueing = True
        super().cue_then(then)

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

    def __init__(self, rig: Rig, channel: int, block_index: int):
        super().__init__(rig)
        self.block_index = block_index
        touch_block = self.session.config.study1["touch_block"]
        repeated = list(touch_block["repeated_scales"])
        self.plan = repeated * int(touch_block["n_repetitions"]) + list(
            touch_block["once_scales"]
        )
        self.channel = channel
        self.done_count = 0
        self.gap_s = float(touch_block["gap_s"])
        # Stage boundary (CLAUDE.md). No VAS training here: every touch scale was trained
        # during the touch calibration (SPEC.md 10.6), so the intervention never contains it.
        # A scale added to the block without being trained there is a defect, stopped here
        # before the block begins rather than rated untrained.
        untrained = [s for s in self.plan if self.session.vas_training_due(s)]
        assert not untrained, f"touch block scales {untrained} were never trained"

    def begin(self) -> None:
        def prepare() -> None:
            self.rig.show_between()
            self.experimenter.set_instruction(
                self.instruction_text(READY_TOUCH_BLOCK, block=self.block_index), NOW
            )
            self.experimenter.refresh()

        self.await_proceed(self._next, prepare)

    def _next(self) -> None:
        # "x/N answered", as in the estimation run: the same in every condition.
        self.experimenter.set_instruction(
            self.instruction_text("touch_block", answered=self.done_count,
                                  total=len(self.plan)),
            WAIT,
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
        if self.done_count == len(self.plan):
            self.finish(None)
            return
        # A blank that reads as a break before the next scale (UI_PRINCIPLES.md 1.10).
        self.blank_for(self.gap_s, self._next)


class SessionRunner(Procedure):
    """SPEC.md 2 from the garment fitting to the closing screen. See the module docstring."""

    # The id of each stage as it starts: a demonstration's Finish this stage (tatp/demo.py).
    stage_started = Signal(str)

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
        # The session's phases in order, for the experimenter's timeline (LOG N7.F16h): those
        # the stages begin in, and the rekindle as part of the intervention. The schedule's,
        # the same in every condition.
        self.phases = session_phases(self.session.schedule)
        self.experimenter.set_timeline(self.phases)
        self.experimenter.set_stage_plan(stage_plan(self.session.schedule,
                                                    self.experimenter.text))
        # Stages a resumed session found completed (`_resume`); empty for a fresh session.
        self._completed: frozenset[str] = frozenset()
        self._launch: Callable[[], None] | None = None
        # The session time the timed wait now running ends at (`_wait_until`), for skip_wait.
        self.waiting_until_s: float | None = None
        self._alarms: list[tuple[float, str]] = []
        # Every alert sounded, so a step whose alarms are set again does not sound one twice.
        self._sounded: set[str] = set()
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
        # And whether its thermode had been removed too, so only the touch is left to restart.
        self._resumed_thermode_removed = False
        self._stopping_for_error = False
        # Re-calibration, which the runner alone owns (docs/LOG.md N7.F12a1): the calibration
        # that governs the touch, run again for it (None after a crash-resume, until one runs);
        # the touch calibration's preference, which a re-calibration during the intervention
        # keeps; whether one runs there, the procedure it runs in place of, and the phase to go
        # back to; where a stop came while touch was calibrated or delivered, so that its plain
        # resume is recorded as the choice it was; the touch-back step after one, with the
        # procedure it is a step of (`_touch_restarting`); and when a wait that will stop the
        # touch falls due.
        self._calibration: TouchCalibration | None = None
        self._preference: str | None = None if resume is None else resume.preferred_pattern
        self._recalibrating = False
        self._detoured: Procedure | None = None
        self._phase_before_recalibration = INTERVENTION
        self._stop_where: str | None = None
        self._touch_back: tuple[Procedure, Callable[[], None]] | None = None
        self._touch_off_due_s: float | None = None
        # Stops during a re-calibration in the intervention count as the intervention's.
        rig.interruptions.in_intervention = self._in_intervention
        # Set when an error ended the program with the session open (`_leave_open`): nothing
        # afterwards may close it, or it could not be resumed.
        self.left_open = False

        # A protocol's own wait for the go shows what the runner shows between steps, so a
        # self-start prompt still waiting is not taken down by a block that arrives first.
        rig.show_between = self._show_between
        self.experimenter.abort_requested.connect(self.abort)
        # For the whole session, interruptions included (SPEC.md 11, 13).
        self.experimenter.note_entered.connect(self._note)
        # Connected here, before `start` connects the procedure's own handlers, so a pending
        # delivery is cancelled and restarted before any step repeats.
        self.rig.interruptions.interrupted.connect(self._delivery_interrupted)
        self.rig.interruptions.resumed.connect(self._delivery_resumed)

    def connect_actions(self) -> None:
        self.experimenter.garment_disconnect_requested.connect(self._disconnect_garment)
        self.experimenter.garment_connect_requested.connect(self._connect_garment)
        self.experimenter.recalibration_requested.connect(self._recalibrate)
        # After `Interruptions`' own, connected with the rig. Offers are worked out afresh
        # from the state at each, never withdrawn blindly, so the order the slots run in
        # cannot leave them wrong (a resume with nothing to restore ends at once).
        self.participant.emergency_stop.connect(self._stopped_now)
        self.experimenter.resume_requested.connect(self._offer_recalibration)

    def disconnect_actions(self) -> None:
        self.experimenter.garment_disconnect_requested.disconnect(self._disconnect_garment)
        self.experimenter.garment_connect_requested.disconnect(self._connect_garment)
        self.experimenter.recalibration_requested.disconnect(self._recalibrate)
        self.participant.emergency_stop.disconnect(self._stopped_now)
        self.experimenter.resume_requested.disconnect(self._offer_recalibration)

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
            # From the noise level it sets on, the noise is heard only while the garment may
            # run (`tatp.audio.NoiseGate`; S, 21 Oct 2026).
            "setup.masking_check": lambda: self._protocol(lambda: MaskingCheck(self.rig),
                                                          lambda _: self.session.noise.arm()),
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
            "mark_zone": lambda: self.await_proceed(self._stage_done,
                                                    self._standby("mark_zone", NOW)),
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
        self.experimenter.new_stage()
        self.experimenter.set_stage(stage_group(stage.id, stage.phase), stage.id)
        # After the row, so what a listener logs falls inside the stage it belongs to.
        self.stage_started.emit(stage.id)
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
        index = self.stage_index + 1
        # A resumed session completed some stages before the crash, and not always only ones
        # before the restart point: a file from before the setup order changed (5 Oct 2026)
        # has the masking check done and the rehearsal not. Those are reloaded, never rerun.
        while self.stages[index].id in self._completed:
            self.session.log("stage_skipped_completed", detail=self.stages[index].id)
            index += 1
        self._run_stage(index)

    def _protocol(self, make: Callable[[], Procedure], then=None) -> None:
        """Run a protocol as this stage; `then(result)` before the next stage begins."""

        def done(result: object) -> None:
            if then is not None:
                then(result)
            self._stage_done()

        self.run_child(make, done)

    def _standby(self, instruction: str, heading: str,
                 **values: object) -> Callable[[], None]:
        def prepare() -> None:
            self._show_between()
            self.experimenter.set_instruction(self.instruction_text(instruction, **values),
                                              heading)
            self.experimenter.set_status("")
            self.experimenter.refresh()

        return prepare

    def _show_between(self) -> None:
        """The participant's screen between steps: standby, unless the touch is starting.

        A delivery still starting owns the participant's screen -- the cue, then in the
        participant-preferred condition the self-start prompt, which is put back if a block
        took the screen in the meantime (docs/LOG.md N7.D17). Before its cue a delivery shows
        nothing of its own, so standby: after a resume, a delivery started again is ramping,
        and the stop or paused screen must not stay up through it (N7.F11c8).
        """
        if self._delivery is not None and self._delivery.prompting:
            self.participant.show_message(SELF_START_SCREEN)
        elif self._delivery is None or not self._delivery.cueing:
            self.participant.show_message(self._standby_screen())

    def _standby_screen(self) -> str:
        """The rest screen: while the intervention's touch is on, the one saying the screen
        brings what comes next, since between blocks it does (S, 21 Oct 2026); otherwise the
        one saying the experimenter will. Which follows the touch, not the condition."""
        return STANDBY_INTERVENTION_SCREEN if self._touch_on else STANDBY_SCREEN

    # == setup and touch calibration ===========================================================

    def _fit_garment(self) -> None:
        standby = self._standby("fit_garment", NOW)

        def prepare() -> None:
            standby()
            # The participant has only just sat down: nothing has happened yet to rest from.
            self.participant.show_message(SESSION_STARTING_SCREEN)

        self.await_proceed(self._stage_done, prepare)

    def _welcome(self) -> None:
        # What happens next, which the experimenter is about to see from across the divider.
        self.instruct("welcome", WAIT)
        self.run_trial(
            lambda: MessageConfirm(
                self.session, self.participant, self.experimenter,
                lambda: self.participant.show_message(WELCOME_SCREEN), WELCOME_SCREEN,
            ),
            self._stage_done,
        )

    def _touch_calibration(self) -> None:
        def calibrated(result) -> None:
            # Every condition's delivery, computed identically; which one is used is decided
            # only when the intervention starts (SPEC.md 16).
            self._calibrated(result)
            self.session.noise.want(False, "touch calibration done")
            self._offer_recalibration()

        # The garment runs through the calibration, so the noise masks it (Bilaga 3a).
        self.session.noise.want(True, "touch calibration")
        self._protocol(self._new_calibration, calibrated)

    def _new_calibration(self) -> TouchCalibration:
        """Kept: a re-calibration during the intervention runs it again."""
        calibration = TouchCalibration(self.rig, self.resume)
        self._preview(calibration)
        calibration.recalibration_changed.connect(self._offer_recalibration)
        self._calibration = calibration
        return calibration

    def _calibrated(self, result) -> None:
        self._preference = result.preferred_pattern
        self.deliveries = {
            condition: result.for_condition(condition)
            for condition in self.session.config.study1["design"]["conditions"]
        }

    def _baseline(self) -> None:
        """Bilaga 1 Table 2's baseline relaxation and alertness, with the garment off."""
        self.session.garment.stop()
        scales = list(self.session.config.study1["touch_block"]["baseline_scales"])
        gap_s = float(self.session.config.study1["touch_block"]["gap_s"])

        def rate(index: int) -> None:
            def rated(_response) -> None:
                if index + 1 == len(scales):
                    self._stage_done()
                    return
                # A blank that reads as a break before the next scale (UI_PRINCIPLES.md 1.10).
                self.blank_for(gap_s, lambda: rate(index + 1))

            self.run_trial(
                lambda: TouchRating(
                    self.session, self.participant, self.experimenter, scales[index],
                    self.reference_channel,
                ),
                rated,
            )

        def begin() -> None:
            # Introduced, like each task of the calibration before it (N7.F11c1). The
            # experimenter's line is the ratings' own: the participant is reading about them.
            self.introduce(
                BASELINE_INTRO_SCREEN,
                self.instruction_text("baseline_ratings"),
                lambda: rate(0),
            )

        # Relaxation and alertness have no training sentence today, so this gives none; it is
        # here so a scale given one later is trained at its first use like every other.
        self.train_then(scales, begin)

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
        if previous_phase not in self.f40_mn:
            # Only a demonstration that jumped past the earlier estimate gets here: started as
            # a session with no earlier estimate is (docs/LOG.md N7.D8), and said so.
            self._jump_fallback(f"{phase} starts from the configured filament: the "
                                f"{previous_phase} estimate was jumped past")
            return Prior(self.pinprick["start_filament_label_g_session1_pre_s"],
                         pinprick.CONFIG_DEFAULT)
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
        """SPEC.md 8.4. The noise is silent for the verbal exchange, as it is whenever the
        garment cannot run (`tatp.audio.NoiseGate`)."""

        def make() -> AreaMapping:
            mapping = AreaMapping(self.rig, self.ledger)
            mapping.pacing_cue.connect(self._pacing_tick)
            return mapping

        self._protocol(make)

    def _pacing_tick(self, path: int, cue: int) -> None:
        self.session.audio.pacing_tick(f"path {path}, cue {cue}")

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

        heat_min = self.session.schedule.window(SENSITISATION).duration_min
        self.await_proceed(started, self._standby("thermode_start", NOW,
                                                  minutes=f"{heat_min:g}"))

    def _capsaicin_apply(self, at: Upcoming) -> None:
        def applied() -> None:
            self.session.set_phase(CAPSAICIN)
            self._stage_done()

        self._arm(at, "capsaicin_apply", applied, waiting="heat_on")

    def _capsaicin_remove(self, at: Upcoming) -> None:
        self._arm(at, "capsaicin_remove", self._stage_done, waiting="capsaicin_on")

    def _intervention_start(self, at: Upcoming) -> None:
        hours = self.session.schedule.window(INTERVENTION).duration_min / MIN_PER_H
        self._arm(at, "intervention_start", lambda: self._deliver(self._stage_done),
                  hours=f"{hours:g}")

    def _intervention_end(self, at: Upcoming) -> None:
        """The touch off, then a wait for the experimenter: they tell the participant that it
        has finished and what comes next before the measures begin again (N7.F11c10). Until
        15 Oct 2026 the instruction was replaced by the next stage's in the same moment."""

        def ended() -> None:
            self._stop_touch("the intervention has ended")
            self.await_proceed(self._stage_done, self._standby("intervention_end", NOW))

        # A re-calibration that ends after this is due does not start the touch again only
        # for this to stop it (`_recalibrated`).
        self._touch_off_due_s = at.due_s
        self._wait_until(at.due_s, ended, self._standby("waiting", WAIT))

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
        self.session.noise.want(True, "the garment's touch")
        self._start_delivery()
        self._offer_recalibration()

        def show() -> None:
            self._show_between()
            self.experimenter.set_instruction(
                self.instruction_text(TOUCH_START_INSTRUCTION), WAIT
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
        # Standby unless a protocol has the screen: a block still waiting for its go has not
        # taken it yet (N7.F11c8).
        if self._child is None or self._child.awaiting_go:
            self.participant.show_message(self._standby_screen())
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
        if self._stop_where is not None:
            where, self._stop_where = self._stop_where, None
            touchcal.log_recalibration(self.session, resumption.RESUME_CHOICE, EMERGENCY_STOP,
                                       where, "", self._in_intervention())
        self._offer_recalibration()

    def _restart_touch(self) -> None:
        """Start the touch again -- at once, or once the block in progress has ended.

        A delivery puts its cue, and any self-start prompt, on the participant's screen, and
        inside a block that screen belongs to the block's own trial. So in a block the touch
        stays off until the block ends, and that is logged (docs/LOG.md N7.D17) -- except
        while it is being started again in a step of its own after a re-calibration, when no
        trial has the screen (`_touch_back_then`).
        """
        if self.session.block_index is None or self._touch_restarting:
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
        self._touch_off_due_s = None
        self._cancel_delivery()
        if self.session.garment.connected:
            self.session.garment.stop()
        self.session.log("garment_deactivated", detail=why)
        self.session.noise.want(False, why)
        self._offer_recalibration()

    # == re-calibration, docs/LOG.md N7.F12a1 ==================================================
    # The runner is its one owner: what is offered, the choice and its record, the
    # interruption it ends or makes, and, in the intervention, the calibration run again. A
    # touch calibration that is running says what it can offer and takes the path chosen.

    def _innermost(self) -> Procedure:
        procedure: Procedure = self
        while procedure._child is not None:
            procedure = procedure._child
        return procedure

    def _calibration_running(self) -> TouchCalibration | None:
        """The touch calibration running now, the stage or a re-calibration, if any."""
        innermost = self._innermost()
        return innermost if isinstance(innermost, TouchCalibration) else None

    def _in_intervention(self) -> bool:
        """For the session file's count: a re-calibration chosen inside one there counts too,
        though its phase is `touch_calibration`."""
        return self.session.phase in CONDITION_PHASES or self._recalibrating

    def _recalibration_where(self) -> str:
        """`<where>` of the `recalibration` event: the stage, and the calibration's step while
        one runs."""
        stage = self.stages[self.stage_index].id
        calibration = self._calibration_running()
        if calibration is None:
            return stage
        return f"{stage}{resumption.WHERE_STEP_SEPARATOR}{calibration.step_name}"

    def _recalibration_offers(self) -> tuple[bool, bool]:
        """(rebalance, restart) now. While touch is being calibrated, what the calibration can
        take; while the condition's touch is on, Restart, and Rebalance once this process has
        a calibration with targets to rebalance against (after a crash-resume, the first is a
        restart). Never past the limit, while paused, or while a resume is under way, which is
        then the only way on. Identical in every condition (SPEC.md 16)."""
        interruptions = self.rig.interruptions
        if (self.session.closed or interruptions.resuming
                or interruptions.active not in (None, EMERGENCY_STOP)
                or not touchcal.recalibration_allowed(self.session)):
            return False, False
        calibration = self._calibration_running()
        if calibration is not None:
            return calibration.recalibration_offers()
        if not self._touch_on:
            return False, False
        return self._calibration is not None and bool(self._calibration.targets), True

    def _offer_recalibration(self) -> None:
        rebalance, restart = self._recalibration_offers()
        touch = self._calibration_running() is not None or self._touch_on
        self.experimenter.set_actions_enabled(
            recalibrate_rebalance=rebalance, recalibrate_restart=restart,
            recalibration_used=(touch and not self.session.closed
                                and touchcal.recalibrations_used_up(self.session)),
        )

    def _stopped_now(self) -> None:
        """A stop while touch was calibrated or delivered: its plain resume is a choice,
        recorded where the stop came; and a stop during a resume's cue, which cancels the
        resume, offers the choice again."""
        if self.session.closed:
            return
        if self._stop_where is None and (
            self._calibration_running() is not None or self._touch_on
        ):
            self._stop_where = self._recalibration_where()
        self._offer_recalibration()

    def _recalibrate(self, choice: str, reason: str) -> None:
        """Rebalance or restart, from the controls or in place of Resume after a stop (S,
        15 Oct 2026; docs/LOG.md N7.F12a1).

        A choice no longer offered -- the state moved on while the dialog was open -- is
        logged and ignored. Otherwise it is logged and counted, and the garment goes to zero:
        the step in progress is abandoned as a stop abandons it (`Interruptions.take_over`),
        or the stop ends unrestored. A touch calibration running takes the path itself. In
        the intervention the calibration in use runs again from that path in place of the
        abandoned step (`Procedure.detour`), in phase `touch_calibration`, keeping the
        stage's preference; the session clock does not stop, so alerts sound, and a step that
        falls due meanwhile waits for it. Identical in every condition.
        """
        rebalance, restart = self._recalibration_offers()
        if not (rebalance if choice == touchcal.REBALANCE else restart):
            self.session.log("recalibration_ignored", origin="experimenter",
                             severity="warning", detail=f"{choice}: no longer offered")
            self._offer_recalibration()
            return
        assert reason in self.experimenter.text["dialogs"]["recalibration_reasons"], reason
        interruptions = self.rig.interruptions
        stopped = interruptions.active == EMERGENCY_STOP
        calibration = self._calibration_running()
        touchcal.log_recalibration(
            self.session, choice, EMERGENCY_STOP if stopped else touchcal.FROM_CONTROLS,
            self._recalibration_where(), reason, self._in_intervention(),
        )
        self._stop_where = None
        innermost = self._innermost()
        if stopped:
            interruptions.end_without_restore(choice)
        else:
            interruptions.take_over(choice)
        if calibration is not None:
            calibration.recalibrate(choice, reason)
            self._offer_recalibration()
            return
        self._recalibrating = True
        # The condition's touch stays off until the new calibration's (`_recalibrated`).
        self._cancel_delivery()
        self._redeliver = False
        self._touch_after_block = False
        self._phase_before_recalibration = self.session.phase
        if self._calibration is None:
            self._new_calibration()
        calibration = self._calibration
        assert self._preference is not None, "the intervention began with no preference"
        calibration.recalibrate_on_start(choice, reason, self._preference)
        self._detoured = innermost
        innermost.detour(lambda: calibration, self._recalibrated)
        self._offer_recalibration()

    def _recalibrated(self, result, go_on: Callable[[], None]) -> None:
        """The new calibration governs the touch from now, every condition's delivery
        computed from it identically. The touch starts again before the abandoned step is
        repeated (`_touch_back_then`) -- inside a block too, whose ratings and measures are
        made under it -- unless that step is a wait that will stop the touch, already due."""
        self._recalibrating = False
        self.session.set_phase(self._phase_before_recalibration)
        self._calibrated(result)
        self._offer_recalibration()
        procedure, self._detoured = self._detoured, None
        due = self._touch_off_due_s
        ending = due is not None and self.session.clock.t_session_s() >= due
        if self._touch_on and self.session.garment.connected and not ending:
            self._touch_back_then(procedure, go_on)
        else:
            go_on()

    def _touch_back_then(self, procedure: Procedure, go_on: Callable[[], None]) -> None:
        """The condition's touch started again, as `_deliver` starts it -- `touch_start` for
        `touch_start_display_s` on the experimenter's side in every condition, and the
        delivery's cue, and in the participant-preferred condition its self-start prompt, on
        the participant's -- then `go_on`, once a delivery not waiting on the participant has
        started the touch. A step of `procedure`, so a stop meanwhile repeats it."""

        def begin() -> None:
            if self._delivery is None:
                self._start_delivery()
            self._show_between()
            self.experimenter.set_instruction(
                self.instruction_text(TOUCH_START_INSTRUCTION), WAIT
            )
            self.experimenter.set_status("")
            self.experimenter.refresh()
            procedure._after(self.touch_start_display_s,
                             lambda: self._once_delivery_settles(back))

        def back() -> None:
            self._touch_back = None
            # As at a block's launch (N7.D17): the session never waits for the participant's
            # press, so a block can go on before the touch is started, which the data says.
            if self._delivery is not None and self.session.block_index is not None:
                self.session.log(
                    "self_start_pending_at_block", severity="warning",
                    detail=f"block {self.session.block_index} goes on after a re-calibration "
                    "before the touch was started",
                )
            go_on()

        self._touch_back = (procedure, begin)
        procedure.step(begin)

    @property
    def _touch_restarting(self) -> bool:
        """The touch-back step is the step in force: so it cannot outlive its step, whatever
        replaces or cancels that (spec-review of N7.F12a1)."""
        if self._touch_back is None:
            return False
        procedure, begin = self._touch_back
        return procedure.running and procedure._step is begin

    def _disconnect_garment(self) -> None:
        """The experimenter's Disconnect (SPEC.md 11). The session goes on; nothing is lost."""
        garment = self.session.garment
        if not garment.connected:
            return
        pending = self._delivery is not None
        self._cancel_delivery()
        garment.stop()
        # The stop's own write may have found the link lost, which the session has logged as
        # the disconnect already (docs/LOG.md N7.U16): one event, one row.
        if not garment.connected:
            self.experimenter.refresh()
            return
        garment.disconnect()
        if garment.link_lost:  # the disconnect's own zeroing write found it lost
            self.experimenter.refresh()
            return
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
                if POST_S not in self.chosen_filament_label_g:
                    # A demonstration that jumped past the post-S estimate.
                    self.chosen_filament_label_g[POST_S] = self.pinprick[
                        "start_filament_label_g_session1_pre_s"]
                    self._jump_fallback("pinprick blocks use the configured filament: the "
                                        "post-sensitisation estimate was jumped past")
                filament = self.chosen_filament_label_g[POST_S]
                self.run_child(
                    lambda: ShortProtocol(
                        self.rig, SECONDARY, filament, self._cap((INTERVENTION, block.index)),
                        block.index,
                    ),
                    self._block_ended,
                )
            else:
                self.run_child(
                    lambda: TouchBlock(self.rig, self.reference_channel, block.index),
                    self._block_ended,
                )

        self._set_alarms(at, f"block {block.index}")
        self._wait_until(at.due_s, armed, self._standby("waiting", WAIT))

    def _arm_launch(self, block: Block) -> None:
        """The experimenter's go on the armed block both launches it and starts its protocol.

        Connected before the child is started, so it runs before the child's own handler and
        every row of the block is written inside it (SPEC.md 7.4).
        """

        def launched() -> None:
            if self.rig.interruptions.active is not None:
                return  # the child ignores this press too; the next one counts
            if self._recalibrating or self._touch_restarting:
                # The block's go is withdrawn for these (`Procedure.detour`), so nothing would
                # start; the press is recorded, and the next one after them counts.
                self.session.log("proceed_ignored", origin="experimenter",
                                 detail="a re-calibration, or the touch starting after it")
                return
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
            self.await_proceed(started, self._standby("thermode_rekindle", NOW))

        def started() -> None:
            self._clear_alarms()
            self._launched(at)
            heating(self.session.clock.t_session_s())

        def heating(heat_t_s: float) -> None:
            # Counted down to the heat's end, which is the next thing to act on, not to the
            # next block (15 Oct 2026 pilot review).
            end_s = heat_t_s + duration_s
            standby = self._standby("rekindle_heating", WAIT)

            def prepare() -> None:
                self.session.set_upcoming(PHASE, REKINDLE_END, end_s)
                standby()

            # The heat's end is a step like any scheduled one (SPEC.md 7.4): alerted as due,
            # and as overdue if the thermode's removal is not confirmed within the margin.
            self._set_alarms(Upcoming(PHASE, REKINDLE_END, end_s), REKINDLE_END)
            self._wait_until(end_s, ended, prepare)

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
                heating(heat_t_s)

            self.await_proceed(confirmed, self._standby("rekindle_resumed", NOW))

        def ended() -> None:
            # The thermode comes off before the garment's touch starts again under it. The
            # heat's end is past, so the countdown goes on to the next block rather than
            # showing the heat's end due, then overdue, in the alarm colours. Its alerts are
            # armed now, beside the heat's overdue one, so a slow removal cannot make the next
            # block's due alert late.
            following = self._next_upcoming(self.stage_index + 1)
            if following is not None:
                self._set_alarms(following, self._alarm_name(following), keep=True)
            standby = self._standby("rekindle_remove", NOW)

            def prepare() -> None:
                self._show_upcoming(self.stage_index + 1)
                standby()

            self.await_proceed(removed, prepare)

        def removed() -> None:
            # Logged, so a resume after this press does not ask for it again. The next step
            # sets its own alarms as it begins; one already sounded does not sound twice.
            self.session.log(resumption.REKINDLE_THERMODE_REMOVED, origin="experimenter")
            self._clear_alarms()
            reactivate()

        def reactivate() -> None:
            self.session.set_phase(INTERVENTION)
            self._show_upcoming(self.stage_index + 1)

            def reactivated() -> None:
                self.session.log("garment_reactivated", detail="after the rekindle")
                self._stage_done()

            self._deliver(reactivated)

        if self._resumed_heat_t_s is not None:
            heat_t_s, self._resumed_heat_t_s = self._resumed_heat_t_s, None
            if self._resumed_thermode_removed:
                # The heat and the thermode's removal are both done: only the touch is left.
                self.session.log(
                    "rekindle_resumed", severity="warning",
                    detail="the thermode was removed before the crash; the touch starts again",
                )
                reactivate()
                return
            resumed_after_heat(heat_t_s)
            return
        self._set_alarms(at, REKINDLE)
        self._touch_off_due_s = at.due_s  # as at the intervention's end
        self._wait_until(at.due_s, armed, self._standby("waiting", WAIT))

    # == a demonstration's Jump to (S, 21 Oct 2026) ========================================

    def jumpable(self, stage_id: str) -> bool:
        """Whether Jump to may go to `stage_id` now: not while the session is interrupted, being
        re-calibrated or closed, and on a garment that may be worn not to the intervention's
        touch before the touch calibration has run, which only a real one may set."""
        if (self.session.closed or self.rig.interruptions.active is not None
                or self.rig.interruptions.resuming or self._recalibrating):
            return False
        return not self.needs_calibration(stage_id)

    def needs_calibration(self, stage_id: str) -> bool:
        """Whether Jump to `stage_id` waits for a real touch calibration: the intervention's
        touch on a garment that may be worn."""
        return (self.session.garment.worn and self.deliveries is None
                and self.touches(stage_id))

    def touches(self, stage_id: str) -> bool:
        """Whether the intervention's touch is on when `stage_id` begins."""
        stage = next(s for s in self.stages if s.id == stage_id)
        return stage.phase == INTERVENTION and stage_id != "intervention.start"

    def jump_to(self, stage_id: str) -> None:
        """Go straight to `stage_id`, back or forward, without running the stages between:
        a demonstration's Jump to (S, 21 Oct 2026: "it should actually skip, not fast
        forward ... keep manual/auto as it was"). Who presses is untouched.

        What is running is cancelled as an abort cancels it, and an open block is closed
        aborted. Session time moves on, never back, to where the stage would begin: its own
        scheduled time, less `demo.skip_lead_s` so its countdown is still seen, or the latest
        scheduled time before it; t=0 is set now if the stage comes after it. The garment's
        touch is on exactly as it would be there. A stage run again writes its rows again
        beside the earlier ones, which stand; the log's `demo_jump` says which came after.
        A value a jumped-past stage would have measured comes from the configured fallback,
        logged as `demo_jump_fallback`.
        """
        assert self.session.demo, "Jump to is a demonstration's"
        assert self.jumpable(stage_id), f"{stage_id} cannot be jumped to now"
        ids = [stage.id for stage in self.stages]
        index = ids.index(stage_id)
        here = self.stages[self.stage_index].id
        back = index <= self.stage_index
        self.session.log(
            "demo_jump", severity="warning",
            detail=f"from {here} to {stage_id}" + (
                "; run again, its earlier rows stand" if back else ""),
        )
        self._stop_for_jump()
        self._move_clock_to(index)
        touches = self.touches(stage_id) and not (
            stage_id == "intervention.end"
            and self.session.clock.t_session_s() >= self.stages[index].upcoming.due_s)
        if self._touch_on and not touches:
            self._stop_touch("demonstration jump")
        if not touches:
            # A touch calibration cancelled mid-way never said it was done (review of N7.F18j);
            # the stage jumped to wants the noise again itself if it runs the garment.
            self.session.noise.want(False, "demonstration jump")
        if touches and not self._touch_on:
            self._fallbacks_for_touch()
            self.session.set_phase(INTERVENTION)
            self._deliver(lambda: self._run_stage(index))
            return
        self._run_stage(index)

    def _stop_for_jump(self) -> None:
        """Everything under way stops, writing nothing more, as it does for an abort."""
        self._disarm()
        self._clear_alarms()
        if self._child is not None:
            self._child.cancel()
            self._child = None
        self._halt()
        self._step = None
        self._on_go = None
        self.waiting_until_s = None
        self._settled_then = None
        self.experimenter.hide_fit_preview()
        self.experimenter.withdraw_substitution()
        self.experimenter.offer_alternative(None)
        if self.session.block_index is not None:
            self.session.end_block(aborted=True)

    def _move_clock_to(self, index: int) -> None:
        """Session time to where stage `index` would begin, if that is later than now."""
        sensitisation = [stage.id for stage in self.stages].index(SENSITISATION)
        clock = self.session.clock
        if index > sensitisation and not clock.session_started:
            self.session.start_sensitisation()
        if not clock.session_started:
            return
        lead_s = float(self.session.config.study1["demo"]["skip_lead_s"])
        target = self.stages[index].upcoming
        earlier = [stage.upcoming.due_s for stage in self.stages[:index]
                   if stage.upcoming is not None]
        if target is not None:
            to_s = target.due_s - lead_s
        elif earlier:
            to_s = max(earlier)
        else:
            return
        ahead_s = to_s - clock.t_session_s()
        if ahead_s > 0:
            clock.skip(ahead_s)
            self.session.garment.skip(ahead_s)

    def _fallbacks_for_touch(self) -> None:
        """What the intervention's touch needs from stages jumped past: a calibration, and
        the touch scales' training, which the calibration gives."""
        if self.deliveries is None:
            calibration = self._new_calibration()
            self._calibrated(calibration.unrun_result("demonstration jump"))
            self._jump_fallback("the touch is delivered at the fallback levels: the touch "
                                "calibration was jumped past")
        scales = self.session.config.study1["touch_block"]
        untrained = [scale for scale in [*scales["repeated_scales"], *scales["once_scales"]]
                     if self.session.vas_training_due(scale)]
        if untrained:
            self.session.vas_trained.update(untrained)
            self._jump_fallback(f"no training for {', '.join(untrained)}: the touch "
                                "calibration, which gives it, was jumped past")

    def _jump_fallback(self, detail: str) -> None:
        # Stage boundary (CLAUDE.md): a session never has a stage jumped past.
        assert self.session.demo, f"a jump fallback in a session: {detail}"
        self.session.log("demo_jump_fallback", severity="warning", detail=detail)

    # == the end ===============================================================================

    def _session_end(self) -> None:
        self.session.clear_upcoming()
        # Nothing more is asked of the participant, whatever the experimenter still enters.
        self.participant.show_message(END_SCREEN)
        if self.ledger.close():
            self._finish_session()
            return

        def closing() -> None:
            self.ledger.close()
            self._finish_session()

        # The ledger has put its once-only prompt up; the next go closes the session with
        # whatever is still missing flagged (SPEC.md 8.4).
        self.await_proceed(closing, lambda: self.participant.show_message(END_SCREEN))

    def _finish_session(self) -> None:
        """Close the session, then wait for the experimenter's last Next step to end the
        program (N7.F11c9). Until 15 Oct 2026 the program ended the moment the files were
        closed, so both screens vanished and nobody saw that the data were saved.

        Every file is written before the wait, so closing the window then loses nothing, and
        an error then finds the session closed and reopens nothing (`stop_on_error`). From
        here the files take no more rows -- a note excepted, which is the experimenter's own
        record -- so the stop and the pause are let go: the garment is already off and
        disconnected, and nothing is running for them to interrupt. A stop pressed from here is
        therefore not logged, deliberately. Pause and Connect garment are disabled, so nothing
        can connect the garment again with no stop wired to it.
        """
        self.session.log("stage_completed", detail=self.stages[self.stage_index].id)
        self.completed = True
        self.finish(None)
        self._close_session("")
        self._await_end(SESSION_COMPLETE_INSTRUCTION)

    def _await_end(self, instruction_key: str) -> None:
        """The session is closed: say so, and wait for the Next step that ends the program."""
        interruptions = self.rig.interruptions
        self.participant.emergency_stop.disconnect(interruptions.emergency_stop)
        self.experimenter.pause_requested.disconnect(interruptions.pause)
        self.experimenter.distances_entered.disconnect(self.ledger.enter)
        self.experimenter.set_mapping_phases([])
        self.experimenter.set_actions_enabled(closed=True)
        # The one press after the session closed, on Finish session: it ends the program.
        self.rig.closing = True
        self.experimenter.set_instruction(self.instruction_text(instruction_key), NOW)
        self.experimenter.set_detail(self._data_check())
        self.experimenter.set_status("")
        self.experimenter.refresh()
        self._complete_shown_s = self.session.clock.real_elapsed_s()
        self.experimenter.proceed_requested.connect(self._end_program)

    def _data_check(self) -> str:
        """What was saved, anything recorded as missing, and how to upload it (SOP.md 14.2):
        under the last instruction, so the data are checked and uploaded before the program
        closes (S, 21 Oct 2026). A demonstration's data are never uploaded, and it says so."""
        words = self.experimenter.text["data_check"]
        session = self.session
        folder = session.data_folder
        # This run's own files, by the name the collection gives them: not an earlier run's.
        written = [table for table in session.files.tables
                   if session.files.path(table).exists()]
        lines = [words["saved"].format(files=len(written), folder=folder)]
        missing = self.ledger.incomplete()
        lines.append(words["missing"].format(value=self.ledger.missing_text(missing))
                     if missing else words["none_missing"])
        if session.demo:
            lines.append(words["demo"].format(folder=folder))
        else:
            lines.append(words["upload"].format(
                code=session.participant_code, session=session.session_number,
                upload_folder=session.config.hardware["data"]["upload_folder"]))
        return LINE_BREAK.join(lines)

    def _end_program(self) -> None:
        """The experimenter's last Next step, on a session already closed. A press within
        `session_end.quit_lockout_s` of the screen appearing is the second of a double press
        on the Next step before it, and would skip the screen saying the data are saved."""
        lockout_s = float(self.session.config.study1["session_end"]["quit_lockout_s"])
        if self.session.clock.real_elapsed_s() - self._complete_shown_s < lockout_s:
            return
        QApplication.instance().quit()

    def _note(self, note: str) -> None:
        """SPEC.md 11's timestamped note: written, then confirmed with the time it was written,
        so a note the experimenter sees confirmed is one that is in the log."""
        stamp = self.session.log(NOTE_EVENT, origin="experimenter", detail=note)
        self.experimenter.confirm_note(time_of(stamp))

    def stop_for_error(self, summary: str) -> None:
        """An error nothing caught, in a session still open (`stop_on_error`).

        Qt keeps its event loop running past an exception in a slot, so without this the
        session stood still with nothing on either screen to say why (the masking check, 15
        Oct 2026). Everything that could move the session on is cancelled first, so nothing
        runs under the dialog's own event loop; then the error is logged, the garment goes to
        zero and the experimenter is told. The session is then **left open, as a crash leaves
        it** (`_leave_open`), not aborted: an abort writes `session_end_iso`, and a session with
        one is never offered for resume, so the next start would have begun again from setup
        with a new t=0 (spec-review of N7.F10c). That happens whatever goes wrong on the way, so
        an error in here cannot leave the session standing.

        From touch calibration on the experimenter is told that there was an error but not
        what it was: an exception's text can name a pattern or a condition (SPEC.md 16). The
        log has it.
        """
        # A timer the error left behind can still raise under the dialog. That one is on the
        # console; the session is already being stopped.
        if self._stopping_for_error:
            return
        self._stopping_for_error = True
        try:
            self.cancel()
            self.rig.interruptions.cancel_resume()
            self.session.log(SOFTWARE_ERROR_EVENT, severity="error", detail=summary)
            if self.session.garment.connected:
                self.session.garment.stop()
            self.participant.show_message(PAUSED_SCREEN)
            dialogs = self.experimenter.text["dialogs"]
            if self.session.phase == SETUP:
                message = dialogs["software_error"].format(value=summary)
            else:
                message = dialogs["software_error_withheld"]
            self.experimenter.error_dialog(message).exec()
        finally:
            self._leave_open()

    def _leave_open(self) -> None:
        """End the program as a crash would, with the session still open to a resume (SPEC.md
        15): every row already written stays, a row a failed write held is retried, and the
        closing keys are not written. The garment and the sound are let go."""
        self.left_open = True
        self._clear_alarms()
        if self.session.garment.connected:
            self.session.garment.stop()
            self.session.garment.disconnect()
        self.session.audio.close()
        # Last, because stopping the garment writes rows of its own.
        self.session.files.release()
        if self.lock is not None:
            self.lock.release()
        QApplication.instance().quit()

    def abort(self, reason: str) -> None:
        """The experimenter's abort (SPEC.md 11). Everything collected so far is kept. Ends as a
        completed session does, on the end screen and a Next step (LOG N7.F17e): until 20 Oct
        2026 the program quit at once, and nobody saw that the data were saved.

        Nothing once the session is closed: Abort session is withdrawn then, but a dialog
        opened before the close can still be confirmed after it (code review of N7.F17e)."""
        if self.session.closed:
            return
        self.cancel()
        self.rig.interruptions.end()
        # Distances still missing are written as missing, without the end-of-session prompt.
        self.ledger.prompted = True
        self.ledger.close()
        self._close_session(reason)
        self.participant.show_message(END_SCREEN)
        self._await_end(SESSION_ABORTED_INSTRUCTION)

    def cancel(self) -> None:
        self._disarm()
        self._clear_alarms()
        self._cancel_delivery()
        super().cancel()

    def _close_session(self, abort_reason: str) -> None:
        self._clear_alarms()
        self.experimenter.refresh()
        self.session.close(abort_reason)
        if self.lock is not None:
            self.lock.release()

    # == waiting, arming and alerts (SPEC.md 7.4) ==============================================

    def _wait_until(self, t_session_s: float, then, prepare) -> None:
        """A step that waits until a session time; repeated after an interruption, it waits
        only for what is left."""

        def check() -> None:
            # A timer can fire a little early -- its milliseconds are rounded -- and a step
            # armed early could be launched before it is due, so the clock has the last word.
            remaining_s = t_session_s - self.session.clock.t_session_s()
            if remaining_s <= 0:
                self.waiting_until_s = None
                then()
            else:
                self.waiting_until_s = t_session_s
                self._after(remaining_s, check)

        def begin() -> None:
            prepare()
            check()

        self.step(begin)

    def skippable_s(self, lead_s: float) -> float | None:
        """The session seconds `skip_wait(lead_s)` would skip now, or None."""
        if self.waiting_until_s is None or self._pending is None:
            return None
        skipped_s = self.waiting_until_s - lead_s - self.session.clock.t_session_s()
        return skipped_s if skipped_s > 0 else None

    def skip_wait(self, lead_s: float) -> float | None:
        """End the timed wait now running, `lead_s` before what it waits for: a
        demonstration's Skip the wait (tatp/demo.py). Returns the session seconds skipped, or
        None when there is no wait to skip -- a protocol running, or the experimenter's go
        awaited -- or less than `lead_s` of one is left."""
        skipped_s = self.skippable_s(lead_s)
        if skipped_s is None:
            return None
        self.session.clock.skip(skipped_s)
        self.session.garment.skip(skipped_s)
        # The wait's own check and the alerts were timed for the old clock: run them now.
        self._timer.stop()
        self._fire()
        self._schedule_alarm()
        return skipped_s

    def _arm(self, at: Upcoming, instruction: str, then: Callable[[], None],
             waiting: str = "waiting", **values: object) -> None:
        """Wait until due, then wait for the experimenter's go, alerting either side of due.

        `waiting` is the instruction until then, and `values` fill `instruction`.
        """

        def go() -> None:
            self._clear_alarms()
            self._launched(at)
            # Launched: the countdown goes on to the next scheduled step rather than saying
            # this one is due, and late, while it runs.
            self._show_upcoming(self.stage_index + 1)
            then()

        self._set_alarms(at, at.label_key)
        self._wait_until(
            at.due_s,
            lambda: self.await_proceed(go, self._standby(instruction, NOW, **values)),
            self._standby(waiting, WAIT),
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
        at = self._next_upcoming(from_index) if self.session.clock.session_started else None
        if at is None:
            self.session.clear_upcoming()
        else:
            self.session.set_upcoming(at.kind, at.label_key, at.due_s, at.block)
        self.experimenter.refresh()

    def _next_upcoming(self, from_index: int) -> Upcoming | None:
        return next((stage.upcoming for stage in self.stages[from_index:]
                     if stage.upcoming is not None), None)

    @staticmethod
    def _alarm_name(at: Upcoming) -> str:
        """What an alert names its step by, as the step's own stage does."""
        return f"{BLOCK} {at.block.index}" if at.kind == BLOCK else at.label_key

    def _set_alarms(self, at: Upcoming, what: str, keep: bool = False) -> None:
        """The due alert ahead of time and the overdue one after. One already past sounds now,
        and only the latest of those, so a late arrival is not a burst of alerts; one that has
        already sounded never sounds again. `keep` adds these to the alarms already set, for
        two steps awaited at once (the rekindle's thermode, and the step after it)."""
        now_s = self.session.clock.t_session_s()
        alarms = [
            (at.due_s - self.due_lead_s, f"{what} due"),
            (at.due_s + self.overdue_margin_s, f"{what} overdue"),
        ]
        past = [alarm for alarm in alarms if alarm[0] <= now_s]
        future = [alarm for alarm in alarms if alarm[0] > now_s]
        self._alarms = sorted([*self._alarms, *future] if keep else future)
        if past and past[-1][1] not in self._sounded:
            # Now, not on a timer: a step already late may be launched before a timer fires.
            self._sound(past[-1][1])
        self._schedule_alarm()

    def _sound(self, reason: str) -> None:
        self._sounded.add(reason)
        self.session.audio.experimenter_alert(reason)

    def _schedule_alarm(self) -> None:
        self._alarm_timer.stop()
        if self._alarms:
            wait_s = max(0.0, self._alarms[0][0] - self.session.clock.t_session_s())
            self._alarm_timer.start(self.session.clock.scaled_ms(wait_s))

    def _fire_alarm(self) -> None:
        _, reason = self._alarms.pop(0)
        self._sound(reason)
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
        done = list(state.completed_stages)
        # The skin marking was added on 20 Oct 2026 (N7.F16l). A session that went past it --
        # one written before it existed, above all -- has the skin marked already, and resumed
        # there would be sent back to pre-sensitisation after t=0 (spec review).
        ids = [stage.id for stage in self.stages]
        mark = ids.index(MARK_ZONE_STAGE)
        if MARK_ZONE_STAGE not in done and any(ids.index(s) > mark for s in done if s in ids):
            done.append(MARK_ZONE_STAGE)
        self._completed = frozenset(done)
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
        # In the session's order, so the file keeps DATA_SCHEMA.md's key order.
        if "setup.stop_rehearsal" in done and state.stop_rehearsal_press_detected is not None:
            self.session.record_stop_rehearsal(state.stop_rehearsal_press_detected)
        if "setup.masking_check" in done:
            assert state.masking is not None, "a completed masking check recorded its result"
            self.session.record_masking(*state.masking)
            self.session.audio.start_noise(state.masking[0])
            # Heard again as the stage it resumes in wants it (`tatp.audio.NoiseGate`).
            self.session.noise.arm()
        # SPEC.md 10.6: training already given in this session is not given again.
        self.session.vas_trained.update(state.vas_trained)
        # docs/LOG.md N7.F12a1: counted for the whole session, across the crash.
        self.session.intervention_emergency_stops = state.intervention_emergency_stops
        self.session.intervention_recalibrations = state.intervention_recalibrations
        self.session.recalibrations = state.recalibrations
        self.session.calibrations_used = state.calibrations_used
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
                self._resumed_thermode_removed = state.rekindle_thermode_removed
            self._run_stage(index)
        elif stage.phase == INTERVENTION and stage.id != "intervention.start" and not (
            # The intervention is over: the touch it would start would be stopped again at
            # once, under the experimenter telling the participant it has finished (N7.F11c10).
            stage.id == "intervention.end"
            and self.session.clock.t_session_s() >= stage.upcoming.due_s
        ):
            # The garment was on when the session crashed; it is started again, with the cue.
            self.session.set_phase(INTERVENTION)
            self._deliver(lambda: self._run_stage(index))
        else:
            self._run_stage(index)


def stop_on_error(runner_of: Callable[[], SessionRunner | None],
                  elsewhere: Callable[[str], None]) -> None:
    """Make an error nothing caught stop the session, visibly (`SessionRunner.stop_for_error`).

    Installed by `run_session.main` and the launcher, never by the tests or the validator,
    which have their own. The traceback still goes to the console first. `runner_of` gives the
    session running now, if any; with none open, `elsewhere` is told the error instead -- the
    launcher's own window, where a Start that failed would otherwise do nothing visible.
    """
    previous = sys.excepthook

    def hook(kind, error, trace) -> None:
        previous(kind, error, trace)
        summary = "".join(traceback.format_exception_only(kind, error)).strip()
        runner = runner_of()
        if runner is not None and not runner.session.closed:
            runner.stop_for_error(summary)
        else:
            elsewhere(summary)

    sys.excepthook = hook
