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


def _plant(folder, participant: str, experimenter: str):
    (folder / "participant_xx.yaml").write_text(participant, encoding="utf-8")
    (folder / "experimenter_xx.yaml").write_text(experimenter, encoding="utf-8")
    return folder


def test_the_validator_entry_point_finds_every_planted_violation(tmp_path):
    """`violations()` is what the validator calls, so it is tested against planted text."""
    condition = CONDITIONS[0]
    folder = _plant(
        tmp_path,
        f"screens:\n  welcome: 'Welcome to TATP'\n  end: 'That was {condition}'\n",
        f"status:\n  line: 'Running {condition}'\n",
    )
    found = blinding.violations(folder)
    assert len(found) == 3
    assert any("participant_xx.yaml:screens.welcome" in hit for hit in found)
    assert any("participant_xx.yaml:screens.end" in hit for hit in found)
    assert any("experimenter_xx.yaml:status.line" in hit for hit in found)


def test_the_experimenter_text_may_name_the_study(tmp_path):
    """Only condition labels are forbidden to the experimenter, not the study name."""
    folder = _plant(tmp_path, "screens:\n  welcome: 'Hello'\n", "title: 'TATP Study 1'\n")
    assert blinding.violations(folder) == []


def test_a_folder_with_no_text_files_is_refused(tmp_path):
    with pytest.raises(AssertionError):
        blinding.violations(tmp_path)


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
