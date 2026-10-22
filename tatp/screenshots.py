"""Every screen state, as a PNG. SPEC.md 17.4.

Two jobs, and they are separate on purpose.

**A catalogue.** `shots()` walks every state either window can be in, in both languages, and
hands back a name, a description of what the image should show, and the pixmap. It is the only
place that knows how to put a window into a given state, so the screenshot run and the
manifest cannot disagree about what the states are.

**A regression check, armed per screen.** `screenshots/manifest.yaml` lists every expected
state. An entry with no image fails and an image with no entry fails, so a screen that quietly
stops being rendered is caught rather than silently dropped. Comparison against
`screenshots/reference/` is *per entry*: a screen with an approved reference is compared and
any difference beyond `TOLERANCE_FRACTION` fails; a screen without one is not compared at all.

That last distinction is what makes this usable during a build. Approving a screen arms it;
until then it is catalogued but not defended, so adding a screen does not require freezing
wording that is still moving. Changing an armed screen deliberately means reviewing the diff
and re-approving, with `--approve-all` for a wording pass across every screen at once.

**What this is not.** A pixel comparison cannot tell you a screen is *right*, only that it has
not changed since someone said it was. The blinding check that matters is
`tests/test_blinding_text.py`; the manifest description is what a reviewer reads to decide
whether the picture matches the intent.

The catalogue holds what the software can actually show, so a manifest entry always
corresponds to a real screen. The experimenter states are built from a hand-made view plus
fixed sample content (the `SAMPLE_*` constants), because the states worth photographing -- a
block overdue, a stop pressed, a fit on screen -- are the ones a real session reaches rarely.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from types import SimpleNamespace

import numpy as np
import yaml
from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from tatp import config as cfg
from tatp import pattern_design as pd
from tatp import schedule
from tatp import touchcal_maths as maths
from tatp.clock import Clock
from tatp.demo import DEMO_GARMENT, OFF, RESTS_DIFFER, DemoControls, demo_rests
from tatp.devices import ON_SCREEN, check_key, matching_outputs
from tatp.garment.base import Limits
from tatp.garment.mock import MockGarment
from tatp.hardware_check import Detectors, HardwareCheckDialog
from tatp.instruments import InstrumentsDialog
from tatp.launcher import WARN, LauncherWindow
from tatp.pinprick import F40Fit, LongResult
from tatp.remote_keys import ANY_KEYBOARD, with_key_source
from tatp.responder import Action, Responder
from tatp.resume import offer_wording
from tatp.session_runner import INTERVENTION, session_phases, stage_layout, stage_plan
from tatp.touchcal import MATCH_TARGET, FitReady
from tatp.ui.application import application
from tatp.ui.experimenter import (
    CONFIRMED,
    LAB_SCREEN_HEIGHT_PX,
    LAB_SCREEN_WIDTH_PX,
    NOW,
    PREPARE,
    QUERIED,
    WAIT,
    ExperimenterWindow,
)
from tatp.ui.garment_display import states_from_status
from tatp.ui.participant import ParticipantWindow
from tools.design_pattern import DesignerWindow

SCREENSHOT_DIR = cfg.REPO_ROOT / "screenshots"
MANIFEST_PATH = SCREENSHOT_DIR / "manifest.yaml"
REFERENCE_DIR = SCREENSHOT_DIR / "reference"
CURRENT_DIR = SCREENSHOT_DIR / "current"
DIFF_DIR = SCREENSHOT_DIR / "diff"

# How the windows are grabbed. Presentation, not study parameters (SPEC.md 4.2): the size is
# the lab PC's, and the tolerance is what separates a font rasterising a shade differently on
# another machine from a screen that actually changed.
WIDTH_PX = LAB_SCREEN_WIDTH_PX
HEIGHT_PX = LAB_SCREEN_HEIGHT_PX
# The lab laptop's usable screen, for the windows that open on it maximized or fitted to it
# (the designer, the instruments dialog): a 1920 x 1080 panel at 150 % scaling, less the
# taskbar and a title bar. Photographed there, S sees them as they will open.
LAPTOP_WIDTH_PX = 1280
LAPTOP_HEIGHT_PX = 640
TOLERANCE_FRACTION = 0.002

LANGUAGES = ("sv", "en")

# The scale that carries the marker-position and first-press-side variants SPEC.md 17.4 asks
# for. One scale is enough -- the marker is drawn by the same code whatever the question -- and
# every scale still gets its uncued state, which is the one the wording review looks at.
VARIANT_SCALE = "pain"
MARKER_POSITIONS = (5.0, 50.0, 95.0)
# The `choices` keys whose two options are two stimuli, so each button is emphasised in turn.
PAIRED_CHOICES = ("comparison",)

# -- sample content for the experimenter screens ---------------------------------------------
# What a session would push into the window, fixed so each picture is the same every run. None
# of it is a study parameter: it is the content of a photograph (SPEC.md 4.2).
DIALOG_WIDTH_PX = 720
SAMPLE_ELAPSED_S = 3725.0
SAMPLE_SITE = 3
SAMPLE_CHANNEL = 2
# Part-way through the estimation run: ten amplitudes and two catch trials (R32).
SAMPLE_ANSWERED = 3
SAMPLE_PRESENTATIONS = 12
# The channel matched, which of the channels matched it is, and how many there are.
SAMPLE_MATCH = {"channel": SAMPLE_CHANNEL, "index": 2, "count": 4}
SAMPLE_PATH = "lateral"
SAMPLE_DISTANCES = ("42", "37,5")
SAMPLE_INSIDE_MM = "8"
SAMPLE_BLOCK = {"kind": "block", "label_key": "block", "block_index": 3, "block_type": "touch"}
SAMPLE_DUE_IN_S = 245.0
SAMPLE_DUE_NOW_S = -5.0
SAMPLE_DUE_SOON_S = 25.0
# A short series' third application, of five, and its rest; a lighter filament applied.
SAMPLE_PROGRESS = 3
SAMPLE_SHORT_N = 5
SAMPLE_REST_S = 9.0
SAMPLE_SUBSTITUTE = "15"
SAMPLE_DATA_FILES = 11
SAMPLE_OVERDUE_S = -420.0
SAMPLE_HARDWARE = {"connected": True, "link_lost": False, "faults": [],
                   "channel_pressure_kpa": None, "channels_on": None}
SAMPLE_PRESSURES_KPA = {1: 38.5, 2: 41.0, 3: 40.0, 4: 39.5, 5: 42.0}
# The channels on while a channel is matched to the reference: those two (LOG N7.F16i).
SAMPLE_CHANNELS_ON = [2, 3]
SAMPLE_FAULT = "channel 4: valve did not report"
# Unresolved open items as `config.OpenItem.__str__` gives them, "[number] summary".
SAMPLE_OPEN_ITEMS = ["[L3] audio levels", "[5] patterns"]
# What the prototype driver reports when its link goes, at full length (arduino_mosfet.py).
SAMPLE_LINK_FAULT = ("serial write failed on COM3: WriteFile failed (PermissionError(13, "
                     "'The device does not recognize the command.', None, 22))")
SAMPLE_ERROR = "hardware.yaml: required key 'garment.driver' is missing"
SAMPLE_F40 = {
    "run_index": 1, "filament": "26", "filament_mn": 255.0, "f40_mn": 321.4, "total": 14,
    "measure": 9, "rho": 0.71, "slope": 51.6, "target": 40.0,
    "points": ((147.0, 23.5), (147.0, 28.0), (255.0, 36.5), (255.0, 41.0), (588.0, 58.5),
               (588.0, 52.0), (98.0, 18.0), (98.0, 14.5), (255.0, 39.0)),
}
SAMPLE_TOUCH = {
    "run_index": 2, "intercept": -41.5, "slope": 52.0, "r_squared": 0.87, "residual_sd": 6.4,
    "span": 62.6, "rho": 0.91, "bracket": (9.0, 150.0), "p": (15.9, 24.6, 145.0),
    "points": ((9.0, 8.5, False), (18.0, 22.0, False), (30.0, 35.5, False),
               (0.0, 2.0, True), (55.0, 50.0, False), (90.0, 58.5, False),
               (150.0, 71.0, False), (0.0, 0.0, True), (120.0, 69.0, False)),
}
SAMPLE_PARTICIPANT = "07"
SAMPLE_INITIALS = "SM"
SAMPLE_PATTERN_FOLDER = "config/patterns/examples"
SAMPLE_DATA_FOLDER = "data"
# The resume offer's completed phases and blocks, and how long ago sensitisation began,
# worded by the same `resume.offer_wording` the real offer is.
SAMPLE_RESUME_COMPLETED = ("setup", "touch_calibration", "pre_sensitisation", "sensitisation")
# The channel the hardware check is drawn with on (docs/LOG.md N7.F10b).
SAMPLE_CHANNEL_ON = 2
# The demonstration's garment display (docs/LOG.md N7.F12f): every channel set to this share
# of the ceiling, these channels on, then this one turned on and drawn this long after.
SAMPLE_DEMO_PRESSURE_FRACTION = 0.6
SAMPLE_DEMO_CHANNELS_ON = (2, 3)
SAMPLE_DEMO_CHANGED = 4
SAMPLE_DEMO_CHANGED_AGO_S = 0.2
SAMPLE_DEMO_LOST = "no reply from the device"
# Where the demonstration in the pictures is: pre-sensitisation's filament series, at its go.
SAMPLE_DEMO_PHASE = "pre_sensitisation"
SAMPLE_DEMO_STAGE = "pre_sensitisation.long"
SAMPLE_DEMO_FILAMENT = "26"
SAMPLE_RESUME_BLOCKS = ("1", "2", "3", "4")
SAMPLE_RESUME_AGO_MIN = 72
SAMPLE_SESSION_NUMBER = 1
SAMPLE_LANGUAGES = ("sv", "en")
# The garment the checked session dialog shows chosen: the prototype, which the lab pilots on.
SAMPLE_GARMENT = "arduino_mosfet"
SAMPLE_T_ZERO = datetime(2026, 9, 24, 9, 30)
# The pattern designer's sample content. A moving example, and a name that is no condition's.
SAMPLE_DESIGN_PATTERN = cfg.CONFIG_DIR / "patterns" / "examples" / "sweep_03cms.csv"
SAMPLE_DESIGN_NAME = "sweep_draft"
SAMPLE_DESIGN_IDS = (1, 2, 3, 4, 5)
SAMPLE_DESIGN_INTERVAL_MS = 75.0
SAMPLE_DESIGN_HOLD_MS = 150.0
SAMPLE_TIMED_INTERVAL_MS = 100.0
SAMPLE_TIMED = ((1, 0, 500), (2, 400, 900), (3, 800, 1300), (4, 1200, 1700), (5, 1600, 2100))
SAMPLE_OFF_GRID = ((1, 0, 500), (2, 450, 900))
SAMPLE_PLAYBACK_S = 1.25
SAMPLE_PLAYBACK_ON = (2, 3)


@dataclass(frozen=True)
class Shot:
    name: str
    description: str
    pixmap: QPixmap

    @property
    def filename(self) -> str:
        return f"{self.name}.png"


class ManifestError(Exception):
    """The manifest and the catalogue disagree about which screens exist."""


# -- putting the windows into each state ---------------------------------------------------


def _grab(widget: QWidget) -> QPixmap:
    widget.resize(WIDTH_PX, HEIGHT_PX)
    return widget.grab()


def _experimenter_view(**overrides) -> dict:
    """A view in the shape `Session.experimenter_view()` returns.

    Hand-built rather than taken from a real session, because the states worth photographing
    are the ones a real session reaches rarely -- both banners up, open items outstanding --
    and reaching them for real would mean breaking the config to take a picture of it.
    `tests/test_ui.py` is where the window is driven from a real view.
    """
    view = {
        "participant_code": "01",
        "session_number": 1,
        "limb": "left",
        "experimenter_initials": "SM",
        "phase": "setup",
        "elapsed_s": 0.0,
        "garment_connected": True,
        "garment_driver": "mock",
        "placeholder_text": False,
        "reduced_capability_device": False,
        "unresolved_open_items": [],
        "fit_preview_enabled": False,
        "demo": False,
        "next_event": None,
        "interruption": None,
        "resuming": False,
        "hardware": {"connected": True, "link_lost": False, "faults": [],
                     "channel_pressure_kpa": None, "channels_on": None},
    }
    view.update(overrides)
    return view


def _participant_shots(config: cfg.Config, language: str) -> Iterator[Shot]:
    window = ParticipantWindow(config, Responder(config.hardware), Clock())
    text = config.participant_text

    for key in sorted(text["screens"]):
        window.show_message(key)
        yield Shot(
            f"participant_{language}_screen_{key}",
            f"The participant text `screens.{key}`, centred, {language}.",
            _grab(window),
        )

    for key in sorted(text["adjust_targets"]):
        window.show_adjustment(key)
        yield Shot(
            f"participant_{language}_adjust_{key}",
            f"The adjustment screen for `{key}`: the target, both large buttons drawn with "
            f"their labels, and the confirm sentence, {language}.",
            _grab(window),
        )

    window.show_adjustment(MATCH_TARGET, paired=True)
    window.emphasise_adjustment(0)
    yield Shot(
        f"participant_{language}_adjust_{MATCH_TARGET}_first_playing",
        f"The channel match (SPEC.md 9 step 3) while the first of its two alternating touches "
        f"plays: 'the first' and 'the second' between the buttons, the one playing in bold and "
        f"underlined (docs/LOG.md N7.F11c5), {language}.",
        _grab(window),
    )

    for key in sorted(k for k, v in text["audio_setup"].items() if isinstance(v, str)):
        window.show_audio_setup(key)
        yield Shot(
            f"participant_{language}_audio_setup_{key}",
            f"The masking check's `audio_setup.{key}` (SPEC.md 10.7), a text screen: its "
            f"wording names the buttons itself, so none are drawn, {language}.",
            _grab(window),
        )

    window.show_preference(1, len(config.study1["patterns"]["preference_candidates"]))
    yield Shot(
        f"participant_{language}_preference",
        f"The preference selection (SPEC.md 9 step 6): the opening line, both large buttons "
        f"drawn with their labels, the place in the list between them (LOG N7.F16k), and the "
        f"confirm sentence, {language}.",
        _grab(window),
    )

    yield from _choice_shots(window, text, language)

    window.show_blank()
    yield Shot(
        f"participant_{language}_blank",
        "Nothing at all -- what the participant sees during a stimulus.",
        _grab(window),
    )

    window.show_warning_cue()
    yield Shot(
        f"participant_{language}_cue",
        f"The visual warning cue: the `warning_cue` text alone, at the message position in "
        f"the button symbols' size, {language}.",
        _grab(window),
    )

    for scale in sorted(text["vas"]):
        window.show_vas(scale)
        yield Shot(
            f"participant_{language}_vas_{scale}_uncued",
            f"The `{scale}` scale with its question and anchors and NO marker -- the state "
            f"before the first press, {language}.",
            _grab(window),
        )

    for scale in sorted(text["training"]):
        window.show_vas_training(scale, accepting=False)
        yield Shot(
            f"participant_{language}_vas_training_{scale}",
            f"The VAS training for `{scale}` (SPEC.md 10.6) while the experimenter explains "
            f"the anchors and proportionality aloud: the scale exactly as it is rated, with no "
            f"marker and nothing below it; only the stop button does anything, {language}.",
            _grab(window),
        )

    # One scale is enough for the practice: its line is the same under every scale. Photographed
    # after the first press, so the marker the participant is practising with is in the shot.
    window.show_vas_training(VARIANT_SCALE, accepting=True)
    window.vas.state.press(Action.INCREASE, window.clock.real_elapsed_s())
    yield Shot(
        f"participant_{language}_vas_training_{VARIANT_SCALE}_practice",
        f"The `{VARIANT_SCALE}` training once the experimenter has pressed Next step: a "
        f"practice rating, `training.{VARIANT_SCALE}` below the scale, the marker shown after "
        f"a right press; ▶ confirms the practice, which is never recorded as a rating, "
        f"{language}.",
        _grab(window),
    )

    yield from _vas_variant_shots(window, language)

    # The remote's buttons on screen, for a pilot or a demonstration without it (docs/LOG.md
    # N7.F12e4). Every other participant screen is the remote's, with no buttons below it.
    responder = {**config.hardware["responder"], "participant_input": ON_SCREEN}
    on_screen = cfg.Config(**{**config.__dict__,
                              "hardware": {**config.hardware, "responder": responder}})
    buttons = ParticipantWindow(on_screen, Responder(on_screen.hardware), Clock())
    buttons.show_adjustment(sorted(text["adjust_targets"])[0])
    yield Shot(
        f"participant_{language}_on_screen_buttons",
        f"The adjustment screen with the remote's four buttons drawn below it, for a mouse or "
        f"trackpad (hardware page, 'Mouse or trackpad'): ‹ and › at the left, ▶ apart, the "
        f"stop alone at the right on its sticker's disc. Pilot codes and demonstrations only; "
        f"with the remote the window has no such row ({language}).",
        _grab(buttons),
    )
    _dispose(buttons)


def _choice_shots(window: ParticipantWindow, text: dict, language: str) -> Iterator[Shot]:
    """Every state of a drawn two-alternative choice (SPEC.md 10.8).

    All four are photographed because each one is a claim the review checks: that the buttons
    carry the device's own symbols, that emphasis is legible but not a recommendation, and that
    a chosen button is unmistakably chosen. The blank between trials is already covered by
    `participant_<language>_blank`, which is the same empty screen.
    """
    for key in sorted(text["choices"]):
        name = f"participant_{language}_choice_{key}"
        window.show_choice(key)
        yield Shot(
            f"{name}_waiting",
            f"`choices.{key}` with both buttons drawn and neither emphasised -- the state "
            f"before the first stimulus, {language}.",
            _grab(window),
        )

        # Only a choice between two stimuli emphasises a button; a question about something
        # already happening (`evenness`) never reaches that state.
        if key in PAIRED_CHOICES:
            window.emphasise_choice("left")
            yield Shot(
                f"{name}_emphasis_left",
                "The left button's outline thickened while its stimulus plays "
                "(UI_PRINCIPLES.md 5.11). It must read as `this is the one you are feeling`, "
                "never as a suggestion.",
                _grab(window),
            )

        window.accept_choice()
        yield Shot(
            f"{name}_accepting",
            "Both stimuli delivered, no emphasis, the next press is the answer. Identical to "
            "the waiting state by design: nothing on screen may hint that a press is due.",
            _grab(window),
        )

        window.choice.selected = "right"
        window.choice.update()
        yield Shot(
            f"{name}_chosen_right",
            "The right button shown back as chosen -- filled, its symbol reversed out. Set "
            "directly rather than by pressing, because the press starts a timer that would "
            "blank the screen before it could be grabbed.",
            _grab(window),
        )


def _vas_variant_shots(window: ParticipantWindow, language: str) -> Iterator[Shot]:
    """The marker positions and both first-press sides SPEC.md 17.4 asks for."""
    state = window.vas.state
    for side, action in (("left", Action.DECREASE), ("right", Action.INCREASE)):
        window.show_vas(VARIANT_SCALE)
        state.cue()
        state.press(action, window.clock.real_elapsed_s())
        yield Shot(
            f"participant_{language}_vas_{VARIANT_SCALE}_first_press_{side}",
            f"The marker where a first {side} press puts it -- SPEC.md 10.2's rule that the "
            f"marker appears on the side that was pressed.",
            _grab(window),
        )

    for percent in MARKER_POSITIONS:
        window.show_vas(VARIANT_SCALE)
        state.cue()
        state.press(Action.INCREASE, window.clock.real_elapsed_s())
        # Set directly rather than pressing there. The pixels are the point, and stepping to
        # 5 % at move_step_pct would be a hundred presses photographing nothing new.
        state.percent = percent
        window.vas.update()
        yield Shot(
            f"participant_{language}_vas_{VARIANT_SCALE}_at_{percent:g}pct",
            f"The marker at {percent:g} % along the line, no numbers and no tick marks "
            f"beyond the labelled anchors.",
            _grab(window),
        )


def _sample_f40_fit() -> F40Fit:
    sample = SAMPLE_F40
    result = LongResult(
        phase="pre_sensitisation", region="primary", run_index=sample["run_index"],
        start_filament_label_g=sample["filament"], start_source="config_default",
        f40_mn=sample["f40_mn"], chosen_filament_label_g=sample["filament"],
        chosen_force_mn=sample["filament_mn"], out_of_range=False, out_of_range_direction="",
        capped=False, applications_total=sample["total"],
        applications_measure=sample["measure"], ordinal_rho=sample["rho"],
    )
    return F40Fit(result, sample["slope"], sample["target"], sample["points"])


def _sample_touch_fit() -> FitReady:
    sample = SAMPLE_TOUCH
    fit = maths.RatingFit(
        fit_form=maths.LOG_PRESSURE, intercept=sample["intercept"], slope=sample["slope"],
        r_squared=sample["r_squared"], residual_sd=sample["residual_sd"],
        span_vas=sample["span"], spearman_rho=sample["rho"],
        bracket_min_kpa=sample["bracket"][0], bracket_max_kpa=sample["bracket"][-1],
    )
    return FitReady(
        run_index=sample["run_index"], points=sample["points"], fit=fit,
        r_squared=sample["r_squared"], residual_sd=sample["residual_sd"], monotonic=True,
        stage1_pass=True, stage1_failures=(), p20_kpa=sample["p"][0], p30_kpa=sample["p"][1],
        p80_kpa=sample["p"][-1],
    )


def _experimenter_states(config: cfg.Config) -> dict:
    """Every state of the window: (description, view overrides, what the protocol pushes in).

    What the protocol pushes -- the instruction, the status, the target, the awaited actions --
    is a function of the window, applied after a fresh window is built for each state so no
    state inherits another's.
    """
    text = config.experimenter_text
    instructions = text["instructions"]
    step_mm = f"{float(config.study1['mapping']['step_size_mm']):g}"
    filament = SAMPLE_F40["filament"]
    path = text["terms"]["mapping_paths"][SAMPLE_PATH]
    upcoming = {**SAMPLE_BLOCK, "due_in_s": SAMPLE_DUE_IN_S, "due_soon": False,
                "overdue": False}

    def instruct(key, heading, **values):
        return lambda window: window.set_instruction(cfg.instruction(config, key, **values),
                                                     heading)

    def pinprick(window):
        # While the participant rates the 26 g at site 3: the next one to have ready.
        window.set_instruction(cfg.instruction(config, "rating_next_filament",
                                               filament=filament), PREPARE)
        window.set_target("primary", SAMPLE_SITE + 1, filament=True)
        window.set_progress(text["status"]["progress"].format(done=SAMPLE_PROGRESS,
                                                              total=SAMPLE_SHORT_N))
        window.set_status(instructions["await_participant"])
        # What a filament trial offers while it runs (tatp/pinprick.py `_connect_extra`).
        window.set_actions_enabled(substitution=True)

    # What is up while a block is waited for, and once it is due: the sample block is a touch
    # block.
    waiting = instruct("waiting", WAIT)
    ready = instruct("ready_touch_block", NOW, block=SAMPLE_BLOCK["block_index"])

    return {
        "plain": (
            "No banners, no open items, nothing scheduled -- a correctly configured session "
            "at setup. The routine controls along the bottom, Next emphasised; the "
            "situational ones (Resume, Discard, the rematch, Re-calibrate, the fit choice, "
            "the filament applied instead, the mapping distances) hidden in places kept for "
            "them; no zone diagram, since there is no target; the garment's state, channels "
            "and button together on the right.",
            {}, None,
        ),
        "placeholder_banner": (
            "The unapproved-wording banner (SPEC.md 12.4), red and unmissable.",
            {"placeholder_text": True}, None,
        ),
        "reduced_capability_banner": (
            "The reduced-capability banner naming the garment in use in words, as the "
            "launcher does (SPEC.md 12.4).",
            {"reduced_capability_device": True, "garment_driver": SAMPLE_GARMENT}, None,
        ),
        "demo_banner": (
            "The demonstration banner (docs/LOG.md N7.D23), amber like the others that say "
            "the session runs but what it records is not data.",
            {"demo": True}, None,
        ),
        "all_banners": (
            "All three banners at once, one line each with the detail in the tooltip, in the "
            "space they need, which is fixed from the session's start: no banner comes or "
            "goes during a session, so nothing below moves (UI_PRINCIPLES.md 3.3). The "
            "fit-preview banner is amber like the reduced-capability one (SPEC.md 11.1).",
            {"placeholder_text": True, "reduced_capability_device": True,
             "garment_driver": SAMPLE_GARMENT, "fit_preview_enabled": True}, None,
        ),
        "open_items": (
            "Unresolved open items listed for the experimenter (SPEC.md 20): one small amber "
            "line at the foot of the banner region, by number, the summaries in the tooltip.",
            {"unresolved_open_items": SAMPLE_OPEN_ITEMS}, None,
        ),
        "disconnected": (
            "The garment reported disconnected: red and bold in the hardware panel, and its "
            "button reading Connect garment, emphasised as the way forward.",
            {"hardware": {**SAMPLE_HARDWARE, "connected": False}}, None,
        ),
        "pinprick_primary": (
            "A pinprick application rated: under Prepare, the next filament to have ready, "
            "its site marked among the zone's eight on the diagram beside the instruction, "
            "the series' progress at the heading's right, the technique text below, the "
            "response pending -- never its value -- and the filament-applied-instead choice "
            "at the foot, as it is only during a filament trial (S, 21 Oct 2026).",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S}, pinprick,
        ),
        "pinprick_apply": (
            "The filament is due: under Now, S's wording, the site on the diagram, Next "
            "pressable (S, 21 Oct 2026).",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                instruct("apply_filament", NOW, filament=filament)(window),
                window.set_target("primary", SAMPLE_SITE, filament=True),
                window.set_progress(text["status"]["progress"].format(
                    done=SAMPLE_PROGRESS, total=SAMPLE_SHORT_N)),
                window.set_actions_enabled(substitution=True),
            ),
        ),
        "pinprick_interval": (
            "The rest before the next filament: under Wait with the seconds left, the next "
            "filament and its site (S, 16 and 21 Oct 2026).",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                window.set_instruction(cfg.instruction(config, "next_filament",
                                                       filament=filament), WAIT,
                                       SAMPLE_REST_S),
                window.set_target("primary", SAMPLE_SITE, filament=True),
                window.set_progress(text["status"]["progress"].format(
                    done=SAMPLE_PROGRESS, total=SAMPLE_SHORT_N)),
            ),
        ),
        "substitution_recorded": (
            "A lighter filament recorded as applied instead: the message beside Correct last "
            "application…, in the target colour, until the next application starts (S, 21 and "
            "22 Oct 2026).",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                pinprick(window),
                window.set_filaments([f["label_g"] for f in config.filaments["filaments"]]),
                window.show_substitution(text["warnings"]["substitution_recorded"].format(
                    filament=SAMPLE_SUBSTITUTE), CONFIRMED),
            ),
        ),
        "prepare_series": (
            "Before a series: under Prepare, S's wording, and the zone it is in on the diagram "
            "(S, 21 Oct 2026).",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                instruct("ready_short", PREPARE, filament=filament)(window),
                window.set_target("primary"),
            ),
        ),
        "pilot_rig_pinprick": (
            "What the 15 Oct 2026 pilot looked like: the prototype sleeve's reduced-capability "
            "banner and the open items above a filament trial.",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S,
             "reduced_capability_device": True, "garment_driver": SAMPLE_GARMENT,
             "unresolved_open_items": SAMPLE_OPEN_ITEMS},
            pinprick,
        ),
        "brush_secondary": (
            "A brush stroke in the secondary zone: the dashed ellipse outlined.",
            {"phase": "post_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                instruct("apply_brush", NOW)(window),
                window.set_target("secondary", SAMPLE_SITE),
            ),
        ),
        "mapping": (
            "A mapping path: the four paths on the diagram, the one being walked heavy, the "
            "technique text shown because a filament is used, and the mapping distances box "
            "on the right now that a phase has been mapped (S, 21 Oct 2026).",
            {"phase": "post_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                window.set_instruction(
                    cfg.instruction(config, "mapping_path", path=path, step=step_mm), NOW
                ),
                window.set_target("secondary", filament=True, path=SAMPLE_PATH),
                window.set_mapping_phases(["post_sensitisation"]),
            ),
        ),
        "distances": (
            "The mapping distances box with a row per mapped time point: two recorded, "
            "outlined in the target colour, one queried in amber, and the line under the "
            "fields saying why and what to do (S, 21 Oct 2026).",
            {"phase": "post_intervention", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                waiting(window),
                window.set_mapping_phases(["post_sensitisation", "post_intervention"]),
                _type_distances(window, config),
            ),
        ),
        "block_pinprick": (
            "A pinprick block in the intervention: the countdown to the next block in grey, "
            "no pressures (hidden for blinding, SPEC.md 16) and no placeholder in their place.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S, "next_event": upcoming},
            pinprick,
        ),
        "block_touch": (
            "A touch block in the intervention: the one line shown at every touch start in "
            "every condition, and nothing else that could differ between them.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S},
            instruct("touch_start", WAIT),
        ),
        "intervention_fault": (
            "A garment fault during the intervention: shown in red, counted, and without the "
            "channel, which could say which pattern is running (SPEC.md 16).",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "hardware": {**SAMPLE_HARDWARE, "faults": [SAMPLE_FAULT]}},
            instruct("touch_start", WAIT),
        ),
        "countdown": (
            "Waiting for the next block: 'Next: block 3 (touch) in 04:05', grey, and the "
            "heading saying Wait with the same time left.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S, "next_event": upcoming},
            waiting,
        ),
        "block_due_soon": (
            "The block due within the due alert's lead: calmly, in amber, with its time "
            "left (S, 21 Oct 2026).",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "next_event": {**SAMPLE_BLOCK, "due_in_s": SAMPLE_DUE_SOON_S, "due_soon": True,
                            "overdue": False}},
            waiting,
        ),
        "block_due": (
            "The block is due: amber and bold in the same place as the countdown, and how late "
            "beside the session clock, in amber.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "next_event": {**SAMPLE_BLOCK, "due_in_s": SAMPLE_DUE_NOW_S, "due_soon": True,
                            "overdue": False}},
            ready,
        ),
        "block_overdue": (
            "The block past the overdue alert's margin: still 'due now' in amber where the "
            "countdown is, and how late beside the session clock, now in red (S, 21 Oct 2026: "
            "a red OVERDUE was alarming).",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "next_event": {**SAMPLE_BLOCK, "due_in_s": SAMPLE_OVERDUE_S, "due_soon": True,
                            "overdue": True}},
            ready,
        ),
        "rekindle_due": (
            "The rekindle is due: a timed event that is not a block, named by its phase, and "
            "the thermode to place.",
            {"phase": "rekindle", "elapsed_s": SAMPLE_ELAPSED_S,
             "next_event": {"kind": "rekindle", "label_key": "rekindle", "block_index": None,
                            "block_type": None, "due_in_s": SAMPLE_DUE_NOW_S,
                            "due_soon": True, "overdue": False}},
            instruct("thermode_rekindle", NOW),
        ),
        "interrupted_emergency_stop": (
            "The participant pressed the stop: the red line under the phase, the step on hold "
            "dimmed beneath it, Resume emphasised in its own slot and Abort the only controls "
            "offered, Next step greyed, and nothing moved.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "interruption": "emergency_stop"},
            # The stop cancels the trial, which withdraws the correction's offer
            # (tatp/pinprick.py `_disconnect_extra`).
            lambda window: (pinprick(window),
                            window.set_actions_enabled(substitution=False)),
        ),
        "touchcal_stopped_recalibrate": (
            "The participant pressed the stop during touch calibration's step 4, with step 2's "
            "fit accepted: beside Resume, Re-calibrate… is offered, in the place of the "
            "rematch in the situational row; its dialog asks what to repeat and why (docs/"
            "LOG.md N7.F12a1; S, 21 Oct 2026). The same in every condition; nothing else "
            "moved.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S,
             "interruption": "emergency_stop"},
            lambda window: (
                instruct("touchcal_equalise", WAIT, **SAMPLE_MATCH)(window),
                window.set_actions_enabled(recalibrate_rebalance=True,
                                           recalibrate_restart=True),
            ),
        ),
        "intervention_recalibrate": (
            "The intervention, waiting for the next block with the condition's touch on: "
            "Re-calibrate… offered at any time, as during touch calibration (S, 15 Oct 2026; "
            "docs/LOG.md N7.F12a1). The same in every condition, and no pressures (SPEC.md "
            "16).",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S, "next_event": upcoming},
            lambda window: (
                waiting(window),
                window.set_actions_enabled(recalibrate_rebalance=True,
                                           recalibrate_restart=True),
            ),
        ),
        "touchcal_stopped_recalibration_used": (
            "A stop during touch calibration once the re-calibrations a limit allows "
            "(recalibrations_max, none by default) are used: Resume only, and one grey line "
            "where the two offers were saying why.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S,
             "interruption": "emergency_stop"},
            lambda window: (
                instruct("touchcal_estimation", WAIT, answered=SAMPLE_ANSWERED,
                         total=SAMPLE_PRESENTATIONS)(window),
                window.set_actions_enabled(recalibration_used=True),
            ),
        ),
        "interrupted_pause": (
            "The experimenter's pause: the same line in amber, the step dimmed, Resume "
            "offered.",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S,
             "interruption": "pause"},
            instruct("ready_long", PREPARE, filament=filament),
        ),
        "status_warning": (
            "A warning in the status region, in amber, kept apart from the routine status so "
            "the next 'Waiting for...' does not replace it (15 Oct 2026 pilot review). It goes "
            "under the routine line; this one is too long for both, so it has the region.",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                pinprick(window),
                window.set_warning(text["warnings"]["out_of_range"].format(
                    value=text["terms"]["out_of_range"]["above"]
                )),
            ),
        ),
        "first_pain_measures": (
            "Before the session's first pain measure: what to tell the participant, set down "
            "the type scale to fit its region.",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            instruct("ready_long_first", PREPARE),
        ),
        "fit_garment": (
            "The first step of a session: the garment, the remote's buttons by their printed "
            "symbols, the headphones and the cue, then Next.",
            {"phase": "setup"},
            instruct("fit_garment", NOW),
        ),
        "hardware_pressures": (
            "Touch calibration: the hardware panel with every channel's pressure and one "
            "fault, in red.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S,
             "hardware": {**SAMPLE_HARDWARE, "channel_pressure_kpa": SAMPLE_PRESSURES_KPA,
                          "channels_on": SAMPLE_CHANNELS_ON,
                          "faults": [SAMPLE_FAULT]}},
            instruct("touchcal_match", WAIT, **SAMPLE_MATCH),
        ),
        "link_lost": (
            "The prototype sleeve's link lost mid-session (docs/LOG.md N7.U16): shown "
            "disconnected, the warning that it may still be on first in the fault line, then "
            "the newest fault's start; the earlier-fault count gives way to them.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S,
             "garment_connected": False,
             "hardware": {**SAMPLE_HARDWARE, "connected": False, "link_lost": True,
                          "faults": [SAMPLE_FAULT, SAMPLE_LINK_FAULT]}},
            instruct("touchcal_match", WAIT, **SAMPLE_MATCH),
        ),
        "long_instruction": (
            "A long instruction: an unusable touch estimate with no re-runs left. At the large "
            "size, as every instruction is (LOG N7.F17e); nothing below it has moved, and the "
            "one answer offered is the fallback, on a button of its own, as the procedure "
            "offers it.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                window.set_instruction(cfg.instruction(
                    config, "touchcal_stage1_exhausted", value=text["terms"]["stage1"]["flat"]
                ), NOW),
                window.offer_alternative(text["controls"]["fit_fallback"]),
            ),
        ),
        "touchcal_estimation_skip": (
            "The estimation run with the mock or prototype garment: how many ratings are "
            "answered, and Skip calibration in the situational row, shown only on a pilot rig "
            "once a few ratings are in (docs/LOG.md N7.F8b, N7.F8c). Nothing else has moved.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                instruct("touchcal_estimation", WAIT, answered=SAMPLE_ANSWERED,
                         total=SAMPLE_PRESENTATIONS)(window),
                window.set_actions_enabled(skip_calibration=True),
            ),
        ),
        "awaiting_rebalance": (
            "The evenness question answered 'uneven': the rematch offered beside Next, "
            "because the procedure waits on either.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S,
             "hardware": {**SAMPLE_HARDWARE, "channel_pressure_kpa": SAMPLE_PRESSURES_KPA,
                          "channels_on": SAMPLE_CHANNELS_ON}},
            lambda window: (
                window.set_instruction(cfg.instruction(config, "touchcal_uneven"), NOW),
                window.set_actions_enabled(rebalance=True),
            ),
        ),
        "intervention_end": (
            "The intervention over and the garment off: what to tell the participant before "
            "the measures begin again, then Next (docs/LOG.md N7.F11c10). The same in "
            "every condition.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S},
            instruct("intervention_end", NOW),
        ),
        "session_complete": (
            "The last state: the session closed and every file written, the garment to come "
            "off, what was saved and how to upload it under the instruction, and Finish "
            "session to close the program (docs/LOG.md N7.F11c9; S, 21 Oct 2026). The "
            "garment is shown disconnected, as closing the session leaves it, and Pause and "
            "the garment button are withdrawn: nothing is left to pause or to connect again.",
            {"phase": "session_end", "elapsed_s": SAMPLE_ELAPSED_S, "garment_connected": False,
             "hardware": {**SAMPLE_HARDWARE, "connected": False}},
            lambda window: (
                window.set_instruction(cfg.instruction(config, "session_complete"), NOW),
                window.set_detail(_sample_data_check(config)),
                window.set_actions_enabled(closed=True),
            ),
        ),
        "fit_preview_f40": (
            "The main window while the F40 fit preview (SPEC.md 11.1) is open, only with "
            "fit_preview.enabled: the banner saying what it costs, the instruction saying the "
            "decision is due, Re-run and Accept offered, and no rating anywhere on this "
            "window -- they are in the preview window.",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S,
             "fit_preview_enabled": True},
            lambda window: (
                window.set_instruction(cfg.instruction(config, "f40_fit_review"), NOW),
                window.set_actions_enabled(fit_decision=True),
                window.show_fit_preview(_sample_f40_fit()),
            ),
        ),
        "fit_preview_touch": (
            "The main window while the touch-calibration fit preview is open: its instruction "
            "at a smaller size because it is long, Accept and Re-run offered.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S,
             "fit_preview_enabled": True},
            lambda window: (
                window.set_instruction(cfg.instruction(config, "touchcal_fit_review"), NOW),
                window.set_actions_enabled(fit_decision=True),
                window.show_fit_preview(_sample_touch_fit()),
            ),
        ),
    }


def _session_phases(config: cfg.Config) -> list[str]:
    """The phases on a session's timeline, as `SessionRunner.phases` lists them."""
    return session_phases(schedule.generate(config.schedule))


