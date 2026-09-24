"""The pattern designer's logic, with no Qt. SPEC.md 12.2, 12.4.

`tools/design_pattern.py` is the window; everything it decides is decided here, so each rule is
tested directly rather than through widgets (as `VasState` and `AdjustmentState` are).

**One format, three ways in.** A pattern is composed as a tick grid, or as ordered channels
(hold times and a delay, in the prototype repository's three modes), or as timed channels
(onset and offset per channel). The last two are converted to the grid at the pattern's
`row_interval_ms`, and **a timing that does not fall on a row boundary is refused**, never
rounded: a rounded onset is a different velocity from the one that was typed.

**The loader's rules are the designer's rules.** Nothing here re-implements what makes a pattern
valid. A design is written out as the exact CSV and sidecar text a save would produce, and that
text goes through `patterns.from_text` -- the code `load_pattern` runs -- and `patterns.expand`.
So a pattern that would fail to load cannot be saved, and the prototype's silent-skip defect
(SPEC.md 12.4) is refused here by the same comparison that refuses it on loading.

**The prototype rig's command file.** `clearcode`, then `addcode:0x<mask>/<ms>` per run of
identical rows, with bit `channel_id` set for each channel on -- the format of the prototype
repository's `stim_files/` and of `Controller.Stimulus.to_file4arduino_timed`. Two differences
from that code, both deliberate:

- **The mask is written in lower-case hex.** The sketch's `parseUint32` accepts only `0-9` and
  `a-f`; the prototype's `modular_approach/stimulus.py` writes `{mask:X}`, and any mask with a
  letter in it would then be refused by the Arduino and silently skipped.
- **Trailing all-off rows are kept** as an `addcode:0x0/<ms>` step. The prototype drops them, so
  one `exec` there is shorter than one cycle of the pattern; here one `exec` is exactly one
  cycle, `Pattern.duration_s`, as the session plays it. Leading all-off rows are kept by both.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import yaml

from tatp.garment import patterns
from tatp.garment.patterns import Pattern, PatternError

# The prototype repository's three ways of turning ordered channels into timings
# (`modular_approach/README.txt`).
SEQUENTIAL = "sequential"
JOIN_HOLD = "join_hold"
JOIN_STAY = "join_stay"
MODES = (SEQUENTIAL, JOIN_HOLD, JOIN_STAY)

# The descriptive sidecar fields the example patterns carry. Read by nobody but a person: the
# CSV and `row_interval_ms` are authoritative (config/patterns/examples/README.md).
OPTIONAL_FIELDS = ("nominal_velocity_cm_s", "assumed_channel_spacing_cm", "overlap_rows")

# The name is also the file stem, so it is kept to what every file system takes unchanged.
NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")

# The prototype's shift register is 32 bits wide (`write32bits` in the sketch).
MASK_BITS = 32

COMMAND_CLEAR = "clearcode"
REFERENCE_TAB = "\t"
REFERENCE_COMMA = ","


class DesignError(Exception):
    """A design the designer refuses, with the reason as a text key and its values.

    The key indexes `designer.errors` in the experimenter text, so the reason is shown in the
    window's language rather than in the English of a developer message.
    """

    def __init__(self, key: str, **values: object):
        super().__init__(key, values)
        self.key = key
        self.values = values


@dataclass
class Design:
    """A pattern being edited: the grid and its sidecar, not yet validated."""

    name: str
    row_interval_ms: float
    channel_ids: tuple[int, ...]
    loop: bool
    rows: list[list[int]]
    # The optional descriptive fields and anything else a loaded sidecar carried, kept so that
    # re-saving a pattern does not drop what its author wrote.
    extras: dict = field(default_factory=dict)


# -- composing ------------------------------------------------------------------------------


def _exact(value: float | int | str) -> Fraction:
    """A typed number as an exact fraction: 0.3 is three tenths, not a binary neighbour."""
    return Fraction(str(value))


def row_index(value_ms: float, interval_ms: float) -> int:
    """`value_ms` in rows. Refused, never rounded, when it is not a whole number of rows."""
    value, interval = _exact(value_ms), _exact(interval_ms)
    if interval <= 0:
        raise DesignError("interval")
    if value < 0:
        raise DesignError("negative", value=_shown(value_ms))
    rows = value / interval
    if rows.denominator != 1:
        raise DesignError("off_grid", value=_shown(value_ms), interval=_shown(interval_ms))
    return rows.numerator


def ordered_spans(
    entries: Sequence[tuple[int, float]], delay_ms: float, mode: str
) -> list[tuple[int, Fraction, Fraction]]:
    """Ordered channels with hold times, as (channel, onset, offset) in ms.

    The three modes of the prototype repository's `modular_approach/README.txt`, which
    describes them but never implemented them, so the reading here is the build's:

    - `sequential`: each channel on and off in turn, the next starting `delay_ms` after the
      previous one ends. A delay of zero is the prototype's `generate_sequence`.
    - `join_hold`: each channel joins `delay_ms` after the previous one's onset and holds its
      own time.
    - `join_stay`: each joins `delay_ms` after the previous onset, and all go off together when
      the longest-lasting would have ended.
    """
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} is not one of {MODES}")
    delay = _exact(delay_ms)
    if delay < 0:
        raise DesignError("negative", value=_shown(delay_ms))
    if not entries:
        raise DesignError("nothing")
    spans = []
    onset = Fraction(0)
    for channel, hold_ms in entries:
        hold = _exact(hold_ms)
        if hold <= 0:
            raise DesignError("hold", channel=channel, value=_shown(hold_ms))
        spans.append((channel, onset, onset + hold))
        onset = onset + hold + delay if mode == SEQUENTIAL else onset + delay
    if mode == JOIN_STAY:
        end = max(offset for _, _, offset in spans)
        spans = [(channel, onset, end) for channel, onset, _ in spans]
    return spans


def timed_rows(
    spans: Sequence[tuple[int, float | Fraction, float | Fraction]],
    interval_ms: float,
    channel_ids: Sequence[int],
) -> list[list[int]]:
    """(channel, onset ms, offset ms) as grid rows, one column per `channel_ids` entry.

    The grid ends at the last offset: `patterns.expand` turns a channel still on in the final
    row off at the end of that row. A channel may have several on-periods, but two that touch
    or overlap are refused, because the grid would silently join them into one.
    """
    if not spans:
        raise DesignError("nothing")
    indexed = []
    for channel, onset_ms, offset_ms in spans:
        if channel not in channel_ids:
            raise DesignError("unknown_channel", channel=channel)
        if _exact(offset_ms) <= _exact(onset_ms):
            raise DesignError("empty_span", channel=channel, onset=_shown(onset_ms),
                              offset=_shown(offset_ms))
        indexed.append((channel, row_index(onset_ms, interval_ms),
                        row_index(offset_ms, interval_ms)))

    for channel in channel_ids:
        mine = sorted((start, end) for c, start, end in indexed if c == channel)
        for (_, end), (start, _) in zip(mine, mine[1:], strict=False):
            if start <= end:
                raise DesignError("overlap", channel=channel)

    n_rows = max(end for _, _, end in indexed)
    rows = [[0] * len(channel_ids) for _ in range(n_rows)]
    for channel, start, end in indexed:
        column = list(channel_ids).index(channel)
        for row in rows[start:end]:
            row[column] = 1
    return rows


def ordered_rows(
    entries: Sequence[tuple[int, float]],
    delay_ms: float,
    mode: str,
    interval_ms: float,
    channel_ids: Sequence[int],
) -> list[list[int]]:
    return timed_rows(ordered_spans(entries, delay_ms, mode), interval_ms, channel_ids)


def resized(
    rows: list[list[int]], old_ids: Sequence[int], new_ids: Sequence[int]
) -> list[list[int]]:
    """The grid under a new channel list: a kept channel keeps its column, a new one is off."""
    return [
        [row[list(old_ids).index(cid)] if cid in old_ids else 0 for cid in new_ids]
        for row in rows
    ]


# -- validating, saving and loading ---------------------------------------------------------


def csv_text(design: Design) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(design.channel_ids)
    writer.writerows(design.rows)
    return buffer.getvalue()


def sidecar_text(design: Design) -> str:
    meta = {
        "name": design.name,
        "row_interval_ms": float(design.row_interval_ms),
        "channel_ids": list(design.channel_ids),
        "loop": design.loop,
        **{key: value for key, value in design.extras.items() if value is not None},
    }
    return yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)


def csv_path(design: Design, folder: Path) -> Path:
    return folder / f"{design.name}.csv"


def validate(design: Design, folder: Path) -> Pattern:
    """The pattern this design would load as, from `folder`. Refuses what would not load.

    The name and the row interval are checked here because the loader takes both on trust: a
    name is also a file name, and an interval of zero loads but has no duration to play.
    """
    if not NAME_PATTERN.fullmatch(design.name):
        raise DesignError("name")
    if not design.row_interval_ms > 0:
        raise DesignError("interval")
    path = csv_path(design, folder)
    try:
        pattern = patterns.from_text(csv_text(design), sidecar_text(design), path)
    except PatternError as error:
        raise DesignError("not_loadable", value=str(error)) from error
    patterns.expand(pattern)
    return pattern


def save(design: Design, folder: Path, overwrite: bool = False) -> Pattern:
    """Write the CSV and its sidecar into `folder`, and prove they load back unchanged."""
    pattern = validate(design, folder)
    target = csv_path(design, folder)
    sidecar = target.with_suffix(".yaml")
    if not overwrite and (target.exists() or sidecar.exists()):
        raise DesignError("exists", value=target.name)
    # `load_folder` refuses two patterns of one name, so a clash would break the whole folder.
    for other in sorted(folder.glob("*.csv")):
        if other == target:
            continue
        try:
            name = patterns.load_pattern(other).name
        except PatternError as error:
            raise DesignError("folder_unreadable", value=str(error)) from error
        if name == design.name:
            raise DesignError("name_taken", value=other.name)
    target.write_text(csv_text(design), encoding="utf-8", newline="")
    sidecar.write_text(sidecar_text(design), encoding="utf-8")
    loaded = patterns.load_pattern(target)
    # Stage boundary (CLAUDE.md): what is on disk is what was validated, or nothing is trusted.
    assert loaded == pattern, f"{target.name} did not load back as it was saved"
    return loaded


def from_pattern(pattern: Pattern) -> Design:
    """A loaded pattern as a design, with its sidecar's other fields kept."""
    meta = yaml.safe_load(pattern.source.with_suffix(".yaml").read_text(encoding="utf-8"))
    return Design(
        name=pattern.name,
        row_interval_ms=pattern.row_interval_ms,
        channel_ids=pattern.channel_ids,
        loop=pattern.loop,
        rows=[list(row) for row in pattern.rows],
        extras={k: v for k, v in meta.items() if k not in patterns.SIDECAR_KEYS},
    )


