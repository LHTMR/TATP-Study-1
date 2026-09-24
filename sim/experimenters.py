"""The virtual experimenter. SPEC.md 17.3, 17.5.

The normal experimenter runs a whole session from the experimenter screen, and only from it:

- **It applies what the screen asks for, once per warning cue.** At each cue it reads the
  instruction, parses it against the `apply_filament` or `apply_brush` wording it was formatted
  from, and touches the virtual participant: the filament's force -- the weighed one where the
  set has been weighed, since that is what the filament presses with -- or the brush. Reading
  the screen rather than the protocol is the point: a prompt that named the wrong filament
  would be applied wrongly here, as it would be in the lab. The cue is noticed as it goes up
  (`warning_cue_shown`), not by looking now and then: at the validator's speed a cue is on
  screen for well under a millisecond.
- **It presses Start block whenever the screen says the software is waiting for it** -- the
  garment fitted, the thermode started, the capsaicin, the next block, the next mapping path,
  the rekindle -- and presses it again to stop each mapping path. The software decides when a
  press counts (SPEC.md 7.4); a press it is not waiting for is ignored, as the lab's would be.
- **It enters the four mapping distances** once a time point's four paths have run.
- **It resumes after an interruption**, through `resume_requested`, after `resume_after_s` of
  session time. The resume is the experimenter's and never a timer's (SPEC.md 10.9); this is
  the experimenter.
- It accepts a touch-calibration estimate that is put to it, re-runs one that cannot be used,
  and proceeds past an uneven or zero-gain question, so a session never waits on it.

`abort_when`, if given, is asked on every look at the screen; once it answers yes the
experimenter aborts the session with `SCENARIO_ENDED`. The validator uses it to end a scenario
whose error path is over, instead of paying for the rest of a session that proves nothing new.

**`ImplausibleDistances`** is the SPEC.md 17.5 experimenter who enters implausible mapping
distances and then leaves the last time point's unentered at session end.

It also keeps every string the experimenter window showed, for the validator's SPEC.md 16 check.
"""

from __future__ import annotations

import re
import string
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from sim.responders import TICK_S, VirtualParticipant
from tatp.procedure import Rig
from tatp.units import MS_PER_S

