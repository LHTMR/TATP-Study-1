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
from tatp import screenshots
from tatp.clock import Clock
from tatp.responder import Action, Responder, ResponderError
from tatp.session import Session
from tatp.ui import experimenter as experimenter_ui
from tatp.ui.experimenter import ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import QT_KEYS

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
SPIN_TIMEOUT_S = 5.0
LAPTOP_WIDTH_PX = screenshots.LAPTOP_WIDTH_PX
LAPTOP_HEIGHT_PX = screenshots.LAPTOP_HEIGHT_PX


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
    """What the window itself shows -- not a dialog it owns, which is a window of its own."""
    return [
        label.text()
        for label in window.findChildren(QLabel)
        if label.window() is window and label.isVisibleTo(window) and label.text()
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
    """Open item 9: null means primary screen, windowed. Never silently fullscreened.

    Driven from a crafted value, not the live config: the lab PC's own indices are set there
    (docs/LOG.md N6.16).
    """
    screens = {**session.config.hardware["screens"], "participant_screen_index": None}
    participant.place(screens)
    assert not participant.isFullScreen()


def test_the_experimenter_window_is_placed_on_its_screen(session):
    screens = session.config.hardware["screens"]
    window = ExperimenterWindow(session.config.experimenter_text, session.experimenter_view)
    window.place({**screens, "experimenter_screen_index": None})
    assert not window.isMaximized()
    with pytest.raises(IndexError, match="experimenter_screen_index"):
        window.place({**screens, "experimenter_screen_index": 99})
    window.place({**screens, "experimenter_screen_index": 0})
    assert window.isMaximized()


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


def test_no_response_screen_draws_the_emergency_stop(participant):
    """A response screen that drew the stop button would be inviting the press (SPEC.md 10.9).

    Only the rehearsal points at it, and says so at the call.
    """
    responder = participant.choice.responder
    with pytest.raises(ResponderError, match="never drawn as an option"):
        responder.symbol_for(Action.EMERGENCY_STOP)
    assert responder.symbol_for(Action.EMERGENCY_STOP, pointing_at_stop=True)


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


def test_the_preference_screen_reads_the_buttons_as_the_adjustment_does(participant):
    """Something now moves between patterns (SPEC.md 9 step 6), so a press is drawn and sent."""
    pressed, confirmed = [], []
    participant.adjust_pressed.connect(pressed.append)
    participant.adjust_confirmed.connect(lambda: confirmed.append(True))
    participant.show_preference()
    participant.keyPressEvent(QKeyEvent(QEvent.KeyPress, QT_KEYS["pagedown"], Qt.NoModifier))
    assert participant.control.held == {"right"}
    assert pressed == [Action.INCREASE.value]
    _press(participant, "period")
    assert confirmed == [True]


def test_a_message_screen_reports_the_play_button(participant):
    """"Press ▶ to continue" needs the press to reach whoever is waiting for it."""
    seen = []
    participant.message_confirmed.connect(lambda: seen.append(True))
    participant.show_message("stop_rehearsal_done")
    _press(participant, "period")
    assert seen == [True]
    participant.show_vas("pain")
    _press(participant.vas, "period")
    assert seen == [True], "a confirm on the VAS is the VAS's, not a message's"


def test_the_stop_rehearsal_draws_the_stop_button_and_nothing_else_does(participant, session):
    symbols = session.config.hardware["responder"]["button_symbols"]
    participant.show_message("stop_rehearsal")
    assert participant.message.stop_symbol == symbols["emergency_stop"]
    participant.show_message("emergency_stop")
    assert participant.message.stop_symbol is None
    participant.show_blank()
    assert participant.message.stop_symbol is None


def test_the_warning_cue_announces_itself_for_the_audible_cue(participant):
    seen = []
    participant.warning_cue_shown.connect(lambda: seen.append(True))
    participant.show_warning_cue()
    assert seen == [True]


def test_the_level_adjustment_reads_the_buttons_on_a_text_screen(participant, session):
    pressed = []
    participant.adjust_pressed.connect(pressed.append)
    participant.show_level_adjustment("find_level")
    assert participant.message.text == session.config.participant_text["audio_setup"][
        "find_level"
    ]
    participant.keyPressEvent(QKeyEvent(QEvent.KeyPress, QT_KEYS["pageup"], Qt.NoModifier))
    assert pressed == [Action.DECREASE.value]


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


@pytest.mark.parametrize("shown", [True, False])
def test_the_placeholder_banner_follows_the_view(app, session, shown):
    """CLAUDE.md and SPEC.md 12.4: unmissable while `placeholder_text` is true, absent when not.

    Driven from the flag rather than from whatever the config happens to hold today, so this
    keeps testing the banner as participant wording gets approved.
    """
    text = session.config.experimenter_text
    window = ExperimenterWindow(
        text, lambda: {**session.experimenter_view(), "placeholder_text": shown}
    )
    assert (text["banners"]["placeholder_text"] in _visible_texts(window)) is shown


def test_the_reduced_capability_banner_names_the_garment_in_words(app, session):
    text = session.config.experimenter_text
    window = ExperimenterWindow(
        text, lambda: {**session.experimenter_view(), "reduced_capability_device": True}
    )
    assert window.reduced_capability_banner.isVisibleTo(window)
    name = text["terms"]["garments"][session.config.hardware["garment"]["driver"]]
    assert name in window.reduced_capability_banner.text()
    assert session.garment.driver_name not in window.reduced_capability_banner.text()


def test_a_banner_that_comes_mid_session_is_refused(experimenter):
    """UI_PRINCIPLES.md 3.3. Every banner is settled before the session starts, so the region
    takes only the space of the banners present; one appearing later would move the phase and
    the instruction at exactly the wrong moment, and is refused instead."""
    window, held = experimenter
    held["override"] = {"placeholder_text": True}
    with pytest.raises(AssertionError, match="banners changed"):
        window.refresh()


@pytest.mark.parametrize("language", ["sv", "en"])
@pytest.mark.parametrize("banners", [{}, {"reduced_capability_device": True}])
def test_the_window_fits_the_lab_laptop(app, language, banners):
    """A 1920 x 1080 laptop at 150 % leaves about 1280 x 640 (S's lab review, 24 Sep 2026):
    with no banner, and with the one a pilot on the prototype sleeve always has."""
    text = cfg.load(language, language).experimenter_text
    view = _all_keys(garment_driver="arduino_mosfet", **banners)
    window = ExperimenterWindow(text, lambda: view)
    hint = window.minimumSizeHint()
    assert hint.width() <= LAPTOP_WIDTH_PX and hint.height() <= LAPTOP_HEIGHT_PX, hint


def test_no_banner_leaves_no_empty_band(app, session):
    """A laptop screen has no quarter to spare for banners that are not there (S's lab
    review, 24 Sep 2026)."""
    view = {**session.experimenter_view(), "placeholder_text": False,
            "reduced_capability_device": False, "fit_preview_enabled": False}
    window = ExperimenterWindow(session.config.experimenter_text, lambda: view)
    assert not window.banner_area.isVisibleTo(window)


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


def _hardware(connected=True, faults=(), pressures=None):
    return {"connected": connected, "faults": list(faults), "channel_pressure_kpa": pressures}


def test_the_garment_state_is_shown(experimenter, session):
    window, held = experimenter
    text = session.config.experimenter_text["status"]
    controls = session.config.experimenter_text["controls"]
    assert window.garment.text() == text["connected"]
    assert window.garment_button.text() == controls["disconnect"]
    disconnects = _emitted(window.garment_disconnect_requested)
    window.garment_button.click()
    assert disconnects == [()]

    held["override"] = {"hardware": _hardware(connected=False)}
    window.refresh()
    assert window.garment.text() == text["disconnected"]
    assert window.garment_button.text() == controls["connect"]
    connects = _emitted(window.garment_connect_requested)
    window.garment_button.click()
    assert connects == [()]


def test_it_reads_the_session_only_through_experimenter_view(experimenter):
    """The window holds a reader, not a Session, so it cannot reach Session.condition."""
    window, _ = experimenter
    assert not any(isinstance(value, Session) for value in vars(window).values())


# -- the experimenter window's controls, SPEC.md 11 --------------------------------------


def _all_keys(**overrides) -> dict:
    return screenshots._experimenter_view(**overrides)


@pytest.fixture
def drawn(app, loaded):
    """The window over a hand-built view with every key, for states a session rarely reaches."""
    held = {"view": _all_keys()}
    window = ExperimenterWindow(loaded.experimenter_text, lambda: held["view"])
    window.resize(1280, 800)
    return window, held


def _emitted(signal) -> list:
    seen = []
    signal.connect(lambda *args: seen.append(args))
    return seen


def test_every_action_signal_has_a_control_that_emits_it(drawn):
    """SPEC.md 11: each action the experimenter has is a control on the screen."""
    window, _ = drawn
    window.set_actions_enabled(rebalance=True, fit_decision=True)
    for widget, signal in (
        (window.proceed_button, window.proceed_requested),
        (window.pause_button, window.pause_requested),
        (window.discard_button, window.discard_requested),
        (window.rebalance_button, window.rebalance_requested),
        (window.fit_accept_button, window.fit_accepted),
        (window.garment_button, window.garment_disconnect_requested),
    ):
        seen = _emitted(signal)
        widget.click()
        assert seen == [()], f"{widget.text()} did not emit"


def test_resume_is_enabled_only_while_interrupted(drawn):
    """Interruptions.resume raises when nothing is interrupted, so the button must not offer."""
    window, held = drawn
    assert not window.resume_button.isEnabled()
    assert window.pause_button.isEnabled()
    for kind in ("emergency_stop", "pause"):
        held["view"] = _all_keys(interruption=kind)
        window.refresh()
        assert window.resume_button.isEnabled()
        assert not window.pause_button.isEnabled()
        assert not window.proceed_button.isEnabled()
        assert window.abort_button.isEnabled()
        seen = _emitted(window.resume_requested)
        window.resume_button.click()
        assert seen == [()]
        assert window.alert.text() == window.text["status"][f"interrupted_{kind}"]
    held["view"] = _all_keys()
    window.refresh()
    assert not window.resume_button.isEnabled()
    assert window.alert.text() == ""


@pytest.mark.parametrize("language", ["sv", "en"])
def test_the_interruption_line_fits_its_reserved_height(app, language):
    text = cfg.load(language, language).experimenter_text
    for kind in ("emergency_stop", "pause"):
        view = _all_keys(interruption=kind)
        window = ExperimenterWindow(text, lambda view=view: view)
        window.resize(1280, 800)
        window.show()
        assert window.alert.heightForWidth(window.alert.width()) <= window.alert.height(), (
            f"status.interrupted_{kind} wraps past the reserved line in {language}"
        )


def test_the_window_fits_the_screenshot_size(drawn):
    """At 1280 x 800 nothing is squeezed below its minimum; the grab would grow otherwise."""
    window, _ = drawn
    assert window.minimumSizeHint().height() <= 800


def test_the_interruption_line_does_not_move_the_instruction(drawn):
    window, held = drawn
    window.set_instruction("x")
    window.show()
    before = window.instruction.pos().y()
    held["view"] = _all_keys(interruption="emergency_stop")
    window.refresh()
    assert window.instruction.pos().y() == before


def test_rebalance_and_the_fit_choice_wait_to_be_asked_for(drawn):
    window, _ = drawn
    for widget in (window.rebalance_button, window.fit_accept_button, window.fit_rerun_button):
        assert not widget.isEnabled()
    window.set_actions_enabled(rebalance=True)
    assert window.rebalance_button.isEnabled()
    assert not window.fit_accept_button.isEnabled()
    window.set_actions_enabled(fit_decision=True)
    assert window.fit_accept_button.isEnabled() and window.fit_rerun_button.isEnabled()
    window.set_actions_enabled(rebalance=False, fit_decision=False)
    assert not window.rebalance_button.isEnabled()
    assert not window.fit_accept_button.isEnabled()


def test_an_experimenter_choice_enables_the_controls_it_waits_on(app, session, participant):
    """touchcal's accept/re-run and rebalance questions reach the buttons with no wiring."""
    from tatp.trials import ExperimenterChoice

    window = ExperimenterWindow(session.config.experimenter_text, session.experimenter_view)
    choice = ExperimenterChoice(
        session, participant, window,
        {"accept": window.fit_accepted, "rerun": window.fit_rerun_requested},
        "touchcal_fit_review",
    )
    choice.start()
    assert window.fit_accept_button.isEnabled()
    assert not window.rebalance_button.isEnabled()
    window.fit_accept_button.click()
    assert not window.fit_accept_button.isEnabled(), "disabled again once answered"


def test_abort_asks_for_confirmation_and_a_reason(drawn):
    window, _ = drawn
    seen = _emitted(window.abort_requested)
    dialog = window.open_abort_dialog()
    assert not dialog.confirm.isEnabled(), "an abort with no reason is not offered"
    dialog.reason.setText("participant withdrew")
    dialog.confirm.click()
    assert seen == [("participant withdrew",)]

    dialog = window.open_abort_dialog()
    dialog.reason.setText("changed my mind")
    dialog.cancel.click()
    assert seen == [("participant withdrew",)], "cancelling aborts nothing"


def test_a_rerun_carries_its_reason(drawn):
    window, _ = drawn
    window.set_actions_enabled(fit_decision=True)
    seen = _emitted(window.fit_rerun_requested)
    dialog = window.open_rerun_dialog()
    dialog.reason.setText("filament slipped")
    dialog.confirm.click()
    assert seen == [("filament slipped",)]


def test_a_note_and_a_substitution_are_emitted_and_cleared(drawn):
    window, _ = drawn
    notes, substitutions = _emitted(window.note_entered), _emitted(window.substitution_entered)
    window.note.setText("  participant sneezed ")
    window.note_button.click()
    window.substitution.setText("15")
    window.substitution_button.click()
    assert notes == [("participant sneezed",)]
    assert substitutions == [("15",)]
    assert window.note.text() == window.substitution.text() == ""
    window.note_button.click()
    assert notes == [("participant sneezed",)], "an empty note is not a note"


def test_the_distance_fields_follow_the_configured_path_order(drawn, loaded):
    """The ledger reads the tuple in mapping.path_ids order; the fields come from the text."""
    window, _ = drawn
    assert window.distances.path_ids == loaded.study1["mapping"]["path_ids"]


def test_distances_are_entered_for_a_mapped_phase_and_never_block(drawn):
    window, _ = drawn
    distances = window.distances
    seen = _emitted(window.distances_entered)
    assert not window.distances_button.isEnabled(), "nothing mapped yet"
    assert not distances.enter_button.isEnabled()
    window.set_mapping_phases(["post_sensitisation"])
    assert window.distances_button.isEnabled()
    window.distances_button.click()
    assert distances.isVisible() and not distances.isModal()
    distances.fields[0].setText("42,5")
    distances.fields[2].setText("-3")
    distances.enter_button.click()
    assert seen == [("post_sensitisation", (42.5, None, -3.0, None))]

    # A new mapping while distances are typed changes neither the fields nor the phase.
    window.set_mapping_phases(["post_sensitisation", "post_intervention"])
    assert distances.phase.currentData() == "post_sensitisation"
    assert distances.fields[0].text() == "42,5"

    # With nothing typed, the latest phase is selected.
    distances.clear()
    window.set_mapping_phases(["post_sensitisation", "post_intervention", "rekindle"])
    assert distances.phase.currentData() == "rekindle", "the latest when nothing is typed"


def test_an_unfinished_distance_is_not_sent(drawn):
    window, _ = drawn
    seen = _emitted(window.distances_entered)
    window.set_mapping_phases(["post_sensitisation"])
    window.distances.fields[1].setText("12.")
    window.distances.enter_button.click()
    assert seen == []


@pytest.mark.parametrize(
    "event, key",
    [
        ({"kind": "block", "label_key": "block", "block_index": 3, "block_type": "touch",
          "due_in_s": 125.2, "overdue": False}, "next_event"),
        ({"kind": "block", "label_key": "block", "block_index": 3, "block_type": "touch",
          "due_in_s": -4.0, "overdue": False}, "block_due"),
        ({"kind": "block", "label_key": "block", "block_index": 3, "block_type": "touch",
          "due_in_s": -400.0, "overdue": True}, "block_overdue"),
        ({"kind": "rekindle", "label_key": "rekindle", "block_index": None, "block_type": None,
          "due_in_s": -1.0, "overdue": False}, "event_due"),
    ],
)
def test_the_countdown_states(drawn, event, key):
    window, held = drawn
    held["view"] = _all_keys(next_event=event)
    window.refresh()
    status = window.text["status"]
    if key == "next_event":
        assert window.countdown.text() == status["next_event"].format(
            phase=status["block_label"].format(
                block=3, value=window.text["terms"]["block_types"]["touch"]
            ),
            time="02:06",
        )
    elif key == "event_due":
        assert window.countdown.text() == status["event_due"].format(
            phase=window.text["phases"]["rekindle"]
        )
    else:
        assert window.countdown.text() == status[key].format(block=3)


def test_the_countdown_is_redrawn_by_its_timer(app, loaded):
    """LOG N6.20: the clock ticks on its own, at the configured interval."""
    ticks = {"n": 0}

    def view():
        ticks["n"] += 1
        return _all_keys(elapsed_s=float(ticks["n"]))

    interval = loaded.hardware["screens"]["experimenter_refresh_interval_s"]
    window = ExperimenterWindow(loaded.experimenter_text, view, refresh_interval_s=interval)
    assert window.timer.isActive()
    first = ticks["n"]
    _spin(lambda: ticks["n"] > first)


def test_the_hardware_panel_shows_pressure_only_when_given(drawn):
    window, held = drawn
    held["view"] = _all_keys(hardware=_hardware(pressures={1: 12.0, 2: 30.25}))
    window.refresh()
    assert window.pressures.isVisibleTo(window)
    assert "30.2" in window.pressures.text() or "30.3" in window.pressures.text()

    held["view"] = _all_keys(hardware=_hardware(pressures=None, faults=["valve 3 stuck"]))
    window.refresh()
    assert not window.pressures.isVisibleTo(window)
    assert window.pressures.text() == ""
    assert "valve 3 stuck" in window.faults.text()


def test_no_pressure_is_drawn_during_the_intervention_even_if_the_view_leaks_it(drawn):
    """SPEC.md 16. The view withholds it; the window holds the same line on its own."""
    window, held = drawn
    for phase in ("intervention", "rekindle"):
        held["view"] = _all_keys(phase=phase, hardware=_hardware(pressures={1: 55.0}))
        window.refresh()
        assert window.pressures.text() == ""


def test_a_fault_from_the_intervention_stays_withheld_afterwards(drawn):
    """Shown in full after the rekindle, it would reveal the channel just the same."""
    window, held = drawn
    first, later = "channel 4: valve stuck", "channel 2: sensor offline"
    held["view"] = _all_keys(phase="intervention", hardware=_hardware(faults=[first]))
    window.refresh()
    held["view"] = _all_keys(phase="post_intervention",
                             hardware=_hardware(faults=[first, later]))
    window.refresh()
    assert "channel 4" not in window.faults.text() + window.faults.toolTip()
    assert "channel 2" in window.faults.text(), "a fault raised afterwards is shown, in full"


def test_refresh_does_not_refit_unchanged_text(drawn, monkeypatch):
    window, _ = drawn
    window.set_instruction("apply")
    calls = []
    monkeypatch.setattr(experimenter_ui, "_fit_to", lambda *args: calls.append(args))
    window.refresh()
    window.refresh()
    assert calls == []
    window.set_status("received")
    assert calls, "a changed text is fitted"


def test_a_fault_in_the_intervention_is_shown_without_its_channel(drawn):
    """Which channel faulted could say which pattern is running (SPEC.md 16)."""
    window, held = drawn
    held["view"] = _all_keys(phase="intervention",
                             hardware=_hardware(faults=["channel 4: valve stuck"]))
    window.refresh()
    assert window.faults.isVisibleTo(window)
    assert "channel 4" not in window.faults.text()
    assert "channel 4" not in window.faults.toolTip()
    assert "1" in window.faults.text()


def test_the_zone_diagram_marks_the_target_and_a_new_step_clears_it(drawn):
    window, _ = drawn
    window.set_instruction("apply")
    window.set_target("secondary", 4)
    assert window.zone.region == "secondary"
    assert "4" in window.target.text()
    window.set_instruction("next")
    assert window.zone.region is None
    assert window.target.text() == ""


def test_a_pinprick_trial_marks_its_zone(rig_trial):
    window, _ = rig_trial
    assert window.zone.region == "primary"


@pytest.mark.parametrize("enabled", [True, False])
def test_the_fit_preview_banner_follows_the_view(app, loaded, enabled):
    view = _all_keys(fit_preview_enabled=enabled)
    window = ExperimenterWindow(loaded.experimenter_text, lambda: view)
    assert window.fit_preview_banner.isVisibleTo(window) is enabled


# -- blinding: no rating and no condition on the lab screen, SPEC.md 11, 11.1, 16 ---------

RATING_PRESSES = 3  # right presses after the first: 75 % + 3 x 0.5 % = 76.5 %
RATING_SHOWN = "76.5"


@pytest.fixture
def rig_trial(app, session, participant):
    """One real pinprick trial rated at a known, distinctive value."""
    from tatp.pinprick import Application, PinprickTrial

    window = ExperimenterWindow(
        session.config.experimenter_text,
        lambda: {**session.experimenter_view(), "unresolved_open_items": []},
    )
    window.resize(1280, 800)
    session.set_phase("pre_sensitisation")
    application = Application(
        protocol="short", region="primary", trial_index=1, purpose="measure",
        filament_label_g=session.config.study1["pinprick"]["start_filament_label_g_session1_pre_s"],
        site_index=1,
    )
    trial = PinprickTrial(session, participant, window, application)
    done = []
    trial.finished.connect(done.append)
    trial.start()
    # The trial is held here too: a parentless QObject nobody references is collected, and its
    # connections with it.
    return window, (participant, done, trial)


def test_the_window_never_draws_a_rating(rig_trial):
    """Bilaga 1 3.3. The rating is in the data file; nothing on the lab screen carries it."""
    window, (participant, done, _) = rig_trial
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    _press(participant.vas, "pagedown")
    for _ in range(RATING_PRESSES):
        _press(participant.vas, "pagedown")
    assert participant.vas.state.percent == float(RATING_SHOWN)
    _press(participant.vas, "period")
    assert len(done) == 1, "the trial ends when the participant confirms"
    window.refresh()
    shown = " ".join(_visible_texts(window))
    assert RATING_SHOWN not in shown
    assert "76" not in shown


def _f40_fit():
    from tatp.pinprick import F40Fit, LongResult

    result = LongResult(
        phase="pre_sensitisation", region="primary", run_index=1,
        start_filament_label_g="26", start_source="config_default", f40_mn=321.0,
        chosen_filament_label_g="26", chosen_force_mn=255.0, out_of_range=False,
        out_of_range_direction="", capped=False, applications_total=12,
        applications_measure=9, ordinal_rho=0.71,
    )
    return F40Fit(result, 51.6, 40.0, ((147.0, 23.5), (255.0, 37.5), (588.0, 58.5)))


def _touch_fit():
    from tatp import touchcal_maths as maths
    from tatp.touchcal import FitReady

    fit = maths.RatingFit(
        fit_form=maths.LOG_PRESSURE, intercept=-40.0, slope=50.0, r_squared=0.87,
        residual_sd=6.5, span_vas=60.0, spearman_rho=0.9, bracket_min_kpa=10.0,
        bracket_max_kpa=160.0,
    )
    return FitReady(
        run_index=2, points=((10.0, 12.5, False), (40.0, 41.5, False), (0.0, 3.0, True),
                             (160.0, 71.5, False)),
        fit=fit, r_squared=0.87, residual_sd=6.5, monotonic=True, stage1_pass=True,
        stage1_failures=(), p20_kpa=15.8, p30_kpa=25.1, p80_kpa=158.5,
    )


def test_a_fit_is_refused_while_the_preview_is_off_and_nothing_is_drawn(drawn):
    """SPEC.md 11.1: the preview is the one exception, and only while it is on."""
    window, _ = drawn
    before = window.grab().toImage()
    for fit in (_f40_fit(), _touch_fit()):
        with pytest.raises(experimenter_ui.FitPreviewRefused):
            window.show_fit_preview(fit)
    preview = window.fit_preview
    assert not preview.isVisible()
    assert preview.plot.points == ()
    assert preview.quality.text() == preview.derived.text() == ""
    assert not window.fit_accept_button.isEnabled()
    shown = " ".join(_visible_texts(window) + _visible_texts(preview))
    for rating in ("23.5", "37.5", "58.5", "41.5", "71.5", "321"):
        assert rating not in shown
    assert window.grab().toImage() == before


@pytest.mark.parametrize("make_fit", [_f40_fit, _touch_fit])
def test_the_enabled_preview_draws_the_fit_and_hides_it_again(app, loaded, make_fit):
    view = _all_keys(fit_preview_enabled=True)
    window = ExperimenterWindow(loaded.experimenter_text, lambda: view)
    window.resize(1280, 800)
    window.show_fit_preview(make_fit())
    preview = window.fit_preview
    assert preview.isVisible() and not preview.isModal()
    assert preview.plot.points and preview.plot.line
    assert window.fit_accept_button.isEnabled() and window.fit_rerun_button.isEnabled()
    assert preview.accept_button.isEnabled() and preview.rerun_button.isEnabled()
    assert preview.derived.text() and preview.quality.text()
    seen = _emitted(window.fit_accepted)
    preview.accept_button.click()
    assert seen == [()], "the preview's Accept is the window's"

    window.hide_fit_preview()
    assert not preview.isVisible()
    assert preview.plot.points == ()
    assert preview.derived.text() == preview.quality.text() == ""
    assert not window.fit_accept_button.isEnabled()


def test_the_main_window_never_carries_the_fit(drawn):
    """Even with the preview on and open, the ratings are in the preview window only."""
    window, held = drawn
    held["view"] = _all_keys(fit_preview_enabled=True)
    window.show_fit_preview(_f40_fit())
    shown = " ".join(_visible_texts(window))
    for rating in ("23.5", "37.5", "58.5", "321"):
        assert rating not in shown


def test_catch_trials_are_left_off_the_touch_plot(drawn):
    window, held = drawn
    held["view"] = _all_keys(fit_preview_enabled=True)
    window.show_fit_preview(_touch_fit())
    assert (0.0, 3.0) not in window.fit_preview.plot.points
    assert len(window.fit_preview.plot.points) == 3


def test_a_long_instruction_steps_down_the_scale_and_moves_nothing(drawn):
    window, _ = drawn
    window.show()
    window.set_instruction("x")
    status_y = window.status.pos().y()
    assert window.instruction.font().pointSize() == experimenter_ui.SIZE_HEADLINE
    longest = max(window.text["instructions"].values(), key=len)
    window.set_instruction(longest)
    assert window.instruction.font().pointSize() < experimenter_ui.SIZE_HEADLINE
    assert window.instruction.heightForWidth(window.instruction.width()) <= (
        window.instruction.height()
    ), "the longest instruction does not fit even at the smallest size"
    assert window.status.pos().y() == status_y


def test_nothing_drawn_differs_between_conditions(app, session, loaded):
    """SPEC.md 16, UI_PRINCIPLES.md 2.3. The same session under each condition, pixel for pixel.

    The intervention and the rekindle are the phases where the garment delivers something that
    depends on the condition, so each condition is given a different pressure there.
    """
    def still_view():
        # The clock is the one thing allowed to change between two grabs.
        return {**session.experimenter_view(), "elapsed_s": 0.0, "t_session_s": 0.0}

    window = ExperimenterWindow(session.config.experimenter_text, still_view)
    window.resize(1280, 800)
    for phase in ("intervention", "rekindle"):
        session.set_phase(phase)
        images, views = [], []
        for index, condition in enumerate(loaded.study1["design"]["conditions"]):
            session._condition = condition
            # Each condition delivers differently; none of it may reach the lab screen.
            session.garment.set_pressure(1, float(index + 1))
            views.append(still_view())
            window.refresh()
            images.append(window.grab().toImage())
        assert all(v == views[0] for v in views), f"the view differs by condition in {phase}"
        assert all(image == images[0] for image in images), f"the screen differs in {phase}"
