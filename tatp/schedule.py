"""The session schedule. SPEC.md 7.

The twelve intervention blocks are **generated from parameters, then overridable per block**
(SPEC.md 7.1): `schedule.yaml`'s `generate:` section produces an evenly spaced alternating grid
and `overrides:` replaces the offset or the type of any individual block. The grid is data
rather than code because it is not settled and will change during piloting (SPEC.md 20 item 4).

**Validation warns and never blocks (SPEC.md 7.3).** Piloting will legitimately want irregular
schedules, so every rule here produces a sentence naming the block and the rule, and nothing
raises. That exception covers scheduling decisions only -- a malformed `overrides:` entry is a
configuration error and still stops the program, as SPEC.md 6 requires.

**Nothing here starts a block.** SPEC.md 7.4: the software times phases and displays countdowns,
the experimenter launches each block, and no block is ever skipped automatically. A `Block` is
therefore a plan, and the gap between `planned_offset_min` and the moment the experimenter
actually launched it is recorded rather than prevented -- `Session.start_block` writes it.

The warning strings are English literals rather than `config/text/` entries. They are operator
diagnostics on the same footing as the `detail` column of the log and the terminal warnings of
`run_session.py`, not screen text; SPEC.md 10.4 governs what is presented to a participant or
drawn on the experimenter window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from tatp.config import ConfigError

BLOCK_TYPES = ("pinprick", "touch")

S_PER_MIN = 60.0


@dataclass(frozen=True)
class Block:
    """One scheduled intervention block. `index` is 1-based and is what the data files record.

    The index is identity, not position: an override that moves a block later does not renumber
    it, because `block_index` in an already-written row has to keep meaning the same block.
    """

    index: int
    type: str
    planned_offset_min: float
    expected_duration_min: float | None
    overridden: bool

    @property
    def planned_offset_s(self) -> float:
        return self.planned_offset_min * S_PER_MIN

    @property
    def planned_end_min(self) -> float | None:
        """When the block is expected to finish, or None while the durations are unsettled."""
        if self.expected_duration_min is None:
            return None
        return self.planned_offset_min + self.expected_duration_min


@dataclass(frozen=True)
class Window:
    """A timed phase that is not a block -- sensitisation, capsaicin, the rekindle."""

    name: str
    start_min: float
    duration_min: float

    @property
    def end_min(self) -> float:
        return self.start_min + self.duration_min

    def contains(self, start_min: float, end_min: float | None) -> bool:
        """Whether a block starting at `start_min` runs into this window at all.

        The window is half-open, `[start, end)`, so a block that finishes exactly as the
        rekindle begins does not overlap it. A block whose duration is unknown is treated as an
        instant instead of as zero-length: "does it *begin* inside the window" is the part that
        can still be answered without the durations, and a block launched at the moment the
        rekindle starts collides with it however long it turns out to run.
        """
        if end_min is None:
            return self.start_min <= start_min < self.end_min
        return start_min < self.end_min and end_min > self.start_min


@dataclass(frozen=True)
class Schedule:
    """The generated grid, the windows around it, and the rules that check them."""

    blocks: tuple[Block, ...]
    windows: tuple[Window, ...]
    max_session_duration_min: float
    equal_spacing_tolerance_s: float

    @property
    def total_duration_min(self) -> float:
        """Session length from t=0, as far as the schedule knows about it.

        Everything before sensitisation (touch calibration, pre-sensitisation measures) is at a
        negative offset and is not scheduled; the post-intervention measures have no configured
        duration. So this is the end of the last thing the schedule places, and it is a lower
        bound on the session rather than the whole of it.
        """
        ends = [window.end_min for window in self.windows]
        for block in self.blocks:
            ends.append(block.planned_end_min or block.planned_offset_min)
        return max(ends)

    def window(self, name: str) -> Window:
        for window in self.windows:
            if window.name == name:
                return window
        raise KeyError(name)

    def block(self, index: int) -> Block:
        for block in self.blocks:
            if block.index == index:
                return block
        raise KeyError(index)

    # -- SPEC.md 7.3 -------------------------------------------------------------------

    def warnings(self) -> tuple[str, ...]:
        """Every scheduling rule this grid breaks. Never raises: warn, do not block."""
        found: list[str] = []
        found.extend(self._order_warnings())
        found.extend(self._window_warnings())
        found.extend(self._alternation_warnings())
        found.extend(self._spacing_warnings())
        found.extend(self._length_warnings())
        return tuple(found)

    def _order_warnings(self) -> list[str]:
        found = []
        unknown = [b.index for b in self.blocks if b.expected_duration_min is None]
        if unknown:
            found.append(
                "expected block durations are not set, so a block can only be checked against "
                "the moment it starts, not the time it occupies -- overlapping blocks are not "
                f"detected at all (open item 4); blocks affected: {_indices(unknown)}"
            )
        for previous, block in zip(self.blocks, self.blocks[1:], strict=False):
            if block.planned_offset_min < previous.planned_offset_min:
                found.append(
                    f"block {block.index} is planned for {block.planned_offset_min:g} min, "
                    f"before block {previous.index} at {previous.planned_offset_min:g} min"
                )
        found.extend(self._overlap_warnings())
        return found

    def _overlap_warnings(self) -> list[str]:
        """Blocks that run into each other.

        Asked of the blocks in the order they actually run, not in index order: an override can
        put block 1 after block 4, and two blocks that overlap need not be neighbours in the
        numbering. `reaches` is the block extending furthest into the session so far rather than
        simply the previous one, so a long block still catches a short one nested inside it.
        """
        found: list[str] = []
        reaches: Block | None = None
        for block in sorted(self.blocks, key=lambda b: (b.planned_offset_min, b.index)):
            if reaches is not None and block.planned_offset_min < reaches.planned_end_min:
                found.append(
                    f"block {block.index} starts at {block.planned_offset_min:g} min, while "
                    f"block {reaches.index} is still running until "
                    f"{reaches.planned_end_min:g} min"
                )
            end = block.planned_end_min
            if end is not None and (reaches is None or end > reaches.planned_end_min):
                reaches = block
        return found

    def _window_warnings(self) -> list[str]:
        found = []
        for window in self.windows:
            if window.name == "intervention":
                continue
            for block in self.blocks:
                if window.contains(block.planned_offset_min, block.planned_end_min):
                    found.append(
                        f"block {block.index} at {block.planned_offset_min:g} min falls in the "
                        f"{window.name} window, {window.start_min:g}-{window.end_min:g} min"
                    )
        # The intervention window bounds when a block may be *launched*, not when the last
        # rating must be in: the experimenter starts each block (SPEC.md 7.4) and the grid puts
        # the last one on the closing minute, so testing its end would warn on every grid.
        intervention = self.window("intervention")
        for block in self.blocks:
            offset = block.planned_offset_min
            if offset < intervention.start_min or offset > intervention.end_min:
                found.append(
                    f"block {block.index} at {offset:g} min lies outside the intervention, "
                    f"{intervention.start_min:g}-{intervention.end_min:g} min"
                )
        return found

    def _alternation_warnings(self) -> list[str]:
        """SPEC.md 7.1: the grid alternates and blocks are never back-to-back by type."""
        found = []
        for previous, block in zip(self.blocks, self.blocks[1:], strict=False):
            if block.type == previous.type:
                found.append(
                    f"blocks {previous.index} and {block.index} are both {block.type} blocks, "
                    f"so the grid does not alternate"
                )
        return found

    def _spacing_warnings(self) -> list[str]:
        found = []
        tolerance_min = self.equal_spacing_tolerance_s / S_PER_MIN
        for block_type in BLOCK_TYPES:
            same = [b for b in self.blocks if b.type == block_type]
            gaps = [
                (a, b, b.planned_offset_min - a.planned_offset_min)
                for a, b in zip(same, same[1:], strict=False)
                if not self._straddles_rekindle(a, b)
            ]
            if len(gaps) < 2:
                continue
            first = gaps[0][2]
            for _, block, gap in gaps[1:]:
                if abs(gap - first) > tolerance_min:
                    found.append(
                        f"{block_type} block {block.index} is {gap:g} min after the previous "
                        f"{block_type} block, where the others are {first:g} min apart"
                    )
        return found

    def _straddles_rekindle(self, earlier: Block, later: Block) -> bool:
        """Whether the rekindle falls between two blocks.

        The grid puts the rekindle and a margin either side of it in one gap on purpose
        (SPEC.md 7.1), so that gap is not evidence of uneven spacing and comparing it against
        the others would report the one intended irregularity as the rule being broken. Each
        half is regular in itself, and that is what the check measures. A check that always
        fires is a check nobody reads.
        """
        rekindle = self.window("rekindle")
        return (
            earlier.planned_offset_min <= rekindle.start_min
            and rekindle.end_min <= later.planned_offset_min
        )

    def _length_warnings(self) -> list[str]:
        total = self.total_duration_min
        if total > self.max_session_duration_min:
            return [
                f"the schedule runs to {total:g} min from t=0, over the configured maximum of "
                f"{self.max_session_duration_min:g} min"
            ]
        return []

    # -- SPEC.md 7.2 -------------------------------------------------------------------

    def preview_rows(self, t_zero: datetime) -> list[dict]:
        """One row per block: index, type, planned offset, wall clock, expected duration."""
        rows = []
        for block in self.blocks:
            rows.append(
                {
                    "index": block.index,
                    "type": block.type,
                    "planned_offset_min": block.planned_offset_min,
                    "planned_wall_clock": (
                        t_zero + timedelta(minutes=block.planned_offset_min)
                    ).strftime("%H:%M:%S"),
                    "expected_duration_min": block.expected_duration_min,
                    "overridden": block.overridden,
                }
            )
        return rows


def _indices(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers)


def _alternating(n_pinprick: int, n_touch: int, first: str) -> list[str]:
    """Types in order, taking from each pool in turn so the grid alternates (SPEC.md 7.1).

    Unequal pools cannot alternate all the way to the end. The remainder is appended rather
    than dropped or redistributed, and `_alternation_warnings` then names the join -- which is
    a scheduling decision to warn about, not a configuration error to refuse.
    """
    if first not in BLOCK_TYPES:
        raise ConfigError(
            f"schedule.yaml: generate.first_block_type is {first!r}, not one of "
            f"{list(BLOCK_TYPES)}"
        )
    pools = {"pinprick": n_pinprick, "touch": n_touch}
    order = [first, *(t for t in BLOCK_TYPES if t != first)]
    types: list[str] = []
    while sum(pools.values()):
        for block_type in order:
            if pools[block_type]:
                pools[block_type] -= 1
                types.append(block_type)
    return types


def _centred(n: int, low: float, high: float, spacing: float) -> list[float]:
    """`n` blocks `spacing` apart, with the window's spare time shared equally at both ends.

    Sharing it rather than packing against `low` is what buys the breathing room: the blocks
    sit clear of both edges of their window, so a block running over its estimate has somewhere
    to go before it hits whatever the window abuts.
    """
    if n == 0:
        return []
    margin = (high - low - (n - 1) * spacing) / 2.0
    # Whole minutes, because the experimenter reads these off a schedule and launches the block
    # by hand. Rounding down gives the spare half-minute to the end of the window rather than
    # the start, so nothing is pushed closer to whatever the window abuts.
    #
    # A negative margin means the blocks do not fit in the window. They then start at its
    # opening and overrun the far end, rather than being centred and spilling out of both --
    # overrunning the end of the session is a scheduling problem the warnings describe, whereas
    # spilling backwards would push a block into the rekindle, which is the one thing the split
    # exists to prevent.
    margin = math.floor(margin) if margin > 0 else 0.0
    return [low + margin + i * spacing for i in range(n)]


def _offsets(n: int, start: float, duration: float, generate: dict) -> list[float]:
    """Block offsets. SPEC.md 7.1.

    The rekindle divides the intervention into two windows. Blocks are split as evenly as
    possible between them -- with an odd count the later window takes the extra, because it is
    the post-rekindle half the design is most interested in -- and within each they sit
    `block_spacing_min` apart with the spare time shared at both ends.

    Spacing is its own parameter rather than `intervention_duration / n`. That derived value was
    exactly 10 min, which is 12 blocks filling all 120 minutes and leaving nothing for the
    rekindle, so the pause had to be borrowed from the front and left 1 min of margin ahead of
    the rekindle. Making spacing explicit is what creates the slack (S, 23 Aug 2026).
    """
    if n == 0:
        return []
    end = start + duration
    spacing = float(generate["block_spacing_min"])
    rekindle_start = float(generate["rekindle_offset_min"])
    rekindle_end = rekindle_start + float(generate["rekindle_duration_min"])
    # A rekindle outside the intervention divides nothing. Not a configuration error: piloting
    # may well want a session without one.
    if not start <= rekindle_start < end:
        return _centred(n, start, end, spacing)
    before = n // 2
    return _centred(before, start, rekindle_start, spacing) + _centred(
        n - before, rekindle_end, end, spacing
    )


def _durations(generate: dict, types: list[str]) -> dict[str, float | None]:
    """Expected duration per block type, which is null until the grid is settled."""
    declared = generate.get("expected_duration_min")
    if not isinstance(declared, dict):
        raise ConfigError(
            "schedule.yaml: generate.expected_duration_min must be a mapping of block type to "
            "minutes, with null for a duration that is not settled yet"
        )
    for block_type in sorted(set(types)):
        if block_type not in declared:
            raise ConfigError(
                f"schedule.yaml: generate.expected_duration_min has no entry for "
                f"{block_type!r}, which the grid contains"
            )
    # Checked here rather than in config.SCHEMA because null is a legitimate value while open
    # item 4 is open, which SCHEMA has no way to express. These are the two fields a human will
    # hand-edit the day it is resolved, so a wrong one has to name the file and the key
    # (SPEC.md 6) instead of surfacing later as a TypeError inside a warning string.
    for block_type, value in declared.items():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(
                f"schedule.yaml: generate.expected_duration_min.{block_type} is "
                f"{value!r}, expected a number of minutes or null"
            )
        if value < 0:
            raise ConfigError(
                f"schedule.yaml: generate.expected_duration_min.{block_type} is {value}, "
                f"below the minimum 0"
            )
    return dict(declared)


def _apply_override(block: Block, entry: dict, durations: dict[str, float | None]) -> Block:
    block_type = entry.get("type", block.type)
    if block_type not in BLOCK_TYPES:
        raise ConfigError(
            f"schedule.yaml: overrides entry for block {block.index} has type "
            f"{block_type!r}, not one of {list(BLOCK_TYPES)}"
        )
    offset = entry.get("offset_min", block.planned_offset_min)
    if not isinstance(offset, (int, float)) or isinstance(offset, bool):
        raise ConfigError(
            f"schedule.yaml: overrides entry for block {block.index} has offset_min "
            f"{offset!r}, which is not a number"
        )
    return Block(
        index=block.index,
        type=block_type,
        planned_offset_min=float(offset),
        expected_duration_min=durations[block_type],
        overridden=True,
    )


def generate(schedule_config: dict) -> Schedule:
    """Build the grid from `generate:`, then replace the blocks named in `overrides:`."""
    gen = schedule_config["generate"]
    types = _alternating(
        gen["n_pinprick_blocks"], gen["n_touch_blocks"], gen["first_block_type"]
    )
    durations = _durations(gen, types)

    # The grid is not settled (open item 4). If someone declares it settled, the durations the
    # preview and the overlap check need must have arrived with it.
    if gen.get("settled") and any(v is None for v in durations.values()):
        raise ConfigError(
            "schedule.yaml: generate.settled is set, but generate.expected_duration_min still "
            "contains null. A settled grid is one whose block durations are known."
        )

    start = float(gen["intervention_start_offset_min"])
    duration = float(gen["intervention_duration_min"])
    offsets = _offsets(len(types), start, duration, gen)
    blocks = [
        Block(
            index=i + 1,
            type=block_type,
            planned_offset_min=offsets[i],
            expected_duration_min=durations[block_type],
            overridden=False,
        )
        for i, block_type in enumerate(types)
    ]

    by_index = {block.index: block for block in blocks}
    for entry in schedule_config["overrides"] or []:
        index = entry.get("index")
        if index not in by_index:
            raise ConfigError(
                f"schedule.yaml: overrides names block {index!r}, but the grid has blocks "
                f"{_indices(sorted(by_index))}"
            )
        by_index[index] = _apply_override(by_index[index], entry, durations)

    windows = (
        Window("sensitisation", 0.0, float(gen["sensitisation_duration_min"])),
        Window(
            "capsaicin",
            float(gen["capsaicin_start_offset_min"]),
            float(gen["capsaicin_duration_min"]),
        ),
        Window(
            "rekindle",
            float(gen["rekindle_offset_min"]),
            float(gen["rekindle_duration_min"]),
        ),
        Window("intervention", start, float(gen["intervention_duration_min"])),
    )

    schedule = Schedule(
        blocks=tuple(by_index[i] for i in sorted(by_index)),
        windows=windows,
        max_session_duration_min=float(
            schedule_config["validation"]["max_session_duration_min"]
        ),
        equal_spacing_tolerance_s=float(
            schedule_config["validation"]["equal_spacing_tolerance_s"]
        ),
    )

    # Stage boundary (CLAUDE.md): everything downstream indexes blocks by these.
    assert len(schedule.blocks) == gen["n_pinprick_blocks"] + gen["n_touch_blocks"]
    assert len({b.index for b in schedule.blocks}) == len(schedule.blocks)
    return schedule
