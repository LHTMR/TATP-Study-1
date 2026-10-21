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
import sys
import time

import pytest
from PySide6.QtWidgets import QApplication
from virtual_participant import EXAMPLES, Virtual, make_config, press

from tatp import config as cfg
from tatp import resume as resumption
from tatp import session_runner
from tatp.audio import AudioError
from tatp.clock import Clock
from tatp.pinprick import BrushTrial, F40Fit, LongProtocol, PinprickTrial, ladder, prior_for
from tatp.procedure import Rig
from tatp.responder import Responder
from tatp.session import Session
from tatp.session_runner import SessionRunner, TouchBlock, Upcoming, stop_on_error
from tatp.touchcal import Comparison, TouchCalibration, TouchRating
from tatp.touchcal_maths import Delivery
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow

# As fast as the moving patterns allow: each pattern event is a flushed `garment` row, so above
# a few hundred times real speed the writes fall behind the pattern and never catch up.
CLOCK_SPEED = 400.0
RUN_TIMEOUT_S = 90.0  # generous: the gate runs this beside every other test
PAIN_F40_MN = 130.0
PAIN_SLOPE = 51.6
BRUSH_PCT = 10.0
DISTANCES_MM = (40.0, 35.0, 45.0, 30.0)
# The touch-start test times what the experimenter sees, so it runs slower: at this speed the
# tolerance below is 80 ms of real time, which a loaded machine's timers stay inside.
TIMING_CLOCK_SPEED = 50.0
TIMING_TOLERANCE_S = 4.0
# How early the session may move on: one Windows timer tick (15.6 ms) of real time. Under the
# parallel test load it has moved on up to 6.9 ms early, which a bare timer in a probe never
# did (docs/LOG.md N7.U9). At real speed that is milliseconds of a six-second display.
EARLY_S = 0.016 * TIMING_CLOCK_SPEED


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
    # Wider than the rekindle's heat, so the block after it is already due when the removal is
    # awaited however promptly the session runs. Since the scale comes at the delivery press
    # (LOG N7.F17a) the protocols no longer make every step late, and whether this one was came
    # down to the machine's load.
    schedule["validation"]["due_alert_lead_s"] = 120.0
    # And an overdue margin of 1.5 real seconds at CLOCK_SPEED: at 60 s it was 150 ms, which
    # the parallel gate's load could put between a block falling due and the simulated go, so a
    # prompt launch sometimes sounded overdue as well. The overdue alert has its own test.
    schedule["validation"]["overdue_alert_margin_s"] = 600.0
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
                fit_preview=False, session_number=1, speed=CLOCK_SPEED,
                recalibrations_max=None) -> SessionRunner:
    base = make_config(loaded, tmp_path)
    study1 = {**short_study(loaded), "choice": base.study1["choice"]}
    study1["touch_calibration"] = {**study1["touch_calibration"],
                                   "recalibrations_max": recalibrations_max}
    if fit_preview:
        study1["fit_preview"] = {**study1["fit_preview"], "enabled": True}
    config = cfg.Config(**{
        **base.__dict__, "schedule": compressed_schedule(loaded), "study1": study1,
    })
    session = Session(
        config, "01", session_number, "SM", EXAMPLES, clock=Clock(speed=speed),
        rng_seed=seed if resume is None else resume.rng_seed,
        resumed_from="" if resume is None else resume.open.session_file.name,
    )
    if condition is not None:
        session._condition = condition
    session.start()
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    participant.resize(1280, 800)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    handed_over = False
    try:
        runner = SessionRunner(Rig(session, participant, experimenter), resume=resume)
        handed_over = True
        return runner
    finally:
        # As `run_session.build`: a refused runner lets the session's files go.
        if not handed_over:
            session.files.release()


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
            if trial.awaits_proceed:
                rig.experimenter.proceed_requested.emit()  # applied
            elif window.stack.currentWidget() is window.vas and trial.rating_cue_iso:
                press(window.vas, "pagedown")
                window.vas.state.percent = self._pain(trial)
                press(window.vas, "f5")
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
    """One whole session, shared by the tests that only read what it wrote.

    Only what it wrote: its windows are deleted when the first test using it ends
    (tests/conftest.py)."""
    runner = make_runner(loaded, tmp_path_factory.mktemp("full"))
    # Every instruction the experimenter was shown, in order, for the tests of what they say.
    runner.shown_instructions = []
    # And what the countdown named as each was shown.
    runner.shown_upcoming = []
    real = runner.experimenter.set_instruction

    def spy(text, *rest):
        runner.shown_instructions.append(text)
        upcoming = runner.session._upcoming
        runner.shown_upcoming.append(None if upcoming is None else upcoming[1])
        real(text, *rest)

    runner.experimenter.set_instruction = spy
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
        "setup.garment", "setup.welcome", "setup.stop_rehearsal", "setup.masking_check",
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


def test_each_scale_is_trained_once_before_its_first_rating(finished):
    """SPEC.md 10.6, Bilaga 1 3.9: intensity then pleasantness at the start of touch
    calibration, before step 1; pain at pre-S; none in the intervention; relaxation and
    alertness have no training."""
    events = _events(finished.session)
    confirmed = [r for r in events if r["event"] == "vas_training_confirmed"]
    assert [r["detail"] for r in confirmed] == ["intensity", "pleasantness", "pain"]
    assert [r["phase"] for r in confirmed] == [
        "touch_calibration", "touch_calibration", "pre_sensitisation"
    ]
    assert all(r["origin"] == "participant" for r in confirmed)
    names = [(r["event"], r["detail"]) for r in events]
    first_adjustment = next(i for i, r in enumerate(events)
                            if r["event"] == "touch_calibration_run")
    assert names.index(("vas_training_confirmed", "pleasantness")) < first_adjustment
    for scale in ("intensity", "pain", "pleasantness"):
        shown = names.index(("vas_training_shown", scale))
        explained = names.index(("vas_training_explained", scale))
        assert events[explained]["origin"] == "experimenter"
        assert shown < explained < names.index(("vas_training_confirmed", scale))
        assert names.index(("vas_training_confirmed", scale)) < names.index(
            ("rating_cued", scale)
        ), f"{scale} was rated before its training"


def test_training_is_given_only_in_the_configured_sessions(app, loaded, tmp_path):
    study1 = {**loaded.study1,
              "training": {**loaded.study1["training"], "vas_proportionality_sessions": [1]}}
    config = cfg.Config(**{**make_config(loaded, tmp_path).__dict__, "study1": study1})
    first = Session(config, "01", 1, "SM", EXAMPLES, rng_seed=7)
    try:
        second = Session(config, "01", 2, "SM", EXAMPLES, rng_seed=7)
        try:
            assert first.vas_training_due("pain") and not second.vas_training_due("pain")
            assert not first.vas_training_due("relaxation"), "no training text, no training"
            first.vas_trained.add("pain")
            assert not first.vas_training_due("pain")
        finally:
            second.close()
    finally:
        first.close()


def test_an_empty_session_list_means_no_training(app, loaded, tmp_path):
    study1 = {**loaded.study1,
              "training": {**loaded.study1["training"], "vas_proportionality_sessions": []}}
    config = cfg.Config(**{**make_config(loaded, tmp_path).__dict__, "study1": study1})
    session = Session(config, "01", 1, "SM", EXAMPLES, rng_seed=7)
    try:
        assert not any(session.vas_training_due(s) for s in session.trained_scales)
    finally:
        session.close()


def test_a_touch_block_refuses_to_run_a_scale_never_trained(app, loaded, tmp_path):
    """SPEC.md 10.6: a touch scale the calibration did not train is a defect, not a rating."""
    runner = make_runner(loaded, tmp_path)
    try:
        with pytest.raises(AssertionError, match="never trained"):
            TouchBlock(runner.rig, runner.reference_channel, 1)
    finally:
        runner.session.close()


def test_the_garment_is_off_for_the_rekindle_and_on_again_after(finished):
    events = _events(finished.session)
    names = [r["event"] for r in events]
    off = next(i for i, r in enumerate(events)
               if r["event"] == "garment_deactivated" and r["detail"] == "rekindle")
    on = names.index("garment_reactivated")
    assert off < on
    assert events[off]["phase"] == "rekindle"
    assert names.count("garment_activated") == 2, "at the intervention start and the rekindle"


def _shown(finished, key, **values) -> int:
    """Where the instruction `key` was first shown, in the order the session showed them."""
    text = cfg.instruction(finished.session.config, key, **values)
    return finished.shown_instructions.index(text)


def test_the_rekindle_tells_the_experimenter_each_step(finished):
    """15 Oct 2026 pilot review: the heat counted down, then the thermode removed with the
    experimenter's go before the garment's touch starts again (LOG N7.F11b10)."""
    heat = _shown(finished, "thermode_rekindle")
    heating = _shown(finished, "rekindle_heating")
    remove = _shown(finished, "rekindle_remove")
    restart = finished.shown_instructions.index(
        finished.experimenter.text["instructions"]["touch_start"], remove
    )
    assert heat < heating < remove < restart
    events = _events(finished.session)
    presses = [r for r in events if r["event"] == "proceed" and r["phase"] == "rekindle"]
    assert len(presses) == 2, "the heat started, and the thermode removed"
    reactivated = next(r for r in events if r["event"] == "garment_reactivated")
    assert float(presses[-1]["t_session_s"]) <= float(reactivated["t_session_s"])


