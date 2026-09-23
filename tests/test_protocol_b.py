"""Protocol B in full, driven through the real windows. SPEC.md 9, 11.1, 12.3, 12.4, 16.

A virtual participant (`tests/virtual_participant.py`) presses what a cooperative participant
would and rates on a known observer model, so each test knows what the calibration must find.
"""

from __future__ import annotations

import csv

import pytest
from PySide6.QtWidgets import QApplication
from virtual_participant import (
    P40_KPA,
    SLOPE_VAS_PER_LOG10,
    Virtual,
    make_config,
    make_rig,
    press,
)

from tatp import config as cfg
from tatp import touchcal
from tatp.touchcal_maths import REFERENCE_STRONGER, TEST_STRONGER


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def rig(app, loaded, tmp_path):
    made = make_rig(make_config(loaded, tmp_path))
    yield made
    made.session.close()


def _rows(session, table):
    path = session.files.path(table)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _events(session, name):
    return [row for row in _rows(session, "log") if row["event"] == name]


def _calibrate(rig, **setup):
    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)
    for name, value in setup.items():
        setattr(virtual, name, value)
    return virtual.run(), virtual


def _true(pct):
    return P40_KPA * 10 ** ((pct - 40) / SLOPE_VAS_PER_LOG10)


# -- the whole protocol -----------------------------------------------------------------


def test_a_full_calibration_writes_every_table_and_finds_the_observer(rig):
    session = rig.session
    result, _ = _calibrate(rig, gains={1: 1.3, 2: 1.1, 4: 0.9, 5: 1.2})

    assert isinstance(result, touchcal.TouchCalibrationResult)
    assert result.stage1_pass and result.valid_for_analysis
    for pct, value in ((20.0, result.p20_kpa), (30.0, result.p30_kpa), (80.0, result.p80_kpa)):
        assert value == pytest.approx(_true(pct), rel=0.02)
    assert result.match_level_kpa == pytest.approx(_true(50.0), rel=0.02)
    assert result.gains[3] == 1.0
    assert result.gains[1] == pytest.approx(1.3) and result.gains[4] == pytest.approx(0.9)
    assert result.p30_kpa <= result.pleasant_kpa <= result.p80_kpa

    adjust = _rows(session, "touchcal_adjust")
    stages = [row["stage"] for row in adjust]
    assert stages.count("anchor") == 2
    assert stages.count("channel_match") == 8, "four channels, two start points each"
    assert stages.count("pleasantness") == 2
    pleasant = [row for row in adjust if row["stage"] == "pleasantness"]
    assert {row["start_direction"] for row in pleasant} == {"below", "above"}
    assert float(pleasant[0]["range_min_kpa"]) == pytest.approx(result.p30_kpa)
    assert float(pleasant[0]["range_max_kpa"]) == pytest.approx(result.p80_kpa)

    estimate = _rows(session, "touchcal_estimate")
    assert len(estimate) == 12, "ten amplitudes plus two catch trials"
    assert sum(row["catch_trial"] == "true" for row in estimate) == 2
    assert [int(row["presentation_order"]) for row in estimate] == list(range(1, 13))
    assert not _rows(session, "touch_ratings"), "estimation ratings are not touch_ratings"

    (fit,) = _rows(session, "touchcal_fit")
    assert fit["stage1_pass"] == "true" and fit["superseded"] == "false"
    assert float(fit["slope"]) == pytest.approx(SLOPE_VAS_PER_LOG10, rel=1e-3)
    assert fit["catch_flag"] == "false"
    assert fit["extrapolated"] == ""

    compare = _rows(session, "touchcal_compare")
    assert len(compare) == 8, "always the first, so no pair favours a channel twice"
    assert {row["order"] for row in compare} == {"test_first", "reference_first"}
    assert all(row["readjusted"] == "false" for row in compare)

    (even,) = _rows(session, "touchcal_evenness")
    assert even["judgement"] == "even"
    (preference,) = _rows(session, "touchcal_preference")
    assert preference["chosen_pattern"] == result.preferred_pattern
    assert preference["moves"] == "2"
    assert preference["all_felt"] == "true"


