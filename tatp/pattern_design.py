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

**A re-saved sidecar keeps what its author wrote.** The fields the designer owns are rewritten
in place, line by line, and every other line -- comments, null fields, keys the designer does
not know -- is kept exactly, as `tatp/instruments.py` does for `filaments.yaml`. A pattern with
no sidecar yet gets a fresh one. An opened pattern is saved back to its own file, so a neutral
file name that differs from the pattern's `name` survives a re-save.

**Numbers are shown losslessly** (`shown`): a float as its `repr`, an int as an int. A number
shown to six significant figures and read back would silently change a row interval of
1000/12 ms on the next save.

**Channels are not bits.** A pattern addresses the sleeve's channels 1-5, distal to proximal,
as the session does. The prototype's files address shift-register bits. `wiring` is the map
between them, `hardware.yaml`'s `garment.prototype.channel_bits`, the same one the
`arduino_mosfet` driver plays through, so an imported prototype CSV arrives in channels and an
exported command file fires the bits the sleeve is wired to. A bit or a channel outside the
wiring is refused, never passed through: a pattern on an unwired bit plays nothing.

**The prototype rig's command file.** `clearcode`, then `addcode:0x<mask>/<ms>` per run of
identical rows, with each on channel's bit set -- the format of the prototype repository's
`stim_files/` and of `Controller.Stimulus.to_file4arduino_timed`. Two differences from that
code, both deliberate:

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
import math
import re
from collections.abc import Mapping, Sequence
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
# Everything in a sidecar the designer writes. Any other key is the author's and is kept.
OWNED_FIELDS = (*patterns.SIDECAR_KEYS, *OPTIONAL_FIELDS)

# The name is also the file stem of a new pattern, so it is kept to what every file system
# takes unchanged.
NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")

# A top-level `key: value  # comment` line, the one sidecar shape rewritten in place. The value
# is a flow list, a quoted string or a plain scalar; the comment is kept.
SIDECAR_LINE = (
    r"^(?P<head>{key}:[ \t]*)"
    r"(?P<value>\[[^\]]*\]|\"[^\"]*\"|'[^']*'|[^#\s](?:[^#]*[^#\s])?)?"
    r"(?P<tail>[ \t]*(?:#.*)?)$"
)

COMMAND_CLEAR = "clearcode"
REFERENCE_TAB = "\t"
REFERENCE_COMMA = ","
DECIMAL_COMMA = ","
DECIMAL_POINT = "."
BOM = "﻿"
# Wide enough that PyYAML never folds a rewritten value onto a second line.
YAML_LINE_WIDTH = 1_000_000


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
    # The optional descriptive fields, None where not given.
    extras: dict = field(default_factory=dict)
    # Where it was opened from, so Save writes back there, and the sidecar text it had, so a
    # re-save keeps the author's comments and fields. None for a pattern not yet saved.
    path: Path | None = None
    sidecar_source: str | None = None


# -- numbers --------------------------------------------------------------------------------


def shown(value: object) -> str:
    """A number as text that reads back as exactly the same number.

    `repr` for a float, because `:g` keeps six significant figures and 1000/12 would come back
    as 83.3333. An exact fraction that is whole is shown as an int.
    """
    if isinstance(value, Fraction):
        return str(value.numerator) if value.denominator == 1 else repr(float(value))
    if isinstance(value, float):
        return repr(value)
    return str(value)


def parse_number(text: str, field_name: str) -> int | float:
    """A typed number, with either decimal mark. Refuses blank, non-numbers and non-finite.

    A whole number typed without a decimal mark stays an int, so `overlap_rows: 1` is saved
    back as it was written rather than as 1.0.
    """
    typed = text.strip().replace(DECIMAL_COMMA, DECIMAL_POINT)
    if not typed:
        raise DesignError("required", field=field_name)
    try:
        value: int | float = int(typed)
    except ValueError:
        try:
            value = float(typed)
        except ValueError:
            raise DesignError("number", field=field_name, value=text) from None
    if not _finite(value):
        raise DesignError("not_finite", field=field_name, value=text)
    return value


