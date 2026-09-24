"""The whole session, in order, on a compressed schedule. SPEC.md 2, 7.4, 8.4, 12.3, 15, 16.

A real `SessionRunner` over a real session and both windows, driven by the introspecting
driver of `tests/virtual_participant.py` extended to the pain protocols and the experimenter's
launches. The schedule is shrunk and the protocols shortened so a whole session runs in seconds;
what is tested is the order, the timing rules and the records, not the protocols themselves,
which have their own tests.
"""

from __future__ import annotations

import copy
import csv
import math
import time

import pytest
from PySide6.QtWidgets import QApplication
from virtual_participant import EXAMPLES, Virtual, make_config, press

from tatp import config as cfg
from tatp import resume as resumption
from tatp.clock import Clock
from tatp.pinprick import BrushTrial, F40Fit, LongProtocol, PinprickTrial, ladder
from tatp.procedure import Rig
from tatp.responder import Responder
from tatp.session import Session
from tatp.session_runner import SessionRunner, Upcoming
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow

# As fast as the moving patterns allow: each pattern event is a flushed `garment` row, so above
# a few hundred times real speed the writes fall behind the pattern and never catch up.
CLOCK_SPEED = 400.0
RUN_TIMEOUT_S = 40.0
PAIN_F40_MN = 130.0
PAIN_SLOPE = 51.6
BRUSH_PCT = 10.0
DISTANCES_MM = (40.0, 35.0, 45.0, 30.0)


def compressed_schedule(loaded: cfg.Config) -> dict:
    schedule = copy.deepcopy(loaded.schedule)
    schedule["generate"].update(
        n_pinprick_blocks=2, n_touch_blocks=2,
        sensitisation_duration_min=0.5, capsaicin_start_offset_min=0.5,
        capsaicin_duration_min=1.0, intervention_start_offset_min=3.0,
        intervention_duration_min=10.0, rekindle_offset_min=8.0, rekindle_duration_min=0.5,
        block_spacing_min=1.5, expected_duration_min={"pinprick": 0.5, "touch": 0.5},
    )
    schedule["validation"]["max_session_duration_min"] = 1000.0
    return schedule


def short_study(loaded: cfg.Config) -> dict:
    study1 = copy.deepcopy(loaded.study1)
    study1["pinprick"]["short_protocol_n_trials"] = 2
    study1["brush"]["n_trials"] = 2
    study1["touch_block"]["n_repetitions"] = 1
    study1["mapping"]["max_steps"] = 3
    return study1


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


def make_runner(loaded, tmp_path, resume=None, condition=None, seed=7,
                fit_preview=False) -> SessionRunner:
    base = make_config(loaded, tmp_path)
    study1 = {**short_study(loaded), "choice": base.study1["choice"]}
    if fit_preview:
        study1["fit_preview"] = {**study1["fit_preview"], "enabled": True}
    config = cfg.Config(**{
        **base.__dict__, "schedule": compressed_schedule(loaded), "study1": study1,
    })
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED),
        rng_seed=seed if resume is None else resume.rng_seed,
        resumed_from="" if resume is None else resume.open.session_file.name,
    )
    if condition is not None:
        session._condition = condition
    session.start()
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    participant.resize(1280, 800)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    return SessionRunner(Rig(session, participant, experimenter), resume=resume)


