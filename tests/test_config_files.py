"""Every YAML file under config/ must parse.

`tatp/config.py` only loads the files it knows about, so a malformed pattern file would not be
noticed until the condition that points at it ran. Parsing all of them here is the cheapest
check that exists, and it is the one that catches an unquoted `key: value` inside a prose
string -- the failure mode of a file written by hand and never loaded.
"""

from __future__ import annotations

import pytest
import yaml

from tatp.config import CONFIG_DIR

YAML_FILES = sorted(CONFIG_DIR.rglob("*.yaml"))

# The conversion factor the Aesthesio data chart states it used. A unit conversion, which
# SPEC.md 4.2 allows as a literal.
MN_PER_G = 9.80665

# The chart's milliNewton column is rounded to two significant figures, so at the bottom of the
# ladder -- 0.008 g, 0.08 mN -- the rounding alone is about 2 %. A mistyped label moves a row by
# 25 % or more, so this tolerance still catches every transcription error it is here to catch.
FORCE_TOLERANCE = 0.03


def test_there_are_config_files():
    assert YAML_FILES, f"no YAML files under {CONFIG_DIR}"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: str(p.relative_to(CONFIG_DIR)))
def test_parses(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path}: expected a mapping at the top level"


def test_fit_preview_is_off_in_the_committed_config():
    """SPEC.md 11.1. Enabling this is a study decision, not a config tweak.

    The preview shows the experimenter the participant's ratings, which Bilaga 1 3.3 says does
    not happen and which `screens.welcome` tells the participant does not happen. A flag
    flipped in passing fails here rather than reaching a participant who was told otherwise.
    """
    study1 = yaml.safe_load((CONFIG_DIR / "study1.yaml").read_text(encoding="utf-8"))
    assert study1["fit_preview"]["enabled"] is False, (
        "fit_preview.enabled is true in the committed config. If that is deliberate, the "
        "'the experimenter does not see your answers' sentence must come out of "
        "screens.welcome in both languages first. See FOR_S.md B3.4, then update this test."
    )


def test_every_gram_label_agrees_with_its_force():
    """The gram labels are the identifier (SPEC.md 8.1), so they are checked, not trusted.

    Both columns are transcribed from the Aesthesio data chart, and the chart states the factor
    relating them. Multiplying the label by it must reproduce the force, so a mistyped digit
    fails here instead of naming the wrong filament in a session. This checks the transcription
    against itself; confirmation against the physical kit is FOR_S.md A3.8.
    """
    filaments = yaml.safe_load(
        (CONFIG_DIR / "filaments.yaml").read_text(encoding="utf-8")
    )["filaments"]
    assert filaments, "filaments.yaml lists no filaments"
    labels = [f["label_g"] for f in filaments]
    assert len(set(labels)) == len(labels), f"duplicate gram labels: {labels}"
    assert labels == sorted(labels, key=float), "list the ladder in ascending order"
    for filament in filaments:
        expected_mn = float(filament["label_g"]) * MN_PER_G
        assert expected_mn == pytest.approx(
            filament["force_nominal_mn"], rel=FORCE_TOLERANCE
        ), (
            f"filament labelled {filament['label_g']} g implies {expected_mn:.3f} mN, but "
            f"force_nominal_mn is {filament['force_nominal_mn']} mN"
        )
