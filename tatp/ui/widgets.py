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

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QButtonGroup,
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
# Whatever exists only in a demonstration -- its banner, its controls, how it differs from a
# session -- in a colour of its own, so it is never taken for part of a session (S, 20 Oct
# 2026; UI_PRINCIPLES.md 3.7). Violet: no warning, state or target uses it.
DEMO_COLOUR = "#b48cf0"
DEMO_BANNER_COLOUR = "#5a3d8a"

# One scale, four steps, each meaning a level rather than a screen's local preference
# (UI_PRINCIPLES.md 4.3).
# Pixels per point on the lab PC: Windows lays text out at 96 dots to the inch, against the
# 72 points of an inch. A unit conversion (`set_points`).
PX_PER_POINT = 96 / 72
# Windows' own interface size, and the headless platform's: what anything not sized here is
# drawn at, on every platform (macOS's own is 13).
SIZE_SYSTEM = 9
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
# The ids the zone diagram carries for each region, and each region's numbered sites
# (assets/hyperalgesia_zones.svg).
ZONE_IDS = {"primary": "primary", "secondary": "secondary"}
SITE_ID = "{region}_site_{site}"
# The part of the figure shown, if the figure names one.
VIEW_ID = "view"
TARGET_LINE_PX = 5
# The current site, drawn this many times its marker's radius, and the others' outline.
SITE_TARGET_SCALE = 2.2
SITE_LINE_PX = 1.5
# The current site's number, as a fraction of its filled marker's diameter.
SITE_NUMBER_SCALE = 0.7
# The mapping paths (study1.yaml mapping.path_ids) as arrows toward the zone's centre, each
# along its anatomical direction in the figure's own coordinates, a right hand's dorsum with
# the fingers up: distal up, proximal down, lateral to the thumb (left), medial away from it.
PATH_DIRECTIONS = {"proximal": (0.0, 1.0), "lateral": (-1.0, 0.0), "distal": (0.0, -1.0),
                   "medial": (1.0, 0.0)}
# An arrow starts this far outside the secondary zone and ends this far inside it, as
# fractions of the zone's half-width in its direction.
PATH_OUTSIDE = 0.3
PATH_INSIDE = 0.25
PATH_LINE_PX = 2
PATH_TARGET_LINE_PX = 5
# The brush's sites (S, 22 Oct 2026): in the primary zone the whole zone, which the brush
# covers, tinted; in the secondary zone a stroke along each edge of the primary zone, just
# outside it, in the mapping paths' order (proximal, lateral, distal, medial), the first again
# for a fifth. Placeholder positions, as the filament sites' are (open item 11).
BRUSH_EDGES = tuple(PATH_DIRECTIONS)
BRUSH_OFFSET_UNITS = 8
BRUSH_STROKE_FRACTION = 0.6
BRUSH_LINE_PX = 3
BRUSH_TARGET_LINE_PX = 7
BRUSH_ZONE_TINT_ALPHA = 0.3
# The primary zone's filament sites, spread evenly across it for the number a series uses:
# one row up to this many, two beyond, the first the longer (five: three and two).
ONE_ROW_SITES_MAX = 4
# Each site in the middle of its equal share of a row, or of the zone's height.
SHARE_MIDDLE = 0.5
PRIMARY = "primary"
ARROW_HEAD_PX = 9
ARROW_HEAD_TARGET_SCALE = 1.5
# Label sizes in the figure's own units, so they scale with it.
ZONE_LABEL_UNITS = 15
CAPTION_UNITS = 11
# Where the labels sit, in the figure's units: the secondary zone's under it, the caption at
# the foot.
SH_LABEL_BELOW_UNITS = 16
CAPTION_FROM_FOOT_UNITS = 10

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
# The tick box of a checkbox, and of the designer's radio buttons.
CHECK_INDICATOR_PX = 14


