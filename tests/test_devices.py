"""What is connected, and the hardware a session runs with. docs/LOG.md N7.F12e1-e5."""

from __future__ import annotations

import sys

import pytest

from tatp import config as cfg
from tatp import devices
from tatp.devices import (
    KEYBOARD,
    ON_SCREEN,
    REMOTE,
    HardwareChoices,
    configured,
    matching_outputs,
)
from tatp.remote_keys import ANY_KEYBOARD, RAW_INPUT, with_key_source
from tatp.session import hardware_with_choices

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
        "garment_port", "participant_input",
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
    assert hardware["changed_at_launch"] == ""


def test_the_alternative_keys_are_none_of_the_remotes_but_its_play_buttons_escape(lab):
    responder = lab["responder"]
    alternative = {key for keys in responder["alternative_keys"].values() for key in keys}
    remote = {key for keys in responder["keys"].values() for key in keys}
    assert alternative & remote == {"escape"}, "hardware.yaml says why Esc is allowed"


def test_the_sound_devices_are_listed_by_a_child_process(lab):
    """The child path end to end, on whatever this machine has: it loads PortAudio, and this
    process does not (docs/LOG.md N7.F12e2)."""
    listed = devices.probe_in_child(lab["audio"], lab["devices"]["probe_timeout_s"])
    assert set(listed) == {"outputs", "default", "unresolved"}
    assert all(isinstance(output, str) for output in listed["outputs"])


def test_the_test_sound_child_plays_through_the_sessions_audio(lab, capsys):
    """`serve`, given the test double: each command goes through `Audio`, and nothing fails."""
    audio = {**lab["audio"], "backend": "recording"}

    class _NoPortAudio:
        class PortAudioError(Exception):
            pass

    commands = [f"{devices.START_NOISE} -30", f"{devices.SET_LEVEL} -20", devices.CUE,
                devices.ALERT, devices.STOP_NOISE]
    devices.serve(audio, commands, _NoPortAudio)
    assert capsys.readouterr().out == ""


def test_a_failed_sound_is_reported_and_the_child_carries_on(lab, capsys):
    audio = {**lab["audio"], "backend": "recording"}

    class _NoPortAudio:
        class PortAudioError(Exception):
            pass

    devices.serve(audio, [f"{devices.START_NOISE} loud", devices.ALERT], _NoPortAudio)
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1 and out[0].startswith(f"{devices.FAILED}{devices.START_NOISE} ")