def _finite(value: object) -> bool:
    # An int too large for a float overflows rather than reporting itself infinite.
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


# -- composing ------------------------------------------------------------------------------


def _exact(value: float | int | Fraction) -> Fraction:
    """A number as an exact fraction: 0.3 is three tenths, not a binary neighbour."""
    if isinstance(value, Fraction):
        return value
    if not _finite(value):
        raise DesignError("not_finite_value", value=shown(value))
    return Fraction(str(value))


def row_index(value_ms: float, interval_ms: float) -> int:
    """`value_ms` in rows. Refused, never rounded, when it is not a whole number of rows."""
    value, interval = _exact(value_ms), _exact(interval_ms)
    if interval <= 0:
        raise DesignError("interval")
    if value < 0:
        raise DesignError("negative", value=shown(value_ms))
    rows = value / interval
    if rows.denominator != 1:
        raise DesignError("off_grid", value=shown(value_ms), interval=shown(interval_ms))
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
        raise DesignError("negative", value=shown(delay_ms))
    if not entries:
        raise DesignError("nothing")
    spans = []
    onset = Fraction(0)
    for channel, hold_ms in entries:
        hold = _exact(hold_ms)
        if hold <= 0:
            raise DesignError("hold", channel=channel, value=shown(hold_ms))
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
            raise DesignError("empty_span", channel=channel, onset=shown(onset_ms),
                              offset=shown(offset_ms))
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


# -- the files ------------------------------------------------------------------------------


def csv_text(design: Design) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(design.channel_ids)
    writer.writerows(design.rows)
    return buffer.getvalue()


def _owned(design: Design) -> dict:
    """The sidecar fields the designer writes, in order. None where an optional one is blank."""
    return {
        "name": design.name,
        "row_interval_ms": float(design.row_interval_ms),
        "channel_ids": list(design.channel_ids),
        "loop": design.loop,
        **{key: design.extras.get(key) for key in OPTIONAL_FIELDS},
    }


def _flow(value: object) -> str:
    """`value` as a one-line YAML scalar or flow list, in YAML's own spelling of it."""
    return yaml.safe_dump([value], default_flow_style=True, allow_unicode=True,
                          width=YAML_LINE_WIDTH).strip()[1:-1]


def sidecar_text(design: Design) -> str:
    """The sidecar a save writes: a fresh one, or the loaded one, its owned fields rewritten.

    An owned field on a line of its own is rewritten in place with its comment kept. One the
    file does not have is appended, unless it is a blank optional field. Anything else the
    file holds is kept as written, and the result is parsed and compared with what was meant:
    a sidecar laid out some other way is refused rather than rewritten wrongly.
    """
    owned = _owned(design)
    if design.sidecar_source is None:
        # One `key: value` line each, in the examples' style, so a later re-save can rewrite
        # every field in place.
        return "".join(f"{k}: {_flow(v)}\n" for k, v in owned.items() if v is not None)

    old = yaml.safe_load(design.sidecar_source)
    if not isinstance(old, dict):
        raise DesignError("sidecar_layout", value=design.path.name if design.path else "")
    written = set()
    lines = []
    for line in design.sidecar_source.splitlines(keepends=True):
        ending = line[len(line.rstrip("\r\n")):]
        body = line[: len(line) - len(ending)]
        for key, value in owned.items():
            match = re.match(SIDECAR_LINE.format(key=re.escape(key)), body)
            if match is not None:
                body = f"{match['head']}{_flow(value)}{match['tail']}"
                written.add(key)
        lines.append(body + ending)
    text = "".join(lines)
    missing = [k for k, v in owned.items() if k not in written and v is not None]
    if missing:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "".join(f"{key}: {_flow(owned[key])}\n" for key in missing)

    # Stage boundary (CLAUDE.md): the rewrite holds exactly what was meant, or is not written.
    expected = {**old, **{k: v for k, v in owned.items() if k in old or v is not None}}
    try:
        rewritten = yaml.safe_load(text)
    except yaml.YAMLError:
        rewritten = None
    if rewritten != expected:
        raise DesignError("sidecar_layout", value=design.path.name if design.path else "")
    return text


