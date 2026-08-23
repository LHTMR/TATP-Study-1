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

# Standard gravity, the only thing relating a gram label to a force. A unit conversion, which
# SPEC.md 4.2 allows as a literal.
MN_PER_G = 9.81


def test_there_are_config_files():
    assert YAML_FILES, f"no YAML files under {CONFIG_DIR}"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: str(p.relative_to(CONFIG_DIR)))
def test_parses(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path}: expected a mapping at the top level"


def test_every_gram_label_agrees_with_the_manual_force():
    """The gram labels are the identifier (SPEC.md 8.1), so they are checked, not trusted.

    `label_g` was transcribed from the standard Semmes-Weinstein set rather than read off the
    kit. Multiplying by standard gravity must reproduce `force_manual_mn`, which was already in
    the file, so a mistyped label fails here instead of naming the wrong filament in a session.
    Confirmation against the physical kit is still outstanding (FOR_S.md A3.8).
    """
    filaments = yaml.safe_load(
        (CONFIG_DIR / "filaments.yaml").read_text(encoding="utf-8")
    )["filaments"]
    assert filaments, "filaments.yaml lists no filaments"
    labels = [f["label_g"] for f in filaments]
    assert len(set(labels)) == len(labels), f"duplicate gram labels: {labels}"
    for filament in filaments:
        expected_mn = float(filament["label_g"]) * MN_PER_G
        assert expected_mn == pytest.approx(filament["force_manual_mn"], rel=0.01), (
            f"filament labelled {filament['label_g']} g implies {expected_mn:.1f} mN, but "
            f"force_manual_mn is {filament['force_manual_mn']} mN"
        )
