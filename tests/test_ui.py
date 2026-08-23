"""The two windows. SPEC.md 10, 11, 12.4, 16.

Both are driven through real Qt under QT_QPA_PLATFORM=offscreen, which is what SPEC.md 17.1
requires of the whole suite. The experimenter window is fed a real `Session.experimenter_view()`
rather than a hand-written dict, so a field added to the view without being handled here shows
up as a failure rather than as a screen that quietly stops updating.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel

from tatp import config as cfg
from tatp.clock import Clock
from tatp.responder import Responder
from tatp.session import Session
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def session(loaded, tmp_path):
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    config = cfg.Config(**{**loaded.__dict__, "hardware": hardware})
    made = Session(config, "01", 1, "SM", EXAMPLES, clock=Clock(speed=100.0), rng_seed=7)
    made.start()
    yield made
    made.close()


@pytest.fixture
def participant(app, session):
    made = ParticipantWindow(session.config, Responder(session.config.hardware), session.clock)
    made.resize(1280, 800)
    return made


def _press(widget, name):
    key = QT_KEYS[name]
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def _visible_texts(window) -> list[str]:
    return [
        label.text()
        for label in window.findChildren(QLabel)
        if label.isVisibleTo(window) and label.text()
    ]


# -- the participant window --------------------------------------------------------------


def test_it_carries_no_wording_of_its_own(participant, session):
    """SPEC.md 10.4: no user-facing string in any .py file."""
    text = session.config.participant_text
    participant.show_message("standby")
    assert participant.message.text == text["screens"]["standby"]
    participant.show_vas("pain")
    assert participant.vas.question == text["vas"]["pain"]["question"]


def test_a_missing_screen_key_raises_rather_than_showing_a_blank(participant):
    with pytest.raises(KeyError):
        participant.show_message("no_such_screen")


def test_each_screen_is_selected_in_turn(participant):
    participant.show_warning_cue()
    assert participant.stack.currentWidget() is participant.cue
    participant.show_blank()
    assert participant.stack.currentWidget() is participant.message
    assert participant.message.text == ""
    participant.show_vas("pain")
    assert participant.stack.currentWidget() is participant.vas


def test_the_emergency_stop_works_when_the_vas_is_not_showing(participant):
    """SPEC.md 13: it is a stop button, not a rating control."""
    stops = []
    participant.emergency_stop.connect(lambda: stops.append(1))
    participant.show_warning_cue()
    _press(participant, "f5")
    assert stops == [1]
    participant.show_vas("pain")
    _press(participant.vas, "f5")
    assert stops == [1, 1]


def test_escape_is_swallowed_off_the_vas_as_well(participant):
    """SPEC.md 10.1: the play button emits it, and Qt would read it as 'close this window'."""
    participant.show_message("standby")
    event = QKeyEvent(QEvent.KeyPress, QT_KEYS["escape"], Qt.NoModifier)
    participant.keyPressEvent(event)
    assert event.isAccepted()


def test_a_null_screen_index_leaves_the_window_where_it_is(participant, session):
    """Open item 9: null means primary screen, windowed. Never silently fullscreened."""
    participant.place(session.config.hardware["screens"])
    assert not participant.isFullScreen()


def test_an_impossible_screen_index_is_refused_rather_than_wrapped(participant):
    with pytest.raises(IndexError, match="participant_screen_index"):
        participant.place({"participant_screen_index": 99, "participant_fullscreen": True})


def test_the_window_renders_headless(participant):
    participant.show_warning_cue()
    pixmap = participant.grab()
    assert pixmap.width() == 1280
    assert not pixmap.isNull()


# -- the experimenter window -------------------------------------------------------------


@pytest.fixture
def experimenter(app, session):
    """The window over the live view, plus a dict of fields a test can override on top of it.

    Reading the real `experimenter_view()` every refresh is the point: a field added to the view
    and not handled by the window fails here rather than quietly stopping the screen updating.
    """
    held = {"override": {}}
    window = ExperimenterWindow(
        session.config.experimenter_text,
        lambda: {**session.experimenter_view(), **held["override"]},
    )
    window.resize(900, 700)
    return window, held


def test_it_shows_nothing_the_experimenter_may_not_see(experimenter, session):
    """SPEC.md 16 and Bilaga 1 3.3: never the condition, never a rating."""
    window, _ = experimenter
    shown = " ".join(_visible_texts(window))
    assert session.condition not in shown
    for condition in session.config.study1["design"]["conditions"]:
        assert condition not in shown


def test_the_placeholder_banner_is_shown_while_the_wording_is_unapproved(experimenter, session):
    """CLAUDE.md and SPEC.md 12.4: unmissable while `placeholder_text` is true."""
    window, held = experimenter
    assert session.experimenter_view()["placeholder_text"] is True, "still PLACEHOLDER (L4)"
    banner = session.config.experimenter_text["banners"]["placeholder_text"]
    assert banner in _visible_texts(window)

    held["override"] = {"placeholder_text": False}
    window.refresh()
    assert banner not in _visible_texts(window)


def test_the_reduced_capability_banner_names_the_device(experimenter, session):
    window, held = experimenter
    assert not window.reduced_capability_banner.isVisibleTo(window), "the mock sets per-channel"
    held["override"] = {"reduced_capability_device": True}
    window.refresh()
    assert window.reduced_capability_banner.isVisibleTo(window)
    assert session.garment.driver_name in window.reduced_capability_banner.text()


def test_the_session_identity_and_phase_are_shown(experimenter, session):
    window, _ = experimenter
    text = session.config.experimenter_text
    assert session.participant_code in window.identity.text()
    assert session.experimenter_initials in window.identity.text()
    assert text["terms"]["limbs"][session.limb] in window.identity.text()
    assert window.phase.text() == text["phases"][session.phase]
    session.set_phase("pre_sensitisation")
    window.refresh()
    assert window.phase.text() == text["phases"]["pre_sensitisation"]


def test_the_unresolved_open_items_are_on_the_screen(experimenter, session):
    window, held = experimenter
    assert window.open_items.isVisibleTo(window)
    for item in session.config.unresolved:
        assert item.number in window.open_items.text()
    held["override"] = {"unresolved_open_items": []}
    window.refresh()
    assert not window.open_items.isVisibleTo(window)


def test_the_garment_state_is_shown(experimenter, session):
    window, held = experimenter
    text = session.config.experimenter_text["status"]
    assert window.garment.text() == text["connected"]
    held["override"] = {"garment_connected": False}
    window.refresh()
    assert window.garment.text() == text["disconnected"]


def test_it_reads_the_session_only_through_experimenter_view(experimenter):
    """The window holds a reader, not a Session, so it cannot reach Session.condition."""
    window, _ = experimenter
    assert not any(isinstance(value, Session) for value in vars(window).values())
