"""The virtual experimenter. SPEC.md 17.3, 17.5.

The normal experimenter, as much of one as the software gives an experimenter to do today. The
adversarial experimenters of SPEC.md 17.5 are for error paths -- a completed session re-entered,
the garment disconnected, the window closed -- that the launcher and the Milestone 5 controls
will create, and are not built before those exist (SPEC.md 17.3).

Two jobs:

- **It applies the filament the screen asks for, once per warning cue.** At each cue it reads
  the instruction off the experimenter window, parses it against the `apply_filament` wording
  it was formatted from, and touches the virtual participant with that filament's force -- the
  weighed one where the set has been weighed, since that is what the filament actually presses
  with, and the label force otherwise.
  Reading the screen rather than the protocol is the point: a prompt that named the wrong
  filament would be applied wrongly here, as it would be in the lab.
- **It resumes after an interruption**, through `ExperimenterWindow.resume_requested`, the
  signal Milestone 5's button will emit, after `resume_after_s` of session time. The resume is
  the experimenter's and never a timer's (SPEC.md 10.9); this is the experimenter. How quickly
  matters: the rate limit only shapes a restore that follows the stop closely, so the scenario
  that provokes it uses a quick experimenter.

It also keeps every string the experimenter window showed, for the validator's SPEC.md 16 check.
"""

from __future__ import annotations

import re
import string

from PySide6.QtCore import QObject, QTimer

from sim.responders import TICK_S, VirtualParticipant
from tatp.procedure import Rig
from tatp.units import MS_PER_S

# Session seconds between an interruption and the experimenter's resume.
RESUME_AFTER_S = 5.0


def template_pattern(template: str) -> re.Pattern:
    """A regular expression matching `template` once formatted, one named group per field."""
    parts = []
    for literal, field, _spec, _conversion in string.Formatter().parse(template):
        parts.append(re.escape(literal))
        if field is not None:
            parts.append(f"(?P<{field}>.+?)")
    return re.compile("".join(parts))


class VirtualExperimenter(QObject):
    def __init__(
        self,
        rig: Rig,
        participant: VirtualParticipant,
        resume_after_s: float = RESUME_AFTER_S,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.rig = rig
        self.participant = participant
        self.resume_after_s = resume_after_s
        self._apply = template_pattern(rig.experimenter.text["instructions"]["apply_filament"])
        self._forces = {
            filament["label_g"]: (
                filament["force_nominal_mn"]
                if filament["force_measured_mn"] is None
                else filament["force_measured_mn"]
            )
            for filament in rig.session.config.filaments["filaments"]
        }
        self.applied: list[str] = []
        self.resumes = 0
        self.seen_text: set[str] = set()
        self._on_cue = False

        rig.interruptions.interrupted.connect(self._on_interrupted)
        self._resume_timer = QTimer(self)
        self._resume_timer.setSingleShot(True)
        self._resume_timer.timeout.connect(self._resume)
        self._timer = QTimer(self)
        self._timer.setInterval(int(round(TICK_S * MS_PER_S)))
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._resume_timer.stop()

    def _tick(self) -> None:
        window = self.rig.experimenter
        # The elapsed clock is left out: it is digits, and a new string every second.
        for label in (
            window.placeholder_banner,
            window.reduced_capability_banner,
            window.identity,
            window.phase,
            window.garment,
            window.instruction,
            window.technique,
            window.status,
            window.open_items,
        ):
            if label.text():
                self.seen_text.add(label.text())

        # One application per warning cue, as in the lab: the cue says the stimulus is coming,
        # and the experimenter applies whatever the screen names at that moment. Keyed on the
        # cue rather than on the instruction changing, so a repeat of the same filament -- the
        # same trial after a stop, or the same filament twice -- is applied again.
        participant = self.rig.participant
        on_cue = participant.stack.currentWidget() is participant.cue
        if on_cue and not self._on_cue:
            match = self._apply.fullmatch(window.instruction.text())
            if match is not None:
                label = match["filament"]
                self.applied.append(label)
                self.participant.feel_filament(self._forces[label])
        self._on_cue = on_cue

    def _on_interrupted(self, kind: str) -> None:
        # A child timer rather than `QTimer.singleShot`, so it dies with this object and a
        # resume can never reach a later run.
        self._resume_timer.start(self.rig.session.clock.scaled_ms(self.resume_after_s))

    def _resume(self) -> None:
        self.resumes += 1
        self.rig.experimenter.resume_requested.emit()