def _grab_checked(window: QWidget, name: str) -> QPixmap:
    """`_grab`, refusing a layout that no longer fits the screen: it would grow the grab and
    pass as a differently-sized picture."""
    pixmap = _grab(window)
    assert pixmap.height() == HEIGHT_PX, f"{name} needs {pixmap.height()} px of {HEIGHT_PX}"
    return pixmap


def _demo_window(config: cfg.Config, sample: _SampleDemo, lose: str | None = None):
    """A demonstration's experimenter window, its channels fed by `sample` as `Demo` feeds
    them, with the demo controls along its foot."""
    link_lost = lose is not None
    hardware = {**SAMPLE_HARDWARE, "connected": not link_lost, "link_lost": link_lost,
                "faults": [SAMPLE_LINK_FAULT] if link_lost else []}
    view = _experimenter_view(demo=True, phase=SAMPLE_DEMO_PHASE, elapsed_s=SAMPLE_ELAPSED_S,
                              garment_connected=not link_lost, hardware=hardware)
    window = _session_window(config, lambda: view)
    window.resize(WIDTH_PX, HEIGHT_PX)
    window.garment_fed_elsewhere = True
    window.garment_display.show_states(sample.states(), False, 0.0)
    if lose is not None:
        # As `Demo` feeds a lost link: the last commanded state held, in amber.
        sample.garment.lost(lose)
        window.garment_display.show_states(sample.states(), True, 0.0)
    window.garment_display.setVisible(True)
    window.set_instruction(cfg.instruction(config, "ready_long",
                                           filament=SAMPLE_DEMO_FILAMENT), PREPARE)
    window.set_target("secondary")
    responder = Responder(config.hardware)
    controls = DemoControls(
        sample, config.experimenter_text,
        {action: responder.symbol_for(action, pointing_at_stop=True) for action in Action},
    )
    controls.timer.stop()
    window.add_demo_panel(controls)
    window.refresh()
    return window, controls


