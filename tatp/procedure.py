"""The shape every protocol takes. SPEC.md 8, 9, 10.7, 10.9, 13.

Two kinds of object run a session, and every protocol module builds on them.

**A trial** is one stimulus and one response: a `PinprickTrial`, an `Adjustment`, a
`TouchRating`. It has `start()`, `cancel()` and a `finished` signal carrying its result. It
knows nothing about interruptions: when one happens, whatever is running it calls `cancel()`,
which tears it down silently and writes no row -- there is no response to write.

**A procedure** is a sequence of steps: the long protocol, the estimation run, the masking
check, and in the end the session itself. It subclasses `Procedure`, which supplies the part
that must be identical everywhere -- what an interruption does to a sequence:

- `step(begin)` runs `begin` and remembers it as the step to repeat.
- `run_trial(make_trial, on_done)` is a step that builds a fresh trial and runs it. The trial
  is built by `make_trial` each time, so a repeat after an interruption is a new trial with the
  same plan rather than a half-used one.
- `run_child(make_child, on_done)` runs a nested procedure. While a child is running the parent
  ignores interruptions, because **only the innermost procedure handles one** -- a parent that
  restarted on resume would throw away everything its child had already done.
- `wait(seconds, then)` is session-paced time, scaled by the clock. A wait is a step too, so an
  interruption during an inter-stimulus interval restarts the interval.
- `await_proceed(then, prepare)` is a step that waits for the experimenter's
  `proceed_requested`, the one way every procedure is launched (SPEC.md 7.4).
- `finish(result)` ends the procedure and emits `finished(result)`.

On `Interruptions.interrupted` the innermost procedure cancels its trial and its timer. On
`resumed` it runs the remembered step again. A subclass never handles the emergency stop itself;
one that must, like the stop rehearsal, overrides `on_interrupted` and `on_resumed`.

`finished` is emitted only on completion. The abort path is `cancel()`, which emits nothing: an
aborted procedure has no result, and the caller that aborted it already knows.

**Results are frozen dataclasses** defined in the protocol's own module, carrying what a later
phase needs -- the long protocol's chosen filament, the touch calibration's pressures. What a
later phase needs to survive a crash is also in the data files, which is where resume reads it
from (SPEC.md 15); the result is the in-process handoff, not the record.

**`Rig`** is what a running session is made of: the session, both windows, the interruptions,
and the timer that plays garment patterns. Every procedure takes one, so a new procedure never
needs its own copy of the wiring.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

from tatp.interruption import Interruptions
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow, RemoteKeyRouter
from tatp.units import MS_PER_S


class Rig(QObject):
    """The session, both windows, the interruptions and the pattern clock, held together."""

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
        self.interruptions = Interruptions(session, participant, experimenter, self)
        session.attach_interruptions(lambda: self.interruptions.active)
        # The remote's presses reach the participant window whichever window is active. The
        # filter is a child of that window, not of the rig: Qt deletes it with the window, and a
        # deleted filter is dropped from the application. As a child of the rig it could
        # outlive the window it points at -- the rig sits in reference cycles, so its end is
        # the garbage collector's timing -- and a key event anywhere then reached a filter
        # whose window was gone (docs/LOG.md N7.I3).
        self._remote_keys = RemoteKeyRouter(participant, participant)
        QApplication.instance().installEventFilter(self._remote_keys)
        # SPEC.md 10.5: the audible cue sounds with the visual one, from one signal, so no
        # protocol can show the one and forget the other.
        participant.warning_cue_shown.connect(session.audio.participant_cue)

        # Patterns are delivered by `GarmentController.advance()`, which has to be called; this
        # is the one caller. Real milliseconds, like the adjustment tick: it samples the clock,
        # and `advance()` itself reads the scaled time, so an accelerated session plays its
        # patterns accelerated without the tick having to know.
        interval_s = float(session.config.hardware["garment"]["pattern_tick_interval_s"])
        self._pattern_tick = QTimer(self)
        self._pattern_tick.setInterval(int(round(interval_s * MS_PER_S)))
        self._pattern_tick.timeout.connect(self._advance)
        self._pattern_tick.start()

        # Two presses that are not responses, so no trial hears them: a confirm on the VAS
        # before the marker is shown (docs/LOG.md N6.11), and a press on a choice screen before
        # it accepts one (DATA_SCHEMA.md, `touchcal_compare`). Both are something the
        # participant did, and button events belong in the log (SPEC.md 14.2). Logged here,
        # once for every procedure, rather than in each protocol that shows those screens.
        participant.pressed_without_marker.connect(self._confirmed_without_marker)
        participant.pressed_before_accepting.connect(self._pressed_before_accepting)

    def _advance(self) -> None:
        if self.session.garment.connected:
            self.session.garment.advance()

    def _confirmed_without_marker(self) -> None:
        self.session.log("confirm_without_marker", origin="participant")

    def _pressed_before_accepting(self) -> None:
        self.session.log("choice_pressed_early", origin="participant")


class Procedure(QObject):
    """A sequence of steps that survives an interruption by repeating the one it was in."""

    finished = Signal(object)

    def __init__(self, rig: Rig, parent: QObject | None = None):
        super().__init__(parent)
        self.rig = rig
        self.session = rig.session
        self.participant = rig.participant
        self.experimenter = rig.experimenter
        self.running = False

        self._step: Callable[[], None] | None = None
        self._trial: QObject | None = None
        self._child: Procedure | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        # Precise, like the trials' (tatp/pinprick.py): the intervals between applications are
        # timed against their configured length.
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._fire)
        self._pending: Callable[[], None] | None = None
        self._on_go: Callable[[], None] | None = None

    # -- lifecycle ---------------------------------------------------------------------

    def start(self) -> None:
        if self.running:
            raise RuntimeError(f"{type(self).__name__} is already running")
        self.running = True
        self.rig.interruptions.interrupted.connect(self._on_interrupted)
        self.rig.interruptions.resumed.connect(self._on_resumed)
        self.experimenter.proceed_requested.connect(self._on_proceed)
        self.connect_actions()
        self.begin()

    def begin(self) -> None:
        """The first step. Every subclass implements it."""
        raise NotImplementedError

    def connect_actions(self) -> None:
        """Connect the experimenter signals this procedure answers. Undone when it ends.

        Connected on start rather than on construction, so a procedure that is built but not
        running never answers a button meant for another.
        """

    def disconnect_actions(self) -> None:
        """Undo `connect_actions`."""

    def cancel(self) -> None:
        """Stop everything, write nothing more, emit nothing. The abort path."""
        if not self.running:
            return
        if self._child is not None:
            self._child.cancel()
            self._child = None
        self._halt()
        self._leave()

    def finish(self, result: object) -> None:
        self._halt()
        self._leave()
        self.finished.emit(result)

    # -- steps -------------------------------------------------------------------------

    def step(self, begin: Callable[[], None]) -> None:
        """Run `begin`, and run it again if an interruption abandons it."""
        self._halt()
        self._step = begin
        begin()

    def run_trial(
        self, make_trial: Callable[[], QObject], on_done: Callable[[object], None]
    ) -> None:
        """A step that runs one trial, built fresh each time it runs."""

        def begin() -> None:
            trial = make_trial()
            self._trial = trial
            trial.finished.connect(lambda result: self._trial_done(trial, result, on_done))
            trial.start()

        self.step(begin)

    def run_child(
        self, make_child: Callable[[], Procedure], on_done: Callable[[object], None]
    ) -> None:
        """Run a nested procedure. It, not this one, handles interruptions while it runs."""
        self._halt()
        self._step = None
        child = make_child()
        self._child = child
        child.finished.connect(lambda result: self._child_done(child, result, on_done))
        child.start()

    def wait(self, seconds: float, then: Callable[[], None]) -> None:
        """Session-paced time: scaled by the clock, and restarted if interrupted."""
        self.step(lambda: self._after(seconds, then))

    def await_proceed(
        self, then: Callable[[], None], prepare: Callable[[], None] | None = None
    ) -> None:
        """A step that waits for the experimenter to say go (SPEC.md 7.4, 8.3).

        `prepare` puts the screens into the state the wait needs -- the instruction, the
        participant's standby -- and runs again when an interrupted wait is resumed, so a
        resume never leaves the participant looking at the stop screen.
        """

        def begin() -> None:
            if prepare is not None:
                prepare()
            self._on_go = then

        self.step(begin)

    def on_proceed(self, then: Callable[[], None] | None) -> None:
        """What the experimenter's next go does, outside a waiting step; None for nothing."""
        self._on_go = then

    def _on_proceed(self) -> None:
        # A press while interrupted must not launch anything behind the stop screen, and one
        # while a child runs is the child's. The resume re-runs the waiting step, and the next
        # press is the one that counts.
        if (
            self._on_go is None
            or self._child is not None
            or self.rig.interruptions.active is not None
        ):
            return
        then, self._on_go = self._on_go, None
        self.session.log("proceed", origin="experimenter", detail=type(self).__name__)
        then()

    # -- interruptions ------------------------------------------------------------------

    def on_interrupted(self, kind: str) -> None:
        """Abandon the step in progress. Overridden only by a procedure that expects a stop."""
        self._halt()
        self.session.log("step_abandoned", detail=f"{type(self).__name__}, {kind}")

    def on_resumed(self) -> None:
        """Repeat the step that was abandoned."""
        self.session.log("step_repeated", detail=type(self).__name__)
        if self._step is not None:
            self._step()

    def _on_interrupted(self, kind: str) -> None:
        if self._child is None:
            self.on_interrupted(kind)

    def _on_resumed(self) -> None:
        if self._child is None:
            self.on_resumed()

    # -- plumbing ----------------------------------------------------------------------

    def _trial_done(self, trial: QObject, result: object, on_done) -> None:
        if trial is not self._trial:
            return  # a trial cancelled by an interruption cannot report late
        self._trial = None
        on_done(result)

    def _child_done(self, child: Procedure, result: object, on_done) -> None:
        if child is not self._child:
            return
        self._child = None
        on_done(result)

    def _after(self, seconds: float, method: Callable[[], None]) -> None:
        self._pending = method
        self._timer.start(self.session.clock.scaled_ms(seconds))

    def _fire(self) -> None:
        method, self._pending = self._pending, None
        method()

    def _halt(self) -> None:
        self._timer.stop()
        self._pending = None
        if self._trial is not None:
            trial, self._trial = self._trial, None
            trial.cancel()

    def _leave(self) -> None:
        self.running = False
        self._on_go = None
        self.rig.interruptions.interrupted.disconnect(self._on_interrupted)
        self.rig.interruptions.resumed.disconnect(self._on_resumed)
        self.experimenter.proceed_requested.disconnect(self._on_proceed)
        self.disconnect_actions()
