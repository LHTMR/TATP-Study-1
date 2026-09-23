"""White noise, the participant cue and the experimenter alerts. SPEC.md 10.5, 10.7.

**Two layers, the same split as the garment.** `Audio` owns every rule that must hold whatever
plays the sound: the hard ceiling on the noise, the cue level tracking the noise, what is
logged. An `AudioOutput` only turns levels into sound. `SounddeviceOutput` is the real one;
`RecordingOutput` is the test double, which records what it was asked to play the way
`MockGarment` records what it was commanded. `audio.backend` in `hardware.yaml` chooses between
them, and nothing falls back from one to the other: a real session whose sound device fails
raises, rather than carrying on silently with a double that plays nothing.

**The ceiling is enforced in one place**, `Audio.set_noise_level`, which every level change
goes through. It is the audio counterpart of the pressure ceiling of SPEC.md 13: the
participant's own "stop before it is uncomfortable" is what should bite first (SPEC.md 10.7
step 3), and this is what stops a held button regardless.

**Levels are RMS dBFS throughout**, so "the cue is `participant_cue_over_noise_db` above the
noise" compares like with like: a sine's RMS is its peak over the square root of two, and noise
generated at a given RMS has that RMS. Full scale is 1.0; anything louder is clipped at output.

**The cue sounds only while the noise runs.** Its level is defined relative to the noise
(SPEC.md 10.7), so before the masking check has set one, and while the noise is stopped for the
mapping or an earplug exchange, there is no level to set it at. The visual cue carries those
moments on its own. Every tone that does sound is logged with its onset (SPEC.md 10.5).

**The experimenter alert goes to its own device** (`audio.experimenter_device`), because it must
not be audible to the participant, whose headphones carry the noise (SPEC.md 10.5). Null means
the system default, which is right on a development machine and on the lab PC may well be the
participant's headphones -- which is why it is an open item.

No literals (SPEC.md 4.2): every level, frequency and duration is in `config/hardware.yaml`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

import numpy as np

from tatp.clock import Clock
from tatp.units import DB_PER_AMPLITUDE_DECADE, DECADE


class AudioError(Exception):
    """The configured audio output cannot do what was asked. Never worked around."""


def amplitude(level_dbfs: float) -> float:
    """RMS amplitude, as a fraction of full scale, for a level in dBFS."""
    return float(DECADE ** (level_dbfs / DB_PER_AMPLITUDE_DECADE))


def tone(hz: float, duration_s: float, level_dbfs: float, ramp_s: float,
         sample_rate_hz: int) -> np.ndarray:
    """A sine at `level_dbfs` RMS, with raised-cosine onset and offset ramps.

    The ramps are what stop a tone starting with a click. A click is a second, louder cue the
    configuration never asked for.
    """
    n = int(round(duration_s * sample_rate_hz))
    t = np.arange(n) / sample_rate_hz
    peak = amplitude(level_dbfs) * np.sqrt(2)
    samples = peak * np.sin(2 * np.pi * hz * t)
    n_ramp = min(int(round(ramp_s * sample_rate_hz)), n // 2)
    if n_ramp > 0:
        envelope = (1 - np.cos(np.pi * np.arange(n_ramp) / n_ramp)) / 2
        samples[:n_ramp] *= envelope
        samples[n - n_ramp:] *= envelope[::-1]
    return samples


# -- outputs ----------------------------------------------------------------------------


class AudioOutput(ABC):
    """Turns levels into sound. Knows no rule; `Audio` has already applied them."""

    @abstractmethod
    def start_noise(self, rms: float) -> None: ...

    @abstractmethod
    def set_noise(self, rms: float) -> None: ...

    @abstractmethod
    def stop_noise(self) -> None: ...

    @abstractmethod
    def participant_tone(self, samples: np.ndarray) -> None:
        """Mixed over the noise, into the participant's headphones."""

    @abstractmethod
    def experimenter_tone(self, samples: np.ndarray) -> None:
        """On the lab-side device, never the participant's."""