def _session_window(config: cfg.Config, read_view) -> ExperimenterWindow:
    """The experimenter window as a session sets it up: the phases on its timeline (LOG
    N7.F16h) and the mock garment's channels in its side column (N7.F16i)."""
    window = ExperimenterWindow(config.experimenter_text, read_view)
    window.set_timeline(_session_phases(config))
    # The row of the phase's steps, as a session sets it (S, 21 Oct 2026): the view's phase,
    # at its first step.
    plan = stage_plan(schedule.generate(config.schedule), config.experimenter_text)
    phase = read_view()["phase"]
    if phase in plan:
        window.set_stage_plan(plan)
        window.set_stage(phase, plan[phase][0][0])
    # Next step pressable where the instruction asks for it, as a session's is (UI_PRINCIPLES.md
    # 5.13, 5.16), not in every picture: there is no procedure here to ask.
    proceed = config.experimenter_text["controls"]["proceed"]
    window.set_proceed_source(lambda: proceed in window._instruction_text)
    garment = MockGarment(Limits.from_config(config.hardware), Clock())
    window.set_garment(garment.channels(), garment.limits.pressure_ceiling_kpa,
                       garment.per_channel_pressure,
                       float(config.hardware["screens"]["garment_highlight_s"]))
    return window


def _experimenter_shots(config: cfg.Config, language: str) -> Iterator[Shot]:
    text = config.experimenter_text
    for name, (description, overrides, push) in _experimenter_states(config).items():
        view = _experimenter_view(**overrides)
        window = _session_window(config, lambda view=view: view)
        # Sized first, so a long instruction is fitted to the width it will be drawn at.
        window.resize(WIDTH_PX, HEIGHT_PX)
        if push is not None:
            push(window)
        window.refresh()
        pixmap = _grab(window)
        # A layout whose minimum is taller than the screen grows the grab rather than failing,
        # so a state that no longer fits would pass as a differently-sized picture.
        assert pixmap.height() == HEIGHT_PX, (
            f"experimenter_{language}_{name} needs {pixmap.height()} px of {HEIGHT_PX}"
        )
        yield Shot(f"experimenter_{language}_{name}", f"{description} ({language})", pixmap)
        if window.fit_preview.isVisible():
            yield Shot(
                f"experimenter_{language}_{name}_window",
                f"The fit preview window itself for `{name}`: the plot, the quality, what the "
                f"session will use, and Accept / Re-run ({language}).",
                window.fit_preview.grab(),
            )
            window.hide_fit_preview()

    window = ExperimenterWindow(text, _experimenter_view)
    dialogs = {
        "abort_dialog": (
            "The abort confirmation: what happens to the data, a reason field, and Abort "
            "disabled until a reason is typed.",
            window.abort_dialog(),
        ),
        "rerun_dialog": (
            "The re-run reason, asked before a fit is discarded (SPEC.md 11.1).",
            window.rerun_dialog(),
        ),
        "error_dialog": (
            "The error dialog: a red title and the message as raised.",
            window.error_dialog(SAMPLE_ERROR),
        ),
    }
    window.set_actions_enabled(recalibrate_rebalance=True, recalibrate_restart=True)
    dialogs["recalibrate_dialog"] = (
        "Re-calibrate…: what each choice repeats, then why, from a fixed list; Re-calibrate "
        "disabled until both are chosen (docs/LOG.md N7.F12a1; S, 21 Oct 2026).",
        window.recalibration_dialog(),
    )
    dialogs["recalibrate_dialog_chosen"] = (
        "Re-calibrate… with Restart the calibration and a reason chosen, shown pressed, so "
        "Re-calibrate is enabled.",
        _chosen(window.recalibration_dialog(), "restart", "channel_uneven"),
    )
    # Correct last application… for the 26 g just given (S, 22 Oct 2026).
    given = config.study1["pinprick"]["primary_filament_label_g"]
    window.set_filaments([f["label_g"] for f in config.filaments["filaments"]
                          if f["label_g"] != given])
    window.set_actions_enabled(substitution=True, discard=False)
    dialogs["correction_dialog"] = (
        "Correct last application… before the rating is in: another filament from the set, "
        "or Discard and repeat, listed greyed, saying when it can be taken.",
        window.correction_dialog(),
    )
    window.set_actions_enabled(discard=True)
    dialogs["correction_dialog_rated"] = (
        "Correct last application… in the rest after the rating: both corrections offered.",
        window.correction_dialog(),
    )
    for name, (description, dialog) in dialogs.items():
        yield Shot(f"experimenter_{language}_{name}", f"{description} ({language})",
                   _grab_dialog(dialog))

    yield from _launcher_shots(config, language)


