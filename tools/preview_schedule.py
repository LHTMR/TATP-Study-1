#!/usr/bin/env python
"""Print the session timeline and its warnings. SPEC.md 7.2.

No hardware, no session started, nothing written. It loads and validates the configuration,
generates the grid, and prints one row per block -- index, type, planned offset, planned
wall-clock time, expected duration -- plus the timed windows around them and the total.

The wall-clock column needs a session t=0, the start of heat sensitisation. There is no session
here, so `--start` supplies one and defaults to now: the point of the column is to answer "what
time will block 9 be" while planning a booking, and the offsets are what is authoritative.

The report is in the experimenter's language, from `schedule_preview` and `schedule_warnings`
in the experimenter text (docs/LOG.md N7.U10). The launcher shows it as its entry 4 (SPEC.md
4.1).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tatp import config as cfg  # noqa: E402  -- after the path insert above
from tatp import schedule as sched  # noqa: E402

# The report's columns and their widths in a terminal. Their headings are in the text.
COLUMNS = (
    ("index", 5),
    ("type", 9),
    ("planned_offset_min", 8),
    ("planned_wall_clock", 9),
    ("expected_duration_min", 9),
    ("overridden", 10),
)
WINDOW_NAME_WIDTH = 18
UNSET = "-"
T_ZERO_FORMAT = "%H:%M:%S"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--start",
        default=None,
        help="session t=0 as HH:MM, for the wall-clock column. Defaults to now.",
    )
    parser.add_argument("--participant-language", default="sv", choices=("sv", "en"))
    parser.add_argument("--experimenter-language", default="en", choices=("sv", "en"))
    return parser.parse_args(argv)


def t_zero_from(start: str | None, now: datetime) -> datetime:
    if start is None:
        return now
    hour, _, minute = start.partition(":")
    return now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def _cell(row: dict, key: str, text: dict) -> str:
    value = row[key]
    if key == "overridden":
        return text["schedule_preview"]["override" if value else "generated"]
    if key == "type":
        return text["terms"]["block_types"][value]
    if value is None:
        return UNSET
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def render(
    schedule: sched.Schedule, t_zero: datetime, text: dict, separator: str | None = None
) -> list[str]:
    """The whole report, as lines, in the language of `text` (the experimenter text).
    Returned rather than printed so a test can read it.

    By default the columns are padded with spaces for a terminal. A `separator` joins the
    cells unpadded instead -- a tab, for a window whose font is not fixed-pitch.
    """
    words = text["schedule_preview"]
    padded = separator is None
    joiner = "  " if padded else separator

    def columns(cells) -> str:
        if not padded:
            return joiner.join(cell for cell, _ in cells)
        return joiner.join(cell.ljust(width) for cell, width in cells).rstrip()

    lines = [words["t_zero"].format(time=t_zero.strftime(T_ZERO_FORMAT)), ""]

    lines.append(columns((words["columns"][key], width) for key, width in COLUMNS))
    lines.append(joiner.join("-" * width for _, width in COLUMNS))
    for row in schedule.preview_rows(t_zero):
        lines.append(columns((_cell(row, key, text), width) for key, width in COLUMNS))

    lines.append("")
    lines.append(words["windows"])
    for window in schedule.windows:
        name = text["phases"][window.name]
        span = f"{window.start_min:g} - {window.end_min:g}"
        lines.append(f"  {name.ljust(WINDOW_NAME_WIDTH)} {span}" if padded
                     else f"  {name}{joiner}{span}")

    lines.append("")
    lines.append(words["runs_to"].format(value=f"{schedule.total_duration_min:g}"))

    warnings = schedule.warnings()
    lines.append("")
    if not warnings:
        lines.append(words["no_warnings"])
    else:
        # SPEC.md 7.3: these never block. Piloting will legitimately want irregular schedules.
        lines.append(words["warnings"].format(value=len(warnings)))
        lines.extend(f"  - {warning.describe(text)}" for warning in warnings)
    return lines


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = cfg.load(args.participant_language, args.experimenter_language)
    schedule = sched.generate(config.schedule)
    now = datetime.now()
    for line in render(schedule, t_zero_from(args.start, now), config.experimenter_text):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
