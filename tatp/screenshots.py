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
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch

import numpy as np
import yaml
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QWidget

from tatp import config as cfg
from tatp import touchcal_maths as maths
from tatp.clock import Clock
from tatp.instruments import InstrumentsDialog
from tatp.launcher import WARN, LauncherWindow
from tatp.pinprick import F40Fit, LongResult
from tatp.responder import Action, Responder
from tatp.touchcal import FitReady
from tatp.ui.application import application
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow

SCREENSHOT_DIR = cfg.REPO_ROOT / "screenshots"
MANIFEST_PATH = SCREENSHOT_DIR / "manifest.yaml"
REFERENCE_DIR = SCREENSHOT_DIR / "reference"
CURRENT_DIR = SCREENSHOT_DIR / "current"
DIFF_DIR = SCREENSHOT_DIR / "diff"

# How the windows are grabbed. Presentation, not study parameters (SPEC.md 4.2): the size is
# the lab PC's, and the tolerance is what separates a font rasterising a shade differently on
# another machine from a screen that actually changed.
WIDTH_PX = 1280
HEIGHT_PX = 800
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
SAMPLE_PATH = "lateral"
SAMPLE_DISTANCES = ("42", "37,5")
SAMPLE_BLOCK = {"kind": "block", "label_key": "block", "block_index": 3, "block_type": "touch"}
SAMPLE_DUE_IN_S = 245.0
SAMPLE_DUE_NOW_S = -5.0
SAMPLE_OVERDUE_S = -420.0
SAMPLE_HARDWARE = {"connected": True, "faults": [], "channel_pressure_kpa": None}
SAMPLE_PRESSURES_KPA = {1: 38.5, 2: 41.0, 3: 40.0, 4: 39.5, 5: 42.0}
SAMPLE_FAULT = "channel 4: valve did not report"
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
SAMPLE_RESUME_AGO = "1 h 12 min"
SAMPLE_T_ZERO = datetime(2026, 9, 24, 9, 30)


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
        "garment_driver": "MockGarment",
        "placeholder_text": False,
        "reduced_capability_device": False,
        "unresolved_open_items": [],
        "fit_preview_enabled": False,
        "next_event": None,
        "interruption": None,
        "hardware": {"connected": True, "faults": [], "channel_pressure_kpa": None},
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

    for key in sorted(k for k, v in text["audio_setup"].items() if isinstance(v, str)):
        window.show_audio_setup(key)
        yield Shot(
            f"participant_{language}_audio_setup_{key}",
            f"The masking check's `audio_setup.{key}` (SPEC.md 10.7), a text screen: its "
            f"wording names the buttons itself, so none are drawn, {language}.",
            _grab(window),
        )

    window.show_preference()
    yield Shot(
        f"participant_{language}_preference",
        f"The preference selection (SPEC.md 9 step 6): the opening line, both large buttons "
        f"drawn with their labels, and the confirm sentence, {language}.",
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
        "The visual warning cue: one filled disc, centred, no wording.",
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

    yield from _vas_variant_shots(window, language)


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
        # already happening (`still_audible`, `evenness`) never reaches that state.
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
        state.press(action)
        yield Shot(
            f"participant_{language}_vas_{VARIANT_SCALE}_first_press_{side}",
            f"The marker where a first {side} press puts it -- SPEC.md 10.2's rule that the "
            f"marker appears on the side that was pressed.",
            _grab(window),
        )

    for percent in MARKER_POSITIONS:
        window.show_vas(VARIANT_SCALE)
        state.cue()
        state.press(Action.INCREASE)
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


def _experimenter_states(text: dict) -> dict:
    """Every state of the window: (description, view overrides, what the protocol pushes in).

    What the protocol pushes -- the instruction, the status, the target, the awaited actions --
    is a function of the window, applied after a fresh window is built for each state so no
    state inherits another's.
    """
    instructions = text["instructions"]
    filament = SAMPLE_F40["filament"]
    apply_filament = instructions["apply_filament"].format(
        filament=filament, force_mn=f"{SAMPLE_F40['filament_mn']:g}", site=SAMPLE_SITE,
        region=text["terms"]["regions"]["primary"],
    )
    apply_brush = instructions["apply_brush"].format(
        site=SAMPLE_SITE, region=text["terms"]["regions"]["secondary"]
    )
    path = text["terms"]["mapping_paths"][SAMPLE_PATH]
    upcoming = {**SAMPLE_BLOCK, "due_in_s": SAMPLE_DUE_IN_S, "overdue": False}

    def pinprick(window):
        window.set_instruction(apply_filament)
        window.set_target("primary", SAMPLE_SITE, filament=True)
        window.set_status(instructions["await_participant"])

    def ready(window):
        window.set_instruction(instructions["ready"])

    return {
        "plain": (
            "No banners, no open items, nothing scheduled -- a correctly configured session "
            "at setup. Controls along the bottom, Resume, Rebalance and the fit choice "
            "disabled; the zone diagram with no zone marked; the hardware panel connected "
            "with no pressures.",
            {}, None,
        ),
        "placeholder_banner": (
            "The unapproved-wording banner (SPEC.md 12.4), red and unmissable.",
            {"placeholder_text": True}, None,
        ),
        "reduced_capability_banner": (
            "The reduced-capability banner naming the driver in use (SPEC.md 12.4).",
            {"reduced_capability_device": True}, None,
        ),
        "all_banners": (
            "All three banners at once: nothing below the reserved region has moved "
            "(UI_PRINCIPLES.md 3.3). The fit-preview banner is amber like the "
            "reduced-capability one (SPEC.md 11.1).",
            {"placeholder_text": True, "reduced_capability_device": True,
             "fit_preview_enabled": True}, None,
        ),
        "open_items": (
            "Unresolved open items listed for the experimenter (SPEC.md 20).",
            {"unresolved_open_items": ["L3 audio levels", "5 patterns"]}, None,
        ),
        "disconnected": (
            "The garment reported disconnected: red and bold in the hardware panel, Connect "
            "enabled and Disconnect not.",
            {"hardware": {**SAMPLE_HARDWARE, "connected": False}}, None,
        ),
        "pinprick_primary": (
            "A pinprick application: the filament by its gram label, the primary zone "
            "outlined on the diagram with its site beside it, the technique text below, and "
            "the response pending -- never its value.",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S}, pinprick,
        ),
        "brush_secondary": (
            "A brush stroke in the secondary zone: the dashed ellipse outlined.",
            {"phase": "post_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                window.set_instruction(apply_brush),
                window.set_target("secondary", SAMPLE_SITE),
            ),
        ),
        "mapping": (
            "A mapping path: the secondary zone outlined without a site, the technique text "
            "shown because a filament is used, and Mapping distances enabled now that a "
            "phase has been mapped.",
            {"phase": "post_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: (
                window.set_instruction(instructions["mapping_path"].format(path=path)),
                window.set_target("secondary", filament=True),
                window.set_mapping_phases(["post_sensitisation"]),
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
            lambda window: window.set_instruction(instructions["touch_start"]),
        ),
        "intervention_fault": (
            "A garment fault during the intervention: shown in red, counted, and without the "
            "channel, which could say which pattern is running (SPEC.md 16).",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "hardware": {**SAMPLE_HARDWARE, "faults": [SAMPLE_FAULT]}},
            lambda window: window.set_instruction(instructions["touch_start"]),
        ),
        "countdown": (
            "Waiting for the next block: 'Next: block 3 (touch) in 04:05', grey.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S, "next_event": upcoming},
            ready,
        ),
        "block_due": (
            "The block is due: amber and bold in the same place as the countdown.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "next_event": {**SAMPLE_BLOCK, "due_in_s": SAMPLE_DUE_NOW_S, "overdue": False}},
            ready,
        ),
        "block_overdue": (
            "The block is overdue: red and bold, OVERDUE in capitals.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "next_event": {**SAMPLE_BLOCK, "due_in_s": SAMPLE_OVERDUE_S, "overdue": True}},
            ready,
        ),
        "rekindle_due": (
            "The rekindle is due: a timed event that is not a block, named by its phase.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "next_event": {"kind": "rekindle", "label_key": "rekindle", "block_index": None,
                            "block_type": None, "due_in_s": SAMPLE_DUE_NOW_S,
                            "overdue": False}},
            ready,
        ),
        "interrupted_emergency_stop": (
            "The participant pressed the stop: the red line under the phase, Resume and "
            "Abort the only controls enabled, and nothing else moved.",
            {"phase": "intervention", "elapsed_s": SAMPLE_ELAPSED_S,
             "interruption": "emergency_stop"},
            pinprick,
        ),
        "interrupted_pause": (
            "The experimenter's pause: the same line in amber, Resume enabled.",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S,
             "interruption": "pause"},
            ready,
        ),
        "hardware_pressures": (
            "Touch calibration: the hardware panel with every channel's pressure and one "
            "fault, in red.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S,
             "hardware": {**SAMPLE_HARDWARE, "channel_pressure_kpa": SAMPLE_PRESSURES_KPA,
                          "faults": [SAMPLE_FAULT]}},
            lambda window: window.set_instruction(
                instructions["touchcal_match"].format(channel=SAMPLE_CHANNEL)
            ),
        ),
        "long_instruction": (
            "The longest instruction the session gives, set down the type scale so it fits "
            "its region: nothing below it has moved, and the controls are where they always "
            "are.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S},
            lambda window: window.set_instruction(
                instructions["touchcal_stage1_exhausted"].format(
                    value=text["terms"]["stage1"]["flat"]
                )
            ),
        ),
        "awaiting_rebalance": (
            "The evenness question answered 'uneven': Rebalance and Start block both "
            "enabled, because the procedure waits on either.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S,
             "hardware": {**SAMPLE_HARDWARE, "channel_pressure_kpa": SAMPLE_PRESSURES_KPA}},
            lambda window: (
                window.set_instruction(instructions["touchcal_uneven"]),
                window.set_actions_enabled(rebalance=True),
            ),
        ),
        "fit_preview_f40": (
            "The main window while the F40 fit preview (SPEC.md 11.1) is open, only with "
            "fit_preview.enabled: the banner saying what it costs, Accept and Re-run enabled, "
            "and no rating anywhere on this window -- they are in the preview window.",
            {"phase": "pre_sensitisation", "elapsed_s": SAMPLE_ELAPSED_S,
             "fit_preview_enabled": True},
            lambda window: window.show_fit_preview(_sample_f40_fit()),
        ),
        "fit_preview_touch": (
            "The main window while the touch-calibration fit preview is open: its instruction "
            "at a smaller size because it is long, Accept and Re-run enabled.",
            {"phase": "touch_calibration", "elapsed_s": SAMPLE_ELAPSED_S,
             "fit_preview_enabled": True},
            lambda window: (
                window.set_instruction(instructions["touchcal_fit_review"]),
                window.show_fit_preview(_sample_touch_fit()),
            ),
        ),
    }


