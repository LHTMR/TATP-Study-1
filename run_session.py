#!/usr/bin/env python
"""Entry point. SPEC.md 4.1.

Milestone 1 runs the vertical slice from a command line: load and validate the configuration,
open both windows, run one touch adjustment and its intensity rating against the mock garment,
then one pinprick application, and close the session so the data files are complete. The
four-entry launcher of SPEC.md 4.1 is Milestone 5 -- until the auxiliary tools exist there is
nothing for three of its entries to open.

**Warn, never block.** Unresolved open items and unapproved participant wording stop this being
a session that may be run with a real participant, and both are already a banner on the
experimenter screen and a warning row in the log (SPEC.md 12.4, 20). They are printed here as
well, because someone starting the software from a terminal should see them before the windows
appear -- but they do not prevent the run, which is what makes the software pilotable while
`FOR_S.md` is still open.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp import touchcal
from tatp.clock import Clock
from tatp.pinprick import Application, PinprickTrial
from tatp.responder import Responder
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow

# The screen shown once the slice is over. A key in config/text/participant_*.yaml, not wording.
END_SCREEN = "session_end"

# The one application the slice runs. Both are indices, not study parameters (SPEC.md 4.2) --
# which filament is applied comes from `pinprick.start_filament_label_g_session1_pre_s`, and the
# site rotation that would choose the site is Milestone 3.
FIRST_TRIAL_INDEX = 1
FIRST_SITE_INDEX = 1

ABORT_EMERGENCY_STOP = "emergency stop during the slice trial"


class SliceRunner:
    """Milestone 1's whole session: one adjustment, one touch rating, one application, close.

    Milestones 3 and 4 replace this with the protocols in full and Milestone 5 with the
    schedule. It exists so that the slice is something that runs, rather than something only the
    test suite can reach -- and so that the three layers it touches (the garment, the VAS and
    the data files) are exercised together rather than one at a time.
    """

    def __init__(self, session: Session, participant: ParticipantWindow,
                 experimenter: ExperimenterWindow):
        self.session = session
        self.participant = participant
        self.experimenter = experimenter
        self.completed = False
        self.adjustment: touchcal.Adjustment | None = None
        self.rating: touchcal.TouchRating | None = None
        self.trial: PinprickTrial | None = None
        self.channel = int(session.config.study1["touch_calibration"]["reference_channel"])

    # -- the touch half ----------------------------------------------------------------

    def run(self) -> None:
        """Protocol B step 1, first anchor: adjust the reference channel (SPEC.md 9)."""
        self.session.set_phase("touch_calibration")
        self.session.garment.set_channel(self.channel, True)
        plan = touchcal.anchor_plans(self.session.config)[0]
        self.adjustment = touchcal.Adjustment(
            self.session, self.participant, self.experimenter, plan
        )
        self.adjustment.finished.connect(self._adjusted)
        self.adjustment.start()

    def _adjusted(self, produced_kpa) -> None:
        if produced_kpa is None:
            self._stopped()
            return
        self.rating = touchcal.TouchRating(
            self.session,
            self.participant,
            self.experimenter,
            touchcal.INTENSITY_SCALE,
            self.channel,
        )
        self.rating.finished.connect(self._rated)
        self.rating.start()

    def _rated(self, response) -> None:
        if response is None:
            self._stopped()
            return
        self.session.garment.stop()
        self._run_trial()

    # -- the pinprick half -------------------------------------------------------------

    def _run_trial(self) -> None:
        self.session.set_phase("pre_sensitisation")
        pinprick = self.session.config.study1["pinprick"]
        application = Application(
            protocol="short",
            region="primary",
            trial_index=FIRST_TRIAL_INDEX,
            purpose="measure",
            filament_label_g=pinprick["start_filament_label_g_session1_pre_s"],
            site_index=FIRST_SITE_INDEX,
        )
        self.trial = PinprickTrial(
            self.session, self.participant, self.experimenter, application
        )
        self.trial.finished.connect(self._finished)
        self.trial.start()

    def _finished(self, response) -> None:
        # A trial that ended in an emergency stop carries no response (SPEC.md 13). What the
        # session does next is the session's decision, and for a one-trial session that is to
        # stop and record why.
        if response is None:
            self._stopped()
            return
        self.completed = True
        self.participant.show_message(END_SCREEN)
        self._close("")

    # -- the end -----------------------------------------------------------------------

    def _stopped(self) -> None:
        """An emergency stop anywhere in the slice ends it. The stop screen is already up."""
        self._close(ABORT_EMERGENCY_STOP)

    def _close(self, abort_reason: str) -> None:
        self.experimenter.refresh()
        self.session.close(abort_reason)
        QApplication.instance().quit()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a TATP Study 1 session.")
    parser.add_argument("--participant", required=True, help="participant code, e.g. 01")
    parser.add_argument("--session", type=int, required=True, help="session number")
    parser.add_argument("--experimenter", required=True, help="experimenter initials")
    parser.add_argument(
        "--patterns",
        type=Path,
        required=True,
        help="garment pattern folder; there is no default, because defaulting to the "
        "provisional mockups in config/patterns/examples/ would substitute them silently "
        "(FOR_S A3.2)",
    )
    parser.add_argument("--participant-language", default="sv", choices=("sv", "en"))
    parser.add_argument("--experimenter-language", default="en", choices=("sv", "en"))
    parser.add_argument(
        "--clock-speed",
        type=float,
        default=1.0,
        help="accelerate every configured interval (SPEC.md 17.3). Anything but 1.0 is a "
        "development run, and is recorded in the session file.",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="RNG seed; drawn and recorded when not given"
    )
    return parser.parse_args(argv)


def warnings_for(config: cfg.Config) -> list[str]:
    """What someone starting from a terminal should read before the windows cover it."""
    lines = [f"[{item.number}] {item.summary}" for item in config.unresolved]
    if config.has_placeholder_text():
        lines.append("participant screens still contain PLACEHOLDER wording")
    return lines


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = cfg.load(args.participant_language, args.experimenter_language)
    for line in warnings_for(config):
        print(f"WARNING: {line}", file=sys.stderr)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    session = Session(
        config,
        args.participant,
        args.session,
        args.experimenter,
        args.patterns,
        clock=Clock(speed=args.clock_speed),
        rng_seed=args.seed,
    )
    session.start()

    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    experimenter = ExperimenterWindow(config.experimenter_text, session.experimenter_view)
    participant.place(config.hardware["screens"])
    participant.show()
    experimenter.show()

    runner = SliceRunner(session, participant, experimenter)
    runner.run()
    app.exec()

    # Nothing above catches an exception, so reaching here means the loop ended. The session is
    # closed by the runner; closing twice is safe and covers a window shut by hand.
    session.close()
    return 0 if runner.completed else 1


if __name__ == "__main__":
    sys.exit(main())