def test_what_each_condition_delivers(rig):
    result, _ = _calibrate(rig, gains={1: 1.3, 2: 1.1, 4: 0.9, 5: 1.2})
    patterns = rig.session.config.study1["patterns"]["condition_pattern"]
    assert result.sham.pattern_name == patterns["sham"]
    assert result.sham.pressure_kpa[3] == pytest.approx(result.p20_kpa)
    assert result.sham.pressure_kpa[1] == pytest.approx(result.p20_kpa * 1.3)
    assert result.ct_targeted.pattern_name == patterns["ct_targeted"]
    assert result.participant_preferred.pattern_name == result.preferred_pattern
    # docs/research/R31: the two moving conditions at the same level, so the pattern is the
    # only difference between them.
    assert result.ct_targeted.pressure_kpa == result.participant_preferred.pressure_kpa
    assert result.ct_targeted.pressure_kpa[3] == pytest.approx(result.pleasant_kpa)
    assert result.for_condition("sham") is result.sham


def test_calibration_never_reads_or_shows_the_condition(rig, monkeypatch):
    """SPEC.md 16: nothing in calibration differs between conditions, or reaches a screen."""
    session = rig.session
    read = []
    original = type(session).condition
    monkeypatch.setattr(
        type(session), "condition",
        property(lambda self: read.append(True) or original.fget(self)),
    )
    shown = []
    rig.experimenter.set_instruction = lambda text: shown.append(text)
    rig.experimenter.set_status = lambda text: shown.append(text)
    _calibrate(rig)
    assert read == []
    for condition in session.config.study1["design"]["conditions"]:
        assert not any(condition in text for text in shown)
    for pattern in session.patterns:
        assert not any(pattern in text for text in shown)


# -- the stage-1 gate and the fit preview -----------------------------------------------


def _flat(rig):
    """Rate everything the same, which no rating function fits."""

    def flat(trial):
        if isinstance(trial, touchcal.TouchRating):
            window = rig.participant
            press(window.vas, "pagedown")
            window.vas.state.percent = 50.0
            press(window.vas, "period")

    return flat


def test_a_failing_fit_is_put_to_the_experimenter_and_a_rerun_keeps_the_first(rig):
    session = rig.session
    decisions = []

    def decide(trial):
        decisions.append(trial.instruction)
        if len(decisions) == 1:
            return "rerun", ("flat ratings",)
        return "accept", ()

    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)
    virtual.decide = decide
    ratings_seen = []

    def before(trial):
        # Flat on the first run only.
        if isinstance(trial, touchcal.TouchRating) and procedure.run_index == 1:
            ratings_seen.append(trial)
            _flat(rig)(trial)

    virtual.before_step = before
    result = virtual.run()

    assert decisions[0] == "touchcal_stage1_unusable", "a flat fit cannot be inverted"
    fits = _rows(session, "touchcal_fit")
    assert [row["run_index"] for row in fits] == ["1", "2"]
    assert fits[0]["superseded"] == "true" and fits[0]["rerun_reason"] == "flat ratings"
    assert fits[0]["stage1_pass"] == "false"
    assert "flat" in fits[0]["stage1_failures"]
    assert fits[0]["p20_kpa"] == "", "no inversion, so no target"
    assert fits[1]["superseded"] == "false"
    assert result.run_index == 2
    runs = {row["run_index"] for row in _rows(session, "touchcal_estimate")}
    assert runs == {"1", "2"}, "the discarded run's trials stay in the data"
    # The preview is off, so this is a stage-1 re-run: its own event, not a preview re-run.
    assert session.fit_preview_reruns == 0
    assert _events(session, "touchcal_stage1_rerun")


def test_an_estimate_that_cannot_be_inverted_cannot_be_accepted(rig):
    session = rig.session
    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)
    tries = []

    def decide(trial):
        tries.append(trial.instruction)
        return ("accept", ()) if len(tries) == 1 else ("rerun", ("second try",))

    virtual.decide = decide
    virtual.before_step = lambda trial: (
        _flat(rig)(trial) if procedure.run_index == 1 else None
    )
    virtual.run()
    assert _events(session, "accept_refused")
    assert tries[:2] == ["touchcal_stage1_unusable", "touchcal_stage1_unusable"]


def test_the_fit_preview_puts_even_a_good_fit_to_the_experimenter(app, loaded, tmp_path):
    preview = {**loaded.study1["fit_preview"], "enabled": True}
    rig = make_rig(make_config(loaded, tmp_path, fit_preview=preview))
    try:
        decisions = []
        procedure = touchcal.TouchCalibration(rig)
        virtual = Virtual(rig, procedure)
        virtual.decide = lambda trial: decisions.append(trial.instruction) or (
            ("rerun", ("look again",)) if len(decisions) == 1 else ("accept", ())
        )
        virtual.run()
        assert decisions[0] == "touchcal_fit_review"
        assert rig.session.fit_preview_reruns == 1, "a re-run chosen from the preview counts"
    finally:
        rig.session.close()