class Driver(Virtual):
    """`Virtual`, plus pain ratings, the experimenter's launches and the mapping distances."""

    def __init__(self, rig, runner, stop_when=None):
        super().__init__(rig, runner)
        self.forces = {f.label_g: f.force_mn for f in ladder(rig.session.config)}
        self.stop_when = stop_when
        self.enter_distances = True
        self.reruns_left = 0

    def innermost(self):
        proc = self.procedure
        while proc._child is not None:
            proc = proc._child
        return proc

    def step(self) -> None:
        rig, window = self.rig, self.rig.participant
        if rig.interruptions.active is not None:
            super().step()
            return
        if self.enter_distances:
            for phase, point in self.procedure.ledger.time_points.items():
                if len(point.starts) == point.n_paths and not point.distances:
                    rig.experimenter.distances_entered.emit(phase, DISTANCES_MM)
        innermost = self.innermost()
        if isinstance(innermost, LongProtocol) and innermost._awaiting_fit is not None:
            if self.reruns_left:
                self.reruns_left -= 1
                rig.experimenter.fit_rerun_requested.emit("the driver re-runs once")
            else:
                rig.experimenter.fit_accepted.emit()
            return
        trial = self.current()
        if isinstance(trial, (PinprickTrial, BrushTrial)):
            if window.stack.currentWidget() is window.vas and trial.rating_cue_iso:
                press(window.vas, "pagedown")
                window.vas.state.percent = self._pain(trial)
                press(window.vas, "period")
            return
        if trial is None:
            if self.innermost()._on_go is not None:
                rig.experimenter.proceed_requested.emit()
            return
        super().step()

    def _pain(self, trial) -> float:
        if isinstance(trial, BrushTrial):
            return BRUSH_PCT
        force = self.forces[trial.applied_label_g]
        rating = 40 + PAIN_SLOPE * (math.log10(force) - math.log10(PAIN_F40_MN))
        return min(max(rating, 0.0), 100.0)

    def run(self, timeout_s: float = RUN_TIMEOUT_S):
        self.procedure.start()
        deadline = time.monotonic() + timeout_s
        while self.procedure.running and not self.procedure.session.closed:
            if self.stop_when is not None and self.stop_when():
                return
            if time.monotonic() > deadline:
                stage = self.procedure.stages[self.procedure.stage_index].id
                raise AssertionError(f"the session stalled at {self.current()!r}, {stage}")
            QApplication.processEvents()
            self.step()
            time.sleep(0.0005)


def _rows(session, table):
    path = session.files.path(table)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _events(session):
    return _rows(session, "log")


@pytest.fixture(scope="module")
def finished(app, loaded, tmp_path_factory):
    """One whole session, shared by the tests that only read what it wrote."""
    runner = make_runner(loaded, tmp_path_factory.mktemp("full"))
    Driver(runner.rig, runner).run()
    return runner


# -- the whole session -------------------------------------------------------------------------


def test_every_stage_runs_once_in_the_planned_order(finished):
    completed = [r["detail"] for r in _events(finished.session)
                 if r["event"] == "stage_completed"]
    assert completed == [stage.id for stage in finished.stages]
    assert finished.completed
    assert finished.session.closed


def test_the_order_of_the_session(finished):
    ids = [stage.id for stage in finished.stages]
    assert ids[:6] == [
        "setup.garment", "setup.welcome", "setup.masking_check", "setup.stop_rehearsal",
        "touch_calibration", "touch_calibration.baseline",
    ]
    assert ids.index("pre_sensitisation.long") < ids.index("sensitisation")
    assert ids.index("capsaicin.remove") < ids.index("post_sensitisation.long")
    assert ids.index("post_sensitisation.long") < ids.index("post_sensitisation.mapping")
    assert "pre_sensitisation.mapping" not in ids
    assert ids.index("intervention.start") < ids.index("block.1")
    assert ids.index("block.2") < ids.index("rekindle") < ids.index("block.3")
    assert ids.index("intervention.end") < ids.index("post_intervention.long")
    assert ids[-1] == "session_end"


def test_every_block_runs_in_order_and_records_its_lateness(finished):
    blocks = _rows(finished.session, "blocks")
    assert [int(b["block_index"]) for b in blocks] == [1, 2, 3, 4]
    for row in blocks:
        assert float(row["lateness_min"]) >= 0, "a block is never launched before it is due"
        assert row["aborted"] == "false"


def test_the_three_long_protocols_carry_their_prior_forward(finished):
    rows = _rows(finished.session, "calibration_pinprick")
    assert [r["phase"] for r in rows] == [
        "pre_sensitisation", "post_sensitisation", "post_intervention"
    ]
    assert [r["start_source"] for r in rows] == [
        "config_default", "previous_timepoint", "previous_timepoint"
    ]
    assert {r["region"] for r in rows} == {"secondary"}


def test_intervention_pinprick_blocks_use_the_post_s_filament(finished):
    chosen = next(r["chosen_filament_label_g"] for r in _rows(finished.session,
                  "calibration_pinprick") if r["phase"] == "post_sensitisation")
    block_rows = [r for r in _rows(finished.session, "pinprick") if r["block_index"]]
    assert block_rows
    assert {r["filament_label_g"] for r in block_rows} <= {chosen} | {
        f.label_g for f in ladder(finished.session.config)
    }
    assert {r["region"] for r in block_rows} == {"secondary"}
    assert {r["protocol"] for r in block_rows} == {"short"}


