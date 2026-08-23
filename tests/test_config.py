"""Configuration loading. SPEC.md 6, 20.

The point of these tests is that a bad configuration stops the program at load, rather than two
hours into a session. So they test the failures as much as the success.
"""

from __future__ import annotations

import shutil

import pytest

from tatp import config as cfg


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


def test_loads_the_real_configuration(loaded):
    assert loaded.participant_language == "sv"
    assert loaded.experimenter_language == "en"
    assert loaded.study1["design"]["n_sessions"] == len(loaded.study1["design"]["conditions"])
    assert len(loaded.sha256) == 64


def test_unknown_language_is_rejected():
    with pytest.raises(cfg.ConfigError, match="participant language"):
        cfg.load("de", "en")


def test_open_items_are_reported_until_their_config_path_is_filled(loaded):
    assert loaded.open_items, "open_items.yaml defines no items"
    numbers = {item.number for item in loaded.open_items}
    assert {"L1", "L2", "L3", "L4"} <= numbers
    # Nothing has been supplied yet (FOR_S.md), so every locally-raised item is still open.
    assert {item.number for item in loaded.unresolved} >= {"L1", "L2", "L3", "L4"}
    assert all(item.blocks_use for item in loaded.blocking_unresolved)


def test_placeholder_participant_text_is_detected(loaded):
    assert loaded.has_placeholder_text(), (
        "participant wording is still unsupplied (FOR_S.md A1.1), so this must be True; if "
        "S has supplied it, this test is what tells you to remove the startup banner"
    )


def test_resolve_star_paths():
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert cfg.resolve(data, "a.b[*].c") == [1, 2]
    assert cfg.resolve(data, "a.missing") == []
    with pytest.raises(cfg.ConfigError, match="not a list"):
        cfg.resolve({"a": {"b": 1}}, "a.b[*]")


def _config_copy(tmp_path):
    destination = tmp_path / "config"
    shutil.copytree(cfg.CONFIG_DIR, destination)
    return destination


def test_a_null_required_value_names_the_file_and_the_key(tmp_path):
    config_dir = _config_copy(tmp_path)
    path = config_dir / "study1.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("n_participants: 41", "n_participants: null"),
        encoding="utf-8",
    )
    with pytest.raises(cfg.ConfigError, match=r"study1.yaml.*n_participants.*null"):
        cfg.load("sv", "en", config_dir=config_dir)


def test_a_missing_translation_key_is_fatal(tmp_path):
    """SPEC.md 10.4: never fall back silently to the other language."""
    config_dir = _config_copy(tmp_path)
    path = config_dir / "text" / "participant_en.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    top_level = next(i for i, line in enumerate(lines) if line and not line[0].isspace()
                     and line.rstrip().endswith(":"))
    end = next(
        (i for i in range(top_level + 1, len(lines))
         if lines[i] and not lines[i][0].isspace()),
        len(lines),
    )
    path.write_text("\n".join(lines[:top_level] + lines[end:]) + "\n", encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="missing key"):
        cfg.load("sv", "en", config_dir=config_dir)
