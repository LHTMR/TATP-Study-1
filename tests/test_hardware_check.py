"""The hardware page: shown before the launcher, and as its entry 5 (docs/LOG.md N7.F4,
N7.F12e1-e5).

Driven with the audio test double, the mock garment and detectors that report what each test
says is connected, so nothing here needs a device. What is tested is that each check goes
through the session's own code, that each choice follows what is connected until it is made by
hand, that a device connected later is found, and that closing lets go.
"""

from __future__ import annotations

import copy
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.audio import amplitude
from tatp.devices import KEYBOARD, ON_SCREEN, REMOTE
from tatp.hardware_check import (
    INPUT,
    MISSING,
    OK,
    STAND_IN,
    STATE_COLOURS,
    Detectors,
    HardwareCheckDialog,
)
from tatp.responder import Action
from tatp.ui.vas import QT_KEYS

BOSE = "Bose QC Headphones, Windows WASAPI"
SPEAKERS = "Speakers (Realtek(R) Audio), Windows WASAPI"
LAPTOP = "Speakers (Realtek(R) Audio), MME"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def hardware(loaded):
    hardware = copy.deepcopy(loaded.hardware)
    hardware["audio"]["backend"] = "recording"
    hardware["garment"]["driver"] = "mock"
    return hardware


@pytest.fixture
def connected():
    """The lab, as the page is told it is: two screens, the sleeve's port, the remote, and
    both sound devices. Each test changes what it needs."""
    return SimpleNamespace(screens=[(1280, 800), (1280, 800)], ports=["COM3"], remote=True,
                           outputs=[BOSE, SPEAKERS, LAPTOP], default=LAPTOP)


def _detectors(connected) -> Detectors:
    def probe(_audio, on_done):
        on_done({"outputs": list(connected.outputs), "default": connected.default,
                 "unresolved": {}}, "")

    return Detectors(lambda: list(connected.screens), lambda: list(connected.ports),
                     lambda: connected.remote, probe)


@pytest.fixture
def page_for(app, hardware, connected):
    made = []

    def build(choices=None, hardware=hardware):
        dialog = HardwareCheckDialog(cfg.load("sv", "en").experimenter_text, hardware,
                                     choices, _detectors(connected))
        dialog.show()
        made.append(dialog)
        return dialog

    yield build
    for dialog in made:
        dialog.reject()


@pytest.fixture
def check(page_for):
    return page_for()


def _press(widget, name: str, autorepeat: bool = False) -> None:
    for kind in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(
            widget, QKeyEvent(kind, QT_KEYS[name], Qt.NoModifier, "", autorepeat)
        )


def _state(page, name: str) -> str:
    colour = page.status[name].styleSheet().removeprefix("color: ").removesuffix(";")
    return {value: key for key, value in STATE_COLOURS.items()}[colour]


# -- the lab's own setup -----------------------------------------------------------------


def test_with_everything_connected_every_choice_is_the_labs(check, hardware):
    lab = hardware
    choices = check.choices()
    assert choices.participant_screen_index == lab["screens"]["participant_screen_index"]
    assert choices.participant_audio_device == lab["audio"]["participant_device"]
    assert choices.experimenter_audio_device == lab["audio"]["experimenter_device"]
    assert choices.garment_port == lab["garment"]["prototype"]["port"]
    assert choices.participant_input == REMOTE
    assert all(_state(check, name) == OK for name in check.status)
    assert check.session_hardware()["changed_at_launch"] == ""


# -- the remote and its alternatives -------------------------------------------------------


def test_each_remote_button_counts_as_its_own_action(check):
    for name in ("pageup", "pagedown", "f5", "escape", "period"):
        _press(check.cancel_button, name)
    assert check.presses == {
        Action.DECREASE: 1, Action.INCREASE: 1, Action.CONFIRM: 2, Action.EMERGENCY_STOP: 1,
    }
    assert "(period)" in check.last_key.text(), "the last key is named, so ▶'s two can be seen"


def test_a_held_button_counts_once(check):
    _press(check, "pagedown")
    _press(check, "pagedown", autorepeat=True)
    assert check.presses[Action.INCREASE] == 1