def test_the_heat_and_the_capsaicin_say_what_is_on(finished):
    assert _shown(finished, "thermode_start", minutes="0.5") < _shown(finished, "heat_on")
    assert _shown(finished, "capsaicin_apply") < _shown(finished, "capsaicin_on")
    assert _shown(finished, "capsaicin_on") < _shown(finished, "capsaicin_remove")


def test_the_capsaicin_removal_is_logged_by_its_own_name(finished):
    """The countdown during the capsaicin names its removal, not the phase after it, and the
    log's scheduled step carries the same name (LOG N7.F11b17)."""
    started = [r["detail"].split(";")[0] for r in _events(finished.session)
               if r["event"] == "scheduled_step_started"]
    assert "capsaicin_removal" in started and "post_sensitisation" not in started


def test_each_block_says_what_it_is_before_it_starts(finished):
    text = finished.experimenter.text
    region = text["terms"]["regions"]["secondary"]
    filament = finished.chosen_filament_label_g["post_sensitisation"]
    n = finished.session.config.study1["pinprick"]["short_protocol_n_trials"]
    for block in finished.session.schedule.blocks:
        if block.type == "pinprick":
            ready = cfg.instruction(finished.session.config, "ready_short",
                                    n=n, filament=filament, region=region)
            _shown(finished, "ready_pinprick_block", block=block.index, ready=ready)
        else:
            _shown(finished, "ready_touch_block", block=block.index)


def test_the_first_pain_measure_is_introduced_once(finished):
    """Before the pain scale's training, what the participant is told (LOG N7.F11b14)."""
    config = finished.session.config
    first = cfg.instruction(config, "ready_long_first")
    assert finished.shown_instructions.count(first) >= 1
    training = next(i for i, t in enumerate(finished.shown_instructions)
                    if config.say["proportionality"]["pain"] in t)
    assert finished.shown_instructions.index(first) < training
    later = finished.shown_instructions[training:]
    assert first not in later, "the later long protocols have the ordinary ready line"


def test_the_gap_after_a_rating_does_not_leave_the_last_application_up(finished):
    """LOG N7.F11b8: during the interval the instruction says to wait."""
    between = finished.experimenter.text["instructions"]["between_applications"]
    assert between in finished.shown_instructions


def test_the_noise_is_heard_only_while_the_garment_may_run(finished):
    """S, 21 Oct 2026: silenced in every phase that does not need it and while the
    experimenter explains something; it masks the garment (Bilaga 3a). Heard through the touch
    calibration and the intervention's touch, silent for the mappings and every pain measure
    outside the intervention."""
    events = [(r["event"], r["detail"], r["phase"]) for r in _events(finished.session)]
    heard, intervals, start = False, [], None
    for i, (event, _detail, _phase) in enumerate(events):
        if event == "white_noise_silenced" and heard:
            intervals.append((start, i))
            heard = False
        elif event in ("white_noise_resumed", "white_noise_started") and not heard:
            heard, start = True, i
    if heard:
        intervals.append((start, len(events)))

    def during(index: int) -> bool:
        return any(a <= index < b for a, b in intervals)

    ticks = [i for i, (e, _, _) in enumerate(events) if e == "pacing_tick"]
    assert ticks and not any(during(t) for t in ticks), "every tick in silence"
    cues = [i for i, (e, _, p) in enumerate(events)
            if e == "stimulus_due" and p in ("pre_sensitisation", "post_sensitisation")]
    assert cues and not any(during(c) for c in cues), "no noise for the pain measures"
    touch = [i for i, (e, _, p) in enumerate(events)
             if e == "warning_cue" and p == "touch_calibration"]
    assert touch and all(during(c) for c in touch), "the noise masks the calibration"
    on = [i for i, (e, _, _) in enumerate(events) if e == "garment_activated"]
    assert on and all(during(i) for i in on), "and the intervention's touch"
    said = [i for i, (e, d, _) in enumerate(events)
            if e == "white_noise_silenced" and d == "a sentence said aloud"]
    assert said, "silenced while the experimenter says something aloud"


def test_the_mapping_areas_are_recorded(finished):
    areas = _rows(finished.session, "sh_area")
    assert [r["phase"] for r in areas] == ["post_sensitisation", "post_intervention"]
    assert all(r["area_missing"] == "false" for r in areas)


def test_every_scheduled_step_is_alerted_and_every_alert_logged(finished):
    alerts = [r["detail"] for r in _events(finished.session)
              if r["event"] == "experimenter_alert"]
    # One alert a step, whether it arrives early (the due one, on its timer), a little late (the
    # due one, at once) or very late (the overdue one alone) -- never a burst.
    for what in ("block 1", "block 2", "block 3", "block 4", "rekindle", "intervention"):
        assert sum(alert.startswith(what + " ") for alert in alerts) == 1, what


def test_the_rekindle_heat_end_is_alerted_and_the_next_block_is_not_delayed(finished):
    """Spec-review of N7.F11b10: the touch restarts on the removal press, so the heat's end is
    alerted like a scheduled step, and the next block's alerts are armed while the removal is
    awaited -- the block's alert sounds at its time, never twice."""
    events = _events(finished.session)
    alerts = [(i, r["detail"]) for i, r in enumerate(events)
              if r["event"] == "experimenter_alert"]
    assert any(detail.startswith("rekindle_end ") for _, detail in alerts)
    removed = next(i for i, r in enumerate(events) if r["event"] == "rekindle_thermode_removed")
    after = finished.stages[[s.id for s in finished.stages].index("rekindle") + 1]
    name = f"block {after.upcoming.block.index}"
    theirs = [(i, detail) for i, detail in alerts if detail.startswith(name + " ")]
    assert len(theirs) == 1, "once, not again when the block's own stage sets its alarms"
    assert theirs[0][0] < removed, "sounded while the removal was awaited"


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


def test_the_first_participant_screen_says_the_session_will_start(app, loaded, tmp_path):
    """S, 30 Sep 2026: not 'Rest for a moment' to someone who has only just sat down."""
    runner = make_runner(loaded, tmp_path)
    try:
        runner.start()
        participant = runner.rig.participant
        assert participant.message.text == participant.text["screens"]["session_starting"]
    finally:
        runner.session.close()


# -- the experimenter view (the contract with Stream E) ----------------------------------------


def test_the_experimenter_view_has_the_agreed_keys(app, loaded, tmp_path):
    runner = make_runner(loaded, tmp_path)
    view = runner.session.experimenter_view()
    assert view["next_event"] is None, "nothing is scheduled before t=0"
    assert view["interruption"] is None
    assert set(view["hardware"]) == {"connected", "link_lost", "faults", "channel_pressure_kpa",
                                     "channels_on"}
    assert isinstance(view["hardware"]["channel_pressure_kpa"], dict)
    assert isinstance(view["hardware"]["channels_on"], list)
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
    # Due soon from the due alert, overdue only past the overdue alert's margin, as the alerts
    # sound (S, 21 Oct 2026: OVERDUE the moment it fell due was alarming).
    validation = session.config.schedule["validation"]
    now_s = session.clock.t_session_s()
    session.set_upcoming("phase", "capsaicin", now_s + validation["due_alert_lead_s"] / 2)
    upcoming = session.experimenter_view()["next_event"]
    assert upcoming["due_soon"] and not upcoming["overdue"]
    session.set_upcoming("phase", "capsaicin", now_s - validation["overdue_alert_margin_s"] / 2)
    upcoming = session.experimenter_view()["next_event"]
    assert upcoming["due_in_s"] < 0 and not upcoming["overdue"], "late, not yet overdue"
    session.set_upcoming("phase", "capsaicin", now_s - validation["overdue_alert_margin_s"] * 2)
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
    assert views[0]["hardware"]["channels_on"] is None
    assert views[0] == views[1] == views[2]


# -- resume (SPEC.md 15) -----------------------------------------------------------------------


def _crash_after(app, loaded, tmp_path, stage_id, event="stage_completed"):
    """Run a session until `event` is logged for `stage_id`, then abandon it as a crash would.

    `stage_id` is matched against the start of the event's detail."""
    runner = make_runner(loaded, tmp_path)

    def reached() -> bool:
        return any(r["event"] == event and r["detail"].startswith(stage_id)
                   for r in _events(runner.session))

    Driver(runner.rig, runner, stop_when=reached).run()
    runner.cancel()  # the process dies: nothing is closed, nothing more is written
    return runner


def _resumed(loaded, tmp_path, crashed):
    found = resumption.find_open_session(crashed.session.data_folder, "01", 1)
    state = resumption.load(found, crashed.session.config, True)
    return make_runner(loaded, tmp_path, resume=state)


def test_an_open_session_is_found_and_a_closed_one_is_not(app, loaded, tmp_path):
    crashed = _crash_after(app, loaded, tmp_path, "setup.welcome")
    folder = crashed.session.data_folder
    found = resumption.find_open_session(folder, "01", 1)
    assert found is not None and found.session_file == crashed.session.files.path("session")
    assert found.sensitisation_start_iso is None
    assert "setup.welcome" in found.completed_stages
    crashed.session.close()
    assert resumption.find_open_session(folder, "01", 1) is None


