"""The forbidden-terms check of SPEC.md 16 and 17.2.

Every string in `config/text/participant_{sv,en}.yaml` is checked against
`config/blinding.yaml`, case-insensitively, plus the condition labels read from `study1.yaml`
so a new condition cannot leave a stale list behind.

**This is a floor, not a blinding check.** A grep catches the study name and the condition
labels; it cannot catch "this should help with the pain", which contains none of them and
breaks SPEC.md 16 completely. `config/blinding.yaml` says so at more length. The wording review
is what catches framing.

The experimenter files are checked for condition labels only, for the other half of SPEC.md 16
-- the experimenter is blind to condition too, and the label must not reach their screen either.
They are not checked for the study name, which they may legitimately use.
"""

from __future__ import annotations

import pytest
import yaml

from tatp.config import CONFIG_DIR

TEXT_DIR = CONFIG_DIR / "text"
PARTICIPANT_FILES = sorted(TEXT_DIR.glob("participant_*.yaml"))
EXPERIMENTER_FILES = sorted(TEXT_DIR.glob("experimenter_*.yaml"))


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _strings(node, trail=""):
    """Every string in a nested structure, with the dotted path that reaches it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{trail}.{key}" if trail else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{trail}[{index}]")
    elif isinstance(node, str):
        yield trail, node


FORBIDDEN_TERMS = _load(CONFIG_DIR / "blinding.yaml")["forbidden_terms"]
CONDITIONS = _load(CONFIG_DIR / "study1.yaml")["design"]["conditions"]


def _hits(path, terms):
    lowered = [term.lower() for term in terms]
    return [
        f"{path.name}:{trail}: {term!r} in {value!r}"
        for trail, value in _strings(_load(path))
        for term in lowered
        if term in value.lower()
    ]


def test_the_forbidden_list_is_not_empty():
    """A list that emptied by accident would make every check below pass silently."""
    assert FORBIDDEN_TERMS, "config/blinding.yaml lists no forbidden terms"
    assert CONDITIONS, "study1.yaml lists no conditions"


@pytest.mark.parametrize("path", PARTICIPANT_FILES, ids=lambda p: p.name)
def test_no_participant_text_contains_a_forbidden_term(path):
    hits = _hits(path, FORBIDDEN_TERMS)
    assert not hits, "SPEC.md 16:\n" + "\n".join(hits)


@pytest.mark.parametrize(
    "path", PARTICIPANT_FILES + EXPERIMENTER_FILES, ids=lambda p: p.name
)
def test_no_screen_text_names_a_condition(path):
    """SPEC.md 16: the condition is recorded in the data and never displayed, to either role."""
    hits = _hits(path, CONDITIONS)
    assert not hits, "SPEC.md 16:\n" + "\n".join(hits)


def test_a_planted_forbidden_term_is_found(tmp_path):
    """The detector, tested against crafted text rather than against today's config."""
    planted = tmp_path / "participant_xx.yaml"
    planted.write_text("screens:\n  welcome: 'Welcome to TATP'\n", encoding="utf-8")
    hits = _hits(planted, FORBIDDEN_TERMS)
    assert len(hits) == 1
    assert "screens.welcome" in hits[0]


def test_the_check_is_case_insensitive(tmp_path):
    planted = tmp_path / "participant_xx.yaml"
    planted.write_text("screens:\n  welcome: 'touch away THE pain'\n", encoding="utf-8")
    assert _hits(planted, FORBIDDEN_TERMS)