def csv_path(design: Design, folder: Path) -> Path:
    """Where Save As writes a pattern: its name is its file stem."""
    return folder / f"{design.name}.csv"


def target_of(design: Design, folder: Path | None) -> Path:
    """Where the design validates from: its own file once it has one."""
    return design.path if design.path is not None else csv_path(design, folder or Path())


def validate(design: Design, target: Path) -> Pattern:
    """The pattern this design would load as, from `target`. Refuses what would not load.

    The name and the row interval are checked here because a name is also a new pattern's
    file name, and the interval must be a real duration before it can be put on a grid.
    """
    if not NAME_PATTERN.fullmatch(design.name):
        raise DesignError("name")
    if not (_finite(design.row_interval_ms) and design.row_interval_ms > 0):
        raise DesignError("interval")
    try:
        pattern = patterns.from_text(csv_text(design), sidecar_text(design), target)
    except PatternError as error:
        raise DesignError("not_loadable", value=str(error)) from error
    patterns.expand(pattern)
    return pattern


def save(design: Design, target: Path, overwrite: bool = False) -> Pattern:
    """Write the CSV at `target` and its sidecar beside it; prove they load back unchanged."""
    pattern = validate(design, target)
    sidecar = target.with_suffix(".yaml")
    if not overwrite and (target.exists() or sidecar.exists()):
        raise DesignError("exists", value=target.name)
    # `load_folder` refuses two patterns of one name, so a clash would break the whole folder.
    for other in sorted(target.parent.glob("*.csv")):
        if other == target:
            continue
        try:
            name = patterns.load_pattern(other).name
        except PatternError as error:
            raise DesignError("folder_unreadable", value=str(error)) from error
        if name == design.name:
            raise DesignError("name_taken", value=other.name)
    sidecar_body = sidecar_text(design)
    target.write_text(csv_text(design), encoding="utf-8", newline="")
    sidecar.write_bytes(sidecar_body.encode("utf-8"))
    loaded = patterns.load_pattern(target)
    # Stage boundary (CLAUDE.md): what is on disk is what was validated, or nothing is trusted.
    assert loaded == pattern, f"{target.name} did not load back as it was saved"
    design.path, design.sidecar_source = target, sidecar_body
    return loaded


def from_pattern(pattern: Pattern) -> Design:
    """A loaded pattern as a design, remembering its file and its sidecar's text."""
    source = pattern.source.with_suffix(".yaml").read_bytes().decode("utf-8")
    meta = yaml.safe_load(source)
    return Design(
        name=pattern.name,
        row_interval_ms=pattern.row_interval_ms,
        channel_ids=pattern.channel_ids,
        loop=pattern.loop,
        rows=[list(row) for row in pattern.rows],
        extras={key: meta.get(key) for key in OPTIONAL_FIELDS},
        path=pattern.source,
        sidecar_source=source,
    )


def open_pattern(path: Path) -> Design:
    return from_pattern(patterns.load_pattern(path))


def wiring(channel_bits: Sequence[int]) -> dict[int, int]:
    """Channel to bit, from `garment.prototype.channel_bits` (channels 1, 2, ... in order)."""
    bit_for = {channel: int(bit) for channel, bit in enumerate(channel_bits, start=1)}
    # Stage boundary (CLAUDE.md): two channels on one bit would be one stimulus played as two.
    assert len(set(bit_for.values())) == len(bit_for), (
        f"channel_bits repeats a bit: {channel_bits}"
    )
    return bit_for


