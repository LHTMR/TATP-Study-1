"""The Bash hook is what makes `Bash(… python tools/*)` a safe permission rule.

The rule allows arguments, and `tools/make_allocation.py` takes `--out`, so the only thing
stopping a write outside the repository is the hook's path check. That makes these cases
part of the gate rather than a nicety.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".claude" / "hooks" / "check_bash.py"

BLOCKED_EXIT = 2


def run_hook(command: str) -> subprocess.CompletedProcess:
    payload = {"tool_input": {"command": command}, "cwd": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def test_allows_the_commands_the_build_actually_runs():
    for command in [
        "conda run -n tatp-study-1 python tools/make_allocation.py",
        "conda run -n tatp-study-1 python tools/make_allocation.py --seed 7",
        "conda run -n tatp-study-1 python -m pytest -q",
        "git commit -m Milestone 1: config layer and allocation",
        "grep -rn isi_min_s config",
        "make check",
    ]:
        assert run_hook(command).returncode == 0, command


def test_blocks_relative_escape_from_the_repository():
    # The case the `tools/*` permission rule cannot catch by itself.
    for command in [
        "python tools/make_allocation.py --out ../escape.csv",
        "python tools/make_allocation.py --out=../../escape.csv",
        "python ../../elsewhere/script.py",
    ]:
        assert run_hook(command).returncode == BLOCKED_EXIT, command


def test_blocks_absolute_and_home_paths_outside_the_repository():
    for command in [
        "python tools/make_allocation.py --out /tmp/escape.csv",
        "python tools/make_allocation.py --out ~/escape.csv",
    ]:
        assert run_hook(command).returncode == BLOCKED_EXIT, command


def test_blocks_compound_commands():
    for command in [
        "make check && rm -rf data",
        "python -c a=1; b=2",
        "echo `whoami`",
    ]:
        assert run_hook(command).returncode == BLOCKED_EXIT, command