def _experimenter_shots(config: cfg.Config, language: str) -> Iterator[Shot]:
    text = config.experimenter_text
    for name, (description, overrides, push) in _experimenter_states(text).items():
        view = _experimenter_view(**overrides)
        window = ExperimenterWindow(text, lambda view=view: view)
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
    window.set_mapping_phases(["post_sensitisation", "post_intervention"])
    for field, typed in zip(window.distances.fields, SAMPLE_DISTANCES, strict=False):
        field.setText(typed)
    dialogs["distances_dialog"] = (
        "The mapping distances window (SPEC.md 8.4): the latest mapped phase selected, one "
        "field per path in path order, two typed with either decimal mark. Non-modal: the "
        "session runs on behind it.",
        window.distances,
    )
    for name, (description, dialog) in dialogs.items():
        yield Shot(f"experimenter_{language}_{name}", f"{description} ({language})",
                   _grab_dialog(dialog))

    yield from _launcher_shots(config, language)


def _grab_dialog(dialog: QWidget) -> QPixmap:
    dialog.resize(DIALOG_WIDTH_PX, dialog.sizeHint().height())
    return dialog.grab()


def _launcher_shots(config: cfg.Config, language: str) -> Iterator[Shot]:
    """The launcher and its dialogs (SPEC.md 4.1). Nothing is started and nothing is written."""
    def no_session(config, args):
        raise AssertionError("the screenshot run never starts a session")

    def findings(config, args):
        return [(WARN, "warnings.experimenter_changed", "")]

    launcher = LauncherWindow(config, preflight=findings, build=no_session)
    yield Shot(
        f"experimenter_{language}_launcher",
        f"The launcher's four entries (SPEC.md 4.1), Design a pattern disabled with its reason "
        f"({language}).",
        _grab_dialog(launcher),
    )

    dialog = launcher.session_dialog()
    # The configured folder resolves to an absolute path that differs between machines.
    dialog.data_folder.setText(SAMPLE_DATA_FOLDER)
    yield Shot(
        f"experimenter_{language}_launcher_session",
        f"The session dialog as it opens: the data folder filled in from config, the pattern "
        f"folder empty with no default, Start disabled until a check passes ({language}).",
        _grab_dialog(dialog),
    )
    dialog.participant.setText(SAMPLE_PARTICIPANT)
    dialog.experimenter.setText(SAMPLE_INITIALS)
    dialog.pattern_folder.setText(SAMPLE_PATTERN_FOLDER)
    dialog.check()
    yield Shot(
        f"experimenter_{language}_launcher_session_checked",
        f"The session dialog after Check: a preflight warning listed in amber, Start "
        f"enabled because nothing refuses ({language}).",
        _grab_dialog(dialog),
    )
    yield Shot(
        f"experimenter_{language}_launcher_resume",
        f"The resume question (SPEC.md 15), naming how long ago the session began "
        f"({language}).",
        _grab_dialog(dialog.resume_dialog(SAMPLE_RESUME_AGO)),
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
    instruments.resize(DIALOG_WIDTH_PX, HEIGHT_PX)
    yield Shot(
        f"experimenter_{language}_launcher_instruments",
        f"Instruments and environment (SPEC.md 8.1): every filament with its label, size, "
        f"nominal force and a measured-force field; the weighing date and balance; the "
        f"optional room temperature and humidity ({language}).",
        instruments.grab(),
    )
    preview = launcher.preview_dialog(SAMPLE_T_ZERO)
    yield Shot(
        f"experimenter_{language}_launcher_preview",
        f"The schedule preview (SPEC.md 7.2): tools/preview_schedule.py's report, read-only "
        f"({language}).",
        preview.grab(),
    )


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