def _dispose(window: QWidget) -> None:
    """Close a shown window and delete it now, in Qt's own time. Left to the garbage
    collector, a window in a reference cycle is destroyed whenever a later allocation
    triggers a collection -- possibly inside another window's construction, where a signal
    it emits while dying reaches a half-deleted object (docs/LOG.md N7.I3)."""
    window.close()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _chosen(dialog, action: str, reason: str):
    """A re-calibration dialog with `action` and `reason` chosen, as the experimenter leaves
    it."""
    dialog.actions[action].click()
    dialog.options[reason].click()
    return dialog


def _type_distances(window, config: cfg.Config) -> None:
    """Post-sensitisation's distances in, one confirmed outside the range; post-
    intervention's partly typed, one with either decimal mark, and one queried as inside the
    primary zone -- as the ledger reports them."""
    text = config.experimenter_text
    box = window.distances
    for field, typed in zip(box.fields("post_sensitisation"), SAMPLE_DISTANCES * 2,
                            strict=False):
        field.setText(typed)
    later = box.fields("post_intervention")
    later[0].setText(SAMPLE_DISTANCES[0])
    later[1].setText(SAMPLE_INSIDE_MM)
    every_path = set(range(1, len(box.path_ids) + 1))
    box.show_outcome("post_sensitisation", every_path, set(), set(), "", CONFIRMED)
    paths = text["terms"]["mapping_paths"]
    path_ids = list(paths)
    # The first path recorded, the second queried, the rest walked and still awaited.
    first, second, *rest = sorted(every_path)
    box.show_outcome("post_intervention", {first}, {second}, set(rest),
                     text["distances"]["inside_primary"].format(
                         phase=text["timeline"]["post_intervention"],
                         path=paths[path_ids[1]], value=SAMPLE_INSIDE_MM),
                     QUERIED)


