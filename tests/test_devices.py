"""What is connected, and the hardware a session runs with. docs/LOG.md N7.F12e1-e5."""

from __future__ import annotations

import dataclasses
import sys

import pytest

from tatp import config as cfg
from tatp import devices
from tatp.demo import DEMO_GARMENT, REAL_TIME_SPEED, demo_config
from tatp.devices import (
    KEYBOARD,
    ON_SCREEN,
    REMOTE,
    HardwareChoices,
    configured,
    matching_outputs,
)
from tatp.remote_keys import ANY_KEYBOARD, RAW_INPUT, with_key_source
from tatp.session import hardware_with_choices, with_hardware_choices

OUTPUTS = [
    "Bose QC Headphones, Windows WASAPI",
    "Bose QC Headphones Hands-Free, Windows WASAPI",
    "Speakers (Realtek(R) Audio), Windows WASAPI",
    "Speakers (Realtek(R) Audio), MME",
]


@pytest.fixture(scope="module")
def lab():
    """hardware.yaml as the lab has it, raw_input and all."""
    return with_key_source(cfg.load("sv", "en").hardware, RAW_INPUT)


def _choices(lab, **changed) -> HardwareChoices:
    return HardwareChoices(**{**configured(lab).__dict__, **changed})


def test_a_device_is_matched_as_sounddevice_matches_it():
    assert matching_outputs("Speakers Realtek WASAPI", OUTPUTS) == [OUTPUTS[2]]
    assert matching_outputs("speakers mme", OUTPUTS) == [OUTPUTS[3]]
    assert matching_outputs("WASAPI Speakers", OUTPUTS) == [], "the words in order"
    assert len(matching_outputs("Bose WASAPI", OUTPUTS)) == 2, "two match: cannot be opened"
    # Several matches settled by the one whose device name is exactly the spec.
    assert matching_outputs("Bose QC Headphones", OUTPUTS) == [OUTPUTS[0]]


def test_the_lab_setup_changes_nothing(lab):
    hardware = hardware_with_choices(lab, configured(lab))
    assert hardware["changed_at_launch"] == ""
    assert hardware["responder"]["keys"] == lab["responder"]["keys"]
    if sys.platform == "win32":
        assert hardware["responder"]["key_source"] == RAW_INPUT


def test_a_macbook_with_one_screen_and_no_lab_device(lab):
    """S, 15 Oct 2026: one screen, its own speakers, no remote, no sleeve."""
    hardware = hardware_with_choices(lab, _choices(
        lab, participant_screen_index=None, experimenter_screen_index=0,
        participant_audio_device=None, experimenter_audio_device=None, garment_port=None,
        participant_input=KEYBOARD,
    ))
    assert hardware["screens"]["participant_screen_index"] is None
    assert hardware["audio"]["participant_device"] is None
    assert hardware["responder"]["key_source"] == ANY_KEYBOARD
    assert hardware["responder"]["keys"] == lab["responder"]["alternative_keys"]
    assert hardware["changed_at_launch"].split(";") == [
        "participant_screen_index", "participant_audio_device", "experimenter_audio_device",
        "garment_port", "participant_input", devices.KEY_SOURCE_CHANGE,
    ]


def test_the_on_screen_buttons_press_the_remotes_own_keys(lab):
    hardware = hardware_with_choices(lab, _choices(lab, participant_input=ON_SCREEN))
    assert hardware["responder"]["keys"] == lab["responder"]["keys"]
    assert hardware["responder"]["key_source"] == ANY_KEYBOARD


def test_off_windows_the_remote_is_read_from_every_keyboard(lab, monkeypatch):
    """Raw Input is Windows'; preflight would refuse raw_input on a Mac."""
    from tatp import session

    monkeypatch.setattr(session, "raw_input_available", lambda: False)
    hardware = hardware_with_choices(lab, _choices(lab, participant_input=REMOTE))
    assert hardware["responder"]["key_source"] == ANY_KEYBOARD
    assert hardware["changed_at_launch"] == devices.KEY_SOURCE_CHANGE, (
        "recorded, never silent: preflight refuses it for a study participant"
    )


