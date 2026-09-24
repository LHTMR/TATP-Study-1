"""Components shared by the experimenter window and the launcher. SPEC.md 4, 11, 11.1.

Both are lab-side screens, so both follow the experimenter half of `docs/UI_PRINCIPLES.md`:
dark, one four-step type scale, and every string from `config/text/experimenter_*.yaml`. The
participant window shares none of this -- it is a stimulus display with rules of its own.

Nothing here reads a session. The zone diagram is told a region, the fit plot is handed
points, and each dialog is handed its wording.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tatp.config import REPO_ROOT
from tatp.units import DECADE

# -- palette and type scale ----------------------------------------------------------------
# Presentation only, not study parameters (SPEC.md 4.2). The reference screenshots pin these.
#
# Dark, because the lab screen shares a dim room with a participant looking at a near-black
# one, and a full-brightness page is then the brightest object in their field of view
# (UI_PRINCIPLES.md 3.5).
BACKGROUND = "#141414"
FOREGROUND = "#ebebeb"
SECONDARY = "#9a9a9a"
CONTROL_BACKGROUND = "#262626"
CONTROL_BORDER = "#4a4a4a"
DISABLED = "#555555"
# The banners mean different things and demand different responses, so they do not look alike
# (UI_PRINCIPLES.md 3.4): red is "do not run a participant at all", amber is "this session runs
# but part of what it records is compromised, and is flagged".
PLACEHOLDER_COLOUR = "#b00020"
REDUCED_CAPABILITY_COLOUR = "#8a5a00"
WARNING_COLOUR = "#e0a12a"
DISCONNECTED_COLOUR = "#e0453f"
# Where the current stimulus goes, on the zone diagram. A colour no warning uses, so a
# highlighted zone never reads as an alarm.
TARGET_COLOUR = "#4fa3e0"

# One scale, four steps, each meaning a level rather than a screen's local preference
# (UI_PRINCIPLES.md 4.3).
SIZE_SMALL = 15
SIZE_BODY = 18
SIZE_LARGE = 24
SIZE_HEADLINE = 32

MARGIN_PX = 24
GROUP_GAP_PX = 22
ITEM_GAP_PX = 8
BANNER_PADDING_PX = 8
CONTROL_PADDING_PX = 6
SCREEN_FILL_FRACTION = 0.92

ZONES_SVG = REPO_ROOT / "assets" / "hyperalgesia_zones.svg"
# The ids the zone diagram carries for each region (assets/hyperalgesia_zones.svg).
ZONE_IDS = {"primary": "primary", "secondary": "secondary"}
TARGET_LINE_PX = 5

# The fit plot's own geometry.
PLOT_MARGIN_LEFT_PX = 44
PLOT_MARGIN_BOTTOM_PX = 44
PLOT_MARGIN_TOP_PX = 24
PLOT_MARGIN_RIGHT_PX = 12
PLOT_POINT_RADIUS_PX = 4
PLOT_MARKER_RADIUS_PX = 6
PLOT_LINE_PX = 2
PLOT_RATING_TICKS = (0.0, 50.0, 100.0)
PLOT_RATING_MAX = 100.0
PLOT_LINE_SAMPLES = 50
LABEL_GAP_PX = 4


def stylesheet() -> str:
    """The lab-side look, for a whole window. Labels set their own colour on top of it."""
    return (
        f"QWidget {{ background-color: {BACKGROUND}; color: {FOREGROUND}; }}"
        f"QPushButton {{ background-color: {CONTROL_BACKGROUND}; color: {FOREGROUND}; "
        f"border: 1px solid {CONTROL_BORDER}; padding: {CONTROL_PADDING_PX}px; }}"
        f"QPushButton:disabled {{ color: {DISABLED}; border-color: {CONTROL_BACKGROUND}; }}"
        f"QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ "
        f"background-color: {CONTROL_BACKGROUND}; color: {FOREGROUND}; "
        f"border: 1px solid {CONTROL_BORDER}; padding: {CONTROL_PADDING_PX // 2}px; }}"
        f"QLineEdit:disabled {{ color: {DISABLED}; }}"
    )


def sized(widget: QWidget, point_size: int) -> QWidget:
    font = widget.font()
    font.setPointSize(point_size)
    widget.setFont(font)
    return widget


def label(point_size: int, wrap: bool = False, colour: str = FOREGROUND) -> QLabel:
    made = QLabel()
    made.setWordWrap(wrap)
    sized(made, point_size)
    made.setStyleSheet(f"color: {colour};")
    return made


def button(text: str, point_size: int = SIZE_SMALL) -> QPushButton:
    made = QPushButton(text)
    sized(made, point_size)
    made.setAutoDefault(False)
    return made


def line_edit(point_size: int = SIZE_SMALL) -> QLineEdit:
    return sized(QLineEdit(), point_size)


def fit_to_screen(window: QWidget, width_px: int, height_px: int) -> None:
    """Open `window` at this size, or at what its screen has room for if that is less.

    A lab laptop at 150 % scaling has far fewer logical pixels than its panel, and a window
    sized for a desktop then opens with its lower half off the screen (S, 24 Sep 2026). The
    fraction leaves room for the title bar and the taskbar edge, which the available
    geometry does not always exclude.
    """
    available = window.screen().availableGeometry()
    window.resize(min(width_px, int(available.width() * SCREEN_FILL_FRACTION)),
                  min(height_px, int(available.height() * SCREEN_FILL_FRACTION)))


def banner_style(colour: str) -> str:
    return (
        f"background-color: {colour}; color: #ffffff; "
        f"padding: {BANNER_PADDING_PX}px; font-weight: bold;"
    )


def emphasis_style(colour: str) -> str:
    return f"color: {colour}; font-weight: bold;"


def emphasis_button_style(colour: str) -> str:
    """A button's emphasis, greyed like any other while disabled. A plain colour set on the
    button outranks the window's `:disabled` rule, so a disabled Abort looked pressable."""
    return (
        f"QPushButton {{ color: {colour}; font-weight: bold; }}"
        f"QPushButton:disabled {{ color: {DISABLED}; font-weight: normal; }}"
    )


