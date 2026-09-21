"""Render every VAS scale in each anchor layout, so the alternative can be shown to colleagues.

`interior_above` is the study's layout and is what `make shots` photographs. `ends_outside` is
the alternative S chose to keep for comparison (10 Sep 2026): every label below the line, the
end labels hanging outwards, and a shorter line so they stay on screen. A session never uses it.

Every scale uncued in both languages, plus a rating at 5 % on the pain scale -- the case that
shows whether the marker can cover an interior anchor's name.

    make layouts
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
from tatp.responder import Action, Responder  # noqa: E402
from tatp.screenshots import HEIGHT_PX, SCREENSHOT_DIR, WIDTH_PX  # noqa: E402
from tatp.ui.participant import ParticipantWindow  # noqa: E402
from tatp.ui.vas import LAYOUTS  # noqa: E402

LAYOUT_DIR = SCREENSHOT_DIR / "vas_layouts"
MARKER_SCALE = "pain"
MARKER_PCT = 5.0


def main() -> int:
    QApplication.instance() or QApplication([])
    written = []
    for language in ("sv", "en"):
        config = cfg.load(language, language)
        window = ParticipantWindow(config, Responder(config.hardware), Clock())
        window.resize(WIDTH_PX, HEIGHT_PX)
        for name, layout in LAYOUTS.items():
            folder = LAYOUT_DIR / name
            folder.mkdir(parents=True, exist_ok=True)
            window.vas.layout = layout
            for scale in sorted(config.participant_text["vas"]):
                window.show_vas(scale)
                path = folder / f"{language}_{scale}.png"
                window.grab().save(str(path))
                written.append(path)

            window.show_vas(MARKER_SCALE)
            window.vas.state.press(Action.INCREASE)
            window.vas.state.percent = MARKER_PCT
            window.vas.update()
            path = folder / f"{language}_{MARKER_SCALE}_at_{MARKER_PCT:g}pct.png"
            window.grab().save(str(path))
            written.append(path)

    print(f"{len(written)} images in {LAYOUT_DIR.relative_to(cfg.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