# A style sheet replaces the platform's own button drawing, its pressed look included, so a
# press showed nothing (S, 20 Oct 2026; LOG N7.F16e): a button that does not visibly go down
# is pressed again. Pressed is filled in the target colour, and a pressable button under the
# pointer is outlined in the foreground. Appended to every button style below, since a
# button's own style sheet outranks the window's.
PRESS_RULES = (
    f"QPushButton:hover:!disabled:!pressed {{ border-color: {FOREGROUND}; }}"
    f"QPushButton:pressed {{ background-color: {TARGET_COLOUR}; color: {BACKGROUND}; "
    f"border-color: {TARGET_COLOUR}; }}"
)


def stylesheet() -> str:
    """The lab-side look, for a whole window. Labels set their own colour on top of it."""
    return (
        f"QWidget {{ background-color: {BACKGROUND}; color: {FOREGROUND}; }}"
        f"QPushButton {{ background-color: {CONTROL_BACKGROUND}; color: {FOREGROUND}; "
        f"border: 1px solid {CONTROL_BORDER}; padding: {CONTROL_PADDING_PX}px; }}"
        f"QPushButton:disabled {{ color: {DISABLED}; border-color: {CONTROL_BACKGROUND}; }}"
        f"{PRESS_RULES}"
        # A button that stays down says so: otherwise on and off look the same (N7.F10b).
        f"QPushButton:checked {{ background-color: {TARGET_COLOUR}; color: {BACKGROUND}; }}"
        f"QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ "
        f"background-color: {CONTROL_BACKGROUND}; color: {FOREGROUND}; "
        f"border: 1px solid {CONTROL_BORDER}; padding: {CONTROL_PADDING_PX // 2}px; }}"
        f"QLineEdit:disabled {{ color: {DISABLED}; }}"
        # Qt's own indicator is near-invisible on the dark background when unchecked.
        f"QCheckBox::indicator {{ width: {CHECK_INDICATOR_PX}px; "
        f"height: {CHECK_INDICATOR_PX}px; border: 1px solid {SECONDARY}; "
        f"background-color: {CONTROL_BACKGROUND}; }}"
        f"QCheckBox::indicator:checked {{ background-color: {TARGET_COLOUR}; }}"
    )


def set_points(font: QFont, point_size: float) -> QFont:
    """`font` at `point_size` as the lab PC draws it, on every platform: Windows, and Qt's
    headless platform the tests run on, draw a point as 96/72 of a pixel, macOS as one, so the
    same screen had a third more room on a Mac (S, 22 Oct 2026: "We should minimise those
    differences"). In pixels, which every platform draws alike."""
    font.setPixelSize(max(1, round(point_size * PX_PER_POINT)))
    return font


def sized(widget: QWidget, point_size: int) -> QWidget:
    widget.setFont(set_points(widget.font(), point_size))
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
        f"{PRESS_RULES}"
    )


def primary_button_style(point_size: int = SIZE_BODY) -> str:
    """The way forward: filled, outlined in the foreground colour, and bold, so it is the
    button found first at a glance (UI_PRINCIPLES.md 5.1). Greyed like any other while
    disabled, with its fill dropped so a disabled one never reads as the way forward.
    `point_size` is the button's own size, so taking on the emphasis never resizes it."""
    return (
        f"QPushButton {{ background-color: {CONTROL_BORDER}; color: {FOREGROUND}; "
        f"border: 1px solid {FOREGROUND}; font-size: {point_size}pt; font-weight: bold; }}"
        f"QPushButton:disabled {{ background-color: {CONTROL_BACKGROUND}; color: {DISABLED}; "
        f"border-color: {CONTROL_BACKGROUND}; font-weight: normal; }}"
        f"{PRESS_RULES}"
    )


# -- the zone diagram, SPEC.md 11 ---------------------------------------------------------


