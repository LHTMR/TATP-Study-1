"""The pattern designer's window. SPEC.md 12.2.

The rules are tested in `tests/test_pattern_design.py`; here, that the window applies them:
what it composes, what it refuses to save, and that it plays through the real garment path.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import serial
from PySide6.QtWidgets import QApplication, QLabel

from tatp import config as cfg
from tatp import pattern_design as pd
from tatp.garment import patterns
from tatp.garment.arduino_mosfet import ArduinoMosfetGarment
from tools.design_pattern import DesignerWindow

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
PROTOTYPE = Path(__file__).resolve().parent / "fixtures" / "prototype"
# The smallest experimenter screen the windows are made for: a 1920 x 1080 laptop panel at
# 150 % scaling, less the taskbar and a title bar.
LAPTOP_WIDTH_PX = 1280
LAPTOP_HEIGHT_PX = 640


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
    # A playback timer left running would tick for the rest of the worker's tests.
    assert not made.timer.isActive(), "closing the window stops playback"


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
    window.set_mode("join_hold")
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
    assert window.save_as(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_save_round_trips_and_asks_before_replacing(window, tmp_path, monkeypatch):
    assert window.open_file(EXAMPLES / "sweep_03cms.csv")
    saved = window.save_as(tmp_path)
    assert saved == patterns.load_pattern(tmp_path / "sweep_03cms.csv")
    assert saved.rows == patterns.load_pattern(EXAMPLES / "sweep_03cms.csv").rows

    asked = []
    monkeypatch.setattr(window, "confirm_overwrite", lambda target: asked.append(target))
    window.toggle(0, 4)
    assert window.save_as(tmp_path) is None
    assert asked == [tmp_path / "sweep_03cms.csv"]
    assert patterns.load_pattern(tmp_path / "sweep_03cms.csv").rows == saved.rows

    monkeypatch.setattr(window, "confirm_overwrite", lambda target: True)
    assert window.save_as(tmp_path).rows[0] == (1, 0, 0, 0, 1)


def test_the_optional_fields_are_kept_as_written(window, tmp_path):
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    assert window.extra_fields["overlap_rows"].text() == "1"
    window.save_as(tmp_path)
    assert "overlap_rows: 1\n" in (tmp_path / "sweep_03cms.yaml").read_text(encoding="utf-8")


def test_a_prototype_csv_imports_in_channels_and_exports_back_in_bits(window, tmp_path):
    """S, 24 Sep 2026: the prototype's bits are translated to the sleeve's channels 1-5."""
    bits = window.hardware["garment"]["prototype"]["channel_bits"]
    source = tmp_path / "two_steps.csv"
    # Channel 5's bit on first, then channel 1's: a sweep written in bits.
    source.write_text(f"{bits[0]},0,1\n{bits[4]},1,0\n", encoding="utf-8")
    assert window.import_reference(source, 1000)
    assert window.pattern.channel_ids == (1, 5)
    assert window.pattern.rows == ((0, 1), (1, 0))
    exported = tmp_path / "two_steps.txt"
    assert window.export_to(exported)
    assert exported.read_text(encoding="utf-8") == (
        f"clearcode\naddcode:0x{1 << bits[4]:x}/1000\naddcode:0x{1 << bits[0]:x}/1000"
    )


def test_a_prototype_bit_that_is_not_wired_is_refused(window, loaded):
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    assert not window.import_reference(PROTOTYPE / "motion_stim.csv", 1000)
    assert window.pattern.name == "sweep_03cms", "the design shown is kept"
    prefix = loaded.experimenter_text["designer"]["errors"]["unwired_bit"].split("{")[0]
    assert window.message.text().startswith(prefix)


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


def test_play_refuses_channels_the_garment_does_not_have(window):
    _parameters(window, ids="1, 6")
    window.add_row()
    window.toggle(0, 1)
    assert not window.play()
    assert not window.playing


class FakePort:
    """The prototype's serial port: records writes, answers the handshake."""

    def __init__(self, *args, **kwargs):
        self.lines: list[str] = []

    def reset_input_buffer(self):
        pass

    def write(self, data: bytes):
        self.lines.append(data.decode("ascii").strip())

    def flush(self):
        pass

    def readline(self) -> bytes:
        return b"hello\r\n"

    def close(self):
        self.lines.append("closed")


@pytest.fixture
def sleeve(monkeypatch):
    ports: list[FakePort] = []
    monkeypatch.setattr(ArduinoMosfetGarment, "serial_factory",
                        staticmethod(lambda *a, **k: ports.append(FakePort()) or ports[-1]))
    monkeypatch.setattr("tatp.garment.arduino_mosfet.time.sleep", lambda s: None)
    return ports


