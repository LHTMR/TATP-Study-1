"""The prototype garment driver. tatp/garment/arduino_mosfet.py, SPEC.md 12.1, 12.4, 13.

The serial port is a recording double, so these run headless with no sleeve attached. What is
asserted is the byte stream the firmware would receive, because that is the whole of what the
driver does.
"""

from __future__ import annotations

import csv

import pytest
import serial

from tatp import config as cfg
from tatp.clock import Clock
from tatp.garment.arduino_mosfet import ArduinoMosfetGarment
from tatp.garment.base import GarmentError, Limits

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"


class FakePort:
    """Records writes; answers the handshake as the flashed firmware does."""

    def __init__(self, port, baud, timeout, reply=b"hello\r\n"):
        self.port, self.baud, self.timeout = port, baud, timeout
        self.reply = reply
        self.lines: list[str] = []
        self.closed = False
        self.fail_writes = False

    def reset_input_buffer(self):
        pass

    def write(self, data: bytes):
        if self.fail_writes:
            raise serial.SerialException("device unplugged")
        self.lines.append(data.decode("ascii"))

    def flush(self):
        pass

    def readline(self) -> bytes:
        return self.reply

    def close(self):
        self.closed = True


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def made(loaded, monkeypatch):
    ports: list[FakePort] = []

    def factory(*args, **kwargs):
        port = FakePort(*args, **kwargs)
        ports.append(port)
        return port

    monkeypatch.setattr(ArduinoMosfetGarment, "serial_factory", staticmethod(factory))
    monkeypatch.setattr("tatp.garment.arduino_mosfet.time.sleep", lambda s: None)
    garment = ArduinoMosfetGarment(
        Limits.from_config(loaded.hardware), Clock(), hardware=loaded.hardware
    )
    return garment, ports


def _states(port: FakePort) -> list[str]:
    return [line.strip() for line in port.lines if line.startswith("setstate")]


def test_it_declares_what_the_prototype_can_do():
    """SPEC.md 12.4: on/off only, so the session runs Protocol B in timing-only mode."""
    assert ArduinoMosfetGarment.per_channel_pressure is False
    assert ArduinoMosfetGarment.n_channels == 5


def test_connect_zeroes_the_outputs_and_checks_the_handshake(made, loaded):
    garment, ports = made
    garment.connect()
    port = ports[0]
    prototype = loaded.hardware["garment"]["prototype"]
    assert (port.port, port.baud) == (prototype["port"], prototype["baud"])
    assert port.lines[0] == "setstate:0x0\n", "every output off before anything else"
    assert port.lines[1] == "hello\n"


def test_a_device_that_does_not_answer_is_refused(loaded, monkeypatch):
    monkeypatch.setattr(
        ArduinoMosfetGarment,
        "serial_factory",
        staticmethod(lambda *a, **k: FakePort(*a, **k, reply=b"")),
    )
    monkeypatch.setattr("tatp.garment.arduino_mosfet.time.sleep", lambda s: None)
    garment = ArduinoMosfetGarment(
        Limits.from_config(loaded.hardware), Clock(), hardware=loaded.hardware
    )
    with pytest.raises(GarmentError, match="did not answer"):
        garment.connect()
    assert not garment.connected


def test_channels_map_to_their_wired_bits(made, loaded):
    garment, ports = made
    garment.connect()
    bits = loaded.hardware["garment"]["prototype"]["channel_bits"]
    for channel, bit in zip(garment.channels(), bits, strict=True):
        garment.set_channel(channel, True)
        assert _states(ports[0])[-1] == f"setstate:0x{1 << bit:x}"
        garment.set_channel(channel, False)
        assert _states(ports[0])[-1] == "setstate:0x0"


