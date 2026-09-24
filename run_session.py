#!/usr/bin/env python
"""Entry point. SPEC.md 4.1.

Runs one whole session (`tatp/session_runner.py`) from a command line: load and validate the
configuration, run the preflight checks, offer to resume an open session (SPEC.md 15), open
both windows and run the session to its closing screen. The launcher of SPEC.md 4.1 (Stream E)
calls the same two functions, `preflight(config, args)` and `build(config, args)`, with an
`args` shaped like `parse_args`'s.

**Warn, never block.** Unresolved open items and unapproved participant wording stop this being
a session that may be run with a real participant, and both are already a banner on the
experimenter screen and a warning row in the log (SPEC.md 12.4, 20). They are printed here as
well, because someone starting the software from a terminal should see them before the windows
appear -- but they do not prevent the run, which is what makes the software pilotable while
`config/open_items.yaml` is still open. The preflight refusals are different: a completed
session, an unallocated code and a second instance are refused (SPEC.md 17.5).
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from tatp import config as cfg
from tatp import preflight as pre
from tatp import resume as resumption
from tatp.clock import ISO_FORMAT, Clock
from tatp.procedure import Rig
from tatp.responder import Responder
from tatp.session import DRIVERS, Session, SessionError
from tatp.session_runner import SessionRunner
from tatp.ui.application import application
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.units import S_PER_MIN

# Written to the session file when the event loop ends before the session did: the window was
# closed, or the process asked to stop. Data, not wording -- it is never shown.
WINDOW_CLOSED = "the window was closed before the session ended"
# The launcher's resume offer: a preflight entry whose value is how long ago the open session
# began (SPEC.md 15). A key into the experimenter text, like every other finding.
RESUME_OFFER = "dialogs.resume_found"
# The prefix of a scheduled block's stage id (`tatp/session_runner.py`).
BLOCK_STAGE = "block"
# Exit codes, for a script that runs sessions.
EXIT_REFUSED = 2
EXIT_OPEN_SESSION = 3

ResumeDecision = Callable[[resumption.OpenSession], bool]


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
        "(open item 5)",
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
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument(
        "--resume", dest="resume", action="store_const", const=True, default=None,
        help="if this session was interrupted by a crash, resume it (SPEC.md 15)",
    )
    choice.add_argument(
        "--new", dest="resume", action="store_const", const=False,
        help="if this session was interrupted by a crash, start it again from the beginning",
    )
    return parser.parse_args(argv)


def warnings_for(config: cfg.Config) -> list[str]:
    """What someone starting from a terminal should read before the windows cover it."""
    lines = [f"[{item.number}] {item.summary}" for item in config.unresolved]
    if config.has_placeholder_text():
        lines.append("participant screens still contain PLACEHOLDER wording")
    return lines


def preflight(config: cfg.Config, args: argparse.Namespace) -> list[pre.Finding]:
    """The launcher's checks (`tatp/preflight.py`), plus the resume offer when one is due."""
    data_folder = pre.data_folder_for(config)
    findings = pre.preflight(
        config, args.participant, args.session, args.experimenter, data_folder
    )
    open_session = resumption.find_open_session(data_folder, args.participant, args.session)
    if open_session is not None:
        summary = resume_summary(config, open_session)
        findings.append(pre.Finding(pre.WARN, RESUME_OFFER, summary))
    return findings


