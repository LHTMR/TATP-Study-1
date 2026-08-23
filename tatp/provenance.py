"""Session provenance. SPEC.md 14.2.

Every field the session file records about how the software was built and configured, so a
data file traces to the exact interface the participant saw (SPEC.md 17.4).
"""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from tatp import __version__
from tatp.config import REPO_ROOT


def git_sha() -> tuple[str, bool]:
    """(sha, dirty). Empty sha when git is unavailable rather than a fabricated value.

    subprocess is run with check=False and the return code inspected, so there is no broad
    except here -- a git that exits non-zero is an expected outcome, not an error to swallow.
    """
    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        return "", False
    rev = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if rev.returncode != 0:
        return "", False
    status = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = bool(status.stdout.strip())
    return rev.stdout.strip() + ("-dirty" if dirty else ""), dirty


def qt_versions() -> tuple[str, str]:
    """(qt_runtime_version, pyside_version). Imported lazily so the tools that do not need
    Qt -- preview_schedule, make_allocation -- do not pay for it."""
    import PySide6
    from PySide6 import QtCore

    return QtCore.qVersion(), PySide6.__version__


def package_versions() -> str:
    """Resolved package versions, so a session records the environment it actually ran in.

    SPEC.md 3 asks for the resolved versions in each session file. importlib.metadata reports
    what is installed, which is the truth; environment.yml only says what was asked for.
    """
    from importlib.metadata import distributions

    seen = {dist.metadata["Name"]: dist.version for dist in distributions()}
    return ";".join(f"{name}={version}" for name, version in sorted(seen.items()) if name)


def screenshot_freeze_sha() -> str:
    """The git SHA recorded at the last screenshot freeze, or empty before the first."""
    marker = REPO_ROOT / "screenshots" / "freeze.txt"
    if not marker.exists():
        return ""
    return marker.read_text(encoding="utf-8").strip()


def base() -> dict[str, str]:
    """Provenance that does not depend on the session."""
    sha, dirty = git_sha()
    qt_version, pyside_version = qt_versions()
    return {
        "software_version": __version__,
        "git_sha": sha,
        "git_dirty": "true" if dirty else "false",
        "screenshot_freeze_sha": screenshot_freeze_sha(),
        "python_version": platform.python_version(),
        "qt_version": qt_version,
        "pyside_version": pyside_version,
        "package_versions": package_versions(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "hostname": socket.gethostname(),
    }


def cloud_sync_warning(folder: Path, markers: list[str]) -> str:
    """Empty unless the data folder resolves inside a cloud-synced tree (SPEC.md 14.1).

    Warn and record, never refuse: a session that cannot start because of where its output
    goes is worse than a session whose output location is flagged.
    """
    resolved = str(folder.resolve())
    hits = [marker for marker in markers if marker.lower() in resolved.lower()]
    if not hits:
        return ""
    return f"{resolved} matches {', '.join(hits)}"


def python_executable() -> str:
    return sys.executable
