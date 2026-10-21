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
- `train_then(scales, then)` gives the VAS proportionality training still due for those scales
  (SPEC.md 10.6), one step per screen, then runs `then`.
- `blank_for(seconds, then)` is a `wait` on a blank screen; `introduce(screen, instruction,
  then)` puts up a screen the participant confirms before a new kind of task.
- `detour(make_child, then)` runs a nested procedure in place of a step an interruption has
  abandoned, then repeats that step: a re-calibration in the middle of the intervention.
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
from tatp.remote_keys import key_source
from tatp.session import Session
from tatp.trials import MessageConfirm, VasTraining, spoken_instruction
from tatp.ui.experimenter import NOW, WAIT, ExperimenterWindow
from tatp.ui.participant import STANDBY_SCREEN, ParticipantWindow, RemoteKeyRouter
from tatp.units import MS_PER_S

# `log` event names (docs/DATA_SCHEMA.md) and an experimenter text key, not wording.
VAS_TRAINING_SHOWN = "vas_training_shown"
VAS_TRAINING_EXPLAINED = "vas_training_explained"
# The suffix of an estimate's instruction once no re-runs are left (touch calibration, the F40
# preview): the same words without Re-run, which is then not offered (code review of N7.F17e).
NO_RERUNS_LEFT = "_last"
VAS_TRAINING_INSTRUCTION = "vas_training"
# The screen and the experimenter's line before the session's first practice (LOG N7.F14a).
PRACTICE_INTRO = "practice_intro"
# The `say` key of the proportionality sentences, one per trained scale.
PROPORTIONALITY = "proportionality"
# Between the scale's labels where the experimenter is told to read them out.
ANCHOR_SEPARATOR = " / "



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
        # What the participant sees while a protocol waits for the experimenter's go before it
        # starts: the rest screen, not a blank identical to the one under a stimulus (15 Oct
        # 2026 pilot review, docs/LOG.md N7.F11c8). The session runner replaces it with its
        # own, which leaves a self-start prompt still waiting for its press in place (N7.D17).
        self.show_between: Callable[[], None] = lambda: participant.show_message(STANDBY_SCREEN)
        self.interruptions = Interruptions(session, participant, experimenter, self)
        session.attach_interruptions(lambda: self.interruptions.active,
                                     lambda: self.interruptions.resuming)
        # The remote's presses reach the participant window whichever window is active. The
        # filter is a child of that window, not of the rig: Qt deletes it with the window, and a
        # deleted filter is dropped from the application. As a child of the rig it could
        # outlive the window it points at -- the rig sits in reference cycles, so its end is
        # the garbage collector's timing -- and a key event anywhere then reached a filter
        # whose window was gone (docs/LOG.md N7.I3).
        # Under raw_input the remote's presses come from its raw reports, straight to the
        # participant window, and what the log must show of the remote comes with them
        # (tatp.remote_keys): unplugged, an unknown key, Raw Input failing. Not once the session
        # has closed -- the end screen stays up while the experimenter packs away.
        def remote_event(event: str, severity: str, detail: str) -> None:
            if not session.closed:
                session.log(event, severity=severity, detail=detail)

        source = key_source(
            session.config.hardware["responder"], participant, participant.deliver_remote_key,
            remote_event,
        )
        self._remote_keys = RemoteKeyRouter(participant, source, participant)
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

        # Three presses that are not responses, so no trial hears them: a confirm on the VAS
        # before the marker is shown (docs/LOG.md N6.11), a press on a choice screen before it
        # accepts one (DATA_SCHEMA.md, `touchcal_compare`), and a play-button press carried over
        # from the screen before (N7.U15). Each is something the
        # participant did, and button events belong in the log (SPEC.md 14.2). Logged here,
        # once for every procedure, rather than in each protocol that shows those screens.
        participant.pressed_without_marker.connect(self._confirmed_without_marker)
        participant.pressed_before_accepting.connect(self._pressed_before_accepting)
        participant.confirm_carried_over.connect(self._confirm_carried_over)

        # The outermost procedure running on this rig -- the session runner in a session -- and
        # whether the closed session's last Next step is awaited (`proceed_awaited`).
        self.root: Procedure | None = None
        self.closing = False
        experimenter.set_proceed_source(self.proceed_awaited)
        # A participant awaited too long is warned of, and logged (SPEC.md 8.3: never
        # auto-advanced).
        experimenter.set_no_response_s(
            float(session.config.study1["vas"]["no_response_warning_s"]))
        experimenter.set_note_saved_s(
            float(session.config.hardware["screens"]["note_saved_shown_s"]))
        # A bound method, not a lambda holding the session (CLAUDE.md, engineering lesson 3).
        experimenter.no_response.connect(self._no_response)
        garment = session.garment
        experimenter.set_garment(
            garment.channels(), garment.limits.pressure_ceiling_kpa,
            garment.per_channel_pressure,
            float(session.config.hardware["screens"]["garment_highlight_s"]),
        )

    def proceed_awaited(self) -> bool:
        """Whether a press of Next step now would do something (S, 20 Oct 2026; docs/LOG.md
        N7.F16d): the innermost procedure waits for the go, or its trial listens for it.

        The window offers Next step only then, so a press is never silently dropped. Which
        steps wait for the go, and when, is the same in every condition: the touch start on
        the experimenter's side is a fixed display whatever the delivery does (`SessionRunner
        ._deliver`, N7.D17), which `tests/test_session_runner.py` holds by comparing the
        sequence across the three conditions (SPEC.md 16)."""
        if self.closing:
            return True
        procedure = self.root
        if procedure is None or not procedure.running:
            return False
        while procedure._child is not None:
            procedure = procedure._child
        if procedure._on_go is not None:
            return True
        return procedure._trial is not None and self._listens_for_proceed(procedure._trial)

    def _listens_for_proceed(self, trial: QObject) -> bool:
        # A pinprick or brush application says so itself (`tatp.pinprick._RatedTrial`).
        if getattr(trial, "awaits_proceed", False):
            return True
        connections = getattr(trial, "_connections", ())
        if any(signal == self.experimenter.proceed_requested for signal, _ in connections):
            return True
        children = getattr(trial, "_children", ())
        return any(self._listens_for_proceed(child) for child in children)

    def _advance(self) -> None:
        if self.session.garment.connected:
            self.session.garment.advance()

    def _no_response(self, waited_s: float) -> None:
        self.session.log("no_response", severity="warning", detail=f"{waited_s:.0f} s")

    def _confirmed_without_marker(self) -> None:
        self.session.log("confirm_without_marker", origin="participant")

    def _pressed_before_accepting(self) -> None:
        self.session.log("choice_pressed_early", origin="participant")

    def _confirm_carried_over(self) -> None:
        self.session.log("confirm_carried_over", origin="participant")


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
        if self.rig.root is None or not self.rig.root.running:
            self.rig.root = self
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

        # Once only: a procedure can be run again -- touch calibration is, to re-calibrate
        # (`detour`) -- and its finishing then is not this run's.
        def done(result: object) -> None:
            child.finished.disconnect(done)
            self._child_done(child, result, on_done)

        child.finished.connect(done)
        child.start()

    def detour(
        self,
        make_child: Callable[[], Procedure],
        then: Callable[[object, Callable[[], None]], None],
    ) -> None:
        """Run a procedure in place of the step an interruption has just abandoned: the
        re-calibration during the intervention (docs/LOG.md N7.F12a1), in whichever procedure
        is innermost. What this one offers the experimenter is withdrawn meanwhile
        (`suspend_offers`). Then `then(result, go_on)`, where `go_on()` gives the offers back
        and runs the abandoned step again, as a resume would have, now or after a step of
        its own."""
        step = self._step
        self.suspend_offers()
        # A go the abandoned step waited for is its own again only when it repeats: a press
        # before then -- during the detour, or a step `then` runs first -- starts nothing.
        self.on_proceed(None)

        def go_on() -> None:
            self.restore_offers()
            self._step = step
            if step is not None:
                step()

        self.run_child(make_child, lambda result: then(result, go_on))

    def suspend_offers(self) -> None:
        """Withdraw what this procedure offers the experimenter while another runs in its
        place (`detour`). Nothing, unless a procedure offers something of its own."""

    def restore_offers(self) -> None:
        """Undo `suspend_offers`, as the abandoned step comes back."""

    def train_then(self, scales, then: Callable[[], None]) -> None:
        """The proportionality training for each of `scales` still due, then `then` (10.6).

        Called by a procedure before the first stimulus of a run that rates on those scales, so
        a training screen never falls between a stimulus and its rating. Each scale is two
        steps, so an interruption repeats the one it was in:

        1. The scale alone, with no button but the stop doing anything, while the experimenter
           explains the anchors and proportionality aloud (Bilaga 1 3.6.1, 3.9), from
           `say.proportionality` in the participant's language; their go is logged
           `vas_training_explained`.
        2. `VasTraining`: a practice rating, never recorded as a rating.

        Once confirmed it is not shown again this session (`Session.vas_training_due`). The
        session's first practice is introduced first (`screens.practice_intro`): the welcome no
        longer explains the buttons and the scale, since no scale is on the screen there.
        """
        due = [scale for scale in dict.fromkeys(scales) if self.session.vas_training_due(scale)]
        if not due:
            then()
            return
        if not self.session.vas_trained:
            self.introduce(PRACTICE_INTRO, self.instruction_text(PRACTICE_INTRO),
                           lambda: self._train(due, then))
            return
        self._train(due, then)

    def _train(self, due: list[str], then: Callable[[], None]) -> None:
        scale = due[0]

        def show() -> None:
            self.participant.show_vas_training(scale, accepting=False)
            # The proportionality sentence is the experimenter's to say, not the participant's
            # to read (S's lab-run list, 5 Oct 2026). The experimenter cannot see the
            # participant's screen, so the labels to read out are given too. Both are said to
            # the participant, so both are in the participant's language.
            config = self.session.config
            anchors = sorted(config.participant_text["vas"][scale]["anchors"],
                             key=lambda anchor: anchor["pct"])
            self.experimenter.set_instruction(self.instruction_text(
                VAS_TRAINING_INSTRUCTION,
                anchors=ANCHOR_SEPARATOR.join(anchor["label"] for anchor in anchors),
                explanation=config.say[PROPORTIONALITY][scale],
            ), NOW)
            self.experimenter.set_status("")
            self.experimenter.refresh()
            self.session.log(VAS_TRAINING_SHOWN, detail=scale)

        def explained() -> None:
            self.session.log(VAS_TRAINING_EXPLAINED, origin="experimenter", detail=scale)
            self.run_trial(
                lambda: VasTraining(self.session, self.participant, self.experimenter, scale),
                lambda _: self.train_then(due[1:], then),
            )

        self.await_proceed(explained, show)

    def instruct(self, key: str, heading: str, wait_s: float | None = None,
                 **values: object) -> None:
        """What the experimenter should do now (SPEC.md 11), filled by `config.instruction`,
        under `heading` (`tatp.ui.experimenter.HEADINGS`) and, for a wait, its time left."""
        self.experimenter.set_instruction(self.instruction_text(key, **values), heading,
                                          wait_s)
        self.experimenter.refresh()

    def instruction_text(self, key: str, **values: object) -> str:
        """`instructions.<key>`, filled. One with a sentence to say aloud silences the noise
        while it is up, and any other brings it back (`tatp.audio.NoiseGate`)."""
        return spoken_instruction(self.session, key, **values)

    def wait(self, seconds: float, then: Callable[[], None]) -> None:
        """Session-paced time: scaled by the clock, and restarted if interrupted."""
        self.step(lambda: self._after(seconds, then))

    def blank_for(self, seconds: float, then: Callable[[], None]) -> None:
        """A `wait` on a blank screen, the break between two ratings (UI_PRINCIPLES.md 1.10).
        The blank is part of the step, so a repeat after a resume takes the stop screen down."""

        def begin() -> None:
            self.participant.show_blank()
            self._after(seconds, then)

        self.step(begin)

    def introduce(self, screen: str, instruction: str, then: Callable[[], None]) -> None:
        """`screens.<screen>`, confirmed with ▶, before a new kind of task (docs/LOG.md
        N7.F11c1), with `instruction` on the experimenter screen meanwhile. A step of its own,
        so an interruption repeats it; called only between tasks, never between a stimulus and
        its rating."""

        def show() -> None:
            self.participant.show_message(screen)
            # The participant is reading: nothing for the experimenter to do but wait.
            self.experimenter.set_instruction(instruction, WAIT)
            self.experimenter.set_status("")
            self.experimenter.refresh()

        self.run_trial(
            lambda: MessageConfirm(self.session, self.participant, self.experimenter, show,
                                   screen),
            lambda _: then(),
        )

    @property
    def awaiting_go(self) -> bool:
        """Whether this procedure is waiting for the experimenter's go (`await_proceed`)."""
        return self._on_go is not None

    def await_proceed(
        self, then: Callable[[], None], prepare: Callable[[], None] | None = None
    ) -> None:
        """A step that waits for the experimenter to say go (SPEC.md 7.4, 8.3).

        `prepare` puts the screens into the state the wait needs -- the instruction, the
        participant's standby -- and runs again when an interrupted wait is resumed, so a
        resume never leaves the participant looking at the stop screen.
        """

        def begin() -> None:
            # Whatever the status said belongs to the step before: a wait for the go is a new
            # step, and "Response received" left up reads as this one's (LOG N7.F16c).
            self.experimenter.set_status("")
            if prepare is not None:
                prepare()
            self._on_go = then
            # Next step is offered from now (`Rig.proceed_awaited`), not at the next tick.
            self.experimenter.refresh()

        self.step(begin)

    def on_proceed(self, then: Callable[[], None] | None) -> None:
        """What the experimenter's next go does, outside a waiting step; None for nothing."""
        self._on_go = then
        self.experimenter.refresh()

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