def resume_summary(config: cfg.Config, open_session: resumption.OpenSession) -> dict:
    """The two values the resume offer shows (SPEC.md 15): what was completed, and how long
    ago sensitisation began -- both in the experimenter's language."""
    text = config.experimenter_text
    dialogs = text["dialogs"]
    stages = list(open_session.completed_stages)
    # Stages run in order, so every phase before the last one reached is finished.
    phases = []
    for stage in stages:
        phase = stage.split(".")[0]
        if phase != BLOCK_STAGE and phase not in phases:
            phases.append(phase)
    if stages and not stages[-1].startswith(BLOCK_STAGE) and phases:
        phases.pop()
    parts = [text["phases"][phase] for phase in phases if phase in text["phases"]]
    blocks = [stage.split(".")[1] for stage in stages if stage.startswith(BLOCK_STAGE + ".")]
    if blocks:
        parts.append(dialogs["resume_blocks"].format(value=", ".join(blocks)))
    started = open_session.sensitisation_start_iso
    if started is None:
        since = dialogs["resume_not_sensitised"]
    else:
        ago_s = (datetime.now() - datetime.strptime(started, ISO_FORMAT)).total_seconds()
        hours, minutes = divmod(int(ago_s // S_PER_MIN), int(S_PER_MIN))
        since = dialogs["resume_since_sensitisation"].format(value=f"{hours}:{minutes:02d}")
    return {
        "completed": ", ".join(parts) or dialogs["resume_nothing_completed"],
        "since_sensitisation": since,
    }


def build(
    config: cfg.Config,
    args: argparse.Namespace,
    resume_decision: ResumeDecision | None = None,
) -> SessionRunner:
    """Everything `main` starts, up to but not including the event loop.

    Separate so that `tools/validate_session.py` and the launcher drive the path a session takes
    rather than a copy of its wiring (SPEC.md 17.3). The QApplication must already exist; the
    runner is returned unstarted, holding the data folder's instance lock.

    Whether to resume an open session (SPEC.md 15) is `args.resume` -- True, False, or None when
    no offer was made -- unless `resume_decision` is given, which the validator's virtual
    experimenter answers. Declining starts a new session, logged; the open one's files stay as
    they are.
    """
    data_folder = pre.data_folder_for(config)
    lock = pre.InstanceLock(data_folder)
    if not lock.acquire():
        raise SessionError(f"another session is running from {data_folder} ({lock.path})")

    open_session = resumption.find_open_session(data_folder, args.participant, args.session)
    state = None
    if open_session is not None:
        resume = args.resume if resume_decision is None else resume_decision(open_session)
        if resume is None:
            lock.release()
            raise SessionError(
                f"{open_session.session_file.name} is an open session; decide whether to "
                f"resume it (SPEC.md 15) before starting"
            )
        if resume:
            driver = DRIVERS[config.hardware["garment"]["driver"]]
            state = resumption.load(open_session, config, driver.per_channel_pressure)

    session = Session(
        config,
        args.participant,
        args.session,
        args.experimenter,
        args.patterns,
        clock=Clock(speed=args.clock_speed),
        rng_seed=args.seed if state is None else state.rng_seed,
        resumed_from="" if state is None else open_session.session_file.name,
    )
    session.start(
        room_temperature_c=getattr(args, "room_temperature_c", None),
        relative_humidity_pct=getattr(args, "relative_humidity_pct", None),
    )
    if open_session is not None and state is None:
        session.log(
            "open_session_declined", origin="experimenter", severity="warning",
            detail=f"{open_session.session_file.name} left as it was; starting again",
        )

    participant = ParticipantWindow(config, Responder(config.hardware), session.clock)
    experimenter = ExperimenterWindow(
        config.experimenter_text,
        session.experimenter_view,
        refresh_interval_s=config.hardware["screens"]["experimenter_refresh_interval_s"],
    )
    participant.place(config.hardware["screens"])
    participant.show()
    experimenter.show()
    runner = SessionRunner(Rig(session, participant, experimenter), resume=state)
    runner.lock = lock
    return runner


def shut_down(runner: SessionRunner) -> None:
    """After the event loop: a session it left open was closed from outside, not completed.

    That is recorded as an abort, with the block it happened in marked aborted and any mapping
    distance still missing flagged -- every row already written stays as it is (SPEC.md 17.5).
    """
    if not runner.session.closed:
        runner.abort(WINDOW_CLOSED)
    if runner.lock is not None:
        runner.lock.release()


def experimenter_text(config: cfg.Config, dotted_key: str) -> str:
    node = config.experimenter_text
    for part in dotted_key.split("."):
        node = node[part]
    return node


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = cfg.load(args.participant_language, args.experimenter_language)
    for line in warnings_for(config):
        print(f"WARNING: {line}", file=sys.stderr)
    findings = preflight(config, args)
    for severity, text_key, value in findings:
        text = experimenter_text(config, text_key)
        values = value if isinstance(value, dict) else {"value": value}
        print(f"{severity.upper()}: {text.format_map(defaultdict(str, values))}",
              file=sys.stderr)
    if pre.refusals(findings):
        return EXIT_REFUSED
    if any(key == RESUME_OFFER for _, key, _ in findings) and args.resume is None:
        return EXIT_OPEN_SESSION  # the terminal's answer is --resume or --new

    app = application(config.hardware)
    runner = build(config, args)
    runner.start()
    app.exec()
    # Nothing above catches an exception, so reaching here means the loop ended.
    shut_down(runner)
    return 0 if runner.completed else 1


if __name__ == "__main__":
    sys.exit(main())
