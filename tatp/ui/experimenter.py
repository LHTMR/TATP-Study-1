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
points have a mapping through `set_mapping_phases()`. Whether Next step would do anything is
asked of the rig (`set_proceed_source`): a yes or no, the same in every condition.

It carries no wording of its own: every string comes from
`config/text/experimenter_{sv,en}.yaml` (SPEC.md 10.4).

**The experimenter's actions are signals.** Every action SPEC.md 11 gives the experimenter is a
signal below, and every signal has a control that emits it. A protocol never reads a widget; it
connects to a signal, so the virtual experimenter of SPEC.md 17.5 drives the same path a real
one does.

**The layout is read in a fixed order** (UI_PRINCIPLES.md 5.2): the banner region with the
open items, who and where with the clock, the phase with the countdown, the steps of the phase,
any interruption, then what is going on now -- the largest thing on the screen -- and the
garment and the mapping distances on the right, and the controls along the bottom: the routine
ones, then those a step offers now and then. Every region above the controls has a fixed
height, and whatever comes and goes keeps its place while it is hidden, so nothing moves when a
warning appears, a control is offered or an instruction is long (UI_PRINCIPLES.md 3.3). A long
instruction steps down the type scale to fit its region rather than growing it.

**What is going on now is one panel** (S, 21 Oct 2026: "This area should always be what's going
on now"): a heading saying whether to act, get ready or wait -- a wait with its time left --
then the instruction with the zone diagram beside it, what the participant is doing, and the
filament-applied-instead choice with its own message. Whatever is entered says what became of
it beside the entry, never on a line of its own elsewhere.

**The fit preview is a window of its own** (SPEC.md 11.1): the one named screen where ratings
reach the experimenter (UI_PRINCIPLES.md 2.5), opened at the end of an estimation run and
closed after the choice. Its Accept and Re-run are the main window's, so either can be used.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Collection, Sequence
from html import escape

from PySide6.QtCore import QPoint, QRegularExpression, Qt, QTimer, Signal, SignalInstance
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QGuiApplication,
    QKeySequence,
    QRegularExpressionValidator,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
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
from tatp.ui.garment_display import GarmentDisplay
from tatp.ui.timeline import PhaseTimeline
from tatp.ui.widgets import (
    CORRECT_DISCARD,
    CORRECT_FILAMENT,
    DEMO_BANNER_COLOUR,
    DISABLED,
    DISCONNECTED_COLOUR,
    FOREGROUND,
    GROUP_GAP_PX,
    ITEM_GAP_PX,
    PLACEHOLDER_COLOUR,
    REDUCED_CAPABILITY_COLOUR,
    SECONDARY,
    SIZE_BODY,
    SIZE_HEADLINE,
    SIZE_LARGE,
    SIZE_SMALL,
    TARGET_COLOUR,
    WARNING_COLOUR,
    ActionChoiceDialog,
    CorrectionDialog,
    FitPlot,
    MessageDialog,
    ReasonDialog,
    ZoneDiagram,
    banner_style,
    button,
    emphasis_button_style,
    emphasis_style,
    label,
    line_edit,
    primary_button_style,
    sample_line,
    set_points,
    sized,
    stylesheet,
)
from tatp.units import MIN_PER_H, MS_PER_S, S_PER_MIN

# The window's own margin: narrower than the shared one, because height is what this screen is
# short of.
MARGIN_PX = 20
# The lab's experimenter screen in Qt's pixels: 1920 x 1200 at 150 % (docs/LOG.md N7.U10).
# The window is never larger, on any machine, so a bigger screen -- a MacBook's 1440 x 870 --
# shows what the lab shows, not a roomier layout (S, 22 Oct 2026).
LAB_SCREEN_WIDTH_PX = 1280
LAB_SCREEN_HEIGHT_PX = 800
IDENTITY_SEPARATOR = "  ·  "
# Between a button's label and its key.
KEY_HINT_SEPARATOR = "  "
LINE_SEPARATOR = "\n"
RICH_LINE_BREAK = "<br>"
# Nothing below the banners may move during a session, because a layout that reflows at the
# moment something has gone wrong is a layout that gets misread (UI_PRINCIPLES.md 3.3). Every
# banner is settled before the session starts -- the text files, the driver, the fit-preview
# switch -- so the banner region takes the space of the banners present, fixed from the first
# refresh, and `refresh` refuses a banner that comes or goes after it. It used to reserve room
# for all three, which was a quarter of a laptop screen left empty in almost every session.
# The interruption line is reserved at one line; a test holds both languages' wording to it.
ALERT_LINES = 1
# The heading at the instruction's own largest size, at least as prominent as what it heads
# (S, 22 Oct 2026); a stop or pause line too long for it is set a size down until it fits.
ALERT_SIZES = (SIZE_HEADLINE, SIZE_LARGE, SIZE_BODY, SIZE_SMALL)
# What to do now has four lines at the headline size, so a sentence to read aloud keeps it
# (review of N7.F16). A longer one is set a size down the scale, until it fits (3.3, 4.3).
INSTRUCTION_LINES = 4
INSTRUCTION_SIZES = (SIZE_HEADLINE, SIZE_LARGE, SIZE_BODY, SIZE_SMALL)
# The phase row's shares: two thirds the timeline, one third the countdown, which steps down
# the type scale to fit its third (LOG N7.F16h).
TIMELINE_SHARE = 2
COUNTDOWN_SHARE = 1
COUNTDOWN_SIZES = (SIZE_LARGE, SIZE_BODY, SIZE_SMALL)
# How long Next step is shown down after Space presses it: long enough to be seen.
PRESS_SHOWN_MS = 120
# The status line under it: two lines of body text, or the small size if that is not enough.
STATUS_LINES = 2
STATUS_SIZES = (SIZE_BODY, SIZE_SMALL)
# How many stage starts a warning outlives (`new_stage`).
WARNING_STAGES = 1
# The right of the window: the garment, and beside it the mapping distances (S, 21 Oct 2026).
# Side by side, because stacked they are taller than the lab laptop has room for, and narrow
# enough to leave the instruction the width a sentence read aloud needs at the large size.
GARMENT_COLUMN_PX = 190
DISTANCES_COLUMN_PX = 210
SIDE_COLUMN_PX = GARMENT_COLUMN_PX + ITEM_GAP_PX * 2 + DISTANCES_COLUMN_PX
FAULT_LINES = 4
# Beside the instruction it belongs to, as tall as the instruction's region (S, 21 Oct 2026:
# "bigger and below/connected to the instructions"). Below it there is no height to spare on
# the lab laptop (UI_PRINCIPLES.md 5.21), so it stands at the instruction's right. Fixed, so
# nothing resizes as it comes and goes.
ZONE_HEIGHT_PX = 240
DISTANCE_FIELD_PX = 56
# The distances box's message: lines of small text enough for a query in its narrow column.
DISTANCE_MESSAGE_LINES = 4
# A distance field walked and still awaited: a heavier outline and a tint of the same colour.
AWAITED_BORDER_PX = 2
AWAITED_TINT_ALPHA = 0.25
# One line beside the choice: the lab laptop has no height for a second (LOG N7.F18q).
SUBSTITUTION_MESSAGE_LINES = 1
CONTROL_COLUMNS = 5
# Over what to do now (S, 21 Oct 2026): act, get ready, or wait. Keys of the experimenter
# text's `headings`, each drawn in its own colour, so it is known before it is read
# (UI_PRINCIPLES.md 5.6).
NOW, PREPARE, WAIT = HEADINGS = ("now", "prepare", "wait")
WAIT_FOR = "wait_for"
PREPARE_FOR = "prepare_for"
# The two kinds of entry message, by how they are drawn.
CONFIRMED, QUERIED = "confirmed", "queried"
# The figure is a right hand (assets/hyperalgesia_zones.svg): mirrored for this limb.
MIRRORED_LIMB = "left"
FIT_WINDOW_WIDTH_PX = 720
FIT_PLOT_HEIGHT_PX = 380
# A distance in mm, with either decimal mark: the Swedish keyboard types a comma.
DISTANCE_PATTERN = r"^-?\d+([.,]\d+)?$"
DECIMAL_COMMA = ","
DECIMAL_POINT = "."
ITEM_NUMBER = re.compile(r"^\[([^\]]+)\]")

EMERGENCY_STOP = "emergency_stop"
PAUSE = "pause"
INTERRUPTIONS = (EMERGENCY_STOP, PAUSE)
# What `recalibration_requested` carries first, and the `recalibration` log vocabulary
# (docs/DATA_SCHEMA.md); the keys of `dialogs.recalibrate_choices`.
RECALIBRATE_REBALANCE = "rebalance"
RECALIBRATE_RESTART = "restart"
RECALIBRATIONS = (RECALIBRATE_REBALANCE, RECALIBRATE_RESTART)
BLOCK = "block"
# The phases during which per-channel pressure would differ by condition (SPEC.md 16). The view
# already withholds it then; the window holds the same line, so a view that leaked it would not
# be drawn.
BLINDED_PHASES = ("intervention", "rekindle")


class FitPreviewRefused(Exception):
    """A fit was handed over with the preview off. It carries ratings (SPEC.md 11.1)."""


def clock_text(seconds: float) -> str:
    """mm:ss, and h:mm:ss from an hour: "185:00" read as a typo (review of LOG N7.F16)."""
    minutes, remainder = divmod(int(seconds), int(S_PER_MIN))
    hours, minutes = divmod(minutes, int(MIN_PER_H))
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes:02d}:{remainder:02d}"


def event_name(text: dict, event: dict) -> str:
    """What a scheduled event is called on the screen: a block by its number and type, which
    every condition shares, or a phase."""
    if event["kind"] == BLOCK:
        block_type = text["terms"]["block_types"][event["block_type"]]
        return text["status"]["block_label"].format(block=event["block_index"],
                                                    value=block_type)
    return text["phases"][event["label_key"]]


def _number(value: float | None, spec: str, missing: str) -> str:
    return missing if value is None else format(value, spec)


def _banner(colour: str) -> QLabel:
    """One line, never wrapped and never widening the window: a test holds each headline to
    the width of the lab laptop in both languages."""
    made = label(SIZE_BODY)
    made.setStyleSheet(banner_style(colour))
    made.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return made


def _reserve(widget: QWidget) -> None:
    """Keep `widget`'s space while it is hidden, so its coming and going moves nothing
    (UI_PRINCIPLES.md 3.3)."""
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)