def _sample_data_check(config: cfg.Config) -> str:
    """What the session-complete page says was saved and how to upload it, for the sample."""
    words = config.experimenter_text["data_check"]
    return "\n".join((
        words["saved"].format(files=SAMPLE_DATA_FILES, folder=SAMPLE_DATA_FOLDER),
        words["none_missing"],
        words["upload"].format(code=SAMPLE_PARTICIPANT, session=SAMPLE_SESSION_NUMBER,
                               upload_folder=config.hardware["data"]["upload_folder"]),
    ))


def _grab_dialog(dialog: QWidget) -> QPixmap:
    # A long wrapped message needs more height at this width than the size hint, which is
    # worked out at the dialog's own preferred width, gives it; it was cut off top and bottom.
    layout = dialog.layout()
    wrapped = (layout.totalHeightForWidth(DIALOG_WIDTH_PX)
               if layout is not None and layout.hasHeightForWidth() else 0)
    dialog.resize(DIALOG_WIDTH_PX, max(dialog.sizeHint().height(), wrapped))
    return dialog.grab()


class _SampleDemo(QObject):
    """What the demo controls draw from, with no session behind it: a person at both places,
    a connected mock garment with every channel's pressure set and some channels on, and the
    filament series of pre-sensitisation under way."""

    stage_started = Signal(str)

    def __init__(self, config: cfg.Config, worn: bool = False):
        super().__init__()
        self.runner = self
        self.session = self
        # Drawn as on a worn garment (tatp/demo.py), the mock standing in for it.
        self.worn = worn
        self.settings = demo_rests(config.study1, DEMO_GARMENT)["demo"]
        self.clock = Clock()
        self.garment = MockGarment(Limits.from_config(config.hardware), self.clock)
        self.garment.connect()
        kpa = self.garment.limits.pressure_ceiling_kpa * SAMPLE_DEMO_PRESSURE_FRACTION
        for channel in self.garment.channels():
            self.garment.set_pressure(channel, kpa)
        for channel in SAMPLE_DEMO_CHANNELS_ON:
            self.garment.set_channel(channel, True)
        self.participant_mode = OFF
        self.experimenter_mode = OFF
        self.auto_running = False
        self.config = config
        self.schedule = schedule.generate(config.schedule)
        self.phases = _session_phases(config)
        self.phase = SAMPLE_DEMO_PHASE
        self.stages = [SimpleNamespace(id=stage_id, phase=phase)
                       for stage_id, phase, _ in stage_layout(self.schedule)]
        self.stage_index = [stage.id for stage in self.stages].index(SAMPLE_DEMO_STAGE)
        # No touch calibration has run, so on a worn garment the intervention's touch cannot
        # be jumped to.
        self.deliveries = None

    def choose(self, who: str, mode: str) -> None:
        setattr(self, f"{who}_mode", mode)

    def jumpable(self, stage_id: str) -> bool:
        stage = next(stage for stage in self.stages if stage.id == stage_id)
        return not (self.worn and stage.phase == INTERVENTION
                    and stage_id != "intervention.start")

    def differs_now(self) -> str | None:
        # The filament series under way: its rests are a demonstration's.
        return RESTS_DIFFER

    def states(self) -> dict:
        return states_from_status(self.garment.status(), self.garment.channels(),
                                  bool(self.garment.connected),
                                  self.garment.per_channel_pressure)


