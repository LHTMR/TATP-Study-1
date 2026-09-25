"""tools/check_upload.py: every local session file has an identical copy in 01_raw."""

from __future__ import annotations

import pytest

from tatp import config as cfg
from tools import check_upload

SESSION_1 = "TATP1_2026-09-26_10-00-00_P07_S1_session.csv"
LOG_1 = "TATP1_2026-09-26_10-00-00_P07_S1_log.csv"
SESSION_2 = "TATP1_2026-10-03_10-00-00_P07_S2_session.csv"
OTHER = "TATP1_2026-09-27_10-00-00_P08_S1_session.csv"


@pytest.fixture
def folders(tmp_path):
    data, raw = tmp_path / "data", tmp_path / "01_raw"
    data.mkdir()
    raw.mkdir()
    for name in (SESSION_1, LOG_1, SESSION_2, OTHER):
        (data / name).write_text(f"rows of {name}\n")
        (raw / name).write_text(f"rows of {name}\n")
    (data / "TATP1_instance.lock").write_text("")
    return data, raw


def run(data, raw, *extra):
    return check_upload.main(["--data", str(data), "--raw", str(raw), *extra])


def test_every_file_identical_passes_and_the_lock_file_is_not_checked(folders, capsys):
    assert run(*folders) == 0
    assert "4 files checked: 4 identical, 0 missing, 0 different." in capsys.readouterr().out


def test_a_missing_file_fails_and_is_named(folders, capsys):
    data, raw = folders
    (raw / LOG_1).unlink()
    assert run(data, raw) == 1
    out = capsys.readouterr().out
    assert f"MISSING   {LOG_1}" in out
    assert "1 missing" in out


def test_a_copy_of_the_same_size_but_different_content_fails(folders, capsys):
    data, raw = folders
    original = (data / SESSION_1).read_text()
    (raw / SESSION_1).write_text(original.upper())
    assert (raw / SESSION_1).stat().st_size == (data / SESSION_1).stat().st_size
    assert run(data, raw) == 1
    assert f"DIFFERENT {SESSION_1}" in capsys.readouterr().out


def test_a_file_only_in_raw_is_not_a_problem(folders, capsys):
    data, raw = folders
    (raw / "TATP1_2026-09-28_10-00-00_P09_S1_session.csv").write_text("from another PC\n")
    assert run(data, raw) == 0


def test_filters_narrow_to_one_participant_and_session(folders, capsys):
    data, raw = folders
    (raw / OTHER).unlink()
    assert run(data, raw, "--participant", "07", "--session", "1") == 0
    assert "2 files checked" in capsys.readouterr().out


def test_an_unreachable_share_stops_rather_than_reporting_everything_missing(folders):
    data, raw = folders
    with pytest.raises(AssertionError, match="cannot be reached"):
        run(data, raw.parent / "not_mounted")


def test_the_share_is_configured():
    assert cfg.load("en", "en").hardware["data"]["upload_folder"].endswith("01_raw")