def test_a_session_from_before_the_skin_marking_resumes_where_it_stopped(app, loaded,
                                                                         tmp_path):
    """Spec review of N7.F16l: a log written before `pre_sensitisation.mark_zone` existed has
    no row completing it. Resumed, it goes on from where it crashed -- not back to marking the
    skin, which it is past."""
    crashed = _crash_after(app, loaded, tmp_path, "pre_sensitisation.long")
    log = crashed.session.files.path("log")
    lines = log.read_text(encoding="utf-8").splitlines(keepends=True)
    old = [line for line in lines
           if not ("stage_completed" in line and session_runner.MARK_ZONE_STAGE in line)]
    assert len(old) == len(lines) - 1, "the marking's completion, as an old build never wrote"
    log.write_text("".join(old), encoding="utf-8")
    runner = _resumed(loaded, tmp_path, crashed)
    begun = []
    Driver(runner.rig, runner, stop_when=lambda: begun.append(1) or len(begun) > 1).run()
    started = [r["detail"] for r in _events(runner.session) if r["event"] == "stage_started"]
    assert started[0] == "pre_sensitisation.short_primary"
    runner.cancel()
    runner.session.close()


def test_a_crash_before_t_zero_reloads_what_was_completed(app, loaded, tmp_path):
    """SPEC.md 15: calibrations are reloaded, not redone -- before t=0 as after it."""
    crashed = _crash_after(app, loaded, tmp_path, "touch_calibration.baseline")
    runner = _resumed(loaded, tmp_path, crashed)
    assert not runner.resume.after_t_zero
    # The skin marking, which begins pre-sensitisation (LOG N7.F16l).
    interrupted = "pre_sensitisation.mark_zone"
    assert runner.resume.in_progress == interrupted
    begun = []
    Driver(runner.rig, runner, stop_when=lambda: begun.append(1) or len(begun) > 1).run()
    events = _events(runner.session)
    started = [r["detail"] for r in events if r["event"] == "stage_started"]
    assert started[0] == interrupted, "resumed at the stage that was interrupted"
    redone = [r for r in events if r["event"] == "stage_redone"]
    assert redone and interrupted in redone[0]["detail"]
    assert runner.deliveries == crashed.deliveries, "the touch calibration was reloaded"
    values = {r["key"]: r["value"] for r in _rows(runner.session, "session")}
    old = {r["key"]: r["value"] for r in _rows(crashed.session, "session")}
    assert values["white_noise_level_dbfs"] == old["white_noise_level_dbfs"]
    assert runner.session.audio.noise_running, "the noise is back at the chosen level"
    runner.cancel()
    runner.session.close()


def test_a_resume_of_an_old_order_session_skips_the_completed_masking_check(
    app, loaded, tmp_path, monkeypatch
):
    """Before 5 Oct 2026 the masking check came before the stop rehearsal. A session file
    written in that order, crashed between the two, resumes at the rehearsal -- and the
    masking check after it is already done, so it is skipped, not run and recorded twice."""
    from tatp import session_runner

    original = session_runner.stage_layout

    def old_order(schedule):
        stages = original(schedule)
        ids = [stage[0] for stage in stages]
        i, j = ids.index("setup.stop_rehearsal"), ids.index("setup.masking_check")
        stages[i], stages[j] = stages[j], stages[i]
        return stages

    monkeypatch.setattr(session_runner, "stage_layout", old_order)
    crashed = _crash_after(app, loaded, tmp_path, "setup.masking_check")
    monkeypatch.setattr(session_runner, "stage_layout", original)

    runner = _resumed(loaded, tmp_path, crashed)

    def past_the_setup() -> bool:
        return any(r["event"] == "stage_started" and r["detail"] == "touch_calibration"
                   for r in _events(runner.session))

    Driver(runner.rig, runner, stop_when=past_the_setup).run()
    started = [r["detail"] for r in _events(runner.session) if r["event"] == "stage_started"]
    assert started[:2] == ["setup.stop_rehearsal", "touch_calibration"]
    keys = [r["key"] for r in _rows(runner.session, "session")]
    assert keys.count("masking_confirmed") == 1, "the masking keys are written once"
    runner.cancel()
    runner.session.close()


def test_a_resume_during_the_rekindle_never_prompts_the_heat_again(app, loaded, tmp_path):
    """The heat was launched before the crash: it is confirmed, timed from then, and the
    garment stays off until the rekindle completes."""
    crashed = _crash_after(app, loaded, tmp_path, "rekindle;", event="scheduled_step_started")
    runner = _resumed(loaded, tmp_path, crashed)
    assert runner.resume.rekindle_heat_t_s is not None
    # Until the touch is running again, which at this clock speed can land a timer tick after
    # the stage itself completes.
    Driver(runner.rig, runner, stop_when=lambda: "garment_activated" in [
        r["event"] for r in _events(runner.session)
    ]).run()
    events = [(r["event"], r["detail"]) for r in _events(runner.session)]
    names = [event for event, _ in events]
    assert ("stage_started", "rekindle") in events
    assert not any(e == "scheduled_step_started" and d.startswith("rekindle")
                   for e, d in events), "the heat is not prompted a second time"
    assert "rekindle_resumed" in names
    assert names.index("rekindle_heat_confirmed") < names.index("garment_activated")
    confirmed_s = next(float(r["t_session_s"]) for r in _events(runner.session)
                       if r["event"] == "rekindle_heat_confirmed")
    early = [r for r in _rows(runner.session, "garment")
             if r["event"] == "pattern_start" and float(r["t_session_s"]) <= confirmed_s]
    assert not early, "the garment stays off until the rekindle is over"
    runner.cancel()
    runner.session.close()


def test_a_resume_after_the_thermode_came_off_only_restarts_the_touch(app, loaded, tmp_path):
    """Code review of N7.F11b10: the removal was pressed before the crash, so neither the heat
    nor the removal is asked for again; the heat-resume logic of N7.D14 is not reached."""
    crashed = _crash_after(app, loaded, tmp_path, "", event="rekindle_thermode_removed")
    runner = _resumed(loaded, tmp_path, crashed)
    assert runner.resume.rekindle_thermode_removed
    shown = []
    real = runner.experimenter.set_instruction
    runner.experimenter.set_instruction = lambda text, *rest: (shown.append(text),
                                                               real(text, *rest))
    Driver(runner.rig, runner, stop_when=lambda: "garment_activated" in [
        r["event"] for r in _events(runner.session)
    ]).run()
    names = [r["event"] for r in _events(runner.session)]
    assert "rekindle_resumed" in names
    assert "rekindle_heat_confirmed" not in names, "the heat is not asked about"
    assert "rekindle_thermode_removed" not in names, "nor the removal"
    config = runner.session.config
    for key in ("rekindle_resumed", "rekindle_remove", "thermode_rekindle"):
        assert cfg.instruction(config, key) not in shown
    runner.cancel()
    runner.session.close()


def _recalibrating_driver(runner, choice, stop_when, during=TouchRating):
    """A driver that stops once in run 1, during a `during` trial, and chooses `choice`
    instead of Resume (docs/LOG.md N7.F12a1)."""
    driver = Driver(runner.rig, runner, stop_when=stop_when)
    done = []

    def step(trial):
        calibration = driver.innermost()
        if (not done and isinstance(calibration, TouchCalibration)
                and calibration.run_index == 1 and isinstance(trial, during)):
            done.append(True)
            press(runner.rig.participant, "period")
            runner.experimenter.recalibration_requested.emit(choice, "other")

    driver.before_step = step
    return driver


def _logged(runner, event, detail=None) -> bool:
    return any(r["event"] == event and (detail is None or r["detail"] == detail)
               for r in _events(runner.session))


def _offered(runner) -> tuple[bool, bool, bool]:
    """(rebalance, restart, used up) as the window offers them: one Re-calibrate… control
    whose dialog lists what can be taken (S, 21 Oct 2026)."""
    window = runner.experimenter
    shown = not window.recalibrate_button.isHidden()
    return (shown and window._awaiting["recalibrate_rebalance"],
            shown and window._awaiting["recalibrate_restart"],
            not window.recalibration_used.isHidden())


def _details(runner, event) -> list[str]:
    return [r["detail"] for r in _events(runner.session) if r["event"] == event]