def test_the_remotes_raw_reports_count_as_presses_once_each(check):
    """Under raw_input the remote's presses arrive from its raw reports (docs/LOG.md N7.D22):
    a press counts, its repeats and its release do not."""
    check.remote_key("period", False, False, 100)
    check.remote_key("period", False, True, 150)
    check.remote_key("period", True, False, 200)
    assert check.presses[Action.EMERGENCY_STOP] == 1


def test_the_play_buttons_escape_does_not_close_the_page(check):
    """Every other ▶ is escape; it is a press to count, not Qt's 'close this dialog'."""
    _press(check, "escape")
    assert check.isVisible()


def test_without_the_remote_the_keyboard_stands_in_until_it_is_plugged_in(page_for, connected):
    """S, 15 Oct 2026: with the remote missing, a pilot or a demo can still respond."""
    connected.remote = False
    page = page_for()
    assert page.values[INPUT] == KEYBOARD
    assert _state(page, INPUT) == STAND_IN
    assert page.words["remote_missing"] in page.status[INPUT].text()
    connected.remote = True
    page.detect()
    assert page.values[INPUT] == REMOTE, "found without restarting"
    assert _state(page, INPUT) == OK


def test_where_the_remote_cannot_be_told_apart_the_keyboard_is_chosen(page_for, connected):
    """Off Windows there is no Raw Input, so the remote cannot be seen at all (a MacBook)."""
    connected.remote = None
    page = page_for()
    assert page.values[INPUT] == KEYBOARD
    page.choose(INPUT, page.options[INPUT].index(REMOTE))
    assert page.status[INPUT].text() == page.words["remote_unknown"]


def test_the_keyboard_counts_its_own_keys(page_for, connected):
    connected.remote = False
    page = page_for()
    for name in ("left", "right", "return", "escape"):
        _press(page.cancel_button, name)
    assert page.presses == {action: 1 for action in Action}
    _press(page.cancel_button, "pageup")
    assert page.presses[Action.DECREASE] == 1, "the remote's keys are not the keyboard's"


def test_a_chosen_input_stays_chosen_whatever_is_connected(page_for, connected):
    page = page_for()
    page.choose(INPUT, page.options[INPUT].index(ON_SCREEN))
    connected.remote = False
    page.detect()
    connected.remote = True
    page.detect()
    assert page.values[INPUT] == ON_SCREEN
    assert INPUT in page.choices().chosen


# -- the screens --------------------------------------------------------------------------


def test_one_screen_puts_the_participant_in_a_window_until_the_second_is_connected(
    page_for, connected, hardware
):
    connected.screens = [(1470, 956)]
    page = page_for()
    name = "participant_screen_index"
    assert page.values[name] is None
    assert page.status[name].text() == page.words["screen_unplaced_participant"]
    connected.screens = [(1470, 956), (1280, 800)]
    page.detect()
    assert page.values[name] == hardware["screens"]["participant_screen_index"]


def test_a_screen_chosen_by_hand_and_then_unplugged_is_shown_missing(page_for, connected):
    page = page_for()
    name = "participant_screen_index"
    page.choose(name, page.options[name].index(1))
    connected.screens = [(1280, 800)]
    page.detect()
    assert page.values[name] == 1
    assert _state(page, name) == MISSING
    assert page.combos[name].currentText() == page.words["not_connected"].format(
        value=page.words["screen_numbered"].format(index=1)
    )


# -- the sound ----------------------------------------------------------------------------


def test_a_missing_lab_device_is_shown_missing_on_the_lab_platform(page_for, connected,
                                                                   hardware):
    """In the lab a headset that is off is to be switched on, not quietly replaced by the
    laptop's speakers."""
    connected.outputs = [SPEAKERS, LAPTOP]
    page = page_for(hardware={**hardware, "lab_platform": sys.platform})
    name = "participant_audio_device"
    assert page.values[name] == page.lab.participant_audio_device
    assert _state(page, name) == MISSING
    connected.outputs = [BOSE, SPEAKERS, LAPTOP]
    page.probe_audio()
    assert _state(page, name) == OK, "a headset switched on later is found"


