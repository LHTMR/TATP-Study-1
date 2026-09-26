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

import gc
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The package is imported from the repository root rather than installed, so tests run against
# the working tree and not against a stale copy in site-packages.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402 -- the platform and the path must be set first
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tatp import config as cfg  # noqa: E402
from tatp.ui.application import application  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _study_font():
    """Every test measures text in the font the lab PC draws, not the platform's.

    Created before any test's own `QApplication.instance() or QApplication([])`, which then
    finds this one. Without it the layout tests measured the Mac's system font, and on
    headless Windows measured empty boxes.
    """
    application(cfg.load("sv", "sv").hardware)


@pytest.fixture(autouse=True)
def _windows_die_with_their_test():
    """Every window a test built is deleted by Qt when the test ends (docs/LOG.md N7.U9).

    A test's windows sit in reference cycles with its session and rig, so left alone they are
    destroyed by the garbage collector, at whatever allocation next triggers it in a later
    test. Destroyed that way they corrupted the heap (0xc0000374) and took the worker down,
    in a different test each run. Deleted by Qt first, in its own order, they cannot; the
    collection then finds only dead wrappers. It runs here, not at random, so a test that
    leaves anything else dangerous behind crashes in its own teardown, where it is found.

    Nothing wider than one test may keep a window, since this deletes it. `deleteLater`, not
    `close`: a window's close handler may ask a question, and nobody is there to answer.

    The collector does not run on its own during a test at all (docs/LOG.md N7.U18). Between
    the test body's end and this teardown, pytest-qt processes the events still queued, paint
    events included, for windows the body has just dropped. A collection triggered by an
    allocation inside one `paintEvent` destroyed the window being painted, an access violation.
    Everything freed by reference counting still goes at once; only cycles wait, until here.
    """
    gc.disable()
    yield
    try:
        for window in QApplication.topLevelWidgets():
            window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()
    finally:
        # A teardown that raised must not leave every later test in the worker uncollected.
        gc.enable()
