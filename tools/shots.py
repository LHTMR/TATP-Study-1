"""Entry point for the screenshot run (SPEC.md 17.4). The work is in `tatp/screenshots.py`.

Qt must render without a display, exactly as in `tests/conftest.py` and for the same reason:
`make check` runs headless with no hardware attached (SPEC.md 17.1), and setting the platform
here rather than on the command line means it cannot be forgotten and keeps the invocation free
of an environment-variable prefix.

This file exists so the run has a `tools/` entry point. `run_session.py` deliberately does not
set the platform -- a real session needs a real display.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tatp.screenshots import main  # noqa: E402 -- the platform must be set before Qt loads

if __name__ == "__main__":
    sys.exit(main())
