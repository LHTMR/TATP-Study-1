"""Virtual participants. SPEC.md 17.3, 17.5.

**A virtual participant does what a participant does and nothing more.** It looks at the
participant window -- `stack.currentWidget()` is which screen is up, and the screen's own
attributes are what it draws -- and it presses the remote's keys as key events sent to the
window, so every press goes through the same `keyPressEvent` a real key reaches. It never calls
a protocol, never reads a data file and never touches the session.

**What it feels, it learns from what the software actually delivered**, never from what a
protocol intended. Touch is the pressure the mock garment is delivering. A monofilament or the
brush is whatever the experimenter applied: the virtual experimenter (`sim/experimenters.py`)
reads it off the experimenter screen and calls `feel_filament` or `feel_brush`, which are the
one channel between the two, as the skin is in the lab.

**The observer model is `docs/calibration_sim.py`'s**, rating = 40 + m·(log₁₀F − log₁₀F₄₀) +
noise, clipped to the scale (SPEC.md 17.5). That file is a script -- importing it would run
every scenario of the comparison document -- and it must not be edited or reformatted
(`docs/LOG.md` N6.8). So `load_calibration_sim` executes its module body with the top-level
expression statements taken out, which are exactly its `print(...)` and `run(...)` calls, and
keeps its imports, constants and functions as written. Touch uses the same `rate` function with
a slope and a 40 % point of its own. The ratings the model does not cover -- the brush, the
touch's pleasantness, relaxation and alertness -- are a fixed level plus the same noise.

**The whole session** (SPEC.md 2). Every screen a session shows is answered: the welcome and
the other "press ▶" screens, the noise level, the stop rehearsal, the adjustments, the choices,
the preference selection, the self-start and every VAS. An adjustment is made **by taps**, one
step each, not by holding: the validator runs at a speed where a hold, which moves on real
seconds, would take longer than the session's scaled time-out (`tatp/touchcal.py`).

**Adversarial participants** are subclasses, one per error path that exists to fire (SPEC.md
17.3). Each overrides one hook and counts what it did, so the validator can check the software's
response against the provocation rather than against a guess.

The parameters below describe the virtual participant, not the study. Nothing the software
measures depends on them, which is why they live here and not in `config/` (SPEC.md 4.2).
"""

from __future__ import annotations

import ast
import functools
import time
from pathlib import Path
from types import CodeType

import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

from tatp.config import REPO_ROOT, Config
from tatp.garment.base import GarmentController
from tatp.pinprick import PAIN_SCALE
from tatp.responder import Action
from tatp.touchcal import INTENSITY_SCALE
from tatp.ui.participant import SIDES, ParticipantWindow
from tatp.ui.vas import MAX_PCT, MIN_PCT, QT_KEYS
from tatp.units import MS_PER_S

CALIBRATION_SIM = REPO_ROOT / "docs" / "calibration_sim.py"

# Pinprick: calibration_sim.py's POST-S scenario -- its median F40 and its rating noise.
PAIN_F40_MN = 130.0
PAIN_NOISE_SD = 10.0
# Touch: the same observer on kPa. Chosen so both labelled anchors (10 % and 90 %) fall inside
# the mock garment's range, at about 17 and 170 kPa.
TOUCH_P40_KPA = 40.0
TOUCH_SLOPE_PER_LOG10 = 80.0
TOUCH_NOISE_SD = 10.0
# Trial-to-trial scatter in where an adjustment is stopped, in VAS points. Smaller than the
# rating noise, so the 10 % anchor is never placed below nothing at all.
ADJUST_CRITERION_SD = 3.0
# Where on the intensity scale this participant finds the touch most pleasant.
MOST_PLEASANT_PCT = 55.0
# The ratings the observer model does not cover: a level, plus the rating noise.
BRUSH_PAIN_PCT = 8.0
STATE_LEVELS_PCT = {"pleasantness": 62.0, "relaxation": 55.0, "alertness": 50.0}
# The smallest difference in felt intensity, in VAS points, this participant can tell apart.
COMPARISON_JND_PCT = 5.0
# Noise-level taps, from the start level: to "just audible", then further to cover the garment.
NOISE_TAPS = {"find_level": 15, "mask_level": 15}

