"""Protocol A -- one monofilament application. SPEC.md 8, 10.5.

Milestone 1 builds a single application end to end: the visual warning cue, the prompt telling
the experimenter what to apply and where, the rating cue `rating_cue_delay_s` after the
stimulus, and one row in the `pinprick` table. The search, bracket, measurement and fixed-slope
estimate of SPEC.md 8.2 are Milestone 3 and are deliberately absent -- what to apply, where and
why is decided by the caller and carried here in an `Application`.

No literals (SPEC.md 4.2): every interval comes from `config/study1.yaml`.

**Force.** `force_applied_mn` is the *measured* force of the filament actually applied. Until
the set is weighed it is written empty, never filled in from the nominal label: manufacturer
values deviate from measured by -19.75 % to +17.61 % non-systematically (Berquin et al. 2010),
so the label is a different quantity, not an approximation of the same one. The nominal force is
written to its own column and shown to the experimenter, which is all SPEC.md 8.1 asks of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow

# The `vas` block and the `screens` key this protocol presents. Config keys, not wording.
PAIN_SCALE = "pain"
EMERGENCY_STOP_SCREEN = "emergency_stop"


@dataclass(frozen=True)
class Application:
    """One planned application. Everything the protocol decides; the trial only carries it."""

    protocol: str
    region: str
    trial_index: int
    purpose: str
    filament_size: str
    site_index: int
    # Empty means the filament asked for is the one applied. The safety rule of SPEC.md 8.2
    # lets the experimenter substitute a lower filament, and the estimator must then fit the
    # applied value -- so which one was applied is recorded, never assumed.
    applied_filament_size: str = ""


class PinprickTrial(QObject):
    """One application, driven by the clock. `finished` carries the rating, or None."""

    finished = Signal(object)

    def __init__(
        self,
        session: Session,
        participant: ParticipantWindow,
        experimenter: ExperimenterWindow,
        application: Application,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.session = session
        self.participant = participant
        self.experimenter = experimenter
        self.application = application

        cues = session.config.study1["cues"]
        self.warning_lead_s = float(cues["warning_lead_s"])
        self.warning_duration_s = float(cues["warning_duration_s"])
        self.rating_cue_delay_s = float(session.config.study1["pinprick"]["rating_cue_delay_s"])
        # Stage boundary (CLAUDE.md): the cue precedes the stimulus, so the lead cannot be
        # shorter than the cue itself. Config that says otherwise is a mistake, not a schedule.
        assert self.warning_lead_s >= self.warning_duration_s, (
            f"study1.yaml: cues.warning_lead_s ({self.warning_lead_s} s) is shorter than "
            f"cues.warning_duration_s ({self.warning_duration_s} s)"
        )

        self.cue_onset_iso = ""
        self.rating_cue_iso = ""
        self._cue_onset_t_session_s: float | None = None
        self._pending = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)

    # -- the sequence ------------------------------------------------------------------

    def start(self) -> None:
        """Show the warning cue and prompt the experimenter. SPEC.md 10.5."""
        # Everything that can fail happens before anything is shown or connected, so a trial
        # naming a filament that is not held stops here rather than half-started.
        text = self.experimenter.text
        instruction = text["instructions"]["apply_filament"].format(
            filament=self.application.filament_size,
            force_mn=self._filament(self.application.filament_size)["force_nominal_mn"],
            site=self.application.site_index,
            region=text["terms"]["regions"][self.application.region],
        )
        self.participant.confirmed.connect(self._on_confirmed)
        self.participant.emergency_stop.connect(self._on_emergency_stop)

        clock = self.session.clock
        self.cue_onset_iso = clock.wall_iso()
        self._cue_onset_t_session_s = clock.t_session_s()
        self.participant.show_warning_cue()
        self.session.log("warning_cue", detail=f"trial {self.application.trial_index}")

        self.experimenter.set_instruction(instruction)
        self.experimenter.refresh()
        self._after(self.warning_duration_s, self._end_cue)

    def _end_cue(self) -> None:
        self.participant.show_blank()
        self._after(self.warning_lead_s - self.warning_duration_s, self._stimulus_due)

    def _stimulus_due(self) -> None:
        self.session.log("stimulus_due", detail=f"filament {self.application.filament_size}")
        self._after(self.rating_cue_delay_s, self._cue_rating)

    def _cue_rating(self) -> None:
        self.rating_cue_iso = self.session.clock.wall_iso()
        self.participant.show_vas(PAIN_SCALE)
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["await_participant"]
        )
        self.experimenter.refresh()
        self.session.log("rating_cued", detail=PAIN_SCALE)

    # -- the end of the trial -----------------------------------------------------------

    def _on_confirmed(self, response) -> None:
        self._disconnect()
        self._write(response)
        self.session.log(
            "rating_confirmed",
            origin="participant",
            detail=f"rt {response.rt_s:.3f} s, first press {response.first_press_side}",
        )
        self.experimenter.set_status(
            self.experimenter.text["instructions"]["response_received"]
        )
        self.experimenter.refresh()
        self.participant.show_blank()
        self.finished.emit(response)

    def _on_emergency_stop(self) -> None:
        """SPEC.md 13. The trial stops where it is; no rating was given, so no row is written.

        The log carries the event and its timestamp, so what happened is recoverable. Deciding
        what the session as a whole does next belongs to the session, not to one trial.
        """
        self._disconnect()
        self.participant.show_message(EMERGENCY_STOP_SCREEN)
        self.session.log(
            "emergency_stop",
            origin="participant",
            severity="error",
            detail=f"during trial {self.application.trial_index}",
        )
        self.finished.emit(None)

    def _write(self, response) -> None:
        application = self.application
        applied_size = application.applied_filament_size or application.filament_size
        asked = self._filament(application.filament_size)
        applied = self._filament(applied_size)
        self.session.files.write(
            "pinprick",
            timestamp_iso=self.cue_onset_iso,
            t_session_s=self._cue_onset_t_session_s,
            phase=self.session.phase,
            block_index=self.session.block_index,
            protocol=application.protocol,
            region=application.region,
            trial_index=application.trial_index,
            purpose=application.purpose,
            filament_size=application.filament_size,
            # The nominal/measured pair describes the filament the software asked for;
            # force_applied_mn is the one actually applied, and they differ on a substitution.
            force_nominal_mn=asked["force_nominal_mn"],
            force_measured_mn=asked["force_measured_mn"],
            force_applied_mn=applied["force_measured_mn"],
            substituted=applied_size != application.filament_size,
            site_index=application.site_index,
            cue_onset_iso=self.cue_onset_iso,
            rating_cue_iso=self.rating_cue_iso,
            rating_percent=response.rating_percent,
            rt_s=response.rt_s,
            first_press_side=response.first_press_side,
            direction_changes=response.direction_changes,
            # Both are set by experimenter controls that arrive with the full protocol
            # (SPEC.md 8.2 intolerable, SPEC.md 11 discard-and-repeat).
            intolerable=False,
            discarded=False,
        )

    # -- plumbing ----------------------------------------------------------------------

    def _filament(self, size: str) -> dict:
        for filament in self.session.config.filaments["filaments"]:
            if filament["size"] == size:
                return filament
        raise KeyError(f"filaments.yaml lists no filament of size {size!r}")

    def _after(self, seconds: float, method) -> None:
        self._pending = method
        self._timer.start(self.session.clock.scaled_ms(seconds))

    def _fire(self) -> None:
        method, self._pending = self._pending, None
        method()

    def _disconnect(self) -> None:
        self._timer.stop()
        self._pending = None
        self.participant.confirmed.disconnect(self._on_confirmed)
        self.participant.emergency_stop.disconnect(self._on_emergency_stop)
