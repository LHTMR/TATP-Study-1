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

Not every state SPEC.md 17.4 lists exists yet -- the zone diagram, the hardware panel and the
abort and error dialogs are Milestone 5. The catalogue holds what the software can actually
show, so a manifest entry always corresponds to a real screen.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatch

import numpy as np
import yaml
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QWidget

from tatp import config as cfg
from tatp.clock import Clock
from tatp.responder import Action, Responder
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

        window.emphasise_choice("left")
        yield Shot(
            f"{name}_emphasis_left",
            "The left button's outline thickened while its stimulus plays (UI_PRINCIPLES.md "
            "5.11). It must read as `this is the one you are feeling`, never as a suggestion.",
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


def _experimenter_shots(config: cfg.Config, language: str) -> Iterator[Shot]:
    view = _experimenter_view()
    window = ExperimenterWindow(config.experimenter_text, lambda: view)

    states = {
        "plain": (
            "No banners, no open items -- what a correctly configured session shows.",
            {},
        ),
        "placeholder_banner": (
            "The unapproved-wording banner (SPEC.md 12.4), red and unmissable.",
            {"placeholder_text": True},
        ),
        "reduced_capability_banner": (
            "The reduced-capability banner naming the driver in use (SPEC.md 12.4).",
            {"reduced_capability_device": True},
        ),
        "open_items": (
            "Unresolved open items listed for the experimenter (SPEC.md 20).",
            {"unresolved_open_items": ["L3 audio levels", "5 patterns"]},
        ),
        "disconnected": (
            "The garment reported disconnected.",
            {"garment_connected": False},
        ),
    }
    for name, (description, overrides) in states.items():
        view.clear()
        view.update(_experimenter_view(**overrides))
        window.refresh()
        yield Shot(
            f"experimenter_{language}_{name}",
            f"{description} ({language})",
            _grab(window),
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
