"""Emergency stop, pause and resume. SPEC.md 10.9, 11, 13.

**One owner for every interruption.** The emergency stop is the one path in the software that
must behave identically in every phase, so it is one piece of code rather than a copy in each
protocol. Whatever is running, a press of `f5` does the same four things in the same order: the
garment goes to zero first, before anything that could fail, then the event is logged with its
origin, the stop screen goes up, and whatever procedure is running is told to abandon its step.

A pause is the experimenter's interruption and follows the same path with the `paused` screen.
It also takes the garment to zero: a paused participant is waiting, not being measured, and
should not be under a stimulus they have no way to rate.

**The resume is the experimenter's, never a timer's** (SPEC.md 10.9). It restores what the
garment was doing before the interruption -- the pattern and the pressures -- preceded by the
warning cue, because every garment start is (SPEC.md 10.5). Then the procedure that was running
repeats the step it abandoned. That is what "resumption must be genuinely clean" means in
practice (SPEC.md 13): the trial in progress is lost and repeated, and nothing already collected
is touched.

Contract with procedures (`tatp/procedure.py`): `interrupted` fires once per interruption, after
the garment is at zero and the screen is up. `resumed` fires after the garment is restored. A
second stop during an interruption commands zero again and is logged, but does not fire
`interrupted` again -- nothing is running to abandon.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from tatp.session import Session, SessionError
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow

# The two kinds of interruption, as carried by `interrupted` and written to the log.
EMERGENCY_STOP = "emergency_stop"
PAUSE = "pause"
# A key in config/text/participant_*.yaml, not wording.
PAUSED_SCREEN = "paused"


class Interruptions(QObject):
    """The emergency stop, the pause and the resume, for the whole session."""

    interrupted = Signal(str)
    resumed = Signal()

    def __init__(
        self,
        session: Session,
        participant: ParticipantWindow,
        experimenter: ExperimenterWindow,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.session = session
        self.participant = participant
        self.experimenter = experimenter

        cues = session.config.study1["cues"]
        self.warning_lead_s = float(cues["warning_lead_s"])
        self.warning_duration_s = float(cues["warning_duration_s"])

        # None when nothing is interrupted, otherwise the kind currently in force.
        self.active: str | None = None
        self.emergency_stops = 0
        self._snapshot: dict | None = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._pending = None

        participant.emergency_stop.connect(self.emergency_stop)
        experimenter.pause_requested.connect(self.pause)
        experimenter.resume_requested.connect(self.resume)

    # -- interrupting ------------------------------------------------------------------

    def emergency_stop(self) -> None:
        """SPEC.md 13: immediately all channels to zero, log the press, pause, offer resume."""
        first = self.active is None
        if first:
            self._snapshot = self._garment_snapshot()
        # A stop during a resume's warning cue cancels the restore it was leading up to.
        self._cancel_pending()
        self._zero_garment()
        self.emergency_stops += 1
        self.active = EMERGENCY_STOP
        self.session.log(
            "emergency_stop",
            origin="participant",
            severity="error",
            detail="" if first else "pressed again while interrupted",
        )
        self.participant.show_emergency_stop()
        self.experimenter.refresh()
        if first:
            self.interrupted.emit(EMERGENCY_STOP)

    def pause(self) -> None:
        """The experimenter's pause. Nothing to do if something is already interrupted."""
        if self.active is not None:
            self.session.log("pause_ignored", origin="experimenter", detail=self.active)
            return
        self._snapshot = self._garment_snapshot()
        self._zero_garment()
        self.active = PAUSE
        self.session.log("paused", origin="experimenter", severity="warning")
        self.participant.show_message(PAUSED_SCREEN)
        self.experimenter.refresh()
        self.interrupted.emit(PAUSE)

    # -- resuming ----------------------------------------------------------------------

    def resume(self) -> None:
        """Restore the garment, then let the interrupted procedure repeat its step."""
        if self.active is None:
            raise SessionError("resume was requested, but nothing is interrupted")
        if self._pending is not None:
            return  # already resuming; a second press of the button changes nothing
        self.session.log("resumed", origin="experimenter", detail=self.active)
        if self._snapshot_is_running():
            # SPEC.md 10.5, 10.9: the garment start is preceded by the warning cue.
            self.participant.show_warning_cue()
            self.session.log("warning_cue", detail="before restoring the garment")
            self._after(self.warning_duration_s, self._end_cue)
        else:
            self._finish_resume()

    def _end_cue(self) -> None:
        self.participant.show_blank()
        self._after(self.warning_lead_s - self.warning_duration_s, self._restore)

    def _restore(self) -> None:
        garment = self.session.garment
        snapshot = self._snapshot
        for channel, kpa in sorted(snapshot["pressure_kpa"].items()):
            if kpa > 0:
                delivered = garment.set_pressure(channel, kpa)
                # The rate limit may shorten a restore that follows the stop too closely. It is
                # the safety envelope doing its job, so it is recorded rather than overridden.
                if delivered != kpa:
                    self.session.log(
                        "restore_rate_limited",
                        severity="warning",
                        detail=f"channel {channel}: {delivered:.1f} of {kpa:.1f} kPa",
                    )
        if snapshot["pattern_name"] is not None:
            garment.play_pattern(self.session.patterns[snapshot["pattern_name"]])
        else:
            for channel in snapshot["channels_on"]:
                garment.set_channel(channel, True)
        self.session.log("garment_restored")
        self._finish_resume()

    def _finish_resume(self) -> None:
        self._snapshot = None
        self.active = None
        self.experimenter.refresh()
        self.resumed.emit()

    # -- plumbing ----------------------------------------------------------------------

    def _garment_snapshot(self) -> dict:
        status = self.session.garment.status()
        return {
            "pressure_kpa": status["pressure_kpa"],
            "channels_on": status["channels_on"],
            "pattern_name": status["pattern_name"],
        }

    def _snapshot_is_running(self) -> bool:
        snapshot = self._snapshot
        return bool(
            snapshot
            and (
                snapshot["pattern_name"] is not None
                or snapshot["channels_on"]
                or any(kpa > 0 for kpa in snapshot["pressure_kpa"].values())
            )
        )

    def _zero_garment(self) -> None:
        # A disconnected garment is already delivering nothing, and commanding it would raise
        # on the one path that must never fail.
        if self.session.garment.connected:
            self.session.garment.stop()

    def _after(self, seconds: float, method) -> None:
        self._pending = method
        self._timer.start(self.session.clock.scaled_ms(seconds))

    def _fire(self) -> None:
        method, self._pending = self._pending, None
        method()

    def _cancel_pending(self) -> None:
        self._timer.stop()
        self._pending = None
