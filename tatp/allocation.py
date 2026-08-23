"""Reading the counterbalancing file. SPEC.md 4, 20 item 10.

The allocation is data, generated once by tools/make_allocation.py and committed. This module
only reads it, and refuses anything it cannot resolve: a participant code that is not in the
file is an experimenter typing error, and guessing would silently put someone in the wrong
condition (SPEC.md 17.5).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

COLUMNS = ("participant_code", "session_number", "condition", "limb")


class AllocationError(Exception):
    """The allocation file is malformed, or does not cover the requested session."""


@dataclass(frozen=True)
class Assignment:
    participant_code: str
    session_number: int
    condition: str
    limb: str


class Allocation:
    def __init__(self, rows: list[Assignment], path: Path):
        self.path = path
        self._by_key = {(r.participant_code, r.session_number): r for r in rows}
        self.rows = tuple(rows)

    @property
    def participant_codes(self) -> tuple[str, ...]:
        return tuple(sorted({r.participant_code for r in self.rows}))

    def get(self, participant_code: str, session_number: int) -> Assignment:
        key = (participant_code, session_number)
        if key not in self._by_key:
            known = self.participant_codes
            if participant_code not in known:
                raise AllocationError(
                    f"participant code {participant_code!r} is not in {self.path.name}. "
                    f"Codes run {known[0]!r} to {known[-1]!r}."
                )
            raise AllocationError(
                f"{self.path.name} has no session {session_number} for participant "
                f"{participant_code!r}."
            )
        return self._by_key[key]

    def sessions_for(self, participant_code: str) -> tuple[int, ...]:
        return tuple(
            sorted(s for (code, s) in self._by_key if code == participant_code)
        )


def load(path: Path, conditions: list[str], limbs: list[str], n_sessions: int) -> Allocation:
    """Load and validate the allocation file.

    Validation is here rather than in the generator because the committed file is what a
    session actually reads, and a hand-edit is exactly the failure worth catching.
    """
    if not path.exists():
        raise AllocationError(
            f"{path} does not exist. Generate it with tools/make_allocation.py."
        )
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")
    ]
    reader = csv.DictReader(lines)
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise AllocationError(
            f"{path.name}: columns are {reader.fieldnames}, expected {list(COLUMNS)}"
        )

    rows = []
    for line_number, raw in enumerate(reader, start=2):
        if raw["condition"] not in conditions:
            raise AllocationError(
                f"{path.name} line {line_number}: condition {raw['condition']!r} is not one of "
                f"{conditions}"
            )
        if raw["limb"] not in limbs:
            raise AllocationError(
                f"{path.name} line {line_number}: limb {raw['limb']!r} is not one of {limbs}"
            )
        if not raw["session_number"].isdigit():
            raise AllocationError(
                f"{path.name} line {line_number}: session_number {raw['session_number']!r} is "
                f"not a number"
            )
        rows.append(
            Assignment(
                participant_code=raw["participant_code"],
                session_number=int(raw["session_number"]),
                condition=raw["condition"],
                limb=raw["limb"],
            )
        )

    allocation = Allocation(rows, path)

    # Stage boundary (CLAUDE.md): a counterbalance that is not within-participant complete is
    # not a counterbalance, and the failure would only surface as an imbalance in analysis.
    assert rows, f"{path.name} has no rows"
    for code in allocation.participant_codes:
        assigned = [r.condition for r in rows if r.participant_code == code]
        if sorted(assigned) != sorted(conditions):
            raise AllocationError(
                f"{path.name}: participant {code!r} has conditions {sorted(assigned)}, expected "
                f"each of {sorted(conditions)} exactly once"
            )
        if allocation.sessions_for(code) != tuple(range(1, n_sessions + 1)):
            raise AllocationError(
                f"{path.name}: participant {code!r} has sessions "
                f"{allocation.sessions_for(code)}, expected 1..{n_sessions}"
            )
        limb_by_session = [r.limb for r in sorted(
            (r for r in rows if r.participant_code == code), key=lambda r: r.session_number
        )]
        for earlier, later in zip(limb_by_session, limb_by_session[1:], strict=False):
            if earlier == later:
                raise AllocationError(
                    f"{path.name}: participant {code!r} has {earlier!r} twice in a row; the "
                    f"target limb alternates between visits (SPEC.md 2)"
                )
    return allocation