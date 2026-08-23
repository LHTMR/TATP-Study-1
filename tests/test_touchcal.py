"""Protocol B step 1 and the touch rating. SPEC.md 9, 10.3.

`AdjustmentState` takes the time as an argument, so the accelerating control is tested at exact
times rather than at whatever times a timer happened to fire. The two Qt classes are then tested
for what reaches disk and the log.
"""

from __future__ import annotations

import csv
import time

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp import touchcal
from tatp.clock import Clock
from tatp.responder import Action, Responder
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"

CLOCK_SPEED = 100.0
SPIN_TIMEOUT_S = 10.0

RANGE_MIN_KPA = 0.0
RANGE_MAX_KPA = 200.0
START_KPA = 100.0


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def state(loaded):
    return touchcal.AdjustmentState(
        loaded.hardware["adjustment"], RANGE_MIN_KPA, RANGE_MAX_KPA, START_KPA
    )


@pytest.fixture
def running(app, loaded, tmp_path):
    """A started session in the touch-calibration phase, with both windows."""
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED), rng_seed=7
    )
    session.start()
    session.set_phase("touch_calibration")
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    yield session, participant, experimenter
    session.close()


def _spin(condition) -> None:
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the adjustment did not reach the expected state")
        QApplication.processEvents()
        time.sleep(0.001)


def _press(widget, name) -> None:
    key = QT_KEYS[name]
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def _rows(session, table):
    with session.files.path(table).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# -- the accelerating control, SPEC.md 10.3 -----------------------------------------------


def test_a_tap_moves_one_step(state):
    state.press(Action.INCREASE, 0.0)
    state.tick(state.tap_max_duration_s / 2)
    state.release(Action.INCREASE, state.tap_max_duration_s / 2)
    assert state.pressure_kpa == START_KPA + state.tap_step_kpa
    assert state.button_events == 2


def test_a_tap_on_the_other_button_moves_the_other_way(state):
    state.press(Action.DECREASE, 0.0)
    state.release(Action.DECREASE, state.tap_max_duration_s)
    assert state.pressure_kpa == START_KPA - state.tap_step_kpa


def test_nothing_moves_during_the_hold_delay(state):
    state.press(Action.INCREASE, 0.0)
    state.tick(state.hold_delay_s)
    assert state.pressure_kpa == START_KPA


def test_a_hold_starts_at_the_initial_rate_and_reaches_the_final_one(state):
    """The rate ramps linearly from the initial to the final over the ramp duration."""
    assert state.rate_kpa_s(0.0) == 0.0
    half = state.ramp_duration_s / 2
    expected = (state.rate_initial_kpa_s + state.rate_final_kpa_s) / 2
    assert state.rate_kpa_s(half) == pytest.approx(expected)
    assert state.rate_kpa_s(state.ramp_duration_s) == state.rate_final_kpa_s
    assert state.rate_kpa_s(state.ramp_duration_s * 10) == state.rate_final_kpa_s


def test_the_distance_held_does_not_depend_on_how_often_the_timer_fires(loaded):
    """The travel is the integral of the ramp, not a per-tick accumulation."""
    held_s = 1.0
    coarse = touchcal.AdjustmentState(
        loaded.hardware["adjustment"], RANGE_MIN_KPA, RANGE_MAX_KPA, START_KPA
    )
    fine = touchcal.AdjustmentState(
        loaded.hardware["adjustment"], RANGE_MIN_KPA, RANGE_MAX_KPA, START_KPA
    )
    for each, ticks in ((coarse, 2), (fine, 50)):
        each.press(Action.INCREASE, 0.0)
        for step in range(1, ticks + 1):
            each.tick(each.hold_delay_s + held_s * step / ticks)
    assert coarse.pressure_kpa == pytest.approx(fine.pressure_kpa)
    assert coarse.pressure_kpa > START_KPA


def test_a_long_hold_is_not_also_counted_as_a_tap(state):
    state.press(Action.INCREASE, 0.0)
    state.tick(state.hold_delay_s + state.ramp_duration_s)
    moved = state.pressure_kpa
    state.release(Action.INCREASE, state.hold_delay_s + state.ramp_duration_s)
    assert state.pressure_kpa == moved