def test_primary_hyperalgesia_uses_the_fixed_filament(finished):
    primary = [r for r in _rows(finished.session, "pinprick") if r["region"] == "primary"]
    assert {r["filament_label_g"] for r in primary} == {"26"}
    assert {r["phase"] for r in primary} == {
        "pre_sensitisation", "post_sensitisation", "post_intervention"
    }


def test_touch_blocks_and_the_baseline_write_touch_ratings(finished):
    rows = _rows(finished.session, "touch_ratings")
    baseline = [r["scale"] for r in rows if r["phase"] == "touch_calibration"]
    assert baseline == ["relaxation", "alertness"]
    block = [r["scale"] for r in rows if r["block_index"] == "2"]
    assert block == ["intensity", "pleasantness", "relaxation", "alertness"]


def test_the_garment_is_off_for_the_rekindle_and_on_again_after(finished):
    events = _events(finished.session)
    names = [r["event"] for r in events]
    off = next(i for i, r in enumerate(events)
               if r["event"] == "garment_deactivated" and r["detail"] == "rekindle")
    on = names.index("garment_reactivated")
    assert off < on
    assert events[off]["phase"] == "rekindle"
    assert names.count("garment_activated") == 2, "at the intervention start and the rekindle"


def test_the_noise_stops_for_each_mapping_and_resumes(finished):
    events = [(r["event"], r["detail"]) for r in _events(finished.session)]
    stops = [i for i, (e, d) in enumerate(events)
             if e == "white_noise_stopped" and d == "area mapping"]
    resumes = [i for i, (e, d) in enumerate(events)
               if e == "white_noise_resumed" and d.startswith("area mapping ended")]
    assert len(stops) == len(resumes) == 2
    ticks = [i for i, (e, _) in enumerate(events) if e == "pacing_tick"]
    assert ticks and all(any(s < t < r for s, r in zip(stops, resumes, strict=True))
                         for t in ticks), "every audible tick falls inside a mapping"


def test_the_mapping_areas_are_recorded(finished):
    areas = _rows(finished.session, "sh_area")
    assert [r["phase"] for r in areas] == ["post_sensitisation", "post_intervention"]
    assert all(r["area_missing"] == "false" for r in areas)


def test_every_scheduled_step_is_alerted_and_every_alert_logged(finished):
    alerts = [r["detail"] for r in _events(finished.session)
              if r["event"] == "experimenter_alert"]
    # The compressed grid is shorter than the protocols, so every step here is already late when
    # it arrives, and the one alert it gets is the overdue one -- once, not a burst.
    for what in ("block 1", "block 2", "block 3", "block 4", "rekindle", "intervention"):
        assert sum(alert.startswith(what + " ") for alert in alerts) == 1, what
    assert "block 1 overdue" in alerts


def test_an_alert_sounds_ahead_of_a_step_that_is_not_yet_due(app, loaded, tmp_path):
    runner = make_runner(loaded, tmp_path)
    session = runner.session
    session.start_sensitisation()
    block = session.schedule.blocks[0]
    runner._set_alarms(Upcoming("block", "block", block.planned_offset_s, block), "block 1")
    assert [reason for _, reason in runner._alarms] == ["block 1 due", "block 1 overdue"]
    deadline = time.monotonic() + 10
    while runner._alarms and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.001)
    alerts = [r["detail"] for r in _events(session) if r["event"] == "experimenter_alert"]
    assert alerts == ["block 1 due", "block 1 overdue"]
    session.close()


def test_the_session_file_is_complete(finished):
    values = {r["key"]: r["value"] for r in _rows(finished.session, "session")}
    assert values["sensitisation_start_iso"]
    assert values["session_end_iso"]
    assert values["abort_reason"] == ""


# -- the experimenter view (the contract with Stream E) ----------------------------------------


def test_the_experimenter_view_has_the_agreed_keys(app, loaded, tmp_path):
    runner = make_runner(loaded, tmp_path)
    view = runner.session.experimenter_view()
    assert view["next_event"] is None, "nothing is scheduled before t=0"
    assert view["interruption"] is None
    assert set(view["hardware"]) == {"connected", "faults", "channel_pressure_kpa"}
    assert isinstance(view["hardware"]["channel_pressure_kpa"], dict)
    runner.rig.participant.emergency_stop.emit()
    assert runner.session.experimenter_view()["interruption"] == "emergency_stop"
    runner.session.close()


