"""The virtual participant and experimenter. SPEC.md 17.5.

Each responder is driven against the real windows and the real trial classes, with the noise
switched off where the test needs an exact answer, so what is tested is that it reads the screen
and presses keys correctly -- not the observer model, which is `docs/calibration_sim.py`'s.
"""

from __future__ import annotations

import csv
import math
import time

import pytest
from PySide6.QtWidgets import QApplication

from sim.experimenters import VirtualExperimenter, template_pattern
from sim.responders import (
    CalibrationSimError,
    ConfirmsWithoutMarker,
    HoldsAdjustmentAtMaximum,
    ObserverModel,
    StopsMidBlock,
    VirtualParticipant,
    load_calibration_sim,
)
from tatp import config as cfg
from tatp import touchcal
from tatp.clock import Clock
from tatp.pinprick import PAIN_SCALE
from tatp.procedure import Rig
from tatp.responder import Responder
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
# Low enough that the adjustment's scaled time-out (SPEC.md 9) outlasts a hold across the whole
# range, which runs on real seconds.
CLOCK_SPEED = 10.0
SPIN_TIMEOUT_S = 15.0
SEED = 3


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
    session = Session(
        config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=CLOCK_SPEED), rng_seed=SEED
    )
    session.start()
    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    made = Rig(session, participant, experimenter)
    yield made
    session.close()


def _noiseless() -> ObserverModel:
    return ObserverModel(SEED, pain_noise_sd=0.0, touch_noise_sd=0.0, adjust_criterion_sd=0.0)


def _virtual(rig, cls=VirtualParticipant, model=None) -> VirtualParticipant:
    made = cls(rig.participant, rig.session.garment, rig.session.config, SEED, model=model)
    made.start()
    # Held by the rig for the test's length: a QObject nothing holds is collected at once, and
    # its timer with it (docs/LOG.md N6.30).
    rig.held_by_test = made
    return made


def _spin(condition) -> None:
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the virtual participant did not reach the expected state")
        QApplication.processEvents()
        time.sleep(0.001)


def _log_events(session) -> list[str]:
    with session.files.path("log").open(encoding="utf-8", newline="") as handle:
        return [row["event"] for row in csv.DictReader(handle)]


# -- the observer model -------------------------------------------------------------------


def test_the_model_is_calibration_sims_and_loading_it_runs_no_simulation(capsys):
    namespace = load_calibration_sim()
    assert "rate" in namespace and "S_FIXED" in namespace
    # The script prints a table for every scenario; loading the definitions prints nothing.
    assert capsys.readouterr().out == ""


def test_the_pinprick_slope_is_the_one_the_study_configures(loaded):
    """SPEC.md 8.2: 51.6 VAS points per log10 unit came from this model."""
    slope = ObserverModel(SEED).pain_slope_per_log10
    assert math.isclose(
        slope, loaded.study1["pinprick"]["slope_prior_vas_per_log10"], abs_tol=0.05
    )


def test_a_noiseless_observer_rates_its_own_f40_at_40():
    model = _noiseless()
    assert model.pain_pct(model.pain_f40_mn) == pytest.approx(40.0)
    assert model.touch_pct(model.touch_p40_kpa) == pytest.approx(40.0)
    assert model.touch_pct(0.0) == 0.0, "nothing delivered is nothing felt"


def test_steering_does_not_disturb_the_reported_ratings():
    """Steering reads once per tick, and the tick count varies between identical runs."""
    steered, unsteered = ObserverModel(SEED), ObserverModel(SEED)
    for _ in range(7):
        steered.touch_felt_pct(30.0)
    assert [steered.pain_pct(200.0) for _ in range(5)] == [
        unsteered.pain_pct(200.0) for _ in range(5)
    ]


def test_the_loader_refuses_a_statement_that_could_run_the_simulation(tmp_path):
    script = tmp_path / "sim.py"
    script.write_text(
        "import numpy as np\nK = np.sqrt(2)\ndef run():\n    return 1\nprint(K)\nrun()\n"
        "results = run()\n",
        encoding="utf-8",
    )
    with pytest.raises(CalibrationSimError, match="line 7"):
        load_calibration_sim(script)


