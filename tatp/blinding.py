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

One implementation, called by `tests/test_blinding_text.py` and by `tools/validate_session.py`,
because SPEC.md 17.3 requires the validator's check to be the same code as the test's rather
than a second copy that could disagree with it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import yaml

from tatp.config import CONFIG_DIR

TEXT_DIR = CONFIG_DIR / "text"


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def participant_files(text_dir: Path = TEXT_DIR) -> list[Path]:
    return sorted(text_dir.glob("participant_*.yaml"))


def experimenter_files(text_dir: Path = TEXT_DIR) -> list[Path]:
    return sorted(text_dir.glob("experimenter_*.yaml"))


def forbidden_terms() -> list[str]:
    return list(_load(CONFIG_DIR / "blinding.yaml")["forbidden_terms"])


def conditions() -> list[str]:
    return list(_load(CONFIG_DIR / "study1.yaml")["design"]["conditions"])


def strings(node, trail: str = "") -> Iterator[tuple[str, str]]:
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
    """Each occurrence of any of `terms` in the text file at `path`, as a readable line."""
    lowered = [term.lower() for term in terms]
    return [
        f"{path.name}:{trail}: {term!r} in {value!r}"
        for trail, value in strings(_load(path))
        for term in lowered
        if term in value.lower()
    ]


def violations(text_dir: Path = TEXT_DIR) -> list[str]:
    """Every SPEC.md 16 hit across the text files; empty when the configuration is clean."""
    terms, labels = forbidden_terms(), conditions()
    # Stage boundary (CLAUDE.md): a list that emptied by accident would make every check pass.
    assert terms, "config/blinding.yaml lists no forbidden terms"
    assert labels, "study1.yaml lists no conditions"
    participant, experimenter = participant_files(text_dir), experimenter_files(text_dir)
    # The same: a folder with no text files in it would pass with nothing checked.
    assert participant and experimenter, f"{text_dir} has no participant or experimenter text"
    found = []
    for path in participant:
        found += hits(path, terms)
    for path in participant + experimenter:
        found += hits(path, labels)
    return found
