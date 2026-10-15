"""Demonstration sessions: the software shown without a participant or the three hours.
docs/LOG.md N7.D23.

A demonstration is a real session through the real code -- the same stages, screens, garment
commands and data files -- with these things changed, and none of them able to reach study data:

- **Quarantined.** Its own participant code and allocation (`study1.yaml` `demo`), a fresh
  folder under `demo.data_folder` -- beside the study's `data/`, not in it -- for each run, so a
  demonstration can be run again and again, `demo` true in the session file, and a
  DEMONSTRATION banner on the experimenter screen. The participant screen is unchanged: a
  demonstration shows what a participant sees (SPEC.md 16). Each run writes its own copy of the
  allocation with the conditions shuffled across the session numbers, so a session number cannot
  be chosen to see a condition (open item L16).
- **Any garment, and any keyboard.** The mock garment unless another is chosen, as for any
  session (docs/LOG.md N7.F12f). On a worn garment -- a driver declaring `worn`, which is all
  but the mock -- a demonstration is fully manual, a conservative default for S to revisit
  (SPEC.md 13, 10.9): it runs at real time only (`check_speed`), since above it the rate limit
  is looser in real time; the participant and the experimenter are both people, never
  simulations (`check_person`) -- a simulated participant would raise pressure on someone
  else's arm, and a simulated experimenter would press Next step into garment output with
  nobody at the experimenter screen; so Finish this stage, which makes both fast, is not
  offered. What is left is the garment display and Skip the wait. As a second guard, the
  simulated experimenter never resumes an interruption by itself there either. The ceiling,
  the rate limit and the stop are the session's own, unchanged. And every keyboard is the remote
  (`any_keyboard`), so it runs on any computer, with or without the remote, and a simulated
  participant's presses arrive.
- **What the garment is doing**, channel by channel, in the Demo controls window
  (`tatp/ui/garment_display.py`), in every phase -- which lets a watcher infer the condition
  during the intervention. S asked for it, 15 Oct 2026 (open item L16); a real session's
  experimenter screen never has it.
- **Who presses.** The participant and the experimenter are each, independently, a person, a
  simulation paced to be watched, or a simulation as fast as it can go (`OFF`, `WATCH`, `FAST`;
  `sim/responders.py`, `sim/experimenters.py`, the validator's own). Either can be changed at
  any time from the Demo controls window, so the remote can be handed between a person and the
  simulation mid-session. Logged at the start and at every change (`demo_simulation`).
- **Skip the wait.** The long timed waits -- to the next block, the rekindle, the end of the
  intervention -- end at once, `demo.skip_lead_s` before what they wait for, by moving session
  time on (`Clock.skip`). The participant's hand is not affected. Logged (`demo_wait_skipped`).
- **Finish this stage.** Both simulations run the stage now under way as fast as they can, and
  a timed wait is skipped, then they go back to what they were. A stage is finished, never
  skipped: what later stages need from it -- the touch calibration, the F40s -- comes from the
  real procedure, not from invented values.

`demo.clock_speed` (or `--demo-speed`) can also run every session-paced interval faster, as the
validator does; at 1 a person meets every interval as a participant would.

The simulations are imported when a demonstration starts, so a real session never loads them.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QVBoxLayout, QWidget

from tatp.clock import Clock
from tatp.config import REPO_ROOT, Config
from tatp.remote_keys import ANY_KEYBOARD, with_key_source
from tatp.session import DRIVERS, with_session_choices
from tatp.session_runner import SessionRunner
from tatp.ui.garment_display import GarmentDisplay
from tatp.ui.widgets import (
    GROUP_GAP_PX,
    ITEM_GAP_PX,
    MARGIN_PX,
    SIZE_BODY,
    SIZE_SMALL,
    WARNING_COLOUR,
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
# A demonstration's garment unless another is chosen, and the only one nothing is worn on.
DEMO_GARMENT = "mock"
# The slowest a demonstration runs: real time, as a participant meets every interval.
REAL_TIME_SPEED = 1.0
ALLOCATION_NAME = "demo_allocation.csv"
# What a simulated experimenter records when it re-runs an estimate that cannot be used.
RERUN_REASON = "demonstration: the simulated experimenter re-ran an unusable estimate"


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


def run_folder(demo: dict) -> Path:
    """A folder of this run's own, under `demo.data_folder`: never one a run used before."""
    root = resolved(demo["data_folder"])
    stamp = Clock().filename_stamp()
    folder, n = root / stamp, 1
    while folder.exists():
        n += 1
        folder = root / f"{stamp}_{n}"
    return folder


