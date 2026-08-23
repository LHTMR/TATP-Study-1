"""Session state, provenance and blinding. SPEC.md 7.4, 14, 16.

These run a real session against the mock garment and read the files it produced, so what is
checked is the data on disk rather than the intention in the code.
"""

from __future__ import annotations

import csv
import re

import pytest

from tatp import config as cfg
from tatp.clock import Clock
from tatp.datafiles import SCHEMA_PATH, parse_schema
from tatp.session import PHASES, Session, SessionError

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def session(loaded, tmp_path, monkeypatch):
    """A real session writing into a temporary folder, so no test touches data/."""
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"]}}
    hardware["data"]["folder"] = str(tmp_path / "data")
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    made = Session(
        config,
        participant_code="01",
        session_number=1,
        experimenter_initials="SM",
        pattern_folder=EXAMPLES,
        clock=Clock(speed=60.0),
        rng_seed=7,
    )
    yield made
    made.close()


def _table(session, name):
    with session.files.path(name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _session_values(session):
    return {row["key"]: row["value"] for row in _table(session, "session")}


def _session_with(loaded, tmp_path, schedule, participant_code):
    """A session on a crafted schedule, so a test never depends on today's `schedule.yaml`."""
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "d"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware, "schedule": schedule})
    return Session(config, participant_code, 1, "SM", EXAMPLES)


# -- blinding --------------------------------------------------------------------------


def test_the_condition_is_recorded(session):
    session.start()
    assert session.condition in session.config.study1["design"]["conditions"]
    assert _session_values(session)["condition"] == session.condition


def test_the_condition_is_not_in_what_the_experimenter_may_see(session):
    """CLAUDE.md: the condition is hidden from the experimenter screen as well."""
    view = session.experimenter_view()
    assert session.condition not in [str(value) for value in view.values()]
    assert not any("condition" in key for key in view)
    assert not any(
        session.condition in str(value) for value in view.values()
    ), "no field may leak the condition, even inside a longer string"


def test_the_experimenter_view_carries_the_warnings_it_must_show(session):
    view = session.experimenter_view()
    # Whether the wording is currently approved is not this test's business -- that it is
    # reported at all is. tests/test_ui.py drives the banner from both values.
    assert view["placeholder_text"] is session.config.has_placeholder_text()
    assert view["unresolved_open_items"], "open items must be visible at the screen"
    assert view["limb"] in session.config.study1["design"]["limbs"]


# -- provenance ------------------------------------------------------------------------


def test_every_session_key_is_written_exactly_once(session):
    session.start()
    session.close()
    _, keys = parse_schema()
    rows = [row["key"] for row in _table(session, "session")]
    assert rows == list(keys), "every key, in the order DATA_SCHEMA.md lists them"


def test_provenance_is_populated_from_the_real_environment(session):
    session.start()
    values = _session_values(session)
    assert values["participant_code"] == "01"
    assert values["session_number"] == "1"
    assert values["rng_seed"] == "7"
    assert values["experimenter_initials"] == "SM"
    assert values["garment_driver"] == "MockGarment"
    assert values["reduced_capability_device"] == "false"
    assert re.fullmatch(r"[0-9a-f]{64}", values["config_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", values["allocation_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", values["pattern_sha256"])
    assert values["pattern_names"] == "static_sham;sweep_01cms;sweep_03cms;sweep_20cms"
    assert values["filaments_measured"] == "false", "the set has not been weighed (FOR_S A3.1)"
    assert values["filament_calibration_date"] == ""


def test_an_rng_seed_is_drawn_and_recorded_when_none_is_given(loaded, tmp_path):
    data = {"folder": str(tmp_path / "d"), "cloud_sync_markers": []}
    config = cfg.Config(**{**loaded.__dict__, "hardware": {**loaded.hardware, "data": data}})
    made = Session(config, "02", 1, "SM", EXAMPLES)
    made.start()
    made.close()
    assert made.rng_seed > 0
    assert _session_values(made)["rng_seed"] == str(made.rng_seed)


def test_the_closing_keys_are_written_at_close(session):
    session.start()
    session.start_sensitisation()
    session.close(abort_reason="test abort")
    values = _session_values(session)
    assert values["abort_reason"] == "test abort"
    assert values["session_end_iso"]
    assert values["sensitisation_start_iso"] == session.clock.sensitisation_start_iso


def test_closing_twice_is_safe(session):
    session.start()
    session.close()
    session.close()
    assert _session_values(session)["session_end_iso"]


# -- the log ---------------------------------------------------------------------------


def test_startup_warnings_reach_the_log(session):
    session.start()
    events = {row["event"] for row in _table(session, "log")}
    assert "session_started" in events
    assert "unresolved_open_item" in events


def test_unapproved_participant_wording_is_logged_at_startup(loaded, tmp_path):
    """SPEC.md 20. Driven by a crafted config, so it stays tested as wording gets approved."""
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "d"),
                                            "cloud_sync_markers": []}}
    text = {**loaded.participant_text, "screens": {"standby": f"{cfg.PLACEHOLDER_PREFIX} - no"}}
    config = cfg.Config(
        **{**loaded.__dict__, "hardware": hardware, "participant_text": text}
    )
    made = Session(config, "03", 1, "SM", EXAMPLES)
    made.start()
    made.close()
    with made.files.path("log").open(encoding="utf-8", newline="") as handle:
        events = {row["event"] for row in csv.DictReader(handle)}
    assert "placeholder_participant_text" in events