# -- the zone diagram, SPEC.md 11 ---------------------------------------------------------


class ZoneDiagram(QWidget):
    """`assets/hyperalgesia_zones.svg`, with the current stimulus's zone outlined.

    The diagram is a placeholder line drawing (SPEC.md 11). What the layout depends on is only
    that it carries an element per region, named by `ZONE_IDS`, so a proper figure drops in.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.renderer = QSvgRenderer(str(ZONES_SVG))
        assert self.renderer.isValid(), f"{ZONES_SVG} is not a valid SVG"
        for element in ZONE_IDS.values():
            assert self.renderer.elementExists(element), f"{ZONES_SVG} has no #{element}"
        self.region: str | None = None

    def set_region(self, region: str | None) -> None:
        assert region is None or region in ZONE_IDS, f"no zone {region!r}"
        self.region = region
        self.update()

    def _drawing_rect(self) -> QRectF:
        box = self.renderer.viewBoxF()
        scale = min(self.width() / box.width(), self.height() / box.height())
        width, height = box.width() * scale, box.height() * scale
        return QRectF(
            (self.width() - width) / 2, (self.height() - height) / 2, width, height
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        drawing = self._drawing_rect()
        self.renderer.render(painter, drawing)
        if self.region is None:
            return
        box = self.renderer.viewBoxF()
        scale = drawing.width() / box.width()
        bounds = self.renderer.boundsOnElement(ZONE_IDS[self.region])
        target = QRectF(
            drawing.x() + (bounds.x() - box.x()) * scale,
            drawing.y() + (bounds.y() - box.y()) * scale,
            bounds.width() * scale,
            bounds.height() * scale,
        )
        painter.setPen(QPen(QColor(TARGET_COLOUR), TARGET_LINE_PX))
        painter.setBrush(Qt.NoBrush)
        if self.region == "secondary":
            painter.drawEllipse(target)
        else:
            painter.drawRect(target)


# -- the fit plot, SPEC.md 11.1 -----------------------------------------------------------


class FitPlot(QWidget):
    """Observed points, the fitted line and the estimate, on a rating axis of 0 to 100 %.

    Only ever shown inside the fit preview, which is the one place a rating reaches the lab
    screen and only while `fit_preview.enabled` is true (SPEC.md 11.1).
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        sized(self, SIZE_SMALL)
        self.clear()

    def clear(self) -> None:
        self.points: tuple[tuple[float, float], ...] = ()
        self.line: tuple[tuple[float, float], ...] = ()
        self.marker: tuple[float, float] | None = None
        self.log_x = False
        self.x_label = ""
        self.y_label = ""
        self.update()

    def set_data(
        self,
        points: Sequence[tuple[float, float]],
        line: Sequence[tuple[float, float]],
        marker: tuple[float, float] | None,
        log_x: bool,
        x_label: str,
        y_label: str,
    ) -> None:
        self.points = tuple(points)
        self.line = tuple(line)
        self.marker = marker
        self.log_x = log_x
        self.x_label = x_label
        self.y_label = y_label
        self.update()

    def _x(self, value: float) -> float:
        return math.log10(value) if self.log_x else value

    def paintEvent(self, event) -> None:
        xs =[self._x(x) for x, _ in self.points + self.line]
        if self.marker is not None:
            xs.append(self._x(self.marker[0]))
        if not xs:
            return
        x_low, x_high = min(xs), max(xs)
        if x_high == x_low:
            x_low, x_high = x_low - 1, x_high + 1

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        area = QRectF(
            PLOT_MARGIN_LEFT_PX,
            PLOT_MARGIN_TOP_PX,
            self.width() - PLOT_MARGIN_LEFT_PX - PLOT_MARGIN_RIGHT_PX,
            self.height() - PLOT_MARGIN_TOP_PX - PLOT_MARGIN_BOTTOM_PX,
        )

        def at(x: float, rating: float) -> QPointF:
            fraction = (self._x(x) - x_low) / (x_high - x_low)
            clamped = min(max(rating, 0.0), PLOT_RATING_MAX)
            return QPointF(
                area.left() + fraction * area.width(),
                area.bottom() - clamped / PLOT_RATING_MAX * area.height(),
            )

        metrics = painter.fontMetrics()
        painter.setPen(QPen(QColor(SECONDARY), 1))
        painter.drawLine(area.bottomLeft(), area.bottomRight())
        painter.drawLine(area.bottomLeft(), area.topLeft())
        for tick in PLOT_RATING_TICKS:
            y = area.bottom() - tick / PLOT_RATING_MAX * area.height()
            text = f"{tick:g}"
            painter.drawText(
                QPointF(area.left() - metrics.horizontalAdvance(text) - LABEL_GAP_PX,
                        y + metrics.ascent() / 2),
                text,
            )
        for edge in (x_low, x_high):
            value = DECADE**edge if self.log_x else edge
            text = f"{value:.3g}"
            x = area.left() + (edge - x_low) / (x_high - x_low) * area.width()
            painter.drawText(
                QPointF(min(x, area.right() - metrics.horizontalAdvance(text)),
                        area.bottom() + metrics.ascent() + LABEL_GAP_PX),
                text,
            )
        painter.drawText(
            QPointF(area.center().x() - metrics.horizontalAdvance(self.x_label) / 2,
                    self.height() - LABEL_GAP_PX),
            self.x_label,
        )
        # Above the axis rather than inside it, where the points would run through it.
        painter.drawText(QPointF(LABEL_GAP_PX, metrics.ascent()), self.y_label)

        if len(self.line) > 1:
            painter.setPen(QPen(QColor(TARGET_COLOUR), PLOT_LINE_PX))
            for (x0, y0), (x1, y1) in zip(self.line, self.line[1:], strict=False):
                painter.drawLine(at(x0, y0), at(x1, y1))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(FOREGROUND))
        for x, rating in self.points:
            painter.drawEllipse(at(x, rating), PLOT_POINT_RADIUS_PX, PLOT_POINT_RADIUS_PX)

        if self.marker is not None:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(WARNING_COLOUR), PLOT_LINE_PX))
            painter.drawEllipse(at(*self.marker), PLOT_MARKER_RADIUS_PX, PLOT_MARKER_RADIUS_PX)


