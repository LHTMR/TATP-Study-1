"""The committed counterbalancing file. SPEC.md 4, 20 item 10.

These test the file that sessions actually read, not the generator, because a hand-edit of the
committed CSV is the failure worth catching: it would put someone in the wrong condition and
show up only as an imbalance in analysis.
"""

from __future__ import annotations

from collections import Counter

import pytest

from tatp import allocation as alloc
from tatp import config as cfg


@pytest.fixture(scope="module")
def design():
    study1 = cfg.load("sv", "en").study1["design"]
    path = cfg.REPO_ROOT / study1["allocation_file"]
    return study1, alloc.load(path, study1["conditions"], study1["limbs"], study1["n_sessions"])


def _real_codes(study1, allocation) -> list[str]:
    """The counterbalance is over real participants; pilot codes sit above the offset."""
    return [c for c in allocation.participant_codes if int(c) < study1["pilot_code_offset"]]


def test_covers_every_participant_and_session(design):
    study1, allocation = design
    n_codes = study1["n_participants"] + study1["n_pilot_participants"]
    assert len(_real_codes(study1, allocation)) == study1["n_participants"]
    assert len(allocation.participant_codes) == n_codes
    assert len(allocation.rows) == n_codes * study1["n_sessions"]
    assert allocation.participant_codes[0] == "01"
    assert allocation.get("01", 1).condition in study1["conditions"]


def test_each_pilot_code_runs_its_participants_allocation(design):
    """Pilot code offset + i is participant i, so a pilot session is a real session's."""
    study1, allocation = design
    for i in range(1, study1["n_pilot_participants"] + 1):
        pilot = str(study1["pilot_code_offset"] + i)
        real = str(i).zfill(len(str(study1["n_participants"])))
        for session in range(1, study1["n_sessions"] + 1):
            p, r = allocation.get(pilot, session), allocation.get(real, session)
            assert (p.condition, p.limb) == (r.condition, r.limb)


def test_condition_orders_are_balanced_to_within_one_participant(design):
    study1, allocation = design
    orders = Counter(
        tuple(
            r.condition
            for r in sorted(
                (r for r in allocation.rows if r.participant_code == code),
                key=lambda r: r.session_number,
            )
        )
        for code in _real_codes(study1, allocation)
    )
    # 3! = 6 orders over 41 participants: 6 orders used 7 times and 5 used 6 times, or similar.
    assert len(orders) == 6
    assert max(orders.values()) - min(orders.values()) <= 1


def test_starting_limb_is_balanced(design):
    study1, allocation = design
    starts = Counter(allocation.get(code, 1).limb for code in _real_codes(study1, allocation))
    assert set(starts) == set(study1["limbs"])
    assert max(starts.values()) - min(starts.values()) <= 1


def test_limb_alternates_between_visits(design):
    """SPEC.md 2. `alloc.load` asserts this, so reaching here at all is the check."""
    _, allocation = design
    for code in allocation.participant_codes:
        limbs = [allocation.get(code, s).limb for s in allocation.sessions_for(code)]
        assert all(a != b for a, b in zip(limbs, limbs[1:], strict=False))


def test_an_unknown_participant_code_is_refused_not_guessed(design):
    _, allocation = design
    with pytest.raises(alloc.AllocationError, match="not in"):
        allocation.get("99", 1)
    with pytest.raises(alloc.AllocationError, match="no session"):
        allocation.get("01", 9)


def test_a_hand_edited_file_is_rejected(design, tmp_path):
    study1, allocation = design
    broken = tmp_path / "allocation.csv"
    lines = allocation.path.read_text(encoding="utf-8").splitlines()
    # Give participant 01 the same condition twice: the counterbalance is no longer complete.
    lines[4] = lines[3].replace(",1,", ",2,")
    broken.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(alloc.AllocationError, match="expected"):
        alloc.load(broken, study1["conditions"], study1["limbs"], study1["n_sessions"])
