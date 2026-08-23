#!/usr/bin/env python
"""Print the session timeline and its warnings. SPEC.md 7.2.

No hardware, no session started, nothing written. It loads and validates the configuration,
generates the grid, and prints one row per block -- index, type, planned offset, planned
wall-clock time, expected duration -- plus the timed windows around them and the total.

The wall-clock column needs a session t=0, the start of heat sensitisation. There is no session
here, so `--start` supplies one and defaults to now: the point of the column is to answer "what
time will block 9 be" while planning a booking, and the offsets are what is authoritative.

Reachable from the launcher as entry 4 once the launcher exists (SPEC.md 4.1, Milestone 5).
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

COLUMNS = (
    ("index", "Block", 5),
    ("type", "Type", 9),
    ("planned_offset_min", "Offset", 8),
    ("planned_wall_clock", "Clock", 9),
    ("expected_duration_min", "Duration", 9),
    ("overridden", "Source", 10),
)

UNSET = "-"


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


def _cell(row: dict, key: str) -> str:
    value = row[key]
    if key == "overridden":
        return "override" if value else "generated"
    if value is None:
        return UNSET
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def render(schedule: sched.Schedule, t_zero: datetime) -> list[str]:
    """The whole report, as lines. Returned rather than printed so a test can read it."""
    lines = [f"Session t=0 (start of sensitisation) at {t_zero.strftime('%H:%M:%S')}", ""]

    lines.append("  ".join(head.ljust(width) for _, head, width in COLUMNS).rstrip())
    lines.append("  ".join("-" * width for _, _, width in COLUMNS))
    for row in schedule.preview_rows(t_zero):
        lines.append(
            "  ".join(_cell(row, key).ljust(width) for key, _, width in COLUMNS).rstrip()
        )

    lines.append("")
    lines.append("Timed windows, minutes from t=0")
    for window in schedule.windows:
        lines.append(
            f"  {window.name.ljust(15)} {window.start_min:g} - {window.end_min:g}"
        )

    lines.append("")
    lines.append(f"Schedule runs to {schedule.total_duration_min:g} min from t=0")

    warnings = schedule.warnings()
    lines.append("")
    if not warnings:
        lines.append("No warnings.")
    else:
        # SPEC.md 7.3: these never block. Piloting will legitimately want irregular schedules.
        lines.append(f"{len(warnings)} warning(s). None prevents the schedule running:")
        lines.extend(f"  - {warning}" for warning in warnings)
    return lines


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = cfg.load(args.participant_language, args.experimenter_language)
    schedule = sched.generate(config.schedule)
    for line in render(schedule, t_zero_from(args.start, datetime.now())):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
