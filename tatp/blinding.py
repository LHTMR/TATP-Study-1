"""The forbidden-terms check of SPEC.md 16 and 17.2.

Here rather than in the test so that `tests/test_blinding_text.py` and
`tools/validate_session.py` run one implementation, not two that could disagree.

**This is a floor, not a blinding check.** A grep catches the study name and the condition
labels; it cannot catch "this should help with the pain", which contains none of them and
breaks SPEC.md 16 completely. `config/blinding.yaml` says so at more length. The wording review
is what catches framing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tatp.config import CONFIG_DIR

TEXT_DIR = CONFIG_DIR / "text"


def participant_files() -> list[Path]:
    return sorted(TEXT_DIR.glob("participant_*.yaml"))


def experimenter_files() -> list[Path]:
    return sorted(TEXT_DIR.glob("experimenter_*.yaml"))


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def forbidden_terms() -> list[str]:
    return _load(CONFIG_DIR / "blinding.yaml")["forbidden_terms"]


def conditions() -> list[str]:
    """Read from study1.yaml so a new condition cannot leave a stale list behind."""
    return _load(CONFIG_DIR / "study1.yaml")["design"]["conditions"]


def strings(node, trail=""):
    """Every string in a nested structure, with the dotted path that reaches it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from strings(value, f"{trail}.{key}" if trail else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from strings(value, f"{trail}[{index}]")
    elif isinstance(node, str):
        yield trail, node


def hits(path: Path, terms: list[str]) -> list[str]:
    """Each occurrence of a term in the file, case-insensitively, as a readable line."""
    lowered = [term.lower() for term in terms]
    return [
        f"{path.name}:{trail}: {term!r} in {value!r}"
        for trail, value in strings(_load(path))
        for term in lowered
        if term in value.lower()
    ]


def violations() -> list[str]:
    """Every SPEC.md 16 hit across the screen text of both roles.

    Participant files are checked for the forbidden terms and the condition labels. Experimenter
    files are checked for the condition labels only -- the experimenter is blind to condition
    too, but may legitimately use the study name.
    """
    terms, labels = forbidden_terms(), conditions()
    # Stage boundary (CLAUDE.md): an emptied list would make every check pass silently.
    assert terms, "config/blinding.yaml lists no forbidden terms"
    assert labels, "study1.yaml lists no conditions"
    found = []
    for path in participant_files():
        found += hits(path, terms) + hits(path, labels)
    for path in experimenter_files():
        found += hits(path, labels)
    return found
