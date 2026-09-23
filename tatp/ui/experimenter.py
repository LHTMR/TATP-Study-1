"""The experimenter window. SPEC.md 11, 12.4, 16.

**It reads `Session.experimenter_view()` and nothing else about the session.** The constructor
takes the reader as a callable rather than the session, so that "and nothing else" is
structural: this window holds no reference to a `Session` and therefore has no way to reach
`Session.condition` or a participant's rating, whatever a later edit does to it.

Per-trial prompts -- which filament, at which site -- are not session state and are pushed in by
the protocol module through `set_instruction()` and `set_status()`.

It carries no wording of its own: every string comes from
`config/text/experimenter_{sv,en}.yaml` (SPEC.md 10.4).

Milestone 1 builds the parts the pinprick slice needs. The zone diagram, the per-channel
hardware panel with its disconnect/reconnect button, the countdown to the next scheduled event
and the controls of SPEC.md 11 belong to Milestone 5.

**The experimenter's actions are signals, and they exist before the buttons do.** Every action
SPEC.md 11 gives the experimenter is declared below, so the protocols connect to one name for
each and the virtual experimenter of SPEC.md 17.5 drives the same path a real one will.
Milestone 5 draws the buttons that emit them. A protocol never reads a widget; it connects to a
signal.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tatp.units import S_PER_MIN

# Presentation only, not study parameters (SPEC.md 4.2). The reference screenshots pin these.
#
# Dark, because this screen shares a dim room with a participant looking at a near-black one,
# and a full-brightness page is then the brightest object in their field of view
# (UI_PRINCIPLES.md 3.5).
BACKGROUND = "#141414"
FOREGROUND = "#ebebeb"
SECONDARY = "#9a9a9a"
# The two banners mean different things and demand different responses, so they do not look
# alike (UI_PRINCIPLES.md 3.4): red is "do not run a participant at all", amber is "this
# session runs but its touch data will not be valid".
PLACEHOLDER_COLOUR = "#b00020"
REDUCED_CAPABILITY_COLOUR = "#8a5a00"
WARNING_COLOUR = "#e0a12a"
DISCONNECTED_COLOUR = "#e0453f"

# One scale, four steps, each meaning a level rather than a screen's local preference
# (UI_PRINCIPLES.md 4.3).
SIZE_SMALL = 15
SIZE_BODY = 18
SIZE_LARGE = 24
SIZE_HEADLINE = 32

IDENTITY_SEPARATOR = "  ·  "
MARGIN_PX = 24
GROUP_GAP_PX = 22
# The banner region is always this tall, occupied or not, so that nothing below it moves when a
# banner appears -- a layout that reflows at the moment something has gone wrong is a layout
# that gets misread (UI_PRINCIPLES.md 3.3). `tests/test_ui.py` asserts both banners fit, so a
# wording change that would overflow fails the suite rather than silently clipping a warning.
# Sized with headroom, and deliberately not trimmed to what the current wording needs at the
# current window width: a narrower window wraps a banner onto more lines, so a snug value would
# clip the moment the lab used a smaller window than the one this was measured in.
BANNER_AREA_PX = 240
BANNER_PADDING_PX = 12


def _label(point_size: int, wrap: bool = False, colour: str = FOREGROUND) -> QLabel:
    made = QLabel()
    made.setWordWrap(wrap)
    font = made.font()
    font.setPointSize(point_size)
    made.setFont(font)
    made.setStyleSheet(f"color: {colour};")
    return made


def _banner_style(colour: str) -> str:
    return (
        f"background-color: {colour}; color: #ffffff; "
        f"padding: {BANNER_PADDING_PX}px; font-weight: bold;"
    )


def _elapsed_text(seconds: float) -> str:
    minutes, remainder = divmod(int(seconds), int(S_PER_MIN))
    return f"{minutes:02d}:{remainder:02d}"


class ExperimenterWindow(QWidget):
    """The lab-side screen. Never shows a rating and never shows the condition (SPEC.md 16)."""

    # -- the experimenter's actions, SPEC.md 11 -----------------------------------------
    # "Start block", and every other point where the software waits for the experimenter to say
    # go: the next phase, the next path, "earplugs fitted". The software times; the
    # experimenter launches (SPEC.md 7.4).
    proceed_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    # Discard and repeat the last trial (SPEC.md 11). There is deliberately no skip.
    discard_requested = Signal()
    abort_requested = Signal(str)  # the reason, which is written to the session file
    note_entered = Signal(str)
    # The filament actually applied, when the experimenter substitutes a lower one for the one
    # asked for (SPEC.md 8.2). Carries its gram label.
    substitution_entered = Signal(str)
    # The four mapping distances for one time point (SPEC.md 8.4): the phase, then a tuple of
    # millimetres with None for any not yet measured. Entered whenever convenient.
    distances_entered = Signal(str, object)
    # The fit preview's choice (SPEC.md 11.1). A re-run carries the experimenter's reason.
    fit_accepted = Signal()
    fit_rerun_requested = Signal(str)
    rebalance_requested = Signal()
    garment_connect_requested = Signal()
    garment_disconnect_requested = Signal()

    def __init__(
        self,
        experimenter_text: dict,
        read_view: Callable[[], dict],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.text = experimenter_text
        self.read_view = read_view

        self.setStyleSheet(f"background-color: {BACKGROUND};")

        self.placeholder_banner = _label(SIZE_BODY, wrap=True)
        self.placeholder_banner.setStyleSheet(_banner_style(PLACEHOLDER_COLOUR))
        self.reduced_capability_banner = _label(SIZE_BODY, wrap=True)
        self.reduced_capability_banner.setStyleSheet(
            _banner_style(REDUCED_CAPABILITY_COLOUR)
        )

        # Who and where, in the smallest size on the screen: it is looked up once at the start
        # of a session and never needed at a glance again (UI_PRINCIPLES.md 5.2).
        self.identity = _label(SIZE_SMALL, colour=SECONDARY)
        self.phase = _label(SIZE_LARGE)
        self.elapsed = _label(SIZE_LARGE, colour=SECONDARY)
        self.garment = _label(SIZE_BODY, colour=SECONDARY)
        self.open_items = _label(SIZE_BODY, wrap=True, colour=WARNING_COLOUR)
        # What to do now is the largest thing on the screen, because it is the one thing that
        # has to be readable from where the experimenter is standing (UI_PRINCIPLES.md 3.1).
        self.instruction = _label(SIZE_HEADLINE, wrap=True)
        self.technique = _label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        self.status = _label(SIZE_BODY, colour=SECONDARY)

        self.technique.setText(self.text["instructions"]["monofilament"])

        banner_area = QWidget()
        banner_area.setFixedHeight(BANNER_AREA_PX)
        banners = QVBoxLayout(banner_area)
        banners.setContentsMargins(0, 0, 0, 0)
        banners.addWidget(self.placeholder_banner)
        banners.addWidget(self.reduced_capability_banner)
        banners.addStretch(1)

        # Read top to bottom: who and where, then phase and clock, then what to do now, then
        # anything wrong. The gaps are what carry that order -- an evenly spaced list of labels
        # has no order at all (UI_PRINCIPLES.md 5.2).
        status_row = QHBoxLayout()
        status_row.addWidget(self.phase)
        status_row.addStretch(1)
        status_row.addWidget(self.elapsed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(banner_area)
        layout.addWidget(self.identity)
        layout.addLayout(status_row)
        layout.addWidget(self.garment)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addWidget(self.instruction)
        layout.addWidget(self.technique)
        layout.addWidget(self.status)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addWidget(self.open_items)
        layout.addStretch(1)
        layout.setAlignment(Qt.AlignTop)
        self.refresh()

    # -- pushed in by the protocol ------------------------------------------------------

    def set_instruction(self, text: str) -> None:
        """What to do now (SPEC.md 11). Formatted by the caller from the experimenter text."""
        self.instruction.setText(text)

    def set_status(self, text: str) -> None:
        """Whether the response has been received (SPEC.md 11) -- never what it was."""
        self.status.setText(text)

    # -- read from the session ----------------------------------------------------------

    def refresh(self) -> None:
        """Redraw from `Session.experimenter_view()`. The only way session state gets here."""
        view = self.read_view()
        text = self.text

        # SPEC.md 12.4: persistent and unmissable while they apply, absent when they do not.
        placeholder = bool(view["placeholder_text"])
        self.placeholder_banner.setText(text["banners"]["placeholder_text"])
        self.placeholder_banner.setVisible(placeholder)
        reduced = bool(view["reduced_capability_device"])
        self.reduced_capability_banner.setText(
            text["banners"]["reduced_capability"].format(value=view["garment_driver"])
        )
        self.reduced_capability_banner.setVisible(reduced)

        session_text = text["session"]
        limb = text["terms"]["limbs"][view["limb"]]
        self.identity.setText(
            IDENTITY_SEPARATOR.join(
                (
                    session_text["participant"].format(value=view["participant_code"]),
                    session_text["session_number"].format(value=view["session_number"]),
                    session_text["limb"].format(value=limb),
                    session_text["experimenter"].format(
                        value=view["experimenter_initials"]
                    ),
                )
            )
        )
        self.phase.setText(text["phases"][view["phase"]])
        self.elapsed.setText(
            text["status"]["elapsed"].format(time=_elapsed_text(view["elapsed_s"]))
        )
        # Connected is the quiet, expected state; disconnected is loud. A hazard state that is
        # typeset exactly like a working one is indistinguishable at a glance, which is the
        # only way this line is ever read (UI_PRINCIPLES.md 3.2).
        connected = bool(view["garment_connected"])
        self.garment.setText(text["status"]["connected" if connected else "disconnected"])
        self.garment.setStyleSheet(
            f"color: {SECONDARY};"
            if connected
            else f"color: {DISCONNECTED_COLOUR}; font-weight: bold;"
        )

        items = view["unresolved_open_items"]
        self.open_items.setText(
            text["warnings"]["open_items"].format(value="; ".join(items)) if items else ""
        )
        self.open_items.setVisible(bool(items))
