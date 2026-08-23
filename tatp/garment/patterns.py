"""Loading and expanding tick-grid patterns. SPEC.md 12.2, 12.4.

The CSV is the interface for humans and the thing stored, versioned and hashed into the session
file. One column per channel, one row per time step, 1 for on and 0 for off, with the row
interval carried in a sidecar YAML because it is a per-pattern parameter, not a fixed tick rate.

SPEC.md 12.4 names a defect in the existing repository's loader that must not be inherited: it
parses each cell with `int()` and then tests `== 1` and `== 0`, so a cell of `2` matches neither
test and is silently skipped -- if the channel was already on it never receives its offset and
stays pressurised. Two things here answer that directly. Cell values are compared as text and
anything that is not exactly `0` or `1` is refused, and `expand()` asserts that every channel
that turns on also turns off.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import yaml

SIDECAR_KEYS = ("name", "row_interval_ms", "channel_ids", "loop")


class PatternError(Exception):
    """A pattern file is malformed. Always fatal -- a misread pattern is the wrong stimulus."""


@dataclass(frozen=True)
class Pattern:
    name: str
    channel_ids: tuple[int, ...]
    rows: tuple[tuple[int, ...], ...]
    row_interval_ms: float
    loop: bool
    source: Path

    @property
    def duration_s(self) -> float:
        """One cycle, including the trailing row that returns the last channel to off.

        A pattern whose final row still has channels on is a full row long at the end, not
        instantaneous, so the cycle is one row longer than the grid.
        """
        return len(self.rows) * self.row_interval_ms / 1000.0


@dataclass(frozen=True)
class ChannelEvent:
    t_s: float
    channel_id: int
    on: bool


def load_pattern(csv_path: Path) -> Pattern:
    """Read one pattern and its sidecar. The sidecar has the same stem with a .yaml suffix."""
    sidecar = csv_path.with_suffix(".yaml")
    if not csv_path.exists():
        raise PatternError(f"{csv_path} does not exist")
    if not sidecar.exists():
        raise PatternError(
            f"{csv_path.name} has no sidecar {sidecar.name}. The row interval is a per-pattern "
            f"parameter and is not defaulted (SPEC.md 12.2)."
        )
    meta = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise PatternError(f"{sidecar.name}: expected a mapping at the top level")
    missing = [key for key in SIDECAR_KEYS if meta.get(key) is None]
    if missing:
        raise PatternError(f"{sidecar.name}: {missing} are missing or null")

    with csv_path.open(encoding="utf-8", newline="") as handle:
        grid = [row for row in csv.reader(handle) if row]
    if len(grid) < 2:
        raise PatternError(f"{csv_path.name}: needs a channel-id header and at least one row")

    header = [cell.strip() for cell in grid[0]]
    if not all(cell.lstrip("-").isdigit() for cell in header):
        raise PatternError(f"{csv_path.name}: header {header} is not a list of channel ids")
    channel_ids = tuple(int(cell) for cell in header)
    if len(set(channel_ids)) != len(channel_ids):
        raise PatternError(f"{csv_path.name}: header repeats a channel id: {list(channel_ids)}")
    if tuple(meta["channel_ids"]) != channel_ids:
        raise PatternError(
            f"{sidecar.name}: channel_ids {meta['channel_ids']} do not match the CSV header "
            f"{list(channel_ids)}"
        )

    rows = []
    for number, raw in enumerate(grid[1:], start=2):
        cells = [cell.strip() for cell in raw]
        if len(cells) != len(channel_ids):
            raise PatternError(
                f"{csv_path.name} line {number}: {len(cells)} cells, expected "
                f"{len(channel_ids)}"
            )
        for column, cell in enumerate(cells):
            # Compared as text on purpose: `int()` would accept 2, 01 and -0, and 2 is exactly
            # the value that silently skips both the onset and the offset test (SPEC.md 12.4).
            if cell not in ("0", "1"):
                raise PatternError(
                    f"{csv_path.name} line {number}, channel {channel_ids[column]}: cell "
                    f"{cell!r} is not 0 or 1"
                )
        rows.append(tuple(int(cell) for cell in cells))

    return Pattern(
        name=str(meta["name"]),
        channel_ids=channel_ids,
        rows=tuple(rows),
        row_interval_ms=float(meta["row_interval_ms"]),
        loop=bool(meta["loop"]),
        source=csv_path,
    )


def load_folder(folder: Path) -> dict[str, Pattern]:
    """Every pattern in a folder, by name. The experimenter selects a folder (SPEC.md 12.2)."""
    if not folder.is_dir():
        raise PatternError(f"{folder} is not a folder")
    patterns: dict[str, Pattern] = {}
    for csv_path in sorted(folder.glob("*.csv")):
        pattern = load_pattern(csv_path)
        if pattern.name in patterns:
            raise PatternError(
                f"{folder}: two patterns are named {pattern.name!r} "
                f"({patterns[pattern.name].source.name} and {csv_path.name})"
            )
        patterns[pattern.name] = pattern
    if not patterns:
        raise PatternError(f"{folder} contains no patterns")
    return patterns


def expand(pattern: Pattern) -> tuple[ChannelEvent, ...]:
    """The tick grid as timed channel events, so a driver is not tied to the tick rate.

    A channel still on in the final row is turned off at the end of that row, which is what
    makes one cycle `duration_s` long and what guarantees the on/off pairing below.
    """
    interval_s = pattern.row_interval_ms / 1000.0
    events: list[ChannelEvent] = []
    previous = [0] * len(pattern.channel_ids)
    for index, row in enumerate([*pattern.rows, (0,) * len(pattern.channel_ids)]):
        for column, value in enumerate(row):
            if value != previous[column]:
                events.append(
                    ChannelEvent(index * interval_s, pattern.channel_ids[column], value == 1)
                )
        previous = list(row)

    # Stage boundary (CLAUDE.md), and the direct answer to the defect in SPEC.md 12.4: a
    # channel that turns on and never turns off stays pressurised.
    for channel_id in pattern.channel_ids:
        ons = sum(1 for e in events if e.channel_id == channel_id and e.on)
        offs = sum(1 for e in events if e.channel_id == channel_id and not e.on)
        assert ons == offs, f"{pattern.name}: channel {channel_id} has {ons} on, {offs} off"
    return tuple(events)
