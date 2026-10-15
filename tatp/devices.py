"""What is connected now, and the hardware a session is run with. docs/LOG.md N7.F12e1-e3.

The hardware page (`tatp/hardware_check.py`) opens before the launcher, as a videoconferencing
program's settings do: each device the session uses, found or missing, chosen from what is
connected, with hardware.yaml's lab setup as the default. What is chosen is a `HardwareChoices`,
which `tatp.session.with_hardware_choices` writes into the configuration every session started
from the launcher is checked and run with, and the session file records it.

**Sound devices are listed in a child process.** PortAudio lists the devices once, when it
starts, and restarting it inside a running program is unsafe: that frees every stream it holds,
and sounddevice closes its last `play()` stream again on the next one, which then touches freed
memory (the review of N7.F10c). So the launcher process never loads PortAudio at all before a
session plays its first sound. Listing the devices, checking the configured ones before a
session (`tatp/preflight.py`), and the page's test sounds all run in a short-lived
`python -m tatp.devices` of their own, which sees whatever is connected at that moment. A
headset switched on after the program opened is then found by the next listing, and by the
session, whose own PortAudio starts only at the masking check.

Nothing here imports Qt, so the child process starts quickly.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field

from tatp.audio import Audio, unresolved_devices
from tatp.clock import Clock
from tatp.config import REPO_ROOT

# The child process's commands (`main`).
PROBE = "probe"
SERVE = "serve"
# The serve command's own commands, one per line on its standard input.
START_NOISE = "start"
SET_LEVEL = "level"
STOP_NOISE = "stop"
CUE = "cue"
ALERT = "alert"
# What the serve command prints when a sound fails: this, then why.
FAILED = "failed "

# The participant's response, `responder.participant_input` (docs/LOG.md N7.F12e4). The remote
# is the study's; the two alternatives are for a pilot code or a demonstration only.
REMOTE = "remote"
KEYBOARD = "keyboard"
ON_SCREEN = "on_screen"
PARTICIPANT_INPUTS = (REMOTE, KEYBOARD, ON_SCREEN)


def output_labels(sd) -> list[str]:
    """Every output device, as "<name>, <host API>": the string sounddevice matches a device
    by (`tatp.audio.resolve_device`), so a chosen label opens exactly that device."""
    hostapis = [api["name"] for api in sd.query_hostapis()]
    return [
        f"{device['name']}, {hostapis[device['hostapi']]}"
        for device in sd.query_devices()
        if device["max_output_channels"] > 0
    ]


def matching_outputs(spec: str, outputs: list[str]) -> list[str]:
    """The outputs a device named `spec` opens, by sounddevice's own rule: every word of the
    name, in order, ignoring case; several matches settled by one whose device name is exactly
    `spec`. One match is a device found; none or several, one that cannot be opened."""
    words = spec.lower().split()
    found = []
    for output in outputs:
        position = 0
        for word in words:
            position = output.lower().find(word, position)
            if position < 0:
                break
            position += len(word)
        else:
            found.append(output)
    exact = [output for output in found if output.rpartition(", ")[0].lower() == spec.lower()]
    return exact if len(found) > 1 and len(exact) == 1 else found


def default_output_label(sd) -> str | None:
    """The system's default output now, or None when it has none."""
    index = sd.default.device[1]
    if index is None or index < 0:
        return None
    device = sd.query_devices(index)
    return f"{device['name']}, {sd.query_hostapis(device['hostapi'])['name']}"


def probe(audio_config: dict, sd) -> dict:
    """What the child reports: every output, the default, and each configured device that
    cannot be opened, with why."""
    return {
        "outputs": output_labels(sd),
        "default": default_output_label(sd),
        "unresolved": unresolved_devices(audio_config, sd),
    }


def _child(command: str, audio_config: dict) -> list[str]:
    return [sys.executable, "-m", "tatp.devices", command, json.dumps(audio_config)]


