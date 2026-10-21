"""The two setup procedures before touch calibration. SPEC.md 10.7, 10.9.

**The emergency stop rehearsal** (SPEC.md 10.9) comes first (S, 5 Oct 2026), so the participant
knows the stop before anything else is asked of them. The participant presses the real stop
with the garment running and watches the session resume. It fires the real path: the stop is
`tatp/interruption.py`'s, which zeroes the garment, logs the press and shows the stop screen
exactly as it would at any other moment. This is the one procedure that expects a stop, so it
is the one that overrides `on_interrupted` and `on_resumed` (`tatp/procedure.py`): for it the
stop is the step completing, not the step being abandoned. The noise has not started yet, so
its warning cue is the visual one alone (`Audio.participant_cue`).

**The masking check** (SPEC.md 10.7), straight after. The participant sets their own
white-noise level and checks it against the garment: find the noise, start the fixed
CT-targeted pattern, then raise the noise until it covers the garment and confirm. That
confirm is the answer that the garment is covered: there is no separate question, which S
found confusing (5 Oct 2026). A participant who can still hear the garment tells the
experimenter, whose Next step records it; the noise then stops for the earplug exchange and the
participant sees `paused`, and after earplugs the check restarts from the beginning, the
attempt count carrying on. Reported again with earplugs in, the session continues, recorded as
not masked -- a limitation in the data, not a refusal.

Both run the fixed pattern, `patterns.fixed_ct_pattern`, identical in every session, so neither
carries the condition into a phase the experimenter is present for (SPEC.md 16).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QTimer

from tatp.interruption import EMERGENCY_STOP
from tatp.procedure import Procedure
from tatp.responder import Action
from tatp.touchcal import AdjustmentState, PressTiming
from tatp.trials import Cue, ExperimenterChoice, MessageConfirm, Ramp, Trial
from tatp.ui.experimenter import NOW, WAIT
from tatp.units import MS_PER_S

# Keys in the participant text file.
FIND_LEVEL = "find_level"
MASK_LEVEL = "mask_level"
SETTLED = "settled"
PAUSED_SCREEN = "paused"
# Keys in the experimenter text file's `instructions`.
FIND_INSTRUCTION = "masking_check"
MASK_INSTRUCTION = "masking_check_mask"
MASK_EARPLUGS_INSTRUCTION = "masking_check_mask_earplugs"
EARPLUGS = "earplugs"
MASKING_DONE = "masking_done"
STOP_REHEARSAL_DONE_INSTRUCTION = "stop_rehearsal_done"
INSTRUCTIONS = {FIND_LEVEL: FIND_INSTRUCTION, MASK_LEVEL: MASK_INSTRUCTION}
# Keys in the experimenter text file's `warnings`.
MASKING_FAILED = "masking_failed"
MASKING_FAILED_AFTER_EARPLUGS = "masking_failed_after_earplugs"
MASKING_AT_CEILING = "masking_at_ceiling"
STOP_REHEARSAL_SCREEN = "stop_rehearsal"
STOP_REHEARSAL_DONE_SCREEN = "stop_rehearsal_done"
# The experimenter's action, as `ExperimenterChoice` names it.
PROCEED = "proceed"
# `controls` keys of the steps' other answers (review of N7.F16).
STILL_AUDIBLE_CONTROL = "still_audible"
NO_STOP_PRESS_CONTROL = "no_stop_press"


def noise_control(adjustment: dict, audio: dict) -> dict:
    """The accelerating control of SPEC.md 10.3, in decibels.

    The hold timings describe the participant's hand and are the pressure control's own; the
    step and the rates are the noise's (`audio.white_noise_step_db`,
    `audio.noise_hold_rate_*_db_s`).
    """
    return {
        "tap_step": audio["white_noise_step_db"],
        "hold_delay_s": adjustment["hold_delay_s"],
        "hold_rate_initial_per_s": audio["noise_hold_rate_initial_db_s"],
        "hold_rate_final_per_s": audio["noise_hold_rate_final_db_s"],
        "hold_ramp_duration_s": adjustment["hold_ramp_duration_s"],
    }


class NoiseAdjustment(Trial):
    """The participant moves the noise level with the two large buttons, then confirms.

    The range is `white_noise_start_dbfs` to `white_noise_max_dbfs`: the ceiling is the top of
    the control, and `Audio.set_noise_level` enforces it again whatever asks. Every button edge
    is logged, as for the pressure adjustment (SPEC.md 10.3). Finishes with the level set.

    The masking step can instead be finished by `report_still_audible`, with None: the
    participant has said they can still hear the garment, and the experimenter reports it
    with "They can still hear it", the procedure's other answer (`MaskingCheck`; SPEC.md
    10.7). Not Next step, which never means "no" (review of N7.F16).
    """

    def __init__(self, session, participant, experimenter, screen_key: str):
        super().__init__(session, participant, experimenter)
        self.screen_key = screen_key
        # What the experimenter is told, from the step. The procedure replaces it for the
        # masking step with earplugs in, where Next step means something else.
        self.instruction = INSTRUCTIONS[screen_key]
        audio = session.audio
        self.state = AdjustmentState(
            noise_control(
                session.config.hardware["adjustment"], session.config.hardware["audio"]
            ),
            audio.start_dbfs,
            audio.max_dbfs,
            audio.noise_level_dbfs,
        )
        self._press_timing = PressTiming()
        self._tick = QTimer(self)
        # Real milliseconds: the control describes the hand, not the session (LOG N6.22).
        interval_s = float(session.config.hardware["adjustment"]["tick_interval_s"])
        self._tick.setInterval(int(round(interval_s * MS_PER_S)))
        self._tick.timeout.connect(self._on_tick)

    def start(self) -> None:
        self.listen(self.participant.adjust_pressed, self._pressed)
        self.listen(self.participant.adjust_released, self._released)
        self.listen(self.participant.adjust_confirmed, self._confirmed)
        self.participant.show_level_adjustment(self.screen_key)
        # The participant sets the level; the experimenter watches.
        self.instruct(self.instruction, WAIT)
        self._tick.start()

    def _now(self) -> float:
        return self.session.clock.real_elapsed_s()

    def _pressed(self, action_value: str, event_ms: int) -> None:
        action = Action(action_value)
        self.state.press(action, self._press_timing.pressed(action, event_ms, self._now()))
        self._log("button_down", action_value)

    def _released(self, action_value: str, event_ms: int) -> None:
        action = Action(action_value)
        self.state.release(action, self._press_timing.released(action, event_ms, self._now()))
        self._log("button_up", action_value)
        self._apply()

    def _on_tick(self) -> None:
        self.state.tick(self._now())
        self._apply()

    def _apply(self) -> None:
        if self.state.value != self.session.audio.noise_level_dbfs:
            self.session.audio.set_noise_level(self.state.value)

    def _confirmed(self) -> None:
        level = self.session.audio.noise_level_dbfs
        self.session.log(
            "noise_level_confirmed", origin="participant",
            detail=f"{self.screen_key}: {level:.1f} dBFS",
        )
        self.done(level)

    def report_still_audible(self) -> None:
        self.session.log(
            "masking_reported_audible", origin="experimenter",
            detail=f"{self.screen_key}: {self.session.audio.noise_level_dbfs:.1f} dBFS",
        )
        self.done(None)

    def _log(self, event: str, action_value: str) -> None:
        self.session.log(
            event, origin="participant",
            detail=f"{action_value} at {self.state.value:.1f} dBFS",
        )

    def _teardown(self) -> None:
        self._tick.stop()
        super()._teardown()


@dataclass(frozen=True)
class MaskingResult:
    """What the masking check measured (SPEC.md 10.7), as written to the session file."""

    level_dbfs: float
    confirmed: bool
    attempts: int
    earplugs_used: bool


class MaskingCheck(Procedure):
    """SPEC.md 10.7, steps 1 to 4. Leaves the noise running at the level chosen."""

    def __init__(self, rig):
        super().__init__(rig)
        audio = self.session.config.hardware["audio"]
        self.pressure_kpa = float(audio["masking_check_pressure_kpa"])
        self.earplugs_lockout_s = float(audio["earplugs_proceed_lockout_s"])
        pattern_name = self.session.config.study1["patterns"]["fixed_ct_pattern"]
        self.pattern = self.session.patterns[pattern_name]
        self.attempts = 0
        self.earplugs_used = False

    # -- 1. find the noise -------------------------------------------------------------

    def begin(self) -> None:
        self._find()

    def _find(self) -> None:
        audio = self.session.audio
        if audio.noise_running:
            audio.set_noise_level(audio.start_dbfs)
        else:
            audio.start_noise(audio.start_dbfs)
        # A warning from the round before earplugs is out of date once they are in.
        self.experimenter.clear_warning()
        self.run_trial(lambda: NoiseAdjustment(*self._windows(), FIND_LEVEL), self._found)

    # -- 2. start the garment ----------------------------------------------------------

    def _found(self, level_dbfs: float) -> None:
        self.session.log("masking_threshold", detail=f"easily heard at {level_dbfs:.1f} dBFS")
        levels = {channel: self.pressure_kpa for channel in self.pattern.channel_ids}
        self.run_trial(
            lambda: Ramp(*self._windows(), levels),
            lambda _: self.run_trial(lambda: Cue(*self._windows()), self._garment_on),
        )

    def _garment_on(self, _) -> None:
        self.session.garment.play_pattern(self.pattern)
        self._mask()

    # -- 3. raise to mask: the confirm is the answer -----------------------------------

    def _mask(self) -> None:
        # Counted here, not in the trial, so a step repeated after an interruption is the same
        # attempt rather than a new one.
        self.attempts += 1

        def make() -> NoiseAdjustment:
            # The report is a button of its own saying what it means -- not Next step, which
            # is the way forward everywhere else (review of N7.F16) -- offered again each time
            # the step runs, and hidden, so ignored, while an interruption is in force.
            self.experimenter.offer_alternative(
                self.experimenter.text["controls"][STILL_AUDIBLE_CONTROL])
            trial = NoiseAdjustment(*self._windows(), MASK_LEVEL)
            if self.earplugs_used:
                trial.instruction = MASK_EARPLUGS_INSTRUCTION
            return trial

        self.run_trial(make, self._masked)

    def connect_actions(self) -> None:
        self.experimenter.alternative_requested.connect(self._reported_audible)

    def disconnect_actions(self) -> None:
        self.experimenter.alternative_requested.disconnect(self._reported_audible)
        self.experimenter.offer_alternative(None)

    def _reported_audible(self) -> None:
        if (not isinstance(self._trial, NoiseAdjustment) or self._child is not None
                or self.rig.interruptions.active is not None):
            return
        # Logged once, as `masking_reported_audible` (spec review of N7.F17e: a second row).
        self._trial.report_still_audible()

    def _masked(self, level_dbfs: float | None) -> None:
        self.experimenter.offer_alternative(None)
        if level_dbfs is None:
            self._escalate()
            return
        self.session.log(
            "masking_attempt",
            detail=f"attempt {self.attempts}: covered at {level_dbfs:.1f} dBFS",
        )
        if self.session.audio.at_ceiling:
            # The confirm keeps its meaning, but a level the participant could not raise
            # further may be covering the garment only just, or not: visible in the data and
            # to the experimenter, who can ask.
            self.session.log(
                "masking_at_ceiling", severity="warning",
                detail=f"confirmed at the ceiling, {level_dbfs:.1f} dBFS",
            )
            self.experimenter.set_warning(self.experimenter.text["warnings"][MASKING_AT_CEILING])
        self._done(confirmed=True)

    # -- 4. still audible: earplugs ----------------------------------------------------

    def _escalate(self) -> None:
        warnings = self.experimenter.text["warnings"]
        if self.earplugs_used:
            self.session.log(
                "masking_not_confirmed", severity="warning",
                detail=f"still audible with earplugs after {self.attempts} attempts",
            )
            self.experimenter.set_warning(warnings[MASKING_FAILED_AFTER_EARPLUGS])
            self._done(confirmed=False)
            return
        self.session.garment.stop()
        self.session.log(
            "masking_escalated", severity="warning",
            detail=f"still audible after {self.attempts} attempts"
            + (", at the ceiling" if self.session.audio.at_ceiling else ""),
        )
        self.session.audio.stop_noise("earplug exchange")
        self.experimenter.set_warning(warnings[MASKING_FAILED])

        def hold_off() -> None:
            # A Next step this soon after the report is the same click again -- a double
            # click -- not "the earplugs are in", which takes longer than this to be true.
            self.participant.show_message(PAUSED_SCREEN)
            self.experimenter.set_instruction(self.instruction_text(EARPLUGS), NOW)
            self.experimenter.refresh()
            self._after(self.earplugs_lockout_s, self._offer_earplugs)

        self.step(hold_off)

    def _offer_earplugs(self) -> None:
        self.run_trial(
            lambda: ExperimenterChoice(
                *self._windows(), {PROCEED: self.experimenter.proceed_requested},
                EARPLUGS,
                show=lambda: self.participant.show_message(PAUSED_SCREEN),
            ),
            self._earplugs_fitted,
        )

    def _earplugs_fitted(self, _) -> None:
        self.earplugs_used = True
        self.session.log("earplugs_fitted", origin="experimenter")
        # From step 1, because earplugs move the participant's threshold as well as the
        # garment's loudness (SPEC.md 10.7). The attempt count carries on.
        self._find()

    # -- the end -----------------------------------------------------------------------

    def _done(self, confirmed: bool) -> None:
        self.session.garment.stop()
        result = MaskingResult(
            level_dbfs=self.session.audio.noise_level_dbfs,
            confirmed=confirmed,
            attempts=self.attempts,
            earplugs_used=self.earplugs_used,
        )
        self.session.record_masking(
            result.level_dbfs, result.confirmed, result.attempts, result.earplugs_used
        )
        self.session.log(
            "masking_result",
            severity="info" if confirmed else "warning",
            detail=f"{result.level_dbfs:.1f} dBFS, confirmed {confirmed}, "
            f"{result.attempts} attempts, earplugs {result.earplugs_used}",
        )
        def show() -> None:
            self.participant.show_audio_setup(SETTLED)
            # Next step does nothing here, so the instruction that offered it is replaced.
            self.instruct(MASKING_DONE, WAIT)

        self.run_trial(
            lambda: MessageConfirm(*self._windows(), show, SETTLED),
            lambda _: self.finish(result),
        )

    def _windows(self) -> tuple:
        return self.session, self.participant, self.experimenter


class AwaitStop(Trial):
    """The rehearsal screen, with the garment running, waiting for the press (SPEC.md 10.9).

    It never sees the press itself: the stop is `Interruptions`', and the rehearsal learns of
    it as an interruption. What this trial listens for is the experimenter's Proceed, the one
    way out if the participant cannot press -- which finishes it with no press detected.
    """

    def start(self) -> None:
        # On a button saying what it records, not Next step (review of N7.F16).
        self.listen(self.experimenter.alternative_requested, lambda: self.done(False))
        self.experimenter.offer_alternative(
            self.experimenter.text["controls"][NO_STOP_PRESS_CONTROL])
        self.participant.show_message(STOP_REHEARSAL_SCREEN)
        self.instruct("stop_rehearsal", WAIT)

    def _teardown(self) -> None:
        super()._teardown()
        self.experimenter.offer_alternative(None)


@dataclass(frozen=True)
class StopRehearsalResult:
    press_detected: bool


class StopRehearsal(Procedure):
    """SPEC.md 10.9: the participant presses the real stop once, garment running, and sees the
    session resume."""

    def __init__(self, rig):
        super().__init__(rig)
        study1 = self.session.config.study1
        self.pattern = self.session.patterns[study1["patterns"]["fixed_ct_pattern"]]
        self.pressure_kpa = study1["training"]["stop_rehearsal_pressure_kpa"]
        self.awaiting = False
        self.press_detected = False
        self.done_shown = False

    def begin(self) -> None:
        self.session.log("stop_rehearsal_started")
        self.run_trial(lambda: Cue(*self._windows()), self._garment_on)

    def _garment_on(self, _) -> None:
        if self.pressure_kpa is None:
            # Local item L11: the pressure is S's, and none has been set. The real stop path
            # still runs; nothing is commanded that nobody chose.
            self.session.log(
                "stop_rehearsal_no_pressure", severity="warning",
                detail="training.stop_rehearsal_pressure_kpa is unset (L11); no pressure "
                "commanded",
            )
            self._play(None)
            return
        levels = {channel: float(self.pressure_kpa) for channel in self.pattern.channel_ids}
        self.run_trial(lambda: Ramp(*self._windows(), levels), self._play)

    def _play(self, _) -> None:
        self.session.garment.play_pattern(self.pattern)
        self.awaiting = True
        # A stop from here is the one expected, and the screen says so calmly.
        self.experimenter.set_rehearsal(True)
        self.run_trial(lambda: AwaitStop(*self._windows()), self._no_press)

    # -- the expected stop -------------------------------------------------------------

    def on_interrupted(self, kind: str) -> None:
        # Whatever the interruption, the step in progress is abandoned as usual.
        super().on_interrupted(kind)
        if self.awaiting and kind == EMERGENCY_STOP:
            # The rehearsal's own step completing. `Interruptions` has already zeroed the
            # garment, logged the press and shown the stop screen -- the same path as at any
            # other moment in the session.
            self.awaiting = False
            self.press_detected = True
            self.session.log("stop_rehearsal_press_detected", origin="participant")
            self.instruct("stop_rehearsal_resume", NOW)

    def on_resumed(self) -> None:
        if not self.press_detected or self.done_shown:
            # A pause, or a stop at any other point: repeat the step, as everywhere.
            super().on_resumed()
            return
        # The resume is the point, and it is shown (SPEC.md 10.9): `Interruptions` has
        # restored the garment in front of the participant, preceded by the cue. The done
        # screen follows; an interruption during it repeats it like any other step, and is an
        # ordinary stop again.
        self.done_shown = True
        self.experimenter.set_rehearsal(False)

        def show() -> None:
            self.participant.show_message(STOP_REHEARSAL_DONE_SCREEN)
            # The Resume this instruction asked for has been pressed.
            self.instruct(STOP_REHEARSAL_DONE_INSTRUCTION, WAIT)

        self.run_trial(
            lambda: MessageConfirm(*self._windows(), show, STOP_REHEARSAL_DONE_SCREEN),
            lambda _: self._end(),
        )

    def _no_press(self, _) -> None:
        self.awaiting = False
        self.session.log(
            "stop_rehearsal_no_press", origin="experimenter", severity="warning",
            detail="the experimenter moved on without a stop press",
        )
        self._end()

    def cancel(self) -> None:
        self.experimenter.set_rehearsal(False)
        super().cancel()

    def _end(self) -> None:
        self.experimenter.set_rehearsal(False)
        self.session.garment.stop()
        self.participant.show_blank()
        self.session.record_stop_rehearsal(self.press_detected)
        self.experimenter.set_instruction("")
        self.finish(StopRehearsalResult(self.press_detected))

    def _windows(self) -> tuple:
        return self.session, self.participant, self.experimenter