def test_a_crash_after_a_restart_after_a_stop_redoes_the_calibration_and_keeps_the_count(
    app, loaded, tmp_path
):
    """The crashed calibration is redone from its start (SPEC.md 15), and the re-calibration
    it had still counts towards the limit (docs/LOG.md N7.F12a1)."""
    crashed = make_runner(loaded, tmp_path)
    _recalibrating_driver(crashed, "restart", lambda: _logged(
        crashed, "touch_calibration_run", "run 2")).run()
    crashed.cancel()
    runner = _resumed(loaded, tmp_path, crashed)
    assert runner.resume.in_progress == "touch_calibration"
    assert runner.resume.recalibrations == 1
    offered = []
    driver = Driver(runner.rig, runner,
                    stop_when=lambda: _logged(runner, "stage_completed", "touch_calibration"))

    def stop_again(trial):
        if not offered and isinstance(trial, TouchRating):
            press(runner.rig.participant, "period")
            offered.append(_offered(runner))

    driver.before_step = stop_again
    driver.run()
    assert offered == [(False, True, False)], "no limit; no fit yet to rebalance against"
    assert _details(runner, "recalibration") == [
        "resume; emergency_stop; touch_calibration/step2_estimation; ; "]
    assert runner.session.recalibrations == 1
    assert runner.deliveries is not None
    assert runner.resume.touchcal_runs == 1
    fits = [(r["run_index"], r["superseded"]) for r in _rows(runner.session, "touchcal_fit")]
    assert fits == [("2", "false")], "its runs numbered on from the crashed files' (review)"
    runner.cancel()
    runner.session.close()


def test_a_crash_after_a_rebalanced_calibration_reloads_what_it_delivers(app, loaded, tmp_path):
    crashed = make_runner(loaded, tmp_path)
    _recalibrating_driver(crashed, "rebalance", lambda: _logged(
        crashed, "stage_completed", "touch_calibration"), during=Comparison).run()
    crashed.cancel()
    assert _details(crashed, "recalibration") == [
        "rebalance; emergency_stop; touch_calibration/step4_compare; other; 1"]
    runner = _resumed(loaded, tmp_path, crashed)
    assert "touch_calibration" in runner.resume.completed_stages
    assert runner.resume.recalibrations == 1 and runner.resume.calibrations_used == 1
    Driver(runner.rig, runner, stop_when=lambda: True).run()  # starts it, which reloads
    assert runner.deliveries == crashed.deliveries, "what the rebalanced calibration delivers"
    assert runner.session.recalibrations == 1
    runner.cancel()
    runner.session.close()


def _in_the_calibration(runner, when):
    """The stage's touch calibration, while `when(calibration, trial)`."""
    calibration = runner._calibration_running()
    return calibration is not None and when(calibration)


def test_in_touch_calibration_a_plain_resume_is_recorded_as_the_choice(app, loaded, tmp_path):
    """The runner owns the record (code review of N7.F12a1): every resume from a stop while
    touch is calibrated is logged as a choice, and is not a re-calibration."""
    runner = make_runner(loaded, tmp_path)
    driver = Driver(runner.rig, runner,
                    stop_when=lambda: _logged(runner, "stage_completed", "touch_calibration"))
    stopped = []

    def stop_once(trial):
        if not stopped and isinstance(trial, TouchRating) and _in_the_calibration(
                runner, lambda c: c.estimates):
            stopped.append(_offered(runner))
            press(runner.rig.participant, "period")
            stopped.append(_offered(runner))

    driver.before_step = stop_once
    driver.run()
    assert stopped == [(False, True, False), (False, True, False)], "running, and stopped"
    (choice,) = [r for r in _events(runner.session) if r["event"] == "recalibration"]
    assert choice["detail"] == "resume; emergency_stop; touch_calibration/step2_estimation; ; "
    assert choice["origin"] == "experimenter"
    assert runner.session.recalibrations == 0
    assert _offered(runner) == (False, False, False), "withdrawn once the calibration ends"
    runner.cancel()
    runner.session.close()


def test_a_resume_with_nothing_to_restore_offers_the_choice_again(app, loaded, tmp_path):
    """Code review of N7.F12a1: a stop while the garment is idle -- an introduction screen --
    resumes at once, inside the Resume press; the offers are worked out afresh, never
    withdrawn after it, so they come back."""
    runner = make_runner(loaded, tmp_path)
    seen = []

    def at_the_estimation_intro() -> bool:
        calibration = runner._calibration_running()
        if (not seen and calibration is not None and calibration.run_index == 1
                and runner.participant.message.text
                == runner.participant.text["screens"]["intro_estimation"]):
            press(runner.rig.participant, "period")
            runner.experimenter.resume_requested.emit()
            seen.append((runner.rig.interruptions.active, _offered(runner)))
        return bool(seen)

    Driver(runner.rig, runner, stop_when=at_the_estimation_intro).run()
    assert seen == [(None, (False, True, False))]
    runner.cancel()
    runner.session.close()


@pytest.mark.parametrize("condition", ["ct_targeted", "participant_preferred"])
def test_after_a_stop_in_the_intervention_the_choice_comes_back_in_every_condition(
    app, loaded, tmp_path, condition
):
    """Code review of N7.F12a1: whatever the resume has to restore, the controls come back
    the same in every condition (SPEC.md 16)."""
    runner = make_runner(loaded, tmp_path, condition=condition)
    rig = runner.rig
    seen = []

    def stop_with_the_touch_on() -> bool:
        if seen:
            if rig.interruptions.active is None and not rig.interruptions.resuming:
                seen.append(_offered(runner))
                return True
            return False
        if runner.session.phase == "intervention" and runner._touch_on:
            press(rig.participant, "period")
            seen.append(_offered(runner))
        return False

    Driver(rig, runner, stop_when=stop_with_the_touch_on).run()
    assert seen == [(True, True, False), (True, True, False)], "stopped, and after the resume"
    resumes = _details(runner, "recalibration")
    assert len(resumes) == 1 and resumes[0].startswith("resume; emergency_stop; ")
    runner.cancel()
    runner.session.close()


def test_a_choice_no_longer_offered_is_ignored_and_logged(app, loaded, tmp_path):
    """Code review of N7.F12a1: the dialog can be accepted after the state has moved on."""
    runner = make_runner(loaded, tmp_path)
    Driver(runner.rig, runner, stop_when=lambda: True).run()  # the setup: no touch
    runner.experimenter.recalibration_requested.emit("restart", "other")
    (ignored,) = [r for r in _events(runner.session) if r["event"] == "recalibration_ignored"]
    assert ignored["detail"] == "restart: no longer offered"
    assert runner.session.recalibrations == 0 and runner.rig.interruptions.active is None
    runner.cancel()
    runner.session.close()


@pytest.mark.parametrize("limit, offered", [(0, (False, False, False)),
                                            (1, (False, False, True))])
def test_the_limit_on_re_calibrations(app, loaded, tmp_path, limit, offered):
    """With a limit of one, the stop after one offers Resume only, and says why; with none,
    nothing is offered, and nothing is said to be used up."""
    runner = make_runner(loaded, tmp_path, recalibrations_max=limit)
    driver = Driver(runner.rig, runner,
                    stop_when=lambda: _logged(runner, "stage_completed", "touch_calibration"))
    seen = []

    def act(trial):
        calibration = runner._calibration_running()
        if calibration is None or not isinstance(trial, TouchRating):
            return
        if limit and not runner.session.recalibrations:
            runner.experimenter.recalibration_requested.emit("restart", "other")
        elif not seen:
            press(runner.rig.participant, "period")
            seen.append(_offered(runner))

    driver.before_step = act
    driver.run()
    assert seen == [offered]
    assert runner.session.recalibrations == limit
    runner.cancel()
    runner.session.close()


class _Result:
    """What `_recalibrated` reads of a calibration's result."""

    preferred_pattern = "sweep_03cms"

    def __init__(self, deliveries):
        self.deliveries = deliveries

    def for_condition(self, condition):
        return self.deliveries[condition]


def test_no_touch_is_started_for_a_wait_that_fell_due_to_stop_it(app, loaded, tmp_path):
    """Code review of N7.F12a1: a re-calibration over the wait for the rekindle or the
    intervention's end, ending after that is due, does not start the touch only for the step
    it repeats to stop it."""
    runner = make_runner(loaded, tmp_path)
    session = runner.session
    session.start_sensitisation()
    delivery = Delivery("sweep_03cms", {c: 0.0 for c in session.garment.channels()})
    runner.deliveries = {c: delivery for c in loaded.study1["design"]["conditions"]}
    runner._touch_on = True
    went_on = []
    runner._detoured = runner
    runner._touch_off_due_s = session.clock.t_session_s() - 1.0
    runner._recalibrated(_Result(runner.deliveries), lambda: went_on.append(True))
    assert went_on and runner._delivery is None, "straight on, no touch started"
    runner._detoured = runner
    runner._touch_off_due_s = None
    runner._recalibrated(_Result(runner.deliveries), lambda: went_on.append(True))
    assert len(went_on) == 1 and runner._delivery is not None, "otherwise the touch first"
    runner._cancel_delivery()
    session.close()


def _recalibrate_in_the_intervention(runner, choice, when, stop=False):
    """Once `when()`, in the intervention, with the touch on: (stop, then) re-calibrate."""
    done = []

    def act() -> None:
        if done or not when():
            return
        done.append(_offered(runner))
        if stop:
            press(runner.rig.participant, "period")
        runner.experimenter.recalibration_requested.emit(choice, "too_strong")
        done.append(runner.session.garment.status())

    return act, done