def open_pattern(path: Path) -> Design:
    return from_pattern(patterns.load_pattern(path))


def from_reference_csv(path: Path, column_ms: float, loop: bool) -> Design:
    """The prototype repository's horizontal CSV: one line per channel, its bit id first.

    `Controller.Stimulus.from_csv_matrix` reads it with a column duration given at upload, so
    the file carries none and the designer asks for one. The cells are transposed as text and
    go through `patterns.from_text`, so a `2` or a `0.5` is refused here as it is on loading --
    the prototype parses both with `int()`. The delimiter rule is the prototype's own: a tab if
    the first line has one, else a comma.
    """
    if not _exact(column_ms) > 0:
        raise DesignError("interval")
    text = path.read_bytes().decode("utf-8")
    if not text.strip():
        raise DesignError("nothing")
    delimiter = REFERENCE_TAB if REFERENCE_TAB in text.splitlines()[0] else REFERENCE_COMMA
    lines = []
    for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
        cells = [cell.strip() for cell in row]
        # A trailing delimiter, as a spreadsheet writes one, is dropped as the prototype drops
        # it. An empty cell anywhere else is kept, and refused below as not 0 or 1: the
        # prototype drops those too, which shifts every later step one column earlier.
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            lines.append(cells)
    width = len(lines[0])
    for number, line in enumerate(lines, start=1):
        if len(line) != width:
            raise DesignError("ragged", line=number, value=len(line), expected=width)
    header = [line[0] for line in lines]
    columns = [line[1:] for line in lines]
    grid = [header] + [list(step) for step in zip(*columns, strict=True)]
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(grid)
    sidecar = yaml.safe_dump({
        "name": path.stem, "row_interval_ms": float(column_ms),
        "channel_ids": [int(cid) if cid.lstrip("-").isdigit() else cid for cid in header],
        "loop": loop,
    })
    try:
        pattern = patterns.from_text(buffer.getvalue(), sidecar, path.with_suffix(".csv"))
    except PatternError as error:
        raise DesignError("not_loadable", value=str(error)) from error
    patterns.expand(pattern)
    return Design(
        name=path.stem, row_interval_ms=pattern.row_interval_ms,
        channel_ids=pattern.channel_ids, loop=loop, rows=[list(r) for r in pattern.rows],
    )