class RecordingOutput(AudioOutput):
    """The test double. Plays nothing and records everything, like `MockGarment`."""

    def __init__(self, audio_config: dict):
        self.sample_rate_hz = int(audio_config["sample_rate_hz"])
        self.events: list[tuple] = []

    def start_noise(self, rms: float) -> None:
        self.events.append(("start_noise", rms))

    def set_noise(self, rms: float) -> None:
        self.events.append(("set_noise", rms))

    def stop_noise(self) -> None:
        self.events.append(("stop_noise",))

    def participant_tone(self, samples: np.ndarray) -> None:
        self.events.append(("participant_tone", samples))

    def experimenter_tone(self, samples: np.ndarray) -> None:
        self.events.append(("experimenter_tone", samples))


class SounddeviceOutput(AudioOutput):
    """The real output, through `sounddevice`. The noise is generated, never a file (SPEC.md 3).

    The noise is produced in the stream's callback, block by block, with the cue added into the
    same blocks -- which is what "mixed over it" means: one stream, one device, one clock, so a
    cue cannot drift against the noise it is set relative to.
    """

    def __init__(self, audio_config: dict):
        # Imported here, not at module level: PortAudio is loaded only by a session that is
        # going to play sound, so the test suite and the screenshot run never touch it.
        import sounddevice

        self._sd = sounddevice
        self.sample_rate_hz = int(audio_config["sample_rate_hz"])
        self.channels = int(audio_config["output_channels"])
        self.participant_device = audio_config["participant_device"]
        self.experimenter_device = audio_config["experimenter_device"]
        # White noise needs no reproducibility, and must not draw from the session's RNG,
        # which fixes the trial order (SPEC.md 17.2 seed reproducibility).
        self._rng = np.random.default_rng()
        self._rms = 0.0
        self._pending_tone: np.ndarray | None = None
        self._tone: np.ndarray | None = None
        self._tone_at = 0
        self._stream = None

    def start_noise(self, rms: float) -> None:
        self._rms = rms
        if self._stream is None:
            self._stream = self._sd.OutputStream(
                samplerate=self.sample_rate_hz,
                channels=self.channels,
                device=self.participant_device,
                callback=self._fill,
            )
        self._stream.start()

    def set_noise(self, rms: float) -> None:
        # A float assignment is atomic in CPython, so the callback reads either the old level
        # or the new one, never half of each.
        self._rms = rms

    def stop_noise(self) -> None:
        if self._stream is not None:
            self._stream.stop()

    def participant_tone(self, samples: np.ndarray) -> None:
        self._pending_tone = samples

    def experimenter_tone(self, samples: np.ndarray) -> None:
        self._sd.play(samples, self.sample_rate_hz, device=self.experimenter_device)

    def _fill(self, outdata, frames, time, status) -> None:  # noqa: ARG002 -- PortAudio's
        # `status` reports an underflow. Raising here would only stop the stream, silently,
        # so the next block is the most the software can do about one.
        block = self._rng.normal(0.0, self._rms, frames)
        if self._pending_tone is not None:
            self._tone, self._pending_tone = self._pending_tone, None
            self._tone_at = 0
        if self._tone is not None:
            part = self._tone[self._tone_at:self._tone_at + frames]
            block[: len(part)] += part
            self._tone_at += len(part)
            if self._tone_at >= len(self._tone):
                self._tone = None
        outdata[:] = np.clip(block, -1, 1)[:, None]


BACKENDS: dict[str, type[AudioOutput]] = {
    "sounddevice": SounddeviceOutput,
    "recording": RecordingOutput,
}


# -- the rules --------------------------------------------------------------------------


