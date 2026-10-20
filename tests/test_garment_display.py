"""The experimenter screen's channel display. docs/LOG.md N7.F12f, N7.F16i;
tatp/ui/garment_display.py.

What it is handed in a session -- nothing while the condition's touch runs -- is
tests/test_ui.py's; that a demonstration hands it the garment in every phase is
tests/test_demo.py's.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.clock import Clock
from tatp.garment.base import Limits
from tatp.garment.mock import MockGarment
from tatp.ui.garment_display import GarmentDisplay, states_from_status

# A moment to hand the states over at, in monotonic seconds.
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


def _poll(display, garment, now_s):
    """What a demonstration hands the display: the garment as commanded, now."""
    display.show_states(
        states_from_status(garment.status(), garment.channels(), bool(garment.connected),
                           garment.per_channel_pressure),
        bool(garment.link_lost), now_s,
    )


def _display(config, garment_class=MockGarment):
    garment = garment_class(Limits.from_config(config.hardware), Clock())
    garment.connect()
    display = GarmentDisplay(garment.channels(), garment.limits.pressure_ceiling_kpa,
                             garment.per_channel_pressure, config.experimenter_text["hardware"],
                             float(config.hardware["screens"]["garment_highlight_s"]))
    _poll(display, garment, T0_S)
    return display, garment


def test_a_channel_that_changes_is_lit_then_fades(app, config):
    display, garment = _display(config)
    highlight_s = display.highlight_s
    first, second = garment.channels()[:2]
    assert all(display.highlight(c) == 0 for c in garment.channels()), "nothing changed yet"
    garment.set_channel(first, True)
    _poll(display, garment, T0_S + 1)
    assert display.highlight(first) == 1.0
    assert display.highlight(second) == 0.0
    _poll(display, garment, T0_S + 1 + highlight_s / 2)
    assert display.highlight(first) == pytest.approx(0.5)
    _poll(display, garment, T0_S + 1 + highlight_s)
    assert display.highlight(first) == 0.0
    assert display.states[first][0] is True, "steady, still on"


def test_a_pressure_change_lights_the_channel_and_shows_its_value(app, config):
    display, garment = _display(config)
    channel = garment.channels()[0]
    kpa = garment.limits.pressure_ceiling_kpa / 2
    garment.set_pressure(channel, kpa)
    _poll(display, garment, T0_S + 1)
    assert display.highlight(channel) == 1.0
    assert display.reading(channel) == f"{kpa:.0f}"
    assert display.states[channel] == (False, kpa), "set, not applied: off"


def test_a_driver_without_per_channel_pressure_shows_on_and_off_alone(app, config):
    display, garment = _display(config, _Sleeve)
    channel = garment.channels()[0]
    garment.set_channel(channel, True)
    _poll(display, garment, T0_S + 1)
    assert display.reading(channel) == config.experimenter_text["hardware"]["channel_on"]
    assert display.highlight(channel) == 1.0


def test_a_stop_is_seen_as_every_channel_that_was_on_changing(app, config):
    display, garment = _display(config)
    on = garment.channels()[:2]
    for channel in on:
        garment.set_channel(channel, True)
    _poll(display, garment, T0_S + 1)
    garment.stop()
    _poll(display, garment, T0_S + 10)
    assert [c for c in garment.channels() if display.highlight(c) == 1.0] == list(on)


def test_a_lost_link_holds_the_last_command(app, config):
    """The outputs may still hold their last state (N7.U16): not drawn as switching off. The
    warning itself is the side column's (`hardware.link_lost`)."""
    display, garment = _display(config)
    on = garment.channels()[0]
    garment.set_channel(on, True)
    _poll(display, garment, T0_S + 1)
    before = dict(display.states)
    garment.lost("no reply")
    _poll(display, garment, T0_S + 10)
    assert display.states == before
    assert display.states[on][0] is True
    assert display.link_lost
    assert all(display.highlight(c) == 0 for c in garment.channels())


def test_a_disconnect_shows_every_channel_off(app, config):
    """The driver zeroes its outputs on the way out, whatever the status still holds."""
    display, garment = _display(config)
    on = garment.channels()[0]
    garment.set_pressure(on, garment.limits.pressure_ceiling_kpa / 2)
    garment.set_channel(on, True)
    _poll(display, garment, T0_S + 1)
    garment.disconnect()
    _poll(display, garment, T0_S + 10)
    assert all(state == (False, 0.0) for state in display.states.values())


def test_it_redraws_only_on_a_change_or_a_fading_highlight(app, config, monkeypatch):
    display, garment = _display(config)
    redraws = []
    monkeypatch.setattr(display, "update", lambda: redraws.append(True))
    _poll(display, garment, T0_S + 1)
    assert redraws == [], "steady: nothing to redraw"
    garment.set_channel(garment.channels()[0], True)
    _poll(display, garment, T0_S + 2)
    _poll(display, garment, T0_S + 2 + display.highlight_s / 2)
    _poll(display, garment, T0_S + 2 + display.highlight_s)
    assert len(redraws) == 3, "the change, the fade, and its end"
    _poll(display, garment, T0_S + 3 + display.highlight_s)
    assert len(redraws) == 3


def test_its_fade_runs_only_while_a_row_is_lit(app, config):
    display, garment = _display(config)
    assert not display.fade.isActive()
    garment.set_channel(garment.channels()[0], True)
    _poll(display, garment, T0_S + 1)
    assert display.fade.isActive()
    _poll(display, garment, T0_S + 1 + display.highlight_s)
    assert not display.fade.isActive()


def test_its_size_holds_whatever_the_readings(app, config):
    """Nothing moves as the readings change (UI_PRINCIPLES.md 3.3)."""
    display, garment = _display(config)
    before = display.sizeHint()
    for channel in garment.channels():
        garment.set_pressure(channel, garment.limits.pressure_ceiling_kpa)
        garment.set_channel(channel, True)
    _poll(display, garment, T0_S + 1)
    garment.disconnect()
    _poll(display, garment, T0_S + 2)
    assert display.sizeHint() == before