def test_channels_combine_in_one_mask_in_lower_case_hex(made, loaded):
    """The firmware's parser refuses A-F, so an upper-case mask would be silently dropped."""
    garment, ports = made
    garment.connect()
    for channel in garment.channels():
        garment.set_channel(channel, True)
    bits = loaded.hardware["garment"]["prototype"]["channel_bits"]
    expected = sum(1 << bit for bit in bits)
    assert _states(ports[0])[-1] == f"setstate:0x{expected:x}"
    assert _states(ports[0])[-1] == _states(ports[0])[-1].lower()


def test_the_stop_switches_every_channel_off(made):
    """SPEC.md 13: all channels to zero, immediately."""
    garment, ports = made
    garment.connect()
    garment.set_channel(1, True)
    garment.set_channel(3, True)
    garment.stop()
    assert _states(ports[0])[-1] == "setstate:0x0"


def test_pressure_commands_nothing_on_the_wire(made):
    """The regulator sets the pressure by hand; a command would be a lie about the stimulus."""
    garment, ports = made
    garment.connect()
    before = list(ports[0].lines)
    garment.set_pressure(3, 40.0)
    assert ports[0].lines == before


def test_a_pattern_plays_through_the_bits(made, loaded):
    garment, ports = made
    garment.connect()
    from tatp.garment.patterns import load_pattern

    garment.play_pattern(load_pattern(EXAMPLES / "static_sham.csv"))
    garment.advance()
    bits = loaded.hardware["garment"]["prototype"]["channel_bits"]
    assert _states(ports[0])[-1] == f"setstate:0x{sum(1 << b for b in bits):x}"
    garment.stop_pattern()
    assert _states(ports[0])[-1] == "setstate:0x0"


def test_disconnect_zeroes_and_closes(made):
    garment, ports = made
    garment.connect()
    garment.set_channel(2, True)
    garment.disconnect()
    assert _states(ports[0])[-1] == "setstate:0x0"
    assert ports[0].closed


def test_a_failed_write_is_a_recorded_fault_not_a_silence(made):
    garment, ports = made
    garment.connect()
    ports[0].fail_writes = True
    with pytest.raises(GarmentError, match="unplugged"):
        garment.set_channel(1, True)
    assert garment.faults and "unplugged" in garment.faults[-1]
    assert ports[0].closed, "a dead port is let go, so a reconnect can open it afresh"
    # Disconnected, as the session's status, Connect button and guarded stops must see it.
    assert not garment.connected and garment.status()["channels_on"] == []
    garment.connect()
    assert len(ports) == 2 and not ports[1].closed and garment.connected


def test_a_session_whose_sleeve_is_lost_shows_it_reconnects_and_closes(
    loaded, tmp_path, monkeypatch
):
    """Re-review: with the port dropped but `connected` still true, the session showed the
    sleeve as connected, its Disconnect raised before disconnecting, and close() raised
    before the closing provenance was written."""
    from tatp.session import Session, with_session_choices

    ports: list[FakePort] = []

    def factory(*args, **kwargs):
        ports.append(FakePort(*args, **kwargs))
        return ports[-1]

    monkeypatch.setattr(ArduinoMosfetGarment, "serial_factory", staticmethod(factory))
    monkeypatch.setattr("tatp.garment.arduino_mosfet.time.sleep", lambda s: None)
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"],
                                            "folder": str(tmp_path / "data")}}
    config = with_session_choices(cfg.Config(**{**loaded.__dict__, "hardware": hardware}),
                                  garment="arduino_mosfet")
    session = Session(config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=60.0), rng_seed=7)
    session.start()
    try:
        ports[0].fail_writes = True
        with pytest.raises(GarmentError):
            session.garment.set_channel(1, True)
        assert session.experimenter_view()["garment_connected"] is False
        session.garment.connect()
        assert session.experimenter_view()["garment_connected"] is True
        ports[1].fail_writes = True
        with pytest.raises(GarmentError):
            session.garment.set_channel(2, True)
    finally:
        session.close()
    assert session.closed, "closing after a lost sleeve writes its provenance and ends"


