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
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

# Presentation only, not study parameters (SPEC.md 4.2). The banners are red and large because
# SPEC.md 12.4 requires them to be unmissable; the reference screenshots pin the rest.
BANNER_STYLE = (
    "background-color: #b00020; color: #ffffff; padding: 14px; font-weight: bold;"
)
BANNER_POINT_SIZE = 18
HEADING_POINT_SIZE = 22
INSTRUCTION_POINT_SIZE = 16
SECONDS_PER_MINUTE = 60


def _label(point_size: int, wrap: bool = False) -> QLabel:
    made = QLabel()
    made.setWordWrap(wrap)
    font = made.font()
    font.setPointSize(point_size)
    made.setFont(font)
    return made


def _elapsed_text(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // SECONDS_PER_MINUTE:02d}:{whole % SECONDS_PER_MINUTE:02d}"


class ExperimenterWindow(QWidget):
    """The lab-side screen. Never shows a rating and never shows the condition (SPEC.md 16)."""

    def __init__(
        self,
        experimenter_text: dict,
        read_view: Callable[[], dict],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.text = experimenter_text
        self.read_view = read_view

        self.placeholder_banner = _label(BANNER_POINT_SIZE, wrap=True)
        self.placeholder_banner.setStyleSheet(BANNER_STYLE)
        self.reduced_capability_banner = _label(BANNER_POINT_SIZE, wrap=True)
        self.reduced_capability_banner.setStyleSheet(BANNER_STYLE)

        self.identity = _label(INSTRUCTION_POINT_SIZE)
        self.phase = _label(HEADING_POINT_SIZE)
        self.elapsed = _label(INSTRUCTION_POINT_SIZE)
        self.garment = _label(INSTRUCTION_POINT_SIZE)
        self.open_items = _label(INSTRUCTION_POINT_SIZE, wrap=True)
        self.instruction = _label(HEADING_POINT_SIZE, wrap=True)
        self.technique = _label(INSTRUCTION_POINT_SIZE, wrap=True)
        self.status = _label(INSTRUCTION_POINT_SIZE)

        self.technique.setText(self.text["instructions"]["monofilament"])

        layout = QVBoxLayout(self)
        for widget in (
            self.placeholder_banner,
            self.reduced_capability_banner,
            self.identity,
            self.phase,
            self.elapsed,
            self.garment,
            self.open_items,
            self.instruction,
            self.technique,
            self.status,
        ):
            layout.addWidget(widget)
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
            "   ".join(
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
        connected = "connected" if view["garment_connected"] else "disconnected"
        self.garment.setText(text["status"][connected])

        items = view["unresolved_open_items"]
        self.open_items.setText(
            text["warnings"]["open_items"].format(value="; ".join(items)) if items else ""
        )
        self.open_items.setVisible(bool(items))