def _sample_detectors(screens, ports, remote, outputs) -> Detectors:
    """What the hardware page is told is connected, fixed for the picture: the screens and the
    devices attached differ between machines, and the picture is of the page, not of this
    machine's hardware. The outputs are the lab laptop's on 30 Sep 2026, as far as needed."""

    def probe(request, on_done):
        on_done(sample_probe(request, list(outputs), outputs[0]), "")

    return Detectors(lambda: list(screens), lambda: list(ports), lambda: remote, probe)


def sample_probe(request: dict, outputs: list[str], default: str | None,
                 unusable: dict[str, str] | None = None) -> dict:
    """`tatp.devices.probe`'s answer for these outputs, with no PortAudio: a device can be
    opened when its name matches exactly one output (and the default when there is one),
    unless `unusable` gives a reason it cannot play at the configured settings."""
    unusable = unusable or {}
    checks = {}
    for role, specs in request["candidates"].items():
        checks[role] = {}
        for spec in specs:
            found = (default is not None if spec is None
                     else len(matching_outputs(spec, outputs)) == 1)
            why = "" if found else f"No output device matching {spec!r}"
            checks[role][check_key(spec)] = unusable.get(spec, why) if found else why
    return {"outputs": outputs, "default": default, "checks": checks}


SAMPLE_OUTPUTS = (
    "Speakers (Realtek(R) Audio), Windows WASAPI",
    "Headphones (Realtek(R) Audio), Windows WASAPI",
    "Headphones (Bose QC Headphones), Windows WASAPI",
)
SAMPLE_SCREEN = (WIDTH_PX, HEIGHT_PX)


