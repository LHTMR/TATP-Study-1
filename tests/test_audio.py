"""White noise, cues and alerts. SPEC.md 10.5, 10.7.

Everything runs against `RecordingOutput`, the test double, which is what lets `make check`
pass with no audio device (SPEC.md 17.1). The real output is never built here.
"""

from __future__ import annotations

import numpy as np
import pytest

from tatp import audio as audio_module
from tatp import config as cfg
from tatp.audio import Audio, AudioError, RecordingOutput, amplitude, tone
from tatp.clock import Clock


@pytest.fixture(scope="module")
def audio_config():
    return {**cfg.load("sv", "en").hardware["audio"], "backend": "recording"}


@pytest.fixture
def logged():
    return []


@pytest.fixture
def audio(audio_config, logged):
    def log(event, **fields):
        logged.append((event, fields))

    return Audio(audio_config, Clock(), log)


def _events(audio):
    return [event[0] for event in audio.output.events]


def test_levels_are_rms_dbfs():
    samples = tone(1000.0, 1.0, -20.0, 0.0, 44100)
    rms = np.sqrt(np.mean(samples**2))
    assert rms == pytest.approx(amplitude(-20.0), rel=1e-3)
    assert amplitude(0.0) == 1.0


def test_a_tone_has_no_click_at_either_end():
    samples = tone(1000.0, 0.2, -20.0, 0.01, 44100)
    assert abs(samples[0]) < 1e-9 and abs(samples[-1]) < 1e-3


def test_the_noise_never_exceeds_the_ceiling(audio, logged):
    """SPEC.md 10.7: white_noise_max_dbfs is a hard ceiling, enforced in one place."""
    audio.start_noise(audio.start_dbfs)
    applied = audio.set_noise_level(audio.max_dbfs + 20.0)
    assert applied == audio.max_dbfs
    assert audio.at_ceiling
    assert audio.output.events[-1] == ("set_noise", amplitude(audio.max_dbfs))
    assert any(event == "white_noise_ceiling" for event, _ in logged)


def test_the_start_level_is_clamped_too(audio):
    audio.start_noise(audio.max_dbfs + 5.0)
    assert audio.output.events[-1] == ("start_noise", amplitude(audio.max_dbfs))


def test_the_cue_is_the_configured_margin_over_the_noise(audio, audio_config, logged):
    audio.start_noise(-40.0)
    audio.participant_cue()
    kind, samples = audio.output.events[-1]
    assert kind == "participant_tone"
    expected = -40.0 + audio_config["participant_cue_over_noise_db"]
    rms_db = 20 * np.log10(np.sqrt(np.mean(samples**2)))
    # The onset and offset ramps take a little off the RMS; the margin is what matters.
    assert rms_db == pytest.approx(expected, abs=0.5)
    assert logged[-1][0] == "participant_cue_tone", "every cue onset is timestamped"


def test_the_cue_never_clips_and_says_when_its_margin_shrank(audio, logged):
    audio.start_noise(audio.max_dbfs)
    audio.participant_cue()
    _, samples = audio.output.events[-1]
    assert np.max(np.abs(samples)) <= 1.0 + 1e-9, "peak at or under full scale"
    reduced = [fields for event, fields in logged if event == "participant_cue_margin_reduced"]
    assert reduced, "the shortfall is logged"
    played = [fields for event, fields in logged if event == "participant_cue_tone"][-1]
    assert played["detail"] == f"{audio_module.CUE_MAX_DBFS:.1f} dBFS"


def test_no_cue_sounds_without_the_noise_it_is_set_against(audio):
    audio.participant_cue()
    assert _events(audio) == []
    audio.start_noise(-40.0)
    audio.stop_noise("mapping")
    audio.participant_cue()
    assert "participant_tone" not in _events(audio)


