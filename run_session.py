#!/usr/bin/env python
"""Entry point. SPEC.md 4.1.

Milestone 1 runs the vertical slice from a command line: load and validate the configuration,
open both windows, run one pinprick application against the mock garment, and close the session
so the data files are complete. The four-entry launcher of SPEC.md 4.1 is Milestone 5 -- until
the auxiliary tools exist there is nothing for three of its entries to open.

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
    """Milestone 1's whole session: one application, then close.

    Milestone 3 replaces this with the protocols and Milestone 5 with the schedule. It exists so
    that the slice is something that runs, rather than something only `tests/test_pinprick.py`
    can reach.
    """

    def __init__(self, session: Session, participant: ParticipantWindow,
                 experimenter: ExperimenterWindow):
        self.session = session
        self.participant = participant
        self.experimenter = experimenter
        self.completed = False
        self.trial: PinprickTrial | None = None

    def run(self) -> None:
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
        self.completed = response is not None
        self.participant.show_message(END_SCREEN)
        self.experimenter.refresh()
        self.session.close("" if self.completed else ABORT_EMERGENCY_STOP)
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

    session.set_phase("pre_sensitisation")
    runner = SliceRunner(session, participant, experimenter)
    runner.run()
    app.exec()

    # Nothing above catches an exception, so reaching here means the loop ended. The session is
    # closed by the runner; closing twice is safe and covers a window shut by hand.
    session.close()
    return 0 if runner.completed else 1


if __name__ == "__main__":
    sys.exit(main())
