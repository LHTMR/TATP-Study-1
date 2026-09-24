"""Instruments and environment. SPEC.md 8.1.

Every write goes to a copy of the configuration in a temporary folder; the committed
`config/filaments.yaml` is never touched by the suite.
"""

from __future__ import annotations

import shutil

import pytest
import yaml
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp import instruments
from tatp.instruments import InstrumentsDialog, InstrumentsError, write_filament_forces

WEIGHED = {"0.008": 0.081, "26": 251.3}
DATE = "2026-09-24"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def config_dir(tmp_path):
    copied = tmp_path / "config"
    shutil.copytree(cfg.CONFIG_DIR, copied)
    return copied


@pytest.fixture
def filaments(config_dir):
    return config_dir / "filaments.yaml"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_measured_forces_and_the_date_are_written(filaments):
    write_filament_forces(WEIGHED, DATE, "Mettler XS205", filaments)
    written = _load(filaments)
    by_label = {row["label_g"]: row for row in written["filaments"]}
    assert by_label["26"]["force_measured_mn"] == pytest.approx(251.3)
    assert by_label["0.008"]["force_measured_mn"] == pytest.approx(0.081)
    assert by_label["60"]["force_measured_mn"] is None, "a label not given keeps what it had"
    assert written["weighing_date"] == DATE
    assert written["weighing_balance"] == "Mettler XS205"


def test_everything_else_in_the_file_is_kept_exactly(filaments):
    """The file is mostly the chart's transcription record, in comments; none of it may go."""
    before = filaments.read_text(encoding="utf-8").splitlines()
    write_filament_forces(WEIGHED, DATE, None, filaments)
    after = filaments.read_text(encoding="utf-8").splitlines()
    assert len(before) == len(after)
    changed = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert len(changed) == len(WEIGHED) + 1, "the forces and the date, nothing else"
    assert all(line.startswith("#") for line in after if line.startswith("#"))
    assert [b for b in before if b.startswith("#")] == [a for a in after if a.startswith("#")]


def test_weighing_the_whole_set_resolves_open_item_1(config_dir, filaments):
    every = {row["label_g"]: row["force_nominal_mn"] for row in _load(filaments)["filaments"]}

    def resolved():
        items = cfg.load("sv", "sv", config_dir).open_items
        return {item.number: item.resolved for item in items}

    assert resolved()["1"] is False
    write_filament_forces(every, DATE, None, filaments)
    assert resolved()["1"] is True


@pytest.mark.parametrize(
    "forces, date, error",
    [
        ({"27": 1.0}, DATE, InstrumentsError),
        ({"26": 0.0}, DATE, InstrumentsError),
        ({"26": -3.0}, DATE, InstrumentsError),
        ({"26": float("inf")}, DATE, InstrumentsError),
        ({"26": float("nan")}, DATE, InstrumentsError),
        ({"26": 250.0}, "24/09/2026", ValueError),
        ({"26": 250.0}, "20260924", ValueError),
        ({"26": 250.0}, "2026-02-30", ValueError),
        ({"26": 250.0}, "2026-9-24", ValueError),
    ],
)
def test_a_bad_write_is_refused_and_nothing_changes(filaments, forces, date, error):
    before = filaments.read_bytes()
    with pytest.raises(error):
        write_filament_forces(forces, date, None, filaments)
    assert filaments.read_bytes() == before
    assert sorted(p.name for p in filaments.parent.iterdir() if p.suffix == ".tmp") == []


def test_only_a_reweighed_filament_is_redated(filaments):
    """One save used to re-date every filament; now only a changed force gets the date."""
    assert write_filament_forces({"26": 251.3}, "2026-09-01", None, filaments) == 1
    written = write_filament_forces({"26": 251.3, "60": 590.0}, DATE, None, filaments)
    assert written == 1, "the unchanged 26 g is not written again"
    rows = {row["label_g"]: row for row in _load(filaments)["filaments"]}
    assert rows["26"]["weighed_date"] == "2026-09-01"
    assert rows["60"]["weighed_date"] == DATE
    assert rows["100"]["weighed_date"] is None
    assert _load(filaments)["weighing_date"] == DATE, "the file date is the latest row date"


def test_saving_what_is_already_there_writes_nothing(filaments):
    write_filament_forces({"26": 251.3}, DATE, None, filaments)
    before = filaments.read_bytes()
    assert write_filament_forces({"26": 251.3}, "2026-10-01", None, filaments) == 0
    assert filaments.read_bytes() == before


def test_a_small_force_is_written_as_a_number(filaments):
    """PyYAML reads `1e-05` as a string; the writer spells it out."""
    assert instruments.yaml_number(0.00001) == "0.00001"
    assert instruments.yaml_number(251.0) == "251.0"
    write_filament_forces({"0.008": 0.00001}, DATE, None, filaments)
    rows = {r["label_g"]: r for r in _load(filaments)["filaments"]}
    value = rows["0.008"]["force_measured_mn"]
    assert isinstance(value, float) and value == pytest.approx(0.00001)


def test_the_new_text_is_held_to_the_loaders_rules(filaments):
    """cfg.validate_file is the check `load` runs, applied before anything is written."""
    data = _load(filaments)
    cfg.validate_file("filaments.yaml", data)
    data["filaments"][0]["force_nominal_mn"] = -1.0
    with pytest.raises(cfg.ConfigError):
        cfg.validate_file("filaments.yaml", data)


def test_the_files_line_endings_are_kept(filaments):
    crlf = filaments.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    filaments.write_bytes(crlf)
    write_filament_forces(WEIGHED, DATE, None, filaments)
    assert b"\n" not in filaments.read_bytes().replace(b"\r\n", b"")


def test_a_number_is_read_with_either_decimal_mark():
    assert instruments.parse_number("21,5") == 21.5
    assert instruments.parse_number(" 21.5 ") == 21.5
    with pytest.raises(ValueError):
        instruments.parse_number("warm")


@pytest.fixture
def dialog(app, filaments):
    seen = []
    made = InstrumentsDialog(
        cfg.load("sv", "en").experimenter_text, _load(filaments),
        lambda *values: seen.append(values), path=filaments,
    )
    return made, seen


def test_the_dialog_saves_what_was_typed(dialog, filaments):
    made, _ = dialog
    made.measured["26"].setText("251,3")
    made.weighing_date.setText(DATE)
    assert made.save()
    assert {r["label_g"]: r for r in _load(filaments)["filaments"]}["26"][
        "force_measured_mn"
    ] == pytest.approx(251.3)


@pytest.mark.parametrize(
    "typed, date, key",
    [
        ("heavy", DATE, "invalid_force"),
        ("0", DATE, "invalid_force"),
        ("251", "", "date_required"),
        ("251", "yesterday", "invalid_date"),
        ("", DATE, "nothing_to_save"),
    ],
)
def test_the_dialog_reports_a_typing_mistake_and_writes_nothing(dialog, filaments, typed, date,
                                                                key):
    made, _ = dialog
    before = filaments.read_text(encoding="utf-8")
    made.measured["26"].setText(typed)
    made.weighing_date.setText(date)
    assert not made.save()
    words = made.text["instruments"][key]
    assert made.forces_status.text().startswith(words.split("{")[0])
    assert filaments.read_text(encoding="utf-8") == before


def test_temperature_and_humidity_are_optional_and_handed_on(dialog):
    made, seen = dialog
    made.temperature.setText("21,5")
    assert made.hand_on_environment()
    assert seen == [(21.5, None)]
    made.humidity.setText("damp")
    assert not made.hand_on_environment()
    assert seen == [(21.5, None)], "a mistake hands nothing on"
