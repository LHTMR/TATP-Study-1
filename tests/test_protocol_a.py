"""Protocol A driven end to end through Qt. SPEC.md 8.2, 8.3, 11, 11.1, 13.

A virtual participant answers each rating with key presses, as `tests/test_pinprick.py` does,
and a virtual experimenter emits the experimenter-action signals. The clock is accelerated so
a run of a dozen applications costs a fraction of a second; every interval still comes from
config. What is checked is what reached the data files.
"""

from __future__ import annotations

import csv
import math
import time

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.clock import Clock
from tatp.pinprick import (
    BrushProtocol,
    IntolerableCap,
    LongProtocol,
    LongResult,
    ShortProtocol,
    prior_for,
)
from tatp.procedure import Rig
from tatp.responder import Responder
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
CLOCK_SPEED = 1000.0
SPIN_TIMEOUT_S = 20.0
# The virtual participant's own F40, between the 26 g (255 mN) and 60 g (588 mN) filaments.
F40_MN = 400.0
# 75 % after the first right press, then 0.5 % a press: enough to pin the marker at the top.
PRESSES_TO_THE_CEILING = 60


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


def _make_rig(loaded, tmp_path, study1=None, seed=7):
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware,
                           "study1": study1 or loaded.study1})
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED), rng_seed=seed
    )
    session.start()
    session.set_phase("pre_sensitisation")
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    participant.resize(1280, 800)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    return Rig(session, participant, experimenter)


@pytest.fixture
def rig(app, loaded, tmp_path):
    made = _make_rig(loaded, tmp_path)
    yield made
    made.session.close()


def _spin(condition) -> None:
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the procedure did not reach the expected state")
        QApplication.processEvents()
        time.sleep(0.0005)


def _press(widget, name, times=1) -> None:
    key = QT_KEYS[name]
    for _ in range(times):
        widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
        widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def _rows(session, table):
    path = session.files.path(table)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _events(session):
    return [row["event"] for row in _rows(session, "log")]


def _observer(trial) -> int:
    """How many right presses: one (75 %) at or above the participant's F40, else none."""
    force = trial.session.config.filaments["filaments"]
    applied = next(f for f in force if f["label_g"] == trial.applied_label_g)
    return 1 if applied["force_nominal_mn"] >= F40_MN else 0


def _answer(participant, right_presses: int) -> None:
    if right_presses:
        _press(participant.vas, "pagedown", right_presses)
    else:
        _press(participant.vas, "pageup")
    _press(participant.vas, "period")


def _drive(procedure, done, respond=_observer, before_answer=None, max_trials=60) -> int:
    """Answer every rating until the procedure finishes. Returns how many were answered."""
    participant = procedure.participant
    answered = 0
    while not done:
        _spin(lambda: done or participant.stack.currentWidget() is participant.vas)
        if done:
            break
        trial = procedure._trial
        if before_answer is not None:
            before_answer(answered, trial)
        _answer(participant, respond(trial))
        answered += 1
        assert answered <= max_trials, "the protocol did not end"
    return answered


def _start(procedure) -> list:
    done: list = []
    procedure.finished.connect(done.append)
    procedure.start()
    procedure.experimenter.proceed_requested.emit()
    return done


def _long(rig, **kwargs):
    prior = prior_for(rig.session.config, "pre_sensitisation", 1, None)
    return LongProtocol(rig, "secondary", prior, **kwargs)


# -- the long protocol ---------------------------------------------------------------------