def test_off_the_lab_platform_the_default_output_stands_in(page_for, connected, hardware):
    """A MacBook has none of the lab's WASAPI devices (docs/LOG.md N7.F12e5)."""
    connected.outputs = ["MacBook Air Speakers, Core Audio"]
    connected.default = "MacBook Air Speakers, Core Audio"
    page = page_for(hardware={**hardware, "lab_platform": "elsewhere"})
    for name in ("participant_audio_device", "experimenter_audio_device"):
        assert page.values[name] is None
        assert _state(page, name) == STAND_IN
        assert "MacBook Air Speakers" in page.combos[name].currentText()
    changed = page.session_hardware()["changed_at_launch"].split(";")
    assert {"participant_audio_device", "experimenter_audio_device"} <= set(changed)


def test_choosing_the_labs_device_from_the_list_keeps_its_configured_name(page_for):
    """So choosing it again is not recorded as a change of hardware."""
    page = page_for()
    name = "participant_audio_device"
    page.choose(name, 0)  # the system default
    page.choose(name, page.combos[name].findText(BOSE))
    assert page.values[name] == page.lab.participant_audio_device


def test_a_listing_that_fails_says_why(page_for, hardware):
    page = page_for()
    page._probed(None, "PortAudio could not start")
    assert "PortAudio could not start" in page.status["participant_audio_device"].text()


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


def test_the_test_sounds_play_on_the_device_chosen(page_for):
    page = page_for()
    name = "experimenter_audio_device"
    page.choose(name, page.combos[name].findText(LAPTOP))
    assert page.audio.config["experimenter_device"] == LAPTOP


# -- the garment --------------------------------------------------------------------------


def test_each_garment_channel_turns_on_and_off(check):
    check.toggle_garment()
    assert check.garment.connected
    check.channel_buttons[2].setChecked(True)
    assert check.garment.status()["channels_on"] == [2]
    check.channel_buttons[2].setChecked(False)
    assert check.garment.status()["channels_on"] == []
    check.toggle_garment()
    assert check.garment is None


def test_each_channel_button_says_whether_its_channel_is_on(check):
    """S, 15 Oct 2026: the buttons looked the same on and off."""
    words = check.words
    check.toggle_garment()
    check.channel_buttons[2].setChecked(True)
    assert check.channel_buttons[2].text() == words["channel_on"].format(value=2)
    assert check.channel_buttons[1].text() == words["channel_off"].format(value=1)
    check.channel_buttons[2].setChecked(False)
    assert check.channel_buttons[2].text() == words["channel_off"].format(value=2)
    check.toggle_garment()
    assert all(made.text() == words["channel_off"].format(value=channel)
               for channel, made in check.channel_buttons.items())


def test_a_port_plugged_in_later_is_found(page_for, connected):
    connected.ports = []
    page = page_for()
    assert page.status["garment_port"].text() == page.words["ports_none"]
    connected.ports = ["COM3"]
    page.detect()
    assert _state(page, "garment_port") == OK


# -- reopening and closing ----------------------------------------------------------------


def test_reopened_the_page_is_as_it_was_left(page_for):
    first = page_for()
    first.choose(INPUT, first.options[INPUT].index(ON_SCREEN))
    again = page_for(first.choices())
    assert again.values == first.values
    assert again.chosen == first.chosen


def test_closing_lets_everything_go(check):
    check.toggle_noise()
    check.toggle_garment()
    garment = check.garment
    check.channel_buttons[1].setChecked(True)
    check.reject()
    assert check.audio is None
    assert not garment.connected
    assert check.garment is None
    before = dict(check.presses)
    _press(check.cancel_button, "f5")
    assert check.presses == before, "the remote is no longer taken once the page is closed"


def test_nothing_is_detected_once_closed(page_for, connected):
    """A change of input after closing would take the response keys from the session."""
    connected.remote = False
    page = page_for()
    page.reject()
    connected.remote = True
    page.detect()
    assert page.values[INPUT] == KEYBOARD
    assert page.remote_keys is None