def shuffled_allocation(template: Path, folder: Path) -> Path:
    """This run's allocation: `template` with its conditions shuffled across the sessions of
    each code, written into `folder`. Drawn from the system's entropy, and recorded only in
    the run's own files (open item L16)."""
    lines = template.read_text(encoding="utf-8").splitlines()
    comments = [line for line in lines if line.startswith("#")]
    rows = list(csv.DictReader(line for line in lines if not line.startswith("#")))
    shuffler = random.SystemRandom()
    for code in {row["participant_code"] for row in rows}:
        own = [row for row in rows if row["participant_code"] == code]
        conditions = [row["condition"] for row in own]
        shuffler.shuffle(conditions)
        for row, condition in zip(own, conditions, strict=True):
            row["condition"] = condition
    folder.mkdir(parents=True)
    path = folder / ALLOCATION_NAME
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.writelines(f"{line}\n" for line in comments)
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


class DemoError(ValueError):
    """A demonstration asked for something its settings do not allow."""


def worn_garment(garment: str) -> bool:
    """Whether someone can be wearing what the named driver commands, as the driver declares
    (`GarmentController.worn`): all but the mock."""
    if garment not in DRIVERS:
        raise DemoError(f"garment {garment!r} is not one of {sorted(DRIVERS)}")
    return DRIVERS[garment].worn


def check_speed(demo: dict, speed: float, garment: str) -> float:
    """The speed, if a demonstration may run at it: real time to `demo.max_clock_speed`, and
    real time only on a worn garment, whose rate limit is in session time (SPEC.md 13)."""
    highest = float(demo["max_clock_speed"])
    if not REAL_TIME_SPEED <= speed <= highest:
        raise DemoError(f"a demonstration runs at {REAL_TIME_SPEED:g} to {highest:g} times "
                        f"real speed (study1.yaml demo.max_clock_speed), not {speed:g}")
    if worn_garment(garment) and speed != REAL_TIME_SPEED:
        raise DemoError(f"a demonstration on the {garment} garment runs at real time "
                        f"({REAL_TIME_SPEED:g}), not {speed:g}: faster, its rate limit would "
                        f"be looser in real time (SPEC.md 13)")
    return speed


def check_person(garment: str, who: str, mode: str) -> str:
    """`who`'s mode -- the participant's or the experimenter's -- if a demonstration may run
    with it: on a worn garment, a person only. A simulated participant raises pressure in
    every adjustment, up to the ceiling, on whoever is wearing it; a simulated experimenter
    presses Next step into garment output with nobody at the experimenter screen. The
    conservative default until S decides (SPEC.md 13; docs/LOG.md N7.F12f)."""
    assert mode in MODES, f"no {who} mode {mode!r}; one of {MODES}"
    if worn_garment(garment) and mode != OFF:
        raise DemoError(f"a demonstration on the {garment} garment has a person as the "
                        f"{who}, not a simulation ({mode}): someone may be wearing it")
    return mode


def demo_config(loaded: Config, speed: float, garment: str) -> Config:
    """The configuration a demonstration is checked and run with: a folder of its own, the
    garment chosen, every keyboard the remote, real-time settings kept. Nothing is written yet:
    the folder and its shuffled allocation are made when the demonstration starts
    (`begin_run`), so a check that is refused or cancelled leaves nothing behind."""
    demo = loaded.study1["demo"]
    check_speed(demo, speed, garment)
    config = with_session_choices(loaded, run_folder(demo), garment)
    hardware = with_key_source(config.hardware, ANY_KEYBOARD)
    # The study's own folder, whose instance lock a demonstration holds
    # (`tatp.preflight.lock_folder`), so one never runs beside a session from it, or beside
    # another demonstration.
    study_folder = str(resolved(loaded.hardware["data"]["folder"]))
    hardware = {**hardware, "data": {**hardware["data"], "study_folder": study_folder}}
    study1 = real_time_settings(config.study1, speed)
    # The template until the run begins: it has the code and every session number to check.
    design = {**study1["design"], "allocation_file": str(resolved(demo["allocation_file"]))}
    study1 = {**study1, "design": design}
    return Config(**{**config.__dict__, "hardware": hardware, "study1": study1})


