"""Pairing each key event with the raw report that says which keyboard sent it. LOG N7.D22.

`RawInputKeyboards` itself needs Windows and a native window, so it is checked in the lab
(docs/LOG.md N2.10). What can be checked headless is the pairing it relies on: a raw report,
then the key message it becomes, then the Qt key event made from that message.
"""

from __future__ import annotations

from tatp.remote_keys import Pairing

PERIOD_SCAN = 0x34
PERIOD_VK = 0xBE
NUMPAD_DECIMAL_SCAN = 0x53
VK_DECIMAL = 0x6E
F5_SCAN = 0x3F
F5_VK = 0x74


def _keystroke(pairing, time_ms, remote, scan=PERIOD_SCAN, vk=PERIOD_VK, released=False):
    pairing.report(scan, False, released, remote)
    pairing.message(time_ms, vk, scan, False, released)


def test_a_key_event_takes_its_own_keystrokes_verdict():
    pairing = Pairing()
    _keystroke(pairing, 100, remote=True)
    assert pairing.verdict(1, 100, PERIOD_VK, False) is True


def test_the_experimenters_full_stop_is_not_the_remotes():
    pairing = Pairing()
    _keystroke(pairing, 100, remote=False)
    assert pairing.verdict(1, 100, PERIOD_VK, False) is False


def test_the_numpad_decimal_is_paired_by_scan_code_not_virtual_key():
    """The raw report can name VK_DELETE where the key message names VK_DECIMAL."""
    pairing = Pairing()
    pairing.report(NUMPAD_DECIMAL_SCAN, False, False, False)
    pairing.message(100, VK_DECIMAL, NUMPAD_DECIMAL_SCAN, False, False)
    assert pairing.verdict(1, 100, VK_DECIMAL, False) is False
    assert pairing.misses == 0


def test_a_colon_typed_before_the_stop_does_not_take_the_stops_verdict():
    """A colon is Shift and the full-stop key. Its event is asked about too, in turn."""
    pairing = Pairing()
    _keystroke(pairing, 100, remote=False)  # the experimenter's colon
    _keystroke(pairing, 100, remote=True)  # the participant's stop, in the same clock tick
    assert pairing.verdict(1, 100, PERIOD_VK, False) is False
    assert pairing.verdict(2, 100, PERIOD_VK, False) is True


def test_keystrokes_at_different_times_are_kept_apart():
    pairing = Pairing()
    _keystroke(pairing, 100, remote=False)
    _keystroke(pairing, 140, remote=True)
    assert pairing.verdict(2, 140, PERIOD_VK, False) is True
    assert pairing.verdict(1, 100, PERIOD_VK, False) is False


def test_a_press_and_its_release_each_have_their_own_verdict():
    pairing = Pairing()
    _keystroke(pairing, 100, remote=True)
    _keystroke(pairing, 180, remote=True, released=True)
    assert pairing.verdict(1, 100, PERIOD_VK, False) is True
    assert pairing.verdict(2, 180, PERIOD_VK, True) is True


def test_a_message_with_no_report_leaves_the_others_their_reports():
    pairing = Pairing()
    pairing.report(PERIOD_SCAN, False, False, True)
    pairing.message(90, F5_VK, F5_SCAN, False, False)  # no report of its own
    pairing.message(100, PERIOD_VK, PERIOD_SCAN, False, False)
    assert pairing.verdict(1, 100, PERIOD_VK, False) is True
    assert pairing.misses == 0


def test_reports_whose_key_message_never_came_are_dropped():
    pairing = Pairing()
    pairing.report(F5_SCAN, False, False, False)  # some other window swallowed it
    _keystroke(pairing, 100, remote=True)
    assert pairing.verdict(1, 100, PERIOD_VK, False) is True


def test_the_same_event_asked_twice_takes_one_verdict():
    """A key event propagates to each parent, and the router is asked at every step."""
    pairing = Pairing()
    _keystroke(pairing, 100, remote=False)
    _keystroke(pairing, 100, remote=True)
    assert pairing.verdict(7, 100, PERIOD_VK, False) is False
    assert pairing.verdict(7, 100, PERIOD_VK, False) is False
    assert pairing.verdict(8, 100, PERIOD_VK, False) is True


def test_a_key_event_with_no_verdict_is_the_remotes_and_is_counted():
    """A spurious stop is recoverable; a lost one is not. The miss is logged (N7.D22)."""
    pairing = Pairing()
    assert pairing.verdict(1, 100, PERIOD_VK, False) is True
    assert pairing.misses == 1