def test_felt_catch_trials_are_flagged(rig):
    session = rig.session
    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)

    def felt(trial):
        if isinstance(trial, touchcal.TouchRating) and not session.garment.status()[
            "channels_on"
        ]:
            press(rig.participant.vas, "pagedown")
            rig.participant.vas.state.percent = 30.0
            press(rig.participant.vas, "period")

    virtual.before_step = felt
    virtual.run()
    (fit,) = _rows(session, "touchcal_fit")
    assert fit["catch_flag"] == "true"
    assert float(fit["catch_felt_fraction"]) == 1.0
    assert _events(session, "catch_trials_felt")


# -- equalisation -----------------------------------------------------------------------


def test_a_channel_winning_every_comparison_is_readjusted_then_accepted(rig):
    """docs/research/R33: an order-free winner in both pairs prompts one re-adjustment."""
    session = rig.session

    def choose(key, trial):
        if key != touchcal.COMPARISON_CHOICE:
            return "left"
        # Channel 1 always feels stronger until it has been re-adjusted.
        test_side = "left" if trial.plan.order == touchcal.TEST_FIRST else "right"
        other = "right" if test_side == "left" else "left"
        if trial.plan.channel == 1 and trial.plan.pass_index == 1:
            return test_side
        return other if trial.plan.order == touchcal.TEST_FIRST else test_side

    _calibrate(rig, choose=choose)
    rows = [row for row in _rows(session, "touchcal_compare") if row["channel"] == "1"]
    assert [(row["pass_index"], row["pair_index"]) for row in rows] == [
        ("1", "1"), ("1", "1"), ("1", "2"), ("1", "2"), ("2", "1"), ("2", "1"),
    ]
    assert all(row["judgement"] == TEST_STRONGER for row in rows[:4])
    assert [row["readjusted"] for row in rows[:4]] == ["false", "false", "false", "true"]
    matches = [
        row for row in _rows(session, "touchcal_adjust")
        if row["stage"] == "channel_match" and row["channel"] == "1"
    ]
    assert len(matches) == 4, "both start points again on re-adjustment"
    assert _events(session, "equalisation_mismatch")


def test_a_mismatch_that_survives_readjustment_is_logged_and_the_session_goes_on(rig):
    session = rig.session

    def choose(key, trial):
        if key != touchcal.COMPARISON_CHOICE:
            return "left"
        # The reference always feels stronger on channel 2.
        ref_side = "right" if trial.plan.order == touchcal.TEST_FIRST else "left"
        if trial.plan.channel == 2:
            return ref_side
        return "left"

    result, _ = _calibrate(rig, choose=choose)
    rows = [row for row in _rows(session, "touchcal_compare") if row["channel"] == "2"]
    assert len(rows) == 8, "two passes of two pairs"
    assert all(row["judgement"] == REFERENCE_STRONGER for row in rows)
    assert rows[-1]["readjusted"] == "false", "no passes left, so nothing follows"
    assert "still" in _events(session, "equalisation_mismatch")[-1]["detail"]
    assert result is not None


# -- the evenness check and rebalancing -------------------------------------------------


def test_uneven_offers_a_rebalance_which_reruns_steps_3_and_4(rig):
    session = rig.session
    answers = iter(["right", "left"])  # uneven, then even
    decisions = []

    def choose(key, trial):
        return next(answers) if key == touchcal.EVENNESS_CHOICE else "left"

    def decide(trial):
        decisions.append(trial.instruction)
        return "rebalance", ()

    _calibrate(rig, choose=choose, decide=decide)
    checks = _rows(session, "touchcal_evenness")
    assert [row["judgement"] for row in checks] == ["uneven", "even"]
    assert checks[0]["rebalance_offered"] == "true"
    assert decisions == ["touchcal_uneven"]
    stages = [row["stage"] for row in _rows(session, "touchcal_adjust")]
    assert stages.count("channel_match") == 16
    assert stages.count("pleasantness") == 2, "the reference-scale level stands"


# -- interruptions ----------------------------------------------------------------------


