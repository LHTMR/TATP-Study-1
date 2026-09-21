"""The two windows. SPEC.md 10, 11, 12.4, 16.

Both are driven through real Qt under QT_QPA_PLATFORM=offscreen, which is what SPEC.md 17.1
requires of the whole suite. The experimenter window is fed a real `Session.experimenter_view()`
rather than a hand-written dict, so a field added to the view without being handled here shows
up as a failure rather than as a screen that quietly stops updating.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel

from tatp import config as cfg
from tatp.clock import Clock
from tatp.responder import Action, Responder, ResponderError
from tatp.session import Session
from tatp.ui import experimenter as experimenter_ui
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
SPIN_TIMEOUT_S = 5.0


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


# -- the drawn choice screen, SPEC.md 10.8 -------------------------------------------------


def _spin(condition) -> None:
    """Run the event loop until `condition`, which is how the feedback and gap timers fire."""
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the choice screen never reached the expected state")
        QApplication.processEvents()
        time.sleep(0.001)


def test_the_choice_screen_carries_no_wording_of_its_own(participant, session):
    """SPEC.md 10.4, again: the question and both option labels come from the text file."""
    text = session.config.participant_text["choices"]["comparison"]
    participant.show_choice("comparison")
    assert participant.stack.currentWidget() is participant.choice
    assert participant.choice.question == text["question"]
    assert participant.choice.labels == {"left": text["left"], "right": text["right"]}


def test_a_missing_choice_key_raises_rather_than_showing_a_blank(participant):
    with pytest.raises(KeyError):
        participant.show_choice("no_such_choice")


def test_the_drawn_buttons_carry_the_devices_own_symbols(participant, session):
    """UI_PRINCIPLES.md 5.9: relabel the remote and the screen follows, with no code change."""
    symbols = session.config.hardware["responder"]["button_symbols"]
    responder = participant.choice.responder
    assert responder.symbol_for(Action.DECREASE) == symbols["decrease"]
    assert responder.symbol_for(Action.INCREASE) == symbols["increase"]


def test_no_symbol_is_drawn_for_the_emergency_stop(participant):
    """A screen that drew the stop button would be inviting the press."""
    with pytest.raises(ResponderError, match="button_symbols"):
        participant.choice.responder.symbol_for(Action.EMERGENCY_STOP)


def test_the_press_is_the_response_and_there_is_no_confirm(participant):
    """UI_PRINCIPLES.md 5.12. The play button must not commit a choice nobody made."""
    chosen = []
    participant.chosen.connect(chosen.append)
    participant.show_choice("comparison")
    participant.accept_choice()

    _press(participant, "period")
    assert chosen == [], "the confirm key produced a response on a screen with no confirm"

    _press(participant, "pagedown")
    assert chosen == ["right"]


def test_a_press_before_the_stimuli_are_finished_is_reported_not_counted(participant):
    """The answer is to a pair, so a press during the first half answers nothing."""
    chosen, early = [], []
    participant.chosen.connect(chosen.append)
    participant.pressed_before_accepting.connect(lambda: early.append(1))

    participant.show_choice("comparison")
    participant.emphasise_choice("left")
    _press(participant, "pageup")
    assert chosen == []
    assert early == [1]

    participant.accept_choice()
    _press(participant, "pageup")
    assert chosen == ["left"]


def test_a_choice_cannot_be_revised(participant):
    """No confirm means no window in which a choice is made but not committed."""
    chosen = []
    participant.chosen.connect(chosen.append)
    participant.show_choice("comparison")
    participant.accept_choice()

    _press(participant, "pageup")
    _press(participant, "pagedown")
    assert chosen == ["left"]


def test_emphasis_marks_one_button_and_accepting_clears_it(participant):
    """UI_PRINCIPLES.md 5.11: the emphasis is coincident with the stimulus, not a legend."""
    participant.show_choice("comparison")
    assert participant.choice.emphasised is None

    participant.emphasise_choice("right")
    assert participant.choice.emphasised == "right"

    participant.accept_choice()
    assert participant.choice.emphasised is None


def test_an_emphasis_on_neither_side_is_refused(participant):
    participant.show_choice("comparison")
    with pytest.raises(KeyError):
        participant.emphasise_choice("middle")


def test_the_chosen_button_is_shown_back_then_the_screen_blanks(participant):
    """UI_PRINCIPLES.md 1.10: one trial is told from the next without counting them."""
    gaps = []
    participant.choice_gap_elapsed.connect(lambda: gaps.append(1))
    participant.show_choice("comparison")
    participant.accept_choice()
    _press(participant, "pagedown")

    # Shown back first: the response is emitted on the press, the acknowledgement outlives it.
    assert participant.choice.selected == "right"
    assert not participant.choice.blank

    _spin(lambda: participant.choice.blank)
    _spin(lambda: gaps == [1])


def test_leaving_the_choice_screen_stops_it_reading_buttons(participant):
    """As for the adjustment screen: any route off it disarms the input, an abort included."""
    chosen = []
    participant.chosen.connect(chosen.append)
    participant.show_choice("comparison")
    participant.accept_choice()

    participant.show_emergency_stop()
    _press(participant, "pagedown")
    assert chosen == []


def test_the_emergency_stop_works_on_the_choice_screen(participant):
    """SPEC.md 13: on every screen, and this one reads two other keys."""
    stops = []
    participant.emergency_stop.connect(lambda: stops.append(1))
    participant.show_choice("comparison")
    participant.accept_choice()
    _press(participant, "f5")
    assert stops == [1]


def test_the_choice_screen_renders_in_every_state(participant):
    """Each state is a different picture, so a state that stopped drawing would be caught."""
    participant.show_choice("comparison")
    waiting = participant.grab().toImage()

    participant.emphasise_choice("left")
    emphasised = participant.grab().toImage()
    assert emphasised != waiting

    participant.choice.selected = "right"
    participant.choice.update()
    assert participant.grab().toImage() not in (waiting, emphasised)


# -- the adjustment screen's drawn buttons, UI_PRINCIPLES.md 5.8 and 5.10 -----------------


def test_the_adjustment_screen_carries_no_wording_of_its_own(participant, session):
    text = session.config.participant_text
    participant.show_adjustment("most_pleasant")
    assert participant.stack.currentWidget() is participant.control
    assert participant.control.target == text["adjust_targets"]["most_pleasant"]
    controls = text["participant_controls"]["adjust"]
    assert participant.control.labels == {"left": controls["left"], "right": controls["right"]}
    assert participant.control.confirm == controls["confirm"]


def test_the_preference_screen_carries_no_wording_of_its_own(participant, session):
    controls = session.config.participant_text["participant_controls"]["preference"]
    participant.show_preference()
    assert participant.stack.currentWidget() is participant.control
    assert participant.control.target == controls["intro"]
    assert participant.control.labels == {"left": controls["left"], "right": controls["right"]}
    assert participant.control.confirm == controls["confirm"]


def test_a_held_button_is_drawn_pressed_until_it_is_released(participant):
    """Press-and-hold, so the pressed state lasts exactly as long as the hold."""
    participant.show_adjustment("most_pleasant")
    key = QT_KEYS["pagedown"]
    participant.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    assert participant.control.held == {"right"}
    unheld = participant.grab().toImage()
    participant.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))
    assert participant.control.held == set()
    assert participant.grab().toImage() != unheld, "the pressed state was not drawn"


def test_the_preference_screen_does_not_read_the_buttons(participant):
    """Nothing moves between patterns yet, so a pressed state would be a false report."""
    participant.show_preference()
    participant.keyPressEvent(QKeyEvent(QEvent.KeyPress, QT_KEYS["pagedown"], Qt.NoModifier))
    assert participant.control.held == set()


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


def test_the_placeholder_banner_follows_the_view_in_both_directions(experimenter, session):
    """CLAUDE.md and SPEC.md 12.4: unmissable while `placeholder_text` is true, gone when not.

    Driven from the flag rather than from whatever the config happens to hold today, so this
    keeps testing the banner as participant wording gets approved.
    """
    window, held = experimenter
    banner = session.config.experimenter_text["banners"]["placeholder_text"]

    held["override"] = {"placeholder_text": True}
    window.refresh()
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


def test_nothing_moves_when_the_banners_appear(experimenter):
    """UI_PRINCIPLES.md 3.3. The banner region is reserved whether or not a banner is in it.

    The experimenter learns where the phase and the instruction sit. If they slid down at the
    moment a warning appeared, the warning would cost a re-read of the whole screen at exactly
    the wrong time.
    """
    window, held = experimenter
    held["override"] = {"placeholder_text": False, "reduced_capability_device": False}
    window.refresh()
    window.show()
    quiet = (window.phase.pos().y(), window.instruction.pos().y())

    held["override"] = {"placeholder_text": True, "reduced_capability_device": True}
    window.refresh()
    assert (window.phase.pos().y(), window.instruction.pos().y()) == quiet


def test_both_banners_fit_the_reserved_region(experimenter):
    """The reserved height is only honest if the warnings actually fit inside it.

    A longer wording, or a second language, would otherwise clip a SPEC.md 12.4 banner rather
    than push the layout -- which is worse than the reflow it was reserved to prevent.
    """
    window, held = experimenter
    held["override"] = {"placeholder_text": True, "reduced_capability_device": True}
    window.refresh()
    window.show()
    width = window.placeholder_banner.width()
    needed = sum(
        banner.heightForWidth(width)
        for banner in (window.placeholder_banner, window.reduced_capability_banner)
    )
    assert needed <= experimenter_ui.BANNER_AREA_PX, (
        f"the two banners need {needed} px but only {experimenter_ui.BANNER_AREA_PX} "
        f"is reserved -- raise BANNER_AREA_PX"
    )


def test_the_two_banners_do_not_look_alike():
    """UI_PRINCIPLES.md 3.4: different responses required, so different colours."""
    assert experimenter_ui.PLACEHOLDER_COLOUR != experimenter_ui.REDUCED_CAPABILITY_COLOUR


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