# How often the participant looks at the screen, in real seconds. Short, because at the
# validator's speed a person's reaction time is a large part of the session.
TICK_S = 0.002
# Taps in one look at the screen before looking again; the garment follows a tap at once.
TAPS_PER_TICK = 60
# Taps in a row that changed nothing: the end of the adjustable range has been reached.
END_OF_RANGE_TAPS = 3


class CalibrationSimError(Exception):
    """docs/calibration_sim.py has a top-level statement that could run the simulation."""


@functools.cache
def _calibration_sim_code(path: Path = CALIBRATION_SIM) -> CodeType:
    """The file's definitions, compiled once. Everything that could run the simulation is out.

    Kept: imports, function definitions, and assignments that call nothing the file itself
    defines -- `LAD = np.array([...])` is a constant, `results = run(...)` is the simulation.
    Dropped: bare expressions, which are the `print(...)` and `run(...)` calls. Anything else
    at the top level (a loop, an `if`, a `results = run(...)`) is refused rather than run, so a
    later edit to the file cannot quietly start a four-thousand-participant simulation inside
    every validator run.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    kept = []
    for node in tree.body:
        if isinstance(node, ast.Expr):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            kept.append(node)
            continue
        if isinstance(node, ast.Assign):
            calls = {
                inner.func.id
                for inner in ast.walk(node.value)
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
            }
            if not calls & defined:
                kept.append(node)
                continue
        raise CalibrationSimError(
            f"{path.name} line {node.lineno}: a top-level {type(node).__name__} that is not a "
            f"definition or a constant. It might run the simulation, so it is not loaded."
        )
    tree.body = kept
    return compile(tree, str(path), "exec")


def load_calibration_sim(path: Path = CALIBRATION_SIM) -> dict:
    """The definitions of docs/calibration_sim.py, without running its simulation.

    A fresh namespace on every call, because each caller replaces the module-level `rng`.
    """
    namespace: dict = {"__name__": "calibration_sim"}
    exec(_calibration_sim_code(path), namespace)
    return namespace


class ObserverModel:
    """calibration_sim.py's observer, for pain and for touch, with the run's own noise.

    The file's `rate` draws its noise from a module-level `rng`, so each copy of the file gets
    one seeded from the run. Two copies: one for the noisy ratings a participant reports, and
    one for the noiseless reading used to steer an adjustment. Steering reads the model on every
    tick, and the number of ticks depends on timing -- if it drew from the reporting stream,
    two runs with the same seed would report different ratings.
    """

    def __init__(
        self,
        seed: int,
        pain_f40_mn: float = PAIN_F40_MN,
        pain_noise_sd: float = PAIN_NOISE_SD,
        touch_p40_kpa: float = TOUCH_P40_KPA,
        touch_slope_per_log10: float = TOUCH_SLOPE_PER_LOG10,
        touch_noise_sd: float = TOUCH_NOISE_SD,
        adjust_criterion_sd: float = ADJUST_CRITERION_SD,
    ):
        self._reported = load_calibration_sim()
        self._reported["rng"] = np.random.default_rng(seed)
        self._steering = load_calibration_sim()
        self.pain_f40_mn = pain_f40_mn
        self.pain_noise_sd = pain_noise_sd
        self.touch_p40_kpa = touch_p40_kpa
        self.touch_slope_per_log10 = touch_slope_per_log10
        self.touch_noise_sd = touch_noise_sd
        self.adjust_criterion_sd = adjust_criterion_sd

    @property
    def pain_slope_per_log10(self) -> float:
        return float(self._reported["S_FIXED"])

    def pain_pct(self, force_mn: float) -> float:
        return float(
            self._reported["rate"](force_mn, self.pain_f40_mn, self.pain_noise_sd)
        )

    def touch_pct(self, kpa: float) -> float:
        """A reported touch intensity rating."""
        if kpa <= 0:
            return MIN_PCT  # nothing delivered is nothing felt, and log10(0) is not a sensation
        return float(
            self._reported["rate"](
                kpa, self.touch_p40_kpa, self.touch_noise_sd, self.touch_slope_per_log10
            )
        )

    def touch_felt_pct(self, kpa: float) -> float:
        """The noiseless intensity of `kpa`, which is what steers an adjustment."""
        if kpa <= 0:
            return MIN_PCT
        return float(
            self._steering["rate"](kpa, self.touch_p40_kpa, 0.0, self.touch_slope_per_log10)
        )

    def level_pct(self, level_pct: float) -> float:
        """A rating the model has no psychophysics for: the level, with the rating noise."""
        noisy = level_pct + self._reported["rng"].normal(0.0, self.touch_noise_sd)
        return float(min(max(noisy, MIN_PCT), MAX_PCT))

    def criterion_pct(self) -> float:
        """Where this participant places a target this time: one draw per adjustment."""
        return float(self._reported["rng"].normal(0.0, self.adjust_criterion_sd))


class VirtualParticipant(QObject):
    """The normal responder of SPEC.md 17.5. Answers every screen a session shows."""

    def __init__(
        self,
        window: ParticipantWindow,
        garment: GarmentController,
        config: Config,
        seed: int,
        model: ObserverModel | None = None,
        parent: QObject | None = None,
    ):
        # A child of the window unless told otherwise, so its timer and its connections to the
        # window end with the window rather than outliving it.
        super().__init__(window if parent is None else parent)
        self.window = window
        self.garment = garment
        self.model = model or ObserverModel(seed)
        self.ceiling_kpa = garment.limits.pressure_ceiling_kpa

        keys = config.hardware["responder"]["keys"]
        self._keys = {action: QT_KEYS[keys[action.value][0]] for action in Action}
        self._confirm_symbol = config.hardware["responder"]["button_symbols"]["confirm"]
        vas = config.study1["vas"]
        self._vas_start = {
            "left": float(vas["start_pct_after_left_press"]),
            "right": float(vas["start_pct_after_right_press"]),
        }
        self._vas_step = float(vas["move_step_pct"])
        self._tap_step_kpa = float(config.hardware["adjustment"]["tap_step_kpa"])
        # The participant reads the prompt, and knows which point of the scale it names.
        touch = config.study1["touch_calibration"]
        self.reference_channel = int(touch["reference_channel"])
        text = config.participant_text
        prompts = text["adjust_targets"]
        self._adjust_goals = {
            prompts[key]: float(pct)
            for key, pct in zip(touch["anchor_prompt_keys"], touch["anchors_pct"], strict=True)
        }
        self._adjust_goals[prompts["most_pleasant"]] = MOST_PLEASANT_PCT
        self._match_prompt = prompts["match"]
        self._preference_intro = text["participant_controls"]["preference"]["intro"]
        self._level_screens = {
            text["audio_setup"][key]: taps for key, taps in NOISE_TAPS.items()
        }
        choices = text["choices"]
        # The garment is masked, and the movement feels even (the affirmative is on the left).
        self._choice_answers = {
            choices["still_audible"]["question"]: SIDES[1],
            choices["evenness"]["question"]: SIDES[0],
        }

        self.stimulus_mn: float | None = None
        self.brush_felt = False
        self.seen_text: set[str] = set()
        self.ratings: list[tuple[str, float]] = []
        self.adjustments_seen = 0

        self._token: tuple | None = None
        self._handled = False
        self._held: Action | None = None
        self._shown_at_s = 0.0
        self._adjust_goal: float | None = None
        self._unchanged_taps = 0
        self._choice_felt = dict.fromkeys(SIDES, MIN_PCT)
        # A person watches the comparison continuously. A timer's look at the screen can fall
        # between two short stimuli at the validator's speed, so the emphasis is observed as it
        # changes rather than sampled.
        self._emphasise = window.emphasise_choice
        window.emphasise_choice = self._watch_emphasis
        # The same goes for the warning cue, which is what separates two adjustments with the
        # same prompt: seen as it goes up, so the next screen is always a new one.
        window.warning_cue_shown.connect(self._saw_cue)

        self._timer = QTimer(self)
        self._timer.setInterval(int(round(TICK_S * MS_PER_S)))
        self._timer.timeout.connect(self._tick)

    # -- lifecycle ---------------------------------------------------------------------

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.window.emphasise_choice = self._emphasise
        self.window.warning_cue_shown.disconnect(self._saw_cue)

    def feel_filament(self, force_mn: float) -> None:
        """The experimenter has applied a filament of this force. Called by the experimenter."""
        self.stimulus_mn = float(force_mn)

    def feel_brush(self) -> None:
        """The experimenter has stroked the brush. Called by the experimenter."""
        self.brush_felt = True

    def stats(self) -> dict:
        """What this participant did, for the validator to hold the software's response to."""
        return {"ratings": list(self.ratings), "adjustments_seen": self.adjustments_seen}

    # -- looking at the screen ---------------------------------------------------------

    def _tick(self) -> None:
        window = self.window
        screen = window.stack.currentWidget()
        token = self._token_for(screen)
        if token != self._token:
            self._token = token
            self._new_screen(screen)
        if screen is window.vas:
            self.on_vas()
        elif screen is window.control:
            self.on_control()
        elif screen is window.choice:
            self.on_choice()
        elif screen is window.cue:
            self.on_cue()
        elif screen is window.message:
            self.on_message()

    def _token_for(self, screen: QWidget) -> tuple:
        window = self.window
        if screen is window.vas:
            return (screen, window.vas.scale, window.vas.state.cue_iso)
        if screen is window.control:
            return (screen, window.control.target, id(window.control))
        if screen is window.choice:
            return (screen, window.choice.question, window.choice.accepting)
        if screen is window.message:
            return (screen, window.message.text, window.message.stop_symbol)
        return (screen,)

    def _new_screen(self, screen: QWidget) -> None:
        # A participant does not keep a button held into the next screen -- after an emergency
        # stop, for one, they let go.
        self._let_go()
        self._handled = False
        self._shown_at_s = time.monotonic()
        self._adjust_goal = None
        self._unchanged_taps = 0
        window = self.window
        if not (screen is window.choice and window.choice.accepting):
            self._choice_felt = dict.fromkeys(SIDES, MIN_PCT)
        self.on_new_screen()
        if screen is window.vas:
            vas = window.vas
            self._see(vas.question, vas.statement, *(a["label"] for a in vas.anchors))
        elif screen is window.control:
            control = window.control
            self.adjustments_seen += 1
            self._see(control.target, control.confirm, *control.labels.values())
            if control.target in self._adjust_goals:
                self._adjust_goal = (
                    self._adjust_goals[control.target] + self.model.criterion_pct()
                )
        elif screen is window.choice:
            choice = window.choice
            self._see(choice.question, *choice.labels.values())
        elif screen is window.message:
            self._see(window.message.text)

    def _see(self, *texts: str) -> None:
        self.seen_text.update(str(text) for text in texts if text)

    def _reference_kpa(self) -> float:
        return self.garment.pressure_kpa.get(self.reference_channel, 0.0)

    def _felt_kpa(self) -> float:
        return max(self.garment.pressure_kpa.values(), default=0.0)

    def _saw_cue(self) -> None:
        self._token = None
        self.on_cue()

    def _watch_emphasis(self, side: str | None) -> None:
        self._emphasise(side)
        if side is not None:
            felt = self.model.touch_felt_pct(self._felt_on_kpa())
            self._choice_felt[side] = max(self._choice_felt[side], felt)

    def _felt_on_kpa(self) -> float:
        on = self.garment.status()["channels_on"]
        return max((self.garment.pressure_kpa[c] for c in on), default=0.0)

    # -- the hooks an adversary overrides ---------------------------------------------

    def on_new_screen(self) -> None:
        """A different screen is up. Per-screen state an adversary keeps is reset here."""

    def on_vas(self) -> None:
        if self._handled:
            return
        self._handled = True
        scale = self.window.vas.scale
        self.answer_vas(scale, self.rating_for(scale))

    def on_control(self) -> None:
        if self._handled:
            return
        control = self.window.control
        if control.target == self._preference_intro:
            # One step on from where the selection starts, then choose it.
            self._handled = True
            self.tap(Action.INCREASE)
            self.tap(Action.CONFIRM)
        elif control.target == self._match_prompt:
            self.match()
        elif self._adjust_goal is not None:
            self.adjust(self._adjust_goal)

    def on_choice(self) -> None:
        choice = self.window.choice
        if not choice.accepting or self._handled:
            return
        self._handled = True
        side = self._choice_answers.get(choice.question)
        if side is None:
            # The stronger of the two, when the difference is one a person could feel; otherwise
            # the first. Without the threshold, two channels matched to within a tap would be
            # told apart on a difference nobody feels, and which way would depend on timing.
            left, right = (self._choice_felt[s] for s in SIDES)
            side = SIDES[1] if right - left > COMPARISON_JND_PCT else SIDES[0]
        self.tap(Action.DECREASE if side == SIDES[0] else Action.INCREASE)

    def on_cue(self) -> None:
        """The warning cue. A normal participant waits for the stimulus."""

    def on_message(self) -> None:
        if self._handled:
            return
        message = self.window.message
        if message.stop_symbol is not None:
            self.on_stop_rehearsal()
        elif message.text in self._level_screens:
            self._handled = True
            for _ in range(self._level_screens[message.text]):
                self.tap(Action.INCREASE)
            self.tap(Action.CONFIRM)
        elif self._confirm_symbol in message.text:
            self._handled = True
            self.tap(Action.CONFIRM)

    def on_stop_rehearsal(self) -> None:
        """"Press this button to stop it" (SPEC.md 10.9): pressed once."""
        self._handled = True
        self.press_emergency_stop()

    # -- responding --------------------------------------------------------------------

    def rating_for(self, scale: str) -> float:
        if scale == PAIN_SCALE:
            # Each application is felt once: rated, then gone. A second rating with no new
            # application in between is the guard firing, not a stale stimulus reused.
            if self.brush_felt:
                self.brush_felt = False
                return self.model.level_pct(BRUSH_PAIN_PCT)
            force_mn, self.stimulus_mn = self.stimulus_mn, None
            if force_mn is None:
                raise RuntimeError("asked to rate pain, but no filament has been applied")
            return self.model.pain_pct(force_mn)
        if scale == INTENSITY_SCALE:
            return self.model.touch_pct(self._reference_kpa())
        if scale in STATE_LEVELS_PCT:
            return self.model.level_pct(STATE_LEVELS_PCT[scale])
        raise KeyError(f"the virtual participant has no model for the {scale!r} scale")

    def answer_vas(self, scale: str, pct: float) -> None:
        """Reveal the marker on the nearer side, step it to `pct`, confirm (SPEC.md 10.2)."""
        side = min(SIDES, key=lambda s: abs(self._vas_start[s] - pct))
        self.tap(Action.DECREASE if side == "left" else Action.INCREASE)
        steps = int(round((pct - self._vas_start[side]) / self._vas_step))
        for _ in range(abs(steps)):
            self.tap(Action.INCREASE if steps > 0 else Action.DECREASE)
        self.ratings.append((scale, self.window.vas.state.percent))
        self.tap(Action.CONFIRM)

    def adjust(self, goal_pct: float) -> None:
        """Tap towards the goal, feeling the touch after each tap; confirm once crossed."""
        self._tap_towards(
            lambda: self.model.touch_felt_pct(self._reference_kpa()) - goal_pct
        )

    def match(self) -> None:
        """"As strong as the first": tap the adjusted channel to the reference's pressure."""
        def difference() -> float:
            others = [kpa for channel, kpa in self.garment.pressure_kpa.items()
                      if channel != self.reference_channel]
            return max(others, default=0.0) - self._reference_kpa()

        self._tap_towards(difference)

    def _tap_towards(self, difference) -> None:
        """Tap up while `difference()` is below zero, down while above, then confirm."""
        if time.monotonic() - self._shown_at_s < TICK_S:
            return  # the garment may still be settling from the screen before
        start = difference()
        if start == 0:
            self.confirm_adjustment()
            return
        action = Action.INCREASE if start < 0 else Action.DECREASE
        for _ in range(TAPS_PER_TICK):
            # The pressure, not the felt difference, says whether a tap moved anything: well
            # below threshold every pressure is felt as nothing.
            before = dict(self.garment.pressure_kpa)
            self.tap(action)
            after = difference()
            if (after >= 0) if action is Action.INCREASE else (after <= 0):
                self.confirm_adjustment()
                return
            moved_kpa = max(abs(kpa - before.get(channel, 0.0))
                            for channel, kpa in self.garment.pressure_kpa.items())
            self._unchanged_taps = 0 if moved_kpa else self._unchanged_taps + 1
            if self._unchanged_taps >= END_OF_RANGE_TAPS:
                self.confirm_adjustment()
                return
            if 0 < moved_kpa < self._tap_step_kpa:
                return  # the rate limit is holding the garment back; feel it again next look

    def confirm_adjustment(self) -> None:
        self._let_go()
        self.tap(Action.CONFIRM)
        self._handled = True

    # -- the remote --------------------------------------------------------------------

    def tap(self, action: Action) -> None:
        self._send(action, QEvent.KeyPress)
        self._send(action, QEvent.KeyRelease)

    def hold(self, action: Action) -> None:
        self._send(action, QEvent.KeyPress)
        self._held = action

    def press_emergency_stop(self) -> None:
        self.tap(Action.EMERGENCY_STOP)

    def _let_go(self) -> None:
        if self._held is not None:
            held, self._held = self._held, None
            self._send(held, QEvent.KeyRelease)

    def _send(self, action: Action, kind: QEvent.Type) -> None:
        # Where a real key would land: the VAS reads its own keys, the window reads the rest
        # (tatp/ui/participant.py). Sent as an event rather than a method call, so it passes
        # through Qt's delivery exactly as the remote's key does.
        window = self.window
        target = window.vas if window.stack.currentWidget() is window.vas else window
        QApplication.sendEvent(target, QKeyEvent(kind, self._keys[action], Qt.NoModifier))


