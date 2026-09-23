"""The study fonts are the ones Qt draws, and a font Qt cannot match stops the program."""

import copy

import pytest
from PySide6.QtGui import QFont, QFontInfo, QRawFont

from tatp import config as cfg
from tatp.ui.application import application


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
