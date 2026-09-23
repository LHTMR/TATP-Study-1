"""The forbidden-terms check of SPEC.md 16 and 17.2.

The check itself is `tatp/blinding.py`, so that `tools/validate_session.py` runs the same code
(SPEC.md 17.3). Its docstring says what the check does and does not catch.
"""

from __future__ import annotations

import pytest

from tatp import blinding

PARTICIPANT_FILES = blinding.participant_files()
EXPERIMENTER_FILES = blinding.experimenter_files()
FORBIDDEN_TERMS = blinding.forbidden_terms()
CONDITIONS = blinding.conditions()


def test_the_forbidden_list_is_not_empty():
    """A list that emptied by accident would make every check below pass silently."""
    assert FORBIDDEN_TERMS, "config/blinding.yaml lists no forbidden terms"
    assert CONDITIONS, "study1.yaml lists no conditions"


@pytest.mark.parametrize("path", PARTICIPANT_FILES, ids=lambda p: p.name)
def test_no_participant_text_contains_a_forbidden_term(path):
    hits = blinding.hits(path, FORBIDDEN_TERMS)
    assert not hits, "SPEC.md 16:\n" + "\n".join(hits)


@pytest.mark.parametrize(
    "path", PARTICIPANT_FILES + EXPERIMENTER_FILES, ids=lambda p: p.name
)
def test_no_screen_text_names_a_condition(path):
    """SPEC.md 16: the condition is recorded in the data and never displayed, to either role."""
    hits = blinding.hits(path, CONDITIONS)
    assert not hits, "SPEC.md 16:\n" + "\n".join(hits)


def test_the_validator_entry_point_agrees_with_the_tests():
    """`violations()` is what the validator calls; it must see what the tests above see."""
    assert blinding.violations() == [
        hit for path in PARTICIPANT_FILES for hit in blinding.hits(path, FORBIDDEN_TERMS)
    ] + [
        hit
        for path in PARTICIPANT_FILES + EXPERIMENTER_FILES
        for hit in blinding.hits(path, CONDITIONS)
    ]


def test_a_planted_forbidden_term_is_found(tmp_path):
    """The detector, tested against crafted text rather than against today's config."""
    planted = tmp_path / "participant_xx.yaml"
    planted.write_text("screens:\n  welcome: 'Welcome to TATP'\n", encoding="utf-8")
    hits = blinding.hits(planted, FORBIDDEN_TERMS)
    assert len(hits) == 1
    assert "screens.welcome" in hits[0]


def test_the_check_is_case_insensitive(tmp_path):
    planted = tmp_path / "participant_xx.yaml"
    planted.write_text("screens:\n  welcome: 'touch away THE pain'\n", encoding="utf-8")
    assert blinding.hits(planted, FORBIDDEN_TERMS)