def probe_in_child(audio_config: dict, timeout_s: float) -> dict:
    """`probe`, in a child process of its own, so this one never loads PortAudio. A child that
    fails or does not answer raises: there is no list to fall back on."""
    done = subprocess.run(_child(PROBE, audio_config), cwd=REPO_ROOT, capture_output=True,
                          text=True, timeout=timeout_s, check=True)
    return json.loads(done.stdout)


def probe_command(audio_config: dict) -> tuple[str, list[str]]:
    """The program and arguments for a probe run another way (the page's, without waiting)."""
    program, *arguments = _child(PROBE, audio_config)
    return program, arguments


def serve_command(audio_config: dict) -> tuple[str, list[str]]:
    """The program and arguments of a child that plays the page's test sounds."""
    program, *arguments = _child(SERVE, audio_config)
    return program, arguments


def serve(audio_config: dict, commands, sd) -> None:
    """Play what each line of `commands` asks, through the session's own `Audio`, so the
    noise ceiling holds and the cue is set over the noise as in a session. A sound that fails
    is reported on standard output and the next command is read: a device that cannot be
    opened is what the page is there to show."""
    audio = Audio(audio_config, Clock(), lambda *_, **__: None)
    for line in commands:
        command, _, value = line.strip().partition(" ")
        try:
            if command == START_NOISE:
                audio.start_noise(float(value))
            elif command == SET_LEVEL:
                audio.set_noise_level(float(value))
            elif command == STOP_NOISE:
                audio.stop_noise("hardware page")
            elif command == CUE:
                audio.participant_cue()
            elif command == ALERT:
                audio.experimenter_alert("hardware page")
        except (ValueError, OSError, sd.PortAudioError) as error:
            # The noise did not start, so the page must not show it running.
            audio.noise_running = audio.noise_running and command != START_NOISE
            print(f"{FAILED}{command} {error}", flush=True)
    audio.close()


# -- the hardware a session runs with ------------------------------------------------------


@dataclass(frozen=True)
class HardwareChoices:
    """What the hardware page chose. None for a screen is a window on the experimenter's
    screen; None for a sound device is the system's default output."""

    participant_screen_index: int | None
    experimenter_screen_index: int | None
    participant_audio_device: str | None
    experimenter_audio_device: str | None
    garment_port: str | None
    participant_input: str
    # The choices the person at the page made themselves; the rest follow what is connected.
    chosen: frozenset[str] = field(default_factory=frozenset)


# Every choice, by its field: what the session file's `hardware_changed` names.
CHOICE_NAMES = (
    "participant_screen_index",
    "experimenter_screen_index",
    "participant_audio_device",
    "experimenter_audio_device",
    "garment_port",
    "participant_input",
)


def configured(hardware: dict) -> HardwareChoices:
    """hardware.yaml's own choices: the lab setup."""
    screens, audio = hardware["screens"], hardware["audio"]
    return HardwareChoices(
        participant_screen_index=screens["participant_screen_index"],
        experimenter_screen_index=screens["experimenter_screen_index"],
        participant_audio_device=audio["participant_device"],
        experimenter_audio_device=audio["experimenter_device"],
        garment_port=hardware["garment"]["prototype"]["port"],
        participant_input=hardware["responder"]["participant_input"],
    )


def on_lab_platform(hardware: dict) -> bool:
    """Whether this computer runs the platform hardware.yaml's lab setup describes. Off it, the
    lab's sound devices cannot exist, so the page takes the default output in their place."""
    return sys.platform == hardware["lab_platform"]


def main(argv: list[str]) -> int:
    command, audio_json = argv
    audio_config = json.loads(audio_json)
    import sounddevice

    if command == PROBE:
        print(json.dumps(probe(audio_config, sounddevice)))
    elif command == SERVE:
        serve(audio_config, sys.stdin, sounddevice)
    else:
        raise SystemExit(f"tatp.devices: {command!r} is not one of {PROBE}, {SERVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
