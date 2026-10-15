"""The demonstration's garment display. docs/LOG.md N7.F12f, tatp/ui/garment_display.py.

That it exists only in a demonstration is tests/test_demo.py's.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.clock import Clock
from tatp.garment.base import Limits
from tatp.garment.mock import MockGarment
from tatp.ui.garment_display import GarmentDisplay

# A moment to poll at, in `poll`'s monotonic seconds.
T0_S = 1000.0


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def config():
    return cfg.load("sv", "en")


class _Sleeve(MockGarment):
    """On and off only, as the prototype sleeve: its pressure is set by hand."""

    per_channel_pressure = False


def _display(config, garment_class=MockGarment):
    garment = garment_class(Limits.from_config(config.hardware), Clock())
    garment.connect()
    demo = config.study1["demo"]
    display = GarmentDisplay(garment, config.experimenter_text["demo"],
                             float(demo["garment_display_refresh_s"]),
                             float(demo["garment_highlight_s"]))
    display.timer.stop()  # polled by hand, at chosen moments
    display.poll(T0_S)
    return display, garment


def test_a_channel_that_changes_is_lit_then_fades(app, config):
    display, garment = _display(config)
    highlight_s = display.highlight_s
    first, second = garment.channels()[:2]
    assert all(display.highlight(c) == 0 for c in garment.channels()), "nothing changed yet"
    garment.set_channel(first, True)
    display.poll(T0_S + 1)
    assert display.highlight(first) == 1.0
    assert display.highlight(second) == 0.0
    display.poll(T0_S + 1 + highlight_s / 2)
    assert display.highlight(first) == pytest.approx(0.5)
    display.poll(T0_S + 1 + highlight_s)
    assert display.highlight(first) == 0.0
    assert display.states[first][0] is True, "steady, still on"


def test_a_pressure_change_lights_the_channel_and_shows_its_value(app, config):
    display, garment = _display(config)
    channel = garment.channels()[0]
    kpa = garment.limits.pressure_ceiling_kpa / 2
    garment.set_pressure(channel, kpa)
    display.poll(T0_S + 1)
    assert display.highlight(channel) == 1.0
    words = config.experimenter_text["demo"]
    assert display.reading(channel) == words["garment_pressure"].format(
        state=words["garment_off"], value=f"{kpa:.1f}")


def test_a_driver_without_per_channel_pressure_shows_on_and_off_alone(app, config):
    display, garment = _display(config, _Sleeve)
    channel = garment.channels()[0]
    garment.set_channel(channel, True)
    display.poll(T0_S + 1)
    assert display.reading(channel) == config.experimenter_text["demo"]["garment_on"]
    assert display.highlight(channel) == 1.0


def test_a_stop_is_seen_as_every_channel_that_was_on_changing(app, config):
    display, garment = _display(config)
    on = garment.channels()[:2]
    for channel in on:
        garment.set_channel(channel, True)
    display.poll(T0_S + 1)
    garment.stop()
    display.poll(T0_S + 10)
    assert [c for c in garment.channels() if display.highlight(c) == 1.0] == list(on)


def test_its_size_holds_whatever_the_readings(app, config):
    """Nothing moves as the readings change (UI_PRINCIPLES.md 3.3)."""
    display, garment = _display(config)
    before = display.sizeHint()
    for channel in garment.channels():
        garment.set_pressure(channel, garment.limits.pressure_ceiling_kpa)
        garment.set_channel(channel, True)
    garment.disconnect()
    display.poll(T0_S + 1)
    assert display.sizeHint() == before
    assert not display.connected