def test_the_next_event_counts_down_and_goes_overdue(app, loaded, tmp_path):
    runner = make_runner(loaded, tmp_path)
    session = runner.session
    session.start_sensitisation()
    block = session.schedule.blocks[0]
    session.set_upcoming("block", "block", block.planned_offset_s, block)
    upcoming = session.experimenter_view()["next_event"]
    assert upcoming["kind"] == "block" and upcoming["block_index"] == block.index
    assert upcoming["block_type"] == block.type
    assert 0 < upcoming["due_in_s"] <= block.planned_offset_s and not upcoming["overdue"]
    session.set_upcoming("phase", "capsaicin", 0.0)
    assert session.experimenter_view()["next_event"]["overdue"]
    session.close()


def _view_during_intervention(app, loaded, tmp_path, condition) -> dict:
    runner = make_runner(loaded, tmp_path / condition, condition=condition)
    session = runner.session
    session.start_sensitisation()
    session.set_phase("intervention")
    # What the condition would change: the pressures and the pattern playing.
    for channel in session.garment.channels():
        session.garment.set_pressure(channel, 20.0 if condition == "sham" else 60.0)
    pattern = "static_sham" if condition == "sham" else "sweep_03cms"
    session.garment.play_pattern(session.patterns[pattern])
    session.garment.advance()
    block = session.schedule.blocks[0]
    session.set_upcoming("block", "block", block.planned_offset_s, block)
    view = session.experimenter_view()
    session.close()
    # Times differ between two runs whatever the condition; everything else must not.
    for key in ("elapsed_s", "t_session_s"):
        view.pop(key)
    view["next_event"].pop("due_in_s")
    return view


def test_nothing_in_the_experimenter_view_differs_between_conditions(app, loaded, tmp_path):
    """SPEC.md 16, docs/LOG.md N7.D1: holding everything else fixed, three identical views."""
    views = [
        _view_during_intervention(app, loaded, tmp_path, condition)
        for condition in loaded.study1["design"]["conditions"]
    ]
    assert views[0]["hardware"]["channel_pressure_kpa"] is None
    assert views[0] == views[1] == views[2]


# -- resume (SPEC.md 15) -----------------------------------------------------------------------


def _crash_after(app, loaded, tmp_path, stage_id):
    """Run a session until `stage_id` has completed, then abandon it as a crash would."""
    runner = make_runner(loaded, tmp_path)

    def reached() -> bool:
        return any(r["event"] == "stage_completed" and r["detail"] == stage_id
                   for r in _events(runner.session))

    Driver(runner.rig, runner, stop_when=reached).run()
    runner.cancel()  # the process dies: nothing is closed, nothing more is written
    return runner


def test_an_open_session_is_found_and_a_closed_one_is_not(app, loaded, tmp_path):
    crashed = _crash_after(app, loaded, tmp_path, "setup.welcome")
    folder = crashed.session.data_folder
    found = resumption.find_open_session(folder, "01", 1)
    assert found is not None and found.session_file == crashed.session.files.path("session")
    assert found.sensitisation_start_iso is None
    assert "setup.welcome" in found.completed_stages
    crashed.session.close()
    assert resumption.find_open_session(folder, "01", 1) is None


def test_a_crash_before_t_zero_restarts_setup(app, loaded, tmp_path):
    crashed = _crash_after(app, loaded, tmp_path, "setup.masking_check")
    found = resumption.find_open_session(crashed.session.data_folder, "01", 1)
    state = resumption.load(found, crashed.session.config, True)
    assert not state.after_t_zero
    runner = make_runner(loaded, tmp_path, resume=state)
    Driver(runner.rig, runner, stop_when=lambda: runner.stage_index >= 1).run()
    names = [r["event"] for r in _events(runner.session)]
    assert "resume_restarts_setup" in names
    assert runner.stages[0].id in [r["detail"] for r in _events(runner.session)
                                   if r["event"] == "stage_started"]
    runner.cancel()
    runner.session.close()


