"""Crash recovery: finding an open session and reading back what it had done. SPEC.md 15.

**An open session** is one whose latest session file has no `session_end_iso`. `Session.close`
writes that key on every ordinary ending, an abort and a closed window included, so only a
crash leaves it empty. Only the latest file counts: a resumed session writes new files, and the
file it resumed from stays open forever, so an earlier open file is history, not a crash.

**What "completed" means.** The session runner logs `stage_completed` with the stage's id as
each stage of the session ends (`tatp/session_runner.py`). A stage is one protocol at a time
point, a scheduled block, the rekindle, or one of the timed phases, so "resume from the last
completed block" becomes "resume at the first stage the log does not record as completed".
A block is additionally recorded in `blocks` when it ends; the two are written together.
Everything up to and including sensitisation happens before session t=0, so a crash before t=0
has no clock to keep and restarts the session from setup -- which is logged as that.

**What is reloaded, not redone.** The F40 estimates and the chosen filament
(`calibration_pinprick`), the touch calibration and the preferred pattern
(`touchcal_channels`), the masking check's level, the stop rehearsal, the ceiling ratings that
cap the time point in progress, the mapping distances still outstanding, and the RNG seed. Each
is read from every file in the resume chain, since a session resumed twice has its history in
three sets of files.

Nothing here writes. The files read are the crashed session's own, never overwritten (SPEC.md
14.3); the resumed session writes new ones that name the file they resumed from.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from tatp.touchcal_maths import Delivery

SESSION_SUFFIX = "session.csv"
STAGE_COMPLETED = "stage_completed"
SENSITISATION_STARTED = "sensitisation_started"
MAPPING_PATH_STARTED = "mapping_path_started"
PATH_MARKER = ", path "
CONDITIONS = ("sham", "ct_targeted", "participant_preferred")


def session_files(data_folder: Path, participant_code: str, session_number: int) -> list[Path]:
    """Every session file for this participant and session, oldest first (named by stamp)."""
    pattern = f"TATP1_*_P{participant_code}_S{session_number}_{SESSION_SUFFIX}"
    return sorted(data_folder.glob(pattern))


def table_path(session_file: Path, table: str) -> Path:
    """The same session's file for another table."""
    return session_file.with_name(session_file.name[: -len(SESSION_SUFFIX)] + f"{table}.csv")


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_session_values(session_file: Path) -> dict[str, str]:
    return {row["key"]: row["value"] for row in read_rows(session_file)}


def is_open(session_file: Path) -> bool:
    return not read_session_values(session_file).get("session_end_iso")


@dataclass(frozen=True)
class OpenSession:
    """What the launcher shows before offering to resume (SPEC.md 15)."""

    session_file: Path
    session_start_iso: str
    sensitisation_start_iso: str | None
    completed_stages: tuple[str, ...]


def find_open_session(
    data_folder: Path, participant_code: str, session_number: int
) -> OpenSession | None:
    files = session_files(data_folder, participant_code, session_number)
    if not files or not is_open(files[-1]):
        return None
    chain = _chain(files[-1])
    return OpenSession(
        session_file=files[-1],
        session_start_iso=read_session_values(chain[0])["session_start_iso"],
        sensitisation_start_iso=_sensitisation_start(chain),
        completed_stages=tuple(_completed(chain)),
    )


@dataclass(frozen=True)
class MappingPoint:
    """One time point's mapping as far as it got: starts, and distances already recorded."""

    starts: dict[int, tuple[str, float | None]] = field(default_factory=dict)
    distances: dict[int, tuple[float, str]] = field(default_factory=dict)
    area_written: bool = False


@dataclass(frozen=True)
class ResumeState:
    """Everything a resumed session reloads (SPEC.md 15). Built by `load`."""

    open: OpenSession
    rng_seed: int
    clock_speed: float
    completed_stages: frozenset[str]
    masking: tuple[float, bool, int, bool] | None
    stop_rehearsal_press_detected: bool | None
    f40_mn: dict[str, float]  # accepted estimate per time point (phase)
    chosen_filament_label_g: dict[str, str]
    deliveries: dict[str, Delivery] | None
    preferred_pattern: str | None
    # One per ceiling rating: (phase, block_index or None, region, site_index, applied label)
    intolerable: tuple[tuple[str, int | None, str, int, str], ...]
    mapping: dict[str, MappingPoint]

    @property
    def after_t_zero(self) -> bool:
        return self.open.sensitisation_start_iso is not None


