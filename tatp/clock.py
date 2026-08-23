"""Session clock. SPEC.md 3, 7.4, 15.

Timing uses `time.perf_counter()` because it is monotonic: a wall clock can step backwards
over a daylight-saving change or an NTP correction, and a three-hour session spans enough time
for that to matter. Wall-clock stamps are recorded alongside, but never differenced.

Session t=0 is the start of heat sensitisation, which happens partway through the session, so
t_session_s is undefined before then rather than zero.

`speed` exists for the end-to-end validator, which runs a complete session headless with an
accelerated clock (SPEC.md 17.3). It scales elapsed time only; wall-clock stamps stay real.
"""

from __future__ import annotations

import time
from datetime import datetime

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"
FILENAME_FORMAT = "%Y-%m-%d_%H-%M-%S"


class Clock:
    def __init__(self, speed: float = 1.0):
        if speed <= 0:
            raise ValueError(f"clock speed must be positive, got {speed}")
        self.speed = speed
        self._origin = time.perf_counter()
        self._zero: float | None = None
        self.sensitisation_start_iso: str | None = None

    def elapsed_s(self) -> float:
        """Seconds since the clock was created, scaled by `speed`."""
        return (time.perf_counter() - self._origin) * self.speed

    def start_session(self) -> None:
        """Mark session t=0 -- the start of heat sensitisation (SPEC.md 7.4)."""
        if self._zero is not None:
            raise RuntimeError("session t=0 has already been set")
        self._zero = self.elapsed_s()
        self.sensitisation_start_iso = self.wall_iso()

    def resume_session(self, elapsed_at_resume_s: float) -> None:
        """Reconstruct t=0 from a recorded sensitisation start, not from process start.

        SPEC.md 15: a resumed session keeps its original t=0, so the rekindle still happens at
        the right point relative to sensitisation rather than to the restart.
        """
        self._zero = self.elapsed_s() - elapsed_at_resume_s

    @property
    def session_started(self) -> bool:
        return self._zero is not None

    def t_session_s(self) -> float | None:
        """Seconds from session t=0, or None before sensitisation begins."""
        if self._zero is None:
            return None
        return self.elapsed_s() - self._zero

    def wall_iso(self) -> str:
        """Wall clock, ISO 8601 local with milliseconds. Recorded, never differenced."""
        return datetime.now().strftime(ISO_FORMAT)[:-3]

    def filename_stamp(self) -> str:
        return datetime.now().strftime(FILENAME_FORMAT)

    def scaled_ms(self, seconds: float) -> int:
        """A duration in real milliseconds for a Qt timer, given the clock's speed."""
        return max(0, int(round(seconds * 1000.0 / self.speed)))