def test_a_truncated_data_folder_reconstructs_the_session_state(app, loaded, tmp_path):
    """SPEC.md 17.2: a crash inside the intervention, then everything reloaded from disk."""
    crashed = _crash_after(app, loaded, tmp_path, "block.1")
    old = crashed.session
    found = resumption.find_open_session(old.data_folder, "01", 1)
    state = resumption.load(found, old.config, True)

    assert state.after_t_zero
    assert state.rng_seed == old.rng_seed
    assert state.clock_speed == CLOCK_SPEED
    assert found.sensitisation_start_iso == old.clock.sensitisation_start_iso
    post_s = next(r for r in _rows(old, "calibration_pinprick")
                  if r["phase"] == "post_sensitisation")
    chosen = state.chosen_filament_label_g["post_sensitisation"]
    assert chosen == post_s["chosen_filament_label_g"]
    pre_s = crashed.f40_mn["pre_sensitisation"]
    assert state.f40_mn["pre_sensitisation"] == pytest.approx(pre_s)
    for condition in old.config.study1["design"]["conditions"]:
        assert state.deliveries[condition].pattern_name == (
            crashed.deliveries[condition].pattern_name
        )
        for channel, kpa in crashed.deliveries[condition].pressure_kpa.items():
            assert state.deliveries[condition].pressure_kpa[channel] == pytest.approx(kpa)
    assert state.masking[0] == pytest.approx(old.white_noise_level_dbfs)
    assert "block.1" in state.completed_stages and "block.2" not in state.completed_stages


def test_a_resumed_session_keeps_t_zero_and_finishes_what_was_left(app, loaded, tmp_path):
    crashed = _crash_after(app, loaded, tmp_path, "block.1")
    old = crashed.session
    found = resumption.find_open_session(old.data_folder, "01", 1)
    state = resumption.load(found, old.config, True)
    runner = make_runner(loaded, tmp_path, resume=state)
    new = runner.session
    Driver(runner.rig, runner).run()

    assert runner.completed
    values = {r["key"]: r["value"] for r in _rows(new, "session")}
    assert values["resumed_from_session_file"] == old.files.path("session").name
    assert values["sensitisation_start_iso"] == old.clock.sensitisation_start_iso
    old_values = {r["key"]: r["value"] for r in _rows(old, "session")}
    for key in ("white_noise_level_dbfs", "masking_confirmed", "masking_attempts",
                "earplugs_used", "stop_rehearsal_press_detected"):
        assert values[key] == old_values[key], key
    started = [r["detail"] for r in _events(new) if r["event"] == "stage_started"]
    assert started[0] == "block.2", "resumed after the last completed block"
    assert "setup.masking_check" not in started
    assert [int(r["block_index"]) for r in _rows(new, "blocks")] == [2, 3, 4]
    names = [r["event"] for r in _events(new)]
    assert "session_resumed" in names
    assert names.index("garment_activated") < names.index("block_started"), (
        "the garment is started again before the next block"
    )
    # The prior of post-I came from the reloaded post-S estimate.
    post_i = next(r for r in _rows(new, "calibration_pinprick")
                  if r["phase"] == "post_intervention")
    assert post_i["start_source"] == "previous_timepoint"


def test_abort_marks_the_open_block_and_flags_missing_distances(app, loaded, tmp_path):
    runner = make_runner(loaded, tmp_path)
    driver = Driver(runner.rig, runner, stop_when=lambda: runner.session.block_index == 1)
    driver.enter_distances = False
    driver.run()
    runner.experimenter.abort_requested.emit("participant unwell")
    session = runner.session
    assert session.closed and not runner.completed
    assert [r["aborted"] for r in _rows(session, "blocks")] == ["true"]
    areas = _rows(session, "sh_area")
    assert [r["area_missing"] for r in areas] == ["true"]


# -- the fit preview (SPEC.md 11.1) ------------------------------------------------------------


def test_with_the_fit_preview_on_an_f40_is_rerun_once_then_accepted(app, loaded, tmp_path,
                                                                    monkeypatch):
    hidden = []
    monkeypatch.setattr(ExperimenterWindow, "hide_fit_preview", lambda self: hidden.append(1))
    runner = make_runner(loaded, tmp_path, fit_preview=True)
    shown = []
    runner.experimenter.show_fit_preview = shown.append
    driver = Driver(runner.rig, runner, stop_when=lambda: runner.stage_index > [
        s.id for s in runner.stages].index("pre_sensitisation.long"))
    driver.reruns_left = 1
    driver.run()
    rows = _rows(runner.session, "calibration_pinprick")
    assert [(r["run_index"], r["superseded"]) for r in rows] == [("1", "true"), ("2", "false")]
    assert rows[0]["rerun_reason"] == "the driver re-runs once"
    f40_fits = [fit for fit in shown if isinstance(fit, F40Fit)]
    assert len(f40_fits) == 2, "the preview is shown for each run"
    assert len(shown) == 3, "and once for the touch calibration"
    assert len(hidden) >= len(shown), "and taken down after every decision"
    values = runner.session.fit_preview_reruns
    assert values == 1
    runner.cancel()
    runner.session.close()