def test_the_pressure_stays_inside_the_adjustable_range(state):
    state.press(Action.INCREASE, 0.0)
    state.tick(state.hold_delay_s + state.ramp_duration_s * 100)
    assert state.pressure_kpa == RANGE_MAX_KPA
    state.release(Action.INCREASE, state.hold_delay_s + state.ramp_duration_s * 100)
    state.press(Action.DECREASE, 0.0)
    state.tick(state.hold_delay_s + state.ramp_duration_s * 100)
    assert state.pressure_kpa == RANGE_MIN_KPA


def test_travel_the_range_refused_is_not_exploration(state):
    """Pressing against an end stop teaches the participant nothing (comparison doc 7.3)."""
    state.pressure_kpa = RANGE_MAX_KPA
    state.press(Action.INCREASE, 0.0)
    state.release(Action.INCREASE, state.tap_max_duration_s)
    assert state.exploration_kpa == 0.0


# -- where an adjustment starts -----------------------------------------------------------


def test_an_adjustment_with_no_expectation_starts_at_the_range_end(loaded):
    """Step 1 has nothing to chain off, so a fraction of the range would be invented."""
    plans = touchcal.anchor_plans(loaded)
    fraction = float(loaded.study1["touch_calibration"]["start_offset_fraction"])
    below = plans[0]
    assert below.start_direction == "below"
    assert touchcal.start_pressure_kpa(below, fraction) == below.range_min_kpa
    above = touchcal.AdjustmentPlan(**{**below.__dict__, "start_direction": "above"})
    assert touchcal.start_pressure_kpa(above, fraction) == above.range_max_kpa


def test_an_adjustment_with_an_expectation_starts_the_configured_fraction_away(loaded):
    plan = touchcal.AdjustmentPlan(
        stage="channel_match",
        channel=1,
        target_key="match",
        adjustment_index=1,
        start_direction="below",
        range_min_kpa=0.0,
        range_max_kpa=100.0,
        reference_channel=3,
        expected_kpa=80.0,
    )
    assert touchcal.start_pressure_kpa(plan, 0.5) == pytest.approx(30.0)
    # Clamped to the range rather than started outside it.
    assert touchcal.start_pressure_kpa(plan, 0.9) == 0.0


def test_every_anchor_has_a_prompt_and_the_reference_channel(loaded):
    touch = loaded.study1["touch_calibration"]
    plans = touchcal.anchor_plans(loaded)
    assert len(plans) == len(touch["anchors_pct"]) * touch["adjustments_per_anchor"]
    for plan in plans:
        assert plan.stage == touchcal.ANCHOR_STAGE
        assert plan.channel == touch["reference_channel"]
        assert plan.target_key in loaded.participant_text["adjust_targets"]
        assert plan.reference_channel is None, "there is nothing to match to in step 1"
        assert plan.range_max_kpa == loaded.hardware["garment"]["pressure_ceiling_kpa"]
    assert [p.anchor_percent for p in plans] == list(touch["anchors_pct"])


# -- one adjustment end to end ------------------------------------------------------------


def _run_adjustment(running, taps=3):
    session, participant, experimenter = running
    session.garment.set_channel(3, True)
    plan = touchcal.anchor_plans(session.config)[0]
    adjustment = touchcal.Adjustment(session, participant, experimenter, plan)
    done = []
    adjustment.finished.connect(done.append)
    adjustment.start()
    for _ in range(taps):
        _press(participant, "pagedown")
    return adjustment, done


def test_an_adjustment_writes_one_row_carrying_what_the_participant_did(running):
    session, participant, _ = running
    adjustment, done = _run_adjustment(running)
    _press(participant, "period")

    assert len(done) == 1
    rows = _rows(session, "touchcal_adjust")
    assert len(rows) == 1
    row = rows[0]
    assert row["stage"] == touchcal.ANCHOR_STAGE
    assert row["channel"] == "3"
    assert row["reference_channel"] == ""
    assert float(row["anchor_percent"]) == 10.0
    assert row["adjustment_index"] == "1"
    assert row["start_direction"] == "below"
    assert float(row["start_pressure_kpa"]) == 0.0
    assert float(row["produced_pressure_kpa"]) == pytest.approx(done[0])
    assert float(row["produced_pressure_kpa"]) > 0.0
    assert row["button_events"] == "6", "three taps, down and up each (SPEC.md 10.3)"
    assert row["timed_out"] == "false"
    assert row["valid_for_analysis"] == "true"


