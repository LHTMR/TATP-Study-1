"""The entry point. SPEC.md 4.1, 15, 17.5.

What is tested here is the wiring: the arguments, the terminal warnings, `build` (the instance
lock and the resume decision) and `shut_down`. The session itself is
`tests/test_session_runner.py`'s; the `QApplication.exec()` loop is never entered.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import run_session
from tatp import config as cfg
from tatp import preflight as pre
from tatp.session import SessionError

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"

ARGV = [
    "--participant", "01",
    "--session", "1",
    "--experimenter", "SM",
    "--patterns", str(EXAMPLES),
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def config(loaded, tmp_path):
    hardware = {
        **loaded.hardware,
        "data": {"folder": str(tmp_path / "data"), "cloud_sync_markers": []},
        "audio": {**loaded.hardware["audio"], "backend": "recording"},
    }
    return cfg.Config(**{**loaded.__dict__, "hardware": hardware})


def _rows(session, table):
    with session.files.path(table).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _never(open_session):
    raise AssertionError("no open session was expected")


# -- arguments and warnings ---------------------------------------------------------------


def test_the_pattern_folder_has_no_default():
    """Defaulting it would silently substitute the provisional mockups (open item 5)."""
    with pytest.raises(SystemExit):
        run_session.parse_args([a for a in ARGV if a not in ("--patterns", str(EXAMPLES))])


def test_the_arguments_carry_the_identity_and_the_development_switches():
    args = run_session.parse_args([*ARGV, "--clock-speed", "50", "--seed", "7"])
    assert args.participant == "01"
    assert args.session == 1
    assert args.experimenter == "SM"
    assert args.clock_speed == 50.0
    assert args.seed == 7
    # A real session is Swedish for the participant and English for the experimenter.
    assert args.participant_language == "sv"
    assert args.experimenter_language == "en"
    assert args.resume is None, "no resume offer answered"
    assert run_session.parse_args([*ARGV, "--resume"]).resume is True
    assert run_session.parse_args([*ARGV, "--new"]).resume is False


def test_resume_and_new_are_exclusive():
    with pytest.raises(SystemExit):
        run_session.parse_args([*ARGV, "--resume", "--new"])


def test_preflight_offers_the_resume_of_an_open_session(app, config):
    args = run_session.parse_args(ARGV)
    assert run_session.preflight(config, args) == []
    first = run_session.build(config, args)
    first.start()
    first.cancel()
    first.lock.release()
    findings = run_session.preflight(config, args)
    assert [(severity, key) for severity, key, _ in findings] == [
        ("warn", run_session.RESUME_OFFER)
    ]
    dialogs = config.experimenter_text["dialogs"]
    assert findings[0][2] == {
        "completed": dialogs["resume_nothing_completed"],
        "since_sensitisation": dialogs["resume_not_sensitised"],
    }
    with pytest.raises(SessionError, match="open session"):
        run_session.build(config, args)  # the offer must be answered
    resumed = run_session.build(config, run_session.parse_args([*ARGV, "--resume"]))
    assert resumed.resume is not None
    run_session.shut_down(resumed)


def test_the_resume_summary_names_finished_phases_and_blocks(config):
    from datetime import datetime

    from tatp.clock import ISO_FORMAT
    from tatp.resume import OpenSession

    stages = ("setup.garment", "setup.welcome", "touch_calibration", "pre_sensitisation.long",
              "pre_sensitisation.brush_primary", "sensitisation", "capsaicin.apply",
              "capsaicin.remove", "post_sensitisation.long", "intervention.start", "block.1",
              "block.2")
    now = datetime.now().strftime(ISO_FORMAT)[:-3]
    summary = run_session.resume_summary(
        config, OpenSession(Path("x_session.csv"), now, now, stages)
    )
    phases = config.experimenter_text["phases"]
    assert summary["completed"] == ", ".join([
        phases["setup"], phases["touch_calibration"], phases["pre_sensitisation"],
        phases["sensitisation"], phases["capsaicin"], phases["post_sensitisation"],
        phases["intervention"],
        config.experimenter_text["dialogs"]["resume_blocks"].format(value="1, 2"),
    ])
    assert "0:00" in summary["since_sensitisation"]


def test_temperature_and_humidity_are_recorded_when_given(app, config):
    args = run_session.parse_args(ARGV)
    args.room_temperature_c, args.relative_humidity_pct = 21.5, 28.0
    runner = run_session.build(config, args)
    run_session.shut_down(runner)
    values = {r["key"]: r["value"] for r in _rows(runner.session, "session")}
    assert values["room_temperature_c"] == "21.5"
    assert values["relative_humidity_pct"] == "28.0"


def test_unresolved_open_items_are_printed_before_the_windows_open(loaded):
    """SPEC.md 20: warn, never block. The banner is not visible until a window exists."""
    lines = run_session.warnings_for(loaded)
    assert len(lines) == len(loaded.unresolved) + (1 if loaded.has_placeholder_text() else 0)
    for item in loaded.unresolved:
        assert any(line.startswith(f"[{item.number}]") for line in lines)


# -- build and shut_down ------------------------------------------------------------------


def test_build_returns_an_unstarted_runner_holding_the_lock(app, config):
    runner = run_session.build(config, run_session.parse_args(ARGV), _never)
    assert not runner.running
    data_folder = pre.data_folder_for(config)
    assert pre.refusals(pre.preflight(config, "01", 1, "SM", data_folder)), (
        "a second instance is refused while the first holds the folder"
    )
    with pytest.raises(SessionError, match="another session"):
        run_session.build(config, run_session.parse_args(ARGV), _never)
    run_session.shut_down(runner)
    assert not pre.refusals(pre.preflight(config, "01", 2, "SM", data_folder))


def test_closing_the_window_before_the_end_is_recorded_as_an_abort(app, config):
    runner = run_session.build(config, run_session.parse_args(ARGV), _never)
    runner.start()
    run_session.shut_down(runner)
    assert runner.session.closed and not runner.completed
    values = {r["key"]: r["value"] for r in _rows(runner.session, "session")}
    assert values["abort_reason"] == run_session.WINDOW_CLOSED


def test_an_open_session_is_offered_and_declining_starts_again(app, config):
    first = run_session.build(config, run_session.parse_args(ARGV), _never)
    first.start()
    first.cancel()          # a crash: the session file never gets its end
    first.lock.release()
    asked = []

    def decline(open_session):
        asked.append(open_session.session_file)
        return False

    second = run_session.build(config, run_session.parse_args(ARGV), decline)
    assert asked == [first.session.files.path("session")]
    events = [r["event"] for r in _rows(second.session, "log")]
    assert "open_session_declined" in events
    assert second.resume is None
    run_session.shut_down(second)


def test_accepting_resumes_with_the_recorded_seed(app, config):
    first = run_session.build(config, run_session.parse_args([*ARGV, "--seed", "11"]), _never)
    first.start()
    first.cancel()
    first.lock.release()
    second = run_session.build(config, run_session.parse_args(ARGV), lambda _: True)
    assert second.resume is not None
    assert second.session.rng_seed == 11
    assert second.session.resumed_from == first.session.files.path("session").name
    run_session.shut_down(second)
