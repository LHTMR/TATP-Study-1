"""Garment control, pattern loading and playback. SPEC.md 12, 13."""

from __future__ import annotations

import pytest

from tatp import config as cfg
from tatp.clock import Clock
from tatp.garment import patterns as pat
from tatp.garment.base import GarmentError, Limits
from tatp.garment.mock import MockGarment

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"


class FakeClock(Clock):
    """A clock that only moves when the test moves it, so timing is exact rather than nearly."""

    def __init__(self):
        super().__init__()
        self.now = 0.0

    def elapsed_s(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def limits():
    return Limits.from_config(cfg.load("sv", "en").hardware)


@pytest.fixture
def garment(limits):
    clock = FakeClock()
    controller = MockGarment(limits, clock)
    controller.connect()
    return controller


# -- limits and capabilities -----------------------------------------------------------


def test_the_software_ceiling_sits_below_the_hardware_maximum(limits):
    """SPEC.md 13. The whole point of the ceiling is that it is not the hardware maximum."""
    assert 0 < limits.pressure_ceiling_kpa < limits.pressure_max_kpa


def test_a_ceiling_at_or_above_the_hardware_maximum_is_refused(limits):
    hardware = {
        "garment": {
            "pressure_max_kpa": 250.0,
            "pressure_ceiling_kpa": 250.0,
            "pressure_rate_max_kpa_s": 60.0,
        }
    }
    with pytest.raises(AssertionError, match="below the hardware maximum"):
        Limits.from_config(hardware)


def test_capabilities_are_declared_by_the_class(garment):
    """SPEC.md 12.1: declared by the driver, never queried from the device."""
    caps = garment.capabilities()
    assert caps["n_channels"] == MockGarment.n_channels
    assert caps["per_channel_pressure"] is True
    assert caps["pressure_range_kpa"][1] == garment.limits.pressure_ceiling_kpa
    assert garment.driver_name == "MockGarment"


# -- pressure --------------------------------------------------------------------------


def test_pressure_is_clamped_to_the_ceiling(garment):
    got = garment.set_pressure(1, 10_000.0)
    assert got == garment.limits.pressure_ceiling_kpa
    assert garment.pressure_kpa[1] == got


def test_a_negative_pressure_is_clamped_to_zero(garment):
    assert garment.set_pressure(1, -5.0) == 0.0


def test_the_rate_limit_holds_between_commands(garment):
    """SPEC.md 13: holding the up button must not ramp to maximum quickly."""
    garment.set_pressure(1, 50.0)
    garment.clock.now += 0.1
    allowed = garment.limits.pressure_rate_max_kpa_s * 0.1
    assert garment.set_pressure(1, 200.0) == pytest.approx(50.0 + allowed)
    garment.clock.now += 0.1
    assert garment.set_pressure(1, 0.0) == pytest.approx(50.0)


def test_stop_is_not_rate_limited(garment):
    garment.set_pressure(1, 150.0)
    garment.clock.now += 0.01
    garment.stop()
    assert all(value == 0.0 for value in garment.pressure_kpa.values())


def test_commands_are_refused_when_not_connected(limits):
    controller = MockGarment(limits, FakeClock())
    with pytest.raises(GarmentError, match="not connected"):
        controller.set_pressure(1, 10.0)


def test_an_unknown_channel_is_refused(garment):
    with pytest.raises(GarmentError, match="channel 9 is not one of"):
        garment.set_pressure(9, 10.0)


def test_every_command_is_recorded_with_a_timestamp(garment):
    garment.clock.now = 4.0
    garment.set_pressure(2, 30.0)
    assert garment.commands[-1] == {"t_s": 4.0, "event": "set_pressure"}
    assert [c["event"] for c in garment.commands] == ["connect", "set_pressure"]


def test_a_clamped_command_reports_both_the_request_and_the_result(garment):
    written = []
    garment.on_command = written.append
    garment.set_pressure(1, 10_000.0)
    row = written[-1]
    assert row["requested_kpa"] == 10_000.0
    assert row["pressure_kpa"] == garment.limits.pressure_ceiling_kpa
    assert row["clamped"] is True
    assert row["driver"] == "MockGarment"


def test_an_injected_fault_is_raised_and_recorded(garment):
    garment.inject_fault("valve stuck", on_event="set_pressure")
    with pytest.raises(GarmentError, match="valve stuck"):
        garment.set_pressure(1, 20.0)
    assert garment.faults == ["valve stuck"]
    assert garment.status()["faults"] == ["valve stuck"]


# -- pattern files ---------------------------------------------------------------------


def test_the_example_patterns_load(garment):
    loaded = pat.load_folder(EXAMPLES)
    assert set(loaded) == {"sweep_01cms", "sweep_03cms", "sweep_20cms", "static_sham"}
    sweep = loaded["sweep_03cms"]
    assert sweep.channel_ids == (1, 2, 3, 4, 5)
    assert sweep.row_interval_ms == 500.0
    assert sweep.loop is True
    assert sweep.duration_s == pytest.approx(len(sweep.rows) * 0.5)


def test_the_sham_holds_every_channel_on(garment):
    """The sham differs from the moving patterns in motion only, not extent (PROGRESS.md)."""
    sham = pat.load_pattern(EXAMPLES / "static_sham.csv")
    assert sham.rows == ((1, 1, 1, 1, 1),)
    events = pat.expand(sham)
    assert [e.on for e in events] == [True] * 5 + [False] * 5


def test_every_channel_that_turns_on_turns_off(garment):
    """SPEC.md 12.4: the defect not to inherit is a channel left pressurised."""
    for pattern in pat.load_folder(EXAMPLES).values():
        events = pat.expand(pattern)
        for channel_id in pattern.channel_ids:
            mine = [e for e in events if e.channel_id == channel_id]
            assert [e.on for e in mine] == [True, False] * (len(mine) // 2)


def test_a_cell_that_is_not_zero_or_one_is_refused(tmp_path):
    """SPEC.md 12.4: `int()` accepts 2, which then matches neither the on nor the off test."""
    (tmp_path / "p.csv").write_text("1,2\n1,0\n0,2\n", encoding="utf-8")
    (tmp_path / "p.yaml").write_text(
        "name: p\nrow_interval_ms: 100\nchannel_ids: [1, 2]\nloop: false\n", encoding="utf-8"
    )
    with pytest.raises(pat.PatternError, match="is not 0 or 1"):
        pat.load_pattern(tmp_path / "p.csv")


def test_a_pattern_without_a_sidecar_is_refused(tmp_path):
    """SPEC.md 12.2: the row interval is per pattern and is never defaulted."""
    (tmp_path / "p.csv").write_text("1,2\n1,0\n", encoding="utf-8")
    with pytest.raises(pat.PatternError, match="no sidecar"):
        pat.load_pattern(tmp_path / "p.csv")


def test_a_sidecar_that_disagrees_with_the_header_is_refused(tmp_path):
    (tmp_path / "p.csv").write_text("1,2\n1,0\n", encoding="utf-8")
    (tmp_path / "p.yaml").write_text(
        "name: p\nrow_interval_ms: 100\nchannel_ids: [1, 3]\nloop: false\n", encoding="utf-8"
    )
    with pytest.raises(pat.PatternError, match="do not match the CSV header"):
        pat.load_pattern(tmp_path / "p.csv")


# -- playback --------------------------------------------------------------------------


def test_playback_delivers_events_as_they_come_due(garment):
    sweep = pat.load_pattern(EXAMPLES / "sweep_03cms.csv")
    garment.play_pattern(sweep)
    assert garment.status()["channels_on"] == []

    garment.advance()
    assert garment.status()["channels_on"] == [1], "row 0 is due at t=0"

    garment.clock.now += 0.5
    garment.advance()
    assert garment.status()["channels_on"] == [1, 2]


def test_a_pattern_addressing_a_channel_the_driver_lacks_is_refused(garment, tmp_path):
    (tmp_path / "p.csv").write_text("1,9\n1,1\n", encoding="utf-8")
    (tmp_path / "p.yaml").write_text(
        "name: p\nrow_interval_ms: 100\nchannel_ids: [1, 9]\nloop: false\n", encoding="utf-8"
    )
    with pytest.raises(GarmentError, match="addresses channels"):
        garment.play_pattern(pat.load_pattern(tmp_path / "p.csv"))


def test_a_looping_pattern_starts_again(garment):
    """SPEC.md 12.2: patterns repeat continuously for as long as they are active."""
    sweep = pat.load_pattern(EXAMPLES / "sweep_03cms.csv")
    garment.play_pattern(sweep)
    garment.clock.now += sweep.duration_s - 0.01
    garment.advance()
    assert garment.status()["channels_on"] == [5], "the last row is still running"

    garment.clock.now += 0.01
    garment.advance()
    assert garment.status()["channels_on"] == [1], "at t=duration the next cycle has begun"


def test_a_slow_tick_does_not_drop_a_whole_cycle(garment):
    sweep = pat.load_pattern(EXAMPLES / "sweep_03cms.csv")
    garment.play_pattern(sweep)
    garment.clock.now += sweep.duration_s * 2 + 0.5
    garment.advance()
    assert garment.status()["channels_on"] == [1, 2], "resumes at the right point in the cycle"


def test_stopping_a_pattern_turns_off_what_it_left_on(garment):
    garment.play_pattern(pat.load_pattern(EXAMPLES / "static_sham.csv"))
    garment.advance()
    assert garment.status()["channels_on"] == [1, 2, 3, 4, 5]
    garment.stop_pattern()
    assert garment.status()["channels_on"] == []
    assert garment.status()["pattern_name"] is None
    assert [c["event"] for c in garment.commands][-5:] == ["channel_off"] * 5