def begin_run(config: Config) -> Config:
    """The demonstration starting: its folder made, with its own shuffled allocation in it."""
    folder = Path(config.hardware["data"]["folder"])
    template = Path(config.study1["design"]["allocation_file"])
    design = {**config.study1["design"],
              "allocation_file": str(shuffled_allocation(template, folder))}
    return Config(**{**config.__dict__, "study1": {**config.study1, "design": design}})


class Demo(QObject):
    """The two simulations beside a running session, and what the Demo controls ask of them."""

    def __init__(self, runner: SessionRunner, participant_mode: str, experimenter_mode: str,
                 seed: int):
        super().__init__(runner)
        from sim.experimenters import VirtualExperimenter
        from sim.responders import VirtualParticipant

        self.runner = runner
        rig = runner.rig
        self.session = rig.session
        self.settings = self.session.config.study1["demo"]
        self.garment_name = self.session.config.hardware["garment"]["driver"]
        # Whether someone may be wearing it: then people are the participant and the
        # experimenter, and Finish this stage is not offered (`check_person`). Checked before
        # either simulation starts, so a refusal leaves nothing running.
        self.worn = worn_garment(self.garment_name)
        check_person(self.garment_name, "participant", participant_mode)
        check_person(self.garment_name, "experimenter", experimenter_mode)
        self.participant = VirtualParticipant(
            rig.participant, self.session.garment, self.session.config, seed
        )
        # Always running: when it does not act, it still reads what each cue applied, so a
        # simulated participant beside a person at the experimenter screen can feel it.
        self.experimenter = VirtualExperimenter(rig, self.participant, parent=self)
        self.experimenter.rerun_reason = RERUN_REASON
        if self.worn:
            # Stage boundary (CLAUDE.md): what `check_speed` refused, checked again on the
            # session actually built.
            assert self.session.clock.speed == REAL_TIME_SPEED, (
                f"a demonstration on the {self.garment_name} garment runs at real time, not "
                f"{self.session.clock.speed}"
            )
            # SPEC.md 10.9: on something that may be worn, the resume is a person's. A second
            # guard: the simulated experimenter never acts there anyway.
            self.experimenter.resumes_by_itself = False
        self.experimenter.start()
        # None until set, so the starting modes are logged too, a person's included.
        self.participant_mode: str | None = None
        self.experimenter_mode: str | None = None
        # The modes Finish this stage hands back at the next stage, by who; empty when idle.
        self._before_finish: dict[str, str] = {}
        # Its window, kept here so it lives as long as the demonstration (run_session.py).
        self.controls: DemoControls | None = None
        runner.stage_started.connect(self._stage_started)
        self.set_participant(participant_mode)
        self.set_experimenter(experimenter_mode)

    def set_participant(self, mode: str) -> None:
        check_person(self.garment_name, "participant", mode)
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
            if self.participant_mode in (None, OFF):
                self.participant.start()
        self._log_mode("participant", self.participant_mode, mode)
        self.participant_mode = mode

    def set_experimenter(self, mode: str) -> None:
        check_person(self.garment_name, "experimenter", mode)
        reaction_s = float(self.settings["experimenter_reaction_s"]) if mode == WATCH else 0.0
        self.experimenter.set_pace(mode != OFF, reaction_s)
        self._log_mode("experimenter", self.experimenter_mode, mode)
        self.experimenter_mode = mode

    def choose(self, who: str, mode: str) -> None:
        """A mode chosen in the Demo controls: kept, even past Finish this stage, which still
        hands the other back."""
        self._before_finish.pop(who, None)
        self._set(who, mode)

    def _set(self, who: str, mode: str) -> None:
        (self.set_participant if who == "participant" else self.set_experimenter)(mode)

    def _log_mode(self, who: str, before: str | None, after: str) -> None:
        if before != after:
            self.session.log("demo_simulation", detail=f"{who}: {after}")

    def skip_wait(self) -> float | None:
        """End the timed wait now running; the session seconds skipped, or None."""
        skipped_s = self.runner.skip_wait(float(self.settings["skip_lead_s"]))
        if skipped_s is not None:
            self.session.log("demo_wait_skipped", detail=f"{skipped_s:.1f} s")
        return skipped_s

    def finish_stage(self) -> None:
        """Both simulations, fast, until the next stage starts; then as they were. A timed
        wait the stage is in is skipped too, since being fast does not shorten it. Not on a
        worn garment, where both are people (`check_person`)."""
        if self.worn:
            raise DemoError(f"Finish this stage is not offered on the {self.garment_name} "
                            f"garment: the participant and the experimenter are people")
        if not self._before_finish:
            self._before_finish = {"participant": self.participant_mode,
                                   "experimenter": self.experimenter_mode}
        self.set_participant(FAST)
        self.set_experimenter(FAST)
        self.skip_wait()

    @property
    def finishing(self) -> bool:
        """Whether Finish this stage is running the stage now under way."""
        return bool(self._before_finish)

    def _stage_started(self, _stage_id: str) -> None:
        before, self._before_finish = self._before_finish, {}
        for who, mode in before.items():
            self._set(who, mode)

    def stop(self) -> None:
        self.participant.stop()
        self.experimenter.stop()
        if self.controls is not None:
            self.controls.garment_display.timer.stop()


