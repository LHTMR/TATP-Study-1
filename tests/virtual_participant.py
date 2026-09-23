"""A virtual participant and experimenter for the Qt-level procedure tests.

Not a test module (no `test_` prefix). It drives the real windows with real key events, the
way `tests/test_touchcal.py` does, and reads which trial is running to decide what to press.
It stands in for `sim/responders.py` (SPEC.md 17.5) until that exists: its intensity ratings
follow the observer model of `docs/calibration_sim.py`, rating linear in log pressure through
a known point, here with no noise so each test knows what the fit must find.

Every procedure runs in a `Rig` over a session whose audio is the recording double and whose
choice-screen feedback and gap are shortened, so a whole Protocol B takes seconds.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp import touchcal
from tatp.clock import Clock
from tatp.procedure import Procedure, Rig
from tatp.responder import Responder
from tatp.session import Session
from tatp.setup_checks import AwaitStop, NoiseAdjustment
from tatp.trials import ExperimenterChoice, MessageConfirm
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
CLOCK_SPEED = 200.0
SPIN_TIMEOUT_S = 60.0
# The observer: rating = 40 + SLOPE * (log10 p - log10 P40), clipped to the scale.
P40_KPA = 20.0
SLOPE_VAS_PER_LOG10 = 51.6
FAST_CHOICE_S = 0.005


def make_config(loaded: cfg.Config, tmp_path, **study1_overrides) -> cfg.Config:
    hardware = {
        **loaded.hardware,
        "data": {"folder": str(tmp_path / "data"), "cloud_sync_markers": []},
        "audio": {**loaded.hardware["audio"], "backend": "recording"},
    }
    study1 = {
        **loaded.study1,
        "choice": {"feedback_s": FAST_CHOICE_S, "gap_s": FAST_CHOICE_S},
        **study1_overrides,
    }
    return cfg.Config(**{**loaded.__dict__, "hardware": hardware, "study1": study1})


def make_rig(config: cfg.Config) -> Rig:
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED), rng_seed=7
    )
    session.start()
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    participant.resize(1280, 800)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    return Rig(session, participant, experimenter)


def press(widget, name: str) -> None:
    key = QT_KEYS[name]
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def rating_for(pressure_kpa: float) -> float:
    if pressure_kpa <= 0:
        return 0.0
    rating = 40 + SLOPE_VAS_PER_LOG10 * (math.log10(pressure_kpa) - math.log10(P40_KPA))
    return min(max(rating, 0.0), 100.0)


def pressure_for(rating: float) -> float:
    return P40_KPA * 10 ** ((rating - 40) / SLOPE_VAS_PER_LOG10)


class Virtual:
    """Presses what a cooperative participant would, and answers for the experimenter.

    The answers are overridable: `choose(key, trial)` returns "left" or "right" for a choice
    screen, `decide(trial)` returns (action name, args) for an experimenter choice, and
    `gains` gives the channel-to-reference sensitivity a channel match should reveal.
    """

    def __init__(self, rig: Rig, procedure: Procedure):
        self.rig = rig
        self.procedure = procedure
        self.gains: dict[int, float] = {}
        self.choose: Callable[[str, object], str] = lambda key, trial: "left"
        self.decide: Callable[[ExperimenterChoice], tuple] = self._default_decide
        self.press_stop = True
        self.noise_levels = {"find_level": -45.0, "mask_level": -30.0}
        self.before_step: Callable[[object], None] = lambda trial: None

    # -- where we are ------------------------------------------------------------------

    def current(self):
        proc = self.procedure
        while proc._child is not None:
            proc = proc._child
        trial = proc._trial
        while getattr(trial, "_children", None):
            trial = trial._children[-1]
        return trial

    # -- one step ----------------------------------------------------------------------

    def step(self) -> None:
        rig, window = self.rig, self.rig.participant
        interruptions = rig.interruptions
        if interruptions.active is not None:
            if interruptions._pending is None:
                rig.experimenter.resume_requested.emit()
            return
        trial = self.current()
        if trial is None:
            return
        self.before_step(trial)
        if interruptions.active is not None or trial is not self.current():
            return
        if isinstance(trial, touchcal.Adjustment):
            trial.state.value = self._setting(trial)
            press(window, "period")
        elif isinstance(trial, NoiseAdjustment):
            trial.state.value = self.noise_levels[trial.screen_key]
            trial._apply()
            press(window, "period")
        elif isinstance(trial, touchcal.TouchRating):
            press(window.vas, "pagedown")
            window.vas.state.percent = rating_for(
                rig.session.garment.pressure_kpa[trial.channel]
                if rig.session.garment.status()["channels_on"] else 0.0
            )
            press(window.vas, "period")
        elif window.stack.currentWidget() is window.choice and window.choice.accepting:
            press(window, "pageup" if self.choose(self._choice_key(trial), trial) == "left"
                  else "pagedown")
        elif isinstance(trial, touchcal.PreferenceSelection):
            press(window, "pagedown")
            press(window, "pagedown")
            press(window, "period")
        elif isinstance(trial, (MessageConfirm, touchcal.DeliveryStart)) and (
            window.stack.currentWidget() is window.message and trial._connections
        ):
            press(window, "period")
        elif isinstance(trial, ExperimenterChoice):
            name, args = self.decide(trial)
            trial.actions[name].emit(*args)
        elif isinstance(trial, AwaitStop) and self.press_stop:
            press(window, "f5")

    def _choice_key(self, trial) -> str:
        if isinstance(trial, touchcal.Comparison):
            return touchcal.COMPARISON_CHOICE
        return trial.key

    def _setting(self, trial) -> float:
        plan = trial.plan
        if plan.stage == touchcal.ANCHOR_STAGE:
            return pressure_for(plan.anchor_percent)
        if plan.stage == touchcal.MATCH_STAGE:
            return plan.expected_kpa * self.gains.get(plan.channel, 1.0)
        return (plan.range_min_kpa * plan.range_max_kpa) ** 0.5

    def _default_decide(self, trial: ExperimenterChoice) -> tuple:
        for name in ("proceed", "accept"):
            if name in trial.actions:
                return name, ()
        raise AssertionError(f"no default for {sorted(trial.actions)}")

    # -- running -----------------------------------------------------------------------

    def run(self, timeout_s: float = SPIN_TIMEOUT_S):
        results = []
        self.procedure.finished.connect(results.append)
        self.procedure.start()
        deadline = time.monotonic() + timeout_s
        while not results:
            if time.monotonic() > deadline:
                raise AssertionError(f"the procedure stalled at {self.current()!r}")
            QApplication.processEvents()
            self.step()
            time.sleep(0.0005)
        return results[0]