def _launcher_shots(config: cfg.Config, language: str) -> Iterator[Shot]:
    """The launcher and its dialogs (SPEC.md 4.1). Nothing is started and nothing is written."""
    def no_session(config, args):
        raise AssertionError("the screenshot run never starts a session")

    def findings(config, args):
        return [(WARN, "warnings.experimenter_changed", "")]

    launcher = LauncherWindow(config, preflight=findings, build=no_session)
    yield Shot(
        f"experimenter_{language}_launcher",
        f"The launcher's four entries (SPEC.md 4.1), all enabled. Design a pattern says it is "
        f"for S only, because it shows pattern names and shapes ({language}).",
        _grab_dialog(launcher),
    )

    demo = launcher.session_dialog(demo=True)
    # The configured folder resolves to an absolute path that differs between machines.
    demo.pattern_folder.setText(SAMPLE_PATTERN_FOLDER)
    yield Shot(
        f"experimenter_{language}_launcher_demo",
        f"Run a demo (docs/LOG.md N7.D23): the session dialog with the demonstration's own "
        f"participant code shown and not editable, no data folder or REDCap form, the mock "
        f"garment (changeable: another runs at real time only, with people pressing, "
        f"N7.F12f) and the example "
        f"patterns chosen, and the speed and who presses for the "
        f"participant and the experimenter ({language}).",
        _grab_dialog(demo),
    )
    sample = _SampleDemo(config)
    window, controls = _demo_window(config, sample)
    yield Shot(
        f"experimenter_{language}_demo_controls",
        f"A demonstration's experimenter window (docs/LOG.md N7.D23, N7.F16j): the timeline, "
        f"the channels as commanded in the side column -- every channel's pressure set, "
        f"channels {', '.join(map(str, SAMPLE_DEMO_CHANNELS_ON))} on -- and the demo controls "
        f"along the foot: who presses for the participant and the experimenter (manual, auto "
        f"watchable or auto fast), the clock's speed, the remote's buttons, Auto-run, Jump to "
        f"offering every step of every phase with the one after the step under way chosen "
        f"(S, 21 Oct 2026), and how the filament series under way differs from a session -- "
        f"its rests -- in violet beside them (N7.F17d) ({language}).",
        _grab_checked(window, f"experimenter_{language}_demo_controls"),
    )
    sample.garment.set_channel(SAMPLE_DEMO_CHANGED, True)
    changed_s = time.monotonic()
    display = window.garment_display
    display.show_states(sample.states(), False, changed_s)
    display.show_states(sample.states(), False, changed_s + SAMPLE_DEMO_CHANGED_AGO_S)
    controls.remote.set_held(Action.INCREASE, True)
    controls.sync()
    yield Shot(
        f"experimenter_{language}_demo_controls_garment_changed",
        f"The same {SAMPLE_DEMO_CHANGED_AGO_S:g} s after channel {SAMPLE_DEMO_CHANGED} was "
        f"turned on (docs/LOG.md N7.F12f): its row lit and its bar outlined, fading back over "
        f"screens.garment_highlight_s; and the remote's right button held ({language}).",
        _grab_checked(window, f"experimenter_{language}_demo_controls_garment_changed"),
    )
    window, _ = _demo_window(config, _SampleDemo(config, worn=True), lose=SAMPLE_DEMO_LOST)
    yield Shot(
        f"experimenter_{language}_demo_controls_worn_link_lost",
        f"A demonstration on a worn garment, its link lost (docs/LOG.md N7.F12f): the "
        f"participant and the experimenter people, and auto-run off, said in amber, and the "
        f"intervention's steps greyed in Jump to until a touch calibration has run; the "
        f"channels held at their last command in amber, not shown switching off, "
        f"and the side column's warning that the outputs may still hold it (N7.U16) "
        f"({language}).",
        _grab_checked(window, f"experimenter_{language}_demo_controls_worn_link_lost"),
    )

    dialog = launcher.session_dialog()
    # The configured folder resolves to an absolute path that differs between machines.
    dialog.data_folder.setText(SAMPLE_DATA_FOLDER)
    yield Shot(
        f"experimenter_{language}_launcher_session",
        f"The session dialog as it opens: the data folder filled in from config; the session "
        f"number, both languages and the pattern folder unchosen, with no default; Start, "
        f"always pressable, checks first (LOG N7.F17e) ({language}).",
        _grab_dialog(dialog),
    )
    dialog.participant.setText(SAMPLE_PARTICIPANT)
    dialog.experimenter.setText(SAMPLE_INITIALS)
    dialog.pattern_folder.setText(SAMPLE_PATTERN_FOLDER)
    for combo, value in (
        (dialog.session_number, SAMPLE_SESSION_NUMBER),
        (dialog.participant_language, SAMPLE_LANGUAGES[0]),
        (dialog.experimenter_language, SAMPLE_LANGUAGES[-1]),
        (dialog.garment, SAMPLE_GARMENT),
    ):
        combo.setCurrentIndex(combo.findData(value))
    dialog.check()
    yield Shot(
        f"experimenter_{language}_launcher_session_checked",
        f"The session dialog after Check: a preflight warning listed in amber, and Start "
        f"reading \"Start despite the warnings\" now they have been shown ({language}).",
        _grab_dialog(dialog),
    )
    yield Shot(
        f"experimenter_{language}_launcher_resume",
        f"The resume question (SPEC.md 15): what was completed and how long ago "
        f"sensitisation began. Resume, or an explicit new session; closing it starts nothing "
        f"({language}).",
        _grab_dialog(dialog.resume_dialog(offer_wording(
            config.experimenter_text, list(SAMPLE_RESUME_COMPLETED),
            list(SAMPLE_RESUME_BLOCKS), SAMPLE_RESUME_AGO_MIN,
        ))),
    )

    # The unweighed set, whatever filaments.yaml holds today, so weighing the kit does not
    # change the picture of the dialog.
    unweighed = {
        **config.filaments,
        "weighing_date": None,
        "weighing_balance": None,
        "filaments": [{**f, "force_measured_mn": None} for f in config.filaments["filaments"]],
    }
    instruments = InstrumentsDialog(config.experimenter_text, unweighed, lambda *_: None)
    instruments.resize(LAPTOP_WIDTH_PX, LAPTOP_HEIGHT_PX)
    yield Shot(
        f"experimenter_{language}_launcher_instruments",
        f"Instruments and environment (SPEC.md 8.1), at the lab laptop's size: all twenty "
        f"filaments in view at once, in two halves, each with its label, size and nominal "
        f"force, a field for the weighing in grams and the force in mN it will save; the "
        f"weighing date and Save on one line; the optional room temperature and humidity on "
        f"another. No balance field ({language}).",
        instruments.grab(),
    )
    preview = launcher.preview_dialog(SAMPLE_T_ZERO)
    yield Shot(
        f"experimenter_{language}_launcher_preview",
        f"The schedule preview (SPEC.md 7.2): tools/preview_schedule.py's report, read-only "
        f"({language}).",
        preview.grab(),
    )
    # Sample hardware (`_sample_detectors`), the mock, the test double for the sound and every
    # keyboard as the remote: nothing is played, nothing is opened, and Raw Input needs a native
    # window the offscreen platform does not have. On the lab's platform wherever it is drawn,
    # so a missing device is drawn as the lab would see it on every machine.
    hardware = {
        **with_key_source(config.hardware, ANY_KEYBOARD),
        "lab_platform": sys.platform,
        "garment": {**config.hardware["garment"], "driver": "mock"},
        "audio": {**config.hardware["audio"], "backend": "recording"},
    }
    nothing = HardwareCheckDialog(
        config.experimenter_text, hardware,
        detectors=_sample_detectors([SAMPLE_SCREEN], [], False, SAMPLE_OUTPUTS[:1]),
    )
    # At the lab laptop's 1280 x 800 (docs/LOG.md N7.U10): the page opens fitted to the screen,
    # and on a shorter one scrolls with Continue still in view.
    nothing.resize(LAPTOP_WIDTH_PX, HEIGHT_PX)
    yield Shot(
        f"experimenter_{language}_launcher_hardware_check_nothing_found",
        f"The hardware page (LOG N7.F12e1) with nothing of the lab's connected: one screen, so "
        f"the participant's window shares it; the remote, the headphones and the sleeve's port "
        f"missing, each in its own colour and saying what to do -- in the lab the keyboard is "
        f"chosen by hand, never stood in automatically. Each is found when connected "
        f"({language}).",
        nothing.grab(),
    )
    nothing.release()
    check = HardwareCheckDialog(
        config.experimenter_text, hardware,
        detectors=_sample_detectors([SAMPLE_SCREEN, SAMPLE_SCREEN], ["COM3"], True,
                                    SAMPLE_OUTPUTS),
    )
    check.resize(LAPTOP_WIDTH_PX, HEIGHT_PX)
    yield Shot(
        f"experimenter_{language}_launcher_hardware_check",
        f"The hardware page (LOG N7.F4, N7.F12e1), shown before the launcher, at the lab "
        f"laptop's size, with the lab's hardware connected: each choice on hardware.yaml's "
        f"own, found; a count for each remote button; the noise within the participant's own "
        f"range with the cue and the alert; each garment channel on and off. Continue opens "
        f"the launcher ({language}).",
        check.grab(),
    )
    check.toggle_garment()
    check.channel_buttons[SAMPLE_CHANNEL_ON].setChecked(True)
    yield Shot(
        f"experimenter_{language}_launcher_hardware_check_channel_on",
        f"The hardware check with the mock garment connected and channel {SAMPLE_CHANNEL_ON} "
        f"on: each channel button says on or off, and one that is on is filled (LOG N7.F10b; "
        f"{language}).",
        check.grab(),
    )
    check.release()
    yield from _designer_shots(config, language)


