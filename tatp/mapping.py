"""Secondary-hyperalgesia area mapping. SPEC.md 8.4.

**The software's only job during the mapping is the pacing cue.** It does not count steps and
does not record where the border fell -- that is a pen mark and a ruler. `AreaMapping` runs
the four paths: the experimenter starts each one, a cue fires every `step_interval_s` for up to
`max_steps` cues, and the experimenter stops it at the border. Each cue is logged and emitted
as `pacing_cue`, which is what Milestone 5 wires to the audible tick. The masking noise is
silent through it, as it is whenever the garment cannot run (`tatp.audio.NoiseGate`). An
interruption mid-path runs the whole path again from its start, because the filament was
lifted. The zone diagram beside the instruction shows the four paths, the one to walk drawn
heavy (S, 21 Oct 2026).

**The distances never block.** They are typed whenever convenient, often long after the path,
so they are held by `MappingLedger`, which lives for the whole session and listens to the
experimenter's `distances_entered`. Each path's `mapping` row is written the moment its
distance is accepted (SPEC.md 14.3), and the `sh_area` row once all four are in. A distance
outside the plausible range is queried rather than accepted: the experimenter confirms it by
entering the same value again. What became of each entry is said in the distances box, beside
the fields (`ExperimenterWindow.distances`; S, 21 Oct 2026). A different value for a path
already recorded is a correction, and appends a superseding row -- analysis takes the last row
per time point and path (see
docs/DATA_SCHEMA.md). At session end `MappingLedger.close()` prompts once for anything
outstanding and, the next time it is called, writes what there is with the gaps flagged
missing. Until then a walked but unmeasured path is recoverable from its logged start.

**The area** is the rectangle spanned by the two pairs of opposite paths,
`(d1 + d3) x (d2 + d4)`, each distance measured from the centre of the primary zone. That is
how the heat-capsaicin literature computes it (docs/research/RB1-sh-area-formula.md). The
paths are numbered round the zone by `mapping.path_ids`, so 1 is opposite 3 and 2 opposite 4.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from tatp.config import instruction
from tatp.procedure import Procedure, Rig
from tatp.session import Session, SessionError
from tatp.ui.experimenter import CONFIRMED, NOW, PREPARE, QUERIED, ExperimenterWindow

# There is no participant mapping screen, only standby: the participant is instructed and
# answers verbally (SPEC.md 8.4).
from tatp.ui.participant import STANDBY_SCREEN

# The zone the paths cross, on the diagram (tatp/ui/widgets.py ZONE_IDS).
SECONDARY_ZONE = "secondary"
# The formula takes opposite pairs, so it is defined for exactly four paths round the zone.
N_PATHS_FOR_AREA = 4


def sh_area_mm2(distances_mm: Sequence[float]) -> float:
    """The rectangle spanned by the two pairs of opposite paths (docs/research/RB1)."""
    assert len(distances_mm) == N_PATHS_FOR_AREA, f"four distances, got {distances_mm}"
    return (distances_mm[0] + distances_mm[2]) * (distances_mm[1] + distances_mm[3])


def plausible(distance_mm: float, mapping: dict) -> bool:
    return (
        float(mapping["distance_plausible_min_mm"])
        <= distance_mm
        <= float(mapping["distance_plausible_max_mm"])
    )


@dataclass
class _TimePoint:
    """One time point's mapping: when each path started, and each distance once accepted."""

    n_paths: int
    starts: dict[int, tuple[str, float | None]] = field(default_factory=dict)
    distances: dict[int, tuple[float, str]] = field(default_factory=dict)  # (mm, entered iso)
    queried: dict[int, float] = field(default_factory=dict)  # path -> implausible value
    rows: set[int] = field(default_factory=set)  # paths with a `mapping` row written
    area_written: bool = False

    @property
    def complete(self) -> bool:
        return len(self.distances) == self.n_paths


