"""Configuration loading. SPEC.md 6, 20.

The point of these tests is that a bad configuration stops the program at load, rather than two
hours into a session. So they test the failures as much as the success.
"""

from __future__ import annotations

import shutil

import pytest
import yaml

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


def test_an_open_item_is_resolved_exactly_when_its_config_path_is_filled(loaded):
    """The mechanism, not today's state -- items get resolved and this must keep working.

    An earlier version of this test asserted that L1-L4 were all still open, which made it fail
    the moment L4 was actually supplied. What must hold at every point in the build is that
    `resolved` agrees with the file: an item is open if and only if a path it names is null.
    """
    assert loaded.open_items, "open_items.yaml defines no items"
    assert {"L1", "L2", "L3", "L4"} <= {item.number for item in loaded.open_items}
    assert all(item.blocks_use for item in loaded.blocking_unresolved)

    def filled(check) -> bool:
        data = yaml.safe_load(
            (loaded.config_dir / check["file"]).read_text(encoding="utf-8")
        )
        values = cfg.resolve(data, check["path"])
        return bool(values) and all(value is not None for value in values)

    entries = yaml.safe_load(
        (loaded.config_dir / "open_items.yaml").read_text(encoding="utf-8")
    )["items"]
    by_number = {item.number: item for item in loaded.open_items}
    for entry in entries:
        checks = [entry["resolved_when"], *([entry["also"]] if "also" in entry else [])]
        item = by_number[str(entry["item"])]
        assert item.resolved is all(filled(check) for check in checks), (
            f"open item {entry['item']} reports resolved={item.resolved}, which disagrees with "
            f"the config paths it names"
        )


def test_unapproved_participant_wording_is_detected(loaded):
    """SPEC.md 20 and CLAUDE.md: a PLACEHOLDER string must never reach a participant unseen.

    Driven by a crafted config rather than the live one, so the detector stays tested after S
    approves wording -- which has already happened once for the `screens:` block (L4).
    """
    unapproved = cfg.Config(
        **{
            **loaded.__dict__,
            "participant_text": {"screens": {"standby": f"{cfg.PLACEHOLDER_PREFIX} - not yet"}},
        }
    )
    assert unapproved.has_placeholder_text()
    approved = cfg.Config(
        **{**loaded.__dict__, "participant_text": {"screens": {"standby": "Please wait."}}}
    )
    assert not approved.has_placeholder_text()


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