def _designer_shots(config: cfg.Config, language: str) -> Iterator[Shot]:
    """The pattern designer (SPEC.md 12.2), launcher entry 3. For S, not a blinded experimenter.

    Each state gets a fresh window so none inherits another's. The example patterns are read
    from `config/patterns/examples/`, so a change to them changes these pictures, as it should.
    """
    def designer() -> DesignerWindow:
        window = DesignerWindow(config.experimenter_text, config.hardware)
        window.resize(LAPTOP_WIDTH_PX, LAPTOP_HEIGHT_PX)
        return window

    states: list[tuple[str, str, DesignerWindow]] = []

    window = designer()
    window.open_file(SAMPLE_DESIGN_PATTERN)
    states.append((
        "grid",
        "An example pattern opened on the Grid tab, at the lab laptop's size: the pattern's "
        "fields in two strips across the top; the grid across the whole width, one compact "
        "row per row interval with its time, one column per channel, on cells filled and no "
        "digits. The timeline below draws two cycles because it loops, the repeat fainter; "
        "the line under it says it loads, beside the garment chosen for Play.",
        window,
    ))

    window = designer()
    window.clear()
    window.name_field.setText(SAMPLE_DESIGN_NAME)
    window.interval_field.setText(f"{SAMPLE_DESIGN_INTERVAL_MS:g}")
    window.ids_field.setText(", ".join(map(str, SAMPLE_DESIGN_IDS)))
    window.apply_channel_ids()
    window.loop_box.setChecked(True)
    window.tabs.setCurrentIndex(1)
    window.set_entries(window.ordered, [(cid, SAMPLE_DESIGN_HOLD_MS) for cid in
                                        SAMPLE_DESIGN_IDS])
    window.delay_field.setText(f"{SAMPLE_DESIGN_INTERVAL_MS:g}")
    window.set_mode(pd.JOIN_HOLD)
    window.convert_ordered()
    states.append((
        "ordered",
        "Ordered channels: five channels with their hold times; all three modes listed, "
        "each with what it does, join-and-hold chosen; the delay beside Convert, converted. "
        "The message says the grid was replaced, and the timeline shows the overlapping "
        "sweep.",
        window,
    ))

    window = designer()
    window.clear()
    window.name_field.setText(SAMPLE_DESIGN_NAME)
    window.interval_field.setText(f"{SAMPLE_TIMED_INTERVAL_MS:g}")
    window.ids_field.setText(", ".join(map(str, SAMPLE_DESIGN_IDS)))
    window.apply_channel_ids()
    window.tabs.setCurrentIndex(2)
    window.set_entries(window.timed, SAMPLE_TIMED)
    window.convert_timed()
    states.append((
        "timed",
        "Timed channels: onset and offset per channel in ms, converted. Played once, so "
        "the timeline draws one cycle.",
        window,
    ))
    window = designer()
    window.clear()
    window.name_field.setText(SAMPLE_DESIGN_NAME)
    window.interval_field.setText(f"{SAMPLE_TIMED_INTERVAL_MS:g}")
    window.ids_field.setText(", ".join(map(str, SAMPLE_DESIGN_IDS)))
    window.apply_channel_ids()
    window.tabs.setCurrentIndex(2)
    window.set_entries(window.timed, SAMPLE_TIMED)
    window.convert_timed()
    window.set_entries(window.timed, SAMPLE_OFF_GRID)
    window.convert_timed()
    states.append((
        "off_grid",
        "A timing off the row grid, refused in red with the reason and never rounded. The "
        "grid converted before it is kept, unchanged, and still previewed.",
        window,
    ))

    window = designer()
    window.clear()
    states.append((
        "new",
        "A new pattern: nothing filled in and nothing assumed. The line in red says why it "
        "does not load yet, and Save, Export and Play are disabled.",
        window,
    ))

    window = designer()
    window.open_file(SAMPLE_DESIGN_PATTERN)
    # Chosen, never connected: the picture opens no serial port.
    window.garment_choice.setCurrentIndex(window.garment_choice.findData(SAMPLE_GARMENT))
    window.show_playback(SAMPLE_PLAYBACK_S, set(SAMPLE_PLAYBACK_ON))
    window.stop_button.setEnabled(True)
    states.append((
        "playing",
        "Playback on the prototype sleeve, chosen beside Play: the cursor in amber on the "
        "timeline and the channels on now named, their labels amber. Set directly rather "
        "than played, because a running pattern would never be photographed at the same "
        "moment twice, and the sleeve is never woken for a picture.",
        window,
    ))

    for name, description, window in states:
        window.resize(LAPTOP_WIDTH_PX, LAPTOP_HEIGHT_PX)
        # Shown before the grab: the tab bar places its corner widget, the playback
        # controls, only once it has been shown. Offscreen, so nothing appears.
        window.show()
        QApplication.processEvents()
        pixmap = window.grab()
        assert pixmap.height() == LAPTOP_HEIGHT_PX, (
            f"experimenter_{language}_designer_{name} needs {pixmap.height()} px"
        )
        yield Shot(f"experimenter_{language}_designer_{name}", f"{description} ({language})",
                   pixmap)
        _dispose(window)


def shots(languages: tuple[str, ...] = LANGUAGES) -> Iterator[Shot]:
    """Every catalogued state, in every language."""
    for language in languages:
        # Both roles' text is loaded together, so each language is one config with the other
        # role's language following it -- the experimenter reads the same language here.
        config = cfg.load(language, language)
        yield from _participant_shots(config, language)
        yield from _experimenter_shots(config, language)


# -- the manifest and the comparison -------------------------------------------------------


def read_manifest() -> dict[str, str]:
    if not MANIFEST_PATH.exists():
        raise ManifestError(f"{MANIFEST_PATH} does not exist. Run `make shots-manifest`.")
    loaded = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    return dict(loaded["screens"])


def write_manifest(catalogue: dict[str, str]) -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        "# Every screen state the software can show, with what the image should contain.\n"
        "# SPEC.md 17.4. Generated by `make shots ARGS=--write-manifest`; the descriptions\n"
        "# come from the catalogue in tatp/screenshots.py, so edit them there, not here.\n"
        "#\n"
        "# An entry with no image is a failure, and an image with no entry is a failure. What\n"
        "# is compared against screenshots/reference/ is only what has been approved.\n\n"
        + yaml.safe_dump({"screens": catalogue}, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


def difference_fraction(left: QImage, right: QImage) -> float:
    """Fraction of pixels that differ. 1.0 if the two are not even the same size."""
    if left.size() != right.size() or left.format() != right.format():
        return 1.0
    # Compared as ARGB32 words, which is what QImage.pixel() returns, so the result is the
    # per-pixel count it always was. A Python loop over pixel() took minutes for 64 screens.
    left_px, right_px = (_argb_words(image) for image in (left, right))
    return float(np.count_nonzero(left_px != right_px)) / left_px.size


def _argb_words(image: QImage) -> np.ndarray:
    argb = image.convertToFormat(QImage.Format.Format_ARGB32)
    rows = np.frombuffer(argb.constBits(), np.uint8).reshape(argb.height(), argb.bytesPerLine())
    # Rows can be padded past the last pixel; the padding is not part of the image.
    return rows[:, : argb.width() * 4].copy().view(np.uint32)


@dataclass
class Result:
    written: list[str]
    compared: list[str]
    unarmed: list[str]
    failures: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures


def run(approve: Callable[[str], bool] = lambda name: False) -> Result:
    """Write every screen, compare the armed ones, and report.

    `approve` decides per screen whether this run's image becomes the approved reference --
    `--approve-all` passes a function that says yes to everything, and naming screens on the
    command line approves exactly those.
    """
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    # current/ and diff/ are this run's output only. Without clearing them, a retired screen's
    # last image stays behind looking current -- which is how `screen_adjust` survived its
    # removal and was reviewed as if it were live. Approved references are never touched here.
    for folder in (CURRENT_DIR, DIFF_DIR):
        for stale in folder.glob("*.png"):
            stale.unlink()

    manifest = read_manifest()
    result = Result([], [], [], [])

    for shot in shots():
        current = CURRENT_DIR / shot.filename
        shot.pixmap.save(str(current))
        result.written.append(shot.name)

        if shot.name not in manifest:
            result.failures.append(
                f"{shot.name}: rendered but not in the manifest. Add it with --write-manifest."
            )
            continue

        reference = REFERENCE_DIR / shot.filename
        if approve(shot.name):
            shot.pixmap.save(str(reference))
        if not reference.exists():
            result.unarmed.append(shot.name)
            continue

        fraction = difference_fraction(QImage(str(reference)), shot.pixmap.toImage())
        result.compared.append(shot.name)
        if fraction > TOLERANCE_FRACTION:
            shot.pixmap.save(str(DIFF_DIR / shot.filename))
            result.failures.append(
                f"{shot.name}: {fraction:.2%} of pixels differ from the approved reference "
                f"(tolerance {TOLERANCE_FRACTION:.2%}). Compare "
                f"{reference.relative_to(cfg.REPO_ROOT)} against "
                f"{current.relative_to(cfg.REPO_ROOT)}, then re-approve if the change is meant."
            )

    rendered = set(result.written)
    for name in sorted(set(manifest) - rendered):
        result.failures.append(f"{name}: in the manifest but no image was produced.")
    return result


def freeze() -> list[str]:
    """SPEC.md 17.4's freeze: every entry approved and every diff clean.

    Returns the screens that block it, empty when the build is freezable.
    """
    result = run()
    blocking = list(result.failures)
    blocking += [f"{name}: has no approved reference." for name in result.unarmed]
    return blocking


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screen states as PNGs. SPEC.md 17.4.")
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="rewrite manifest.yaml from the catalogue, then exit",
    )
    parser.add_argument(
        "--approve-all", action="store_true", help="approve every screen (a wording pass)"
    )
    parser.add_argument(
        "--approve", nargs="*", default=[], metavar="NAME", help="approve these screens"
    )
    # Arming happens a role at a time, because reviewing happens a role at a time: the
    # participant screens can be frozen while the experimenter's are still being read.
    parser.add_argument(
        "--approve-matching",
        default=None,
        metavar="GLOB",
        help="approve every screen whose name matches, e.g. 'participant_*'",
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="require every entry approved and every diff clean (SPEC.md 17.4)",
    )
    args = parser.parse_args(argv)

    application(cfg.load(LANGUAGES[0], LANGUAGES[0]).hardware)

    if args.write_manifest:
        catalogue = {shot.name: shot.description for shot in shots()}
        write_manifest(catalogue)
        print(f"{len(catalogue)} screens written to {MANIFEST_PATH.relative_to(cfg.REPO_ROOT)}")
        return 0

    if args.freeze:
        blocking = freeze()
        for line in blocking:
            print(line)
        print(f"{len(blocking)} screens block a freeze.")
        return 1 if blocking else 0

    named = set(args.approve)
    pattern = args.approve_matching

    def approve(name: str) -> bool:
        if args.approve_all:
            return True
        return name in named or (pattern is not None and fnmatch(name, pattern))

    result = run(approve=approve)
    for failure in result.failures:
        print(failure)
    print(
        f"{len(result.written)} screens written, {len(result.compared)} compared, "
        f"{len(result.unarmed)} not yet approved, {len(result.failures)} failures."
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