def test_a_rebalance_from_the_controls_as_the_touch_restarts_then_the_step_goes_on(
    app, loaded, tmp_path
):
    """S, 15 Oct 2026 (docs/LOG.md N7.F12a1): from the controls while the condition's touch
    runs, here as it starts again after the rekindle. The runner's step is abandoned and run
    again after; the touch comes back from the new calibration; and the record says which
    calibration governed when. (A step waiting for its time is repeated the same way after a
    stop, which has its own tests.)"""
    runner = make_runner(loaded, tmp_path)
    session = runner.session

    def touch_restarting() -> bool:
        return (session.phase == "intervention" and runner._touch_on
                and runner._innermost() is runner
                and runner.stages[runner.stage_index].id == "rekindle")

    act, done = _recalibrate_in_the_intervention(runner, "rebalance", touch_restarting)
    stage = []

    def until_the_step_is_done() -> bool:
        act()
        if done and not stage:
            stage.append(runner.stages[runner.stage_index].id)
        return bool(stage) and _logged(runner, "stage_completed", stage[0])

    Driver(runner.rig, runner, stop_when=until_the_step_is_done).run()
    offered, garment = done
    assert offered == (True, True, False), "both, with the touch on"
    assert not garment["channels_on"] and garment["pattern_name"] is None, "the garment to zero"
    (choice,) = _details(runner, "recalibration")
    assert choice == f"rebalance; controls; {stage[0]}; too_strong; 1"
    events = _events(runner.session)
    names = [r["event"] for r in events]
    chosen = names.index("recalibration")
    assert events[chosen]["phase"] == "intervention"
    after = names[chosen:]
    assert after.index("step_abandoned") < after.index("touch_calibration_done")
    assert (after.index("touch_calibration_done") < after.index("garment_activated")
            < after.index("stage_completed")), "the touch back, then the step goes on"
    phases = [r["detail"] for r in events[chosen:] if r["event"] == "phase_changed"]
    assert phases[:2] == ["intervention -> touch_calibration",
                          "touch_calibration -> intervention"]
    channels = _rows(session, "touchcal_channels")
    assert sorted({r["calibration_index"] for r in channels}) == ["1", "2"]
    second = [r for r in channels if r["calibration_index"] == "2"]
    assert second[0]["t_session_s"], "governs from a time in the session"
    assert second[0]["run_index"] == "1", "a rebalance keeps the run"
    match = [r for r in _rows(session, "touchcal_adjust") if r["stage"] == "channel_match"]
    assert {r["pass_index"] for r in match} == {"1", "2"}, "the passes go on"
    assert runner.deliveries[session.condition].pressure_kpa == {
        int(r["channel"]): float(r[f"{session.condition}_kpa"]) for r in second
    }, "the touch from the new calibration"
    assert session.intervention_recalibrations == 1
    # Integrator's decision B: step 6 is not asked again; the preference stands.
    assert len(_rows(session, "touchcal_preference")) == 1 and "preference_kept" in after
    assert {r["participant_preferred_pattern"] for r in channels} == {
        channels[0]["participant_preferred_pattern"]}
    assert names.count("stage_started") == len(set(
        r["detail"] for r in events if r["event"] == "stage_started")), "nothing ran twice"
    runner.cancel()
    session.close()
    values = {r["key"]: r["value"] for r in _rows(session, "session")}
    assert values["intervention_recalibrations"] == "1"


@pytest.mark.parametrize("condition", ["ct_targeted", "participant_preferred"])
def test_a_restart_in_a_touch_block_restarts_the_touch_before_the_rating_repeats(
    app, loaded, tmp_path, condition
):
    """Integrator's decision A: the block's ratings are of the touch being delivered, so
    the touch starts again, with its cue, before the abandoned rating is repeated -- not after
    the block. In the self-start condition, its prompt, as at the intervention's start."""
    runner = make_runner(loaded, tmp_path, condition=condition)
    session = runner.session
    driver = Driver(runner.rig, runner)

    def rating_in_a_touch_block() -> bool:
        return (session.phase == "intervention" and session.block_index is not None
                and isinstance(driver.current(), TouchRating))

    act, done = _recalibrate_in_the_intervention(runner, "restart", rating_in_a_touch_block,
                                                 stop=True)
    block = []

    def until_the_block_ends() -> bool:
        before = bool(done)
        act()
        if done and not before:
            block.append(session.block_index)
        return bool(block) and any(
            r["block_index"] == str(block[0]) for r in _rows(session, "blocks"))

    driver.stop_when = until_the_block_ends
    driver.run()
    (choice,) = _details(runner, "recalibration")
    assert choice.startswith("restart; emergency_stop; block.")
    events = _events(runner.session)
    names = [r["event"] for r in events]
    assert "touch_restart_deferred" not in names
    # The re-calibration's, the last: the stage's own came first.
    done_at = len(names) - 1 - names[::-1].index("touch_calibration_done")
    after = [(r["event"], r["block_index"]) for r in events[done_at:]]
    restarted = next(i for i, (event, _) in enumerate(after)
                     if event == "warning_cue" and events[done_at + i]["detail"]
                     == "_QuietDeliveryStart")
    rated = next(i for i, (event, _) in enumerate(after) if event == "rating_cued")
    assert restarted < rated, "the touch's cue before the repeated rating"
    pending = [r for r in events[done_at:] if r["event"] == "self_start_pending_at_block"]
    if condition == "participant_preferred":
        # The session never waits for the press (N7.D17); the data says the block went on.
        assert pending and pending[0]["severity"] == "warning"
    else:
        assert not pending
        assert names.index("garment_activated", done_at) < done_at + rated, (
            "and the touch on before it"
        )
    ratings = [r for r in _rows(session, "touch_ratings") if r["block_index"] == str(block[0])]
    plan = TouchBlock(runner.rig, 3, block[0]).plan
    assert len(ratings) == len(plan), "the abandoned rating repeated, none lost or doubled"
    fits = [(r["run_index"], r["superseded"]) for r in _rows(session, "touchcal_fit")]
    assert fits == [("1", "false"), ("2", "false")], "the run that governed is not superseded"
    channels = _rows(session, "touchcal_channels")
    assert [r["run_index"] for r in channels if r["calibration_index"] == "2"] == ["2"] * 5
    runner.cancel()
    session.close()


@pytest.mark.parametrize("condition", ["ct_targeted", "participant_preferred"])
def test_next_step_while_the_touch_comes_back_launches_nothing(
    app, loaded, tmp_path, condition
):
    """Spec-review of N7.F12a1: a block armed and waiting for its go when a re-calibration
    took its place. A Next step press while the touch comes back afterwards starts nothing --
    it is logged as ignored -- and the touch-back step cannot be left in force by one, in any
    condition (SPEC.md 16): the block launches on the next press, after it."""
    runner = make_runner(loaded, tmp_path, condition=condition)
    session = runner.session
    state = {}

    def act() -> None:
        innermost = runner._innermost()
        if "chosen" not in state:
            if (session.phase == "intervention" and isinstance(innermost, TouchBlock)
                    and innermost.awaiting_go):
                state["chosen"] = innermost.block_index
                runner.experimenter.recalibration_requested.emit("rebalance", "other")
        elif "pressed" not in state and runner._touch_restarting:
            runner.experimenter.proceed_requested.emit()
            state["pressed"] = len(_events(session))

    driver = Driver(runner.rig, runner, stop_when=lambda: "pressed" in state and _logged(
        runner, "stage_completed", f"block.{state['chosen']}"))
    # Before the driver's own step, which presses Next step for an armed block at once.
    step = driver.step
    driver.step = lambda: (act(), step())
    driver.run()
    assert "pressed" in state
    events = _events(session)
    after = [r["event"] for r in events[state["pressed"] - 1:]]
    assert after[0] == "proceed_ignored", after[:3]
    launch = after.index("block_started")
    assert "garment_activated" in after[:launch] or condition == "participant_preferred"
    assert not runner._touch_restarting and runner._touch_back is None
    ratings = [r for r in _rows(session, "touch_ratings")
               if r["block_index"] == str(state["chosen"])]
    assert len(ratings) == len(TouchBlock(runner.rig, 3, state["chosen"]).plan)
    runner.cancel()
    session.close()


def test_a_crash_after_an_intervention_recalibration_reloads_the_latest(app, loaded, tmp_path):
    crashed = make_runner(loaded, tmp_path)
    session = crashed.session

    def touch_on() -> bool:
        return (session.phase == "intervention" and crashed._touch_on
                and crashed._innermost() is crashed)

    act, done = _recalibrate_in_the_intervention(crashed, "rebalance", touch_on)
    nested = []

    def recalibrated() -> bool:
        act()
        # A restart chosen inside it, in phase touch_calibration, counts for the intervention
        # too (code review of N7.F12a1).
        calibration = crashed._calibration_running()
        if done and not nested and calibration is not None and calibration.step_name == (
                "step3_match"):
            nested.append(True)
            crashed.experimenter.recalibration_requested.emit("restart", "other")
        # And a stop inside it counts as the intervention's (spec-review of N7.F12a1).
        if (nested and len(nested) == 1 and calibration is not None
                and calibration.step_name == "step2_estimation"
                and crashed.rig.interruptions.active is None):
            nested.append(True)
            press(crashed.rig.participant, "period")
        return bool(done) and _logged(crashed, "garment_activated") and len(
            _details(crashed, "touch_calibration_done")) == 2

    Driver(crashed.rig, crashed, stop_when=recalibrated).run()
    crashed.cancel()
    assert len(nested) == 2 and crashed.session.intervention_recalibrations == 2
    assert crashed.session.intervention_emergency_stops == 1
    second = _details(crashed, "recalibration")[1]
    assert second.startswith("restart; controls; ") and second.endswith(
        "/step3_match; other; 2"), second
    runner = _resumed(loaded, tmp_path, crashed)
    assert runner.resume.calibrations_used == 2
    assert runner.resume.intervention_recalibrations == 2
    assert runner.resume.intervention_emergency_stops == 1, "built the same way, by stage"
    assert runner.resume.touchcal_runs == 2
    assert runner.resume.deliveries == crashed.deliveries, "the latest calibration's"
    Driver(runner.rig, runner, stop_when=lambda: runner._touch_on).run()
    assert _offered(runner) == (False, True, False), "a restart first: no calibration here"
    runner.cancel()
    runner.session.close()


