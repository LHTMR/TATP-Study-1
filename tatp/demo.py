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
  else's arm, and a simulated experimenter would press Next into garment output with nobody
  at the experimenter screen; and Jump to does not reach the intervention's touch before a
  real touch calibration has run. As a second guard, the simulated experimenter never
  resumes an interruption by itself there either. The ceiling,
  the rate limit and the stop are the session's own, unchanged. The remote alone is the remote
  when it is plugged in, as in a session (`demo_key_source`); every keyboard otherwise, so it
  runs on any computer. A simulated participant's presses arrive either way.
- **Shorter waits** (`demo_wait_s`; S, 22 Oct 2026): every wait shorter than a session's
  lasts long enough to read -- 3 s for one up to a minute, 5 s for a longer one -- and the
  demo panel says the session's length beside it. The rests between applications and on the
  mock garment the estimation run's window and settle (`demo_rests`), and each scheduled wait,
  which the demonstration ends at its length (`Demo._watch_wait`). What a demonstration shows
  is what happens, not the waiting.
- **What the garment is doing**, channel by channel, in the experimenter window's channel
  display (`tatp/ui/garment_display.py`), in every phase -- which lets a watcher infer the
  condition during the intervention. S asked for it, 15 Oct 2026 (open item L16); a real
  session's display is withheld then.
