"""The session's random stream must not drift under a Python upgrade. docs/LOG.md N3.7.

Each stage draws from `random.Random(f"{rng_seed}:{stage_id}")` (N7.D13). Python guarantees
only that a seed gives the same `random()` sequence across versions; `shuffle`, `sample` and
`uniform`, which the session uses, are stable in practice but not promised. These values were
drawn on the lab PC (Python 3.11.16, 14 Oct 2026). If this fails after an upgrade, a session
recorded before it can no longer be replayed from its seed in the new environment -- decide
before upgrading, not after.
"""

from __future__ import annotations

import random

SEED = "12345:touch_calibration"  # the per-stage form: a string seed, hashed by Python


def test_the_base_stream_is_unchanged():
    rng = random.Random(SEED)
    assert [rng.random() for _ in range(3)] == [
        0.2817074877569894, 0.4168714388503991, 0.07065803454868635,
    ]


def test_the_helpers_the_session_uses_are_unchanged():
    rng = random.Random(SEED)
    for _ in range(3):
        rng.random()
    order = list(range(10))
    rng.shuffle(order)
    assert order == [6, 8, 3, 2, 9, 0, 5, 4, 1, 7]
    assert rng.sample(range(10), 3) == [5, 0, 7]
    assert [rng.uniform(2.0, 4.0) for _ in range(3)] == [
        3.541190918928623, 2.4792883245404553, 2.8837165435902925,
    ]