# -- adversarial participants, SPEC.md 17.5 ----------------------------------------------


class ConfirmsWithoutMarker(VirtualParticipant):
    """Presses confirm before moving the marker, on every scale, then answers.

    The error path: a confirm with no marker shown is not a response, so nothing is recorded as
    one, and each press is logged as `confirm_without_marker` (docs/LOG.md N6.11).
    """

    EMPTY_CONFIRMS = 3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empty_confirms = 0

    def on_vas(self) -> None:
        if not self._handled:
            for _ in range(self.EMPTY_CONFIRMS):
                self.tap(Action.CONFIRM)
                self.empty_confirms += 1
        super().on_vas()

    def stats(self) -> dict:
        return {**super().stats(), "empty_confirms": self.empty_confirms}


class StopsMidBlock(VirtualParticipant):
    """Presses the emergency stop at the first warning cue felt with the garment's touch on.

    The garment's channels are on at a warning cue only inside the intervention, where the
    touch runs throughout and a cue announces a filament -- everywhere else the garment starts
    after its cue -- so the stop lands mid-block and mid-trial. The error path: the garment to
    zero, the trial abandoned without a row, and the experimenter's resume repeating it
    (SPEC.md 13).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stops = 0

    def on_cue(self) -> None:
        if not self.stops and self.garment.status()["channels_on"]:
            self.stops += 1
            self.press_emergency_stop()

    def stats(self) -> dict:
        return {**super().stats(), "stops": self.stops}


class HoldsAdjustmentAtMaximum(VirtualParticipant):
    """Holds "stronger" through the first adjustment until the garment is at the ceiling,
    keeps holding, then confirms. Every later adjustment is made normally.

    The error path: the pressure stops at the software ceiling however long the button is held
    (SPEC.md 13), and the adjustment records the ceiling as what was produced.
    """

    OVERHOLD_S = 0.5  # real seconds held at the ceiling before letting go

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.held_at_ceiling_s = 0.0
        self._ceiling_since_s: float | None = None
        self.ceiling_holds_s: list[float] = []

    def on_new_screen(self) -> None:
        # Each adjustment is held to the ceiling afresh; a second one must not inherit the
        # first one's time there and let go early.
        self.held_at_ceiling_s = 0.0
        self._ceiling_since_s = None

    def adjust(self, goal_pct: float) -> None:
        if self.ceiling_holds_s:
            super().adjust(goal_pct)
            return
        if self._held is None:
            self.hold(Action.INCREASE)
            return
        if self._felt_kpa() < self.ceiling_kpa:
            return
        now = time.monotonic()
        if self._ceiling_since_s is None:
            self._ceiling_since_s = now
        self.held_at_ceiling_s = now - self._ceiling_since_s
        if self.held_at_ceiling_s >= self.OVERHOLD_S:
            self.ceiling_holds_s.append(self.held_at_ceiling_s)
            self.confirm_adjustment()

    def stats(self) -> dict:
        # Every adjustment's hold, since the per-screen figure resets on the next screen.
        return {**super().stats(), "ceiling_holds_s": list(self.ceiling_holds_s)}


class StopsAtMaximum(VirtualParticipant):
    """Holds "stronger" to the ceiling and presses the emergency stop while still holding.

    After the resume it adjusts normally. The error path: the resume restores the pre-stop
    pressure, and the rate limit caps how fast it may come back (SPEC.md 13), which is logged
    as `restore_rate_limited` and shows in the `garment` table as a clamped command.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stops = 0

    def adjust(self, goal_pct: float) -> None:
        if self.stops:
            super().adjust(goal_pct)
            return
        if self._held is None:
            self.hold(Action.INCREASE)
            return
        if self._felt_kpa() >= self.ceiling_kpa:
            self.stops += 1
            self.press_emergency_stop()

    def stats(self) -> dict:
        return {**super().stats(), "stops": self.stops}