def test_a_stop_that_finds_the_link_lost_still_completes_and_the_session_closes(
    loaded, tmp_path, monkeypatch
):
    """Re-review: the emergency stop, the pause and close() were the write that found the
    loss, and raised -- no stop screen, and a session file never finished (SPEC.md 13)."""
    from tatp.session import Session, with_session_choices

    ports: list[FakePort] = []

    def factory(*args, **kwargs):
        ports.append(FakePort(*args, **kwargs))
        return ports[-1]

    monkeypatch.setattr(ArduinoMosfetGarment, "serial_factory", staticmethod(factory))
    monkeypatch.setattr("tatp.garment.arduino_mosfet.time.sleep", lambda s: None)
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"],
                                            "folder": str(tmp_path / "data")}}
    config = with_session_choices(cfg.Config(**{**loaded.__dict__, "hardware": hardware}),
                                  garment="arduino_mosfet")
    session = Session(config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=60.0), rng_seed=7)
    session.start()
    from tatp.garment import patterns

    session.garment.play_pattern(patterns.load_pattern(EXAMPLES / "static_sham.csv"))
    session.garment.advance()
    ports[0].fail_writes = True
    session.garment.stop()  # the emergency stop's own write finds the loss, and completes
    assert not session.garment.connected
    assert session.garment.link_lost, "the screen warns the outputs may still be on"
    assert session.garment.faults[-1].startswith("serial write failed")
    session.close()
    assert session.closed
    with session.files.path("garment").open(encoding="utf-8", newline="") as table:
        events = [row["event"] for row in csv.DictReader(table)]
    after_start = events[events.index("pattern_start"):]
    # Only what happened: the fault and one disconnect, nothing claimed as sent after it.
    assert after_start[-2:] == ["fault", "disconnect"], after_start
    assert "pattern_stop" not in after_start and "stop" not in after_start
    # The session's log has them too, once each (docs/LOG.md N7.U16), so a later reconnect
    # there follows its disconnect.
    with session.files.path("log").open(encoding="utf-8", newline="") as table:
        logged = [row for row in csv.DictReader(table)
                  if row["event"] in ("garment_fault", "garment_disconnected")]
    assert [(row["event"], row["severity"]) for row in logged] == [
        ("garment_fault", "error"), ("garment_disconnected", "error")]
    assert logged[1]["detail"] == "link lost"


def test_a_connection_lost_mid_pattern_ends_the_pattern_quietly(made, loaded):
    """The session's timer keeps calling advance() after the loss: it must not raise again."""
    from tatp.garment import patterns

    garment, ports = made
    garment.connect()
    garment.play_pattern(patterns.load_pattern(EXAMPLES / "sweep_20cms.csv"))
    ports[0].fail_writes = True
    with pytest.raises(GarmentError):
        garment.advance()  # the pattern's first event is due at once
    garment.advance()
    assert not garment.connected


def test_a_connect_that_fails_after_opening_lets_the_port_go(made):
    """Pre-merge review: the designer retries a failed connect, and the session follows it."""
    garment, ports = made

    class Unplugged(FakePort):
        def write(self, data: bytes):
            raise serial.SerialException("device unplugged")

    type(garment).serial_factory = staticmethod(
        lambda *a, **k: ports.append(Unplugged(*a, **k)) or ports[-1]
    )
    with pytest.raises(GarmentError):
        garment.connect()
    assert ports[-1].closed and not garment.connected


def test_the_wiring_must_give_every_channel_its_own_bit(loaded):
    garment_config = {**loaded.hardware["garment"]}
    garment_config["prototype"] = {
        **garment_config["prototype"],
        "channel_bits": [3, 3, 7, 14, 27],
    }
    hardware = {**loaded.hardware, "garment": garment_config}
    with pytest.raises(AssertionError, match="repeats a bit"):
        ArduinoMosfetGarment(Limits.from_config(hardware), Clock(), hardware=hardware)
