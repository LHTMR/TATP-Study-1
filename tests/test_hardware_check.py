"""The hardware check, launcher entry 5 (docs/LOG.md N7.F4).

Driven with the audio test double and the mock garment, so nothing here needs a device. What is
tested is that each check goes through the session's own code, and that closing lets go.
"""

from __future__ import annotations

import copy

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.audio import amplitude
from tatp.hardware_check import HardwareCheckDialog, device_lines
from tatp.responder import Action
from tatp.ui.vas import QT_KEYS


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def check(app, loaded):
    hardware = copy.deepcopy(loaded.hardware)
    hardware["audio"]["backend"] = "recording"
    hardware["garment"]["driver"] = "mock"
    dialog = HardwareCheckDialog(loaded.experimenter_text, hardware)
    dialog.show()
    yield dialog
    dialog.reject()


def _press(widget, name: str, autorepeat: bool = False) -> None:
    for kind in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(
            widget, QKeyEvent(kind, QT_KEYS[name], Qt.NoModifier, "", autorepeat)
        )


def test_each_remote_button_counts_as_its_own_action(check):
    for name in ("pageup", "pagedown", "f5", "escape", "period"):
        _press(check.close_button, name)
    assert check.presses == {
        Action.DECREASE: 1, Action.INCREASE: 1, Action.CONFIRM: 2, Action.EMERGENCY_STOP: 1,
    }
    assert "(period)" in check.last_key.text(), "the last key is named, so ▶'s two can be seen"


def test_a_held_button_counts_once(check):
    _press(check, "pagedown")
    _press(check, "pagedown", autorepeat=True)
    assert check.presses[Action.INCREASE] == 1


def test_the_play_buttons_escape_does_not_close_the_check(check):
    """Every other ▶ is escape; it is a press to count, not Qt's 'close this dialog'."""
    _press(check, "escape")
    assert check.isVisible()


def test_the_noise_runs_through_the_sessions_audio_within_its_range(check):
    check.toggle_noise()
    events = check.audio.output.events
    assert events[0] == ("start_noise", amplitude(check.audio.start_dbfs))
    assert check.cue_button.isEnabled()
    check.level.setValue(round(check.audio.max_dbfs) + 10)
    assert check.audio.noise_level_dbfs == check.audio.max_dbfs, "the ceiling still holds"
    check.play_cue()
    assert events[-1][0] == "participant_tone"
    check.toggle_noise()
    assert not check.audio.noise_running


def test_the_alert_goes_to_the_experimenters_device(check):
    check.play_alert()
    assert check.audio.output.events[-1][0] == "experimenter_tone"


def test_each_garment_channel_turns_on_and_off(check):
    check.toggle_garment()
    assert check.garment.connected
    check.channel_buttons[2].setChecked(True)
    assert check.garment.status()["channels_on"] == [2]
    check.channel_buttons[2].setChecked(False)
    assert check.garment.status()["channels_on"] == []
    check.toggle_garment()
    assert check.garment is None


def test_closing_lets_everything_go(check):
    check.toggle_noise()
    check.toggle_garment()
    garment = check.garment
    check.channel_buttons[1].setChecked(True)
    check.reject()
    assert not check.audio.noise_running
    assert not garment.connected
    assert check.garment is None
    before = dict(check.presses)
    _press(check.close_button, "f5")
    assert check.presses == before, "the remote is no longer taken once the check is closed"


class _FakeSounddevice:
    """sounddevice's matching, reduced to what `device_lines` asks of it."""

    devices = [
        {"name": "Headphones (Realtek)", "hostapi": 0, "max_output_channels": 2},
        {"name": "Microphone (Realtek)", "hostapi": 0, "max_output_channels": 0},
        {"name": "Speakers (Realtek)", "hostapi": 0, "max_output_channels": 2},
    ]

    def query_hostapis(self):
        return [{"name": "Windows WASAPI"}]

    def query_devices(self, device=None, kind=None):
        if device is None:
            return self.devices
        words = device.split()
        found = [d for d in self.devices if d["max_output_channels"] > 0
                 and all(w in f"{d['name']}, Windows WASAPI" for w in words)]
        if len(found) != 1:
            raise ValueError(f"No output device matching {device!r}")
        return found[0]


def test_a_missing_device_is_named_and_every_output_listed(loaded):
    """S's lab run: the headphones were on a cable, and the configured device is Bluetooth."""
    audio = {"participant_device": "Bose QC Headphones WASAPI",
             "experimenter_device": "Speakers Realtek WASAPI"}
    words = loaded.experimenter_text["hardware_check"]
    lines, available = device_lines(audio, words, _FakeSounddevice())
    assert "Bose QC Headphones" in lines[0] and "not found" in lines[0]
    assert lines[1].endswith("Speakers (Realtek), Windows WASAPI")
    assert available.splitlines() == [
        "Headphones (Realtek), Windows WASAPI", "Speakers (Realtek), Windows WASAPI",
    ]