def test_the_long_protocol_searches_measures_and_estimates(rig):
    session = rig.session
    protocol = _long(rig)
    done = _start(protocol)
    _drive(protocol, done)
    result = done[0]
    assert isinstance(result, LongResult)

    rows = _rows(session, "pinprick")
    assert [r["purpose"] for r in rows].count("measure") == 9
    assert rows[0]["filament_label_g"] == "26", "the configured prior at pre-S of session 1"
    assert all(r["protocol"] == "long" and r["run_index"] == "1" for r in rows)
    assert [int(r["trial_index"]) for r in rows] == list(range(1, len(rows) + 1))
    # The site rotates on every application.
    sites = [int(r["site_index"]) for r in rows]
    assert all(a != b for a, b in zip(sites, sites[1:], strict=False))

    # Search 26 g (below), then 60 g (at or above): the crossing is 60 g, and the two below.
    measured = {r["filament_label_g"] for r in rows if r["purpose"] == "measure"}
    assert measured == {"15", "26", "60"}

    (calibration,) = _rows(session, "calibration_pinprick")
    assert calibration["start_filament_label_g"] == "26"
    assert calibration["start_source"] == "config_default"
    assert calibration["applications_total"] == str(len(rows))
    assert calibration["superseded"] == "false" and calibration["capped"] == "false"
    assert calibration["out_of_range"] == "false"
    assert float(calibration["f40_mn"]) == pytest.approx(result.f40_mn)
    assert calibration["chosen_filament_label_g"] == result.chosen_filament_label_g
    assert calibration["ordinal_rho"] != ""
    assert "measure_plan" in _events(session)


def test_the_same_seed_gives_the_same_sequence(app, loaded, tmp_path):
    def sequence(folder, seed):
        made = _make_rig(loaded, tmp_path / folder, seed=seed)
        protocol = _long(made)
        done = _start(protocol)
        _drive(protocol, done)
        labels = [(r["filament_label_g"], r["site_index"]) for r in _rows(made.session,
                                                                           "pinprick")]
        made.session.close()
        return labels

    assert sequence("a", 11) == sequence("b", 11)


def test_the_run_waits_for_the_experimenter(rig):
    protocol = _long(rig)
    protocol.start()
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline:
        QApplication.processEvents()
    assert rig.participant.stack.currentWidget() is not rig.participant.cue
    assert rig.experimenter.instruction.text() == rig.experimenter.text["instructions"]["ready"]
    protocol.cancel()


def test_an_emergency_stop_mid_protocol_loses_only_the_trial_in_progress(rig):
    session, participant, experimenter = rig.session, rig.participant, rig.experimenter
    protocol = _long(rig)
    done = _start(protocol)
    stopped = []

    def stop_once(answered, trial):
        if answered == 3 and not stopped:
            stopped.append(trial.trial_index)
            participant.emergency_stop.emit()
            assert participant.message.text == participant.text["screens"]["emergency_stop"]
            experimenter.resume_requested.emit()
            _spin(lambda: participant.stack.currentWidget() is participant.vas)

    _drive(protocol, done, before_answer=stop_once)
    rows = _rows(session, "pinprick")
    events = _events(session)
    assert stopped and "trial_cancelled" in events and "step_repeated" in events
    # The abandoned application wrote no row, and the repeat is a new application.
    assert len(rows) == done[0].applications_total
    assert [int(r["trial_index"]) for r in rows] == list(range(1, len(rows) + 1))
    assert [r["purpose"] for r in rows].count("measure") == 9


def test_a_discard_writes_a_discards_row_and_repeats(rig):
    session, experimenter = rig.session, rig.experimenter
    protocol = _long(rig)
    done = _start(protocol)
    participant = rig.participant
    # Answer the first rating, then discard it during the interval.
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    _answer(participant, _observer(protocol._trial))
    experimenter.discard_requested.emit()
    _drive(protocol, done)

    rows = _rows(session, "pinprick")
    (discard,) = _rows(session, "discards")
    assert discard["table"] == "pinprick"
    assert discard["trial_timestamp_iso"] == rows[0]["timestamp_iso"]
    assert discard["trial_index"] == "1"
    assert rows[1]["filament_label_g"] == rows[0]["filament_label_g"], "the same plan, repeated"
    assert rows[1]["trial_index"] == "2"
    assert done[0].applications_total == len(rows)


def test_a_discard_with_nothing_to_discard_is_ignored_and_logged(rig):
    protocol = _long(rig)
    protocol.start()
    rig.experimenter.discard_requested.emit()
    assert "discard_ignored" in _events(rig.session)
    assert _rows(rig.session, "discards") == []
    protocol.cancel()


