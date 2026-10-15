"""The remote's buttons read from its raw reports, and its key messages paired to be dropped.
LOG N7.D22.

`RawInputKeyboards` itself needs Windows and a native window, so it is checked in the lab
(docs/LOG.md N2.10). What can be checked headless is the two parts it is built from.
"""

from __future__ import annotations

import pytest

from tatp.remote_keys import VIRTUAL_KEYS, Pairing, RemoteButtons
from tatp.ui.vas import QT_KEYS

PERIOD_SCAN = 0x34
NUMPAD_DECIMAL_SCAN = 0x53
F5_SCAN = 0x3F
REMOTE_KEYS = ["pageup", "pagedown", "f5", "escape", "period"]


# -- the remote's buttons, from its own reports ------------------------------------------------


def test_a_press_and_its_release_are_the_remotes_own():
    buttons = RemoteButtons(REMOTE_KEYS)
    assert buttons.report(VIRTUAL_KEYS["period"], False) == ("period", False, False)
    assert buttons.report(VIRTUAL_KEYS["period"], True) == ("period", True, False)


def test_a_held_button_repeats_by_the_remotes_own_state():
    """Another keyboard holding the same key cannot make the remote's press a repeat: only
    the remote's own reports are counted here."""
    buttons = RemoteButtons(REMOTE_KEYS)
    assert buttons.report(VIRTUAL_KEYS["period"], False)[2] is False
    assert buttons.report(VIRTUAL_KEYS["period"], False)[2] is True
    buttons.report(VIRTUAL_KEYS["period"], True)
    assert buttons.report(VIRTUAL_KEYS["period"], False)[2] is False


def test_a_key_the_remote_does_not_have_is_nothing():
    assert RemoteButtons(REMOTE_KEYS).report(0x41, False) is None  # A


def test_a_key_with_no_virtual_key_is_refused():
    """A responder key Windows cannot be told to look for would never arrive (fail fast)."""
    with pytest.raises(AssertionError, match="no Windows virtual key"):
        RemoteButtons(["period", "space"])


def test_every_key_qt_knows_has_a_virtual_key():
    """The keys a responder may be configured with (QT_KEYS) and the ones Raw Input can read
    are the same set, so a key added to one is added to the other before the lab finds out."""
    assert set(VIRTUAL_KEYS) == set(QT_KEYS)


def test_a_button_held_as_the_remote_went_is_not_a_repeat_after():
    """Its release never came; the next press must not be ignored as an auto-repeat."""
    buttons = RemoteButtons(REMOTE_KEYS)
    buttons.report(VIRTUAL_KEYS["period"], False)
    buttons.release_all()
    assert buttons.report(VIRTUAL_KEYS["period"], False)[2] is False


# -- pairing each key message with its report, to drop the remote's ---------------------------


def test_the_remotes_key_message_is_dropped_and_another_keyboards_kept():
    pairing = Pairing()
    pairing.report(PERIOD_SCAN, False, False, remote=True)
    pairing.report(PERIOD_SCAN, False, False, remote=False)
    assert pairing.message(PERIOD_SCAN, False, False) is True
    assert pairing.message(PERIOD_SCAN, False, False) is False


def test_the_numpad_decimal_is_paired_by_scan_code():
    """Its virtual key differs between the report and the message; its scan code does not."""
    pairing = Pairing()
    pairing.report(NUMPAD_DECIMAL_SCAN, False, False, remote=False)
    assert pairing.message(NUMPAD_DECIMAL_SCAN, False, False) is False


def test_a_press_and_its_release_are_paired_separately():
    pairing = Pairing()
    pairing.report(PERIOD_SCAN, False, False, remote=True)
    pairing.report(PERIOD_SCAN, False, True, remote=True)
    assert pairing.message(PERIOD_SCAN, False, False) is True
    assert pairing.message(PERIOD_SCAN, False, True) is True


def test_a_message_with_no_report_is_told_apart_and_leaves_the_others_theirs():
    """None, not False: a run of these is how Raw Input failing is noticed (N7.D22)."""
    pairing = Pairing()
    pairing.report(PERIOD_SCAN, False, False, remote=True)
    assert pairing.message(F5_SCAN, False, False) is None
    assert pairing.message(PERIOD_SCAN, False, False) is True


def test_reports_whose_message_never_came_are_dropped():
    pairing = Pairing()
    pairing.report(F5_SCAN, False, False, remote=True)  # some other window took it
    pairing.report(PERIOD_SCAN, False, False, remote=False)
    assert pairing.message(PERIOD_SCAN, False, False) is False
    assert pairing.message(F5_SCAN, False, False) is None, "dropped with the one before"