def from_reference_csv(
    path: Path, column_ms: float, loop: bool, bit_for: Mapping[int, int]
) -> Design:
    """The prototype repository's horizontal CSV: one line per bit, the bit first.

    `Controller.Stimulus.from_csv_matrix` reads it with a column duration given at upload, so
    the file carries none and the designer asks for one. The cells are transposed as text and
    go through `patterns.from_text`, so a `2` or a `0.5` is refused here as it is on loading --
    the prototype parses both with `int()`. The delimiter rule is the prototype's own, a tab if
    the line has one and else a comma, applied to the first non-blank line.

    Each bit becomes the channel `bit_for` wires it to, and the columns are put in channel
    order, distal first, as every pattern here is.
    """
    if not (_finite(column_ms) and column_ms > 0):
        raise DesignError("interval")
    text = path.read_bytes().decode("utf-8").removeprefix(BOM)
    first = next((line for line in text.splitlines() if line.strip()), None)
    if first is None:
        raise DesignError("nothing")
    delimiter = REFERENCE_TAB if REFERENCE_TAB in first else REFERENCE_COMMA
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
    if not lines:
        raise DesignError("nothing")
    width = len(lines[0])
    for number, line in enumerate(lines, start=1):
        if len(line) != width:
            raise DesignError("ragged", line=number, value=len(line), expected=width)
    channel_for = {bit: channel for channel, bit in bit_for.items()}
    header = []
    for line in lines:
        bit = line[0]
        if not bit.lstrip("-").isdigit():
            # Left as written, for `from_text` to refuse as any pattern with that header is.
            header.append(bit)
            continue
        if int(bit) not in channel_for:
            raise DesignError("unwired_bit", value=bit,
                              wired=", ".join(str(b) for b in bit_for.values()))
        header.append(str(channel_for[int(bit)]))
    order = sorted(range(len(lines)),
                   key=lambda i: int(header[i]) if header[i].isdigit() else math.inf)
    header = [header[i] for i in order]
    columns = [lines[i][1:] for i in order]
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


def command_steps(
    pattern: Pattern, limits: dict, bit_for: Mapping[int, int]
) -> list[tuple[int, int]]:
    """(mask, ms) per step: runs of identical rows merged, over one whole cycle.

    `limits` is `hardware.yaml`'s `prototype_command_file`: what the sketch can store. A run
    longer than its uint16 delay is split into steps of the same mask, which re-latches the
    same state and changes nothing the participant feels. Each channel's bit is `bit_for`'s.
    """
    max_steps, max_step_ms = limits["max_steps"], limits["max_step_ms"]
    for channel in pattern.channel_ids:
        if channel not in bit_for:
            raise DesignError("unwired_channel", channel=channel,
                              wired=", ".join(str(c) for c in bit_for))
        if not 0 <= bit_for[channel] < limits["mask_bits"]:
            raise DesignError("bit_range", channel=channel, bit=bit_for[channel],
                              bits=limits["mask_bits"])
    interval = _exact(pattern.row_interval_ms)
    runs: list[list[int]] = []
    for row in pattern.rows:
        mask = sum(1 << bit_for[cid]
                   for cid, on in zip(pattern.channel_ids, row, strict=True) if on)
        if runs and runs[-1][0] == mask:
            runs[-1][1] += 1
        else:
            runs.append([mask, 1])
    steps = []
    for mask, n_rows in runs:
        duration = interval * n_rows
        if duration.denominator != 1:
            raise DesignError("not_whole_ms", value=shown(float(duration)))
        remaining = duration.numerator
        while remaining > 0:
            steps.append((mask, min(remaining, max_step_ms)))
            remaining -= max_step_ms
    if len(steps) > max_steps:
        raise DesignError("too_many_steps", value=len(steps), limit=max_steps)
    return steps


def command_file(steps: Sequence[tuple[int, int]]) -> str:
    """The file the prototype's own scripts send line by line before `exec`."""
    return "\n".join([COMMAND_CLEAR, *(f"addcode:0x{mask:x}/{ms}" for mask, ms in steps)])