def test_a_substitution_is_fitted_as_applied(rig):
    session, experimenter = rig.session, rig.experimenter
    protocol = _long(rig)
    done = _start(protocol)

    def substitute_first(answered, trial):
        if answered == 0:
            experimenter.substitution_entered.emit("15")

    _drive(protocol, done, before_answer=substitute_first)
    first = _rows(session, "pinprick")[0]
    assert first["filament_label_g"] == "26" and first["applied_filament_label_g"] == "15"
    assert first["substituted"] == "true" and first["force_applied_mn"] == "147.0"
    # The search steps from the filament applied: 15 g was below, so 26 g comes next.
    assert _rows(session, "pinprick")[1]["filament_label_g"] == "26"
    assert "substitution_entered" in _events(session)


def test_an_unknown_substitution_is_refused(rig):
    protocol = _long(rig)
    done = _start(protocol)

    def bad(answered, trial):
        if answered == 0:
            rig.experimenter.substitution_entered.emit("999")

    _drive(protocol, done, before_answer=bad)
    assert _rows(rig.session, "pinprick")[0]["substituted"] == "false"
    assert "substitution_unknown" in _events(rig.session)


def test_a_ceiling_rating_caps_the_site(rig):
    session = rig.session
    cap = IntolerableCap(99)
    protocol = _long(rig, cap=cap)
    done = _start(protocol)

    def respond(trial):
        # Intolerable at the first application, then an ordinary observer.
        return PRESSES_TO_THE_CEILING if trial.trial_index == 1 else _observer(trial)

    _drive(protocol, done, respond=respond)
    rows = _rows(session, "pinprick")
    assert rows[0]["intolerable"] == "true"
    site = int(rows[0]["site_index"])
    assert cap.cap_for("secondary", site) == 15, "the 26 g is index 15 of the held ladder"
    assert "intolerable_site_cap" in _events(session)
    held = session.config.filaments["filaments"]
    forces = {f["label_g"]: f["force_nominal_mn"] for f in held}
    for row in rows[1:]:
        if int(row["site_index"]) == site:
            assert forces[row["applied_filament_label_g"]] < forces["26"]


def test_the_fit_preview_rerun_keeps_the_superseded_run(app, loaded, tmp_path):
    study1 = {**loaded.study1, "fit_preview": {**loaded.study1["fit_preview"], "enabled": True}}
    rig = _make_rig(loaded, tmp_path, study1=study1)
    session, experimenter = rig.session, rig.experimenter
    protocol = _long(rig)
    fits = []
    protocol.fit_ready.connect(fits.append)
    done = _start(protocol)

    _spin(lambda: fits or (rig.participant.stack.currentWidget() is rig.participant.vas))
    while not fits:
        _answer(rig.participant, _observer(protocol._trial))
        _spin(lambda: fits or (rig.participant.stack.currentWidget() is rig.participant.vas))
    assert len(fits[0].points) == 9
    experimenter.fit_rerun_requested.emit("filament slipped")
    experimenter.proceed_requested.emit()
    while len(fits) < 2:
        _spin(lambda: len(fits) > 1 or (
            rig.participant.stack.currentWidget() is rig.participant.vas))
        if len(fits) < 2:
            _answer(rig.participant, _observer(protocol._trial))
    experimenter.fit_accepted.emit()
    assert done and done[0].run_index == 2

    first, second = _rows(session, "calibration_pinprick")
    assert (first["run_index"], first["superseded"], first["rerun_reason"]) == (
        "1", "true", "filament slipped")
    assert (second["run_index"], second["superseded"]) == ("2", "false")
    assert {r["run_index"] for r in _rows(session, "pinprick")} == {"1", "2"}
    assert session.fit_preview_reruns == 1
    session.close()