def test_phase_changes_are_logged_and_validated(session):
    session.start()
    session.set_phase("pre_sensitisation")
    assert session.phase == "pre_sensitisation"
    last = _table(session, "log")[-1]
    assert last["event"] == "phase_changed"
    assert last["detail"] == "setup -> pre_sensitisation"
    with pytest.raises(SessionError, match="is not one of"):
        session.set_phase("elevenses")


def test_t_session_is_empty_until_sensitisation_begins(session):
    """SPEC.md 7.4: t=0 is the start of heat sensitisation, not the start of the process."""
    session.start()
    assert _table(session, "log")[0]["t_session_s"] == ""
    session.start_sensitisation()
    assert float(_table(session, "log")[-1]["t_session_s"]) >= 0.0


def test_an_unknown_origin_or_severity_is_refused(session):
    session.start()
    with pytest.raises(SessionError, match="origin"):
        session.log("e", origin="the_cat")
    with pytest.raises(SessionError, match="severity"):
        session.log("e", severity="catastrophic")


# -- blocks, SPEC.md 7.4 ------------------------------------------------------------------


def test_a_block_stamps_every_row_written_while_it_is_open(session):
    session.start()
    session.start_sensitisation()
    block = session.schedule.blocks[0]
    session.start_block(block)
    assert session.block_index == block.index
    session.log("something_happened")
    session.end_block()
    session.log("after_the_block")

    rows = {row["event"]: row for row in _table(session, "log")}
    assert rows["something_happened"]["block_index"] == str(block.index)
    assert rows["after_the_block"]["block_index"] == "", "empty outside a block"


def test_a_block_records_its_plan_and_what_actually_happened(session):
    """The gap between plan and reality is data, not something to correct away."""
    session.start()
    session.start_sensitisation()
    block = session.schedule.blocks[0]
    session.start_block(block)
    session.end_block()

    rows = {row["event"]: row for row in _table(session, "log")}
    assert f"planned {block.planned_offset_min:g} min" in rows["block_started"]["detail"]
    assert "against plan" in rows["block_started"]["detail"]
    assert "took" in rows["block_ended"]["detail"]
    # Driven by the block rather than by what schedule.yaml holds today, so this survives the
    # durations changing from estimates to measurements (PROGRESS.md decision 21).
    duration = block.expected_duration_min
    shown = "unset" if duration is None else f"{duration:g} min"
    assert f"expected {shown}" in rows["block_ended"]["detail"]


def test_a_block_with_no_expected_duration_says_unset_rather_than_a_number(loaded, tmp_path):
    """The other branch of the line above, which the live config no longer reaches."""
    generate = {**loaded.schedule["generate"],
                "expected_duration_min": {"pinprick": None, "touch": None}}
    made = _session_with(loaded, tmp_path, {**loaded.schedule, "generate": generate}, "05")
    made.start()
    made.start_sensitisation()
    made.start_block(made.schedule.blocks[0])
    made.end_block()
    made.close()

    with made.files.path("log").open(encoding="utf-8", newline="") as handle:
        rows = {row["event"]: row for row in csv.DictReader(handle)}
    assert "expected unset" in rows["block_ended"]["detail"]