def test_stop_and_resume_are_logged_and_keep_the_level(audio, logged):
    audio.start_noise(-35.0)
    audio.stop_noise("mapping")
    audio.resume_noise("mapping over")
    names = [event for event, _ in logged]
    assert names[-2:] == ["white_noise_stopped", "white_noise_resumed"]
    assert audio.output.events[-1] == ("start_noise", amplitude(-35.0))
    assert audio.noise_running


def test_nothing_resumes_that_never_started(audio):
    with pytest.raises(AudioError, match="no level"):
        audio.resume_noise("too early")


def test_the_experimenter_alert_goes_to_the_lab_side_output(audio, logged):
    audio.experimenter_alert("block due")
    assert _events(audio) == ["experimenter_tone"]
    assert logged[-1] == ("experimenter_alert", {"detail": "block due"})


def test_an_unknown_backend_is_refused(audio_config):
    with pytest.raises(AudioError, match="backend"):
        Audio({**audio_config, "backend": "speakers"}, Clock(), lambda *a, **k: None)


def test_the_real_output_is_not_built_until_something_plays(audio_config, monkeypatch):
    """Building a session must not touch PortAudio (SPEC.md 17.1, headless)."""
    built = []

    class Refusing(RecordingOutput):
        def __init__(self, config):
            built.append(config)
            super().__init__(config)

    monkeypatch.setitem(audio_module.BACKENDS, "sounddevice", Refusing)
    made = Audio({**audio_config, "backend": "sounddevice"}, Clock(), lambda *a, **k: None)
    made.participant_cue()
    assert built == []
    made.start_noise(-40.0)
    assert len(built) == 1


# -- the noise gate and the tick (S, 21 Oct 2026; docs/LOG.md N7.F18j) ----------------------


def test_silenced_noise_keeps_its_stream_so_the_cue_still_sounds(audio, logged):
    audio.start_noise(-35.0)
    audio.silence_noise("not needed")
    assert audio.output.events[-1] == ("set_noise", 0.0)
    assert audio.noise_running and audio.noise_silenced
    audio.participant_cue()
    assert _events(audio)[-1] == "participant_tone", "the cue at its usual level"
    audio.set_noise_level(-30.0)
    assert audio.output.events[-1][0] == "participant_tone", "silent until let back"
    audio.unsilence_noise("needed")
    assert audio.output.events[-1] == ("set_noise", amplitude(-30.0))
    names = [event for event, _ in logged if event.startswith("white_noise")]
    assert names[-2:] == ["white_noise_silenced", "white_noise_resumed"]


def test_the_gate_follows_the_garment_and_what_is_said(audio):
    gate = audio_module.NoiseGate(audio)
    gate.want(True, "calibration")
    gate.say(True)
    assert audio.output.events == [], "nothing before the masking check sets a level"
    audio.start_noise(-35.0)
    gate.arm()
    assert audio.noise_silenced, "said aloud"
    gate.say(False)
    assert not audio.noise_silenced, "the garment may run"
    gate.want(False, "calibration done")
    assert audio.noise_silenced
    gate.want(True, "the touch")
    assert not audio.noise_silenced


def test_the_tick_is_a_click_no_louder_than_the_alert(audio_config):
    """S, 21 Oct 2026: "more like a tick and less like an alert": a sharp start, gone within
    a few ms, its peak no higher than the alert's."""
    rate = int(audio_config["sample_rate_hz"])
    level = float(audio_config["experimenter_alert_level_dbfs"])
    samples = audio_module.click(float(audio_config["pacing_tick_hz"]),
                                 float(audio_config["pacing_tick_duration_s"]),
                                 float(audio_config["pacing_tick_decay_s"]), level, rate)
    peak = amplitude(level) * np.sqrt(2)
    assert np.max(np.abs(samples)) <= peak
    onset = int(rate / float(audio_config["pacing_tick_hz"]))
    assert np.max(np.abs(samples[:onset])) > peak / 2, "it starts at once"
    assert np.max(np.abs(samples[-onset:])) < peak / 100, "and has died away by its end"
    assert len(samples) / rate < float(audio_config["experimenter_alert_duration_s"]) / 10
