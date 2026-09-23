"""Small trials the setup and calibration procedures are built from. SPEC.md 9, 10.5, 10.7-10.9.

A trial in the sense of `tatp/procedure.py`: `start()`, `cancel()` and `finished(result)`. The
procedure running one cancels it on an interruption and, on the resume, builds a fresh one from
the same plan -- so every trial here sets up its own screen and its own garment state in
`start()`, and a repeated trial is indistinguishable from a first one.

`Trial` supplies the parts they share: a session-paced timer, the warning cue, a rate-limited
ramp to a pressure, and connections that are undone however the trial ends. A signal left
connected to a finished trial would answer the next screen's presses.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtCore import QObject, QTimer, Signal, SignalInstance

from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow


class Trial(QObject):
    """The shared machinery. A subclass implements `start()`."""

    finished = Signal(object)

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
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._pending: Callable[[], None] | None = None
        self._connections: list[tuple[SignalInstance, Callable]] = []
        self._children: list[QObject] = []
        self.ended = False

    def start(self) -> None:
        raise NotImplementedError

    # -- ending ------------------------------------------------------------------------

    def done(self, result: object) -> None:
        self._teardown()
        self.finished.emit(result)

    def cancel(self) -> None:
        """Abandoned by an interruption (SPEC.md 13). Nothing more is written."""
        if self.ended:
            return
        for child in self._children:
            child.cancel()
        self._teardown()
        self.session.log("trial_cancelled", detail=type(self).__name__)

    def _teardown(self) -> None:
        self.ended = True
        self._timer.stop()
        self._pending = None
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        self._children.clear()

    # -- plumbing ----------------------------------------------------------------------

    def listen(self, signal: SignalInstance, slot: Callable) -> None:
        """Connect for the life of this trial only."""
        signal.connect(slot)
        self._connections.append((signal, slot))

    def forget(self, signal: SignalInstance, slot: Callable) -> None:
        signal.disconnect(slot)
        self._connections.remove((signal, slot))

    def run(self, child: QObject, then: Callable[[object], None]) -> None:
        """Run a trial inside this one, cancelled with it."""
        self._children.append(child)

        def finished(result: object) -> None:
            self._children.remove(child)
            then(result)

        child.finished.connect(finished)
        child.start()

    def after(self, seconds: float, then: Callable[[], None]) -> None:
        """Session-paced time, scaled by the clock."""
        self._pending = then
        self._timer.start(self.session.clock.scaled_ms(seconds))

    def _fire(self) -> None:
        method, self._pending = self._pending, None
        method()

    def instruct(self, key: str, **values: object) -> None:
        """What the experimenter should do now (SPEC.md 11), from the experimenter text."""
        text = self.experimenter.text["instructions"][key]
        self.experimenter.set_instruction(text.format(**values) if values else text)
        self.experimenter.refresh()

    # -- the cue and the ramp ----------------------------------------------------------

    def cue_then(self, then: Callable[[], None]) -> None:
        """The warning cue that precedes every stimulus (SPEC.md 10.5), then a blank screen.

        The audible cue sounds from the window's own signal (`Rig`), so it cannot be forgotten
        here. `then` runs `warning_lead_s` after the cue's onset.
        """
        cues = self.session.config.study1["cues"]
        duration_s = float(cues["warning_duration_s"])
        lead_s = float(cues["warning_lead_s"])
        self.participant.show_warning_cue()
        self.session.log("warning_cue", detail=type(self).__name__)

        def blank() -> None:
            self.participant.show_blank()
            self.after(lead_s - duration_s, then)

        self.after(duration_s, blank)

    def ramp_then(self, levels_kpa: Mapping[int, float], then: Callable[[], None]) -> None:
        """Command each channel until the garment holds its level, then carry on.

        The rate limit (SPEC.md 13) can shorten a command to a new level, and a stimulus rated
        at a pressure it had not reached would be recorded at the wrong one. So a shortened
        command is repeated each adjustment tick until the garment holds it. A level above the
        ceiling is asked for at the ceiling, which the garment would clamp it to anyway, so
        the loop has somewhere to end.
        """
        garment = self.session.garment
        ceiling = garment.limits.pressure_ceiling_kpa
        tick_s = float(self.session.config.hardware["adjustment"]["tick_interval_s"])
        targets = {channel: min(kpa, ceiling) for channel, kpa in levels_kpa.items()}

        def attempt() -> None:
            reached = True
            for channel, kpa in sorted(targets.items()):
                if garment.pressure_kpa[channel] != kpa:
                    reached = garment.set_pressure(channel, kpa) == kpa and reached
            if reached:
                then()
            else:
                self.after(tick_s, attempt)

        attempt()


class Cue(Trial):
    """The warning cue alone, for a procedure about to start the garment itself."""

    def start(self) -> None:
        self.cue_then(lambda: self.done(None))


class Ramp(Trial):
    """Take channels to their levels, channels left as they were, and finish when held."""

    def __init__(self, session, participant, experimenter, levels_kpa: Mapping[int, float]):
        super().__init__(session, participant, experimenter)
        self.levels_kpa = dict(levels_kpa)

    def start(self) -> None:
        self.ramp_then(self.levels_kpa, lambda: self.done(None))


class Choice(Trial):
    """A two-alternative question answered by a direct press (SPEC.md 10.8).

    For a question about something already happening -- the garment is audible, the movement
    feels even -- so it accepts at once: there is no pair of stimuli to wait for. Finishes with
    the side chosen, after the screen's own feedback and gap have run.
    """

    def __init__(self, session, participant, experimenter, key: str):
        super().__init__(session, participant, experimenter)
        self.key = key
        self.side: str | None = None

    def start(self) -> None:
        self.listen(self.participant.chosen, self._chosen)
        self.participant.show_choice(self.key)
        self.participant.accept_choice()
        self.session.log("choice_shown", detail=self.key)

    def _chosen(self, side: str) -> None:
        self.side = side
        self.session.log("choice_made", origin="participant", detail=f"{self.key}: {side}")
        self.forget(self.participant.chosen, self._chosen)
        self.listen(self.participant.choice_gap_elapsed, lambda: self.done(side))


class MessageConfirm(Trial):
    """A text screen the participant dismisses with the play button ("Press ▶ to continue")."""

    def __init__(self, session, participant, experimenter, show: Callable[[], None], name: str):
        super().__init__(session, participant, experimenter)
        self.show = show
        self.name = name

    def start(self) -> None:
        self.listen(self.participant.message_confirmed, self._confirmed)
        self.show()

    def _confirmed(self) -> None:
        self.session.log("message_confirmed", origin="participant", detail=self.name)
        self.done(None)


class ExperimenterChoice(Trial):
    """Wait for one of the experimenter's actions (SPEC.md 11). Finishes with (name, args).

    `actions` maps a name to one of `ExperimenterWindow`'s signals. Milestone 5 draws the
    buttons; the virtual experimenter of SPEC.md 17.5 emits the same signals.
    """

    def __init__(
        self,
        session,
        participant,
        experimenter,
        actions: Mapping[str, SignalInstance],
        instruction: str,
        **values: object,
    ):
        super().__init__(session, participant, experimenter)
        self.actions = dict(actions)
        self.instruction = instruction
        self.values = values

    def start(self) -> None:
        for name, signal in self.actions.items():
            self.listen(signal, self._slot(name))
        self.instruct(self.instruction, **self.values)

    def _slot(self, name: str) -> Callable:
        def slot(*args: object) -> None:
            self.session.log("experimenter_action", origin="experimenter", detail=name)
            self.done((name, args))

        return slot