def _restyle(widget: QWidget, sheet: str) -> None:
    """Set a style sheet only when it changes: `refresh` runs on a timer, and every
    `setStyleSheet` re-polishes the widget."""
    if widget.styleSheet() != sheet:
        widget.setStyleSheet(sheet)


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
    # "Next step": every point where the software waits for the experimenter to say go -- the
    # next block, the next phase, the next path, "earplugs fitted". The software times; the
    # experimenter launches (SPEC.md 7.4). Enabled except while interrupted (LOG N7.U10).
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
    # A correction confirmed once it could no longer be taken: what was chosen, for the log.
    correction_refused = Signal(str)
    # The four mapping distances for one time point (SPEC.md 8.4): the phase, then a tuple of
    # millimetres with None for any not yet measured. Entered whenever convenient.
    distances_entered = Signal(str, object)
    # The fit preview's choice (SPEC.md 11.1). A re-run carries the experimenter's reason.
    fit_accepted = Signal()
    fit_rerun_requested = Signal(str)
    rebalance_requested = Signal()
    # Re-calibration, while touch is calibrated or delivered, or in place of Resume after a
    # stop then (docs/LOG.md N7.F12a1): `rebalance` or `restart`, then the reason's key from
    # `dialogs.recalibration_reasons`.
    recalibration_requested = Signal(str, str)
    # End touch calibration early, on a pilot rig only (docs/LOG.md N7.F8b). Not a skip-trial
    # control: shown only while the procedure offers it, and recorded as a skipped calibration.
    skip_calibration_requested = Signal()
    garment_connect_requested = Signal()
    garment_disconnect_requested = Signal()
    # A step's other answer, offered by the step with its own label (`offer_alternative`):
    # "They can still hear it", "They could not press the stop", ... (review of N7.F16).
    alternative_requested = Signal()
    # The participant has been awaited past `vas.no_response_warning_s`: the seconds, for
    # the log.
    no_response = Signal(float)

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
        self._awaiting = {"rebalance": False, "fit_accept": False, "fit_rerun": False,
                          "discard": False,
                          "skip_calibration": False, "substitution": False, "closed": False,
                          "recalibrate_rebalance": False, "recalibrate_restart": False,
                          "recalibration_used": False}
        self._interruption: str | None = None
        # A step's other answer, while one is offered (`offer_alternative`).
        self._alternative: str | None = None
        # The stop rehearsal waiting for its stop (`set_rehearsal`), and a resume under way.
        self._rehearsing = False
        # How long the participant has been awaited, and the threshold to say so
        # (`set_no_response_s`); the warning shown for it, while it is.
        self._awaited_since_s: float | None = None
        self._no_response_s: float | None = None
        self._no_response_shown: str | None = None
        self._resuming = False
        self._connected = False
        self._mapping_phases: list[str] = []
        self._instruction_text = ""
        # Over it: act, get ready or wait (`set_instruction`), and a wait's own time left, if
        # the step counts it rather than the schedule.
        self._heading: str | None = None
        self._wait_s: float | None = None
        # The next scheduled step as last drawn, which a wait counts down to; and whether the
        # garment's link is lost, which takes the line over the instruction.
        self._next_event: dict | None = None
        self._link_lost = False
        self._status_text = ""
        # The status as set, before any wait is added to it (`_check_response_wait`).
        self._status_raw = ""
        self._warning_text = ""
        self._warning_stages = 0
        self._open_items_text = ""
        # The steps of each phase, for the row under the phases (`set_stage_plan`).
        self._stage_plan: dict[str, list[tuple[str, str, str]]] = {}
        self._stage_group: str | None = None
        # Faults first seen during the intervention or the rekindle: never shown in detail.
        self._withheld_faults: set[str] = set()
        # What `_fit_text` last fitted, so a refresh with nothing new does no layout work.
        self._fitted: tuple | None = None
        # Whether a press of Next step would do anything now (`set_proceed_source`). Always,
        # for a window with no session behind it.
        self._proceed_awaited: Callable[[], bool] = lambda: True

        self.setMaximumSize(LAB_SCREEN_WIDTH_PX, LAB_SCREEN_HEIGHT_PX)
        self._build_banners()
        self._build_header()
        self._build_centre()
        self._build_entries()
        self._build_controls()
        self.fit_preview = FitPreviewWindow(self)
        # The window holds the focus, so Space is Next: given none, Qt hands it to the first
        # field that takes it -- the note -- and Space typed spaces there (S, 22 Oct 2026). A
        # click on the window's background takes it back from a field.
        self.setFocusPolicy(Qt.ClickFocus)
        self.setFocus()

        # Read top to bottom: banners, who and where, phase and clock, the phase's steps, any
        # interruption, then what is going on now, then the controls. The gaps carry that
        # order -- an evenly spaced list of labels has no order at all (UI_PRINCIPLES.md 5.2).
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        # Every gap is one of the shared spacings below, none left to the style's default.
        layout.setSpacing(0)
        layout.addWidget(self.banner_area)
        layout.addLayout(self.identity_row)
        layout.addLayout(self.phase_row)
        layout.addSpacing(ITEM_GAP_PX // 2)
        layout.addWidget(self.stages)
        layout.addLayout(self.alert_row)
        # Close: the heading is the instruction's own (S, 22 Oct 2026).
        layout.addSpacing(ITEM_GAP_PX // 2)
        layout.addLayout(self.centre, 1)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(self.controls)
        self._layout = layout

        self.refresh()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        if refresh_interval_s is not None:
            self.timer.start(int(round(float(refresh_interval_s) * MS_PER_S)))

    # -- construction --------------------------------------------------------------------

    def _build_banners(self) -> None:
        # One line each, the detail in the tooltip: a banner is read once, at the start, and
        # after that it only has to be recognised, by its colour and its first words
        # (UI_PRINCIPLES.md 3.2). Four two-line banners out-shouted the instruction.
        banners_text = self.text["banners"]
        self.placeholder_banner = _banner(PLACEHOLDER_COLOUR)
        self.placeholder_banner.setText(banners_text["placeholder_text"])
        self.placeholder_banner.setToolTip(banners_text["placeholder_text_detail"])
        self.reduced_capability_banner = _banner(REDUCED_CAPABILITY_COLOUR)
        # SPEC.md 11.1: "in the same register as the reduced-capability banner". Both say the
        # session runs and part of what it records is flagged, which is the same response, so
        # they look the same (UI_PRINCIPLES.md 3.4).
        self.fit_preview_banner = _banner(REDUCED_CAPABILITY_COLOUR)
        self.fit_preview_banner.setText(banners_text["fit_preview"])
        self.fit_preview_banner.setToolTip(banners_text["fit_preview_detail"])
        # A demonstration (tatp/demo.py): the session runs, and nothing it records is data.
        self.demo_banner = _banner(DEMO_BANNER_COLOUR)
        self.demo_banner.setText(banners_text["demo"])
        # Which open items are not final, by number (SPEC.md 20). Here rather than under the
        # instruction, because like the banners it is settled before the session and does not
        # change what to do now. One line, cut rather than wrapped: the summaries are the
        # tooltip, and are printed at startup and in the log.
        self.open_items = label(SIZE_SMALL, colour=WARNING_COLOUR)
        self.open_items.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.banner_area = QWidget()
        banners = QVBoxLayout(self.banner_area)
        banners.setContentsMargins(0, 0, 0, 0)
        banners.addWidget(self.demo_banner)
        banners.addWidget(self.placeholder_banner)
        banners.addWidget(self.reduced_capability_banner)
        banners.addWidget(self.fit_preview_banner)
        banners.addWidget(self.open_items)
        # Which banners are up, and whether the open-items line has its place, from the first
        # refresh on (see the note at the top).
        self._banners_shown: tuple[bool, ...] | None = None
        self._open_items_reserved: bool | None = None

    def _build_header(self) -> None:
        # Who and where, in the smallest size on the screen: it is looked up once at the start
        # of a session and never needed at a glance again (UI_PRINCIPLES.md 5.2).
        self.identity = label(SIZE_SMALL, colour=SECONDARY)
        # The session clock is looked up, not watched: what is timed is the countdown beside
        # the phase. So it sits with who and where, in the same small grey.
        self.elapsed = label(SIZE_SMALL, colour=SECONDARY)
        # How late a scheduled step is, once it is: beside the clock, small, amber, and red
        # only past the overdue alert's margin -- in place of a red OVERDUE in the countdown
        # (S, 21 Oct 2026). Its place is kept, so the clock never moves.
        self.behind = label(SIZE_SMALL)
        _reserve(self.behind)
        self.identity_row = QHBoxLayout()
        self.identity_row.addWidget(self.identity)
        self.identity_row.addStretch(1)
        self.identity_row.addWidget(self.behind)
        self.identity_row.addSpacing(GROUP_GAP_PX)
        self.identity_row.addWidget(self.elapsed)
        # Where the session is up to, phase by phase, the current one named in full (S, 20 Oct
        # 2026; LOG N7.F16h). In the phase's own place once the session's phases are handed
        # over (`set_timeline`); until then, the phase in words.
        self.timeline = PhaseTimeline()
        self.timeline.setVisible(False)
        self.phase = label(SIZE_LARGE)
        self.countdown = label(SIZE_LARGE, colour=SECONDARY)
        self.phase_row = QHBoxLayout()
        self.phase_row.addWidget(self.phase)
        # The timeline and the countdown each have a fixed share of the row, whatever the
        # countdown says, so neither moves when the other changes (UI_PRINCIPLES.md 3.3).
        self.timeline.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.phase_row.addWidget(self.timeline, TIMELINE_SHARE)
        self.phase_row.addSpacing(GROUP_GAP_PX)
        self._phase_countdown = self.phase_row.count()
        self.phase_row.addWidget(self.countdown)
        self._phase_stretch = QWidget()
        self._phase_stretch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.phase_row.addWidget(self._phase_stretch, 1)
        # The steps of the phase under way, the current one named in full (S, 21 Oct 2026: "a
        # second banner below the phase banner with the sub-phases of the current phase").
        # The schedule's, the same in every condition. Its place is kept from the start.
        self.stages = PhaseTimeline(SIZE_BODY)
        self.stages.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        _reserve(self.stages)
        self.stages.setVisible(False)

        # The line over the instruction: whether to act, get ready or wait, a wait with its
        # time left (S, 21 Oct 2026) -- and, in its place, the stop or the pause while the
        # session is interrupted, which is then what is going on now. Reserved, so the
        # instruction below it never moves (UI_PRINCIPLES.md 3.3). How far a series has got
        # is at its right.
        self.alert = label(ALERT_SIZES[0], wrap=True)
        self.alert.setFixedHeight(self.alert.fontMetrics().lineSpacing() * ALERT_LINES)
        self.progress = label(SIZE_LARGE, colour=SECONDARY)
        self._alert_fitted: tuple[str, int] | None = None
        self.alert_row = QHBoxLayout()
        self.alert_row.setSpacing(ITEM_GAP_PX)
        self.alert_row.addWidget(self.alert, 1)
        self.alert_row.addWidget(self.progress)

    def _build_centre(self) -> None:
        # What is going on now, the largest thing on the screen, because it is the one thing
        # that has to be readable from where the experimenter is standing (UI_PRINCIPLES.md
        # 3.1), under the line saying whether to act, get ready or wait (`alert_row`).
        self.instruction = label(SIZE_HEADLINE, wrap=True)
        self.instruction.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.instruction.setFixedHeight(
            self.instruction.fontMetrics().lineSpacing() * INSTRUCTION_LINES
        )
        # Where the stimulus goes, beside the instruction it belongs to: part of it, not of
        # the garment (S, 21 Oct 2026). Shown only while there is a target, so a step with
        # nowhere to go has no picture; which steps have one is a matter of the procedure,
        # never of the condition (SPEC.md 16). While it is hidden the instruction has the
        # width, which a sentence read aloud needs.
        self.zone = ZoneDiagram(self.text["zones"], self.text["terms"]["mapping_paths_short"])
        self.zone.setFixedSize(self.zone.width_for(ZONE_HEIGHT_PX), ZONE_HEIGHT_PX)
        self.zone.setVisible(False)
        instruction_row = QHBoxLayout()
        instruction_row.setSpacing(GROUP_GAP_PX)
        instruction_row.addWidget(self.instruction, 1, Qt.AlignTop)
        instruction_row.addWidget(self.zone, 0, Qt.AlignTop)
        self.status = label(SIZE_BODY, wrap=True, colour=SECONDARY)
        self.status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.status.setFixedHeight(self.status.fontMetrics().lineSpacing() * STATUS_LINES)
        # The monofilament technique while a filament is applied (docs/LOG.md N5.4), and what
        # was saved and how to upload it once the session is over: in the smallest size, the
        # one thing on the screen allowed to be cut short when space runs out, which is why its
        # height is not asked for. Its space is kept while it is hidden, so nothing above it
        # moves between steps (UI_PRINCIPLES.md 5.5).
        self.detail = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        self.detail.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.detail.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self.detail.setMinimumHeight(0)
        _reserve(self.detail)
        self.detail.setVisible(False)
        # No gap around the small print, which takes what height is left and none of the
        # laptop's 640 px (UI_PRINCIPLES.md 5.21).
        left = QVBoxLayout()
        left.setSpacing(0)
        left.addLayout(instruction_row)
        # Half a gap: the instruction's last reserved line is seldom used.
        left.addSpacing(ITEM_GAP_PX // 2)
        left.addWidget(self.status)
        left.addWidget(self.detail, 1)
        left.addLayout(self._build_substitution())

        # The garment, all of it together (S, 21 Oct 2026): its name and state, its channels,
        # the button that disconnects it, and any fault -- then the mapping distances.
        self.hardware_title = label(SIZE_SMALL, colour=SECONDARY)
        self.hardware_title.setText(self.text["hardware"]["title"])
        self.garment = label(SIZE_BODY)
        # The channels, as commanded (`set_garment`): the same display a demonstration shows,
        # fed here from the view, which withholds them while the condition's touch runs.
        self.garment_display: GarmentDisplay | None = None
        self._garment_slot = QVBoxLayout()
        self._garment_slot.setContentsMargins(0, 0, 0, 0)
        # Set by a demonstration, which hands the display the garment's state itself, in every
        # phase (tatp/demo.py); the view then does not.
        self.garment_fed_elsewhere = False
        # One disconnect/reconnect button (SPEC.md 11) that says what it will do now, under the
        # channels it switches off. Withdrawn once the session is closed
        # (`set_actions_enabled(closed=...)`), its place kept.
        self.garment_button = button("")
        self.garment_button.clicked.connect(self._garment_clicked)
        _reserve(self.garment_button)
        # Bounded, so accumulating faults never move the column or push the window off a
        # laptop screen (UI_PRINCIPLES.md 3.3): at most FAULT_LINES lines. The short counts
        # come first and the text is top-aligned, so what a bound cuts is only the tail of the
        # newest fault; its start, which says what failed, always shows. The whole text is in
        # the tooltip and the data.
        self.faults = label(SIZE_SMALL, wrap=True, colour=DISCONNECTED_COLOUR)
        self.faults.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.faults.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.faults.setMaximumHeight(self.faults.fontMetrics().lineSpacing() * FAULT_LINES)
        # The mapping distances, in the window rather than a window of their own (S, 21 Oct
        # 2026), from the first mapping on; their place is kept from the start.
        self.distances = DistancesBox(self.text, self.distances_entered)
        _reserve(self.distances)

        garment = QWidget()
        garment.setFixedWidth(GARMENT_COLUMN_PX)
        column = QVBoxLayout(garment)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ITEM_GAP_PX)
        column.addWidget(self.hardware_title)
        column.addWidget(self.garment)
        column.addLayout(self._garment_slot)
        column.addWidget(self.garment_button)
        column.addWidget(self.faults)
        column.addStretch(1)
        self.distances.setFixedWidth(DISTANCES_COLUMN_PX)
        side = QWidget()
        side.setFixedWidth(SIDE_COLUMN_PX)
        row = QHBoxLayout(side)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(ITEM_GAP_PX * 2)
        row.addWidget(garment, 0, Qt.AlignTop)
        row.addWidget(self.distances, 0, Qt.AlignTop)

        self.centre = QHBoxLayout()
        self.centre.addLayout(left, 1)
        self.centre.addSpacing(GROUP_GAP_PX)
        self.centre.addWidget(side)
        self.set_target(None)

    def _build_substitution(self) -> QHBoxLayout:
        """Correct last application… at the foot of what is going on now, under the
        instruction it is about (S, 22 Oct 2026: one control for both corrections, the filament
        applied instead (SPEC.md 8.2) and discard and repeat (SPEC.md 11)), from the "applied"
        press until the next application's cue; and beside it what became of the last
        correction, until the next application starts. Its place is kept throughout, so
        nothing moves as it comes."""
        self.correct_button = button(self.text["controls"]["correct_application"])
        self.correct_button.clicked.connect(self.open_correction_dialog)
        self.substitution_message = label(SIZE_SMALL, wrap=True)
        self.substitution_message.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.substitution_message.setFixedHeight(
            self.substitution_message.fontMetrics().lineSpacing() * SUBSTITUTION_MESSAGE_LINES)
        # The filaments the dialog offers (`set_filaments`).
        self._filaments: list[str] = []
        row = QHBoxLayout()
        row.setSpacing(ITEM_GAP_PX)
        for widget in (self.correct_button, self.substitution_message):
            _reserve(widget)
        row.addWidget(self.correct_button)
        row.addWidget(self.substitution_message, 1)
        return row

    def _build_controls(self) -> None:
        controls = self.text["controls"]
        # Two tiers. The first row is always there, a size up: the way forward, the
        # interruption, and the end. The second holds what a step offers only now and then,
        # each in a slot of its own that is kept while it is not offered, so the eye learns
        # where each one appears and nothing moves when it does (UI_PRINCIPLES.md 3.3, 5.5).
        # A control that does nothing when pressed is not drawn: ten buttons of equal weight,
        # six of them dead, were "a lot for the eyes" (S, 15 Oct 2026 pilot).
        # The keys are on the buttons, so they are learnt by looking (review of N7.F16).
        keys = self.text["keys"]
        self.proceed_button = button(self._keyed(controls["proceed"], keys["proceed"]),
                                     SIZE_BODY)
        self.pause_button = button(self._keyed(controls["pause"], keys["pause"]), SIZE_BODY)
        self.resume_button = button(self._keyed(controls["resume"], keys["resume"]), SIZE_BODY)
        self.abort_button = button(controls["abort"], SIZE_BODY)
        # A step's other answer, where Next would otherwise have meant "no": labelled by the
        # step with what it does (`offer_alternative`; review of N7.F16).
        self.alternative_button = button("")
        self.alternative_button.clicked.connect(self.alternative_requested.emit)
        self.rebalance_button = button(controls["rebalance"])
        self.fit_accept_button = button(controls["fit_accept"])
        self.fit_rerun_button = button(controls["fit_rerun"])
        # Re-calibration, while touch is calibrated or delivered and beside Resume after a stop
        # then, while the limit allows (docs/LOG.md N7.F12a1): one control, whose dialog says
        # what each choice repeats and asks why (S, 21 Oct 2026).
        self.recalibrate_button = button(controls["recalibrate"])
        # Ends touch calibration early, on a pilot rig, while the calibration offers it.
        self.skip_button = button(controls["skip_calibration"])
        self.skip_button.clicked.connect(self.skip_calibration_requested.emit)
        # In their place after a stop once the limit is reached, saying why only Resume is
        # offered.
        self.recalibration_used = label(SIZE_SMALL, colour=SECONDARY)
        self.recalibration_used.setText(self.text["status"]["recalibration_used"].format(
            controls=controls
        ))
        self.recalibration_used.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # Next is the way forward in every step, so it always looks like it. It is pressable
        # exactly while a press would do something (`set_proceed_source`), which is the same in
        # every condition: the touch start on this side is a fixed display, never the
        # delivery's own timing (SPEC.md 16; LOG N7.D17, N7.F16d). While the session is
        # interrupted Resume is the way forward, and it is only shown then.
        self.proceed_button.setStyleSheet(primary_button_style())
        self.resume_button.setStyleSheet(primary_button_style())
        # The one control that ends the session. Coloured so it is found without reading, and
        # never mistaken for a routine one (UI_PRINCIPLES.md 3.4).
        self.abort_button.setStyleSheet(emphasis_button_style(DISCONNECTED_COLOUR))

        self.proceed_button.clicked.connect(self._proceed_clicked)
        # Space is Next, P Pause and R Resume, wherever the focus is in the program, a text
        # field excepted, which types them (S, 20 Oct 2026; LOG N7.F16d). Across the program,
        # not this window only: on one screen the participant's window is above this one, and
        # a click on it took every key from here (S, 21 Oct 2026: "none of the experimenter
        # shortcuts work"). None is a key the remote sends, so the router never forwards one.
        self.proceed_shortcut = QShortcut(QKeySequence(keys["proceed"]), self)
        self.proceed_shortcut.setContext(Qt.ApplicationShortcut)
        self.proceed_shortcut.activated.connect(self._proceed_key)
        # Pause and Resume from the keyboard too, so neither needs the mouse while the
        # experimenter's hands are on the participant (review of N7.F16).
        self.key_shortcuts = []
        for key, widget in ((keys["pause"], self.pause_button),
                            (keys["resume"], self.resume_button)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(
                lambda widget=widget: widget.isVisible() and widget.isEnabled()
                and widget.click())
            self.key_shortcuts.append(shortcut)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.rebalance_button.clicked.connect(self.rebalance_requested.emit)
        self.fit_accept_button.clicked.connect(self.fit_accepted.emit)
        self.fit_rerun_button.clicked.connect(self.open_rerun_dialog)
        self.recalibrate_button.clicked.connect(self.open_recalibration_dialog)
        self.abort_button.clicked.connect(self.open_abort_dialog)

        self.controls = QGridLayout()
        self.controls.setHorizontalSpacing(ITEM_GAP_PX)
        self.controls.setVerticalSpacing(ITEM_GAP_PX)
        # Pause and Resume each keep a slot of their own rather than sharing one, so a press
        # meant for one can never land on the other as it changes. Abort is last, at the far
        # right, away from Next.
        last = CONTROL_COLUMNS - 1
        for column, widget in ((0, self.proceed_button), (1, self.pause_button),
                               (2, self.resume_button), (last, self.abort_button)):
            self.controls.addWidget(widget, 0, column)
            _reserve(widget)
        # The note between Resume and Abort, in the row that is always there: it can be
        # written at any time (SPEC.md 11), and a row of its own was height the lab laptop
        # does not have (UI_PRINCIPLES.md 5.21).
        self.controls.addLayout(self.entries, 0, last - 1)
        # A control a later step offers, on a row of its own: a step's other answer under the
        # way forward, which it is the alternative to; then the calibration's own rematch,
        # with the re-calibration sharing its slot -- when the procedure offers the rematch,
        # which does the same from where it stands, the rematch has it; Re-run before Accept,
        # as in the fit window and every dialog, the choice that goes on on the right
        # (UI_PRINCIPLES.md 5.5); and Skip calibration last. Discard is with what is going on
        # now (`_build_substitution`), still away from Next.
        for column, widgets in enumerate((
            (self.alternative_button,),
            (self.rebalance_button, self.recalibrate_button),
            (self.fit_rerun_button,),
            (self.fit_accept_button,),
            (self.skip_button,),
        )):
            for widget in widgets:
                self.controls.addWidget(widget, 1, column)
                _reserve(widget)
        # The line saying the re-calibrations are used up, shown only while stopped, spans
        # the row, where nothing else is offered then.
        self.controls.addWidget(self.recalibration_used, 1, 0, 1, CONTROL_COLUMNS)
        _reserve(self.recalibration_used)
        # Columns of one width, so a slot is the same size whatever is in it.
        for column in range(CONTROL_COLUMNS):
            self.controls.setColumnStretch(column, 1)

    def _build_entries(self) -> None:
        """The timestamped note, placed by `_build_controls`, which runs after it."""
        controls = self.text["controls"]
        self.note = line_edit()
        self.note.setPlaceholderText(controls["note"])
        # Interval from `set_note_saved_s`; the window's tests leave it at 0, which restores
        # the placeholder on the next pass of the event loop.
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(lambda: self.note.setPlaceholderText(controls["note"]))
        self.note_button = button(controls["add_note"])
        self.note_button.clicked.connect(self._enter_note)
        self.note.returnPressed.connect(self._enter_note)

        self.entries = QHBoxLayout()
        self.entries.setSpacing(0)
        self.entries.addWidget(self.note, 1)
        self.entries.addWidget(self.note_button)

    # -- placement ---------------------------------------------------------------------

    def place(self, screens: dict) -> None:
        """Put the window maximised on `screens.experimenter_screen_index`.

        Maximised rather than fullscreen, because the experimenter's dialogs open over it. A
        null index leaves it where the system puts it, which is right for a development machine
        and warns at startup (open item 9), as for the participant window.
        """
        index = screens["experimenter_screen_index"]
        if index is None:
            return
        available = QGuiApplication.screens()
        if not 0 <= index < len(available):
            raise IndexError(
                f"hardware.yaml: screens.experimenter_screen_index is {index}, but this "
                f"machine has {len(available)} screen(s)"
            )
        self.setGeometry(available[index].availableGeometry())
        self.showMaximized()

    # -- pushed in by the protocol ------------------------------------------------------

    def set_instruction(self, text: str, heading: str | None = None,
                        wait_s: float | None = None) -> None:
        """What to do now (SPEC.md 11), under its heading: `NOW`, act; `PREPARE`, get ready;
        `WAIT`, nothing to do yet (S, 21 Oct 2026). Every instruction says which, so it is
        never left to the wording. A wait shows its time left: `wait_s` if the step counts it
        itself -- a series' interval, set again as it runs down, under "Prepare" for its last
        seconds -- else the countdown to the next scheduled step, while one is pending.
        Formatted by the caller from the experimenter text.

        Clears the zone diagram's target: a new instruction is a new step, and a stimulus
        location left over from the last one would point at the wrong place. A step that
        places a stimulus calls `set_target` after this.
        """
        assert (heading in HEADINGS) if text else heading is None, (
            f"the instruction {text!r} has the heading {heading!r}; one of {HEADINGS}"
        )
        self._instruction_text = text
        self._heading = heading
        self._wait_s = wait_s if heading in (WAIT, PREPARE) else None
        self._draw_heading()
        self._fit_text()
        self.set_target(None)

    @property
    def heading(self) -> str | None:
        """The heading of what is up now (`set_instruction`), None with nothing up."""
        return self._heading

    def set_progress(self, text: str) -> None:
        """How far the step under way has got, "x/N" wherever the count is known (S, 21 and
        22 Oct 2026), "" for none. The heading beside it is fitted again to the room left."""
        self.progress.setText(text)
        self._set_alert(self.alert.text(), self.alert.styleSheet())

    def set_count(self, done: int, total: int) -> None:
        """`done` of `total`, beside the heading: the one under way, or for a run of ratings
        those answered, as its instruction counts them."""
        self.set_progress(self.text["status"]["progress"].format(done=done, total=total))

    def _draw_heading(self) -> None:
        """The heading, on the line over the instruction while the session runs."""
        if self._interruption is not None or self._link_lost:
            return
        self._set_alert(*self._heading_line())

    def _set_alert(self, text: str, style: str) -> None:
        """The line over the instruction, fitted to its one line when its text or the room
        for it changes: `refresh` redraws it every tick."""
        width = (self.width() - 2 * MARGIN_PX - ITEM_GAP_PX
                 - self.progress.sizeHint().width())
        if (text, width) != self._alert_fitted:
            self._alert_fitted = (text, width)
            _fit_to(self.alert, text, ALERT_SIZES, width, self.alert.height())
        _restyle(self.alert, style)

    def _heading_line(self) -> tuple[str, str]:
        words = self.text["headings"]
        if self._heading is None:
            return "", ""
        wait_s = self._wait_s
        event = self._next_event
        if self._heading == WAIT and wait_s is None and event is not None:
            wait_s = event["due_in_s"] if event["due_in_s"] > 0 else None
        counted = {WAIT: WAIT_FOR, PREPARE: PREPARE_FOR}
        text = (words[counted[self._heading]].format(time=clock_text(math.ceil(wait_s)))
                if wait_s is not None else words[self._heading])
        colour = {NOW: TARGET_COLOUR, PREPARE: FOREGROUND, WAIT: SECONDARY}[self._heading]
        return text, emphasis_style(colour)

    def set_status(self, text: str) -> None:
        """Whether the response has been received (SPEC.md 11) -- never what it was.

        While it says the participant is awaited, how long is counted, and past
        `vas.no_response_warning_s` the wait is shown and warned of, and `no_response` is
        emitted for the log (review of N7.F16: the setting was read by nothing)."""
        awaiting = text == self.text["instructions"]["await_participant"]
        if awaiting and self._status_raw != text:
            self._awaited_since_s = time.monotonic()
        elif not awaiting:
            self._awaited_since_s = None
            if self._no_response_shown is not None:
                self.clear_warning(self._no_response_shown)
                self._no_response_shown = None
        self._status_text = self._status_raw = text
        self._fit_text()

    def set_no_response_s(self, seconds: float) -> None:
        self._no_response_s = seconds

    def set_note_saved_s(self, seconds: float) -> None:
        self._note_timer.setInterval(round(seconds * MS_PER_S))

    def _check_response_wait(self) -> None:
        if self._awaited_since_s is None or self._no_response_s is None:
            return
        waited_s = time.monotonic() - self._awaited_since_s
        if waited_s < self._no_response_s:
            return
        self._status_text = self.text["status"]["awaited_for"].format(
            status=self.text["instructions"]["await_participant"], time=clock_text(waited_s))
        if self._no_response_shown is None:
            self._no_response_shown = self.text["warnings"]["no_response"].format(
                value=f"{self._no_response_s:g}")
            self.set_warning(self._no_response_shown)
            self.no_response.emit(waited_s)

    def set_warning(self, text: str) -> None:
        """A warning, under the status in the same region, in the warning colour.

        Apart from the status, which the routine "Waiting for..." / "Response received"
        replace every few seconds: a warning set there was gone before it was read (15 Oct
        2026 pilot review). It stays until `clear_warning`, or until a second stage has begun
        after it (`new_stage`).
        """
        self._warning_text = text
        self._warning_stages = 0
        self._fit_text()

    def clear_warning(self, text: str | None = None) -> None:
        """Clear the warning; given `text`, only if that is the one shown, so whatever raised a
        warning can withdraw it without taking down another's."""
        if text is not None and text != self._warning_text:
            return
        self._warning_text = ""
        self._fit_text()

    def new_stage(self) -> None:
        """A stage of the session has begun. The status belonged to the stage before -- its
        "Response received" was still up as pre-sensitisation began (S, 20 Oct 2026; LOG
        N7.F16c) -- so it goes. A warning survives the first stage start after it, because
        several are raised as a stage ends, and is cleared at the second. A distance's
        confirmation goes too; a query waiting to be answered stays (UI_PRINCIPLES.md 5.15)."""
        self.set_status("")
        # The count belonged to the stage before, as the status did.
        self.set_progress("")
        self.distances.clear_confirmation()
        if not self._warning_text:
            return
        self._warning_stages += 1
        if self._warning_stages > WARNING_STAGES:
            self.clear_warning()

    def set_target(self, region: str | None, site: int | None = None,
                   filament: bool = False, path: str | None = None,
                   brush: bool = False) -> None:
        """Where the current stimulus goes, on the zone diagram beside the instruction (SPEC.md
        11): the zone, and the `site` in it or the mapping's `path` (S, 21 Oct 2026).

        `filament` shows the monofilament technique under the instruction; `brush` draws the
        brush's sites rather than a filament's (S, 22 Oct 2026).
        """
        self.zone.set_target(region, site, path, brush)
        if (region is not None) != self.zone.isVisibleTo(self):
            self.zone.setVisible(region is not None)
            self._fitted = None
            self._fit_text()
        technique = region is not None and filament
        if technique:
            self.detail.setText(self.text["instructions"]["monofilament"])
        if technique or self.detail.text() == self.text["instructions"]["monofilament"]:
            self.detail.setVisible(technique)

    def set_sites_in_use(self, region: str, count: int | None) -> None:
        """How many of `region`'s sites the series under way uses, for the diagram; None, all
        the figure has."""
        self.zone.set_sites_in_use(region, count)

    def set_detail(self, text: str) -> None:
        """Small print under the status: what was saved, and how to upload it, at the end."""
        self.detail.setText(text)
        self.detail.setVisible(bool(text))

    def set_stage_plan(self, plan: dict[str, list[tuple[str, str, str]]]) -> None:
        """Each phase's steps in order, (id, short label, full name), for the row under the
        phases. The schedule's, the same in every condition."""
        self._stage_plan = dict(plan)

    def set_stage(self, group: str, stage_id: str) -> None:
        """The step under way, in the phase whose steps `group` names."""
        if group != self._stage_group:
            self._stage_group = group
            self.stages.set_phases(self._stage_plan[group])
        self.stages.set_current(stage_id)
        self.stages.setVisible(True)

    def set_filaments(self, labels: Sequence[str]) -> None:
        """The filaments, by gram label and lightest first, that Correct last application…
        offers as applied instead: the set's, never free text (S, 21 Oct 2026), less the one
        already recorded as applied."""
        self._filaments = list(labels)

    def show_substitution(self, text: str, kind: str) -> None:
        """What became of the filament applied instead, beside it: `CONFIRMED` or `QUERIED`
        (S, 21 Oct 2026). Up until the next application starts (`set_actions_enabled`)."""
        colour = TARGET_COLOUR if kind == CONFIRMED else WARNING_COLOUR
        _restyle(self.substitution_message, f"color: {colour};")
        self.substitution_message.setText(text)
        self.substitution_message.setToolTip(text)
        self._apply_enabled()

    def set_actions_enabled(
        self,
        *,
        rebalance: bool | None = None,
        fit_decision: bool | None = None,
        fit_accept: bool | None = None,
        fit_rerun: bool | None = None,
        discard: bool | None = None,
        skip_calibration: bool | None = None,
        substitution: bool | None = None,
        closed: bool | None = None,
        recalibrate_rebalance: bool | None = None,
        recalibrate_restart: bool | None = None,
        recalibration_used: bool | None = None,
    ) -> None:
        """What the running procedure waits for (SPEC.md 9, 11, 11.1). None leaves it as is.

        `rebalance` offers the calibration's own rematch; `fit_decision` offers Accept and
        Re-run, and `fit_accept` or `fit_rerun` one of them where the other would be refused
        (review of N7.F16: a choice offered and then refused is a dead control);
        `discard` and `substitution` offer the two corrections of the last application,
        Discard and repeat and the filament applied instead, through Correct last
        application…, which is offered while either is; an offer of the filament takes down
        the last correction's message (S, 21 Oct 2026: it lingered into the next application).
        `skip_calibration` offers Skip calibration, which exists only on a pilot rig. Each is
        hidden, in a place
        kept for it, when not offered, because a control that does nothing when pressed is one
        the experimenter learns to distrust (UI_PRINCIPLES.md 5.1), and ten of them are a lot
        to look at.
        `closed` is the session closed and its files written (docs/LOG.md N7.F11c9): Pause
        and the garment button are withdrawn, since nothing is left to pause and the garment,
        disconnected by the close, is not to be connected again with no stop wired to it.
        `recalibrate_rebalance` and `recalibrate_restart` say which re-calibrations can be
        taken (docs/LOG.md N7.F12a1); Re-calibrate… is offered while either can, while running
        or stopped but not paused, and its dialog offers only those, and neither while the
        procedure offers its own rematch, nor Restart beside its Re-run (`_recalibrations`);
        `recalibration_used` says, while stopped, that the limit is reached.
        """
        if substitution and not self._awaiting["substitution"]:
            self.substitution_message.setText("")
        if fit_decision is not None:
            fit_accept = fit_rerun = fit_decision
        for key, value in (("rebalance", rebalance), ("fit_accept", fit_accept),
                           ("fit_rerun", fit_rerun),
                           ("discard", discard), ("skip_calibration", skip_calibration),
                           ("substitution", substitution), ("closed", closed),
                           ("recalibrate_rebalance", recalibrate_rebalance),
                           ("recalibrate_restart", recalibrate_restart),
                           ("recalibration_used", recalibration_used)):
            if value is not None:
                self._awaiting[key] = bool(value)
        self._apply_enabled()

    def offer_alternative(self, label_text: str | None) -> None:
        """Offer a step's other answer on a button of its own, labelled with what it does;
        None withdraws it. Next step stays the way forward: it never means "no" (review of
        N7.F16: in the masking check, the stop rehearsal and an undefined gain it did)."""
        self._alternative = label_text
        if label_text is not None:
            self.alternative_button.setText(label_text)
        self._apply_enabled()

    @staticmethod
    def _keyed(text: str, key: str) -> str:
        return f"{text}{KEY_HINT_SEPARATOR}[{key}]"

    def set_mapping_phases(self, phases: Sequence[str]) -> None:
        """The time points that have a mapping, in session order (SPEC.md 8.4): a row each in
        the distances box, from the first mapping on."""
        phases = list(phases)
        if phases == self._mapping_phases:
            return
        self._mapping_phases = phases
        self.distances.set_phases(phases)
        self._apply_enabled()

    # -- the fit preview, SPEC.md 11.1 ---------------------------------------------------

    def show_fit_preview(self, fit) -> None:
        """Open the fit preview on an `F40Fit` or a `FitReady`. Which of Accept and Re-run it
        offers is the procedure's (`set_actions_enabled`): enabled here, both came back on
        over a procedure that had withheld one (code review of N7.F17e).

        Refused unless the view says the preview is enabled: a fit carries the participant's
        ratings, and this is the only place they could reach the lab screen.
        """
        if not self.read_view()["fit_preview_enabled"]:
            raise FitPreviewRefused(
                "a fit was handed to the experimenter window with fit_preview.enabled false"
            )
        self.fit_preview.draw(fit)
        # At the window's right, over the side column, where it hides the least of the
        # instruction -- not centred over it (review of N7.F16).
        corner = self.mapToGlobal(QPoint(self.width() - MARGIN_PX, MARGIN_PX))
        self.fit_preview.move(corner.x() - self.fit_preview.width(), corner.y())
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
        made = ReasonDialog(
            controls["fit_rerun"],
            dialogs["fit_rerun_reason"],
            "",
            controls["fit_rerun"],
            controls["cancel"],
            parent=self,
        )
        # Enter confirms once a reason is typed, as it saves a note (review of N7.F16). Not
        # the abort, which ends the session and is confirmed only by a click.
        made.confirm.setDefault(True)
        return made

    def _recalibrations(self) -> list[str]:
        """The re-calibrations Re-calibrate… offers now: each one that can be taken, but
        Restart not while the procedure offers its own Re-run, which does the same without
        counting against the limit (docs/LOG.md N7.F12a1)."""
        rerunning = self._interruption is None and self._awaiting["fit_rerun"]
        return [choice for choice in RECALIBRATIONS
                if self._awaiting[f"recalibrate_{choice}"]
                and not (choice == RECALIBRATE_RESTART and rerunning)]

    def recalibration_dialog(self) -> ActionChoiceDialog:
        """What to repeat, each choice saying which steps it runs again, and why, from a fixed
        list (docs/LOG.md N7.F12a1; S, 21 Oct 2026). Only what can be taken now is offered.
        The same in every condition, wherever it is offered."""
        controls, dialogs = self.text["controls"], self.text["dialogs"]
        offered = self._recalibrations()
        return ActionChoiceDialog(
            controls["recalibrate"],
            dialogs["recalibrate"],
            dialogs["recalibrate_what"],
            {choice: dialogs["recalibrate_choices"][choice] for choice in offered},
            dialogs["recalibrate_choices_detail"],
            dialogs["recalibration_reason"],
            dialogs["recalibration_reasons"],
            controls["recalibrate_confirm"],
            controls["cancel"],
            parent=self,
        )

    def error_dialog(self, message: str) -> MessageDialog:
        dialogs = self.text["dialogs"]
        return MessageDialog(
            dialogs["error"], message, dialogs["close"], colour=DISCONNECTED_COLOUR, parent=self
        )

    def open_abort_dialog(self) -> ReasonDialog:
        # Paused first, so the garment is at zero and nothing runs on behind the dialog while
        # a reason is typed; Cancel leaves the session paused (review of N7.F16).
        if self._interruption is None and not self._awaiting["closed"]:
            self.pause_requested.emit()
        dialog = self.abort_dialog()
        dialog.accepted.connect(lambda: self.abort_requested.emit(dialog.reason_text()))
        dialog.open()
        return dialog

    def open_rerun_dialog(self) -> ReasonDialog:
        dialog = self.rerun_dialog()
        dialog.accepted.connect(lambda: self.fit_rerun_requested.emit(dialog.reason_text()))
        dialog.open()
        return dialog

    def open_recalibration_dialog(self) -> ActionChoiceDialog:
        dialog = self.recalibration_dialog()
        dialog.accepted.connect(
            lambda: self.recalibration_requested.emit(dialog.action(), dialog.choice())
        )
        dialog.open()
        return dialog

    def show_error(self, message: str) -> MessageDialog:
        dialog = self.error_dialog(message)
        dialog.open()
        return dialog

    # -- the entries ---------------------------------------------------------------------

    def set_timeline(self, phases: Sequence[str]) -> None:
        """The session's phases in order, as keys of the experimenter text's `phases`, for the
        timeline across the top (LOG N7.F16h). The same list in every condition."""
        names, short = self.text["phases"], self.text["timeline"]
        self.timeline.set_phases([(phase, short[phase], names[phase]) for phase in phases])
        # The timeline names the current phase in full, in the phase's own place; the label
        # keeps its text for whatever reads it.
        self.phase.setVisible(False)
        self._phase_stretch.setVisible(False)
        self.countdown.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.phase_row.setStretch(self._phase_countdown, COUNTDOWN_SHARE)
        self.timeline.setVisible(True)
        self.refresh()

    def set_garment(self, channels: Sequence[int], ceiling_kpa: float,
                    per_channel_pressure: bool, highlight_s: float) -> None:
        """The garment's channels, for the channel display in the side column (LOG
        N7.F16i). Once, before the session starts."""
        assert self.garment_display is None, "the garment display is set once"
        self.garment_display = GarmentDisplay(channels, ceiling_kpa, per_channel_pressure,
                                              self.text["hardware"], highlight_s)
        self.garment_display.setVisible(False)
        self._garment_slot.addWidget(self.garment_display)
        self.refresh()

    def add_demo_panel(self, panel: QWidget) -> None:
        """A demonstration's controls, along the foot of the window (tatp/demo.py; S, 20 Oct
        2026: "the demo controls should be integrated into the main window")."""
        self._layout.addSpacing(ITEM_GAP_PX)
        self._layout.addWidget(panel)
        # The session's window at the lab screen's size, and the demonstration's own panel
        # under it, which a session does not have: the cap grows by the panel, never clips it.
        self.setMaximumHeight(LAB_SCREEN_HEIGHT_PX + ITEM_GAP_PX
                              + panel.minimumSizeHint().height())

    def set_proceed_source(self, awaited: Callable[[], bool]) -> None:
        """Ask `awaited()` whether a press of Next step would do anything now (the rig's
        `proceed_awaited`). Next step is offered only then: a button that is pressed and does
        nothing teaches the experimenter to distrust it (S, 20 Oct 2026; UI_PRINCIPLES.md 5.1).
        It returns only a yes or no, the same in every condition (SPEC.md 16)."""
        self._proceed_awaited = awaited
        self._apply_enabled()

    def _proceed_key(self) -> None:
        """Space. A button or a list that has the focus keeps Space's own meaning -- press
        it, open it -- so Space on the demo's Skip never launches a step (code review of
        N7.F16d). Otherwise Next step, at once: an animated click would emit its press about
        100 ms late, and an application's time is that press (N7.F16f). The button is shown
        down for a moment, so the press is seen."""
        focus = QApplication.focusWidget()
        if isinstance(focus, QAbstractButton) and focus is not self.proceed_button:
            focus.click()
            return
        if isinstance(focus, QComboBox):
            focus.showPopup()
            return
        if not (self.proceed_button.isVisible() and self.proceed_button.isEnabled()):
            return
        self.proceed_button.setDown(True)
        QTimer.singleShot(PRESS_SHOWN_MS, self, lambda: self.proceed_button.setDown(False))
        self._proceed_clicked()

    def _proceed_clicked(self) -> None:
        self.proceed_requested.emit()
        # What the press started has run by now: offered again only if a go is still awaited,
        # so a double press never lands on the step after.
        self._apply_enabled()

    def correction_dialog(self) -> CorrectionDialog:
        """What was wrong with the application just given: another filament, or discard and
        repeat it (S, 22 Oct 2026); each only while it can be taken, Discard listed greyed
        otherwise."""
        controls, dialogs = self.text["controls"], self.text["dialogs"]
        filaments = ({label_g: controls["substitution_option"].format(filament=label_g)
                      for label_g in self._filaments}
                     if self._awaiting["substitution"] else {})
        return CorrectionDialog(
            controls["correct_application"], dialogs["correction"],
            dialogs["correction_filament"], filaments,
            controls["discard_repeat"], dialogs["correction_discard"],
            self._awaiting["discard"],
            controls["correction_confirm"], controls["cancel"], parent=self,
        )

    def open_correction_dialog(self) -> CorrectionDialog:
        """Asked in a dialog, so one slip of the mouse records nothing (LOG N7.F17e). What is
        chosen goes only if still offered when confirmed: the procedure may have moved on, and
        then the line beside the control says nothing was recorded."""
        dialog = self.correction_dialog()

        def chosen() -> None:
            action, filament = dialog.choice()
            if action == CORRECT_FILAMENT and self._awaiting["substitution"]:
                self.substitution_entered.emit(filament)
            elif action == CORRECT_DISCARD and self._awaiting["discard"]:
                self.discard_requested.emit()
            else:
                # Not recorded, but not lost without trace: it was what the experimenter
                # meant to say about the application (spec review of N7.F18y).
                self.correction_refused.emit(f"{action} {filament}".strip())
                self.show_substitution(self.text["warnings"]["correction_too_late"], QUERIED)

        dialog.accepted.connect(chosen)
        # One owner, released once answered (CLAUDE.md lesson 3).
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.open()
        return dialog

    def disconnect_dialog(self) -> MessageDialog:
        controls = self.text["controls"]
        return MessageDialog(controls["disconnect"], self.text["dialogs"]["disconnect_confirm"],
                             controls["disconnect"], controls["cancel"], parent=self)

    def _garment_clicked(self) -> None:
        if self._connected:
            # Asked first, in every phase alike, so the asking says nothing about the touch
            # (SPEC.md 16): a single click stopped it (review of N7.F16).
            dialog = self.disconnect_dialog()
            dialog.accepted.connect(self.garment_disconnect_requested.emit)
            dialog.open()
        else:
            self.garment_connect_requested.emit()

    def _enter_note(self) -> None:
        note = self.note.text().strip()
        if note:
            self.note_entered.emit(note)
            self.note.clear()
            # Written: Space is Next again (S, 22 Oct 2026).
            self.setFocus()

    def confirm_note(self, time_text: str) -> None:
        """The note is in the log. Said in the emptied field, where the eye already is, so
        nothing on the screen moves (S, 15 Oct 2026 pilot). Taken back after
        `note_saved_shown_s`, so it is never left up hours later (review of N7.F16)."""
        self.note.setPlaceholderText(self.text["controls"]["note_saved"].format(time=time_text))
        self._note_timer.start()

    # -- read from the session ----------------------------------------------------------

    def refresh(self) -> None:
        """Redraw from `Session.experimenter_view()`. The only way session state gets here."""
        view = self.read_view()
        text = self.text

        # SPEC.md 12.4: persistent and unmissable while they apply, absent when they do not.
        shown = (bool(view["demo"]), bool(view["placeholder_text"]),
                 bool(view["reduced_capability_device"]), bool(view["fit_preview_enabled"]))
        items = view["unresolved_open_items"]
        if self._banners_shown is None:
            self._banners_shown = shown
            # The open-items line keeps its place for the session if it starts with one, so
            # an item settled mid-session moves nothing.
            self._open_items_reserved = bool(items)
            if self._open_items_reserved:
                _reserve(self.open_items)
        # Stage boundary (CLAUDE.md): a banner arriving mid-session would move everything
        # below it, which the banner region no longer reserves room for.
        assert shown == self._banners_shown, (
            f"the banners changed during the session: {self._banners_shown} to {shown}"
        )
        assert self._open_items_reserved or not items, (
            "open items appeared during the session, where the banner region has no room"
        )
        garment_name = text["terms"]["garments"][view["garment_driver"]]
        self.reduced_capability_banner.setText(
            text["banners"]["reduced_capability"].format(value=garment_name)
        )
        self.reduced_capability_banner.setToolTip(
            text["banners"]["reduced_capability_detail"].format(value=garment_name)
        )
        for banner, visible in zip((self.demo_banner, self.placeholder_banner,
                                    self.reduced_capability_banner, self.fit_preview_banner),
                                   shown, strict=True):
            banner.setVisible(visible)
        self.banner_area.setVisible(any(shown) or self._open_items_reserved)

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
        self.timeline.set_current(view["phase"])
        self.elapsed.setText(
            text["status"]["elapsed"].format(time=clock_text(view["elapsed_s"]))
        )
        # The figure is a right hand; a left one is its mirror image (S, 21 Oct 2026).
        self.zone.set_mirrored(view["limb"] == MIRRORED_LIMB)
        self._draw_countdown(view["next_event"])
        self._next_event = view["next_event"]
        self._draw_interruption(view["interruption"], bool(view["resuming"]),
                                bool(view["hardware"]["link_lost"]))
        self._draw_hardware(view["hardware"], view["phase"])

        # By number, so twenty open items still fit the line; the summaries are the tooltip,
        # and are printed at startup (config.OpenItem.__str__ is "[number] summary").
        numbers = []
        for item in items:
            number = ITEM_NUMBER.match(item)
            numbers.append(number[1] if number else item)
        self._open_items_text = (
            text["warnings"]["open_items"].format(value=", ".join(numbers)) if items else ""
        )
        self.open_items.setToolTip(LINE_SEPARATOR.join(items))
        self.open_items.setVisible(bool(items))
        self._check_response_wait()
        self._fit_text()
        self._apply_enabled()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_text()

    def _left_width(self) -> int:
        """The instruction's width, from the window's: known before the first layout. Less the
        zone diagram beside it, while it is shown."""
        width = self.width() - 2 * MARGIN_PX - GROUP_GAP_PX - SIDE_COLUMN_PX
        if self.zone.isVisibleTo(self):
            width -= self.zone.width() + GROUP_GAP_PX
        return width

    def _status_width(self) -> int:
        """The width of the lines under the instruction: the whole column."""
        return self.width() - 2 * MARGIN_PX - GROUP_GAP_PX - SIDE_COLUMN_PX

    def _fit_text(self) -> None:
        """Fit the instruction and the status to their regions, stepping down the scale, and
        the open-items line to the window's width.

        Only when a text or the width has changed: `refresh()` runs on a timer, and measuring
        wrapped text at up to four sizes every tick is work that changes nothing.
        """
        width = self._left_width()
        wanted = (self._instruction_text, self._status_text, self._warning_text,
                  self._interruption, self._open_items_text, width, self.width())
        if wanted == self._fitted:
            return
        self._fitted = wanted
        # One line across the window; cut with an ellipsis, so a cut list says it is cut. The
        # whole list is the tooltip.
        self.open_items.setText(self.open_items.fontMetrics().elidedText(
            self._open_items_text, Qt.ElideRight, self.width() - 2 * MARGIN_PX
        ))
        _fit_to(self.instruction, self._instruction_text, INSTRUCTION_SIZES, width,
                self.instruction.height())
        # The status, then any warning, each on a line of its own; the warning in the warning
        # colour, so it is told from the status before it is read (UI_PRINCIPLES.md 3.2). What
        # does not fit gives way in that order: the routine status, which the next one
        # replaces anyway; never the warning (UI_PRINCIPLES.md 3.1). While interrupted the
        # whole region is dimmed with the step it belongs to (`_draw_interruption`), the
        # warning's own colour included, so the stop line stays the brightest thing in its
        # place.
        width = self._status_width()
        lines = [escape(text, quote=False) for text in (self._status_text,) if text]
        if self._warning_text:
            colour = WARNING_COLOUR if self._interruption is None else DISABLED
            lines.append(f'<span style="color: {colour};">'
                         f'{escape(self._warning_text, quote=False)}</span>')
        self.status.setTextFormat(Qt.RichText)
        height = self.status.height()
        while True:
            _fit_to(self.status, RICH_LINE_BREAK.join(lines), STATUS_SIZES, width, height)
            if len(lines) <= 1 or self.status.heightForWidth(width) <= height:
                break
            lines.pop(0)

    def _draw_countdown(self, event: dict | None) -> None:
        """SPEC.md 7.4: the software counts down, the experimenter launches.

        Calm until the step is near: the countdown in grey, then within the due alert's lead
        in amber, then "due now" in bold amber. Once it is late, how late is beside the session
        clock, amber, and red only past the overdue alert's margin (S, 21 Oct 2026: "Block 1
        (pinprick) is OVERDUE" in red was alarming)."""
        status = self.text["status"]
        if event is None:
            self.countdown.setText("")
            self.behind.setText("")
            return
        is_block = event["kind"] == BLOCK
        name = event_name(self.text, event)
        if is_block:
            block_type = self.text["terms"]["block_types"][event["block_type"]]
        due_in_s = event["due_in_s"]
        if due_in_s > 0:
            time_left = clock_text(math.ceil(due_in_s))
            if event["due_soon"]:
                shown = (
                    status["block_due_soon"].format(block=event["block_index"],
                                                    type=block_type, time=time_left)
                    if is_block
                    else status["event_due_soon"].format(phase=name, time=time_left)
                )
                style = f"color: {WARNING_COLOUR};"
            else:
                shown = status["next_event"].format(phase=name, time=time_left)
                style = f"color: {SECONDARY};"
            self.behind.setText("")
        else:
            shown = (
                status["block_due"].format(block=event["block_index"], type=block_type)
                if is_block
                else status["event_due"].format(phase=name)
            )
            style = emphasis_style(WARNING_COLOUR)
            late_s = math.floor(-due_in_s)
            self.behind.setText(status["behind_schedule"].format(time=clock_text(late_s))
                                if late_s else "")
            _restyle(self.behind, emphasis_style(
                DISCONNECTED_COLOUR if event["overdue"] else WARNING_COLOUR))
        self.countdown.setText(shown)
        self.countdown.setStyleSheet(style)
        if self.timeline.isVisibleTo(self):
            # Its third of the row, at the largest size that holds it on one line. From the
            # window's width, as the instruction's is: known before the first layout.
            room = (self.width() - 2 * MARGIN_PX - GROUP_GAP_PX) * COUNTDOWN_SHARE // (
                TIMELINE_SHARE + COUNTDOWN_SHARE)
            for size in COUNTDOWN_SIZES:
                font = self.countdown.font()
                set_points(font, size)
                font.setBold("bold" in style)
                if QFontMetrics(font).horizontalAdvance(shown) <= room:
                    break
            sized(self.countdown, size)

    def set_rehearsal(self, rehearsing: bool) -> None:
        """The stop rehearsal is waiting for its stop (SPEC.md 10.9): a stop then is the one
        expected, said calmly, with the instruction for it at full strength -- not the alarm
        of an unexpected stop (review of N7.F16)."""
        self._rehearsing = rehearsing
        self.refresh()

    def _draw_interruption(self, interruption: str | None, resuming: bool,
                           link_lost: bool) -> None:
        assert interruption is None or interruption in INTERRUPTIONS, interruption
        # The participant is not awaited while the session is stopped or paused: the wait for
        # their answer starts again at the resume (code review of N7.F17e: it ran on through a
        # pause, and a resumed trial carried the old start). Real seconds throughout, as a
        # person's answer takes them at any clock speed.
        if interruption is not None and self._interruption is None:
            self._awaited_since_s = None
            if self._no_response_shown is not None:
                self.clear_warning(self._no_response_shown)
                self._no_response_shown = None
            self._status_text = self._status_raw
        elif (interruption is None and self._interruption is not None
              and self._status_raw == self.text["instructions"]["await_participant"]):
            self._awaited_since_s = time.monotonic()
        self._interruption = interruption
        self._resuming = resuming
        status = self.text["status"]
        expected = self._rehearsing and interruption == EMERGENCY_STOP
        # While interrupted the step on screen is on hold, so it is dimmed and the stop line
        # is the brightest thing in its place -- except the rehearsal's expected stop, whose
        # instruction is the one to follow. Colour only: nothing moves (UI_PRINCIPLES.md 3.3).
        running = interruption is None or expected
        _restyle(self.instruction, f"color: {FOREGROUND if running else SECONDARY};")
        _restyle(self.status, f"color: {SECONDARY if running else DISABLED};")
        _restyle(self.detail, f"color: {SECONDARY if running else DISABLED};")
        if link_lost:
            # In the alert row, red, as a stop is: the outputs may still be on (N7.U16), and
            # small print in the side column was easily missed (review of N7.F16). First, over
            # a stop's line too, which is when it matters most.
            text = self.text["hardware"]["link_lost"]
            style = emphasis_style(DISCONNECTED_COLOUR)
        elif interruption is not None and resuming:
            # The resume was pressed and its cue is playing: said, so it is not pressed again.
            text, style = status["resuming"], emphasis_style(TARGET_COLOUR)
        elif expected:
            text = status["rehearsal_stop"].format(controls=self.text["controls"])
            style = emphasis_style(TARGET_COLOUR)
        elif interruption is not None:
            # Resume by the label its button carries. The stop is the participant's and is
            # red; a pause is the experimenter's own and amber.
            text = status[f"interrupted_{interruption}"].format(controls=self.text["controls"])
            colour = DISCONNECTED_COLOUR if interruption == EMERGENCY_STOP else WARNING_COLOUR
            style = emphasis_style(colour)
        else:
            text, style = self._heading_line()
        self._link_lost = link_lost
        self._set_alert(text, style)

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
        # No channels means no display at all -- never a placeholder that says something is
        # being withheld, which would itself tell the experimenter the phase matters (SPEC.md
        # 16). A demonstration feeds the display itself, in every phase (tatp/demo.py).
        display = self.garment_display
        if display is not None and not self.garment_fed_elsewhere:
            pressures = hardware["channel_pressure_kpa"]
            channels_on = hardware["channels_on"]
            withheld = pressures is None or channels_on is None or phase in BLINDED_PHASES
            if not withheld:
                display.show_states(
                    {channel: (channel in channels_on,
                               pressures.get(channel, 0.0) if display.per_channel_pressure
                               else None)
                     for channel in display.channels},
                    bool(hardware["link_lost"]),
                )
            display.setVisible(not withheld)
        # That there is a fault is shown; which channel is not, if it arose while the
        # condition's own pattern was running, because the channels in use differ by condition
        # (SPEC.md 16). A fault seen then stays withheld for the rest of the session: showing
        # it in full after the rekindle would reveal it just the same. The data has the detail.
        words = self.text["hardware"]
        if phase in BLINDED_PHASES:
            self._withheld_faults.update(hardware["faults"])
        withheld = [fault for fault in hardware["faults"] if fault in self._withheld_faults]
        shown = [fault for fault in hardware["faults"] if fault not in self._withheld_faults]
        lines = []
        if hardware["link_lost"]:
            # The warning itself is in the alert row (`_draw_interruption`); here the newest
            # fault keeps its start, the counts giving way: they stay in the tooltip and data.
            if shown:
                lines.append(words["fault"].format(value=shown[-1]))
            elif withheld:
                lines.append(words["fault_withheld"].format(value=len(withheld)))
        else:
            if withheld:
                lines.append(words["fault_withheld"].format(value=len(withheld)))
            if len(shown) > 1:
                lines.append(words["faults_earlier"].format(value=len(shown) - 1))
            if shown:
                lines.append(words["fault"].format(value=shown[-1]))
        self.faults.setText(LINE_SEPARATOR.join(lines))
        self.faults.setToolTip(LINE_SEPARATOR.join(words["fault"].format(value=fault)
                                                   for fault in shown))
        self.faults.setVisible(bool(lines))

    def _apply_enabled(self) -> None:
        """Which controls are offered now. Read from the view where it says, else pushed in.

        While the session is interrupted, Resume and Abort are the only ways forward, so they
        are the only controls offered besides the entries (SPEC.md 13), with the two
        re-calibrations after a stop where touch is calibrated or delivered (docs/LOG.md
        N7.F12a1). Next step stays in sight, greyed, because it is the way forward again after
        the resume (LOG N7.U10a). A control not offered is hidden, and disabled too, so no key
        press reaches it.
        """
        running = self._interruption is None
        self.proceed_button.setEnabled(running and self._proceed_awaited())
        accepting = running and self._awaiting["fit_accept"]
        rerunning = running and self._awaiting["fit_rerun"]

        offering = running and self._alternative is not None
        rebalancing = running and self._awaiting["rebalance"]
        skipping = self._awaiting["skip_calibration"]
        substituting = self._awaiting["substitution"]
        stopped = self._interruption == EMERGENCY_STOP
        mapped = bool(self._mapping_phases)
        open_ = not self._awaiting["closed"]
        # Not while paused: the pause is the experimenter's own, and Resume ends it.
        # Not while the calibration offers its own rematch either, which has its place.
        recalibrating = ((running or stopped) and open_ and not rebalancing
                         and bool(self._recalibrations()))
        # The choice stays in sight with its message until the next application offers it
        # afresh, so what became of the last one can still be read (S, 21 Oct 2026).
        correcting = substituting or self._awaiting["discard"]
        # (widget, shown, pressable). Skip calibration stays in sight through an
        # interruption, as it was, but cannot be pressed then.
        offered = (
            (self.pause_button, running and open_, running and open_),
            (self.garment_button, open_, open_),
            # Not once closed: an abort ran again on a closed session (code review of N7.F17e).
            (self.abort_button, open_, open_),
            (self.resume_button, not running and not self._resuming,
             not running and not self._resuming),
            (self.alternative_button, offering, offering),
            (self.rebalance_button, rebalancing, rebalancing),
            (self.fit_accept_button, accepting, accepting),
            (self.fit_rerun_button, rerunning, rerunning),
            (self.recalibrate_button, recalibrating, recalibrating),
            (self.skip_button, skipping, running and skipping),
            (self.correct_button, correcting, running and correcting),
            (self.substitution_message, correcting or bool(self.substitution_message.text()),
             True),
            (self.distances, mapped, mapped),
        )
        focus = QApplication.focusWidget()
        for widget, shown, pressable in offered:
            # Hiding or disabling the control that has the focus makes Qt pass it to the next
            # one -- after Pause, that is Abort, so a Space press would open the abort dialog.
            # The window takes it instead: neither a control nor a text field, which under
            # `any_keyboard` would take the participant's remote keys (docs/LOG.md N7.I1).
            holds = focus is not None and (focus is widget or widget.isAncestorOf(focus))
            if holds and not (shown and pressable):
                self.setFocus()
            widget.setVisible(shown)
            widget.setEnabled(pressable)
        self.recalibration_used.setVisible(stopped and self._awaiting["recalibration_used"])
        self.fit_preview.accept_button.setVisible(accepting)
        self.fit_preview.accept_button.setEnabled(accepting)
        self.fit_preview.rerun_button.setVisible(rerunning)
        self.fit_preview.rerun_button.setEnabled(rerunning)
        # The way forward reads Finish session once the session is closed: it ends the program
        # (S, 21 Oct 2026).
        keys, controls = self.text["keys"], self.text["controls"]
        self.proceed_button.setText(self._keyed(
            controls["finish" if not open_ else "proceed"], keys["proceed"]))
        # Quiet while connected, the expected state; the way forward when it reads Connect.
        self.garment_button.setText(
            controls["disconnect" if self._connected else "connect"]
        )
        _restyle(self.garment_button,
                 f"QPushButton {{ color: {SECONDARY}; }}" if self._connected
                 else primary_button_style(SIZE_SMALL))


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


class DistancesBox(QWidget):
    """The mapping distances (SPEC.md 8.4), in the window, a column per mapped time point and
    a row per path (S, 21 Oct 2026: "embedded, not a separate window", "units displayed").
    Never blocking: entered whenever convenient.

    Enter in a field, or Save, emits `entered(phase, distances)` -- the window's
    `distances_entered` -- for each time point with a field changed since it was last sent,
    or the field Enter was pressed in, with None for any other. The ledger then says what
    became of each (`show_outcome`): a recorded field is outlined in the target colour, a
    queried one in amber, and the lines under the fields say what was recorded or why it is
    queried. A queried value is confirmed by entering it again -- Enter in its field -- so the
    fields keep what was typed. A column per time point means a distance is always
    typed against the time point it belongs to: one shared set of fields with a choice of time
    point kept the earlier one selected, and the post-intervention distances were entered as
    corrections to the post-sensitisation ones (S's demo, 21 Oct 2026).
    """

    def __init__(self, text: dict, entered: SignalInstance, parent: QWidget | None = None):
        super().__init__(parent)
        self.text = text
        self.entered = entered
        controls = text["controls"]
        self.title = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        self.title.setText(controls["distances_title"])
        # How to measure and enter them, on hover: the laptop has no line to spare for it.
        self.title.setToolTip(controls["distances_hint"])
        self.enter_button = button(controls["enter_distances"])
        self.enter_button.clicked.connect(self.enter)
        # `terms.mapping_paths` lists the paths in `mapping.path_ids` order; a test holds the
        # two in step, so the fields are in the order the ledger reads them.
        self.path_ids = list(text["terms"]["mapping_paths"])
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(ITEM_GAP_PX)
        # Close rows: the lab laptop's height is spent above them (UI_PRINCIPLES.md 5.21).
        self.grid.setVerticalSpacing(ITEM_GAP_PX // 2)
        # Save in the corner the rows and columns are named from.
        self.grid.addWidget(self.enter_button, 0, 0)
        for row, path_id in enumerate(self.path_ids, start=1):
            name = label(SIZE_SMALL, colour=SECONDARY)
            name.setText(text["terms"]["mapping_paths_short"][path_id])
            name.setToolTip(text["terms"]["mapping_paths"][path_id])
            self.grid.addWidget(name, row, 0)
        self.validator = QRegularExpressionValidator(QRegularExpression(DISTANCE_PATTERN), self)
        self.columns: dict[str, list[QLineEdit]] = {}
        # What each field last sent: only a field changed since, or the one Enter is pressed
        # in, is sent again, so a queried value is confirmed only by entering it again, never
        # by saving another time point's (review of N7.F18f).
        self._sent: dict[QLineEdit, str] = {}
        self.message = label(SIZE_SMALL, wrap=True)
        self.message.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.message.setFixedHeight(self.message.fontMetrics().lineSpacing()
                                    * DISTANCE_MESSAGE_LINES)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ITEM_GAP_PX)
        layout.addWidget(self.title)
        layout.addLayout(self.grid)
        layout.addWidget(self.message)

    def set_phases(self, phases: Sequence[str]) -> None:
        """A column for each time point with a mapping, in session order; one already there
        keeps what is typed in it."""
        for phase in phases:
            if phase in self.columns:
                continue
            column = len(self.columns) + 1
            name = label(SIZE_SMALL, colour=SECONDARY)
            name.setText(self.text["timeline"][phase])
            name.setToolTip(self.text["phases"][phase])
            self.grid.addWidget(name, 0, column)
            fields = []
            for row in range(1, len(self.path_ids) + 1):
                field = line_edit(SIZE_SMALL)
                field.setFixedWidth(DISTANCE_FIELD_PX)
                field.setValidator(self.validator)
                field.setPlaceholderText(self.text["distances"]["unit"])
                field.setToolTip(self.text["controls"]["distances_hint"])
                field.returnPressed.connect(self._enter_in_field)
                self.grid.addWidget(field, row, column)
                fields.append(field)
            self.columns[phase] = fields

    def fields(self, phase: str) -> list[QLineEdit]:
        """`phase`'s fields, in path order."""
        return self.columns[phase]

    def _enter_in_field(self) -> None:
        self.enter(self.sender())

    def enter(self, pressed_in: QLineEdit | None = None) -> None:
        """Emit, for each time point, the fields changed since they were last sent and the
        field Enter was `pressed_in`, None for any other or a blank. A time point with such a
        field that is not a number sends nothing, and that field is outlined in red."""
        for phase, fields in self.columns.items():
            values: list[float | None] = []
            valid = True
            for field in fields:
                typed = field.text().strip()
                if not typed or (field is not pressed_in
                                 and typed == self._sent.get(field, "")):
                    values.append(None)
                elif field.hasAcceptableInput():
                    values.append(float(typed.replace(DECIMAL_COMMA, DECIMAL_POINT)))
                else:
                    valid = False
                    field.setStyleSheet(f"border: 1px solid {DISCONNECTED_COLOUR};")
            if valid and any(value is not None for value in values):
                for field in fields:
                    self._sent[field] = field.text().strip()
                self.entered.emit(phase, tuple(values))
                # Sent: Space is Next again, as after a note (S, 22 Oct 2026).
                self.window().setFocus()

    def clear_confirmation(self) -> None:
        """Take down a confirmation; a query stays until it is answered."""
        if TARGET_COLOUR in self.message.styleSheet():
            self.message.setText("")
            self.message.setToolTip("")

    def show_fields(self, phase: str, recorded: Collection[int], queried: Collection[int],
                    awaited: Collection[int]) -> None:
        """`phase`'s fields as the ledger holds them, by path (1-based): recorded, queried, or
        walked and still awaited -- the last filled in the target colour until entered, so
        the eye is drawn to them while the marks are fresh (S, 22 Oct 2026)."""
        tint = QColor(TARGET_COLOUR)
        tint.setAlphaF(AWAITED_TINT_ALPHA)
        for path, field in enumerate(self.fields(phase), start=1):
            if path in queried:
                field.setStyleSheet(f"border: 1px solid {WARNING_COLOUR};")
            elif path in recorded:
                field.setStyleSheet(f"border: 1px solid {TARGET_COLOUR};")
            elif path in awaited:
                field.setStyleSheet(
                    f"border: {AWAITED_BORDER_PX}px solid {TARGET_COLOUR};"
                    f" background-color: {tint.name(QColor.HexArgb)};")
            else:
                field.setStyleSheet("")

    def show_outcome(self, phase: str, recorded: Collection[int], queried: Collection[int],
                     awaited: Collection[int], message: str, kind: str) -> None:
        """What the ledger made of the entry for `phase` (`show_fields`), and the line to
        show, `CONFIRMED` or `QUERIED`."""
        self.show_fields(phase, recorded, queried, awaited)
        colour = TARGET_COLOUR if kind == CONFIRMED else WARNING_COLOUR
        _restyle(self.message, f"color: {colour};")
        self.message.setText(message)
        self.message.setToolTip(message)