def load(open_session: OpenSession, config, per_channel_pressure: bool) -> ResumeState:
    """Read the crashed session's history back from its files and every one it resumed from."""
    chain = _chain(open_session.session_file)
    first = read_session_values(chain[0])
    latest = read_session_values(chain[-1])
    setup = next((read_session_values(p) for p in reversed(chain)
                  if read_session_values(p).get("masking_confirmed")), None)
    rehearsal = next((read_session_values(p) for p in reversed(chain)
                      if read_session_values(p).get("stop_rehearsal_ran")), None)

    f40, chosen = {}, {}
    for row in _rows(chain, "calibration_pinprick"):
        if row["superseded"] == "false":
            f40[row["phase"]] = float(row["f40_mn"])
            chosen[row["phase"]] = row["chosen_filament_label_g"]

    deliveries, preferred = _deliveries(_rows(chain, "touchcal_channels"), config,
                                        per_channel_pressure)
    return ResumeState(
        open=open_session,
        rng_seed=int(first["rng_seed"]),
        clock_speed=float(latest["clock_speed"]),
        completed_stages=frozenset(open_session.completed_stages),
        masking=None if setup is None else (
            float(setup["white_noise_level_dbfs"]),
            setup["masking_confirmed"] == "true",
            int(setup["masking_attempts"]),
            setup["earplugs_used"] == "true",
        ),
        stop_rehearsal_press_detected=(
            None if rehearsal is None else rehearsal["stop_rehearsal_press_detected"] == "true"
        ),
        f40_mn=f40,
        chosen_filament_label_g=chosen,
        deliveries=deliveries,
        preferred_pattern=preferred,
        intolerable=tuple(
            (row["phase"], int(row["block_index"]) if row["block_index"] else None,
             row["region"], int(row["site_index"]), row["applied_filament_label_g"])
            for row in _rows(chain, "pinprick")
            if row["intolerable"] == "true"
        ),
        mapping=_mapping(chain, list(config.study1["mapping"]["path_ids"])),
    )


def previous_session_f40(
    data_folder: Path, participant_code: str, session_number: int, phase: str
) -> float | None:
    """The accepted estimate at `phase` in an earlier session, for the next prior (8.2)."""
    found = None
    for session_file in session_files(data_folder, participant_code, session_number):
        for row in read_rows(table_path(session_file, "calibration_pinprick")):
            if row["phase"] == phase and row["superseded"] == "false":
                found = float(row["f40_mn"])
    return found


# -- plumbing --------------------------------------------------------------------------------


def _chain(session_file: Path) -> list[Path]:
    """This file and every file it resumed from, oldest first."""
    chain = [session_file]
    while True:
        previous = read_session_values(chain[0]).get("resumed_from_session_file")
        if not previous:
            return chain
        path = session_file.with_name(previous)
        assert path.exists(), f"{chain[0].name} resumed from {previous}, which is not there"
        chain.insert(0, path)


def _rows(chain: list[Path], table: str) -> list[dict[str, str]]:
    return [row for path in chain for row in read_rows(table_path(path, table))]


def _completed(chain: list[Path]) -> list[str]:
    return [row["detail"] for row in _rows(chain, "log") if row["event"] == STAGE_COMPLETED]


def _sensitisation_start(chain: list[Path]) -> str | None:
    for row in _rows(chain, "log"):
        if row["event"] == SENSITISATION_STARTED:
            return row["detail"] or row["timestamp_iso"]
    return None


def _deliveries(rows, config, per_channel_pressure):
    """Each condition's delivery, from the last accepted calibration's channel rows."""
    if not rows:
        return None, None
    last_stamp = rows[-1]["timestamp_iso"]
    mine = [row for row in rows if row["timestamp_iso"] == last_stamp]
    preferred = mine[0]["participant_preferred_pattern"]
    patterns = dict(config.study1["patterns"]["condition_pattern"])
    patterns["participant_preferred"] = preferred
    deliveries = {}
    for condition in CONDITIONS:
        levels = {int(row["channel"]): float(row[f"{condition}_kpa"]) for row in mine}
        deliveries[condition] = Delivery(
            patterns[condition], levels if per_channel_pressure else None
        )
    return deliveries, preferred


def _mapping(chain: list[Path], path_ids: list[str]) -> dict[str, MappingPoint]:
    points: dict[str, MappingPoint] = {}
    for row in _rows(chain, "log"):
        if row["event"] == MAPPING_PATH_STARTED:
            path = int(row["detail"].rpartition(PATH_MARKER)[2])
            t_s = float(row["t_session_s"]) if row["t_session_s"] else None
            points.setdefault(row["phase"], MappingPoint()).starts[path] = (
                row["timestamp_iso"], t_s
            )
    for row in _rows(chain, "mapping"):
        if row["distance_mm"] and row["phase"] in points:
            path = path_ids.index(row["path_id"]) + 1
            points[row["phase"]].distances[path] = (
                float(row["distance_mm"]), row["distance_entered_iso"]
            )
    written = {row["phase"] for row in _rows(chain, "sh_area")}
    return {
        phase: MappingPoint(point.starts, point.distances, phase in written)
        for phase, point in points.items()
    }