class Audio:
    """Everything the participant hears and the experimenter's alerts. One per session."""

    def __init__(self, audio_config: dict, clock: Clock, log: Callable[..., None]):
        self.config = audio_config
        self.clock = clock
        self.log = log
        backend = audio_config["backend"]
        if backend not in BACKENDS:
            raise AudioError(f"audio.backend is {backend!r}. Available: {sorted(BACKENDS)}.")
        self.backend_name = backend
        # Built lazily: constructing the real output loads PortAudio, which a session that
        # never plays a sound -- and every test that builds one -- has no need of.
        self._output: AudioOutput | None = None

        self.start_dbfs = float(audio_config["white_noise_start_dbfs"])
        self.max_dbfs = float(audio_config["white_noise_max_dbfs"])
        assert self.start_dbfs < self.max_dbfs, (
            "hardware.yaml: audio.white_noise_start_dbfs must be below white_noise_max_dbfs"
        )
        self.sample_rate_hz = int(audio_config["sample_rate_hz"])
        self.ramp_s = float(audio_config["tone_ramp_s"])

        self.noise_level_dbfs: float | None = None
        self.noise_running = False

    @property
    def output(self) -> AudioOutput:
        if self._output is None:
            self._output = BACKENDS[self.backend_name](self.config)
        return self._output

    @property
    def at_ceiling(self) -> bool:
        return self.noise_level_dbfs is not None and self.noise_level_dbfs >= self.max_dbfs

    # -- the noise ---------------------------------------------------------------------

    def set_noise_level(self, level_dbfs: float) -> float:
        """The one place the ceiling is enforced (SPEC.md 10.7). Returns the level applied."""
        applied = min(float(level_dbfs), self.max_dbfs)
        if applied < level_dbfs:
            self.log(
                "white_noise_ceiling",
                severity="warning",
                detail=f"{level_dbfs:.1f} dBFS asked, held at the ceiling {self.max_dbfs:.1f}",
            )
        self.noise_level_dbfs = applied
        if self.noise_running:
            self.output.set_noise(amplitude(applied))
        return applied

    def start_noise(self, level_dbfs: float) -> None:
        applied = self.set_noise_level(level_dbfs)
        self.output.start_noise(amplitude(applied))
        self.noise_running = True
        self.log("white_noise_started", detail=f"{applied:.1f} dBFS")

    def stop_noise(self, reason: str) -> None:
        """For the area mapping and the earplug exchange (SPEC.md 10.5, 10.7). Logged."""
        if not self.noise_running:
            return
        self.output.stop_noise()
        self.noise_running = False
        self.log("white_noise_stopped", detail=reason)

    def resume_noise(self, reason: str) -> None:
        """Back at the level the participant chose. Logged."""
        if self.noise_running:
            return
        if self.noise_level_dbfs is None:
            raise AudioError("resume_noise: no level has been set, so nothing can resume")
        self.output.start_noise(amplitude(self.noise_level_dbfs))
        self.noise_running = True
        self.log("white_noise_resumed", detail=f"{reason}, {self.noise_level_dbfs:.1f} dBFS")

    # -- tones -------------------------------------------------------------------------

    def participant_cue(self) -> None:
        """The alert tone over the noise, `participant_cue_over_noise_db` above it."""
        if not self.noise_running:
            return
        level = self.noise_level_dbfs + float(self.config["participant_cue_over_noise_db"])
        self.output.participant_tone(
            tone(
                float(self.config["participant_cue_hz"]),
                float(self.config["participant_cue_duration_s"]),
                level,
                self.ramp_s,
                self.sample_rate_hz,
            )
        )
        self.log("participant_cue_tone", detail=f"{level:.1f} dBFS")

    def experimenter_alert(self, reason: str) -> None:
        """Lab-side only (SPEC.md 10.5). Block due, rekindle approaching, masking failed."""
        self.output.experimenter_tone(
            tone(
                float(self.config["experimenter_alert_hz"]),
                float(self.config["experimenter_alert_duration_s"]),
                float(self.config["experimenter_alert_level_dbfs"]),
                self.ramp_s,
                self.sample_rate_hz,
            )
        )
        self.log("experimenter_alert", detail=reason)

    def close(self) -> None:
        if self.noise_running:
            self.stop_noise("session closed")
