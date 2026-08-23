"""The screenshot comparison's own logic. SPEC.md 17.4.

The catalogue itself is checked by `make shots`, which is part of the gate -- running all
sixty grabs inside pytest as well would double the cost to assert the same thing twice. What
is tested here is the part with a definite right answer and no Qt window in it: how two images
are compared, and the manifest round trip.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QImage

from tatp import screenshots


@pytest.fixture
def image():
    def make(width=4, height=4, colour="black"):
        made = QImage(width, height, QImage.Format_RGB32)
        made.fill(QColor(colour))
        return made

    return make


def test_identical_images_differ_by_nothing(image):
    assert screenshots.difference_fraction(image(), image()) == 0.0


def test_one_changed_pixel_is_found(image):
    changed = image()
    changed.setPixelColor(0, 0, QColor("white"))
    assert screenshots.difference_fraction(image(), changed) == pytest.approx(1 / 16)


def test_a_different_size_is_a_total_difference(image):
    """Not a tolerable difference at any tolerance -- the two are not the same picture."""
    assert screenshots.difference_fraction(image(), image(width=8)) == 1.0


def test_the_tolerance_is_tight_enough_to_catch_a_word(image):
    """A changed word moves far more than the tolerance; a re-rasterised glyph edge does not.

    Pinned because the tolerance is the whole difference between a check that catches a wording
    change and one that waves it through.
    """
    assert screenshots.TOLERANCE_FRACTION < 0.01


def test_the_manifest_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(screenshots, "SCREENSHOT_DIR", tmp_path)
    monkeypatch.setattr(screenshots, "MANIFEST_PATH", tmp_path / "manifest.yaml")
    catalogue = {"participant_sv_cue": "One filled disc, centred."}
    screenshots.write_manifest(catalogue)
    assert screenshots.read_manifest() == catalogue


def test_a_missing_manifest_is_an_error_not_an_empty_one(tmp_path, monkeypatch):
    """An empty manifest would make "every entry has an image" vacuously true."""
    monkeypatch.setattr(screenshots, "MANIFEST_PATH", tmp_path / "absent.yaml")
    with pytest.raises(screenshots.ManifestError):
        screenshots.read_manifest()
