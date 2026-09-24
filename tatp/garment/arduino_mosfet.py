"""The current prototype garment: a MOSFET array switching each channel on or off. SPEC.md 12.4.

What this rig can do is on/off timing, and nothing else: pressure is set by hand at the
regulator, and the software never sees it. So the driver declares `per_channel_pressure: false`
(SPEC.md 12.1), `set_pressure` commands nothing, and the session runs Protocol B in timing-only
mode with the reduced-capability banner (SPEC.md 12.4). Everything that is on/off -- pattern
playback, the schedule, the stop -- is real.

**The PC times every event.** The prototype's firmware can store and play a sequence
(`addcode` / `exec`), but it plays it once, blocks while it does, and stops on any serial input.
Instead, every change of state goes out as one `setstate:0x<mask>` the moment
`GarmentController.advance()` delivers it, so looping, interruption and the stop work exactly
as they do on the mock (docs/LOG.md N6.5).

**Channels are mapped to bits.** The rest of the software numbers channels 1-5 from distal to
proximal; the firmware addresses 32 shift-register bits. `garment.prototype.channel_bits` is the
wiring, found with `tools/garment_bits.py` (hardware.yaml).

The serial port is opened through `serial_factory`, so the tests drive a recording double in
place of the device, as `MockGarment` stands in for the whole garment.
"""

from __future__ import annotations

import time

import serial

from tatp.garment.base import GarmentController, GarmentError

# The firmware's protocol (the prototype sketch). Not study parameters: the commands the
# device understands.
HANDSHAKE = "hello"
SET_STATE = "setstate:0x{mask:x}"  # lower-case hex; the firmware's parser refuses A-F
LINE_END = "\n"
ENCODING = "ascii"


class ArduinoMosfetGarment(GarmentController):
    # Five channels, like the sleeve (SPEC.md 12.1: declared, not queried).
    n_channels = 5
    per_channel_pressure = False

    serial_factory = staticmethod(serial.Serial)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        prototype = self.hardware["garment"]["prototype"]
        self.port_name = prototype["port"]
        self.baud = int(prototype["baud"])
        self.boot_s = float(prototype["boot_s"])
        self.timeout_s = float(self.hardware["garment"]["connect_timeout_s"])
        bits = [int(bit) for bit in prototype["channel_bits"]]
        # Stage boundary (CLAUDE.md): a channel with no bit, or two channels on one bit, would
        # be a stimulus the software records but the sleeve never delivers.
        assert len(bits) == self.n_channels, (
            f"hardware.yaml: garment.prototype.channel_bits has {len(bits)} bits for "
            f"{self.n_channels} channels"
        )
        assert len(set(bits)) == len(bits), (
            f"hardware.yaml: garment.prototype.channel_bits repeats a bit: {bits}"
        )
        self.bit_for = dict(zip(self.channels(), bits, strict=True))
        self._port = None
        self._mask = 0

    # -- device I/O --------------------------------------------------------------------

    def _connect(self) -> None:
        self._port = self.serial_factory(self.port_name, self.baud, timeout=self.timeout_s)
        # Opening the port resets the Arduino; anything sent while it boots is lost.
        time.sleep(self.boot_s)
        self._port.reset_input_buffer()
        self._mask = 0
        self._write_state()
        self._send(HANDSHAKE)
        reply = self._port.readline().decode(ENCODING, errors="replace").strip()
        if reply != HANDSHAKE:
            self._port.close()
            self._port = None
            raise GarmentError(
                f"{self.port_name} did not answer {HANDSHAKE!r} (replied {reply!r}); it is not "
                f"the prototype's controller, or its firmware is older than the handshake"
            )

    def _disconnect(self) -> None:
        if self._port is None:
            return
        self._mask = 0
        self._write_state()
        self._port.close()
        self._port = None

    def _set_pressure(self, channel: int, kpa: float) -> None:
        """Nothing to command: the regulator sets the pressure by hand (SPEC.md 12.4)."""

    def _set_channel(self, channel: int, on: bool) -> None:
        bit = 1 << self.bit_for[channel]
        self._mask = (self._mask | bit) if on else (self._mask & ~bit)
        self._write_state()

    def _stop(self) -> None:
        self._mask = 0
        self._write_state()

    # -- plumbing ----------------------------------------------------------------------

    def _write_state(self) -> None:
        self._send(SET_STATE.format(mask=self._mask))

    def _send(self, command: str) -> None:
        if self._port is None:
            raise GarmentError(f"{self.driver_name}: {self.port_name} is not open")
        try:
            self._port.write(f"{command}{LINE_END}".encode(ENCODING))
            self._port.flush()
        except serial.SerialException as error:
            # Reported and raised, never swallowed: a sleeve that silently stops obeying is
            # worse than a session that stops (SPEC.md 13).
            self.fault(f"serial write failed on {self.port_name}: {error}")
            raise GarmentError(f"{self.driver_name}: {error}") from error