def _choose(window, driver):
    window.garment_choice.setCurrentIndex(window.garment_choice.findData(driver))


def test_play_on_the_prototype_sleeve_drives_its_bits(window, app, sleeve):
    """S, 24 Sep 2026: Play reaches the real sleeve, through the session's own driver."""
    window.open_file(EXAMPLES / "sweep_20cms.csv")
    _choose(window, "arduino_mosfet")
    assert sleeve == [], "choosing the sleeve does not open its port"
    assert window.play()
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline and not any(
        line.startswith("setstate") and line != "setstate:0x0" for line in sleeve[0].lines
    ):
        app.processEvents()
    first_bit = window.hardware["garment"]["prototype"]["channel_bits"][0]
    assert f"setstate:0x{1 << first_bit:x}" in sleeve[0].lines, "channel 1 is its wired bit"
    window.stop()
    assert sleeve[0].lines[-1] == "setstate:0x0", "Stop switches every channel off"
    window.close()
    assert sleeve[0].lines[-1] == "closed", "closing lets the port go for the session"


def test_choosing_another_garment_lets_the_sleeve_go(window, sleeve):
    window.open_file(EXAMPLES / "sweep_20cms.csv")
    _choose(window, "arduino_mosfet")
    window.play()
    _choose(window, "mock")
    assert sleeve[0].lines[-1] == "closed"
    assert window.play()


def test_a_sleeve_that_cannot_be_reached_is_reported(window, loaded, monkeypatch):
    def missing(*args, **kwargs):
        raise serial.SerialException("could not open port 'COM3'")

    monkeypatch.setattr(ArduinoMosfetGarment, "serial_factory", staticmethod(missing))
    monkeypatch.setattr("tatp.garment.arduino_mosfet.time.sleep", lambda s: None)
    window.open_file(EXAMPLES / "sweep_20cms.csv")
    _choose(window, "arduino_mosfet")
    assert not window.play()
    assert not window.playing
    assert "COM3" in window.message.text()


def test_every_mode_is_described_on_screen(window, loaded):
    """S, 24 Sep 2026: the mode instructions were not visible."""
    words = loaded.experimenter_text["designer"]
    shown = [widget.text() for widget in window.findChildren(QLabel)]
    for mode in pd.MODES:
        assert words["mode_hints"][mode] in shown
    assert window.mode == pd.MODES[0]


def test_the_designer_fits_the_lab_laptop(window):
    """S, 24 Sep 2026: the window opened with its lower half off the laptop's screen."""
    hint = window.minimumSizeHint()
    assert hint.width() <= LAPTOP_WIDTH_PX and hint.height() <= LAPTOP_HEIGHT_PX, hint


def test_open_starts_where_patterns_are_kept(window):
    assert window.start_folder == cfg.CONFIG_DIR / "patterns"
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    assert window.start_folder == EXAMPLES


def test_editing_the_design_stops_playback(window):
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    window.play()
    window.toggle(0, 1)
    assert not window.playing


# -- review fixes ---------------------------------------------------------------------------


def _copy_example(tmp_path, stem="sweep_03cms", as_stem=None) -> Path:
    as_stem = as_stem or stem
    for suffix in (".csv", ".yaml"):
        source = EXAMPLES / f"{stem}{suffix}"
        (tmp_path / f"{as_stem}{suffix}").write_bytes(source.read_bytes())
    return tmp_path / f"{as_stem}.csv"


def test_the_interval_is_shown_losslessly_and_saved_back_unchanged(window, tmp_path):
    """Review item 1: `:g` showed 1000/12 as 83.3333 and a re-save wrote that back."""
    interval = 1000 / 12
    _parameters(window, name="fine", interval=repr(interval), ids="1")
    window.add_row()
    window.toggle(0, 0)
    window.save_as(tmp_path)
    window.clear()
    window.open_file(tmp_path / "fine.csv")
    assert window.interval_field.text() == repr(interval)
    window.toggle(0, 0)
    window.toggle(0, 0)
    window.confirm_overwrite = lambda target: True
    window.save()
    assert patterns.load_pattern(tmp_path / "fine.csv").row_interval_ms == interval


@pytest.mark.parametrize("typed", ["inf", "nan", "1e999", "9" * 5000])
def test_a_non_finite_interval_is_refused_not_raised(window, typed, loaded):
    _parameters(window, interval=typed)
    window.add_row()
    assert window.pattern is None
    assert not window.save_button.isEnabled()
    words = loaded.experimenter_text["designer"]
    assert window.validity.text() == words["errors"]["not_finite"].format(
        field=words["row_interval_ms"], value=typed
    )