def test_an_emergency_stop_mid_estimation_repeats_the_presentation_and_loses_nothing(rig):
    session = rig.session
    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)
    stopped = []

    def stop_once(trial):
        if (
            not stopped
            and isinstance(trial, touchcal.TouchRating)
            and len(_rows(session, "touchcal_estimate")) == 3
        ):
            stopped.append(True)
            press(rig.participant.vas, "f5")

    virtual.before_step = stop_once
    result = virtual.run()
    assert stopped
    assert result.stage1_pass
    estimate = _rows(session, "touchcal_estimate")
    assert len(estimate) == 12, "the interrupted presentation is repeated, not duplicated"
    assert _events(session, "emergency_stop")
    assert _events(session, "resumed")
    assert _events(session, "step_repeated")


def test_a_pause_during_a_comparison_repeats_it(rig):
    session = rig.session
    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)
    paused = []

    def pause_once(trial):
        if not paused and isinstance(trial, touchcal.Comparison):
            paused.append(True)
            rig.experimenter.pause_requested.emit()

    virtual.before_step = pause_once
    virtual.run()
    assert len(_rows(session, "touchcal_compare")) == 8


# -- timing-only mode, SPEC.md 12.4 -----------------------------------------------------


def test_timing_only_mode_runs_every_step_and_marks_nothing_valid(rig, monkeypatch):
    session = rig.session
    monkeypatch.setattr(type(session.garment), "per_channel_pressure", False)
    decisions = []
    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)
    virtual.decide = lambda trial: decisions.append(trial) or ("accept", ())
    # Ratings that no fit survives: the gate must not stop a timing-only session.
    virtual.before_step = _flat(rig)
    result = virtual.run()
    assert decisions == []
    assert not result.valid_for_analysis
    assert result.sham.pressure_kpa is None
    assert result.targets_source != touchcal.FROM_FIT
    assert _events(session, "touchcal_fallback")
    for table in ("touchcal_adjust", "touchcal_estimate", "touchcal_fit",
                  "touchcal_compare", "touchcal_evenness", "touchcal_preference",
                  "touchcal_channels"):
        rows = _rows(session, table)
        assert rows and all(row["valid_for_analysis"] == "false" for row in rows), table


# -- the fallbacks, and the terminal path ------------------------------------------------


def test_unusable_and_out_of_reruns_can_only_continue_on_a_recorded_fallback(app, loaded,
                                                                            tmp_path):
    """No deadlock: with the re-runs used up, Accept continues on a fallback marked invalid."""
    preview = {**loaded.study1["fit_preview"], "max_reruns": 0}
    rig = make_rig(make_config(loaded, tmp_path, fit_preview=preview))
    try:
        session = rig.session
        instructions = []
        procedure = touchcal.TouchCalibration(rig)
        virtual = Virtual(rig, procedure)
        virtual.decide = lambda trial: instructions.append(trial.instruction) or ("accept", ())
        virtual.before_step = _flat(rig)
        result = virtual.run()
        assert instructions[0] == "touchcal_stage1_exhausted"
        assert not result.valid_for_analysis
        assert result.targets_source == touchcal.FROM_BRACKET_LINE
        assert result.p30_kpa < result.p80_kpa
        (fit,) = _rows(session, "touchcal_fit")
        assert fit["superseded"] == "false" and fit["stage1_pass"] == "false"
        channels = _rows(session, "touchcal_channels")
        assert {row["targets_source"] for row in channels} == {"bracket_line"}
        assert all(row["valid_for_analysis"] == "false" for row in channels)
        assert _events(session, "touchcal_fallback")
    finally:
        rig.session.close()


def test_a_rerun_refused_at_the_limit_on_an_unusable_estimate_asks_again_truthfully(
    app, loaded, tmp_path
):
    preview = {**loaded.study1["fit_preview"], "max_reruns": 0}
    rig = make_rig(make_config(loaded, tmp_path, fit_preview=preview))
    try:
        answers = iter([("rerun", ("again",)), ("accept", ())])
        instructions = []
        procedure = touchcal.TouchCalibration(rig)
        virtual = Virtual(rig, procedure)
        virtual.decide = lambda trial: instructions.append(trial.instruction) or next(answers)
        virtual.before_step = _flat(rig)
        virtual.run()
        assert instructions == ["touchcal_stage1_exhausted"] * 2
        assert _events(rig.session, "rerun_refused")
    finally:
        rig.session.close()


