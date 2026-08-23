"""Response-device input. SPEC.md 10.1."""

from __future__ import annotations

import copy

import pytest

from tatp import config as cfg
from tatp.responder import Action, Responder, ResponderError


@pytest.fixture(scope="module")
def hardware():
    return cfg.load("sv", "en").hardware


def test_the_r400_keys_map_to_the_four_actions(hardware):
    responder = Responder(hardware)
    assert responder.action_for("pageup") is Action.DECREASE
    assert responder.action_for("pagedown") is Action.INCREASE
    assert responder.action_for("period") is Action.CONFIRM
    assert responder.action_for("f5") is Action.EMERGENCY_STOP
    assert responder.action_for("space") is None


def test_escape_does_nothing_at_all(hardware):
    """SPEC.md 10.1: the play button emits escape, so a quit binding would end the session."""
    responder = Responder(hardware)
    assert responder.is_ignored("escape")
    assert responder.action_for("escape") is None
    assert "escape" not in responder.keys


def test_binding_an_ignored_key_to_an_action_is_refused(hardware):
    broken = copy.deepcopy(hardware)
    broken["responder"]["keys"]["confirm"] = ["escape"]
    with pytest.raises(ResponderError, match="must do nothing at all"):
        Responder(broken)


def test_one_key_bound_to_two_actions_is_refused(hardware):
    broken = copy.deepcopy(hardware)
    broken["responder"]["keys"]["confirm"] = ["pageup"]
    with pytest.raises(ResponderError, match="bound to both"):
        Responder(broken)


def test_an_action_with_no_key_is_refused(hardware):
    broken = copy.deepcopy(hardware)
    broken["responder"]["keys"]["emergency_stop"] = []
    with pytest.raises(ResponderError, match="emergency_stop is empty"):
        Responder(broken)
