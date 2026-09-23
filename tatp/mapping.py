"""Secondary-hyperalgesia area mapping. SPEC.md 8.4.

**The software's only job during the mapping is the pacing cue.** It does not count steps and
does not record where the border fell -- that is a pen mark and a ruler. `AreaMapping` runs
the four paths: the experimenter starts each one, a cue fires every `step_interval_s` for up to
`max_steps` cues, and the experimenter stops it at the border. Each cue is logged and emitted
as `pacing_cue`, which is what Milestone 5 wires to the audible tick. The white noise is
switched off around the mapping by whoever runs it, not here.

**The distances never block.** They are typed whenever convenient, often long after the path,
so they are held by `MappingLedger`, which lives for the whole session and listens to the
experimenter's `distances_entered`. Once all four distances of a time point are in, it writes
the four `mapping` rows and the `sh_area` row. A distance outside the plausible range is
queried rather than accepted: the experimenter confirms it by entering the same value again.
At session end `MappingLedger.close()` prompts once for anything outstanding and, the next time
it is called, writes what there is with the gaps flagged missing.

**The area** is the rectangle spanned by the two pairs of opposite paths,
`(d1 + d3) x (d2 + d4)`, each distance measured from the centre of the primary zone. That is
how the heat-capsaicin literature computes it (docs/research/RB1-sh-area-formula.md). The
paths are numbered round the zone by `mapping.path_ids`, so 1 is opposite 3 and 2 opposite 4.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from tatp.procedure import Procedure, Rig
from tatp.session import Session, SessionError
from tatp.ui.experimenter import ExperimenterWindow

# A key in config/text/participant_*.yaml, not wording. There is no participant mapping
# screen; the participant is instructed and answers verbally (SPEC.md 8.4).
STANDBY_SCREEN = "standby"

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
    written: bool = False

    @property
    def complete(self) -> bool:
        return len(self.distances) == self.n_paths


class MappingLedger(QObject):
    """Every time point's mapping distances, for the whole session. One per session.

    `area_recorded` carries `(phase, area_mm2)` when a time point's rows are written with a
    computed area.
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
        """A path's pacing began. A path run again replaces its start (SPEC.md 13 resume)."""
        point = self.time_points.setdefault(phase, _TimePoint(self.n_paths))
        clock = self.session.clock
        point.starts[path] = (clock.wall_iso(), clock.t_session_s())

    # -- the experimenter's entries ----------------------------------------------------

    def enter(self, phase: str, distances: Sequence[float | None]) -> None:
        """Distances for one time point, None for any not yet measured. Never blocks."""
        if phase not in self.time_points:
            raise SessionError(f"distances were entered for {phase!r}, which has no mapping")
        if len(distances) != self.n_paths:
            raise SessionError(
                f"{len(distances)} distances were entered for {phase!r}; there are "
                f"{self.n_paths} paths"
            )
        point = self.time_points[phase]
        if point.written:
            self.session.log(
                "distances_already_recorded", origin="experimenter", severity="warning",
                detail=f"{phase}: {list(distances)}",
            )
            return
        warnings = []
        for path, value in enumerate(distances, start=1):
            if value is None or path in point.distances:
                continue
            value = float(value)
            if not plausible(value, self.mapping) and point.queried.get(path) != value:
                # Queried, never silently accepted (SPEC.md 17.5): the same value entered again
                # is the confirmation.
                point.queried[path] = value
                self.session.log(
                    "distance_queried", origin="experimenter", severity="warning",
                    detail=f"{phase}, path {path}: {value} mm",
                )
                warnings.append(
                    self.experimenter.text["warnings"]["distance_implausible"].format(
                        path=self.path_name(path), value=f"{value:g}"
                    )
                )
                continue
            confirmed = point.queried.pop(path, None) == value
            point.distances[path] = (value, self.session.clock.wall_iso())
            self.session.log(
                "distance_entered", origin="experimenter",
                severity="warning" if confirmed else "info",
                detail=f"{phase}, path {path}: {value} mm"
                + (" (confirmed outside the plausible range)" if confirmed else ""),
            )
        if warnings:
            self.experimenter.set_status(" ".join(warnings))
            self.experimenter.refresh()
        if point.complete:
            self._write(phase, point)

    # -- session end (SPEC.md 8.4) ------------------------------------------------------

    def outstanding(self) -> list[str]:
        return [phase for phase, point in self.time_points.items() if not point.written]

    def close(self) -> bool:
        """Call at session end. True when the session may close.

        The first call with anything outstanding prompts the experimenter and returns False.
        Any later call writes what there is, with every gap flagged missing, and returns True.
        """
        outstanding = self.outstanding()
        if outstanding and not self.prompted:
            self.prompted = True
            self.experimenter.set_instruction(
                self.experimenter.text["dialogs"]["distances_outstanding"]
            )
            self.experimenter.refresh()
            self.session.log(
                "distances_outstanding", severity="warning", detail=", ".join(outstanding)
            )
            return False
        for phase in outstanding:
            self._write(phase, self.time_points[phase])
        return True

    # -- plumbing ----------------------------------------------------------------------

    def path_name(self, path: int) -> str:
        return self.experimenter.text["terms"]["mapping_paths"][self.path_ids[path - 1]]

    def _write(self, phase: str, point: _TimePoint) -> None:
        clock = self.session.clock
        for path in range(1, self.n_paths + 1):
            if path not in point.starts:
                # No start means no row: `timestamp_iso` is the path's start, and inventing one
                # would be inventing data. The distance, if any, is still in `sh_area`.
                self.session.log(
                    "mapping_path_not_run", severity="warning", detail=f"{phase}, path {path}"
                )
                continue
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
        point.written = True
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
        self._on_go = None
        self.experimenter.proceed_requested.connect(self._on_proceed)

    def cancel(self) -> None:
        if self.running:
            self.experimenter.proceed_requested.disconnect(self._on_proceed)
        super().cancel()

    def finish(self, result: object) -> None:
        self.experimenter.proceed_requested.disconnect(self._on_proceed)
        super().finish(result)

    def begin(self) -> None:
        self.participant.show_message(STANDBY_SCREEN)
        self.session.log("mapping_started", detail=self.session.phase)
        self._await_path()

    def _await_path(self) -> None:
        self.path += 1
        if self.path > self.n_paths:
            self.finish(MappingResult(self.session.phase, self.n_paths))
            return
        text = self.experimenter.text["instructions"]
        ready = text["mapping_ready"].format(
            path=self.ledger.path_name(self.path), value=self.n_paths
        )
        # Read aloud before the first path; there is no participant mapping screen.
        instruction = f"{text['mapping_script']}\n\n{ready}" if self.path == 1 else ready

        def begin() -> None:
            self._on_go = self._start_path
            self.experimenter.set_instruction(instruction)
            self.experimenter.set_status("")
            self.experimenter.refresh()

        self.step(begin)

    def _start_path(self) -> None:
        self.ledger.path_started(self.session.phase, self.path)
        self.session.log("mapping_path_started", origin="experimenter", detail=self._detail())
        self.experimenter.set_instruction(
            self.experimenter.text["instructions"]["mapping_path"].format(
                path=self.ledger.path_name(self.path)
            )
        )
        self.experimenter.refresh()
        self.cue = 0
        self._on_go = self._stop_path
        self._pace()

    def _pace(self) -> None:
        self.cue += 1
        # SPEC.md 10.5: timestamp every cue onset.
        self.session.log("pacing_cue", detail=f"{self._detail()}, cue {self.cue}")
        self.pacing_cue.emit(self.path, self.cue)
        if self.cue >= self.max_steps:
            self.wait(self.step_interval_s, lambda: self._end_path("cue limit reached"))
        else:
            self.wait(self.step_interval_s, self._pace)

    def _stop_path(self) -> None:
        self._end_path("stopped by the experimenter")

    def _end_path(self, why: str) -> None:
        self._halt()
        self._on_go = None
        self.session.log("mapping_path_ended", detail=f"{self._detail()}: {why}")
        self._await_path()

    def _on_proceed(self) -> None:
        if self._on_go is None or self.rig.interruptions.active is not None:
            return
        then, self._on_go = self._on_go, None
        then()

    def _detail(self) -> str:
        return f"{self.session.phase}, path {self.path}"
