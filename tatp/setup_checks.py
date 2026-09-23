"""The two setup procedures before touch calibration. SPEC.md 10.7, 10.9.

**The masking check** (SPEC.md 10.7). The participant sets their own white-noise level and
checks it against the garment: find the noise, start the fixed CT-targeted pattern, raise the
noise until it covers the garment, then say whether the garment is still audible. When raising
can no longer help, the experimenter is alerted audibly and on screen, the noise stops for the
earplug exchange and the participant sees `paused`; after earplugs the check restarts from the
beginning, the attempt count carrying on rather than resetting. A session that still cannot be
masked continues, recorded as not masked -- a limitation in the data, not a refusal.

**The emergency stop rehearsal** (SPEC.md 10.9), straight after. The participant presses the
real stop with the garment running and watches the session resume. It fires the real path: the
stop is `tatp/interruption.py`'s, which zeroes the garment, logs the press and shows the stop
screen exactly as it would at any other moment. This is the one procedure that expects a stop,
so it is the one that overrides `on_interrupted` and `on_resumed` (`tatp/procedure.py`): for it
the stop is the step completing, not the step being abandoned.

Both run the fixed pattern, `patterns.fixed_ct_pattern`, identical in every session, so neither
carries the condition into a phase the experimenter is present for (SPEC.md 16).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QTimer

from tatp.interruption import EMERGENCY_STOP
from tatp.procedure import Procedure
from tatp.responder import Action
from tatp.touchcal import AdjustmentState
from tatp.trials import Choice, Cue, ExperimenterChoice, MessageConfirm, Ramp, Trial
from tatp.ui.participant import SIDES
from tatp.units import MS_PER_S

# Keys in the participant text file.
FIND_LEVEL = "find_level"
MASK_LEVEL = "mask_level"
SETTLED = "settled"
STILL_AUDIBLE = "still_audible"
PAUSED_SCREEN = "paused"
STOP_REHEARSAL_SCREEN = "stop_rehearsal"
STOP_REHEARSAL_DONE_SCREEN = "stop_rehearsal_done"
# The experimenter's action, as `ExperimenterChoice` names it.
PROCEED = "proceed"


def noise_control(adjustment: dict, audio: dict) -> dict:
    """The accelerating control of SPEC.md 10.3, in decibels.

    The tap and hold timings describe the participant's hand and are the pressure control's
    own; the step and the rates are the noise's (`audio.white_noise_step_db`,
    `audio.noise_hold_rate_*_db_s`).
    """
    return {
        "tap_max_duration_s": adjustment["tap_max_duration_s"],
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
    """

    def __init__(self, session, participant, experimenter, screen_key: str):
        super().__init__(session, participant, experimenter)
        self.screen_key = screen_key
        audio = session.audio
        self.state = AdjustmentState(
            noise_control(
                session.config.hardware["adjustment"], session.config.hardware["audio"]
            ),
            audio.start_dbfs,
            audio.max_dbfs,
            audio.noise_level_dbfs,
        )
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
        self.instruct("masking_check")
        self._tick.start()

    def _now(self) -> float:
        return self.session.clock.real_elapsed_s()

    def _pressed(self, action_value: str) -> None:
        self.state.press(Action(action_value), self._now())
        self._log("button_down", action_value)

    def _released(self, action_value: str) -> None:
        self.state.release(Action(action_value), self._now())
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
    """SPEC.md 10.7, steps 1 to 5. Leaves the noise running at the level chosen."""

    def __init__(self, rig):
        super().__init__(rig)
        audio = self.session.config.hardware["audio"]
        self.pressure_kpa = float(audio["masking_check_pressure_kpa"])
        self.max_attempts = int(audio["masking_check_max_attempts"])
        pattern_name = self.session.config.study1["patterns"]["fixed_ct_pattern"]
        self.pattern = self.session.patterns[pattern_name]
        self.attempts = 0
        self.round_attempts = 0
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
        self.round_attempts = 0
        self.run_trial(
            lambda: NoiseAdjustment(*self._windows(), FIND_LEVEL), self._found
        )

    # -- 2. start the garment ----------------------------------------------------------

    def _found(self, level_dbfs: float) -> None:
        self.session.log("masking_threshold", detail=f"just audible at {level_dbfs:.1f} dBFS")
        levels = {channel: self.pressure_kpa for channel in self.pattern.channel_ids}
        self.run_trial(
            lambda: Ramp(*self._windows(), levels),
            lambda _: self.run_trial(lambda: Cue(*self._windows()), self._garment_on),
        )

    def _garment_on(self, _) -> None:
        self.session.garment.play_pattern(self.pattern)
        self._raise()

    # -- 3 and 4. raise to mask, then check --------------------------------------------

    def _raise(self) -> None:
        self.run_trial(lambda: NoiseAdjustment(*self._windows(), MASK_LEVEL), self._raised)

    def _raised(self, level_dbfs: float) -> None:
        self.attempts += 1
        self.round_attempts += 1
        self.session.log(
            "masking_attempt",
            detail=f"attempt {self.attempts} at {level_dbfs:.1f} dBFS",
        )
        self.run_trial(lambda: Choice(*self._windows(), STILL_AUDIBLE), self._answered)

    def _answered(self, side: str) -> None:
        # The affirmative is on the left (SPEC.md 10.7): "yes, I can still hear it".
        if side != SIDES[0]:
            self._done(confirmed=True)
        elif self.round_attempts < self.max_attempts and not self.session.audio.at_ceiling:
            self._raise()
        else:
            self._escalate()

    # -- 5. escalate -------------------------------------------------------------------

    def _escalate(self) -> None:
        warnings = self.experimenter.text["warnings"]
        if self.earplugs_used:
            self.session.log(
                "masking_not_confirmed", severity="warning",
                detail=f"still audible with earplugs after {self.attempts} attempts",
            )
            self.experimenter.set_status(warnings["masking_failed_after_earplugs"])
            self._done(confirmed=False)
            return
        self.session.garment.stop()
        self.session.log(
            "masking_escalated", severity="warning",
            detail=f"after {self.attempts} attempts"
            + (", at the ceiling" if self.session.audio.at_ceiling else ""),
        )
        self.session.audio.experimenter_alert("masking check failed")
        self.session.audio.stop_noise("earplug exchange")
        self.experimenter.set_status(warnings["masking_failed"])
        self.run_trial(
            lambda: ExperimenterChoice(
                *self._windows(), {PROCEED: self.experimenter.proceed_requested},
                "earplugs",
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
        self.run_trial(
            lambda: MessageConfirm(
                *self._windows(),
                lambda: self.participant.show_audio_setup(SETTLED),
                SETTLED,
            ),
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
        self.listen(self.experimenter.proceed_requested, lambda: self.done(False))
        self.participant.show_message(STOP_REHEARSAL_SCREEN)
        self.instruct("stop_rehearsal")


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
            text = self.experimenter.text["instructions"]["stop_rehearsal_resume"]
            self.experimenter.set_instruction(text)
            self.experimenter.refresh()

    def on_resumed(self) -> None:
        if not self.press_detected or self.done_shown:
            # A pause, or a stop at any other point: repeat the step, as everywhere.
            super().on_resumed()
            return
        # The resume is the point, and it is shown (SPEC.md 10.9): `Interruptions` has
        # restored the garment in front of the participant, preceded by the cue. The done
        # screen follows; an interruption during it repeats it like any other step.
        self.done_shown = True
        self.run_trial(
            lambda: MessageConfirm(
                *self._windows(),
                lambda: self.participant.show_message(STOP_REHEARSAL_DONE_SCREEN),
                STOP_REHEARSAL_DONE_SCREEN,
            ),
            lambda _: self._end(),
        )

    def _no_press(self, _) -> None:
        self.awaiting = False
        self.session.log(
            "stop_rehearsal_no_press", origin="experimenter", severity="warning",
            detail="the experimenter moved on without a stop press",
        )
        self._end()

    def _end(self) -> None:
        self.session.garment.stop()
        self.participant.show_blank()
        self.session.record_stop_rehearsal(self.press_detected)
        self.experimenter.set_instruction("")
        self.finish(StopRehearsalResult(self.press_detected))

    def _windows(self) -> tuple:
        return self.session, self.participant, self.experimenter
