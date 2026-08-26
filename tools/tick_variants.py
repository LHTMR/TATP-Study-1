"""Render the VAS anchor tick in each candidate style, for S to choose between.

`UI_PRINCIPLES.md` 1.4 settles the design -- the tick straddles the line, thinner than the line
and subordinate to it. It does not settle how far it rises or how heavy it is, and neither does
anything else: that is a judgement about rendered pixels, so it is made by looking at them.

Two scales, because the tick does two jobs. `pleasantness` has two end anchors and nothing
stacked, which is the tick as a plain landmark. `intensity` in Swedish stacks four labels onto
two rows, which is the tick as the leader line tying a dropped label to its percentage -- the
case that decides whether a heavier tick is legible or noisy.

**This tool is scaffolding for one decision.** When S chooses, fold the chosen numbers back into
`tatp/ui/vas.py` as constants and delete this file with `TickStyle`.

    make ticks
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Offscreen, for the same reason as tools/shots.py: this renders with no display attached.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402 -- platform set before Qt loads

from tatp import config as cfg  # noqa: E402
from tatp.clock import Clock  # noqa: E402
from tatp.responder import Responder  # noqa: E402
from tatp.screenshots import HEIGHT_PX, SCREENSHOT_DIR, WIDTH_PX  # noqa: E402
from tatp.ui.participant import ParticipantWindow  # noqa: E402
from tatp.ui.vas import TICK_STYLES  # noqa: E402

VARIANT_DIR = SCREENSHOT_DIR / "tick_variants"

# The scale to show in each language, chosen for what it asks of the tick.
CASES = (("en", "pleasantness"), ("sv", "intensity"))


def main() -> int:
    QApplication.instance() or QApplication([])
    VARIANT_DIR.mkdir(parents=True, exist_ok=True)

    written = []
    for language, scale in CASES:
        config = cfg.load(language, language)
        window = ParticipantWindow(config, Responder(config.hardware), Clock())
        for name, style in TICK_STYLES.items():
            window.vas.tick_style = style
            window.show_vas(scale)
            window.resize(WIDTH_PX, HEIGHT_PX)
            path = VARIANT_DIR / f"tick_{name}_{scale}_{language}.png"
            window.grab().save(str(path))
            written.append(path)

    for path in written:
        print(path.relative_to(cfg.REPO_ROOT))
    print(f"{len(written)} images in {VARIANT_DIR.relative_to(cfg.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
