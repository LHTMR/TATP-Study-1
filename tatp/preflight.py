"""What is checked before a session starts. SPEC.md 11, 14.3, 15, 17.5.

`preflight` answers the adversarial experimenters of SPEC.md 17.5 before anything is written:

- **Refused:** a session that has already been completed; a participant code the allocation
  file does not have; a second instance while one is running from the same data folder.
- **Warned, and allowed:** session N when session N-1 has no data; initials that differ from
  the participant's earlier sessions (SPEC.md 11); a session that was started and aborted
  before. A warning is the experimenter's to read, and the deviation lands in the data.

The launcher (Stream E) shows each `Finding` by its `text_key`, a dotted path into
`config/text/experimenter_*.yaml`, with `value` filled into `{value}`.

**One instance per data folder**, enforced by an operating-system lock on a file in it rather
than by the file's existence. A lock the process holds is released by the operating system when
the process ends, however it ends -- so a crash never leaves a stale lock that would then refuse
the very resume SPEC.md 15 exists for.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

from tatp import allocation as alloc
from tatp.config import REPO_ROOT, Config
from tatp.resume import read_session_values, session_files
from tatp.session import earlier_experimenters

REFUSE = "refuse"
WARN = "warn"
LOCK_NAME = "TATP1_instance.lock"
# The lock covers one byte of the lock file: all a byte-range lock needs to exclude a second
# holder. A size, not a study parameter.
LOCK_BYTES = 1


class Finding(NamedTuple):
    """A tuple, so the launcher can unpack `(severity, text_key, value)` directly."""

    severity: str  # REFUSE or WARN
    text_key: str  # e.g. "preflight.session_completed"
    value: str


class InstanceLock:
    """Held for as long as a session runs from this data folder."""

    def __init__(self, data_folder: Path):
        self.path = data_folder / LOCK_NAME
        self._handle = None

    def acquire(self) -> bool:
        """True if taken. False if another instance holds it -- never waits for it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:  # the only way to ask the OS whether a lock is free is to try to take it
            _lock(handle)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        _unlock(self._handle)
        self._handle.close()
        self._handle = None


def _lock(handle) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, LOCK_BYTES)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, LOCK_BYTES)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def data_folder_for(config: Config) -> Path:
    folder = Path(config.hardware["data"]["folder"])
    return folder if folder.is_absolute() else REPO_ROOT / folder


def preflight(
    config: Config,
    participant_code: str,
    session_number: int,
    initials: str,
    data_folder: Path,
) -> list[Finding]:
    """Every reason not to start, or to start with a warning. Writes nothing."""
    findings: list[Finding] = []
    design = config.study1["design"]
    path = Path(design["allocation_file"])
    allocation = alloc.load(
        path if path.is_absolute() else REPO_ROOT / path,
        design["conditions"], design["limbs"], design["n_sessions"],
    )
    if session_number not in allocation.sessions_for(participant_code):
        # An unknown code has no sessions at all, so one check covers both typing errors.
        findings.append(Finding(REFUSE, "preflight.code_not_allocated", participant_code))

    for session_file in session_files(data_folder, participant_code, session_number):
        values = read_session_values(session_file)
        number = str(session_number)
        if values.get("session_end_iso") and not values.get("abort_reason"):
            findings.append(Finding(REFUSE, "preflight.session_completed", number))
            break
        if values.get("abort_reason"):
            findings.append(Finding(WARN, "preflight.session_aborted_before", number))
            break

    previous = session_number - 1
    if previous >= 1 and not session_files(data_folder, participant_code, previous):
        findings.append(Finding(WARN, "preflight.previous_session_missing", str(previous)))

    earlier = earlier_experimenters(data_folder, participant_code)
    if earlier and initials not in earlier:
        findings.append(Finding(WARN, "warnings.experimenter_changed", initials))

    probe = InstanceLock(data_folder)
    if probe.acquire():
        probe.release()
    else:
        findings.append(Finding(REFUSE, "preflight.another_instance", str(probe.path)))
    return findings


def refusals(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.severity == REFUSE]
