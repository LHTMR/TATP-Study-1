"""Unit conversions, and nothing else.

SPEC.md 4.2 allows a numeric literal in task code when it is a unit conversion. It was written
in six places before this file existed -- `/ 1000.0` in three modules, `/ 60.0` in two --
which is six chances to write `/ 100.0` and produce a plausible wrong number rather than an
error.

**Nothing here is a study parameter.** There are sixty seconds in a minute whatever S decides,
so these are the one kind of constant that must *not* move to `config/`: a configurable
`s_per_min` would be a setting that can be wrong.

`tools/lint_literals.py` enforces the boundary from the other side -- an unnamed number in
`tatp/` fails the gate, so the next conversion someone needs lands here rather than inline.
"""

from __future__ import annotations

MS_PER_S = 1000.0
S_PER_MIN = 60.0