def test_the_intervention_stops_are_counted_across_a_crash(app, loaded, tmp_path):
    crashed = make_runner(loaded, tmp_path)
    pressed = []

    def stop_once_then_crash() -> bool:
        if (not pressed and crashed.session.phase == "intervention"
                and crashed.rig.interruptions.active is None):
            pressed.append(True)
            press(crashed.rig.participant, "period")
            return False
        return bool(pressed) and _logged(crashed, "stage_completed", "block.1")

    Driver(crashed.rig, crashed, stop_when=stop_once_then_crash).run()
    crashed.cancel()
    assert crashed.session.intervention_emergency_stops == 1
    runner = _resumed(loaded, tmp_path, crashed)
    assert runner.resume.intervention_emergency_stops == 1
    Driver(runner.rig, runner, stop_when=lambda: True).run()  # starts it, which reloads
    runner.cancel()
    runner.session.close()
    values = {r["key"]: r["value"] for r in _rows(runner.session, "session")}
    assert values["intervention_emergency_stops"] == "1"


def test_once_the_heat_has_ended_the_countdown_moves_on(finished):
    """Code review of N7.F11b10: while the thermode is waited for, the heat's end does not go
    due and overdue in the alarm colours; the countdown is the next block's."""
    config = finished.session.config
    heating = finished.shown_instructions.index(cfg.instruction(config, "rekindle_heating"))
    remove = finished.shown_instructions.index(cfg.instruction(config, "rekindle_remove"))
    assert finished.shown_upcoming[heating] == "rekindle_end"
    assert finished.shown_upcoming[remove] == "block"
    events = [r["event"] for r in _events(finished.session)]
    assert events.index("rekindle_thermode_removed") < events.index("garment_reactivated")


def test_a_chain_that_resumes_from_itself_is_refused(tmp_path):
    path = tmp_path / "TATP1_2026-09-24_10-00-00_P01_S1_session.csv"
    path.write_text(f"key,value\nrng_seed,1\nresumed_from_session_file,{path.name}\n",
                    encoding="utf-8")
    with pytest.raises(resumption.ResumeError, match="already in its chain"):
        resumption.find_open_session(tmp_path, "01", 1)


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


def _intervals(session, block_index: str) -> list[str]:
    return [r["detail"] for r in _events(session)
            if r["event"] == "interval" and r["block_index"] == block_index]


def test_after_a_resume_every_stage_draws_what_it_would_have(app, loaded, tmp_path,
                                                              finished):
    """Each stage has its own stream from the seed and its id: the jittered intervals of a
    block after the crash are those of the uninterrupted session with the same seed."""
    crashed = _crash_after(app, loaded, tmp_path, "block.2")
    runner = _resumed(loaded, tmp_path, crashed)
    # SPEC.md 10.6: every scale was trained before the crash, and is not trained again.
    assert runner.resume.vas_trained == {"intensity", "pain", "pleasantness"}
    Driver(runner.rig, runner, stop_when=lambda: any(
        r["event"] == "stage_completed" and r["detail"] == "block.3"
        for r in _events(runner.session)
    )).run()
    assert _intervals(runner.session, "3") == _intervals(finished.session, "3")
    assert _intervals(runner.session, "3"), "block 3 is a pinprick block, with intervals"
    assert not any(r["event"] == "vas_training_shown" for r in _events(runner.session))
    runner.cancel()
    runner.session.close()


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
    # Ended as a completed session is, on the end screen and a Next step (LOG N7.F17e), not by
    # quitting with nobody shown the data were saved.
    participant = runner.participant
    assert participant.message.text == participant.text["screens"]["session_end"]
    assert runner.experimenter._instruction_text == runner.instruction_text("session_aborted")
    assert runner.rig.closing and runner.rig.proceed_awaited()


def test_a_note_is_logged_and_confirmed_with_its_time(app, loaded, tmp_path):
    """SPEC.md 11's timestamped note, during a stop as well. Before 15 Oct 2026 the field was
    connected to nothing, so every note was lost (docs/LOG.md N7.F10a)."""
    runner = make_runner(loaded, tmp_path)
    try:
        runner.start()
        window = runner.experimenter
        before = window.note.placeholderText()
        window.note.setText("  participant sneezed ")
        window.note_button.click()
        runner.rig.participant.emergency_stop.emit()
        window.note.setText("during the stop")
        window.note.returnPressed.emit()
        notes = [(r["origin"], r["detail"]) for r in _events(runner.session)
                 if r["event"] == "experimenter_note"]
        assert notes == [("experimenter", "participant sneezed"),
                         ("experimenter", "during the stop")]
        assert window.note.text() == ""
        saved = window.text["controls"]["note_saved"].split("{time}")[0]
        assert window.note.placeholderText() != before
        assert window.note.placeholderText().startswith(saved)
    finally:
        runner.session.close()


class _ShownError:
    """The error dialog, answered at once: `exec` would wait for a person."""

    def __init__(self, shown: list, message: str):
        shown.append(message)

    def exec(self) -> int:
        return 0


def test_an_uncaught_error_stops_the_session_and_says_so(app, loaded, tmp_path, monkeypatch):
    """The 15 Oct 2026 demo stood still in the masking check: the sound device raised inside a
    Qt slot, the event loop carried on, and neither screen said anything (N7.F10c)."""
    runner = make_runner(loaded, tmp_path)
    shown: list[str] = []
    monkeypatch.setattr(runner.experimenter, "error_dialog",
                        lambda message: _ShownError(shown, message))
    # The hook stop_on_error passes the traceback on to: silent, since pytest-qt's own would
    # fail the test for the error raised on purpose.
    monkeypatch.setattr(sys, "excepthook", lambda *_: None)
    stop_on_error(lambda: runner, lambda summary: pytest.fail(f"not the session's: {summary}"))
    runner.start()
    try:
        raise AudioError("No output device matching 'Bose QC Headphones'")
    except AudioError:
        sys.excepthook(*sys.exc_info())

    session = runner.session
    assert runner.left_open and not session.closed and not runner.completed
    assert not session.garment.connected
    errors = [r for r in _events(session) if r["event"] == "software_error"]
    assert len(errors) == 1 and "Bose QC Headphones" in errors[0]["detail"]
    assert errors[0]["severity"] == "error"
    assert len(shown) == 1 and "Bose QC Headphones" in shown[0]
    participant = runner.rig.participant
    assert participant.message.text == participant.text["screens"]["paused"]
    # Left open as a crash leaves it, so the next start offers the resume (SPEC.md 15); an
    # abort would have written session_end_iso, and a fresh session would have begun.
    values = resumption.read_session_values(session.files.path("session"))
    assert not values.get("session_end_iso")
    found = resumption.find_open_session(session.files.folder, "01", 1)
    assert found is not None and found.session_file == session.files.path("session")


def _error_during(runner, monkeypatch, shown: list) -> None:
    """Raise an error nothing catches, through the hook a session installs."""
    monkeypatch.setattr(runner.experimenter, "error_dialog",
                        lambda message: _ShownError(shown, message))
    monkeypatch.setattr(sys, "excepthook", lambda *_: None)
    stop_on_error(lambda: runner, lambda summary: pytest.fail(f"not the session's: {summary}"))
    try:
        raise KeyError("ct_targeted")
    except KeyError:
        sys.excepthook(*sys.exc_info())


@pytest.mark.parametrize("phase", ["touch_calibration", "intervention"])
def test_after_setup_the_error_text_is_withheld_from_the_experimenter(
        app, loaded, tmp_path, monkeypatch, phase):
    """An exception's text can name a pattern -- the preference selection's in touch
    calibration -- or a condition (SPEC.md 16): the experimenter is told there was an error,
    and the log has what it was (the reviews of N7.F10c)."""
    runner = make_runner(loaded, tmp_path)
    runner.start()
    runner.session.set_phase(phase)
    shown: list[str] = []
    _error_during(runner, monkeypatch, shown)
    assert shown == [runner.experimenter.text["dialogs"]["software_error_withheld"]]
    errors = [r["detail"] for r in _events(runner.session) if r["event"] == "software_error"]
    assert errors == ["KeyError: 'ct_targeted'"]
    assert runner.left_open


