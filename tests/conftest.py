"""Test-suite setup.

Qt must render without a display so that `make check` passes headless with no hardware
attached (SPEC.md 17.1). Setting QT_QPA_PLATFORM here rather than on the command line matters
for two reasons:

- It cannot be forgotten. A command-line `QT_QPA_PLATFORM=offscreen pytest` works only when
  someone remembers the prefix, and a test run that silently uses a real display would still
  pass locally and fail on the lab PC.
- It keeps the invocation a plain `python -m pytest`, with no leading variable assignment.
  The permission rules in .claude/settings.json match on a command prefix, so an env-var
  prefix would stop the allowed form from matching and prompt on every run.

It must be set before anything imports Qt, which is what conftest.py at the top of the test
tree guarantees.

`run_session.py` deliberately does NOT do this -- a real session needs a real display.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The package is imported from the repository root rather than installed, so tests run against
# the working tree and not against a stale copy in site-packages.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
