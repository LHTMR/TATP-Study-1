"""Garment driver with no hardware. SPEC.md 12.1.

A first-class deliverable, not scaffolding: the whole system runs end to end against it, the
end-to-end validator drives it, and every real driver is a drop-in swap behind the same
interface. It records every command with a timestamp, enforces the same clamps -- which it gets
for free, because the clamps live in the base class -- and can inject faults.

It declares `per_channel_pressure: true`, so it stands in for the experiment garment rather than
the current prototype. `arduino_mosfet.py` is the driver that declares false (SPEC.md 12.4).
"""

from __future__ import annotations

from tatp.garment.base import GarmentController, GarmentError


class MockGarment(GarmentController):
    # Five channels at 1.5 cm spacing over a 6 cm span (SPEC.md 12.2). Declared by the class,
    # like every driver's capabilities, rather than configured or queried (SPEC.md 12.1).
    n_channels = 5
    per_channel_pressure = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Every command with the time it was issued, so a mock session can be inspected the
        # same way a real one is.
        self.commands: list[dict] = []
        self._fault_on: str | None = None
        self._fault_detail = ""

    def inject_fault(self, detail: str, on_event: str = "set_pressure") -> None:
        """Make the next command of this kind fail, as a device fault would."""
        self._fault_on = on_event
        self._fault_detail = detail

    def _device(self, event: str) -> None:
        self.commands.append({"t_s": self.clock.elapsed_s(), "event": event})
        if self._fault_on == event:
            self._fault_on = None
            self.fault(self._fault_detail)
            raise GarmentError(f"{self.driver_name}: {self._fault_detail}")

    def _connect(self) -> None:
        self._device("connect")

    def _disconnect(self) -> None:
        self._device("disconnect")

    def _set_pressure(self, channel: int, kpa: float) -> None:
        self._device("set_pressure")

    def _set_channel(self, channel: int, on: bool) -> None:
        self._device("channel_on" if on else "channel_off")

    def _stop(self) -> None:
        self._device("stop")
