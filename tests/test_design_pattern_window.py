"""The pattern designer's window. SPEC.md 12.2.

The rules are tested in `tests/test_pattern_design.py`; here, that the window applies them:
what it composes, what it refuses to save, and that it plays through the real garment path.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.garment import patterns
from tools.design_pattern import DesignerWindow

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
PROTOTYPE = Path(__file__).resolve().parent / "fixtures" / "prototype"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def window(app, loaded):
    made = DesignerWindow(loaded.experimenter_text, loaded.hardware)
    yield made
    made.close()


def _parameters(window, name="drawn", interval="100", ids="1, 2, 3", loop=False):
    window.name_field.setText(name)
    window.interval_field.setText(interval)
    window.ids_field.setText(ids)
    window.apply_channel_ids()
    window.loop_box.setChecked(loop)


def test_a_new_design_assumes_nothing_and_cannot_be_saved(window, loaded):
    assert window.pattern is None
    words = loaded.experimenter_text["designer"]
    assert window.validity.text() == words["errors"]["required"].format(
        field=words["row_interval_ms"]
    )
    assert not window.save_button.isEnabled()
    assert not window.export_button.isEnabled()
    assert not window.play_button.isEnabled()


def test_the_grid_is_drawn_by_clicking(window, tmp_path):
    _parameters(window)
    window.add_row()
    window.add_row()
    window.toggle(0, 0)
    window.toggle(1, 1)
    window.toggle(1, 2)
    assert window.pattern is not None
    assert window.pattern.rows == ((1, 0, 0), (0, 1, 1))
    assert window.save_button.isEnabled()
    window.grid.setCurrentCell(0, 0)
    window.duplicate_row()
    assert window.rows == [[1, 0, 0], [1, 0, 0], [0, 1, 1]]
    window.grid.setCurrentCell(2, 0)
    window.remove_row()
    assert window.rows == [[1, 0, 0], [1, 0, 0]]


def test_changing_the_channels_keeps_the_columns_kept(window):
    _parameters(window)
    window.add_row()
    window.toggle(0, 2)
    window.ids_field.setText("3, 7")
    window.apply_channel_ids()
    assert window.channel_ids == (3, 7)
    assert window.rows == [[1, 0]]


def test_ordered_channels_convert_to_the_grid(window, loaded):
    _parameters(window, interval="75", ids="1, 2, 3, 4, 5")
    window.set_entries(window.ordered, [(cid, 150) for cid in (1, 2, 3, 4, 5)])
    window.delay_field.setText("75")
    window.mode.setCurrentIndex(window.mode.findData("join_hold"))
    window.convert_ordered()
    sweep = patterns.load_pattern(EXAMPLES / "sweep_20cms.csv")
    assert window.pattern.rows == sweep.rows
    assert window.message.text() == loaded.experimenter_text["designer"]["converted"].format(
        value=len(sweep.rows)
    )


def test_timed_channels_convert_to_the_grid(window):
    _parameters(window, ids="3, 4, 11")
    window.set_entries(window.timed, [(3, 0, 500), (4, 400, 900), (11, 800, 1300)])
    window.convert_timed()
    assert len(window.pattern.rows) == 13


def test_an_off_grid_timing_is_refused_and_the_grid_kept(window, loaded):
    _parameters(window, ids="3, 4, 11")
    window.add_row()
    window.toggle(0, 0)
    window.set_entries(window.timed, [(3, 0, 250)])
    window.convert_timed()
    assert window.rows == [[1, 0, 0]]
    errors = loaded.experimenter_text["designer"]["errors"]
    assert window.message.text() == errors["off_grid"].format(value="250", interval="100")


def test_a_design_that_would_not_load_cannot_be_saved(window, tmp_path):
    _parameters(window, name="two words")
    window.add_row()
    assert window.pattern is None
    assert not window.save_button.isEnabled()
    assert window.save_to(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_save_round_trips_and_asks_before_replacing(window, tmp_path, monkeypatch):
    assert window.open_file(EXAMPLES / "sweep_03cms.csv")
    saved = window.save_to(tmp_path)
    assert saved == patterns.load_pattern(tmp_path / "sweep_03cms.csv")
    assert saved.rows == patterns.load_pattern(EXAMPLES / "sweep_03cms.csv").rows

    asked = []
    monkeypatch.setattr(window, "confirm_overwrite", lambda target: asked.append(target))
    window.toggle(0, 4)
    assert window.save_to(tmp_path) is None
    assert asked == [tmp_path / "sweep_03cms.csv"]
    assert patterns.load_pattern(tmp_path / "sweep_03cms.csv").rows == saved.rows

    monkeypatch.setattr(window, "confirm_overwrite", lambda target: True)
    assert window.save_to(tmp_path).rows[0] == (1, 0, 0, 0, 1)


def test_the_optional_fields_are_kept_as_written(window, tmp_path):
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    assert window.extra_fields["overlap_rows"].text() == "1"
    window.save_to(tmp_path)
    assert "overlap_rows: 1\n" in (tmp_path / "sweep_03cms.yaml").read_text(encoding="utf-8")


def test_a_prototype_csv_imports_and_exports_as_the_prototype_would(window, tmp_path):
    assert window.import_reference(PROTOTYPE / "motion_stim.csv", 1000)
    assert window.pattern.channel_ids == (3, 28)
    exported = tmp_path / "motion_stim.txt"
    assert window.export_to(exported)
    expected = (PROTOTYPE / "motion_stim_1000ms.txt").read_text(encoding="utf-8")
    assert exported.read_text(encoding="utf-8") == expected


def test_an_unreadable_file_is_reported_not_raised(window, tmp_path):
    (tmp_path / "bad.csv").write_text("1\n2\n", encoding="utf-8")
    assert not window.open_file(tmp_path / "bad.csv")
    assert not window.import_reference(tmp_path / "bad.csv", 100)
    assert window.message.text()


def test_the_timeline_shows_two_cycles_of_a_looped_pattern(window):
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    assert window.timeline.cycles == 2
    assert window.timeline.span_s == pytest.approx(6.0)
    window.loop_box.setChecked(False)
    assert window.timeline.cycles == 1


def test_play_runs_through_the_real_garment_path(window, app):
    window.open_file(EXAMPLES / "sweep_20cms.csv")
    assert window.play()
    commands = window.garment.commands
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline and not any(
        c["event"] == "channel_on" for c in commands
    ):
        app.processEvents()
    assert any(c["event"] == "channel_on" for c in commands)
    assert window.timeline.cursor_s is not None
    window.stop()
    assert not window.playing
    assert window.garment.status()["channels_on"] == []
    assert window.timeline.cursor_s is None


def test_play_refuses_channels_the_mock_does_not_have(window):
    window.import_reference(PROTOTYPE / "motion_stim.csv", 1000)
    assert not window.play()
    assert not window.playing


def test_editing_the_design_stops_playback(window):
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    window.play()
    window.toggle(0, 1)
    assert not window.playing
