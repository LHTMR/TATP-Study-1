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
import io
from dataclasses import dataclass
from pathlib import Path

import yaml

from tatp.units import MS_PER_S

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
        return len(self.rows) * self.row_interval_ms / MS_PER_S


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
    # Bytes decoded rather than `read_text`, so line endings reach the CSV reader exactly as
    # `open(newline="")` would hand them over.
    return from_text(
        csv_path.read_bytes().decode("utf-8"), sidecar.read_text(encoding="utf-8"), csv_path
    )


def from_text(csv_text: str, sidecar_text: str, csv_path: Path) -> Pattern:
    """Every rule `load_pattern` applies, on the text of a pattern and its sidecar.

    `load_pattern` reads the two files and calls this, so a pattern held in memory -- the
    designer's, before it is saved -- is refused by exactly the code that would refuse it on
    loading, not by a second copy of the rules. `csv_path` names the pattern in messages and
    becomes its `source`.
    """
    sidecar = csv_path.with_suffix(".yaml")
    meta = yaml.safe_load(sidecar_text)
    if not isinstance(meta, dict):
        raise PatternError(f"{sidecar.name}: expected a mapping at the top level")
    missing = [key for key in SIDECAR_KEYS if meta.get(key) is None]
    if missing:
        raise PatternError(f"{sidecar.name}: {missing} are missing or null")

    grid = [row for row in csv.reader(io.StringIO(csv_text, newline="")) if row]
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
    events = [event for _, event in _indexed_events(pattern)]

    # Stage boundary (CLAUDE.md), and the direct answer to the defect in SPEC.md 12.4: a
    # channel that turns on and never turns off stays pressurised.
    for channel_id in pattern.channel_ids:
        ons = sum(1 for e in events if e.channel_id == channel_id and e.on)
        offs = sum(1 for e in events if e.channel_id == channel_id and not e.on)
        assert ons == offs, f"{pattern.name}: channel {channel_id} has {ons} on, {offs} off"
    return tuple(events)


def loop_events(pattern: Pattern) -> tuple[tuple[ChannelEvent, ...], tuple[ChannelEvent, ...]]:
    """The events of the first cycle and of every later one, for a pattern that loops.

    A channel that is on in both the last row and the first is held on across the wrap. Played
    from `expand` alone it would be switched off at the end of each cycle and on again at the
    start of the next, so a one-row static pattern -- the sham -- would be commanded off and on
    every row interval: a pulsing stimulus rather than a static one, and a `garment` row per
    channel per interval for the whole intervention. So the first cycle keeps its onsets and
    drops those channels' final offsets, and later cycles drop both. The offsets are not lost:
    `GarmentController.stop_pattern` and `stop` switch off every channel left on.
    """
    events = expand(pattern)
    if not pattern.loop:
        return events, events
    first, last = pattern.rows[0], pattern.rows[-1]
    held = {cid for cid, a, b in zip(pattern.channel_ids, first, last, strict=True) if a and b}
    # By row index, not by time: `index * interval` is a float, and equality on it would drop
    # or keep an event depending on rounding.
    end_row = len(pattern.rows)
    indexed = [(i, e) for i, e in _indexed_events(pattern)
               if not (e.channel_id in held and i == end_row)]
    first_cycle = tuple(e for _, e in indexed)
    later = tuple(e for i, e in indexed if not (e.channel_id in held and i == 0))
    return first_cycle, later


def _indexed_events(pattern: Pattern) -> list[tuple[int, ChannelEvent]]:
    """Each channel change with the row it happens at; the trailing all-off row included."""
    interval_s = pattern.row_interval_ms / MS_PER_S
    events: list[tuple[int, ChannelEvent]] = []
    previous = [0] * len(pattern.channel_ids)
    for index, row in enumerate([*pattern.rows, (0,) * len(pattern.channel_ids)]):
        for column, value in enumerate(row):
            if value != previous[column]:
                events.append((index, ChannelEvent(
                    index * interval_s, pattern.channel_ids[column], value == 1
                )))
        previous = list(row)
    return events