def test_an_error_while_stopping_for_an_error_still_ends_the_session(
        app, loaded, tmp_path, monkeypatch):
    """Ending the program is in a `finally`: a session must never be left standing
    (N7.F10c)."""
    runner = make_runner(loaded, tmp_path)
    runner.start()

    def broken(_message):
        raise RuntimeError("the dialog could not be built")

    monkeypatch.setattr(runner.experimenter, "error_dialog", broken)
    monkeypatch.setattr(sys, "excepthook", lambda *_: None)
    stop_on_error(lambda: runner, lambda summary: pytest.fail(summary))
    with pytest.raises(RuntimeError, match="could not be built"):
        try:
            raise KeyError("first")
        except KeyError:
            sys.excepthook(*sys.exc_info())
    assert runner.left_open and not runner.completed
    assert not runner.session.garment.connected


def test_with_no_session_open_an_uncaught_error_goes_elsewhere(monkeypatch):
    """A Start that failed in the launcher, before any session existed (N7.F10c)."""
    told: list[str] = []
    monkeypatch.setattr(sys, "excepthook", lambda *_: None)
    stop_on_error(lambda: None, told.append)
    try:
        raise IndexError("screens.participant_screen_index is 1, but this machine has 1 screen")
    except IndexError:
        sys.excepthook(*sys.exc_info())
    assert told == ["IndexError: screens.participant_screen_index is 1, but this machine has "
                    "1 screen"]


# -- the fit preview (SPEC.md 11.1) ------------------------------------------------------------


def test_with_the_fit_preview_on_an_f40_is_rerun_once_then_accepted(app, loaded, tmp_path,
                                                                    monkeypatch):
    """Against the real experimenter window: its preview is drawn, then taken down."""
    shown, hidden, instructions = [], [], []
    real_show = ExperimenterWindow.show_fit_preview
    real_hide = ExperimenterWindow.hide_fit_preview

    def spy_show(self, fit):
        shown.append(fit)
        instructions.append(self._instruction_text)
        real_show(self, fit)

    def spy_hide(self):
        hidden.append(1)
        real_hide(self)

    monkeypatch.setattr(ExperimenterWindow, "show_fit_preview", spy_show)
    monkeypatch.setattr(ExperimenterWindow, "hide_fit_preview", spy_hide)
    runner = make_runner(loaded, tmp_path, fit_preview=True)
    driver = Driver(runner.rig, runner, stop_when=lambda: runner.stage_index > [
        s.id for s in runner.stages].index("pre_sensitisation.long"))
    driver.reruns_left = 1
    driver.run()
    rows = _rows(runner.session, "calibration_pinprick")
    assert [(r["run_index"], r["superseded"]) for r in rows] == [("1", "true"), ("2", "false")]
    assert rows[0]["rerun_reason"] == "the driver re-runs once"
    f40_fits = [fit for fit in shown if isinstance(fit, F40Fit)]
    assert len(f40_fits) == 2, "the preview is shown for each run"
    review = cfg.instruction(runner.session.config, "f40_fit_review")
    said = [text for text, fit in zip(instructions, shown, strict=True)
            if isinstance(fit, F40Fit)]
    assert said == [review, review], "the decision due is said, not the last trial's"
    assert len(shown) == 3, "and once for the touch calibration"
    assert len(hidden) >= len(shown), "and taken down after every decision"
    values = runner.session.fit_preview_reruns
    assert values == 1
    runner.cancel()
    runner.session.close()


# -- the prior of a later session (SPEC.md 8.2) ------------------------------------------------


def test_session_two_starts_from_session_ones_pre_s_estimate(app, loaded, tmp_path):
    first = make_runner(loaded, tmp_path)
    row = dict.fromkeys(first.session.files.tables["calibration_pinprick"].column_names)
    row.update(
        timestamp_iso=first.session.clock.wall_iso(), phase="pre_sensitisation",
        region="secondary", run_index=1, superseded=False, start_filament_label_g="26",
        start_source="config_default", applications_total=12, applications_measure=9,
        capped=False, slope_prior_vas_per_log10=51.6, f40_mn=40.0,
        chosen_filament_label_g="4.0", chosen_force_mn=39.2, out_of_range=False,
    )
    first.session.files.write("calibration_pinprick", **row)
    first.session.close()
    second = make_runner(loaded, tmp_path, session_number=2)
    prior = second._prior("pre_sensitisation")
    assert prior == prior_for(second.session.config, "pre_sensitisation", 2, 40.0)
    assert prior.source == "previous_timepoint"
    second.session.close()


def test_without_an_estimate_session_two_starts_from_the_default_and_warns(app, loaded,
                                                                          tmp_path):
    make_runner(loaded, tmp_path).session.close()
    second = make_runner(loaded, tmp_path, session_number=2)
    prior = second._prior("pre_sensitisation")
    assert prior.source == "config_default"
    assert any(r["event"] == "no_previous_session_estimate" and r["severity"] == "warning"
               for r in _events(second.session))
    second.session.close()


# -- the touch start, the same on the experimenter's side in every condition (SPEC.md 16) -----


PRESS_AFTER_S = 20.0


def _experimenter_sequence(app, loaded, tmp_path, condition) -> list[tuple[str, float]]:
    """What the experimenter screen shows, and when, from the touch start until the session
    moves on -- with a participant who presses the self-start after PRESS_AFTER_S."""
    runner = make_runner(loaded, tmp_path / condition, condition=condition,
                         speed=TIMING_CLOCK_SPEED)
    session = runner.session
    session.start_sensitisation()
    session.set_phase("intervention")
    levels = {channel: 30.0 for channel in session.garment.channels()}
    runner.deliveries = {
        name: Delivery("static_sham" if name == "sham" else "sweep_03cms", levels)
        for name in loaded.study1["design"]["conditions"]
    }
    shown: list[tuple[str, float]] = []
    real = runner.experimenter.set_instruction

    def spy(text, *rest):
        # The heading with it (S, 21 Oct 2026): over the instruction, so as seen as it.
        shown.append((f"{rest[0] if rest else None}: {text}", session.clock.t_session_s()))
        real(text, *rest)

    runner.experimenter.set_instruction = spy
    # The masking noise is perceived too (S, 21 Oct 2026: silenced when the garment cannot
    # run): its every change, with its time, is part of what must not differ.
    real_silence, real_unsilence = session.audio.silence_noise, session.audio.unsilence_noise

    def silence(reason):
        shown.append((f"noise silenced: {reason}", session.clock.t_session_s()))
        real_silence(reason)

    def unsilence(reason):
        shown.append((f"noise heard: {reason}", session.clock.t_session_s()))
        real_unsilence(reason)

    session.audio.silence_noise, session.audio.unsilence_noise = silence, unsilence
    session.audio.start_noise(float(loaded.hardware["audio"]["white_noise_start_dbfs"]))
    session.noise.arm()
    moved_on = []
    # The runner as the rig's root, so whether Next step is offered is read as in a session
    # (`Rig.proceed_awaited`); what follows the touch start waits for the go, as a block does.
    runner.rig.root, runner.running = runner, True
    runner._deliver(lambda: runner.await_proceed(
        lambda: None, lambda: moved_on.append(session.clock.t_session_s())))
    window = runner.participant
    deadline = time.monotonic() + RUN_TIMEOUT_S
    pressed = False
    self_start = loaded.participant_text["screens"]["self_start"]
    offered = False
    while not (moved_on and session.clock.t_session_s() > PRESS_AFTER_S + 1):
        assert time.monotonic() < deadline, "the touch start never moved on"
        QApplication.processEvents()
        # Next step as the window offers it: when it changes, and to what (LOG N7.F16d).
        if runner.experimenter.proceed_button.isEnabled() != offered:
            offered = not offered
            shown.append((f"next step offered: {offered}", session.clock.t_session_s()))
        if (not pressed and session.clock.t_session_s() > PRESS_AFTER_S
                and window.message.text == self_start):
            press(window, "f5")
            pressed = True
        time.sleep(0.0005)
    assert (condition == "participant_preferred") == pressed
    assert session.garment.status()["pattern_name"] is not None, "the touch is running"
    runner.running = False  # never started, so nothing of a start's to undo
    runner.cancel()
    session.close()
    return [*shown, ("moved on", moved_on[0])]


def test_a_touch_start_display_shorter_than_the_slowest_delivery_is_refused(
    app, loaded, tmp_path
):
    """A full ramp to the ceiling plus the cue must fit inside the display, or when the session
    moves on depends on the condition's pressure (SPEC.md 16)."""
    garment = loaded.hardware["garment"]
    slowest_s = garment["pressure_ceiling_kpa"] / garment["pressure_rate_max_kpa_s"]
    study1 = {**loaded.study1, "delivery": {"touch_start_display_s": slowest_s / 2}}
    too_short = cfg.Config(**{**loaded.__dict__, "study1": study1})
    with pytest.raises(AssertionError, match="slowest touch start"):
        make_runner(too_short, tmp_path)


