"""Response-device input. SPEC.md 10.1.

The Logitech R400 emits four keys and nothing else, so the mapping from key to action is
configuration, not code. The one rule worth stating twice is the `escape` rule: the play button
emits `escape` as well as `period`, so a default quit binding would let a participant end the
session by confirming a rating. `escape` is bound to nothing at all, and this module refuses a
configuration in which an ignored key is also an action key.
"""

from __future__ import annotations

from enum import StrEnum


class ResponderError(Exception):
    """The key mapping is unusable. Fatal at startup, never worked around at run time."""


class Action(StrEnum):
    DECREASE = "decrease"
    INCREASE = "increase"
    CONFIRM = "confirm"
    EMERGENCY_STOP = "emergency_stop"


class Responder:
    """Maps key names to actions. Knows nothing about Qt, so it needs no display to test."""

    def __init__(self, hardware: dict):
        block = hardware["responder"]
        self.device = block.get("device", "")
        self.ignored = tuple(block["ignore_keys"])

        self._by_key: dict[str, Action] = {}
        for action in Action:
            keys = block["keys"][action.value]
            if not keys:
                raise ResponderError(f"responder.keys.{action.value} is empty")
            for key in keys:
                if key in self._by_key:
                    raise ResponderError(
                        f"key {key!r} is bound to both {self._by_key[key].value!r} and "
                        f"{action.value!r}"
                    )
                self._by_key[key] = action

        both = sorted(set(self._by_key) & set(self.ignored))
        if both:
            raise ResponderError(
                f"{both} are in responder.ignore_keys and also bound to an action. An ignored "
                f"key must do nothing at all (SPEC.md 10.1)."
            )

        # Stage boundary (CLAUDE.md): the emergency stop is not optional (SPEC.md 13).
        assert Action.EMERGENCY_STOP in self._by_key.values(), "no emergency stop key is bound"

    @property
    def keys(self) -> tuple[str, ...]:
        """Every key that does something, so the UI can swallow the rest."""
        return tuple(sorted(self._by_key))

    def action_for(self, key: str) -> Action | None:
        """The action for a key name, or None if the key does nothing."""
        return self._by_key.get(key)

    def is_ignored(self, key: str) -> bool:
        return key in self.ignored
