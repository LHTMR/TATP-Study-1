"""The experimenter window. SPEC.md 7.4, 11, 11.1, 12.4, 13, 16.

**It reads `Session.experimenter_view()` and nothing else about the session.** The constructor
takes the reader as a callable rather than the session, so that "and nothing else" is
structural: this window holds no reference to a `Session` and therefore has no way to reach
`Session.condition` or a participant's rating, whatever a later edit does to it. The one route
by which a rating reaches it is `show_fit_preview`, which refuses unless the view says the
preview is enabled (SPEC.md 11.1).

Per-trial prompts -- which filament, at which site -- are not session state and are pushed in by
the protocol module through `set_instruction()`, `set_status()` and `set_target()`. What the
running procedure is waiting for is pushed in through `set_actions_enabled()`, and which time
points have a mapping through `set_mapping_phases()`.

It carries no wording of its own: every string comes from
`config/text/experimenter_{sv,en}.yaml` (SPEC.md 10.4).

**The experimenter's actions are signals.** Every action SPEC.md 11 gives the experimenter is a
signal below, and every signal has a control that emits it. A protocol never reads a widget; it
connects to a signal, so the virtual experimenter of SPEC.md 17.5 drives the same path a real
one does.

**The layout is read in a fixed order** (UI_PRINCIPLES.md 5.2): the reserved banner region,
who and where, the phase with the countdown and the clock, any interruption, then what to do
now -- the largest thing on the screen -- beside where to do it and the garment, and the
controls along the bottom. Every region above the controls has a fixed height, so nothing moves
when a warning appears or an instruction is long (UI_PRINCIPLES.md 3.3). A long instruction
steps down the type scale to fit its region rather than growing it.

**The fit preview is a window of its own** (SPEC.md 11.1): the one named screen where ratings
reach the experimenter (UI_PRINCIPLES.md 2.5), opened at the end of an estimation run and
closed after the choice. Its Accept and Re-run are the main window's, so either can be used.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence

from PySide6.QtCore import QRegularExpression, Qt, QTimer, Signal, SignalInstance
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tatp import touchcal_maths as maths
from tatp.ui.widgets import (
    DISCONNECTED_COLOUR,
    GROUP_GAP_PX,
    ITEM_GAP_PX,
    PLACEHOLDER_COLOUR,
    REDUCED_CAPABILITY_COLOUR,
    SECONDARY,
    SIZE_BODY,
    SIZE_HEADLINE,
    SIZE_LARGE,
    SIZE_SMALL,
    WARNING_COLOUR,
    FitPlot,
    MessageDialog,
    ReasonDialog,
    ZoneDiagram,
    banner_style,
    button,
    emphasis_style,
    label,
    line_edit,
    sample_line,
    sized,
    stylesheet,
)
from tatp.units import MS_PER_S, S_PER_MIN

# The window's own margin: narrower than the shared one, because height is what this screen is
# short of.
MARGIN_PX = 20
IDENTITY_SEPARATOR = "  ·  "
LINE_SEPARATOR = "\n"
PRESSURE_SEPARATOR = "   "
# The banner region is always this tall, occupied or not, so that nothing below it moves when a
# banner appears -- a layout that reflows at the moment something has gone wrong is a layout
# that gets misread (UI_PRINCIPLES.md 3.3). `tests/test_ui.py` asserts all three banners fit in
# both languages, so a wording change that would overflow fails the suite rather than silently
# clipping a warning.
BANNER_AREA_PX = 220
# The interruption line is reserved at one line; a test holds both languages' wording to it.
ALERT_LINES = 1
# What to do now has three lines at the headline size. A longer instruction is set at the next
# size down the scale, and so on, until it fits (UI_PRINCIPLES.md 3.3, 4.3).
INSTRUCTION_LINES = 3
INSTRUCTION_SIZES = (SIZE_HEADLINE, SIZE_LARGE, SIZE_BODY, SIZE_SMALL)
# The status line under it: two lines of body text, or the small size if that is not enough.
STATUS_LINES = 2
STATUS_SIZES = (SIZE_BODY, SIZE_SMALL)
OPEN_ITEMS_LINES = 2
SIDE_COLUMN_PX = 300
ZONE_MIN_HEIGHT_PX = 100
SUBSTITUTION_FIELD_PX = 300
DISTANCE_FIELD_PX = 110
CONTROL_COLUMNS = 4
FIT_WINDOW_WIDTH_PX = 720
FIT_PLOT_HEIGHT_PX = 380
# A distance in mm, with either decimal mark: the Swedish keyboard types a comma.
DISTANCE_PATTERN = r"^-?\d+([.,]\d+)?$"
DECIMAL_COMMA = ","
DECIMAL_POINT = "."
NO_BREAK_SPACE = " "
ITEM_NUMBER = re.compile(r"^\[([^\]]+)\]")

EMERGENCY_STOP = "emergency_stop"
PAUSE = "pause"
INTERRUPTIONS = (EMERGENCY_STOP, PAUSE)
BLOCK = "block"
# The phases during which per-channel pressure would differ by condition (SPEC.md 16). The view
# already withholds it then; the window holds the same line, so a view that leaked it would not
# be drawn.
BLINDED_PHASES = ("intervention", "rekindle")


class FitPreviewRefused(Exception):
    """A fit was handed over with the preview off. It carries ratings (SPEC.md 11.1)."""


def _clock_text(seconds: float) -> str:
    minutes, remainder = divmod(int(seconds), int(S_PER_MIN))
    return f"{minutes:02d}:{remainder:02d}"


def _number(value: float | None, spec: str, missing: str) -> str:
    return missing if value is None else format(value, spec)


def _fit_to(widget: QLabel, text: str, sizes: Sequence[int], width: int, height: int) -> None:
    """Set `text` at the first size in `sizes` whose wrapped height fits `height` at `width`."""
    widget.setText(text)
    for size in sizes:
        sized(widget, size)
        if widget.heightForWidth(width) <= height:
            return


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
        refresh_interval_s: float | None = None,
        parent: QWidget | None = None,
    ):
        """`refresh_interval_s` is `screens.experimenter_refresh_interval_s`. None runs no
        timer, which is what the tests and the screenshots want: they call `refresh()`."""
        super().__init__(parent)
        self.text = experimenter_text
        self.read_view = read_view
        self.setStyleSheet(stylesheet())

        # What the running procedure is waiting for, beyond what the view says (SPEC.md 11).
        self._awaiting = {"rebalance": False, "fit_decision": False}
        self._interruption: str | None = None
        self._connected = False
        self._mapping_phases: list[str] = []
        self._instruction_text = ""
        self._status_text = ""
        self._open_items_text = ""
        self._open_items_detail = ""

        self._build_banners()
        self._build_header()
        self._build_centre()
        self._build_controls()
        self._build_entries()
        self.fit_preview = FitPreviewWindow(self)
        self.distances = DistancesDialog(self.text, self.distances_entered, parent=self)

        # Read top to bottom: banners, who and where, phase and clock, any interruption, then
        # what to do now beside where to do it, then the controls. The gaps carry that order --
        # an evenly spaced list of labels has no order at all (UI_PRINCIPLES.md 5.2).
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        # Every gap is one of the shared spacings below, none left to the style's default.
        layout.setSpacing(0)
        layout.addWidget(self.banner_area)
        layout.addWidget(self.identity)
        layout.addLayout(self.phase_row)
        layout.addWidget(self.alert)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(self.centre, 1)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(self.controls)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(self.entries)

        self.refresh()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        if refresh_interval_s is not None:
            self.timer.start(int(round(float(refresh_interval_s) * MS_PER_S)))

    # -- construction --------------------------------------------------------------------

    def _build_banners(self) -> None:
        self.placeholder_banner = label(SIZE_BODY, wrap=True)
        self.placeholder_banner.setStyleSheet(banner_style(PLACEHOLDER_COLOUR))
        self.placeholder_banner.setText(self.text["banners"]["placeholder_text"])
        self.reduced_capability_banner = label(SIZE_BODY, wrap=True)
        self.reduced_capability_banner.setStyleSheet(banner_style(REDUCED_CAPABILITY_COLOUR))
        # SPEC.md 11.1: "in the same register as the reduced-capability banner". Both say the
        # session runs and part of what it records is flagged, which is the same response, so
        # they look the same (UI_PRINCIPLES.md 3.4).
        self.fit_preview_banner = label(SIZE_BODY, wrap=True)
        self.fit_preview_banner.setStyleSheet(banner_style(REDUCED_CAPABILITY_COLOUR))
        self.fit_preview_banner.setText(self.text["banners"]["fit_preview"])

        self.banner_area = QWidget()
        self.banner_area.setFixedHeight(BANNER_AREA_PX)
        banners = QVBoxLayout(self.banner_area)
        banners.setContentsMargins(0, 0, 0, 0)
        banners.addWidget(self.placeholder_banner)
        banners.addWidget(self.reduced_capability_banner)
        banners.addWidget(self.fit_preview_banner)
        banners.addStretch(1)

    def _build_header(self) -> None:
        # Who and where, in the smallest size on the screen: it is looked up once at the start
        # of a session and never needed at a glance again (UI_PRINCIPLES.md 5.2).
        self.identity = label(SIZE_SMALL, colour=SECONDARY)
        self.phase = label(SIZE_LARGE)
        self.countdown = label(SIZE_LARGE, colour=SECONDARY)
        self.elapsed = label(SIZE_LARGE, colour=SECONDARY)
        self.phase_row = QHBoxLayout()
        self.phase_row.addWidget(self.phase)
        self.phase_row.addSpacing(GROUP_GAP_PX)
        self.phase_row.addWidget(self.countdown)
        self.phase_row.addStretch(1)
        self.phase_row.addWidget(self.elapsed)

        # Reserved whether or not the session is interrupted, so the instruction below it does
        # not move when the stop is pressed (UI_PRINCIPLES.md 3.3).
        self.alert = label(SIZE_BODY, wrap=True)
        self.alert.setFixedHeight(self.alert.fontMetrics().lineSpacing() * ALERT_LINES)

    def _build_centre(self) -> None:
        # What to do now is the largest thing on the screen, because it is the one thing that
        # has to be readable from where the experimenter is standing (UI_PRINCIPLES.md 3.1).
        self.instruction = label(SIZE_HEADLINE, wrap=True)
        self.instruction.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.instruction.setFixedHeight(
            self.instruction.fontMetrics().lineSpacing() * INSTRUCTION_LINES
        )
        self.status = label(SIZE_BODY, wrap=True, colour=SECONDARY)
        self.status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.status.setFixedHeight(self.status.fontMetrics().lineSpacing() * STATUS_LINES)
        # A fixed two lines, however many items are open: the summaries are printed at startup
        # and in the log, and here the line only has to say which are not final (SPEC.md 20).
        self.open_items = label(SIZE_SMALL, wrap=True, colour=WARNING_COLOUR)
        self.open_items.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.open_items.setFixedHeight(
            self.open_items.fontMetrics().lineSpacing() * OPEN_ITEMS_LINES
        )
        # The monofilament technique, in the smallest size (docs/LOG.md N5.4), and only while a
        # filament is being applied. It is the one thing on the screen allowed to be cut short
        # when space runs out, which is why it is last and why its height is not asked for.
        self.technique = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        self.technique.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.technique.setText(self.text["instructions"]["monofilament"])
        self.technique.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self.technique.setVisible(False)
        left = QVBoxLayout()
        left.setSpacing(ITEM_GAP_PX)
        left.addWidget(self.instruction)
        left.addWidget(self.status)
        left.addWidget(self.open_items)
        left.addWidget(self.technique, 1)

        # Where the stimulus goes, then the garment: both answer "where", and neither is read
        # as often as the instruction.
        self.zone = ZoneDiagram()
        self.zone.setMinimumHeight(ZONE_MIN_HEIGHT_PX)
        self.target = label(SIZE_BODY)
        self.target.setAlignment(Qt.AlignHCenter)
        self.hardware_title = label(SIZE_SMALL, colour=SECONDARY)
        self.hardware_title.setText(self.text["hardware"]["title"])
        self.garment = label(SIZE_BODY)
        self.pressures = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        self.faults = label(SIZE_SMALL, colour=DISCONNECTED_COLOUR)
        self.faults.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        # One disconnect/reconnect button (SPEC.md 11) that says what it will do now.
        self.garment_button = button("")
        self.garment_button.clicked.connect(self._garment_clicked)
        state = QHBoxLayout()
        state.addWidget(self.hardware_title)
        state.addWidget(self.garment)
        state.addStretch(1)

        side = QWidget()
        side.setFixedWidth(SIDE_COLUMN_PX)
        column = QVBoxLayout(side)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ITEM_GAP_PX)
        column.addWidget(self.zone, 1)
        column.addWidget(self.target)
        column.addLayout(state)
        column.addWidget(self.pressures)
        column.addWidget(self.faults)
        column.addWidget(self.garment_button)

        self.centre = QHBoxLayout()
        self.centre.addLayout(left, 1)
        self.centre.addSpacing(GROUP_GAP_PX)
        self.centre.addWidget(side)

    def _build_controls(self) -> None:
        controls = self.text["controls"]
        self.proceed_button = button(controls["start_block"])
        self.pause_button = button(controls["pause"])
        self.resume_button = button(controls["resume"])
        self.discard_button = button(controls["discard_repeat"])
        self.rebalance_button = button(controls["rebalance"])
        self.fit_accept_button = button(controls["fit_accept"])
        self.fit_rerun_button = button(controls["fit_rerun"])
        self.abort_button = button(controls["abort"])
        # The one control that ends the session. Coloured so it is found without reading, and
        # never mistaken for a routine one (UI_PRINCIPLES.md 3.4).
        self.abort_button.setStyleSheet(emphasis_style(DISCONNECTED_COLOUR))

        self.proceed_button.clicked.connect(self.proceed_requested.emit)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.discard_button.clicked.connect(self.discard_requested.emit)
        self.rebalance_button.clicked.connect(self.rebalance_requested.emit)
        self.fit_accept_button.clicked.connect(self.fit_accepted.emit)
        self.fit_rerun_button.clicked.connect(self.open_rerun_dialog)
        self.abort_button.clicked.connect(self.open_abort_dialog)

        self.controls = QGridLayout()
        self.controls.setHorizontalSpacing(ITEM_GAP_PX)
        self.controls.setVerticalSpacing(ITEM_GAP_PX)
        ordered = (
            self.proceed_button,
            self.pause_button,
            self.resume_button,
            self.discard_button,
            self.rebalance_button,
            self.fit_accept_button,
            self.fit_rerun_button,
            self.abort_button,
        )
        for index, widget in enumerate(ordered):
            row, column = divmod(index, CONTROL_COLUMNS)
            self.controls.addWidget(widget, row, column)

    def _build_entries(self) -> None:
        controls = self.text["controls"]
        self.note = line_edit()
        self.note.setPlaceholderText(controls["note"])
        self.note_button = button(controls["add_note"])
        self.note_button.clicked.connect(self._enter_note)
        self.note.returnPressed.connect(self._enter_note)

        self.substitution = line_edit()
        self.substitution.setPlaceholderText(controls["substitution"])
        self.substitution.setFixedWidth(SUBSTITUTION_FIELD_PX)
        self.substitution_button = button(controls["record_substitution"])
        self.substitution_button.clicked.connect(self._enter_substitution)

        # The distances are typed long after the path, a few times a session, so they live in a
        # window of their own that never blocks this one (SPEC.md 8.4).
        self.distances_button = button(controls["open_distances"])
        self.distances_button.clicked.connect(self.open_distances)

        self.entries = QHBoxLayout()
        self.entries.addWidget(self.note, 1)
        self.entries.addWidget(self.note_button)
        self.entries.addSpacing(GROUP_GAP_PX)
        self.entries.addWidget(self.substitution)
        self.entries.addWidget(self.substitution_button)
        self.entries.addSpacing(GROUP_GAP_PX)
        self.entries.addWidget(self.distances_button)

    # -- pushed in by the protocol ------------------------------------------------------

    def set_instruction(self, text: str) -> None:
        """What to do now (SPEC.md 11). Formatted by the caller from the experimenter text.

        Clears the zone diagram's target: a new instruction is a new step, and a stimulus
        location left over from the last one would point at the wrong place. A step that
        places a stimulus calls `set_target` after this.
        """
        self._instruction_text = text
        self._fit_text()
        self.set_target(None)

    def set_status(self, text: str) -> None:
        """Whether the response has been received (SPEC.md 11) -- never what it was."""
        self._status_text = text
        self._fit_text()

    def set_target(
        self, region: str | None, site: int | None = None, filament: bool = False
    ) -> None:
        """Where the current stimulus goes, on the zone diagram (SPEC.md 11).

        `filament` shows the monofilament technique under the instruction.
        """
        self.zone.set_region(region)
        self.technique.setVisible(region is not None and filament)
        if region is None:
            self.target.setText("")
            return
        name = self.text["terms"]["regions"][region]
        zones = self.text["zones"]
        self.target.setText(
            zones["target_region"].format(region=name)
            if site is None
            else zones["target"].format(region=name, site=site)
        )

    def set_actions_enabled(
        self, *, rebalance: bool | None = None, fit_decision: bool | None = None
    ) -> None:
        """What the running procedure is waiting for (SPEC.md 9, 11.1). None leaves it as is.

        `rebalance` enables Rebalance channels; `fit_decision` enables Accept and Re-run. Both
        are otherwise disabled, because a control that does nothing when pressed is one the
        experimenter learns to distrust (UI_PRINCIPLES.md 5.1).
        """
        if rebalance is not None:
            self._awaiting["rebalance"] = bool(rebalance)
        if fit_decision is not None:
            self._awaiting["fit_decision"] = bool(fit_decision)
        self._apply_enabled()

    def set_mapping_phases(self, phases: Sequence[str]) -> None:
        """The time points that have a mapping, in session order (SPEC.md 8.4).

        Distances are entered for one of these, defaulting to the latest; before the first
        mapping there is nothing to enter them for, so the entry is disabled.
        """
        phases = list(phases)
        if phases == self._mapping_phases:
            return
        self._mapping_phases = phases
        self.distances.set_phases(phases)
        self._apply_enabled()

    def open_distances(self) -> None:
        self.distances.show()
        self.distances.raise_()

    # -- the fit preview, SPEC.md 11.1 ---------------------------------------------------

    def show_fit_preview(self, fit) -> None:
        """Open the fit preview on an `F40Fit` or a `FitReady`, and enable Accept and Re-run.

        Refused unless the view says the preview is enabled: a fit carries the participant's
        ratings, and this is the only place they could reach the lab screen.
        """
        if not self.read_view()["fit_preview_enabled"]:
            raise FitPreviewRefused(
                "a fit was handed to the experimenter window with fit_preview.enabled false"
            )
        self.fit_preview.draw(fit)
        self.set_actions_enabled(fit_decision=True)
        self.fit_preview.show()
        self.fit_preview.raise_()

    def hide_fit_preview(self) -> None:
        """Close the preview, with nothing rating-derived left behind in it."""
        self.fit_preview.clear()
        self.fit_preview.hide()
        self.set_actions_enabled(fit_decision=False)

    # -- dialogs -------------------------------------------------------------------------

    def abort_dialog(self) -> ReasonDialog:
        """Confirm the abort and ask why (SPEC.md 11). Built separately so it can be drawn."""
        controls, dialogs = self.text["controls"], self.text["dialogs"]
        return ReasonDialog(
            controls["abort"],
            dialogs["abort_confirm"],
            dialogs["abort_reason"],
            controls["abort"],
            controls["cancel"],
            parent=self,
        )

    def rerun_dialog(self) -> ReasonDialog:
        """Ask why the estimate is being re-run (SPEC.md 11.1): the reason is kept with it."""
        controls, dialogs = self.text["controls"], self.text["dialogs"]
        return ReasonDialog(
            controls["fit_rerun"],
            dialogs["fit_rerun_reason"],
            "",
            controls["fit_rerun"],
            controls["cancel"],
            parent=self,
        )

    def error_dialog(self, message: str) -> MessageDialog:
        dialogs = self.text["dialogs"]
        return MessageDialog(
            dialogs["error"], message, dialogs["close"], colour=DISCONNECTED_COLOUR, parent=self
        )

    def open_abort_dialog(self) -> ReasonDialog:
        dialog = self.abort_dialog()
        dialog.accepted.connect(lambda: self.abort_requested.emit(dialog.reason_text()))
        dialog.open()
        return dialog

    def open_rerun_dialog(self) -> ReasonDialog:
        dialog = self.rerun_dialog()
        dialog.accepted.connect(lambda: self.fit_rerun_requested.emit(dialog.reason_text()))
        dialog.open()
        return dialog

    def show_error(self, message: str) -> MessageDialog:
        dialog = self.error_dialog(message)
        dialog.open()
        return dialog

    # -- the entries ---------------------------------------------------------------------

    def _garment_clicked(self) -> None:
        if self._connected:
            self.garment_disconnect_requested.emit()
        else:
            self.garment_connect_requested.emit()

    def _enter_note(self) -> None:
        note = self.note.text().strip()
        if note:
            self.note_entered.emit(note)
            self.note.clear()

    def _enter_substitution(self) -> None:
        filament = self.substitution.text().strip()
        if filament:
            self.substitution_entered.emit(filament)
            self.substitution.clear()

    # -- read from the session ----------------------------------------------------------

    def refresh(self) -> None:
        """Redraw from `Session.experimenter_view()`. The only way session state gets here."""
        view = self.read_view()
        text = self.text

        # SPEC.md 12.4: persistent and unmissable while they apply, absent when they do not.
        self.placeholder_banner.setVisible(bool(view["placeholder_text"]))
        self.reduced_capability_banner.setText(
            text["banners"]["reduced_capability"].format(value=view["garment_driver"])
        )
        self.reduced_capability_banner.setVisible(bool(view["reduced_capability_device"]))
        self.fit_preview_banner.setVisible(bool(view["fit_preview_enabled"]))

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
            text["status"]["elapsed"].format(time=_clock_text(view["elapsed_s"]))
        )
        self._draw_countdown(view["next_event"])
        self._draw_interruption(view["interruption"])
        self._draw_hardware(view["hardware"], view["phase"])

        # By number, so twenty open items still fit the line; the summaries are the tooltip,
        # and are printed at startup (config.OpenItem.__str__ is "[number] summary").
        items = view["unresolved_open_items"]
        shown = []
        for item in items:
            number = ITEM_NUMBER.match(item)
            shown.append(number[1] if number else item)
        self._open_items_text = (
            text["warnings"]["open_items"].format(value=", ".join(shown)) if items else ""
        )
        self._open_items_detail = LINE_SEPARATOR.join(items)
        self.open_items.setVisible(bool(items))
        self._fit_text()
        self._apply_enabled()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_text()

    def _left_width(self) -> int:
        """The instruction column's width, from the window's: known before the first layout."""
        return self.width() - 2 * MARGIN_PX - GROUP_GAP_PX - SIDE_COLUMN_PX

    def _fit_text(self) -> None:
        """Fit the instruction and the status to their regions, stepping down the scale."""
        width = self._left_width()
        _fit_to(self.instruction, self._instruction_text, INSTRUCTION_SIZES, width,
                self.instruction.height())
        _fit_to(self.status, self._status_text, STATUS_SIZES, width, self.status.height())
        self.open_items.setText(self._open_items_text)
        self.open_items.setToolTip(self._open_items_detail)

    def _draw_countdown(self, event: dict | None) -> None:
        """SPEC.md 7.4: the software counts down, the experimenter launches."""
        status = self.text["status"]
        if event is None:
            self.countdown.setText("")
            return
        is_block = event["kind"] == BLOCK
        if is_block:
            name = status["block_label"].format(
                block=event["block_index"],
                value=self.text["terms"]["block_types"][event["block_type"]],
            )
        else:
            name = self.text["phases"][event["label_key"]]
        # Due and overdue look different from a countdown and from each other: the first says
        # get ready, the other two say act now, and overdue says it louder
        # (UI_PRINCIPLES.md 3.2).
        if event["overdue"]:
            shown = (
                status["block_overdue"].format(block=event["block_index"])
                if is_block
                else status["event_overdue"].format(phase=name)
            )
            style = emphasis_style(DISCONNECTED_COLOUR)
        elif event["due_in_s"] <= 0:
            shown = (
                status["block_due"].format(block=event["block_index"])
                if is_block
                else status["event_due"].format(phase=name)
            )
            style = emphasis_style(WARNING_COLOUR)
        else:
            shown = status["next_event"].format(
                phase=name, time=_clock_text(math.ceil(event["due_in_s"]))
            )
            style = f"color: {SECONDARY};"
        self.countdown.setText(shown)
        self.countdown.setStyleSheet(style)

    def _draw_interruption(self, interruption: str | None) -> None:
        assert interruption is None or interruption in INTERRUPTIONS, interruption
        self._interruption = interruption
        if interruption is None:
            self.alert.setText("")
            self.alert.setStyleSheet("")
            return
        self.alert.setText(self.text["status"][f"interrupted_{interruption}"])
        # The stop is the participant's and is red; a pause is the experimenter's own and amber.
        colour = DISCONNECTED_COLOUR if interruption == EMERGENCY_STOP else WARNING_COLOUR
        self.alert.setStyleSheet(emphasis_style(colour))

    def _draw_hardware(self, hardware: dict, phase: str) -> None:
        # Connected is the quiet, expected state; disconnected is loud. A hazard state that is
        # typeset exactly like a working one is indistinguishable at a glance, which is the
        # only way this line is ever read (UI_PRINCIPLES.md 3.2).
        status = self.text["status"]
        self._connected = bool(hardware["connected"])
        self.garment.setText(status["connected" if self._connected else "disconnected"])
        self.garment.setStyleSheet(
            f"color: {SECONDARY};"
            if self._connected
            else emphasis_style(DISCONNECTED_COLOUR)
        )
        # No pressures means no line at all -- never a placeholder that says something is being
        # withheld, which would itself tell the experimenter the phase matters (SPEC.md 16).
        pressures = hardware["channel_pressure_kpa"]
        if pressures is None or phase in BLINDED_PHASES:
            self.pressures.setText("")
            self.pressures.setVisible(False)
        else:
            # Each reading held together, so a line break never separates a channel from its
            # pressure.
            readings = PRESSURE_SEPARATOR.join(
                status["channel_pressure_short"]
                .format(channel=channel, value=f"{kpa:.1f}")
                .replace(" ", NO_BREAK_SPACE)
                for channel, kpa in sorted(pressures.items())
            )
            self.pressures.setText(status["channel_pressures"].format(value=readings))
            self.pressures.setVisible(bool(pressures))
        words = self.text["hardware"]
        if not hardware["faults"]:
            faults = ""
        elif phase in BLINDED_PHASES:
            # That there is a fault is shown; which channel is not, because the channels in use
            # differ by condition (SPEC.md 16). The log has the detail.
            faults = words["fault_withheld"].format(value=len(hardware["faults"]))
        else:
            faults = LINE_SEPARATOR.join(
                words["fault"].format(value=fault) for fault in hardware["faults"]
            )
        self.faults.setText(
            self.faults.fontMetrics().elidedText(faults, Qt.ElideRight, SIDE_COLUMN_PX)
        )
        self.faults.setToolTip(faults)
        self.faults.setVisible(bool(faults))

    def _apply_enabled(self) -> None:
        """Which controls do something now. Read from the view where it says, else pushed in.

        While the session is interrupted, Resume and Abort are the only ways forward, so they
        are the only controls enabled besides the notes (SPEC.md 13).
        """
        running = self._interruption is None
        self.proceed_button.setEnabled(running)
        self.pause_button.setEnabled(running)
        self.resume_button.setEnabled(not running)
        self.discard_button.setEnabled(running)
        self.rebalance_button.setEnabled(running and self._awaiting["rebalance"])
        deciding = running and self._awaiting["fit_decision"]
        self.fit_accept_button.setEnabled(deciding)
        self.fit_rerun_button.setEnabled(deciding)
        self.fit_preview.accept_button.setEnabled(deciding)
        self.fit_preview.rerun_button.setEnabled(deciding)
        self.garment_button.setText(
            self.text["controls"]["disconnect" if self._connected else "connect"]
        )
        self.distances_button.setEnabled(bool(self._mapping_phases))


class FitPreviewWindow(QDialog):
    """The fit preview (SPEC.md 11.1): the points, the fitted line, its quality, what the
    session will use, and Accept / Re-run. Non-modal, owned by the experimenter window.

    Only `ExperimenterWindow.show_fit_preview` draws into it, and only while the preview is
    enabled.
    """

    def __init__(self, window: ExperimenterWindow):
        super().__init__(window)
        self.text = window.text
        controls = window.text["controls"]
        self.setStyleSheet(stylesheet())
        self.setModal(False)
        self.setFixedWidth(FIT_WINDOW_WIDTH_PX)

        self.title = label(SIZE_LARGE)
        self.plot = FitPlot()
        self.plot.setFixedHeight(FIT_PLOT_HEIGHT_PX)
        self.quality = label(SIZE_BODY, wrap=True)
        self.derived = label(SIZE_BODY, wrap=True)
        self.accept_button = button(controls["fit_accept"], SIZE_BODY)
        self.rerun_button = button(controls["fit_rerun"], SIZE_BODY)
        self.accept_button.clicked.connect(window.fit_accepted.emit)
        self.rerun_button.clicked.connect(window.open_rerun_dialog)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.rerun_button)
        buttons.addWidget(self.accept_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.plot)
        layout.addWidget(self.quality)
        layout.addWidget(self.derived)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addLayout(buttons)

    def clear(self) -> None:
        self.plot.clear()
        for widget in (self.title, self.quality, self.derived):
            widget.setText("")

    def draw(self, fit) -> None:
        # Imported here: both modules build on the experimenter window, so a module-level
        # import is a cycle.
        from tatp.pinprick import F40Fit
        from tatp.touchcal import FitReady

        if isinstance(fit, F40Fit):
            self._draw_f40(fit)
        elif isinstance(fit, FitReady):
            self._draw_touch(fit)
        else:
            raise TypeError(f"the fit preview draws an F40Fit or a FitReady, not {fit!r}")
        self.setWindowTitle(self.title.text())
        self.adjustSize()

    def _draw_f40(self, fit) -> None:
        text = self.text["fit_preview"]
        result = fit.result
        missing = text["missing"]
        forces = [force for force, _ in fit.points] + [result.f40_mn]
        f40_axis = math.log10(result.f40_mn)

        def rating_at(force_mn: float) -> float:
            return fit.target_vas_pct + fit.slope_vas_per_log10 * (
                math.log10(force_mn) - f40_axis
            )

        self.title.setText(text["f40_title"].format(value=result.run_index))
        self.plot.set_data(
            fit.points,
            sample_line(min(forces), max(forces), True, rating_at),
            (result.f40_mn, fit.target_vas_pct),
            log_x=True,
            x_label=text["x_force"],
            y_label=text["y_rating"],
        )
        lines = [
            text["f40_quality"].format(
                rho=_number(result.ordinal_rho, ".2f", missing),
                measure=result.applications_measure,
                total=result.applications_total,
            )
        ]
        if result.out_of_range:
            direction = self.text["terms"]["out_of_range"][result.out_of_range_direction]
            lines.append(text["f40_flags_out_of_range"].format(value=direction))
        if result.capped:
            lines.append(text["f40_flags_capped"])
        self.quality.setText(LINE_SEPARATOR.join(lines))
        self.derived.setText(
            text["f40_derived"].format(
                f40=f"{result.f40_mn:.1f}",
                filament=result.chosen_filament_label_g,
                force=f"{result.chosen_force_mn:.1f}",
                slope=f"{fit.slope_vas_per_log10:g}",
            )
        )

    def _draw_touch(self, fit) -> None:
        text = self.text["fit_preview"]
        missing = text["missing"]
        # Catch trials are zero pressure: not part of the fit, and not a position on a log axis.
        points = [(kpa, rating) for kpa, rating, catch in fit.points if not catch]
        line = ()
        log_x = fit.fit is not None and fit.fit.fit_form == maths.LOG_PRESSURE
        if fit.fit is not None:
            model = fit.fit
            bracket = [model.bracket_min_kpa, model.bracket_max_kpa]
            pressures = [kpa for kpa, _ in points] + bracket
            usable = [kpa for kpa in pressures if kpa > 0 or not log_x]

            def rating_at(kpa: float) -> float:
                axis = float(maths.to_axis([kpa], model.fit_form)[0])
                return model.intercept + model.slope * axis

            line = sample_line(min(usable), max(usable), log_x, rating_at)
        self.title.setText(text["touch_title"].format(value=fit.run_index))
        self.plot.set_data(
            points,
            line,
            None,
            log_x=log_x,
            x_label=text["x_pressure_log" if log_x else "x_pressure_linear"],
            y_label=text["y_rating"],
        )
        monotonic = (
            missing
            if fit.monotonic is None
            else text["answer_yes" if fit.monotonic else "answer_no"]
        )
        verdict = (
            text["touch_stage1_pass"]
            if fit.stage1_pass
            else text["touch_stage1_fail"].format(
                value=", ".join(self.text["terms"]["stage1"][r] for r in fit.stage1_failures)
            )
        )
        self.quality.setText(
            LINE_SEPARATOR.join(
                (
                    text["touch_quality"].format(
                        r_squared=_number(fit.r_squared, ".2f", missing),
                        residual_sd=_number(fit.residual_sd, ".1f", missing),
                        monotonic=monotonic,
                    ),
                    verdict,
                )
            )
        )
        self.derived.setText(
            text["touch_derived"].format(
                p20=_number(fit.p20_kpa, ".1f", missing),
                p30=_number(fit.p30_kpa, ".1f", missing),
                p80=_number(fit.p80_kpa, ".1f", missing),
            )
        )


class DistancesDialog(QDialog):
    """The four mapping distances for one time point (SPEC.md 8.4). Non-modal, never blocking.

    Emits `entered(phase, distances)` -- the window's `distances_entered` -- with None for a
    field left blank. The ledger queries an implausible value rather than taking it, so the
    fields keep what was typed: confirming it is pressing Enter distances again.
    """

    def __init__(self, text: dict, entered: SignalInstance, parent: QWidget | None = None):
        super().__init__(parent)
        self.text = text
        self.entered = entered
        controls = text["controls"]
        self.setWindowTitle(controls["open_distances"])
        self.setStyleSheet(stylesheet())
        self.setModal(False)

        caption = label(SIZE_BODY, wrap=True)
        caption.setText(controls["distances"])
        self.phase = sized(QComboBox(), SIZE_BODY)
        self.phase.currentIndexChanged.connect(self.clear)
        validator = QRegularExpressionValidator(QRegularExpression(DISTANCE_PATTERN), self)
        # `terms.mapping_paths` lists the paths in `mapping.path_ids` order; a test holds the
        # two in step, so the fields are in the order the ledger reads them.
        self.path_ids = list(text["terms"]["mapping_paths"])
        self.fields: list[QLineEdit] = []
        form = QGridLayout()
        form.setHorizontalSpacing(GROUP_GAP_PX)
        for row, path_id in enumerate(self.path_ids):
            name = label(SIZE_BODY, colour=SECONDARY)
            name.setText(text["terms"]["mapping_paths"][path_id])
            field = line_edit(SIZE_BODY)
            field.setFixedWidth(DISTANCE_FIELD_PX)
            field.setValidator(validator)
            form.addWidget(name, row, 0)
            form.addWidget(field, row, 1)
            self.fields.append(field)
        self.enter_button = button(controls["enter_distances"], SIZE_BODY)
        self.enter_button.clicked.connect(self.enter)
        self.close_button = button(text["dialogs"]["close"], SIZE_BODY)
        self.close_button.clicked.connect(self.hide)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.enter_button)
        layout = QVBoxLayout(self)
        layout.addWidget(caption)
        layout.addWidget(self.phase)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(form)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addLayout(buttons)
        self.set_phases([])

    def set_phases(self, phases: Sequence[str]) -> None:
        """The phases with a mapping, the latest selected; nothing to enter before the first."""
        self.phase.blockSignals(True)
        self.phase.clear()
        for phase in phases:
            self.phase.addItem(self.text["phases"][phase], phase)
        self.phase.setCurrentIndex(len(phases) - 1)
        self.phase.blockSignals(False)
        self.clear()
        for widget in (self.phase, self.enter_button, *self.fields):
            widget.setEnabled(bool(phases))

    def enter(self) -> None:
        """Emit what is filled in, None for a blank. Nothing goes while any field is invalid."""
        if self.phase.currentData() is None:
            return
        values: list[float | None] = []
        valid = True
        for field in self.fields:
            typed = field.text().strip()
            if not typed:
                values.append(None)
                field.setStyleSheet("")
            elif field.hasAcceptableInput():
                values.append(float(typed.replace(DECIMAL_COMMA, DECIMAL_POINT)))
                field.setStyleSheet("")
            else:
                valid = False
                field.setStyleSheet(f"border: 1px solid {DISCONNECTED_COLOUR};")
        if valid and any(value is not None for value in values):
            self.entered.emit(self.phase.currentData(), tuple(values))

    def clear(self, *_) -> None:
        for field in self.fields:
            field.clear()
            field.setStyleSheet("")