Points = tuple[tuple[float, float], ...]


def sample_line(low: float, high: float, log_x: bool, rating_at) -> Points:
    """`rating_at(x)` sampled evenly on the plot's own axis between `low` and `high`."""
    fractions = [i / (PLOT_LINE_SAMPLES - 1) for i in range(PLOT_LINE_SAMPLES)]
    if log_x:
        a, b = math.log10(low), math.log10(high)
        xs = [DECADE ** (a + (b - a) * f) for f in fractions]
    else:
        xs = [low + (high - low) * f for f in fractions]
    return tuple((x, rating_at(x)) for x in xs)


# -- dialogs -------------------------------------------------------------------------------


class ReasonDialog(QDialog):
    """A question that needs a reason before it can be confirmed: the abort, the re-run.

    Confirm stays disabled until a reason is typed, because the reason is what the data file
    records about a decision nobody can take back (SPEC.md 11, 11.1).
    """

    def __init__(
        self,
        title: str,
        message: str,
        reason_label: str,
        confirm: str,
        cancel: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(stylesheet())
        self.message = label(SIZE_BODY, wrap=True)
        self.message.setText(message)
        self.reason_label = label(SIZE_SMALL, colour=SECONDARY)
        self.reason_label.setText(reason_label)
        self.reason = line_edit(SIZE_BODY)
        self.confirm = button(confirm, SIZE_BODY)
        self.confirm.setStyleSheet(emphasis_button_style(DISCONNECTED_COLOUR))
        self.cancel = button(cancel, SIZE_BODY)
        self.confirm.setEnabled(False)
        self.reason.textChanged.connect(
            lambda text: self.confirm.setEnabled(bool(text.strip()))
        )
        self.confirm.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.confirm)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(self.message)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addWidget(self.reason_label)
        layout.addWidget(self.reason)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addLayout(buttons)

    def reason_text(self) -> str:
        return self.reason.text().strip()


class MessageDialog(QDialog):
    """A message with one or two buttons: the error dialog, and the resume question."""

    def __init__(
        self,
        title: str,
        message: str,
        accept: str,
        reject: str | None = None,
        colour: str = FOREGROUND,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(stylesheet())
        self.title = label(SIZE_LARGE, colour=colour)
        self.title.setText(title)
        self.message = label(SIZE_BODY, wrap=True)
        self.message.setText(message)
        self.accept_button = button(accept, SIZE_BODY)
        self.accept_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if reject is not None:
            self.reject_button = button(reject, SIZE_BODY)
            self.reject_button.clicked.connect(self.reject)
            buttons.addWidget(self.reject_button)
        buttons.addWidget(self.accept_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(self.title)
        layout.addWidget(self.message)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addLayout(buttons)