def test_the_loader_keeps_definitions_and_constants_and_drops_the_calls(tmp_path, capsys):
    script = tmp_path / "sim.py"
    script.write_text(
        "import numpy as np\nK = np.sqrt(4)\ndef run():\n    print('ran')\nrun()\n",
        encoding="utf-8",
    )
    namespace = load_calibration_sim(script)
    assert namespace["K"] == 2.0 and callable(namespace["run"])
    assert capsys.readouterr().out == ""


# -- answering the screens ----------------------------------------------------------------


def test_the_vas_is_answered_through_its_keys(rig):
    model = _noiseless()
    virtual = _virtual(rig, model=model)
    responses = []
    rig.participant.confirmed.connect(responses.append)
    virtual.feel_filament(model.pain_f40_mn)
    rig.participant.show_vas(PAIN_SCALE)
    _spin(lambda: responses)
    assert responses[0].rating_percent == pytest.approx(40.0)
    assert virtual.ratings == [(PAIN_SCALE, pytest.approx(40.0))]


def test_rating_pain_with_no_filament_applied_is_an_error(rig):
    virtual = VirtualParticipant(rig.participant, rig.session.garment, rig.session.config, SEED)
    with pytest.raises(RuntimeError, match="no filament"):
        virtual.rating_for(PAIN_SCALE)


def test_an_application_is_rated_once_and_not_reused(rig):
    """The guard must be able to fire on a second rating with no new application."""
    virtual = VirtualParticipant(rig.participant, rig.session.garment, rig.session.config, SEED)
    virtual.feel_filament(255.0)
    virtual.rating_for(PAIN_SCALE)
    with pytest.raises(RuntimeError, match="no filament"):
        virtual.rating_for(PAIN_SCALE)


def test_the_adjustment_stops_where_the_anchor_is_felt(rig):
    """The first anchor from below, by holding the right button and letting go at 10 %."""
    model = _noiseless()
    _virtual(rig, model=model)
    plan = touchcal.anchor_plans(rig.session.config)[0]
    trial = touchcal.Adjustment(rig.session, rig.participant, rig.experimenter, plan)
    produced = []
    trial.finished.connect(produced.append)
    trial.start()
    _spin(lambda: produced)
    # log10 P = log10 P40 + (anchor - 40) / slope, the observer's own 10 % point.
    exponent = (plan.anchor_percent - 40.0) / model.touch_slope_per_log10
    expected = model.touch_p40_kpa * 10**exponent
    assert produced[0] == pytest.approx(expected, abs=3.0)


def test_the_choice_goes_to_the_stronger_stimulus(rig):
    _virtual(rig, model=_noiseless())
    garment = rig.session.garment
    chosen = []
    rig.participant.chosen.connect(chosen.append)
    rig.participant.show_choice("comparison")
    # One channel each, so neither command is the second to its channel and rate limited.
    for side, channel, kpa in (("left", 1, 20.0), ("right", 2, 60.0)):
        garment.set_pressure(channel, kpa)
        rig.participant.emphasise_choice(side)
        deadline = time.monotonic() + 0.05
        _spin(lambda deadline=deadline: time.monotonic() > deadline)
    rig.participant.emphasise_choice(None)
    rig.participant.accept_choice()
    _spin(lambda: chosen)
    assert chosen == ["right"]


# -- adversaries --------------------------------------------------------------------------


def test_confirming_without_a_marker_is_logged_and_records_nothing(rig):
    model = _noiseless()
    virtual = _virtual(rig, ConfirmsWithoutMarker, model=model)
    responses = []
    rig.participant.confirmed.connect(responses.append)
    virtual.feel_filament(model.pain_f40_mn)
    rig.participant.show_vas(PAIN_SCALE)
    _spin(lambda: responses)
    assert len(responses) == 1, "the empty confirms produced no response"
    assert virtual.empty_confirms == ConfirmsWithoutMarker.EMPTY_CONFIRMS
    assert _log_events(rig.session).count("confirm_without_marker") == virtual.empty_confirms