class MappingLedger(QObject):
    """Every time point's mapping distances, for the whole session. One per session.

    `area_recorded` carries `(phase, area_mm2)` each time an `sh_area` row with a computed
    area is written, a correction's included.
    """

    area_recorded = Signal(str, float)

    def __init__(
        self, session: Session, experimenter: ExperimenterWindow, parent: QObject | None = None
    ):
        super().__init__(parent)
        self.session = session
        self.experimenter = experimenter
        self.mapping = session.config.study1["mapping"]
        self.n_paths = int(self.mapping["n_paths"])
        self.path_ids = list(self.mapping["path_ids"])
        # Stage boundary (CLAUDE.md): the area formula pairs opposite paths.
        assert self.n_paths == N_PATHS_FOR_AREA == len(self.path_ids), (
            f"study1.yaml: mapping.n_paths is {self.n_paths} and path_ids names "
            f"{len(self.path_ids)}; the area is defined for {N_PATHS_FOR_AREA} paths round "
            f"the zone"
        )
        self.time_points: dict[str, _TimePoint] = {}
        self.prompted = False
        experimenter.distances_entered.connect(self.enter)

    # -- written by the mapping procedure ------------------------------------------------

    def path_started(self, phase: str, path: int) -> None:
        """A path's pacing began. A path run again replaces its start."""
        point = self.time_points[phase]
        clock = self.session.clock
        point.starts[path] = (clock.wall_iso(), clock.t_session_s())
        if path in point.distances and path not in point.rows:
            self._write_path(phase, point, path)

    def restore(
        self,
        phase: str,
        starts: dict[int, tuple[str, float | None]],
        distances: dict[int, tuple[float, str]],
    ) -> None:
        """A time point carried over from a crashed session (SPEC.md 15, `tatp/resume.py`).

        Its paths were started, and some distances accepted, in the earlier files; those rows
        are already written there, so they are marked written here. What is still missing can
        be entered in this session, and the area is written when the last one arrives.
        """
        self.time_points[phase] = _TimePoint(
            self.n_paths, starts=dict(starts), distances=dict(distances), rows=set(distances)
        )
        self.session.log(
            "mapping_restored", severity="warning",
            detail=f"{phase}: {len(distances)} of {self.n_paths} distances already recorded",
        )
        self._show(phase, "", CONFIRMED)

    def open_time_point(self, phase: str) -> None:
        """`phase`'s mapping begins: from now its distances can be entered, in a column of the
        distances box of their own, whose empty fields say what is still to enter."""
        self.time_points.setdefault(phase, _TimePoint(self.n_paths))
        self.experimenter.set_mapping_phases([*self.time_points])

    # -- the experimenter's entries ----------------------------------------------------

    def enter(self, phase: str, distances: Sequence[float | None]) -> None:
        """Distances for one time point, None for any not yet measured. Never blocks.

        What became of them is said in the distances box (S, 21 Oct 2026): what was recorded
        or corrected, or why a value is queried -- inside the primary zone, or further than any
        border should be -- and that entering it again keeps it."""
        if len(distances) != self.n_paths:
            raise SessionError(
                f"{len(distances)} distances were entered for {phase!r}; there are "
                f"{self.n_paths} paths"
            )
        if phase not in self.time_points:
            raise SessionError(f"distances were entered for {phase!r}, which has no mapping")
        # A column of the box exists from the mapping's start, so a distance can be typed
        # before its path is walked: it is held, and its row written when the path starts.
        point = self.time_points[phase]
        words = self.experimenter.text["distances"]
        name = self.experimenter.text["timeline"][phase]
        queries, recorded, corrected_values = [], [], []
        corrected = False
        for path, value in enumerate(distances, start=1):
            if value is None:
                continue
            value = float(value)
            previous = point.distances.get(path)
            if previous is not None and previous[0] == value:
                continue  # the same value again changes nothing
            if not plausible(value, self.mapping) and point.queried.get(path) != value:
                # Queried, never silently accepted (SPEC.md 17.5): the same value entered again
                # is the confirmation.
                point.queried[path] = value
                self.session.log(
                    "distance_queried", origin="experimenter", severity="warning",
                    detail=f"{phase}, path {path}: {value} mm",
                )
                low_mm = float(self.mapping["distance_plausible_min_mm"])
                why = "inside_primary" if value < low_mm else "too_far"
                queries.append(words[why].format(phase=name, path=self.path_name(path),
                                                 value=f"{value:g}"))
                continue
            confirmed = point.queried.pop(path, None) == value
            point.distances[path] = (value, self.session.clock.wall_iso())
            shown = words["value"].format(path=self.short_path_name(path), value=f"{value:g}")
            if previous is None:
                recorded.append(shown)
                self.session.log(
                    "distance_entered", origin="experimenter",
                    severity="warning" if confirmed else "info",
                    detail=f"{phase}, path {path}: {value} mm"
                    + (" (confirmed outside the plausible range)" if confirmed else ""),
                )
            else:
                corrected = True
                corrected_values.append(shown)
                self.session.log(
                    "distance_corrected", origin="experimenter", severity="warning",
                    detail=f"{phase}, path {path}: {previous[0]} mm -> {value} mm",
                )
            if path in point.starts:
                self._write_path(phase, point, path)
        if queries:
            self._show(phase, " ".join(queries), QUERIED)
        elif recorded or corrected_values:
            lines = []
            if recorded:
                lines.append(words["recorded"].format(phase=name, values=", ".join(recorded)))
            if corrected_values:
                lines.append(words["corrected"].format(phase=name,
                                                       values=", ".join(corrected_values)))
            self._show(phase, " ".join(lines), CONFIRMED)
        if point.complete and (not point.area_written or corrected):
            self._write_area(phase, point)
        self.experimenter.refresh()

    def _show(self, phase: str, message: str, kind: str) -> None:
        """The box's fields for `phase` as the ledger holds them, and `message` under them."""
        point = self.time_points[phase]
        self.experimenter.distances.show_outcome(
            phase, {path: value for path, (value, _) in point.distances.items()},
            dict(point.queried), message, kind)

    # -- session end (SPEC.md 8.4) ------------------------------------------------------

    def outstanding(self) -> list[str]:
        return [phase for phase, point in self.time_points.items() if not point.area_written]

    def close(self) -> bool:
        """Call at session end. True when the session may close.

        The first call with anything outstanding prompts the experimenter and returns False.
        Any later call writes what there is, with every gap flagged missing, and returns True.
        """
        outstanding = self.outstanding()
        if outstanding and not self.prompted:
            self.prompted = True
            # Which are missing, and which wait for a confirmation (S, 21 Oct 2026).
            self.experimenter.set_instruction(
                instruction(self.session.config, "distances_outstanding",
                            missing=self.missing_text(outstanding)), NOW
            )
            self.experimenter.refresh()
            self.session.log(
                "distances_outstanding", severity="warning", detail=", ".join(outstanding)
            )
            return False
        for phase in outstanding:
            point = self.time_points[phase]
            for path in range(1, self.n_paths + 1):
                if path not in point.starts:
                    # No start means no row: `timestamp_iso` is the path's start, and inventing
                    # one would be inventing data. The distance, if any, is still in `sh_area`.
                    self.session.log(
                        "mapping_path_not_run", severity="warning",
                        detail=f"{phase}, path {path}",
                    )
                elif path not in point.rows:
                    self._write_path(phase, point, path)
            self._write_area(phase, point)
        return True

    def incomplete(self) -> list[str]:
        """Time points without all four distances: once closed, those recorded missing."""
        return [phase for phase, point in self.time_points.items() if not point.complete]

    def missing_text(self, phases: Sequence[str]) -> str:
        """Each of `phases`' distances still missing, and which wait for a confirmation, for
        the closing prompt and the session-complete page."""
        text = self.experimenter.text
        dialogs = text["dialogs"]
        parts = []
        for phase in phases:
            point = self.time_points[phase]
            paths = [dialogs["distance_to_confirm"].format(path=self.path_name(path))
                     if path in point.queried else self.path_name(path)
                     for path in range(1, self.n_paths + 1) if path not in point.distances]
            listed = (dialogs["distances_missing_all"]
                      if len(paths) == self.n_paths and not point.queried
                      else ", ".join(paths))
            parts.append(dialogs["distances_missing"].format(
                phase=text["timeline"][phase], paths=listed))
        return "; ".join(parts)

    # -- plumbing ----------------------------------------------------------------------

    def path_name(self, path: int) -> str:
        return self.experimenter.text["terms"]["mapping_paths"][self.path_ids[path - 1]]

    def short_path_name(self, path: int) -> str:
        """As the distances box's rows name it, for its own narrow message line."""
        return self.experimenter.text["terms"]["mapping_paths_short"][self.path_ids[path - 1]]

    def _write_path(self, phase: str, point: _TimePoint, path: int) -> None:
        start_iso, start_t = point.starts[path]
        distance = point.distances.get(path)
        self.session.files.write(
            "mapping",
            timestamp_iso=start_iso,
            t_session_s=start_t,
            phase=phase,
            path_id=self.path_ids[path - 1],
            step_interval_s=float(self.mapping["step_interval_s"]),
            step_size_mm=float(self.mapping["step_size_mm"]),
            distance_mm=None if distance is None else distance[0],
            distance_entered_iso=None if distance is None else distance[1],
            distance_missing=distance is None,
        )
        point.rows.add(path)

    def _write_area(self, phase: str, point: _TimePoint) -> None:
        clock = self.session.clock
        values = [point.distances.get(p, (None, None))[0] for p in range(1, self.n_paths + 1)]
        area = None if None in values else sh_area_mm2(values)
        self.session.files.write(
            "sh_area",
            timestamp_iso=clock.wall_iso(),
            t_session_s=clock.t_session_s(),
            phase=phase,
            distance_1_mm=values[0],
            distance_2_mm=values[1],
            distance_3_mm=values[2],
            distance_4_mm=values[3],
            area_mm2=area,
            area_missing=area is None,
        )
        point.area_written = True
        self.session.log(
            "sh_area_recorded", severity="info" if area is not None else "warning",
            detail=f"{phase}: " + ("missing" if area is None else f"{area:g} mm2"),
        )
        if area is not None:
            self.area_recorded.emit(phase, area)


