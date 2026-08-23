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


def test_there_are_config_files():
    assert YAML_FILES, f"no YAML files under {CONFIG_DIR}"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: str(p.relative_to(CONFIG_DIR)))
def test_parses(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path}: expected a mapping at the top level"
