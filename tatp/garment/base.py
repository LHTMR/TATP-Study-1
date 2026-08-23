"""The garment controller interface. SPEC.md 12.1, 13.

The base class owns everything that must be identical across drivers -- the pressure ceiling,
the rate limit, command recording and pattern playback -- and leaves only device I/O to the
subclass. A clamp implemented per driver would be a clamp that differs per driver, and SPEC.md
13 requires the software ceiling to hold independently of what the participant does.

`capabilities()` is declared by the driver class, not queried from the device (SPEC.md 12.1).
The hardware reports nothing of the sort and each driver is written for one rig, so the driver
already knows. The bring-up checklist verifies each declaration against the actual hardware.

Deviation from the signature in SPEC.md 12.1, stated rather than hidden: `play_pattern` takes no
`params` dict. Every per-pattern parameter the spec names -- row interval, channel ids, loop --
is carried in the pattern's own sidecar (SPEC.md 12.2), and an empty dict nothing reads is the
kind of unused option CLAUDE.md forbids. Add it when something needs to go in it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from tatp.clock import Clock
from tatp.garment.patterns import ChannelEvent, Pattern, expand


class GarmentError(Exception):
    """The garment cannot do what was asked. Not caught: a silent stimulus failure is worse."""


@dataclass(frozen=True)
class Limits:
    """The software safety envelope. SPEC.md 13."""

    pressure_max_kpa: float
    pressure_ceiling_kpa: float
    pressure_rate_max_kpa_s: float

    @classmethod
    def from_config(cls, hardware: dict) -> Limits:
        garment = hardware["garment"]
        limits = cls(
            pressure_max_kpa=float(garment["pressure_max_kpa"]),
            pressure_ceiling_kpa=float(garment["pressure_ceiling_kpa"]),
            pressure_rate_max_kpa_s=float(garment["pressure_rate_max_kpa_s"]),
        )
        # Stage boundary (CLAUDE.md). S set the ceiling AT the hardware maximum on 23 Aug 2026,
        # so this permits equality: what the software guarantees is that it never commands past
        # what the hardware is rated for, not that it holds a margin below it. Above the maximum
        # is still refused -- that would be a clamp that clamps nothing (SPEC.md 13).
        assert 0 < limits.pressure_ceiling_kpa <= limits.pressure_max_kpa, (
            f"pressure_ceiling_kpa {limits.pressure_ceiling_kpa} must be above zero and no "
            f"more than the hardware maximum {limits.pressure_max_kpa} (SPEC.md 13)"
        )
        assert limits.pressure_rate_max_kpa_s > 0, "pressure_rate_max_kpa_s must be positive"
        return limits


class GarmentController(ABC):
    """Abstract garment. Subclasses implement device I/O only."""

    # Declared statically by the driver class (SPEC.md 12.1), never queried from the device.
    n_channels: int = 0
    per_channel_pressure: bool = False

    def __init__(
        self,
        limits: Limits,
        clock: Clock,
        on_command: Callable[[dict], None] | None = None,
    ):
        self.limits = limits
        self.clock = clock
        # The session supplies this to write the `garment` table. The driver does not know the
        # phase or the block, so it reports what it did and the session adds the context.
        self.on_command = on_command
        self.connected = False
        self.faults: list[str] = []
        self.pressure_kpa: dict[int, float] = {}
        self._last_command_s: dict[int, float] = {}
        self._pattern: Pattern | None = None
        self._pattern_events: tuple[ChannelEvent, ...] = ()
        self._pattern_start_s: float | None = None
        self._pattern_delivered = 0
        self._channels_on: set[int] = set()

    @property
    def driver_name(self) -> str:
        return type(self).__name__

    def capabilities(self) -> dict:
        return {
            "n_channels": self.n_channels,
            "pressure_range_kpa": (0.0, self.limits.pressure_ceiling_kpa),
            "per_channel_pressure": self.per_channel_pressure,
        }

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "pressure_kpa": dict(self.pressure_kpa),
            "channels_on": sorted(self._channels_on),
            "pattern_name": self._pattern.name if self._pattern else None,
            "faults": list(self.faults),
        }

    # -- lifecycle ---------------------------------------------------------------------

    def connect(self) -> None:
        self._connect()
        self.connected = True
        self.pressure_kpa = {channel: 0.0 for channel in self.channels()}
        self._record("connect")

    def disconnect(self) -> None:
        self._disconnect()
        self.connected = False
        self._record("disconnect")

    def channels(self) -> tuple[int, ...]:
        """Channel ids, 1-based. Pattern files address channels by these ids."""
        return tuple(range(1, self.n_channels + 1))

    # -- pressure ----------------------------------------------------------------------

    def set_pressure(self, channel: int, kpa: float) -> float:
        """Command one channel, clamped to the ceiling and the rate limit. Returns what was set.

        SPEC.md 13: the ceiling and the rate limit are enforced here, above every driver, and
        independently of the participant's adjustment. Both the request and the result are
        recorded so a clamped command is visible in the data rather than looking like a request
        that was never made.
        """
        self._require_connected()
        self._require_channel(channel)
        now = self.clock.elapsed_s()
        current = self.pressure_kpa.get(channel, 0.0)

        target = min(max(float(kpa), 0.0), self.limits.pressure_ceiling_kpa)
        # The rate limit constrains change over time, so the first command to a channel has no
        # elapsed interval to constrain and is not limited. That is the intended reading: the
        # limit exists so that holding a button cannot ramp to maximum quickly (SPEC.md 13),
        # not to slow a single deliberate command to a calibrated pressure.
        since = now - self._last_command_s.get(channel, now)
        if since > 0:
            allowed = self.limits.pressure_rate_max_kpa_s * since
            if abs(target - current) > allowed:
                target = current + allowed * (1.0 if target > current else -1.0)

        self._set_pressure(channel, target)
        self.pressure_kpa[channel] = target
        self._last_command_s[channel] = now
        self._record(
            "set_pressure",
            channel=channel,
            pressure_kpa=target,
            requested_kpa=float(kpa),
            clamped=target != float(kpa),
        )
        return target

    def stop(self) -> None:
        """All channels to zero, immediately. SPEC.md 13.

        The rate limit is deliberately not applied: it exists to stop a pressure rising quickly,
        and applying it to a stop would slow down the one command that must never be slowed.
        """
        self._stop()
        for channel in self.channels():
            self.pressure_kpa[channel] = 0.0
            self._last_command_s[channel] = self.clock.elapsed_s()
        self._channels_on.clear()
        self._pattern = None
        self._pattern_start_s = None
        self._record("stop")

    # -- patterns ----------------------------------------------------------------------

    def play_pattern(self, pattern: Pattern) -> None:
        """Start a pattern. Events are delivered by `advance()`, driven by the session timer."""
        self._require_connected()
        unknown = set(pattern.channel_ids) - set(self.channels())
        if unknown:
            raise GarmentError(
                f"pattern {pattern.name!r} addresses channels {sorted(unknown)}, but "
                f"{self.driver_name} has {self.n_channels}"
            )
        self._pattern = pattern
        self._pattern_events = expand(pattern)
        self._pattern_start_s = self.clock.elapsed_s()
        self._pattern_delivered = 0
        self._record("pattern_start", pattern_name=pattern.name)

    def advance(self) -> None:
        """Deliver every pattern event now due. Called from the session's timer.

        Looping is implemented here rather than in a driver, so every driver loops identically
        (SPEC.md 12.2). A cycle boundary is crossed by wrapping the elapsed time, so a slow tick
        never drops the events of a whole cycle.
        """
        if self._pattern is None or self._pattern_start_s is None:
            return
        elapsed = self.clock.elapsed_s() - self._pattern_start_s
        cycle = self._pattern.duration_s
        assert cycle > 0, f"pattern {self._pattern.name!r} has no duration"
        while True:
            due = [
                event
                for event in self._pattern_events[self._pattern_delivered :]
                if event.t_s <= elapsed
            ]
            for event in due:
                self._deliver(event)
            self._pattern_delivered += len(due)
            if self._pattern_delivered < len(self._pattern_events) or not self._pattern.loop:
                return
            if elapsed < cycle:
                return
            elapsed -= cycle
            self._pattern_start_s += cycle
            self._pattern_delivered = 0

    def stop_pattern(self) -> None:
        """Stop the pattern and return every channel it left on to off."""
        if self._pattern is None:
            return
        name = self._pattern.name
        for channel in sorted(self._channels_on):
            self.set_channel(channel, False)
        self._pattern = None
        self._pattern_start_s = None
        self._record("pattern_stop", pattern_name=name)

    def set_channel(self, channel: int, on: bool) -> None:
        """Turn a channel on or off. What "on" means is the driver's business (SPEC.md 12.4)."""
        self._require_connected()
        self._require_channel(channel)
        self._set_channel(channel, on)
        if on:
            self._channels_on.add(channel)
        else:
            self._channels_on.discard(channel)
        self._record(
            "channel_on" if on else "channel_off",
            channel=channel,
            pressure_kpa=self.pressure_kpa.get(channel),
        )

    def _deliver(self, event: ChannelEvent) -> None:
        self.set_channel(event.channel_id, event.on)

    # -- recording ---------------------------------------------------------------------

    def _record(self, event: str, **fields: object) -> None:
        if self.on_command is None:
            return
        self.on_command({"driver": self.driver_name, "event": event, **fields})

    def fault(self, detail: str) -> None:
        """Record a device fault. Faults are reported, never swallowed."""
        self.faults.append(detail)
        self._record("fault", detail=detail)

    def _require_connected(self) -> None:
        if not self.connected:
            raise GarmentError(f"{self.driver_name} is not connected")

    def _require_channel(self, channel: int) -> None:
        if channel not in self.channels():
            raise GarmentError(
                f"channel {channel} is not one of {list(self.channels())} on "
                f"{self.driver_name}"
            )

    # -- device I/O, implemented per driver ---------------------------------------------

    @abstractmethod
    def _connect(self) -> None: ...

    @abstractmethod
    def _disconnect(self) -> None: ...

    @abstractmethod
    def _set_pressure(self, channel: int, kpa: float) -> None: ...

    @abstractmethod
    def _set_channel(self, channel: int, on: bool) -> None: ...

    @abstractmethod
    def _stop(self) -> None: ...