def test_ids_that_do_not_parse_disable_everything_until_they_do(window, loaded):
    """Review item 4: never act on stale ids."""
    _parameters(window, ids="1, 2")
    window.add_row()
    window.toggle(0, 0)
    assert window.save_button.isEnabled()
    window.ids_field.setText("1, x")
    window.apply_channel_ids()
    for control in (window.save_button, window.save_as_button, window.export_button,
                    window.play_button, *window.convert_buttons):
        assert not control.isEnabled()
    assert window.channel_ids == (1, 2)
    errors = loaded.experimenter_text["designer"]["errors"]
    assert window.validity.text() == errors["channel_ids"].format(value="1, x")

    window.set_entries(window.timed, [(1, 0, 100)])
    window.convert_timed()
    assert window.rows == [[1, 0]]
    assert window.message.text() == errors["channel_ids"].format(value="1, x")

    window.ids_field.setText("1, 2")
    window.apply_channel_ids()
    assert window.save_button.isEnabled()
    assert all(control.isEnabled() for control in window.convert_buttons)


def test_ids_typed_but_not_applied_are_not_acted_on(window, loaded):
    _parameters(window, ids="1, 2")
    window.add_row()
    window.ids_field.setText("1, 2, 3")
    assert not window.save_button.isEnabled()
    assert not any(control.isEnabled() for control in window.convert_buttons)
    errors = loaded.experimenter_text["designer"]["errors"]
    assert window.validity.text() == errors["ids_pending"]


def test_an_opened_pattern_is_saved_back_to_its_own_file(window, tmp_path, monkeypatch):
    """Review item 6: a neutral file name survives a re-save (SOP blinding)."""
    path = _copy_example(tmp_path, as_stem="p07")
    assert window.open_file(path)
    window.toggle(0, 4)
    monkeypatch.setattr(window, "confirm_overwrite", lambda target: True)
    window.save()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p07.csv", "p07.yaml"]
    loaded = patterns.load_pattern(path)
    assert (loaded.name, loaded.rows[0]) == ("sweep_03cms", (1, 0, 0, 0, 1))


def test_a_re_save_keeps_the_sidecar_comments(window, tmp_path, monkeypatch):
    """Review item 5."""
    path = _copy_example(tmp_path)
    window.open_file(path)
    window.loop_box.setChecked(False)
    monkeypatch.setattr(window, "confirm_overwrite", lambda target: True)
    window.save()
    original = (EXAMPLES / "sweep_03cms.yaml").read_text(encoding="utf-8")
    assert path.with_suffix(".yaml").read_text(encoding="utf-8") == original.replace(
        "loop: true", "loop: false"
    )


@pytest.mark.parametrize("sidecar", [
    "name: [unclosed\n",
    "- just\n- a list\n",
    "name: p\nrow_interval_ms: fast\nchannel_ids: [1]\nloop: false\n",
    "name: p\nrow_interval_ms: 100\nchannel_ids: 7\nloop: false\n",
])
def test_every_way_a_file_fails_to_open_is_reported_and_the_design_kept(
    window, tmp_path, loaded, sidecar
):
    """Review item 8."""
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    (tmp_path / "bad.csv").write_text("1\n1\n", encoding="utf-8")
    (tmp_path / "bad.yaml").write_text(sidecar, encoding="utf-8")
    assert not window.open_file(tmp_path / "bad.csv")
    assert window.pattern.name == "sweep_03cms"
    prefix = loaded.experimenter_text["designer"]["errors"]["open_failed"].split("{")[0]
    assert window.message.text().startswith(prefix)
    assert "bad.csv" in window.message.text()


def test_a_file_that_is_not_utf8_is_reported(window, tmp_path):
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    (tmp_path / "latin.csv").write_bytes(b"1\n1\n")
    (tmp_path / "latin.yaml").write_bytes("name: smörgås\n".encode("latin-1"))
    assert not window.open_file(tmp_path / "latin.csv")
    assert not window.import_reference(tmp_path / "latin.yaml", 100)
    assert window.pattern.name == "sweep_03cms"


def test_export_builds_its_steps_once(window, tmp_path, monkeypatch):
    """Review item 9."""
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    calls = []
    real = pd.command_steps
    monkeypatch.setattr(pd, "command_steps", lambda *a: calls.append(a) or real(*a))
    assert window.export_to(tmp_path / "out.txt")
    assert len(calls) == 1


def test_save_validates_once(window, tmp_path, monkeypatch):
    window.open_file(EXAMPLES / "sweep_03cms.csv")
    calls = []
    real = pd.validate
    monkeypatch.setattr(pd, "validate", lambda *a: calls.append(a) or real(*a))
    window.save_as(tmp_path)
    assert len(calls) == 1