def test_an_unusable_bracket_rerun_still_keeps_a_fit_row(rig):
    """SPEC.md 11.1: every run keeps its fit row, even one with nothing to fit."""
    session = rig.session
    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)
    decisions = []
    virtual.decide = lambda trial: (
        decisions.append(trial.instruction)
        or (("rerun", ("zero bracket",)) if len(decisions) == 1 else ("accept", ()))
    )
    real_setting = virtual._setting

    def setting(trial):
        # "Just noticeable" at 0 kPa on the first run: nothing can be sampled on a log axis.
        if trial.plan.stage == touchcal.ANCHOR_STAGE and procedure.run_index == 1:
            return 0.0
        return real_setting(trial)

    virtual._setting = setting
    virtual.run()
    fits = _rows(session, "touchcal_fit")
    assert [row["run_index"] for row in fits] == ["1", "2"]
    assert fits[0]["superseded"] == "true" and fits[0]["rerun_reason"] == "zero bracket"
    assert fits[0]["stage1_failures"] == "bracket_unusable"
    assert fits[0]["slope"] == "" and fits[0]["p20_kpa"] == ""
    assert [r for r in _events(session, "experimenter_action") if "zero bracket" in r["detail"]]
    assert _events(session, "touchcal_stage1_rerun"), "a stage-1 re-run with the preview off"
    assert session.fit_preview_reruns == 0, "only preview re-runs count there"


def test_a_zero_match_is_matched_again_then_put_to_the_experimenter(rig):
    """Never a silent gain of 1 (CLAUDE.md): repeated, then an explicit, recorded fallback."""
    session = rig.session
    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)
    decisions = []

    def decide(trial):
        decisions.append(trial.instruction)
        return "proceed", ()

    virtual.decide = decide
    virtual.gains = {2: 0.0}
    result = virtual.run()
    assert "touchcal_gain_undefined" in decisions
    assert result.gain_sources[2] == touchcal.GAIN_FALLBACK
    assert result.gain_sources[1] == touchcal.GAIN_MATCHED
    assert not result.valid_for_analysis
    matches = [
        row for row in _rows(session, "touchcal_adjust")
        if row["stage"] == "channel_match" and row["channel"] == "2"
    ]
    retries = session.config.study1["touch_calibration"]["channel_match_zero_retries"]
    assert {row["pass_index"] for row in matches} >= {str(i + 1) for i in range(retries + 1)}
    (row,) = [r for r in _rows(session, "touchcal_channels") if r["channel"] == "2"]
    assert row["gain_source"] == "fallback_unit_gain" and row["valid_for_analysis"] == "false"
    assert _events(session, "gain_fallback")


def test_every_adjustment_carries_its_run_and_pass(rig):
    _calibrate(rig)
    rows = _rows(rig.session, "touchcal_adjust")
    assert {row["run_index"] for row in rows} == {"1"}
    assert {row["pass_index"] for row in rows} == {"1"}


def test_the_channels_table_holds_what_every_condition_delivers(rig):
    result, _ = _calibrate(rig, gains={1: 1.3, 2: 1.1, 4: 0.9, 5: 1.2})
    rows = {int(row["channel"]): row for row in _rows(rig.session, "touchcal_channels")}
    assert sorted(rows) == [1, 2, 3, 4, 5]
    for channel, row in rows.items():
        assert float(row["gain"]) == pytest.approx(result.gains[channel])
        assert float(row["sham_kpa"]) == pytest.approx(result.sham.pressure_kpa[channel])
        assert float(row["ct_targeted_kpa"]) == pytest.approx(
            result.ct_targeted.pressure_kpa[channel]
        )
        assert row["participant_preferred_pattern"] == result.preferred_pattern
    assert rows[3]["gain_source"] == "reference" and rows[1]["gain_source"] == "matched"


def test_the_fit_preview_receives_the_points_and_the_verdict(app, loaded, tmp_path):
    preview = {**loaded.study1["fit_preview"], "enabled": True}
    rig = make_rig(make_config(loaded, tmp_path, fit_preview=preview))
    try:
        procedure = touchcal.TouchCalibration(rig)
        ready = []
        procedure.fit_ready.connect(ready.append)
        Virtual(rig, procedure).run()
        (shown,) = ready
        assert len(shown.points) == 12
        assert shown.stage1_pass and shown.fit is not None
        assert shown.p20_kpa == pytest.approx(_true(20.0), rel=0.02)
    finally:
        rig.session.close()