def test_the_touch_start_looks_the_same_to_the_experimenter_in_every_condition(
    app, loaded, tmp_path
):
    display_s = loaded.study1["delivery"]["touch_start_display_s"]
    assert display_s < PRESS_AFTER_S, "so the press comes after the session has moved on"
    sequences = [
        _experimenter_sequence(app, loaded, tmp_path, condition)
        for condition in loaded.study1["design"]["conditions"]
    ]
    texts = [[text for text, _ in sequence] for sequence in sequences]
    assert texts[0] == texts[1] == texts[2]
    assert "next step offered: True" in texts[0]
    assert any(text.startswith("noise heard") for text in texts[0]), "the noise masks it"
    for sequence in sequences:
        moved_s = sequence[-1][1] - sequence[0][1]
        assert display_s - EARLY_S <= moved_s < display_s + TIMING_TOLERANCE_S
        # Next step is offered when the session moves on, in every condition: never earlier
        # or later with the delivery's own timing (LOG N7.F16d).
        offered_s = next(t for text, t in sequence if text == "next step offered: True")
        offered_after_s = offered_s - sequence[0][1]
        assert display_s - EARLY_S <= offered_after_s < display_s + TIMING_TOLERANCE_S
    # And the noise changes at the same moments in every condition.
    noise = [[t - sequence[0][1] for text, t in sequence if text.startswith("noise")]
             for sequence in sequences]
    for later in noise[1:]:
        assert all(abs(a - b) < TIMING_TOLERANCE_S for a, b in zip(noise[0], later,
                                                                   strict=True))


# -- around and between the tasks (15 Oct 2026 pilot review, LOG N7.F11c) --------------------


def _confirmed_screens(session) -> list[str]:
    return [r["detail"] for r in _events(session) if r["event"] == "message_confirmed"]


def test_each_new_kind_of_task_is_introduced_and_confirmed(finished):
    """Touch calibration ran seven tasks back to back with nothing saying the task had
    changed (N7.F11c1). Each is now introduced, and the participant's ▶ starts it."""
    intros = [s for s in _confirmed_screens(finished.session) if s.startswith("intro_")]
    assert intros == [
        "intro_bracket", "intro_estimation", "intro_match", "intro_compare", "intro_pleasant",
        "intro_baseline",
    ]


def test_consecutive_ratings_are_separated_by_the_gap(finished):
    """The next scale never replaces the last at once (UI_PRINCIPLES.md 1.10, N7.F11c7).
    Timed in the blocks; the baseline's ratings come before t=0, with no session time, and
    wait the same way."""
    gap_s = float(finished.session.config.study1["touch_block"]["gap_s"])
    confirmed_s = None
    gaps = []
    for row in _events(finished.session):
        if not row["t_session_s"]:
            continue
        if row["event"] == "rating_confirmed":
            confirmed_s = float(row["t_session_s"])
        elif row["event"] == "rating_cued" and confirmed_s is not None:
            gaps.append(float(row["t_session_s"]) - confirmed_s)
            confirmed_s = None
        elif row["event"] in ("stage_completed", "block_ended"):
            confirmed_s = None
    assert gaps, "a block or the baseline rates more than once"
    assert min(gaps) >= gap_s * 0.95


def test_the_intervention_end_waits_for_the_experimenter(finished):
    """The experimenter tells the participant before the measures begin again (N7.F11c10)."""
    events = [(r["event"], r["detail"]) for r in _events(finished.session)]
    ended = events.index(("garment_deactivated", "the intervention has ended"))
    done = events.index(("stage_completed", "intervention.end"))
    assert ("proceed", "SessionRunner") in events[ended:done]


def test_the_session_ends_on_the_experimenters_last_next_step(app, loaded, tmp_path,
                                                              monkeypatch):
    """Both windows vanished the moment the files closed, and nobody saw that the data were
    saved (N7.F11c9). Now the files close, the screens say so, and Next step ends it."""
    runner = make_runner(loaded, tmp_path)
    quits = []

    class Application:
        @staticmethod
        def instance():
            return Application

        @staticmethod
        def quit():
            quits.append(1)

    monkeypatch.setattr(session_runner, "QApplication", Application)
    Driver(runner.rig, runner).run()
    session, participant = runner.session, runner.rig.participant
    assert runner.completed and session.closed and not quits
    assert participant.message.text == participant.text["screens"]["session_end"]
    assert runner.experimenter.instruction.text() == (
        cfg.instruction(session.config, "session_complete")
    )
    window = runner.experimenter
    assert not window.garment_button.isEnabled() and not window.pause_button.isEnabled()
    assert window.garment_button.isHidden() and window.pause_button.isHidden()
    assert window.proceed_button.isEnabled()
    rows = len(_events(session))
    # Nothing is running to stop, and the files take no more rows.
    participant.emergency_stop.emit()
    runner.experimenter.pause_requested.emit()
    assert len(_events(session)) == rows
    assert participant.message.text == participant.text["screens"]["session_end"]
    # At once: the second half of a double press on the Next step before. Ignored.
    runner.experimenter.proceed_requested.emit()
    assert not quits
    lockout_s = loaded.study1["session_end"]["quit_lockout_s"]
    now_s = session.clock.real_elapsed_s()
    monkeypatch.setattr(session.clock, "real_elapsed_s", lambda: now_s + lockout_s)
    runner.experimenter.proceed_requested.emit()
    assert quits == [1]


def test_a_resume_after_the_intervention_has_ended_does_not_start_the_touch(app, loaded,
                                                                             tmp_path):
    """A crash while the experimenter is telling the participant the touch has finished: the
    resume waits for them again, and the garment is not started in between (N7.F11c10)."""
    crashed = _crash_after(app, loaded, tmp_path, "the intervention has ended",
                           event="garment_deactivated")
    runner = _resumed(loaded, tmp_path, crashed)
    assert runner.resume.in_progress == "intervention.end"
    Driver(runner.rig, runner, stop_when=lambda: any(
        r["event"] == "stage_completed" and r["detail"] == "intervention.end"
        for r in _events(runner.session)
    )).run()
    names = [r["event"] for r in _events(runner.session)]
    assert "garment_activated" not in names
    assert "proceed" in names[names.index("garment_deactivated"):]
    runner.cancel()
    runner.session.close()


def _pending_delivery_runner(loaded, tmp_path, condition):
    """A runner in the intervention with every scale trained and a delivery for each
    condition, ready for `_deliver`."""
    runner = make_runner(loaded, tmp_path, condition=condition)
    session = runner.session
    session.start_sensitisation()
    session.set_phase("intervention")
    session.vas_trained.update(session.trained_scales)
    levels = {channel: 30.0 for channel in session.garment.channels()}
    runner.deliveries = {
        name: Delivery("sweep_03cms", levels)
        for name in loaded.study1["design"]["conditions"]
    }
    return runner


@pytest.mark.parametrize("condition", ["participant_preferred", "ct_targeted"])
def test_a_resume_while_a_delivery_is_starting_never_leaves_the_paused_screen_up(
        app, loaded, tmp_path, monkeypatch, condition):
    """A pause while a block waits for its go and the touch is still starting: the resume
    starts the delivery again, ramping, which shows nothing of its own -- so the block's wait
    puts standby up rather than leave the paused screen (N7.F11c8). Every delivery is held
    before its cue, so the ramping state is the one tested, whatever the timers do."""
    monkeypatch.setattr(session_runner._QuietDeliveryStart, "cue_then",
                        lambda _delivery, _then: None)
    runner = _pending_delivery_runner(loaded, tmp_path, condition)
    session, window = runner.session, runner.rig.participant
    interruptions = runner.rig.interruptions
    runner._deliver(lambda: None)
    runner.run_child(lambda: TouchBlock(runner.rig, runner.reference_channel, 1),
                     lambda _: None)
    interruptions.pause()
    paused = loaded.participant_text["screens"]["paused"]
    assert window.message.text == paused
    interruptions.resume()
    deadline = time.monotonic() + RUN_TIMEOUT_S
    while interruptions.active is not None:
        assert time.monotonic() < deadline, "the resume never finished"
        QApplication.processEvents()
        time.sleep(0.0005)
    assert runner._delivery is not None and not runner._delivery.cueing
    assert window.stack.currentWidget() is window.message
    # The rest between the intervention's blocks: the screen brings what comes next there
    # (S, 21 Oct 2026).
    assert window.message.text == loaded.participant_text["screens"]["standby_intervention"]
    runner.cancel()
    session.close()


def test_a_self_start_prompt_stays_up_while_a_block_waits_for_its_go(app, loaded, tmp_path):
    """A block arriving before the self-start press took the prompt down (N7.F11c8): its wait
    for the go now shows what the runner shows between steps, and after the press, standby."""
    runner = _pending_delivery_runner(loaded, tmp_path, "participant_preferred")
    session, window = runner.session, runner.rig.participant
    self_start = loaded.participant_text["screens"]["self_start"]
    runner._deliver(lambda: None)
    deadline = time.monotonic() + RUN_TIMEOUT_S
    while window.message.text != self_start:
        assert time.monotonic() < deadline, "the self-start prompt never came up"
        QApplication.processEvents()
        time.sleep(0.0005)
    runner.run_child(lambda: TouchBlock(runner.rig, runner.reference_channel, 1),
                     lambda _: None)
    assert window.message.text == self_start
    press(window, "f5")
    assert window.message.text == loaded.participant_text["screens"]["standby_intervention"]
    runner.cancel()
    session.close()