class ZoneDiagram(QWidget):
    """`assets/hyperalgesia_zones.svg`, with where the current stimulus goes marked: its zone
    outlined and, for a filament or the brush, every site of the zone with the current one
    filled (S, 21 Oct 2026: "The diagram should show the sites, rather than writing the site
    number"); for the area mapping, the four paths with the current one drawn heavy.

    The figure is a right hand; `set_mirrored` draws a left one. Its labels are drawn here, so
    they are never mirrored. `words` is the experimenter text's `zones`, `path_words` its
    `terms.mapping_paths_short`.

    The diagram is a placeholder line drawing (SPEC.md 11, open item 11). What the layout
    depends on is only that it carries the ids `ZONE_IDS` and `SITE_ID` name, so a proper
    figure drops in.
    """

    def __init__(self, words: dict, path_words: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.words = words
        self.path_words = path_words
        self.renderer = QSvgRenderer(str(ZONES_SVG))
        assert self.renderer.isValid(), f"{ZONES_SVG} is not a valid SVG"
        if self.renderer.elementExists(VIEW_ID):
            self.renderer.setViewBox(self.renderer.boundsOnElement(VIEW_ID))
        for element in ZONE_IDS.values():
            assert self.renderer.elementExists(element), f"{ZONES_SVG} has no #{element}"
        assert set(path_words) == set(PATH_DIRECTIONS), (
            f"terms.mapping_paths_short names {sorted(path_words)}; the diagram draws "
            f"{sorted(PATH_DIRECTIONS)}"
        )
        self.region: str | None = None
        self.site: int | None = None
        self.path: str | None = None
        self.brush = False
        self.mirrored = False
        # Per zone, how many sites the series under way uses (`set_sites_in_use`).
        self.in_use: dict[str, int] = {}

    def width_for(self, height_px: int) -> int:
        """The width the drawing fills at `height_px`: the diagram keeps its proportions."""
        box = self.renderer.viewBoxF()
        return math.ceil(height_px * box.width() / box.height())

    def sites(self, region: str) -> int:
        """How many numbered sites the figure has for `region`."""
        count = 0
        while self.renderer.elementExists(SITE_ID.format(region=region, site=count + 1)):
            count += 1
        return count

    def set_target(self, region: str | None, site: int | None = None,
                   path: str | None = None, brush: bool = False) -> None:
        """Mark `region`, its `site` if one, or the mapping's `path` if one; None clears.
        `brush` marks the brush's sites rather than a filament's."""
        assert region is None or region in ZONE_IDS, f"no zone {region!r}"
        most = (1 if region == PRIMARY else len(BRUSH_EDGES)) if brush else (
            self.sites(region) if region is not None else 0)
        assert site is None or (region is not None and 1 <= site <= most), (
            f"there is no {'brush ' if brush else ''}site {site} in the {region} zone"
        )
        assert path is None or path in PATH_DIRECTIONS, f"no mapping path {path!r}"
        self.region, self.site, self.path, self.brush = region, site, path, brush
        self.update()

    def set_sites_in_use(self, region: str, count: int | None) -> None:
        """Draw only `region`'s first `count` sites, those a series uses; None, every one."""
        assert count is None or count >= 1, count
        if count is None:
            self.in_use.pop(region, None)
        else:
            self.in_use[region] = count
        self.update()

    def drawn_sites(self) -> int:
        """How many of the target zone's sites are drawn: those the series uses, and the
        current one even past that, where a repeat after a discard has gone on to it. None
        for the brush in the primary zone, whose site is the whole zone."""
        if self.brush:
            return 0 if self.region == PRIMARY else min(
                len(BRUSH_EDGES), self.in_use.get(self.region, len(BRUSH_EDGES)))
        figure = self.sites(self.region)
        return min(figure, max(self.in_use.get(self.region, figure), self.site or 0))

    def set_mirrored(self, mirrored: bool) -> None:
        if mirrored != self.mirrored:
            self.mirrored = mirrored
            self.update()

    def _drawing_rect(self) -> QRectF:
        box = self.renderer.viewBoxF()
        scale = min(self.width() / box.width(), self.height() / box.height())
        width, height = box.width() * scale, box.height() * scale
        return QRectF(
            (self.width() - width) / 2, (self.height() - height) / 2, width, height
        )

    def _point(self, drawing: QRectF, x: float, y: float) -> QPointF:
        """A point of the figure on the widget, mirrored with it."""
        box = self.renderer.viewBoxF()
        scale = drawing.width() / box.width()
        across = (x - box.x()) * scale
        if self.mirrored:
            across = drawing.width() - across
        return QPointF(drawing.x() + across, drawing.y() + (y - box.y()) * scale)

    def _rect(self, drawing: QRectF, element: str) -> QRectF:
        bounds = self.renderer.boundsOnElement(element)
        return QRectF(self._point(drawing, bounds.left(), bounds.top()),
                      self._point(drawing, bounds.right(), bounds.bottom())).normalized()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        drawing = self._drawing_rect()
        box = self.renderer.viewBoxF()
        scale = drawing.width() / box.width()
        painter.save()
        if self.mirrored:
            painter.translate(drawing.x() * 2 + drawing.width(), 0)
            painter.scale(-1, 1)
        self.renderer.render(painter, drawing)
        painter.restore()
        self._draw_labels(painter, drawing, scale)
        if self.region is not None:
            zone = self._rect(drawing, ZONE_IDS[self.region])
            painter.setPen(QPen(QColor(TARGET_COLOUR), TARGET_LINE_PX))
            painter.setBrush(Qt.NoBrush)
            if self.region == "secondary":
                painter.drawEllipse(zone)
            else:
                painter.drawRect(zone)
            if self.path is None:
                self._draw_sites(painter, drawing, scale)
        if self.path is not None:
            self._draw_paths(painter, drawing, scale)
        painter.end()

    def _draw_labels(self, painter: QPainter, drawing: QRectF, scale: float) -> None:
        font = painter.font()
        font.setPixelSize(max(1, round(ZONE_LABEL_UNITS * scale)))
        painter.setFont(font)
        painter.setPen(QColor(FOREGROUND))
        primary = self._rect(drawing, ZONE_IDS["primary"])
        painter.drawText(primary, Qt.AlignCenter, self.words["primary"])
        secondary = self._rect(drawing, ZONE_IDS["secondary"])
        below = QRectF(secondary.left(), secondary.bottom(), secondary.width(),
                       SH_LABEL_BELOW_UNITS * scale * 2)
        painter.drawText(below, Qt.AlignHCenter | Qt.AlignTop, self.words["secondary"])
        font.setPixelSize(max(1, round(CAPTION_UNITS * scale)))
        painter.setFont(font)
        painter.setPen(QColor(SECONDARY))
        foot = QRectF(drawing.left(), drawing.bottom() - CAPTION_FROM_FOOT_UNITS * scale * 2,
                      drawing.width(), CAPTION_FROM_FOOT_UNITS * scale * 2)
        painter.drawText(foot, Qt.AlignCenter, self.words["caption"])

    def _draw_sites(self, painter: QPainter, drawing: QRectF, scale: float) -> None:
        """The sites drawn, the current one filled or heavy, and numbered."""
        marker = self._rect(drawing, SITE_ID.format(region=PRIMARY, site=1))
        radius = marker.width() / 2 * SITE_TARGET_SCALE
        if self.brush and self.region == PRIMARY:
            tint = QColor(TARGET_COLOUR)
            tint.setAlphaF(BRUSH_ZONE_TINT_ALPHA)
            painter.setPen(Qt.NoPen)
            painter.setBrush(tint)
            painter.drawRect(self._rect(drawing, ZONE_IDS[PRIMARY]))
            return
        for site, shape in enumerate(self._site_shapes(drawing), start=1):
            current = site == self.site
            if isinstance(shape, QLineF):
                painter.setPen(QPen(QColor(TARGET_COLOUR),
                                    BRUSH_TARGET_LINE_PX if current else BRUSH_LINE_PX))
                painter.drawLine(shape)
                if current:
                    self._draw_number(painter, shape.center(), radius, site)
                continue
            if not current:
                painter.setPen(QPen(QColor(TARGET_COLOUR), SITE_LINE_PX))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(shape)
                continue
            self._draw_number(painter, shape.center(), shape.width() / 2 * SITE_TARGET_SCALE,
                              site)

    def _site_shapes(self, drawing: QRectF) -> list:
        """Where each drawn site is, on the widget: a brush stroke's line, or a filament
        site's marker -- in the primary zone spread evenly for the number drawn, elsewhere
        the figure's own."""
        count = self.drawn_sites()
        if self.brush:
            return [self._brush_stroke(drawing, edge) for edge in BRUSH_EDGES[:count]]
        if self.region == PRIMARY:
            return self._even_sites(drawing, count)
        return [self._rect(drawing, SITE_ID.format(region=self.region, site=site))
                for site in range(1, count + 1)]

    def _brush_stroke(self, drawing: QRectF, edge: str) -> QLineF:
        bounds = self.renderer.boundsOnElement(ZONE_IDS[PRIMARY])
        dx, dy = PATH_DIRECTIONS[edge]
        centre = bounds.center()
        if dx:
            x = (bounds.left() - BRUSH_OFFSET_UNITS if dx < 0
                 else bounds.right() + BRUSH_OFFSET_UNITS)
            half = bounds.height() * BRUSH_STROKE_FRACTION / 2
            ends = ((x, centre.y() - half), (x, centre.y() + half))
        else:
            y = (bounds.top() - BRUSH_OFFSET_UNITS if dy < 0
                 else bounds.bottom() + BRUSH_OFFSET_UNITS)
            half = bounds.width() * BRUSH_STROKE_FRACTION / 2
            ends = ((centre.x() - half, y), (centre.x() + half, y))
        return QLineF(self._point(drawing, *ends[0]), self._point(drawing, *ends[1]))

    def _even_sites(self, drawing: QRectF, count: int) -> list[QRectF]:
        bounds = self.renderer.boundsOnElement(ZONE_IDS[PRIMARY])
        marker = self.renderer.boundsOnElement(SITE_ID.format(region=PRIMARY, site=1))
        radius = marker.width() / 2
        rows = [count] if count <= ONE_ROW_SITES_MAX else [math.ceil(count / 2), count // 2]
        sites = []
        for row, in_row in enumerate(rows):
            y = bounds.top() + bounds.height() * (row + SHARE_MIDDLE) / len(rows)
            for k in range(in_row):
                x = bounds.left() + bounds.width() * (k + SHARE_MIDDLE) / in_row
                sites.append(QRectF(self._point(drawing, x - radius, y - radius),
                                    self._point(drawing, x + radius, y + radius)).normalized())
        return sites

    def _draw_number(self, painter: QPainter, centre: QPointF, radius: float,
                     site: int) -> None:
        """The current site: filled, with its number."""
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(TARGET_COLOUR))
        painter.drawEllipse(centre, radius, radius)
        font = painter.font()
        font.setPixelSize(max(1, round(2 * radius * SITE_NUMBER_SCALE)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(BACKGROUND))
        painter.drawText(QRectF(centre.x() - radius, centre.y() - radius,
                                2 * radius, 2 * radius), Qt.AlignCenter, str(site))
        font.setBold(False)
        painter.setFont(font)

    def _draw_paths(self, painter: QPainter, drawing: QRectF, scale: float) -> None:
        """The four mapping paths, from outside the secondary zone toward its centre, each
        labelled; the one being walked heavy, in the target colour."""
        bounds = self.renderer.boundsOnElement(ZONE_IDS["secondary"])
        centre_x, centre_y = bounds.center().x(), bounds.center().y()
        half = {(1.0, 0.0): bounds.width() / 2, (0.0, 1.0): bounds.height() / 2}
        font = painter.font()
        font.setPixelSize(max(1, round(CAPTION_UNITS * scale)))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for path, (dx, dy) in PATH_DIRECTIONS.items():
            extent = half[(abs(dx), abs(dy))]
            start = self._point(drawing, centre_x + dx * extent * (1 + PATH_OUTSIDE),
                                centre_y + dy * extent * (1 + PATH_OUTSIDE))
            end = self._point(drawing, centre_x + dx * extent * (1 - PATH_INSIDE),
                              centre_y + dy * extent * (1 - PATH_INSIDE))
            now = path == self.path
            colour = QColor(TARGET_COLOUR if now else SECONDARY)
            painter.setPen(QPen(colour, PATH_TARGET_LINE_PX if now else PATH_LINE_PX))
            painter.drawLine(start, end)
            # The head, pointing inward.
            length = math.hypot(end.x() - start.x(), end.y() - start.y())
            ux, uy = (end.x() - start.x()) / length, (end.y() - start.y()) / length
            head = ARROW_HEAD_PX * (ARROW_HEAD_TARGET_SCALE if now else 1)
            painter.setBrush(colour)
            painter.setPen(Qt.NoPen)
            painter.drawPolygon([end,
                                 QPointF(end.x() - head * ux - head * uy / 2,
                                         end.y() - head * uy + head * ux / 2),
                                 QPointF(end.x() - head * ux + head * uy / 2,
                                         end.y() - head * uy - head * ux / 2)])
            # Beside the arrow's tail, toward the zone's centre line, so it stays in the view.
            word = self.path_words[path]
            width, height = metrics.horizontalAdvance(word), metrics.height()
            across = (abs(uy) * (width / 2 + ARROW_HEAD_PX), abs(ux) * height)
            label = QRectF(start.x() + across[0] - width / 2, start.y() + across[1]
                           - height / 2, width, height)
            # Kept inside the drawing, which shows only part of the figure.
            label.moveLeft(min(max(label.left(), drawing.left()), drawing.right() - width))
            label.moveTop(min(max(label.top(), drawing.top()), drawing.bottom() - height))
            painter.setPen(colour)
            painter.drawText(label, Qt.AlignCenter, word)


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


class ChoiceDialog(QDialog):
    """A question that needs a reason from a fixed list before it can be confirmed: the
    re-calibration after an emergency stop (docs/research/R36). As `ReasonDialog`, but the
    reason is one of `options` ({key: wording}), so it costs one press and can be analysed.
    Each option is a button that stays down when chosen, one at a time."""

    def __init__(
        self,
        title: str,
        message: str,
        reason_label: str,
        options: dict[str, str],
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
        self.confirm = button(confirm, SIZE_BODY)
        self.confirm.setStyleSheet(emphasis_button_style(WARNING_COLOUR))
        self.cancel = button(cancel, SIZE_BODY)
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.options: dict[str, QPushButton] = {}
        reasons = QVBoxLayout()
        for key, wording in options.items():
            option = button(wording, SIZE_BODY)
            option.setCheckable(True)
            self.group.addButton(option)
            self.options[key] = option
            reasons.addWidget(option)
        self.group.buttonToggled.connect(
            lambda *_: self.confirm.setEnabled(bool(self.choice()))
        )

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.confirm)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(self.message)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addWidget(self.reason_label)
        layout.addLayout(reasons)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addLayout(buttons)

    def choice(self) -> str:
        """The chosen option's key, or "" before one is chosen."""
        return next((key for key, option in self.options.items() if option.isChecked()), "")


class ActionChoiceDialog(ChoiceDialog):
    """`ChoiceDialog` with a choice of what to do before the reason: the re-calibration, one
    control for both of its paths (S, 21 Oct 2026). Each action is a button that stays down
    when chosen, with what it does under it in full; one offered alone is chosen already.
    Confirm needs both an action and a reason."""

    def __init__(
        self,
        title: str,
        message: str,
        action_label: str,
        actions: dict[str, str],
        details: dict[str, str],
        reason_label: str,
        reasons: dict[str, str],
        confirm: str,
        cancel: str,
        parent: QWidget | None = None,
    ):
        super().__init__(title, message, reason_label, reasons, confirm, cancel, parent)
        assert actions, "an action dialog with nothing to choose"
        self.action_label = label(SIZE_SMALL, colour=SECONDARY)
        self.action_label.setText(action_label)
        self.action_group = QButtonGroup(self)
        self.action_group.setExclusive(True)
        self.actions: dict[str, QPushButton] = {}
        column = QVBoxLayout()
        for key, wording in actions.items():
            option = button(wording, SIZE_BODY)
            option.setCheckable(True)
            self.action_group.addButton(option)
            self.actions[key] = option
            detail = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
            detail.setText(details[key])
            column.addWidget(option)
            column.addWidget(detail)
        if len(actions) == 1:
            next(iter(self.actions.values())).setChecked(True)
        self.action_group.buttonToggled.connect(self._enable)
        self.group.buttonToggled.disconnect()
        self.group.buttonToggled.connect(self._enable)
        layout = self.layout()
        # What, then why: before the reason's caption, each inserted ahead of the last.
        at = layout.indexOf(self.reason_label)
        layout.insertSpacing(at, GROUP_GAP_PX)
        layout.insertLayout(at, column)
        layout.insertWidget(at, self.action_label)

    def _enable(self, *_) -> None:
        self.confirm.setEnabled(bool(self.action()) and bool(self.choice()))

    def action(self) -> str:
        """The chosen action's key, or "" before one is chosen."""
        return next((key for key, option in self.actions.items() if option.isChecked()), "")


# What `CorrectionDialog.choice` returns as its action.
CORRECT_FILAMENT = "filament"
CORRECT_DISCARD = "discard"


class CorrectionDialog(QDialog):
    """Correct last application… (S, 22 Oct 2026): another filament was applied, one of
    `filaments` ({gram label: wording}, none when that can no longer be recorded), or discard
    and repeat it. One press chooses, each a button that stays down, the choices one group;
    Discard is listed even when it cannot be taken yet, greyed, with `discard_note` saying when
    it can. Confirm needs a choice."""

    def __init__(
        self,
        title: str,
        message: str,
        filament_label: str,
        filaments: dict[str, str],
        discard: str,
        discard_note: str,
        can_discard: bool,
        confirm: str,
        cancel: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(stylesheet())
        self.message = label(SIZE_BODY, wrap=True)
        self.message.setText(message)
        self.confirm = button(confirm, SIZE_BODY)
        self.confirm.setStyleSheet(emphasis_button_style(WARNING_COLOUR))
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.accept)
        self.cancel = button(cancel, SIZE_BODY)
        self.cancel.clicked.connect(self.reject)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.buttonToggled.connect(lambda *_: self.confirm.setEnabled(
            self.group.checkedButton() is not None))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(self.message)
        layout.addSpacing(GROUP_GAP_PX)
        self.filaments: dict[str, QPushButton] = {}
        if filaments:
            caption = label(SIZE_SMALL, colour=SECONDARY)
            caption.setText(filament_label)
            layout.addWidget(caption)
            row = QHBoxLayout()
            for label_g, wording in filaments.items():
                option = button(wording, SIZE_BODY)
                option.setCheckable(True)
                self.group.addButton(option)
                self.filaments[label_g] = option
                row.addWidget(option)
            row.addStretch(1)
            layout.addLayout(row)
            layout.addSpacing(GROUP_GAP_PX)
        self.discard = button(discard, SIZE_BODY)
        self.discard.setCheckable(True)
        self.discard.setEnabled(can_discard)
        self.group.addButton(self.discard)
        self.discard_note = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        self.discard_note.setText(discard_note)
        layout.addWidget(self.discard)
        layout.addWidget(self.discard_note)
        layout.addSpacing(GROUP_GAP_PX)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.confirm)
        layout.addLayout(buttons)

    def choice(self) -> tuple[str, str]:
        """(`CORRECT_FILAMENT`, gram label) or (`CORRECT_DISCARD`, ""), or ("", "") before a
        choice."""
        if self.discard.isChecked():
            return CORRECT_DISCARD, ""
        chosen = next((g for g, option in self.filaments.items() if option.isChecked()), "")
        return (CORRECT_FILAMENT, chosen) if chosen else ("", "")


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
