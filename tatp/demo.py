"""Demonstration sessions: the software shown without a participant or the three hours.
docs/LOG.md N7.D23.

A demonstration is a real session through the real code -- the same stages, screens, garment
commands and data files -- with four things changed, and none of them able to reach study data:

- **Quarantined.** Its own participant code and allocation (`study1.yaml` `demo`), a fresh
  folder under `demo.data_folder` for each run, so a demonstration can be run again and again,
  `demo` true in the session file, and a DEMONSTRATION banner on the experimenter screen. The
  participant screen is unchanged: a demonstration shows what a participant sees (SPEC.md 16).
- **Who presses.** The participant and the experimenter are each, independently, a person, a
  simulation paced to be watched, or a simulation as fast as it can go (`OFF`, `WATCH`, `FAST`;
  `sim/responders.py`, `sim/experimenters.py`, the validator's own). Either can be changed at
  any time from the Demo controls window, so the remote can be handed between a person and the
  simulation mid-session. Every change is logged (`demo_simulation`).
- **Skip the wait.** The long timed waits -- to the next block, the rekindle, the end of the
  intervention -- end at once, `demo.skip_lead_s` before what they wait for, by moving session
  time on (`Clock.skip`). The participant's hand is not affected. Logged (`demo_wait_skipped`).
- **Finish this stage.** Both simulations run the stage now under way as fast as they can, then
  go back to what they were. A stage is finished, never skipped: what later stages need from it
  -- the touch calibration, the F40s -- comes from the real procedure, not from invented values.

`demo.clock_speed` (or `--demo-speed`) can also run every session-paced interval faster, as the
validator does; at 1 a person meets every interval as a participant would.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QComboBox, QGridLayout, QVBoxLayout, QWidget

from sim.experimenters import VirtualExperimenter
from sim.responders import VirtualParticipant
from tatp.clock import Clock
from tatp.config import REPO_ROOT, Config
from tatp.session import with_session_choices
from tatp.session_runner import SessionRunner
from tatp.ui.widgets import (
    ITEM_GAP_PX,
    MARGIN_PX,
    SIZE_BODY,
    SIZE_SMALL,
    button,
    label,
    sized,
    stylesheet,
)
from tatp.units import S_PER_MIN

OFF = "off"
WATCH = "watch"
FAST = "fast"
MODES = (OFF, WATCH, FAST)
# The garment a demonstration uses unless another is chosen: nothing is worn.
DEMO_GARMENT = "mock"


def real_time_settings(study1: dict, speed: float, scale_timeout: bool = True) -> dict:
    """`study1` with the settings that are real time scaled back, at clock speed `speed`.

    Above real speed these would otherwise describe a different session rather than a faster
    one: the adjustment time-out (the hand that adjusts runs in real seconds,
    tatp/touchcal.py), and the choice screen's feedback and gap (real milliseconds on screen).
    The validator keeps the time-out as configured for the scenario whose error path it is.
    """
    choice = {key: float(value) / speed for key, value in study1["choice"].items()}
    touch = dict(study1["touch_calibration"])
    if scale_timeout:
        touch["adjustment_timeout_s"] = float(touch["adjustment_timeout_s"]) * speed
    return {**study1, "choice": choice, "touch_calibration": touch}


def resolved(path: str) -> Path:
    """A configured path, relative to the repository unless absolute."""
    return Path(path) if Path(path).is_absolute() else REPO_ROOT / path


def demo_config(loaded: Config, speed: float, garment: str | None) -> Config:
    """The configuration a demonstration runs with: its own allocation, a fresh folder."""
    demo = loaded.study1["demo"]
    folder = resolved(demo["data_folder"]) / Clock().filename_stamp()
    config = with_session_choices(loaded, folder, garment or DEMO_GARMENT)
    design = {**config.study1["design"], "allocation_file": demo["allocation_file"]}
    study1 = {**real_time_settings(config.study1, speed), "design": design}
    return Config(**{**config.__dict__, "study1": study1})


class Demo(QObject):
    """The two simulations beside a running session, and what the Demo controls ask of them."""

    def __init__(self, runner: SessionRunner, participant_mode: str, experimenter_mode: str,
                 seed: int):
        super().__init__(runner)
        self.runner = runner
        rig = runner.rig
        self.session = rig.session
        self.settings = self.session.config.study1["demo"]
        self.participant = VirtualParticipant(
            rig.participant, self.session.garment, self.session.config, seed
        )
        # Always running: when it does not act, it still reads what each cue applied, so a
        # simulated participant beside a person at the experimenter screen can feel it.
        self.experimenter = VirtualExperimenter(rig, self.participant, parent=self)
        self.experimenter.start()
        self.participant_mode = OFF
        self.experimenter_mode = OFF
        self._before_finish: tuple[str, str] | None = None
        # Its window, kept here so it lives as long as the demonstration (run_session.py).
        self.controls: DemoControls | None = None
        runner.stage_started.connect(self._stage_started)
        self.set_participant(participant_mode)
        self.set_experimenter(experimenter_mode)

    def set_participant(self, mode: str) -> None:
        assert mode in MODES, f"no participant mode {mode!r}; one of {MODES}"
        if mode == OFF:
            self.participant.stop()
        else:
            if mode == WATCH:
                self.participant.set_pace(
                    float(self.settings["participant_reaction_s"]),
                    float(self.settings["participant_press_interval_s"]),
                )
            else:
                self.participant.set_pace(0.0, 0.0)
            if self.participant_mode == OFF:
                self.participant.start()
        self._log_mode("participant", self.participant_mode, mode)
        self.participant_mode = mode

    def set_experimenter(self, mode: str) -> None:
        assert mode in MODES, f"no experimenter mode {mode!r}; one of {MODES}"
        reaction_s = float(self.settings["experimenter_reaction_s"]) if mode == WATCH else 0.0
        self.experimenter.set_pace(mode != OFF, reaction_s)
        self._log_mode("experimenter", self.experimenter_mode, mode)
        self.experimenter_mode = mode

    def _log_mode(self, who: str, before: str, after: str) -> None:
        if before != after:
            self.session.log("demo_simulation", detail=f"{who}: {after}")

    def skip_wait(self) -> float | None:
        """End the timed wait now running; the session seconds skipped, or None."""
        skipped_s = self.runner.skip_wait(float(self.settings["skip_lead_s"]))
        if skipped_s is not None:
            self.session.log("demo_wait_skipped", detail=f"{skipped_s:.1f} s")
        return skipped_s

    def finish_stage(self) -> None:
        """Both simulations, fast, until the next stage starts; then as they were."""
        if self._before_finish is None:
            self._before_finish = (self.participant_mode, self.experimenter_mode)
        self.set_participant(FAST)
        self.set_experimenter(FAST)

    def _stage_started(self, _stage_id: str) -> None:
        if self._before_finish is not None:
            participant_mode, experimenter_mode = self._before_finish
            self._before_finish = None
            self.set_participant(participant_mode)
            self.set_experimenter(experimenter_mode)

    @property
    def finishing(self) -> bool:
        """Whether Finish this stage is running the stage now under way."""
        return self._before_finish is not None

    def stop(self) -> None:
        self.participant.stop()
        self.experimenter.stop()


class DemoControls(QWidget):
    """The Demo controls window, beside the experimenter screen. Experimenter text only."""

    def __init__(self, demo: Demo, text: dict):
        super().__init__()
        self.demo = demo
        words = text["demo"]
        self.words = words
        self.setWindowTitle(words["title"])
        self.setStyleSheet(stylesheet())

        self.participant_mode = self._modes(demo.participant_mode, demo.set_participant)
        self.experimenter_mode = self._modes(demo.experimenter_mode, demo.set_experimenter)
        self.skip_button = button(words["skip_wait"])
        self.skip_button.clicked.connect(self.skip_wait)
        self.finish_button = button(words["finish_stage"])
        self.finish_button.clicked.connect(self.finish_stage)
        self.status = label(SIZE_SMALL, wrap=True)
        demo.runner.stage_started.connect(self._sync)

        grid = QGridLayout()
        for row, (key, modes) in enumerate((("participant", self.participant_mode),
                                            ("experimenter", self.experimenter_mode))):
            who = label(SIZE_BODY)
            who.setText(words[key])
            grid.addWidget(who, row, 0)
            grid.addWidget(modes, row, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.setSpacing(ITEM_GAP_PX)
        layout.addLayout(grid)
        layout.addWidget(self.skip_button)
        layout.addWidget(self.finish_button)
        layout.addWidget(self.status)

    def _modes(self, current: str, choose) -> QComboBox:
        modes = sized(QComboBox(), SIZE_BODY)
        for mode in MODES:
            modes.addItem(self.words["modes"][mode], mode)
        modes.setCurrentIndex(MODES.index(current))
        modes.currentIndexChanged.connect(lambda index: choose(MODES[index]))
        return modes

    def skip_wait(self) -> None:
        skipped_s = self.demo.skip_wait()
        if skipped_s is None:
            self.status.setText(self.words["nothing_to_skip"])
        else:
            self.status.setText(
                self.words["skipped"].format(value=f"{skipped_s / S_PER_MIN:.1f}")
            )

    def finish_stage(self) -> None:
        self.demo.finish_stage()
        self.status.setText(self.words["finishing"])
        self._sync()

    def _sync(self, *_stage_id) -> None:
        """Show the modes the demonstration is in (Finish this stage changes them)."""
        for modes, mode in ((self.participant_mode, self.demo.participant_mode),
                            (self.experimenter_mode, self.demo.experimenter_mode)):
            modes.blockSignals(True)
            modes.setCurrentIndex(MODES.index(mode))
            modes.blockSignals(False)
        if not self.demo.finishing and self.status.text() == self.words["finishing"]:
            self.status.clear()