# Session seconds between an interruption and the experimenter's resume.
RESUME_AFTER_S = 5.0
# What the experimenter measures on each of the four paths, in mm: plausible, and unequal.
NORMAL_DISTANCES_MM = (40.0, 35.0, 45.0, 30.0)
# The reason an ended scenario's session file records.
SCENARIO_ENDED = "validator: the scenario's error path is over"
# Instructions after which the software waits for Start block.
PROCEED_INSTRUCTIONS = (
    "fit_garment", "thermode_start", "capsaicin_apply", "capsaicin_remove",
    "intervention_start", "thermode_rekindle", "ready", "touchcal_uneven", "earplugs",
)


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
        abort_when: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.rig = rig
        self.participant = participant
        self.resume_after_s = resume_after_s
        self.abort_when = abort_when
        text = rig.experimenter.text
        instructions = text["instructions"]
        self._apply = template_pattern(instructions["apply_filament"])
        self._brush = template_pattern(instructions["apply_brush"])
        self._mapping_ready = template_pattern(instructions["mapping_ready"])
        self._mapping_path = template_pattern(instructions["mapping_path"])
        self._gain_undefined = template_pattern(instructions["touchcal_gain_undefined"])
        self._proceed = {instructions[key] for key in PROCEED_INSTRUCTIONS} | {
            text["dialogs"]["distances_outstanding"]
        }
        self._accept = {instructions["touchcal_stage1_failed"],
                        instructions["touchcal_fit_review"],
                        instructions["touchcal_stage1_exhausted"]}
        self._rerun = template_pattern(instructions["touchcal_stage1_unusable"])
        self._accept_patterns = [template_pattern(t) for t in self._accept]
        self._phases = {label: key for key, label in text["phases"].items()}
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
        self.aborted = False
        self.seen_text: set[str] = set()
        self.distances_entered: dict[str, tuple] = {}
        self._mapping: tuple[str, int] | None = None  # (phase, path) being walked

        rig.interruptions.interrupted.connect(self._on_interrupted)
        rig.participant.warning_cue_shown.connect(self._on_cue)
        self._resume_timer = QTimer(self)
        self._resume_timer.setSingleShot(True)
        self._resume_timer.timeout.connect(self._resume)
        # The instruction of a trial is set just after its cue goes up, in the same call.
        self._cue_timer = QTimer(self)
        self._cue_timer.setSingleShot(True)
        self._cue_timer.setInterval(0)
        self._cue_timer.timeout.connect(self._apply_at_cue)
        self._timer = QTimer(self)
        self._timer.setInterval(int(round(TICK_S * MS_PER_S)))
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._resume_timer.stop()
        self._cue_timer.stop()

    # -- the cue ------------------------------------------------------------------------

    def _on_cue(self) -> None:
        self._cue_timer.start()

    def _apply_at_cue(self) -> None:
        instruction = self.rig.experimenter.instruction.text()
        match = self._apply.fullmatch(instruction)
        if match is not None:
            label = match["filament"]
            self.applied.append(label)
            self.participant.feel_filament(self._forces[label])
        elif self._brush.fullmatch(instruction) is not None:
            self.applied.append("brush")
            self.participant.feel_brush()

    # -- looking at the screen ------------------------------------------------------------

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

        if self.aborted:
            return
        if self.abort_when is not None and self.abort_when():
            self.aborted = True
            window.abort_requested.emit(SCENARIO_ENDED)
            return
        if self.rig.interruptions.active is not None:
            return
        instruction = window.instruction.text()
        phase = self._phases.get(window.phase.text())
        self._track_mapping(instruction, phase)
        if instruction in self._proceed or self._gain_undefined.fullmatch(instruction):
            window.proceed_requested.emit()
        elif self._mapping_ready.search(instruction):
            window.proceed_requested.emit()
        elif self._mapping_path.fullmatch(instruction):
            window.proceed_requested.emit()  # stop at the border
        elif any(p.fullmatch(instruction) for p in self._accept_patterns):
            window.fit_accepted.emit()
        elif self._rerun.fullmatch(instruction):
            window.fit_rerun_requested.emit(SCENARIO_ENDED)

    def _track_mapping(self, instruction: str, phase: str | None) -> None:
        """Enter the distances when a time point's last path has ended."""
        path = self._mapping_path.fullmatch(instruction)
        n_paths = int(self.rig.session.config.study1["mapping"]["n_paths"])
        if path is not None:
            index = self._path_index(path["path"])
            self._mapping = (phase, index)
            return
        if self._mapping is not None and self._mapping[1] == n_paths:
            walked, self._mapping = self._mapping[0], None
            self.enter_distances(walked)

    def _path_index(self, name: str) -> int:
        text = self.rig.experimenter.text["terms"]["mapping_paths"]
        ids = list(self.rig.session.config.study1["mapping"]["path_ids"])
        return next(i for i, path_id in enumerate(ids, start=1) if text[path_id] == name)

    def enter_distances(self, phase: str) -> None:
        self.distances_entered[phase] = NORMAL_DISTANCES_MM
        self.rig.experimenter.distances_entered.emit(phase, NORMAL_DISTANCES_MM)

    # -- interruptions --------------------------------------------------------------------

    def _on_interrupted(self, kind: str) -> None:
        # A child timer rather than `QTimer.singleShot`, so it dies with this object and a
        # resume can never reach a later run.
        self._resume_timer.start(self.rig.session.clock.scaled_ms(self.resume_after_s))

    def _resume(self) -> None:
        self.resumes += 1
        self.rig.experimenter.resume_requested.emit()


class ImplausibleDistances(VirtualExperimenter):
    """SPEC.md 17.5: implausible mapping distances, then the last time point left unentered.

    At the first time point it enters a zero, a negative and one longer than the arm, reads the
    query, and enters corrected values. At the second it enters nothing, so the session's end
    has to prompt for them and then close with them flagged missing.
    """

    IMPLAUSIBLE_MM = (0.0, -5.0, 900.0, 30.0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.implausible_entered: list[str] = []

    def enter_distances(self, phase: str) -> None:
        if self.implausible_entered:
            return  # the last time point: left unentered
        self.implausible_entered.append(phase)
        self.rig.experimenter.distances_entered.emit(phase, self.IMPLAUSIBLE_MM)
        super().enter_distances(phase)
