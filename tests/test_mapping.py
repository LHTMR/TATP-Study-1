"""Secondary-hyperalgesia area mapping. SPEC.md 8.4, 17.5.

The pacing is driven through Qt with an accelerated clock; the distances go through the
experimenter's `distances_entered` signal, as Milestone 5's entry field will send them.
"""

from __future__ import annotations

import csv
import time

import pytest
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.clock import Clock
from tatp.mapping import AreaMapping, MappingLedger, plausible, sh_area_mm2
from tatp.procedure import Rig
from tatp.responder import Responder
from tatp.session import Session, SessionError
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
CLOCK_SPEED = 1000.0
SPIN_TIMEOUT_S = 20.0
PHASE = "post_sensitisation"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def rig(app, loaded, tmp_path):
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    session = Session(config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED),
                      rng_seed=3)
    session.start()
    session.set_phase(PHASE)
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    made = Rig(session, participant, experimenter)
    yield made
    session.close()


@pytest.fixture
def ledger(rig):
    return MappingLedger(rig.session, rig.experimenter)


def _spin(condition) -> None:
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the mapping did not reach the expected state")
        QApplication.processEvents()
        time.sleep(0.0005)


def _rows(session, table):
    path = session.files.path(table)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _events(session):
    return [row["event"] for row in _rows(session, "log")]


def _run_paths(rig, ledger, stop_after_cues=3):
    """Run all four paths, stopping each after a few cues, as an experimenter at the border."""
    mapping = AreaMapping(rig, ledger)
    cues = []
    mapping.pacing_cue.connect(lambda path, cue: cues.append((path, cue)))
    done = []
    mapping.finished.connect(done.append)
    mapping.start()
    for path in range(1, 5):
        rig.experimenter.proceed_requested.emit()
        _spin(lambda path=path: (path, stop_after_cues) in cues)
        rig.experimenter.proceed_requested.emit()
    _spin(lambda: done)
    return mapping, cues, done[0]


# -- the formula and the range -------------------------------------------------------------


def test_the_area_is_the_rectangle_of_opposite_paths():
    assert sh_area_mm2([30.0, 20.0, 50.0, 40.0]) == (30.0 + 50.0) * (20.0 + 40.0)


def test_plausibility_is_the_configured_range(loaded):
    mapping = loaded.study1["mapping"]
    low, high = mapping["distance_plausible_min_mm"], mapping["distance_plausible_max_mm"]
    assert plausible(low, mapping) and plausible(high, mapping)
    assert not plausible(high + 1, mapping) and not plausible(low / 2, mapping)


# -- the pacing ----------------------------------------------------------------------------


def test_each_path_is_started_by_the_experimenter_and_every_cue_is_logged(rig, ledger):
    mapping, cues, result = _run_paths(rig, ledger)
    assert result.paths_run == 4 and result.phase == PHASE
    assert {path for path, _ in cues} == {1, 2, 3, 4}
    logged = [r for r in _rows(rig.session, "log") if r["event"] == "pacing_cue"]
    assert len(logged) == len(cues), "every cue onset is timestamped (SPEC.md 10.5)"
    assert _events(rig.session).count("mapping_path_started") == 4
    assert rig.participant.message.text == rig.participant.text["screens"]["standby"]


def test_the_cue_train_stops_itself_at_max_steps(rig, ledger, loaded):
    max_steps = loaded.study1["mapping"]["max_steps"]
    mapping = AreaMapping(rig, ledger)
    cues = []
    mapping.pacing_cue.connect(lambda path, cue: cues.append((path, cue)))
    mapping.start()
    rig.experimenter.proceed_requested.emit()
    _spin(lambda: _events(rig.session).count("mapping_path_ended") == 1)
    assert cues == [(1, cue) for cue in range(1, max_steps + 1)]
    mapping.cancel()


def test_nothing_is_written_until_the_distances_arrive(rig, ledger):
    _run_paths(rig, ledger)
    assert _rows(rig.session, "mapping") == [] and _rows(rig.session, "sh_area") == []


# -- the distances -------------------------------------------------------------------------


def test_distances_write_the_mapping_and_area_rows(rig, ledger):
    _run_paths(rig, ledger)
    areas = []
    ledger.area_recorded.connect(lambda phase, area: areas.append((phase, area)))
    rig.experimenter.distances_entered.emit(PHASE, (30.0, None, 50.0, None))
    assert _rows(rig.session, "sh_area") == [], "no area until all four are in"
    # Each accepted distance is on disk at once (SPEC.md 14.3), not held for the other three.
    assert [r["path_id"] for r in _rows(rig.session, "mapping")] == ["proximal", "distal"]
    rig.experimenter.distances_entered.emit(PHASE, (None, 20.0, None, 40.0))

    rows = _rows(rig.session, "mapping")
    assert [r["path_id"] for r in rows] == ["proximal", "distal", "lateral", "medial"]
    assert [r["distance_mm"] for r in rows] == ["30.0", "50.0", "20.0", "40.0"]
    assert all(r["distance_missing"] == "false" and r["distance_entered_iso"] for r in rows)
    (area,) = _rows(rig.session, "sh_area")
    assert float(area["area_mm2"]) == (30.0 + 50.0) * (20.0 + 40.0)
    assert area["area_missing"] == "false"
    assert areas == [(PHASE, 4800.0)]