class StopsResponding(VirtualParticipant):
    """Never touches the first adjustment; answers everything after it.

    The error path: the adjustment has no stopping rule of its own, so its time-out ends it at
    whatever pressure it started from, flagged `timed_out`, and the session carries on
    (SPEC.md 9). The VAS has no equivalent yet -- `vas.no_response_warning_s` is read but
    nothing warns on it -- so this participant does not go silent on a rating.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ignored_adjustments = 0

    def on_control(self) -> None:
        if self._adjust_goal is not None and not self.ignored_adjustments:
            self.ignored_adjustments += 1
            self._handled = True
        super().on_control()

    def stats(self) -> dict:
        return {**super().stats(), "ignored_adjustments": self.ignored_adjustments}


class F40BelowBottom(VirtualParticipant):
    """Sensitive beyond the ladder: even the lightest filament is rated above 40.

    The error path (SPEC.md 8.2): the search runs down to the lightest filament and stops there
    with `out_of_range` set to `below`, and the session carries on with the boundary filament.
    """

    F40_MN = 0.01  # below the 0.08 mN of the lightest filament in filaments.yaml

    def __init__(self, window, garment, config, seed, model=None, parent=None):
        super().__init__(window, garment, config, seed,
                         model or ObserverModel(seed, pain_f40_mn=self.F40_MN), parent)


class F40AboveTop(VirtualParticipant):
    """Insensitive beyond the ladder: even the heaviest filament is rated below 40.

    The error path (SPEC.md 8.2): the search climbs to the heaviest filament and stops there
    with `out_of_range` set to `above`.
    """

    F40_MN = 100000.0  # far above the 2940 mN of the heaviest

    def __init__(self, window, garment, config, seed, model=None, parent=None):
        super().__init__(window, garment, config, seed,
                         model or ObserverModel(seed, pain_f40_mn=self.F40_MN), parent)