# -- previewing -----------------------------------------------------------------------------


def on_periods(pattern: Pattern) -> dict[int, list[tuple[float, float]]]:
    """Each channel's on-periods in seconds over one cycle, from `patterns.expand`."""
    periods: dict[int, list[tuple[float, float]]] = {cid: [] for cid in pattern.channel_ids}
    started: dict[int, float] = {}
    for event in patterns.expand(pattern):
        if event.on:
            started[event.channel_id] = event.t_s
        else:
            periods[event.channel_id].append((started.pop(event.channel_id), event.t_s))
    return periods


# -- the prototype rig's command file -------------------------------------------------------


def command_steps(pattern: Pattern, max_steps: int, max_step_ms: int) -> list[tuple[int, int]]:
    """(mask, ms) per step: runs of identical rows merged, over one whole cycle.

    A run longer than the sketch's uint16 delay is split into steps of the same mask, which
    re-latches the same state and changes nothing the participant feels.
    """
    for channel in pattern.channel_ids:
        if not 0 <= channel < MASK_BITS:
            raise DesignError("bit_range", channel=channel)
    interval = _exact(pattern.row_interval_ms)
    runs: list[list[int]] = []
    for row in pattern.rows:
        mask = sum(1 << cid for cid, on in zip(pattern.channel_ids, row, strict=True) if on)
        if runs and runs[-1][0] == mask:
            runs[-1][1] += 1
        else:
            runs.append([mask, 1])
    steps = []
    for mask, n_rows in runs:
        duration = interval * n_rows
        if duration.denominator != 1:
            raise DesignError("not_whole_ms", value=_shown(float(duration)))
        remaining = duration.numerator
        while remaining > 0:
            steps.append((mask, min(remaining, max_step_ms)))
            remaining -= max_step_ms
    if len(steps) > max_steps:
        raise DesignError("too_many_steps", value=len(steps), limit=max_steps)
    return steps


def command_file(pattern: Pattern, max_steps: int, max_step_ms: int) -> str:
    """The file the prototype's own scripts send line by line before `exec`."""
    lines = [COMMAND_CLEAR]
    lines += [f"addcode:0x{mask:x}/{ms}" for mask, ms in command_steps(
        pattern, max_steps, max_step_ms)]
    return "\n".join(lines)


def _shown(value: float | int | Fraction | str) -> str:
    number = float(value)
    return f"{number:g}"