def test_an_implausible_distance_is_queried_then_accepted_when_repeated(rig, ledger):
    _run_paths(rig, ledger)
    too_far = rig.session.config.study1["mapping"]["distance_plausible_max_mm"] + 50.0
    rig.experimenter.distances_entered.emit(PHASE, (too_far, 20.0, 50.0, 40.0))
    assert _rows(rig.session, "sh_area") == [], "queried, not silently accepted"
    assert "distance_queried" in _events(rig.session)
    assert f"{too_far:g}" in rig.experimenter.status.text()
    rig.experimenter.distances_entered.emit(PHASE, (too_far, None, None, None))
    (row,) = _rows(rig.session, "sh_area")
    assert float(row["distance_1_mm"]) == too_far


def test_a_corrected_value_replaces_a_queried_one(rig, ledger):
    _run_paths(rig, ledger)
    rig.experimenter.distances_entered.emit(PHASE, (2000.0, 20.0, 50.0, 40.0))
    rig.experimenter.distances_entered.emit(PHASE, (35.0, None, None, None))
    (row,) = _rows(rig.session, "sh_area")
    assert row["distance_1_mm"] == "35.0"
    confirmed = [r for r in _rows(rig.session, "log") if "confirmed outside" in r["detail"]]
    assert confirmed == []


def test_a_correction_appends_superseding_rows_and_logs_both_values(rig, ledger):
    _run_paths(rig, ledger)
    rig.experimenter.distances_entered.emit(PHASE, (30.0, 20.0, 50.0, 40.0))
    rig.experimenter.distances_entered.emit(PHASE, (31.0, 20.0, 50.0, 40.0))
    rows = _rows(rig.session, "mapping")
    proximal = [r for r in rows if r["path_id"] == "proximal"]
    assert [r["distance_mm"] for r in proximal] == ["30.0", "31.0"], "never rewritten"
    assert proximal[-1]["distance_entered_iso"] >= proximal[0]["distance_entered_iso"]
    assert len(rows) == 5, "only the corrected path gets a new row"
    areas = _rows(rig.session, "sh_area")
    assert [float(a["area_mm2"]) for a in areas] == [80.0 * 60.0, 81.0 * 60.0]
    (logged,) = [r for r in _rows(rig.session, "log") if r["event"] == "distance_corrected"]
    assert "30.0" in logged["detail"] and "31.0" in logged["detail"]
    assert logged["severity"] == "warning"


def test_the_same_value_again_changes_nothing(rig, ledger):
    _run_paths(rig, ledger)
    rig.experimenter.distances_entered.emit(PHASE, (30.0, 20.0, 50.0, 40.0))
    rig.experimenter.distances_entered.emit(PHASE, (30.0, 20.0, 50.0, 40.0))
    assert len(_rows(rig.session, "mapping")) == 4
    assert len(_rows(rig.session, "sh_area")) == 1


def test_an_interruption_mid_path_runs_the_whole_path_again(rig, ledger):
    mapping = AreaMapping(rig, ledger)
    cues = []
    mapping.pacing_cue.connect(lambda path, cue: cues.append((path, cue)))
    mapping.start()
    rig.experimenter.proceed_requested.emit()
    _spin(lambda: (1, 3) in cues)
    rig.participant.emergency_stop.emit()
    cues.clear()
    rig.experimenter.resume_requested.emit()
    assert rig.participant.message.text == rig.participant.text["screens"]["standby"]
    _spin(lambda: (1, 2) in cues)
    assert cues[0] == (1, 1), "the cue train starts again from the first cue"
    assert _events(rig.session).count("mapping_path_started") == 2, "path_started again"
    mapping.cancel()


def test_a_resume_while_waiting_for_a_path_restores_standby(rig, ledger):
    mapping = AreaMapping(rig, ledger)
    mapping.start()
    rig.experimenter.pause_requested.emit()
    rig.experimenter.resume_requested.emit()
    assert rig.participant.message.text == rig.participant.text["screens"]["standby"]
    mapping.cancel()


def test_distances_for_a_phase_with_no_mapping_are_an_error(ledger):
    with pytest.raises(SessionError, match="no mapping"):
        ledger.enter("pre_sensitisation", (1.0, 2.0, 3.0, 4.0))


# -- the session end -----------------------------------------------------------------------


def test_outstanding_distances_prompt_once_then_close_flagged_missing(rig, ledger):
    _run_paths(rig, ledger)
    rig.experimenter.distances_entered.emit(PHASE, (30.0, None, 50.0, None))
    assert ledger.outstanding() == [PHASE]
    assert ledger.close() is False, "the first call prompts"
    assert rig.experimenter.instruction.text() == (
        rig.experimenter.text["dialogs"]["distances_outstanding"]
    )
    assert ledger.close() is True, "the second closes"
    rows = _rows(rig.session, "mapping")
    assert [(r["path_id"], r["distance_missing"]) for r in rows] == [
        ("proximal", "false"), ("distal", "false"), ("lateral", "true"), ("medial", "true")
    ]
    (area,) = _rows(rig.session, "sh_area")
    assert area["area_missing"] == "true" and area["area_mm2"] == ""
    assert area["distance_1_mm"] == "30.0" and area["distance_2_mm"] == ""
    assert ledger.outstanding() == []


def test_nothing_outstanding_closes_at_once(ledger):
    assert ledger.close() is True