def test_a_block_cannot_start_before_session_t_zero(session):
    """A block offset is measured from sensitisation; before t=0 there is nothing to record."""
    session.start()
    with pytest.raises(SessionError, match="before session t=0"):
        session.start_block(session.schedule.blocks[0])


def test_two_blocks_cannot_be_open_at_once(session):
    session.start()
    session.start_sensitisation()
    session.start_block(session.schedule.blocks[0])
    with pytest.raises(SessionError, match="still open"):
        session.start_block(session.schedule.blocks[1])


def test_ending_a_block_that_was_never_started_is_refused(session):
    session.start()
    with pytest.raises(SessionError, match="no block is open"):
        session.end_block()


def test_closing_the_session_ends_an_open_block(session):
    """SPEC.md 7.4 wants an actual end for every block, including an aborted one."""
    session.start()
    session.start_sensitisation()
    session.start_block(session.schedule.blocks[0])
    session.close("emergency stop")

    events = [row["event"] for row in _table(session, "log")]
    assert events.index("block_ended") < events.index("session_aborted")


def test_schedule_warnings_are_logged_at_startup(loaded, tmp_path):
    """SPEC.md 7.3: they never block, so the session file has to carry them.

    Driven by a crafted grid with a known fault rather than by whatever the live `schedule.yaml`
    happens to warn about today. Asserting against the live count would quietly become `0 == 0`
    the day open item 4 is resolved, and stop testing anything (PROGRESS.md decision 21).
    """
    on_the_rekindle = loaded.schedule["generate"]["rekindle_offset_min"]
    schedule = {**loaded.schedule, "overrides": [{"index": 1, "offset_min": on_the_rekindle}]}
    made = _session_with(loaded, tmp_path, schedule, "04")
    made.start()
    made.close()

    with made.files.path("log").open(encoding="utf-8", newline="") as handle:
        logged = [r for r in csv.DictReader(handle) if r["event"] == "schedule_warning"]
    assert any("rekindle" in row["detail"] for row in logged)
    assert all(row["severity"] == "warning" for row in logged)
    assert len(logged) == len(made.schedule.warnings())


# -- the garment ------------------------------------------------------------------------


def test_garment_commands_are_written_with_the_session_context(session):
    session.start()
    session.set_phase("intervention")
    session.block_index = 4
    session.garment.set_pressure(2, 30.0)
    rows = _table(session, "garment")
    assert rows[0]["event"] == "connect"
    assert rows[0]["driver"] == "MockGarment"
    assert rows[-1]["event"] == "set_pressure"
    assert rows[-1]["phase"] == "intervention"
    assert rows[-1]["block_index"] == "4"
    assert rows[-1]["pressure_kpa"] == "30.0"
    assert rows[-1]["clamped"] == "false"


def test_a_pattern_run_through_the_session_is_recorded(session):
    session.start()
    session.set_phase("intervention")
    session.garment.play_pattern(session.patterns["static_sham"])
    session.garment.advance()
    session.garment.stop_pattern()
    events = [row["event"] for row in _table(session, "garment")]
    assert events.count("channel_on") == 5
    assert events.count("channel_off") == 5
    assert "pattern_start" in events and "pattern_stop" in events


def test_close_stops_the_garment(session):
    session.start()
    session.garment.set_pressure(1, 40.0)
    session.close()
    assert not session.garment.connected
    assert all(value == 0.0 for value in session.garment.pressure_kpa.values())
    events = [row["event"] for row in _table(session, "garment")]
    assert events[-2:] == ["stop", "disconnect"]


# -- the schema the session writes against ----------------------------------------------


def test_the_phase_vocabulary_still_matches_the_schema_document():
    """PHASES is a copy of the Conventions list in DATA_SCHEMA.md, so it can drift."""
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    bullet = re.search(r"\*\*`phase`\*\*(.+?)\n- ", text, re.DOTALL)
    assert bullet, "the phase convention bullet has moved or changed shape"
    assert tuple(re.findall(r"`(\w+)`", bullet.group(1))) == PHASES


def test_an_unknown_driver_is_refused_rather_than_defaulted(loaded, tmp_path):
    hardware = {**loaded.hardware, "garment": {**loaded.hardware["garment"]}}
    hardware["garment"]["driver"] = "arduino_valves"
    hardware["data"] = {"folder": str(tmp_path / "d"), "cloud_sync_markers": []}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    with pytest.raises(SessionError, match="Available drivers"):
        Session(config, "01", 1, "SM", EXAMPLES)