@dataclass(frozen=True)
class MappingResult:
    """The pacing is done. The area arrives later, through the ledger."""

    phase: str
    paths_run: int


class AreaMapping(Procedure):
    """Pace the four mapping paths of one time point (SPEC.md 8.4). `finished` carries a
    `MappingResult`.

    `proceed_requested` starts each path and, pressed again, stops its cue train at the border.
    `pacing_cue` carries (path, cue) from 1 for every cue, and every cue is logged.

    The path, not the cue, is the step: the cue train runs on the procedure's timer without
    being a step of its own, so a resume repeats the whole path from its start.
    """

    pacing_cue = Signal(int, int)

    def __init__(self, rig: Rig, ledger: MappingLedger):
        super().__init__(rig)
        self.ledger = ledger
        self.mapping = self.session.config.study1["mapping"]
        self.n_paths = int(self.mapping["n_paths"])
        self.max_steps = int(self.mapping["max_steps"])
        self.step_interval_s = float(self.mapping["step_interval_s"])
        self.path = 0
        self.cue = 0
        self._first_cue_s: float | None = None

    def begin(self) -> None:
        self.session.log("mapping_started", detail=self.session.phase)
        # The distances can be entered from now on, for this time point and any earlier one.
        self.ledger.open_time_point(self.session.phase)
        self._await_path()

    def _standby(self) -> None:
        self.participant.show_message(STANDBY_SCREEN)

    def _await_path(self) -> None:
        self.path += 1
        if self.path > self.n_paths:
            # The borders are on the skin; what is left is measuring them, whenever convenient.
            self.experimenter.refresh()
            self.finish(MappingResult(self.session.phase, self.n_paths))
            return
        ready = self.instruction_text(
            "mapping_ready", index=self.path, count=self.n_paths,
            path=self.ledger.path_name(self.path),
        )
        # Read aloud before the first path; there is no participant mapping screen. Built
        # last, so the noise stays silent while it is up (`tatp.audio.NoiseGate`).
        if self.path == 1:
            text = f"{self.instruction_text('mapping_script')}\n\n{ready}"
        else:
            text = ready

        path_id = self.ledger.path_ids[self.path - 1]

        def prepare() -> None:
            self._standby()
            # The path to walk next on the diagram beside it (S, 21 Oct 2026).
            self.experimenter.set_instruction(text, PREPARE)
            # Not beside the script read aloud before the first path, which has the
            # instruction's whole width (LOG N7.F17e).
            if self.path > 1:
                self.experimenter.set_target(SECONDARY_ZONE, path=path_id)
            self.experimenter.set_status("")
            self.experimenter.refresh()

        self.await_proceed(lambda: self.step(self._start_path), prepare)

    def _start_path(self) -> None:
        """The step a resume repeats: the whole path, from its start."""
        self._standby()
        self.ledger.path_started(self.session.phase, self.path)
        self.session.log("mapping_path_started", origin="experimenter", detail=self._detail())
        self.experimenter.set_instruction(self.instruction_text(
            "mapping_path", path=self.ledger.path_name(self.path),
            step=f"{float(self.mapping['step_size_mm']):g}",
        ), NOW)
        self.experimenter.set_target(SECONDARY_ZONE, filament=True,
                                     path=self.ledger.path_ids[self.path - 1])
        self.experimenter.refresh()
        self.cue = 0
        self.on_proceed(self._stop_path)
        self._pace()

    def _pace(self) -> None:
        # Cue n is due (n - 1) step intervals after the path's first cue, so the cadence is
        # the configured one, not one lengthened by each cue's own log write (N7.U13).
        if self.cue == 0:
            self._first_cue_s = self.session.clock.elapsed_s()
        self.cue += 1
        # SPEC.md 10.5: timestamp every cue onset.
        self.session.log("pacing_cue", detail=f"{self._detail()}, cue {self.cue}")
        self.pacing_cue.emit(self.path, self.cue)
        # How far along the path is, so the end at the limit is no surprise (LOG N7.F17e).
        self.experimenter.set_status(self.experimenter.text["status"]["mapping_tick"].format(
            n=self.cue, max=self.max_steps))
        self.experimenter.refresh()
        next_s = self.session.clock.remaining_s(
            self._first_cue_s, self.cue * self.step_interval_s
        )
        if self.cue >= self.max_steps:
            self._after(next_s, self._reached_limit)
        else:
            self._after(next_s, self._pace)

    def _reached_limit(self) -> None:
        """No change reported within `max_steps` ticks: the path ends, and the experimenter is
        told, since the next path's instruction would otherwise replace it without a word
        (LOG N7.F17e)."""
        self.experimenter.set_warning(self.experimenter.text["warnings"]["mapping_limit"].format(
            path=self.ledger.path_name(self.path), max=self.max_steps))
        self._end_path("cue limit reached")

    def _stop_path(self) -> None:
        self._end_path("stopped by the experimenter")

    def _end_path(self, why: str) -> None:
        self._halt()
        self.on_proceed(None)
        self.session.log("mapping_path_ended", detail=f"{self._detail()}: {why}")
        self._await_path()

    def _detail(self) -> str:
        return f"{self.session.phase}, path {self.path}"