def test_without_the_preview_no_ratings_leave_the_procedure(rig):
    procedure = touchcal.TouchCalibration(rig)
    ready = []
    procedure.fit_ready.connect(ready.append)
    Virtual(rig, procedure).run()
    assert ready == []


def test_every_presentation_has_the_same_onset_to_scale_timing(rig):
    """A ramp after onset would bring the scale up later for louder amplitudes (item 8)."""
    session = rig.session
    procedure = touchcal.TouchCalibration(rig)
    virtual = Virtual(rig, procedure)
    onsets = []

    def watch(trial):
        if isinstance(trial, touchcal.EstimationPresentation) and trial.onset_iso and (
            trial.plan.presentation_order not in [o for o, _ in onsets]
        ):
            onsets.append((trial.plan.presentation_order, session.garment.pressure_kpa[3]))

    virtual.before_step = watch
    virtual.run()
    # At onset every non-catch presentation already holds its pressure: nothing ramps after.
    plans = {int(r["presentation_order"]): float(r["pressure_kpa"])
             for r in _rows(session, "touchcal_estimate")}
    assert onsets, "the settle interval was observed at least once"
    for order, held in onsets:
        assert held == pytest.approx(plans[order])


# -- starting a touch delivery, SPEC.md 12.3 and 16 -------------------------------------


def _start_delivery(rig, delivery, self_start):
    trial = touchcal.DeliveryStart(
        rig.session, rig.participant, rig.experimenter, delivery, self_start
    )
    done, seen = [], []
    trial.finished.connect(done.append)
    # Patched on the instance each call, from the class's own methods, so one call's record
    # never collects another's.
    window = rig.experimenter
    window.set_status = lambda text: seen.append(("status", text))
    window.set_instruction = lambda text: (
        seen.append(("instruction", text)),
        type(window).set_instruction(window, text),
    )
    cues = []
    rig.participant.warning_cue_shown.connect(lambda: cues.append(True))
    trial.start()
    spins = 200000
    while not done and spins:
        QApplication.processEvents()
        window = rig.participant
        if trial._connections and window.stack.currentWidget() is window.message:
            press(rig.participant, "period")
        spins -= 1
    return done, seen, cues


def test_the_experimenter_sees_the_same_at_every_touch_start(rig):
    """SPEC.md 16: only one condition self-starts, so the lab screen must not differ."""
    result, _ = _calibrate(rig)
    seen_by_condition = {}
    for condition in rig.session.config.study1["design"]["conditions"]:
        rig.session.garment.stop()
        _, seen, cues = _start_delivery(
            rig, result.for_condition(condition), condition == "participant_preferred"
        )
        seen_by_condition[condition] = seen
        assert cues, "every delivery starts with the warning cue (SPEC.md 10.5)"
    views = list(seen_by_condition.values())
    assert all(view == views[0] for view in views)
    text = rig.session.config.experimenter_text["instructions"]
    assert views[0] == [("instruction", text["touch_start"])]
    assert "self_start" not in text


def test_the_self_start_press_starts_the_pattern_and_records_its_latency(rig):
    session = rig.session
    result, _ = _calibrate(rig)
    delivery = result.participant_preferred
    done, _, cues = _start_delivery(rig, delivery, self_start=True)

    assert cues, "the cue came before the prompt, so it adds nothing after the press"
    assert len(done) == 1 and done[0] >= 0
    assert session.garment.status()["pattern_name"] == delivery.pattern_name
    rows = _rows(session, "garment")
    start = max(i for i, row in enumerate(rows) if row["event"] == "pattern_start")
    assert float(rows[start]["self_start_latency_ms"]) == pytest.approx(done[0])
    assert rows[start]["pattern_name"] == delivery.pattern_name
    assert rows[start - 1]["event"] == "channel_on", "measured to the first device command"
    for channel, kpa in delivery.pressure_kpa.items():
        assert session.garment.pressure_kpa[channel] == pytest.approx(kpa)


def test_a_touch_not_self_started_starts_after_the_cue_with_no_latency(rig):
    result, _ = _calibrate(rig)
    done, _, cues = _start_delivery(rig, result.sham, self_start=False)
    assert done == [None] and cues
    assert rig.session.garment.status()["pattern_name"] == result.sham.pattern_name
