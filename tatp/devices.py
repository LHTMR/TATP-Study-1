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
from typing import NamedTuple

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
# What the serve command prints when a sound fails: this, then why; and once the noise is
# actually playing.
FAILED = "failed "
STARTED = "started"
# A probe's key for the system's default output (`check_key`).
DEFAULT_KEY = ""

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


def check_key(spec: str | None) -> str:
    """A device's key in a probe's `checks`: its name, or "" for the system default."""
    return DEFAULT_KEY if spec is None else spec


def probe(request: dict, sd) -> dict:
    """What the child reports: every output, the default, and, for each role, whether each
    candidate device can be opened as a session opens it (`tatp.audio.resolve_device`: found by
    name, once, and able to play at the configured rate and channels) -- "" when it can, else
    why not. The same resolution the preflight refuses a session by."""
    audio = request["audio"]
    checks = {}
    for role, candidates in request["candidates"].items():
        checks[role] = {}
        for spec in candidates:
            why = unresolved_devices({**audio, f"{role}_device": spec}, sd).get(role, "")
            checks[role][check_key(spec)] = why
    return {"outputs": output_labels(sd), "default": default_output_label(sd), "checks": checks}


def probe_request(audio_config: dict, candidates: dict[str, list[str | None]]) -> dict:
    return {"audio": audio_config, "candidates": candidates}


def _child(command: str, payload: dict) -> list[str]:
    return [sys.executable, "-m", "tatp.devices", command, json.dumps(payload)]


class ProbeError(RuntimeError):
    """The child that lists the sound devices failed, or did not answer in time."""


def probe_in_child(request: dict, timeout_s: float) -> dict:
    """`probe`, in a child process of its own, so this one never loads PortAudio. Waits at most
    `timeout_s`. A child that fails or does not answer raises `ProbeError`, saying what it said:
    there is no list to fall back on."""
    try:
        done = subprocess.run(_child(PROBE, request), cwd=REPO_ROOT, capture_output=True,
                              text=True, timeout=timeout_s, check=True)
    except subprocess.TimeoutExpired as error:
        raise ProbeError(f"PortAudio did not list the sound devices within {timeout_s:g} s"
                         ) from error
    except subprocess.CalledProcessError as error:
        lines = error.stderr.strip().splitlines()
        raise ProbeError(lines[-1] if lines else f"exit code {error.returncode}") from error
    return json.loads(done.stdout)


def probe_command(request: dict) -> tuple[str, list[str]]:
    """The program and arguments for a probe run another way (the page's, without waiting)."""
    program, *arguments = _child(PROBE, request)
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
                # Only now is it playing: the page shows it running from this line.
                print(STARTED, flush=True)
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


# In `hardware_changed` beside the choices: the remote read from every keyboard where the lab
# tells it apart (off Windows), which a study participant may not run with.
KEY_SOURCE_CHANGE = "key_source"
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


SCREEN_NAMES = ("participant_screen_index", "experimenter_screen_index")
# Each sound-device choice, by the role `tatp.audio` names it.
AUDIO_ROLES = {"participant_audio_device": "participant",
               "experimenter_audio_device": "experimenter"}


class Present(NamedTuple):
    """What is connected now. `remote` is None where it cannot be told from a keyboard.
    `outputs` is None until the sound devices have been listed (or when nothing plays through
    them); `checks` is the probe's, by role and `check_key`."""

    screens: list[tuple[int, int]]
    ports: list[str]
    remote: bool | None
    outputs: list[str] | None = None
    default_output: str | None = None
    checks: dict = {}
    audio_error: str = ""


def usable(present: Present, role: str, spec: str | None) -> bool | None:
    """Whether the probe found `spec` can be opened for `role`; None when it was not asked."""
    why = present.checks.get(role, {}).get(check_key(spec))
    return None if why is None else why == ""


def candidates(hardware: dict, choices: HardwareChoices) -> dict[str, list[str | None]]:
    """The devices a probe checks for each role: the lab's, the one chosen, and the default."""
    lab = configured(hardware)
    return {role: list(dict.fromkeys([getattr(lab, name), getattr(choices, name), None]))
            for name, role in AUDIO_ROLES.items()}


def automatic(name: str, hardware: dict, present: Present) -> object:
    """What a choice is while nobody has changed it by hand: the lab's while it is there, and
    what stands in for it while it is not."""
    lab = getattr(configured(hardware), name)
    if name in SCREEN_NAMES:
        return lab if lab is not None and lab < len(present.screens) else None
    if name in AUDIO_ROLES:
        # Off the lab's platform its devices cannot exist; on it, a missing one is shown
        # missing, for someone to connect, rather than quietly replaced by the speakers.
        if present.outputs is None or usable(present, AUDIO_ROLES[name], lab):
            return lab
        return lab if on_lab_platform(hardware) else None
    if name == "participant_input":
        # In the lab a missing remote is shown missing, to be plugged in: standing the keyboard
        # in for it would leave the participant holding an R400 whose buttons do nothing
        # (spec review). Elsewhere it cannot be seen at all, and the keyboard stands in.
        if present.remote or on_lab_platform(hardware):
            return REMOTE
        return KEYBOARD
    return lab


def settle(choices: HardwareChoices, hardware: dict, present: Present) -> HardwareChoices:
    """`choices` against what is connected now: what was chosen by hand stays as chosen, and
    every other choice is worked out again (docs/LOG.md N7.F12e1). The launcher does this at
    every session start, so a monitor or the remote connected after the page closed is used."""
    values = {name: getattr(choices, name) if name in choices.chosen
              else automatic(name, hardware, present) for name in CHOICE_NAMES}
    return HardwareChoices(**values, chosen=choices.chosen)


def main(argv: list[str]) -> int:
    command, payload = argv
    payload = json.loads(payload)
    import sounddevice

    if command == PROBE:
        print(json.dumps(probe(payload, sounddevice)))
    elif command == SERVE:
        serve(payload, sys.stdin, sounddevice)
    else:
        raise SystemExit(f"tatp.devices: {command!r} is not one of {PROBE}, {SERVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