def test_the_adjustment_commands_the_garment_it_is_adjusting(running):
    session, participant, _ = running
    adjustment, _ = _run_adjustment(running)
    _press(participant, "period")
    assert session.garment.pressure_kpa[3] == pytest.approx(adjustment.state.pressure_kpa)
    commands = [
        row for row in _rows(session, "garment")
        if row["event"] == "set_pressure" and row["channel"] == "3"
    ]
    assert commands, "the pressure the participant set must reach the device"


def test_every_button_edge_reaches_the_log(running):
    """SPEC.md 10.3: the search path is recoverable, not just the final setting."""
    session, participant, _ = running
    # Bound, not discarded: an Adjustment with no parent is collected the moment nothing holds
    # it, and a collected QObject stops answering the participant's buttons.
    adjustment, _ = _run_adjustment(running)
    _press(participant, "period")
    events = [row["event"] for row in _rows(session, "log")]
    assert events.count("button_down") == 3
    assert events.count("button_up") == 3
    assert events.index("adjustment_started") < events.index("button_down")
    assert events[-1] == "adjustment_confirmed"


def test_short_exploration_is_recorded_rather_than_refused(running):
    """There is no approved wording for refusing a confirm, so the flag carries it instead."""
    session, participant, _ = running
    adjustment, _ = _run_adjustment(running, taps=1)
    _press(participant, "period")
    row = _rows(session, "touchcal_adjust")[0]
    assert row["min_exploration_met"] == "false"


def test_an_emergency_stop_stops_the_garment_and_writes_no_row(running):
    """SPEC.md 13. Nothing was produced, so there is no produced pressure to record."""
    session, participant, _ = running
    adjustment, done = _run_adjustment(running)
    _press(participant, "f5")

    assert done == [None]
    assert not session.files.path("touchcal_adjust").exists()
    assert session.garment.pressure_kpa[3] == 0.0
    stops = [row for row in _rows(session, "log") if row["event"] == "emergency_stop"]
    assert len(stops) == 1
    assert stops[0]["severity"] == "error"


def test_the_adjustment_times_out_rather_than_waiting_for_ever(running, monkeypatch):
    """SPEC.md 9: the method of adjustment has no stopping rule of its own."""
    session, participant, experimenter = running
    session.garment.set_channel(3, True)
    plan = touchcal.anchor_plans(session.config)[0]
    adjustment = touchcal.Adjustment(session, participant, experimenter, plan)
    # The configured time-out is two minutes of session time; the point under test is what
    # happens when it fires, not how long it is.
    adjustment._timeout.setInterval(0)
    done = []
    adjustment.finished.connect(done.append)
    adjustment.start()
    _spin(lambda: done)

    assert adjustment.timed_out
    row = _rows(session, "touchcal_adjust")[0]
    assert row["timed_out"] == "true"
    assert float(row["produced_pressure_kpa"]) == 0.0, "what they had reached, not nothing"
    timeouts = [r for r in _rows(session, "log") if r["event"] == "adjustment_timed_out"]
    assert timeouts[0]["severity"] == "warning"


# -- the touch rating ---------------------------------------------------------------------


def test_the_touch_rating_records_the_pressure_that_was_delivering(running):
    session, participant, experimenter = running
    session.garment.set_channel(3, True)
    session.garment.set_pressure(3, 42.0)
    rating = touchcal.TouchRating(
        session, participant, experimenter, touchcal.INTENSITY_SCALE, 3
    )
    done = []
    rating.finished.connect(done.append)
    rating.start()
    _press(participant.vas, "pagedown")
    _press(participant.vas, "period")

    assert len(done) == 1
    row = _rows(session, "touch_ratings")[0]
    assert row["scale"] == touchcal.INTENSITY_SCALE
    assert row["phase"] == "touch_calibration"
    assert float(row["rating_percent"]) == done[0].rating_percent
    assert float(row["commanded_pressure_kpa"]) == 42.0
    assert row["first_press_side"] == "right"
    assert row["valid_for_analysis"] == "true"


def test_the_rating_never_reaches_the_experimenter_screen(running):
    """SPEC.md 16, Bilaga 1 3.3. The lab screen says a response arrived, never what it was."""
    session, participant, experimenter = running
    rating = touchcal.TouchRating(
        session, participant, experimenter, touchcal.INTENSITY_SCALE, 3
    )
    rating.start()
    _press(participant.vas, "pagedown")
    _press(participant.vas, "period")
    text = session.config.experimenter_text["instructions"]
    assert experimenter.status.text() == text["response_received"]