def test_the_stop_is_pressed_at_the_first_cue_only(rig):
    virtual = _virtual(rig, StopsMidBlock)
    stops = []
    rig.participant.emergency_stop.connect(lambda: stops.append(1))
    rig.participant.show_warning_cue()
    _spin(lambda: stops)
    rig.participant.show_blank()
    rig.participant.show_warning_cue()
    deadline = time.monotonic() + 0.1
    _spin(lambda: time.monotonic() > deadline)
    assert stops == [1]
    assert virtual.stats()["stops"] == 1


def test_holding_at_maximum_ends_at_the_ceiling(rig):
    virtual = _virtual(rig, HoldsAdjustmentAtMaximum)
    plan = touchcal.anchor_plans(rig.session.config)[0]
    trial = touchcal.Adjustment(rig.session, rig.participant, rig.experimenter, plan)
    produced = []
    trial.finished.connect(produced.append)
    trial.start()
    _spin(lambda: produced)
    assert produced[0] == rig.session.garment.limits.pressure_ceiling_kpa
    holds = virtual.stats()["ceiling_holds_s"]
    assert len(holds) == 1 and holds[0] >= HoldsAdjustmentAtMaximum.OVERHOLD_S


def test_each_adjustment_is_held_at_the_ceiling_afresh(rig):
    """A second adjustment must not inherit the first one's time at the ceiling."""
    virtual = _virtual(rig, HoldsAdjustmentAtMaximum)
    virtual.held_at_ceiling_s = HoldsAdjustmentAtMaximum.OVERHOLD_S
    virtual._ceiling_since_s = 0.0
    rig.participant.show_adjustment(touchcal.anchor_plans(rig.session.config)[0].target_key)
    _spin(lambda: virtual._token is not None and virtual._token[0] is rig.participant.control)
    assert virtual.held_at_ceiling_s == 0.0
    assert virtual._ceiling_since_s is None


# -- the experimenter -----------------------------------------------------------------------


def test_the_instruction_template_parses_back_into_its_fields(loaded):
    template = loaded.experimenter_text["instructions"]["apply_filament"]
    text = template.format(filament="0.40", force_mn=3.9, site=2, region="primary")
    match = template_pattern(template).fullmatch(text)
    assert match["filament"] == "0.40"
    assert match["site"] == "2"


def test_the_experimenter_applies_the_named_filament_at_every_cue(rig):
    """Once per cue, so the same filament asked for twice is applied twice."""
    virtual = VirtualParticipant(rig.participant, rig.session.garment, rig.session.config, SEED)
    experimenter = VirtualExperimenter(rig, virtual)
    experimenter.start()
    text = rig.experimenter.text
    rig.experimenter.set_instruction(
        text["instructions"]["apply_filament"].format(
            filament="26", force_mn=255.0, site=1, region=text["terms"]["regions"]["primary"]
        )
    )
    for applications in (1, 2):
        rig.participant.show_warning_cue()
        _spin(lambda applications=applications: len(experimenter.applied) == applications)
        assert virtual.stimulus_mn == 255.0
        virtual.rating_for(PAIN_SCALE)
        rig.participant.show_blank()
        _spin(lambda: not experimenter._on_cue)
    assert experimenter.applied == ["26", "26"]


def test_nothing_is_applied_without_a_cue(rig):
    virtual = VirtualParticipant(rig.participant, rig.session.garment, rig.session.config, SEED)
    experimenter = VirtualExperimenter(rig, virtual)
    experimenter.start()
    text = rig.experimenter.text
    rig.experimenter.set_instruction(
        text["instructions"]["apply_filament"].format(
            filament="26", force_mn=255.0, site=1, region=text["terms"]["regions"]["primary"]
        )
    )
    deadline = time.monotonic() + 0.1
    _spin(lambda: time.monotonic() > deadline)
    assert experimenter.applied == [] and virtual.stimulus_mn is None


def test_the_experimenter_resumes_after_an_interruption(rig):
    virtual = _virtual(rig)
    experimenter = VirtualExperimenter(rig, virtual, resume_after_s=1.0)
    resumed = []
    rig.interruptions.resumed.connect(lambda: resumed.append(1))
    rig.interruptions.emergency_stop()
    _spin(lambda: resumed)
    assert experimenter.resumes == 1
    assert _log_events(rig.session).count("resumed") == 1