- **The controls, along the foot of the experimenter window** (`DemoControls`; S, 20 Oct
  2026: "the demo controls should be integrated into the main window"). Each says what it
  would do now, or why it can do nothing:
  - **Who presses.** The participant and the experimenter are each, independently, manual (a
    person), auto and paced to be watched, or auto as fast as it can go (`OFF`, `WATCH`,
    `FAST`; `sim/responders.py`, `sim/experimenters.py`, the validator's own), changeable at
    any time, so the remote can be handed between a person and the simulation mid-session.
    Logged at the start and at every change (`demo_simulation`).
  - **Jump to** goes straight to any step of any phase, back or forward, without running the
    steps between and with who presses left as it is (S, 21 Oct 2026: it replaced Skip and
    Fast-forward). Session time moves on to where the step would begin, never back
    (`SessionRunner.jump_to`). A step run again writes its rows beside the earlier ones; a
    value a skipped step would have measured -- the touch calibration, an F40 -- comes from
    the configured fallback, flagged in the log. Logged (`demo_jump`, `demo_jump_fallback`).
  - The clock's speed, explained, and the remote's buttons lit as they arrive.

`demo.clock_speed` (or `--demo-speed`) can also run every session-paced interval faster, as the
validator does; at 1 a person meets every interval as a participant would.

The simulations are imported when a demonstration starts, so a real session never loads them.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

import shiboken6
from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tatp.clock import Clock
from tatp.config import REPO_ROOT, Config
from tatp.devices import KEY_SOURCE_CHANGE
from tatp.pinprick import _Series
from tatp.remote_keys import ANY_KEYBOARD, RAW_INPUT, remote_present, with_key_source
from tatp.responder import Action
from tatp.session import DRIVERS, with_session_choices
from tatp.session_runner import SessionRunner, stage_group, stage_names
from tatp.touchcal import EstimationPresentation
from tatp.ui.experimenter import BLINDED_PHASES, clock_text
from tatp.ui.garment_display import states_from_status
from tatp.ui.participant import ParticipantWindow
from tatp.ui.widgets import (
    BACKGROUND,
    CONTROL_BORDER,
    DEMO_BANNER_COLOUR,
    DEMO_COLOUR,
    FOREGROUND,
    GROUP_GAP_PX,
    ITEM_GAP_PX,
    SIZE_BODY,
    SIZE_SMALL,
    WARNING_COLOUR,
    button,
    label,
    sized,
    stylesheet,
)
from tatp.units import MS_PER_S

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
# The remote's buttons as the demo controls draw them.
REMOTE_PADDING_PX = 3
REMOTE_RADIUS_PX = 4
# Half the outline, so a one-pixel line lands on whole pixels.
REMOTE_OUTLINE_INSET_PX = 0.5
# `demo.session_differs` keys for what the step under way does differently (`differs_now`).
ESTIMATION_DIFFERS = "estimation"
RESTS_DIFFER = "rests"
# A scheduled wait, shortened (`Demo.wait_lengths`): said with its own lengths.
WAITS_DIFFER = "waits"
GARMENT_DIFFERS = "garment"
# The suffix of the whole explanation of each, shown on hover.
DETAIL = "_detail"
# How many characters of a step's name Jump to shows before cutting it.
JUMP_LIST_CHARACTERS = 20


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


def demo_wait_s(demo: dict, session_s: float) -> float:
    """How long a wait of `session_s` in a session lasts in a demonstration (S, 22 Oct 2026):
    as it is if no longer than `demo.short_wait_s`, else that, or `demo.long_wait_s` past
    `demo.long_wait_from_s` -- long enough to read what is up, never the waiting itself."""
    short_s = float(demo["short_wait_s"])
    if session_s <= short_s:
        return session_s
    return short_s if session_s <= float(demo["long_wait_from_s"]) else float(
        demo["long_wait_s"])


def demo_rests(study1: dict, garment: str) -> dict:
    """`study1` with a demonstration's rests (`demo_wait_s`; LOG N7.F14b, N7.F14e, N7.F16g,
    N7.F18aa): between pinprick and brush applications, and on the mock garment the touch
    calibration's estimation window and the settle before each of its scales. A worn garment
    keeps the study's window and settle, which cover a real sleeve's ramp and inflation. The
    demonstration's `rest_s` and `estimation_window_s`, and the session's beside them, are what
    the demo controls say (`session_differs`)."""
    demo = study1["demo"]
    rest_s = demo_wait_s(demo, float(study1["pinprick"]["isi_min_s"]))
    pinprick = {**study1["pinprick"], "isi_min_s": rest_s, "isi_max_s": rest_s}
    brush = {**study1["brush"], "isi_min_s": rest_s, "isi_max_s": rest_s}
    touch = study1["touch_calibration"]
    session = {"isi_min_s": float(study1["pinprick"]["isi_min_s"]),
               "isi_max_s": float(study1["pinprick"]["isi_max_s"]),
               "estimation_window_s": float(touch["estimation_window_s"])}
    if not worn_garment(garment):
        touch = {**touch,
                 "estimation_window_s": demo_wait_s(demo, float(touch["estimation_window_s"])),
                 "estimation_settle_s": demo_wait_s(demo, float(touch["estimation_settle_s"]))}
    return {**study1, "touch_calibration": touch, "pinprick": pinprick, "brush": brush,
            "demo": {**demo, "session": session, "rest_s": rest_s,
                     "estimation_window_s": float(touch["estimation_window_s"])}}


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


def demo_key_source(responder: dict) -> str:
    """Which keyboards are the remote in a demonstration: the remote alone when it is plugged
    in and Raw Input can tell it apart, as in a session -- so the laptop's keys do not answer
    for the participant, and the remote still answers while another program has focus (S, 20
    Oct 2026; docs/LOG.md N7.F16a). Every keyboard otherwise, so a demonstration still runs
    on any computer. A simulated participant's presses are marked as the remote's, and reach
    the participant under either (`sim/responders.py`)."""
    if responder["key_source"] == RAW_INPUT and remote_present(responder):
        return RAW_INPUT
    return ANY_KEYBOARD


def demo_config(loaded: Config, speed: float, garment: str) -> Config:
    """The configuration a demonstration is checked and run with: a folder of its own, the
    garment chosen, every keyboard the remote, real-time settings kept. Nothing is written yet:
    the folder and its shuffled allocation are made when the demonstration starts
    (`begin_run`), so a check that is refused or cancelled leaves nothing behind."""
    demo = loaded.study1["demo"]
    check_speed(demo, speed, garment)
    config = with_session_choices(loaded, run_folder(demo), garment)
    source = demo_key_source(config.hardware["responder"])
    hardware = with_key_source(config.hardware, source)
    # Recorded as the hardware page records it (`hardware_changed`, docs/LOG.md N7.F12e3), so
    # the session file says which keyboards counted (spec review).
    if config.hardware["responder"]["key_source"] != source:
        changed = [name for name in config.hardware.get("changed_at_launch", "").split(";")
                   if name]
        if KEY_SOURCE_CHANGE not in changed:
            changed.append(KEY_SOURCE_CHANGE)
        hardware = {**hardware, "changed_at_launch": ";".join(changed)}
    # The study's own folder, whose instance lock a demonstration holds
    # (`tatp.preflight.lock_folder`), so one never runs beside a session from it, or beside
    # another demonstration.
    study_folder = str(resolved(loaded.hardware["data"]["folder"]))
    hardware = {**hardware, "data": {**hardware["data"], "study_folder": study_folder}}
    study1 = demo_rests(real_time_settings(config.study1, speed), garment)
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
    """The two simulations beside a running session, and what the demo controls ask of them."""

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
        # experimenter (`check_person`).
        # Checked before either simulation starts, so a refusal leaves nothing running.
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
        # Its controls, kept here so they live as long as the demonstration (run_session.py).
        self.controls: DemoControls | None = None
        self.set_participant(participant_mode)
        self.set_experimenter(experimenter_mode)

        # The garment's own commanded state on the experimenter screen, in every phase, read
        # often enough that a pattern's steps are seen as they happen (N7.F12f, N7.F16i).
        self._display = rig.experimenter.garment_display
        rig.experimenter.garment_fed_elsewhere = True
        self._display.setToolTip(session_differs(
            self.session.config.experimenter_text, self.settings
        )[f"{GARMENT_DIFFERS}{DETAIL}"])
        self._garment_timer = QTimer(self)
        self._garment_timer.setInterval(
            int(round(float(self.settings["garment_display_refresh_s"]) * MS_PER_S))
        )
        self._garment_timer.timeout.connect(self._feed_garment)
        self._garment_timer.start()
        self._feed_garment()
        # Each scheduled wait lasts `demo_wait_s` of its session length, then ends (S, 22 Oct
        # 2026): (the session time it waits until, the real time it began, its demo and
        # session lengths), or None while no wait runs.
        self._wait: tuple[float, float, float, float] | None = None
        self._wait_timer = QTimer(self)
        self._wait_timer.setInterval(
            int(round(float(self.settings["controls_refresh_s"]) * MS_PER_S)))
        self._wait_timer.timeout.connect(self._watch_wait)
        self._wait_timer.start()

    def _watch_wait(self) -> None:
        """End the scheduled wait under way once its demonstration length has passed."""
        until_s = self.runner.waiting_until_s
        now_s = self.session.clock.t_session_s()
        if until_s is None or now_s is None or self.session.closed:
            self._wait = None
            return
        if self._wait is None or self._wait[0] != until_s:
            session_s = until_s - now_s
            self._wait = (until_s, self.session.clock.real_elapsed_s(),
                          demo_wait_s(self.settings, session_s), session_s)
        _, began_s, demo_s, session_s = self._wait
        if demo_s < session_s and self.session.clock.real_elapsed_s() - began_s >= demo_s:
            self.skip_wait(0.0)

    def wait_lengths(self) -> tuple[float, float] | None:
        """(demonstration, session) seconds of the scheduled wait under way, where the
        demonstration shortens it; None otherwise."""
        if self._wait is None or self._wait[2] >= self._wait[3]:
            return None
        return self._wait[2], self._wait[3]

    def _feed_garment(self) -> None:
        if not shiboken6.isValid(self._display):
            self._garment_timer.stop()
            return
        garment = self.session.garment
        self._display.show_states(
            states_from_status(garment.status(), garment.channels(), bool(garment.connected),
                               garment.per_channel_pressure),
            bool(garment.link_lost),
        )
        self._display.setVisible(True)

    def differs_now(self) -> str | None:
        """Which of `session_differs` the step under way shows, or None where it runs as a
        session would: the estimation run's window on the mock, a pinprick or brush series'
        rests, the channel display through the phases a session hides it in."""
        procedure = self.runner
        while procedure._child is not None:
            procedure = procedure._child
        if isinstance(procedure._trial, EstimationPresentation) and not self.worn:
            return ESTIMATION_DIFFERS
        if isinstance(procedure, _Series):
            return RESTS_DIFFER
        if self.wait_lengths() is not None:
            return WAITS_DIFFER
        if self.session.phase in BLINDED_PHASES:
            return GARMENT_DIFFERS
        return None

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
        """A mode chosen in the demo controls."""
        (self.set_participant if who == "participant" else self.set_experimenter)(mode)

    def _log_mode(self, who: str, before: str | None, after: str) -> None:
        if before != after:
            self.session.log("demo_simulation", detail=f"{who}: {after}")

    def skip_wait(self, lead_s: float | None = None) -> float | None:
        """End the timed wait now running, `lead_s` (`demo.skip_lead_s` unless given) before
        what it waits for; the session seconds skipped, or None."""
        lead_s = float(self.settings["skip_lead_s"]) if lead_s is None else lead_s
        skipped_s = self.runner.skip_wait(lead_s)
        if skipped_s is not None:
            self.session.log("demo_wait_skipped", detail=f"{skipped_s:.1f} s")
        return skipped_s

    def jump(self, stage_id: str) -> None:
        """Straight to `stage_id` (`SessionRunner.jump_to`), who presses left as it is."""
        self.runner.jump_to(stage_id)

    def stop(self) -> None:
        self.participant.stop()
        self.experimenter.stop()
        self._garment_timer.stop()
        self._wait_timer.stop()
        if self.controls is not None:
            self.controls.timer.stop()


class RemoteButtons(QWidget):
    """The remote's four buttons in a row, each filled while held: a press is seen to arrive
    (S, 20 Oct 2026: with Notepad in front the R400's presses were lost, and nothing showed
    it). Which button, never what a press meant -- and in a demonstration only."""

    def __init__(self, symbols: dict[Action, str], parent: QWidget | None = None):
        super().__init__(parent)
        sized(self, SIZE_BODY)
        self.symbols = symbols
        self.held: set[Action] = set()
        metrics = self.fontMetrics()
        self._box_px = metrics.height() + 2 * REMOTE_PADDING_PX
        self.setFixedSize(len(symbols) * (self._box_px + ITEM_GAP_PX), self._box_px)

    def set_held(self, action: Action, held: bool) -> None:
        if held != (action in self.held):
            (self.held.add if held else self.held.discard)(action)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for index, (action, symbol) in enumerate(self.symbols.items()):
            box = QRectF(index * (self._box_px + ITEM_GAP_PX), 0, self._box_px, self._box_px)
            down = action in self.held
            painter.setPen(QPen(QColor(FOREGROUND if down else CONTROL_BORDER), 1))
            painter.setBrush(QColor(DEMO_COLOUR if down else BACKGROUND))
            inset = REMOTE_OUTLINE_INSET_PX
            painter.drawRoundedRect(box.adjusted(inset, inset, -inset, -inset),
                                    REMOTE_RADIUS_PX,
                                    REMOTE_RADIUS_PX)
            painter.setPen(QColor(BACKGROUND if down else FOREGROUND))
            painter.drawText(box, Qt.AlignCenter, symbol)
        painter.end()


class _RemoteWatch(QObject):
    """Lights the remote's buttons as the participant window receives them."""

    def __init__(self, participant, buttons: RemoteButtons, parent: QObject | None = None):
        super().__init__(parent)
        self.participant = participant
        self.buttons = buttons

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt's name
        kind = event.type()
        if kind in (QEvent.KeyPress, QEvent.KeyRelease) and not event.isAutoRepeat():
            action = self.participant._action(event)
            if action is not None and shiboken6.isValid(self.buttons):
                self.buttons.set_held(action, kind == QEvent.KeyPress)
        return False


class ModeSwitch(QWidget):
    """Who presses for one role: a person, a watchable simulation or a fast one, as three
    buttons of which one is down. Changeable at any moment (S, 20 Oct 2026; LOG N7.F17d)."""

    def __init__(self, names: dict[str, str], choose, parent: QWidget | None = None):
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for mode in MODES:
            made = button(names[mode])
            made.setCheckable(True)
            made.clicked.connect(lambda _checked, mode=mode: choose(mode))
            self.group.addButton(made)
            self.buttons[mode] = made
            row.addWidget(made)

    def show_mode(self, mode: str) -> None:
        self.buttons[mode].setChecked(True)

    def mode(self) -> str:
        return next(mode for mode, made in self.buttons.items() if made.isChecked())


def session_differs(text: dict, demo: dict) -> dict[str, str]:
    """How this demonstration differs from a session, each with the session's own value, by
    where it is shown (S, 20 Oct 2026: "The demo should state somewhere what changes are made
    in the demo and how it is in the real thing", then "not one info dump but embedded where
    relevant"; LOG N7.F17d). `demo` is the demonstration's `study1.demo`, which carries the
    session's values (`demo_rests`), so neither side drifts from what runs."""
    session = demo["session"]
    values = {"demo": f"{float(demo['rest_s']):g}", "low": f"{session['isi_min_s']:g}",
              "high": f"{session['isi_max_s']:g}"}
    estimation = {"demo": f"{float(demo['estimation_window_s']):g}",
                  "session": f"{session['estimation_window_s']:g}"}
    # Each panel line is short, its `_detail` the whole of it on hover.
    return {key: line.format(**(estimation if key.startswith(ESTIMATION_DIFFERS) else values))
            for key, line in text["demo"]["session_differs"].items()}


class DemoControls(QWidget):
    """The demonstration's controls along the foot of the experimenter window (S, 20 Oct
    2026; LOG N7.F16j, N7.F17d). Experimenter text only.

    Each says what it would do now, or why it can do nothing: who presses for each role,
    switched at any moment; Jump to any step of any phase,
    in session order. The clock's speed is said and explained, and the remote's buttons light
    as they arrive. How the demo differs
    from a session is said where it applies: the step under way's timing or garment display
    on the panel while it runs, the rest on the controls they concern (`session_differs`).
    """

    def __init__(self, demo: Demo, text: dict, symbols: dict[Action, str],
                 participant: ParticipantWindow | None = None, parent: QWidget | None = None):
        """`participant` is the window whose remote presses light `symbols`; none in a
        picture of the controls."""
        super().__init__(parent)
        self.demo = demo
        self.text = text
        words = text["demo"]
        self.words = words
        # Its chosen buttons in the demonstration's own colour (UI_PRINCIPLES.md 3.7).
        self.setStyleSheet(stylesheet() + f"QPushButton:checked {{ background-color: "
                                          f"{DEMO_BANNER_COLOUR}; color: {FOREGROUND}; }}")

        self.participant_mode = ModeSwitch(words["modes"],
                                           lambda mode: self._choose("participant", mode))
        self.experimenter_mode = ModeSwitch(words["modes"],
                                            lambda mode: self._choose("experimenter", mode))
        # Every step of every phase, in session order (S, 21 Oct 2026).
        self.jump_list = sized(QComboBox(), SIZE_SMALL)
        # As wide as a step's usual name; a longer one is cut, whole in the open list.
        self.jump_list.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.jump_list.setMinimumContentsLength(JUMP_LIST_CHARACTERS)
        self.jump_list.setToolTip(words["jump_detail"])
        self.jump_button = button(words["jump_go"])
        self.jump_button.setToolTip(words["jump_detail"])
        self.jump_button.clicked.connect(self.jump_now)
        self._jump_entries: list[tuple[str, str, bool]] = []
        # A step chosen in the list is kept; until one is, the list follows the session.
        self._jump_chosen = False
        self.jump_list.activated.connect(self._jump_picked)
        self.clock = label(SIZE_SMALL, colour=DEMO_COLOUR)
        self.clock.setText(words["clock"].format(speed=f"{demo.session.clock.speed:g}"))
        self.clock.setToolTip(words["clock_detail"])
        self.differs = session_differs(text, demo.settings)
        self.remote = RemoteButtons(symbols)
        self.status = label(SIZE_SMALL, colour=DEMO_COLOUR)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # How the step under way differs from a session, while it does (`_differs_now`); the
        # whole line in the tooltip, as the row may cut it.
        self.differs_now = label(SIZE_SMALL, colour=DEMO_COLOUR)
        self.differs_now.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # On a worn garment the participant and the experimenter are people (`check_person`).
        # Fixed for the demonstration, so the note is there from the start or never.
        for widget in (self.participant_mode, self.experimenter_mode):
            widget.setEnabled(not demo.worn)
        self.worn_note = label(SIZE_SMALL, colour=WARNING_COLOUR)
        self.worn_note.setText(words["worn_note"])
        self.worn_note.setVisible(demo.worn)

        who = QHBoxLayout()
        who.setSpacing(ITEM_GAP_PX)
        for key, modes in (("participant", self.participant_mode),
                           ("experimenter", self.experimenter_mode)):
            caption = label(SIZE_SMALL, colour=DEMO_COLOUR)
            caption.setText(words[key])
            caption.setToolTip(self.differs["simulations"])
            modes.setToolTip(self.differs["simulations"])
            who.addWidget(caption)
            who.addWidget(modes)
            who.addSpacing(GROUP_GAP_PX)
        who.addStretch(1)
        remote = label(SIZE_SMALL, colour=DEMO_COLOUR)
        remote.setText(words["remote"])
        remote.setToolTip(self.differs["keyboards"])
        self.remote.setToolTip(self.differs["keyboards"])
        who.addWidget(remote)
        who.addWidget(self.remote)
        actions = QHBoxLayout()
        actions.setSpacing(ITEM_GAP_PX)
        jump = label(SIZE_SMALL, colour=DEMO_COLOUR)
        jump.setText(words["jump"])
        actions.addWidget(jump)
        actions.addWidget(self.jump_list)
        actions.addWidget(self.jump_button)
        self.worn_note.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.worn_note.setToolTip(words["worn_note_detail"])
        actions.addWidget(self.worn_note, 2)
        actions.addSpacing(GROUP_GAP_PX)
        actions.addWidget(self.status, 1)
        actions.addWidget(self.differs_now, 2)
        actions.addWidget(self.clock)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ITEM_GAP_PX)
        layout.addLayout(who)
        layout.addLayout(actions)

        if participant is not None:
            watch = _RemoteWatch(participant, self.remote, self)
            participant.installEventFilter(watch)
            participant.vas.installEventFilter(watch)
        demo.runner.stage_started.connect(self.sync)
        self.timer = QTimer(self)
        refresh_s = float(demo.settings["controls_refresh_s"])
        self.timer.setInterval(int(round(refresh_s * MS_PER_S)))
        self.timer.timeout.connect(self.sync)
        self.timer.start()
        self.sync()

    def _choose(self, who: str, mode: str) -> None:
        self.demo.choose(who, mode)
        self.sync()

    def _jump_picked(self, _index: int) -> None:
        self._jump_chosen = True

    def jump_now(self) -> None:
        stage_id = self.jump_list.currentData()
        if stage_id is not None and self.demo.runner.jumpable(stage_id):
            self.demo.jump(stage_id)
            self.status.setText(self.words["jumped"].format(stage=self.jump_list.currentText()))
            self._jump_chosen = False
            # Done: Space is Next again, not Go a second time (S, 22 Oct 2026).
            self.window().setFocus()
        self.sync()

    def sync(self, *_stage_id) -> None:
        """Say what each control would do now (LOG N7.F16j)."""
        demo, words = self.demo, self.words
        self.participant_mode.show_mode(demo.participant_mode)
        self.experimenter_mode.show_mode(demo.experimenter_mode)
        # Said there and then, not listed apart (S, 20 Oct 2026).
        key = demo.differs_now()
        if key == WAITS_DIFFER:
            # Said with this wait's own lengths (S, 22 Oct 2026).
            demo_s, session_s = demo.wait_lengths()
            lengths = {"demo": f"{demo_s:g}", "session": clock_text(round(session_s))}
            differs = words["wait_differs"].format(**lengths)
            detail = words["wait_differs_detail"].format(**lengths)
        else:
            differs = "" if key is None else self.differs[key]
            detail = "" if key is None else self.differs[f"{key}{DETAIL}"]
        if differs != self.differs_now.text():
            self.differs_now.setText(differs)
            self.differs_now.setToolTip(detail)

        self._sync_jump()

    def _sync_jump(self) -> None:
        """Every step of every phase, named "phase: step", in session order; one that cannot
        be jumped to now is listed, greyed, saying why (UI_PRINCIPLES.md 5.13). Rebuilt only
        when that changes, so a choice made is kept."""
        runner, text, words = self.demo.runner, self.text, self.words
        entries = []
        for stage in runner.stages:
            group = stage_group(stage.id, stage.phase)
            entry = words["jump_entry"].format(
                phase=text["phases"][group],
                stage=stage_names(stage.id, text, runner.session.schedule)[1])
            ok = runner.jumpable(stage.id)
            # Only where that is why: an interruption greys every step, for its own reason.
            if runner.needs_calibration(stage.id):
                entry = words["jump_needs_calibration"].format(entry=entry)
            entries.append((stage.id, entry, ok))
        ids = [stage_id for stage_id, _, _ in entries]
        if entries != self._jump_entries:
            chosen = self.jump_list.currentData()
            self.jump_list.clear()
            for stage_id, entry, ok in entries:
                self.jump_list.addItem(entry, stage_id)
                item = self.jump_list.model().item(self.jump_list.count() - 1)
                item.setEnabled(ok)
            if chosen in ids:
                self.jump_list.setCurrentIndex(ids.index(chosen))
            self._jump_entries = entries
        if not self._jump_chosen:
            # The step after the one under way, until another is chosen.
            here = ids.index(runner.stages[runner.stage_index].id)
            self.jump_list.setCurrentIndex(min(here + 1, len(ids) - 1))
        self.jump_button.setEnabled(any(ok for _, _, ok in entries))
        self.jump_list.setEnabled(any(ok for _, _, ok in entries))