class DemoControls(QWidget):
    """The Demo controls window, beside the experimenter screen. Experimenter text only.

    A tool window of the experimenter's: it closes with it, and never keeps the program
    running once the session's own windows are gone.
    """

    def __init__(self, demo: Demo, text: dict, parent: QWidget | None = None):
        super().__init__(parent, Qt.Tool)
        self.demo = demo
        words = text["demo"]
        self.words = words
        self.setWindowTitle(words["title"])
        self.setStyleSheet(stylesheet())

        self.participant_mode = self._modes("participant", demo.participant_mode)
        self.experimenter_mode = self._modes("experimenter", demo.experimenter_mode)
        self.skip_button = button(words["skip_wait"])
        self.skip_button.clicked.connect(self.skip_wait)
        self.finish_button = button(words["finish_stage"])
        self.finish_button.clicked.connect(self.finish_stage)
        self.status = label(SIZE_SMALL, wrap=True)
        demo.runner.stage_started.connect(self._sync)
        # First, so the status line's changing length never moves it.
        self.garment_display = GarmentDisplay(
            demo.session.garment, words, float(demo.settings["garment_display_refresh_s"]),
            float(demo.settings["garment_highlight_s"]),
        )
        # On a worn garment the participant and the experimenter are people, and so Finish
        # this stage, which makes both simulations fast, is not offered (`check_person`).
        # Fixed for the demonstration, so the note below is there from the start or never.
        self.participant_mode.setEnabled(not demo.worn)
        self.experimenter_mode.setEnabled(not demo.worn)
        self.finish_button.setEnabled(not demo.worn)
        self.worn_note = label(SIZE_SMALL, wrap=True, colour=WARNING_COLOUR)
        self.worn_note.setText(words["worn_note"])
        self.worn_note.setVisible(demo.worn)

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
        layout.addWidget(self.garment_display)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addLayout(grid)
        layout.addWidget(self.skip_button)
        layout.addWidget(self.finish_button)
        layout.addWidget(self.worn_note)
        layout.addWidget(self.status)

    def _modes(self, who: str, current: str) -> QComboBox:
        modes = sized(QComboBox(), SIZE_BODY)
        for mode in MODES:
            modes.addItem(self.words["modes"][mode], mode)
        modes.setCurrentIndex(MODES.index(current))
        modes.currentIndexChanged.connect(lambda index: self.demo.choose(who, MODES[index]))
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
