"""The study fonts are the ones Qt draws, and a font Qt cannot match stops the program."""

import copy
import os
import subprocess
import sys

import pytest
from PySide6.QtGui import QFont, QFontInfo, QRawFont

from tatp import config as cfg
from tatp.config import REPO_ROOT
from tatp.screenshots import HEIGHT_PX, WIDTH_PX
from tatp.ui.application import SCALE_FACTORS_VARIABLE, application, scale_screens

# Both lab screens, the laptop's own and the HP Z24i (docs/LOG.md N7.H3).
LAB_SCREEN_PX = (1920, 1200)


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def test_the_study_font_is_the_one_qt_draws_in_both_weights():
    hardware = cfg.load("sv", "sv").hardware
    study_font = hardware["screens"]["font_families"][0]
    app = application(hardware)
    bold = QFont(app.font())
    bold.setBold(True)
    assert QFontInfo(app.font()).family() == study_font
    assert QFontInfo(bold).family() == study_font


def test_every_character_any_screen_can_show_has_a_glyph_in_a_study_font():
    """A character no configured font holds is drawn as an empty box, silently.

    The confirm symbol was exactly that once the platform font stopped supplying it: 350 tests
    passed over a welcome screen reading "Tryck på [box] för att börja".
    """
    texts = []
    for language in ("sv", "en"):
        config = cfg.load(language, language)
        texts += _strings(config.participant_text) + _strings(config.experimenter_text)
    texts += _strings(config.hardware["responder"]["button_symbols"])
    application(config.hardware)
    fonts = [QRawFont.fromFont(QFont(f)) for f in config.hardware["screens"]["font_families"]]
    characters = {c for text in texts for c in text if not c.isspace()}
    # Code points, not str: PySide reads a non-ASCII str here as unsupported.
    missing = sorted(
        c for c in characters if not any(f.supportsCharacter(ord(c)) for f in fonts)
    )
    assert not missing, f"no study font draws {missing}"


def test_a_family_no_font_file_supplies_fails_fast():
    hardware = copy.deepcopy(cfg.load("sv", "sv").hardware)
    hardware["screens"]["font_families"] = ["Not The Study Font"]
    with pytest.raises(AssertionError, match="Not The Study Font"):
        application(hardware)


# A fresh process, because the factors are read only when Qt starts. The offscreen screen is
# 800x800, so at 2 it is 400x400 in Qt's pixels.
SCALED_PROBE = """
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from tatp.ui.application import scale_screens
scale_screens({"screens": {"scale_factors": [2]}})
from PySide6.QtWidgets import QApplication
app = QApplication([])
size = app.screens()[0].geometry()
print(size.width(), size.height(), app.screens()[0].devicePixelRatio())
"""


def test_the_configured_scale_factor_is_the_one_qt_draws_at():
    """docs/LOG.md N7.U10: the lab's 1920x1200 screens are drawn at the approved 1280x800."""
    result = subprocess.run(
        [sys.executable, "-c", SCALED_PROBE, str(REPO_ROOT)],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.split() == ["400", "400", "2.0"]


def test_the_scale_factors_are_left_alone_once_qt_is_running(monkeypatch):
    """The tests start Qt themselves, so a session or the launcher driven by one draws at the
    design size, unscaled, whatever the lab's factors say."""
    monkeypatch.delenv(SCALE_FACTORS_VARIABLE, raising=False)
    scale_screens({"screens": {"scale_factors": [1.5]}})
    assert SCALE_FACTORS_VARIABLE not in os.environ


def test_the_lab_draws_both_screens_at_the_design_size():
    """1920x1200 at the configured factor is the 1280x800 every screen is approved at."""
    factors = cfg.load("sv", "sv").hardware["screens"]["scale_factors"]
    assert factors is not None, "the lab PC's hardware.yaml scales both screens"
    for factor in factors:
        assert (LAB_SCREEN_PX[0] / factor, LAB_SCREEN_PX[1] / factor) == (WIDTH_PX, HEIGHT_PX)