def test_the_keyboards_stop_is_the_remotes_own_and_no_dialog_key(lab):
    """The full stop mirrors the remote's stop button; Esc, which dismisses dialogs, is not a
    key of the keyboard input at all (code review of N7.F12e4)."""
    responder = lab["responder"]
    alternative = {key for keys in responder["alternative_keys"].values() for key in keys}
    stop = responder["alternative_keys"]["emergency_stop"]
    assert stop == responder["keys"]["emergency_stop"]
    assert "escape" not in alternative


def test_what_was_not_chosen_follows_what_is_connected(lab):
    choices = dataclasses.replace(configured(lab), chosen=frozenset({"garment_port"}),
                                  garment_port="COM9")
    elsewhere = {**lab, "lab_platform": "elsewhere"}
    one_screen = devices.Present([(1470, 956)], [], None)
    settled = devices.settle(choices, elsewhere, one_screen)
    assert settled.participant_screen_index is None
    assert settled.participant_input == KEYBOARD
    assert settled.garment_port == "COM9", "chosen by hand: kept"
    two_screens = devices.Present([(1280, 800), (1280, 800)], [], True)
    settled = devices.settle(choices, elsewhere, two_screens)
    assert settled.participant_screen_index == lab["screens"]["participant_screen_index"]
    assert settled.participant_input == REMOTE


def test_in_the_lab_a_missing_remote_stays_the_remote(lab):
    """Spec review: shown missing, to be plugged in, not replaced by the keyboard."""
    here = {**lab, "lab_platform": sys.platform}
    assert devices.automatic("participant_input", here,
                             devices.Present([(1280, 800)], [], False)) == REMOTE


def test_a_demonstration_records_that_every_keyboard_counted(lab):
    """Spec review: the demonstration's own any_keyboard is in `hardware_changed` too."""
    loaded = cfg.load("sv", "en")
    config = with_hardware_choices(
        cfg.Config(**{**loaded.__dict__, "hardware": lab}), configured(lab))
    demo = demo_config(config, REAL_TIME_SPEED, DEMO_GARMENT)
    assert demo.hardware["responder"]["key_source"] == ANY_KEYBOARD
    assert demo.hardware["changed_at_launch"].split(";").count(devices.KEY_SOURCE_CHANGE) == 1


def test_off_the_lab_platform_an_unusable_lab_device_gives_way_to_the_default(lab):
    lab_device = lab["audio"]["participant_device"]
    present = devices.Present([(1280, 800)], [], None, outputs=["Speakers, Core Audio"],
                              checks={"participant": {lab_device: "No output device",
                                                      devices.DEFAULT_KEY: ""}})
    elsewhere = {**lab, "lab_platform": "elsewhere"}
    assert devices.automatic("participant_audio_device", elsewhere, present) is None
    here = {**lab, "lab_platform": sys.platform}
    assert devices.automatic("participant_audio_device", here, present) == lab_device


def test_the_sound_devices_are_listed_by_a_child_process(lab):
    """The child path end to end, on whatever this machine has: it loads PortAudio, and this
    process does not (docs/LOG.md N7.F12e2). Each candidate is checked as a session opens it."""
    request = devices.probe_request(lab["audio"], {"participant": [None, "no such device"]})
    listed = devices.probe_in_child(request, lab["devices"]["probe_timeout_s"])
    assert set(listed) == {"outputs", "default", "checks"}
    assert all(isinstance(output, str) for output in listed["outputs"])
    assert listed["checks"]["participant"]["no such device"], "a reason it cannot be opened"


def test_the_test_sound_child_plays_through_the_sessions_audio(lab, capsys):
    """`serve`, given the test double: each command goes through `Audio`, and nothing fails."""
    audio = {**lab["audio"], "backend": "recording"}

    class _NoPortAudio:
        class PortAudioError(Exception):
            pass

    commands = [f"{devices.START_NOISE} -30", f"{devices.SET_LEVEL} -20", devices.CUE,
                devices.ALERT, devices.STOP_NOISE]
    devices.serve(audio, commands, _NoPortAudio)
    assert capsys.readouterr().out == f"{devices.STARTED}\n", "only that the noise started"


def test_a_failed_sound_is_reported_and_the_child_carries_on(lab, capsys):
    audio = {**lab["audio"], "backend": "recording"}

    class _NoPortAudio:
        class PortAudioError(Exception):
            pass

    devices.serve(audio, [f"{devices.START_NOISE} loud", devices.ALERT], _NoPortAudio)
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1 and out[0].startswith(f"{devices.FAILED}{devices.START_NOISE} ")