def test_the_fit_preview_rerun_is_bounded(app, loaded, tmp_path):
    study1 = {**loaded.study1, "fit_preview": {**loaded.study1["fit_preview"], "enabled": True,
                                                "max_reruns": 0}}
    rig = _make_rig(loaded, tmp_path, study1=study1)
    protocol = _long(rig)
    fits = []
    protocol.fit_ready.connect(fits.append)
    done = _start(protocol)
    while not fits:
        _spin(lambda: fits or (rig.participant.stack.currentWidget() is rig.participant.vas))
        if not fits:
            _answer(rig.participant, _observer(protocol._trial))
    rig.experimenter.fit_rerun_requested.emit("again")
    assert done and done[0].run_index == 1
    (row,) = _rows(rig.session, "calibration_pinprick")
    assert row["superseded"] == "false"
    assert "fit_rerun_refused" in _events(rig.session)
    rig.session.close()


# -- the short protocol and the brush -------------------------------------------------------


def test_the_short_protocol_takes_the_median_at_a_fixed_filament(rig):
    session = rig.session
    protocol = ShortProtocol(rig, "primary", "60")
    done = _start(protocol)
    presses = iter([1, 0, 1, 1, 0])
    _drive(protocol, done, respond=lambda trial: next(presses))
    result = done[0]
    rows = _rows(session, "pinprick")
    n_trials = session.config.study1["pinprick"]["short_protocol_n_trials"]
    assert len(rows) == n_trials
    assert {r["filament_label_g"] for r in rows} == {"60"}
    assert all(r["protocol"] == "short" and r["purpose"] == "measure" for r in rows)
    assert [int(r["site_index"]) for r in rows] == list(range(1, n_trials + 1))
    assert result.median_rating_percent == 75.0
    assert result.ratings_percent == (75.0, 25.0, 75.0, 75.0, 25.0)


def test_the_short_protocol_intervals_are_jittered_within_range(rig):
    session = rig.session
    protocol = ShortProtocol(rig, "primary", "26")
    done = _start(protocol)
    _drive(protocol, done)
    pinprick = session.config.study1["pinprick"]
    intervals = [
        float(r["detail"].split()[0]) for r in _rows(session, "log") if r["event"] == "interval"
    ]
    assert len(intervals) == pinprick["short_protocol_n_trials"]
    assert all(pinprick["isi_min_s"] <= s <= pinprick["isi_max_s"] for s in intervals)
    assert len(set(intervals)) > 1


def test_the_brush_writes_the_brush_table(rig):
    session = rig.session
    protocol = BrushProtocol(rig, "secondary")
    done = _start(protocol)
    _drive(protocol, done, respond=lambda trial: 0)
    rows = _rows(session, "brush")
    assert len(rows) == session.config.study1["brush"]["n_trials"]
    assert all(r["region"] == "secondary" and r["rating_cue_iso"] for r in rows)
    assert _rows(session, "pinprick") == []
    assert done[0].stimulus == "brush" and done[0].median_rating_percent == 25.0


def test_a_brush_discard_points_at_the_brush_table(rig):
    session = rig.session
    protocol = BrushProtocol(rig, "primary")
    done = _start(protocol)
    _spin(lambda: rig.participant.stack.currentWidget() is rig.participant.vas)
    _answer(rig.participant, 0)
    rig.experimenter.discard_requested.emit()
    _drive(protocol, done, respond=lambda trial: 0)
    rows = _rows(session, "brush")
    (discard,) = _rows(session, "discards")
    assert discard["table"] == "brush"
    assert discard["trial_timestamp_iso"] == rows[0]["timestamp_iso"]
    n_trials = session.config.study1["brush"]["n_trials"]
    assert len(rows) == n_trials + 1 and len(done[0].ratings_percent) == n_trials


def test_the_experimenter_never_sees_a_rating(rig):
    protocol = ShortProtocol(rig, "primary", "26")
    done = _start(protocol)
    seen = []

    # The status line is where the response is acknowledged, so it is where a rating would
    # leak. (The instruction names the filament's force, which is not a rating.)
    def watch(answered, trial):
        seen.append(rig.experimenter.status.text())

    _drive(protocol, done, before_answer=watch)
    seen.append(rig.experimenter.status.text())
    assert not any("75" in text or "25" in text for text in seen)
    assert math.isfinite(done[0].median_rating_percent)
