"""The two windows. SPEC.md 10, 11, 12.4, 16.

Both are driven through real Qt under QT_QPA_PLATFORM=offscreen, which is what SPEC.md 17.1
requires of the whole suite. The experimenter window is fed a real `Session.experimenter_view()`
rather than a hand-written dict, so a field added to the view without being handled here shows
up as a failure rather than as a screen that quietly stops updating.
"""

from __future__ import annotations

import string
import time

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFont, QFontInfo, QFontMetrics, QImage, QKeyEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from tatp import config as cfg
from tatp import screenshots
from tatp.clock import Clock
from tatp.responder import Action, Responder, ResponderError
from tatp.session import Session
from tatp.ui import experimenter as experimenter_ui
from tatp.ui import participant as participant_ui
from tatp.ui import widgets
from tatp.ui.experimenter import CONFIRMED, NOW, QUERIED, ExperimenterWindow
from tatp.ui.participant import ParticipantWindow
from tatp.ui.vas import BACKGROUND, QT_KEYS, QUESTION_Y_FRACTION, SIDE_MARGIN_FRACTION

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"
SPIN_TIMEOUT_S = 5.0
LAPTOP_WIDTH_PX = screenshots.LAPTOP_WIDTH_PX
LAPTOP_HEIGHT_PX = screenshots.LAPTOP_HEIGHT_PX
# The instructions shown with the zone diagram beside them (S, 21 Oct 2026).
WITH_DIAGRAM = (
    "prepare_filament", "prepare_brush", "apply_filament", "apply_brush",
    "rating_next_filament", "rating_next_either", "rating_next_brush", "next_filament",
    "next_brush", "ready_long", "ready_short", "ready_brush", "mapping_ready", "mapping_path",
)
# The share of a banner's width a headline may take, leaving room for a machine that renders
# the same font a little wider.
BANNER_WIDTH_MARGIN = 0.95
# How far a centred line's ink may sit from the screen's centre: glyph side bearings make the
# ink a few pixels asymmetric even when the line is centred exactly.
CENTRE_TOLERANCE_PX = 6


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def session(loaded, tmp_path):
    hardware = {**loaded.hardware, "data": {**loaded.hardware["data"],
                                            "folder": str(tmp_path / "data"),
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


def test_one_message_replacing_another_is_repainted(participant, app, monkeypatch):
    """The first lab run: "The session will start shortly." stayed up after the welcome was
    shown, because the message screen draws its own text and stayed the current widget, so
    nothing asked Qt to paint it again. The participant never saw "Press ▶ to continue".
    """
    painted = []
    paint = participant.message.paintEvent
    monkeypatch.setattr(
        participant.message, "paintEvent", lambda event: (painted.append(1), paint(event))
    )
    participant.show_message("session_starting")
    participant.show()
    app.processEvents()
    painted.clear()
    participant.show_message("welcome")
    app.processEvents()
    participant.close()
    assert painted


def test_the_emergency_stop_works_when_the_vas_is_not_showing(participant):
    """SPEC.md 13: it is a stop button, not a rating control."""
    stops = []
    participant.emergency_stop.connect(lambda: stops.append(1))
    participant.show_warning_cue()
    _press(participant, "period")
    assert stops == [1]
    participant.show_vas("pain")
    _press(participant.vas, "period")
    assert stops == [1, 1]


def test_escape_is_swallowed_off_the_vas_as_well(participant):
    """SPEC.md 10.1: every other ▶ is escape, and Qt would read it as 'close this window'."""
    participant.show_message("standby")
    event = QKeyEvent(QEvent.KeyPress, QT_KEYS["escape"], Qt.NoModifier)
    participant.keyPressEvent(event)
    assert event.isAccepted()


def test_the_play_buttons_escape_half_dismisses_a_message(participant):
    """The lab R400 sends f5 and escape on alternate presses (docs/LOG.md N7.F1)."""
    confirmed = []
    participant.message_confirmed.connect(lambda: confirmed.append(1))
    participant.show_message("welcome")
    _press(participant, "escape")
    assert confirmed == [1]


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

    _press(participant, "f5")
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
    _press(participant, "period")
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
    participant.show_preference(1, 3)
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
    participant.adjust_pressed.connect(lambda value, _event_ms: pressed.append(value))
    participant.adjust_confirmed.connect(lambda: confirmed.append(True))
    participant.show_preference(1, 3)
    participant.keyPressEvent(QKeyEvent(QEvent.KeyPress, QT_KEYS["pagedown"], Qt.NoModifier))
    assert participant.control.held == {"right"}
    assert pressed == [Action.INCREASE.value]
    _press(participant, "f5")
    assert confirmed == [True]


def test_a_held_stop_button_is_one_stop(participant):
    """The R400's stop button auto-repeats when held; a repeat is not another press."""
    stops = []
    participant.emergency_stop.connect(lambda: stops.append(True))
    participant.show_message("welcome")
    key = QT_KEYS["period"]
    participant.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    for _ in range(3):
        participant.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, "", True))
    assert stops == [True]


def test_a_message_screen_reports_the_play_button(participant):
    """"Press ▶ to continue" needs the press to reach whoever is waiting for it."""
    seen = []
    participant.message_confirmed.connect(lambda: seen.append(True))
    participant.show_message("stop_rehearsal_done")
    _press(participant, "f5")
    assert seen == [True]
    participant.show_vas("pain")
    _press(participant.vas, "f5")
    assert seen == [True], "a confirm on the VAS is the VAS's, not a message's"


class _StepClock(Clock):
    """A clock whose elapsed time moves only when the test says, so the lockout is exact."""

    def __init__(self):
        super().__init__()
        self.now_s = 0.0

    def elapsed_s(self) -> float:
        return self.now_s


@pytest.fixture
def stepped(app, session):
    clock = _StepClock()
    made = ParticipantWindow(session.config, Responder(session.config.hardware), clock)
    made.resize(1280, 800)
    return made, clock, session.config.hardware["responder"]["repeat_confirm_lockout_s"]


def test_a_press_carried_over_cannot_dismiss_the_next_message_unread(stepped):
    """docs/LOG.md N7.U15: a double tap on ▶ confirms one screen, not two."""
    window, clock, lockout_s = stepped
    confirmed, ignored = [], []
    window.message_confirmed.connect(lambda: confirmed.append(True))
    window.confirm_carried_over.connect(lambda: ignored.append(True))
    window.show_message("welcome")
    _press(window, "f5")
    window.show_message("stop_rehearsal_done")
    clock.now_s += lockout_s / 2
    _press(window, "f5")
    assert (confirmed, ignored) == ([True], [True]), "the second tap was the first's"
    clock.now_s += lockout_s
    _press(window, "f5")
    assert confirmed == [True, True], "a press after the lockout is the new screen's"


def test_a_press_on_a_screen_that_asks_for_none_starts_no_lockout(stepped):
    """A ▶ during a stimulus's blank screen is nobody's, so it is neither logged as carried
    over nor able to swallow the next screen's press (docs/LOG.md N7.U15)."""
    window, clock, lockout_s = stepped
    confirmed, ignored = [], []
    window.message_confirmed.connect(lambda: confirmed.append(True))
    window.confirm_carried_over.connect(lambda: ignored.append(True))
    window.show_blank()
    _press(window, "f5")
    _press(window, "f5")
    window.show_message("stop_rehearsal_done")
    _press(window, "f5")
    assert ignored == [], "nothing on a blank screen is carried over"
    assert len(confirmed) == 3, "and the screen that asks takes its press at once"


def test_a_press_carried_over_cannot_confirm_an_adjustment_at_its_start(stepped):
    """Carried onto an adjustment, it would record the starting level as the answer."""
    window, clock, lockout_s = stepped
    confirmed = []
    window.adjust_confirmed.connect(lambda: confirmed.append(True))
    window.show_message("welcome")
    _press(window, "f5")
    window.show_level_adjustment("find_level")
    _press(window, "f5")
    assert confirmed == []
    clock.now_s += lockout_s
    _press(window, "f5")
    assert confirmed == [True]


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


def test_the_warning_cue_is_its_text_key_and_nothing_else(participant):
    """SPEC.md 10.5 (S, 15 Oct 2026): words that explain themselves, from the text file, rather
    than a circle the welcome had to explain. Checked on the drawn pixels: the text is laid out
    where every participant message is (UI_PRINCIPLES.md 5.5) -- inside the shared side
    margins, starting on the first line below the message top, centred across -- and nothing
    else is on the screen."""
    participant.show_warning_cue()
    assert participant.cue.text == participant.text["warning_cue"]
    image = participant.cue.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    data = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
    pixels = data.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, : image.width()]
    ink_rows, ink_columns = np.nonzero(np.any(pixels[:, :, :3] != BACKGROUND.red(), axis=2))
    assert ink_rows.size, "nothing was drawn"
    width, height = image.width(), image.height()
    margin = int(width * SIDE_MARGIN_FRACTION)
    top = int(height * QUESTION_Y_FRACTION)
    font = QFont(participant.cue.font())
    font.setPointSize(participant_ui.BUTTON_SYMBOL_POINT_SIZE)
    line_px = QFontMetrics(font).height()
    assert ink_columns.min() >= margin and ink_columns.max() < width - margin
    assert top <= ink_rows.min() < top + line_px, "not at the message position"
    assert ink_rows.max() < top + line_px, "one short line, nothing else on the screen"
    centre_px = (ink_columns.min() + ink_columns.max()) / 2
    assert abs(centre_px - width / 2) <= CENTRE_TOLERANCE_PX


def test_the_level_adjustment_reads_the_buttons_on_a_text_screen(participant, session):
    pressed = []
    participant.adjust_pressed.connect(lambda value, _event_ms: pressed.append(value))
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
    assert name in window.reduced_capability_banner.toolTip()
    assert session.garment.driver_name not in window.reduced_capability_banner.text()


def test_a_banner_that_comes_mid_session_is_refused(experimenter, session):
    """UI_PRINCIPLES.md 3.3. Every banner is settled before the session starts, so the region
    takes only the space of the banners present; one appearing later would move the phase and
    the instruction at exactly the wrong moment, and is refused instead. The flag is flipped
    from whatever the config holds, so this holds as placeholders come and go."""
    window, held = experimenter
    held["override"] = {"placeholder_text": not session.config.has_placeholder_text()}
    with pytest.raises(AssertionError, match="banners changed"):
        window.refresh()


@pytest.mark.parametrize("language", ["sv", "en"])
@pytest.mark.parametrize("banners", [{}, {"reduced_capability_device": True}])
def test_the_window_fits_the_lab_laptop(app, language, banners):
    """A 1920 x 1080 laptop at 150 % leaves about 1280 x 640 (S's lab review, 24 Sep 2026):
    with no banner, and with the one a pilot on the prototype sleeve always has. As a session
    sets it up: the timeline, and the channel display shown (LOG N7.F16h, N7.F16i)."""
    view = _all_keys(garment_driver="arduino_mosfet", **banners)
    window = screenshots._session_window(cfg.load(language, language), lambda: view)
    window.garment_display.setVisible(True)
    hint = window.minimumSizeHint()
    assert hint.width() <= LAPTOP_WIDTH_PX and hint.height() <= LAPTOP_HEIGHT_PX, hint


@pytest.mark.parametrize("language", ["sv", "en"])
def test_every_instruction_is_read_at_the_large_size_on_the_lab_laptop(app, language):
    """The instruction steps down the type scale only for a value longer than the sample's,
    never for its own wording: read-aloud scripts were squeezed to body size (LOG N7.F17e).
    Each field is filled with eight characters, longer than any filament, site or count."""
    config = cfg.load(language, language)
    view = _all_keys()
    window = screenshots._session_window(config, lambda: view)
    window.resize(LAPTOP_WIDTH_PX, LAPTOP_HEIGHT_PX)
    window.show()
    QApplication.processEvents()
    label, width = window.instruction, window._left_width()
    squeezed = []
    for key, template in config.experimenter_text["instructions"].items():
        values = {name.split("[")[0]: "XXXXXXXX"
                  for _, name, _, _ in string.Formatter().parse(template) if name}
        values = {name: value for name, value in values.items()
                  if name not in ("controls", "say")}
        while True:
            # A quoted `say:` line brings fields of its own, named only when it is filled.
            try:
                text = cfg.instruction(config, key, **values)
                break
            except KeyError as missing:
                values[missing.args[0]] = "XXXXXXXX"
        widgets.sized(label, widgets.SIZE_LARGE)
        label.setText(text)
        if label.heightForWidth(width) > label.height():
            squeezed.append(key)
    assert squeezed == []


def test_no_banner_leaves_no_empty_band(app, session):
    """A laptop screen has no quarter to spare for banners that are not there (S's lab
    review, 24 Sep 2026). The open-items line is in the banner region since the 15 Oct 2026
    pilot review, so none are open here either."""
    view = {**session.experimenter_view(), "placeholder_text": False,
            "reduced_capability_device": False, "fit_preview_enabled": False, "demo": False,
            "unresolved_open_items": []}
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
    """By number on one line, cut with an ellipsis when they do not all fit (since the 15 Oct
    2026 pilot review); every one is in the tooltip."""
    window, held = experimenter
    assert window.open_items.isVisibleTo(window)
    shown = window.open_items.text()
    numbers = [item.number for item in session.config.unresolved]
    assert numbers[0] in shown
    assert all(number in shown for number in numbers) or shown.endswith("…")
    for item in session.config.unresolved:
        assert str(item) in window.open_items.toolTip()
    held["override"] = {"unresolved_open_items": []}
    window.refresh()
    assert not window.open_items.isVisibleTo(window)


def _hardware(connected=True, faults=(), pressures=None, link_lost=False, on=None):
    return {"connected": connected, "link_lost": link_lost, "faults": list(faults),
            "channel_pressure_kpa": pressures,
            "channels_on": None if pressures is None else list(on or [])}


def test_the_garment_state_is_shown(experimenter, session):
    window, held = experimenter
    text = session.config.experimenter_text["status"]
    controls = session.config.experimenter_text["controls"]
    assert window.garment.text() == text["connected"]
    assert window.garment_button.text() == controls["disconnect"]
    disconnects = _emitted(window.garment_disconnect_requested)
    window.garment_button.click()
    assert disconnects == [], "asked first (LOG N7.F17e)"
    window.findChildren(widgets.MessageDialog)[-1].accept()
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
    window.set_actions_enabled(rebalance=True, fit_decision=True, discard=True)
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
        if widget in (window.garment_button, window.discard_button):  # asked first (N7.F17e)
            window.findChildren(widgets.MessageDialog)[-1].accept()
        assert seen == [()], f"{widget.text()} did not emit"


def _offered(window, widget) -> bool:
    """Shown and pressable. A control not offered is hidden in a place kept for it, and
    disabled too (S, 15 Oct 2026 pilot review), so a test of only one would miss half."""
    return widget.isVisibleTo(window) and widget.isEnabled()


def test_resume_is_offered_only_while_interrupted(drawn):
    """Interruptions.resume raises when nothing is interrupted, so the button must not offer.
    Was "enabled only": since the 15 Oct 2026 pilot review a control not offered is hidden,
    and Pause and Resume each keep a slot of their own."""
    window, held = drawn
    assert not _offered(window, window.resume_button)
    assert _offered(window, window.pause_button)
    for kind in ("emergency_stop", "pause"):
        held["view"] = _all_keys(interruption=kind)
        window.refresh()
        assert _offered(window, window.resume_button)
        assert not window.pause_button.isVisibleTo(window)
        # Next step stays in sight, greyed, while interrupted (LOG N7.U10a).
        assert window.proceed_button.isVisibleTo(window)
        assert not window.proceed_button.isEnabled()
        assert _offered(window, window.abort_button)
        seen = _emitted(window.resume_requested)
        window.resume_button.click()
        assert seen == [()]
        assert window.alert.text() == window.text["status"][f"interrupted_{kind}"].format(
            controls=window.text["controls"]
        )
    held["view"] = _all_keys()
    window.refresh()
    assert not window.resume_button.isVisibleTo(window)
    assert _offered(window, window.proceed_button)
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


class _Filled(dict):
    """A value for every field an instruction has: two digits, where none is given."""

    def __missing__(self, key):
        return "00"


LANGUAGE_PAIRS = [("sv", "sv"), ("en", "en"), ("sv", "en"), ("en", "sv")]


def _instructions_to_show(config) -> dict[str, str]:
    """Every instruction as `config.instruction` leaves it for the step to fill, the mapping
    script with the first path's line as the screen shows them together."""
    keys = [key for key in config.experimenter_text["instructions"]
            if key not in ("monofilament", "mapping_script")]
    shown = {key: cfg.instruction_template(config, key) for key in keys}
    script = cfg.instruction_template(config, "mapping_script")
    shown["mapping_ready"] = f"{script}\n\n{shown['mapping_ready']}"
    return shown


@pytest.mark.parametrize("participant, experimenter", LANGUAGE_PAIRS)
def test_every_instruction_fits_its_region(app, participant, experimenter):
    """Each instruction, filled with its longest values, fits the instruction region at some
    size of the scale rather than running off its bottom (LOG N7.F11b). The sentences said
    aloud are in the participant's language, so a Swedish one inside an English instruction
    is measured too."""
    config = cfg.load(participant, experimenter)
    text = config.experimenter_text
    terms = text["terms"]
    window = ExperimenterWindow(text, lambda: _all_keys())
    window.resize(1280, 800)
    window.show()
    longest_anchors = max(
        (scale["anchors"] for scale in config.participant_text["vas"].values()), key=len
    )
    values = _Filled(
        anchors=" / ".join(a["label"] for a in longest_anchors),
        explanation=max(config.say["proportionality"].values(), key=len),
        region=max(terms["regions"].values(), key=len),
        path=max(terms["mapping_paths"].values(), key=len),
        value=", ".join(terms["stage1"].values()),
        filament="1.4",
        ready=cfg.instruction_template(config, "ready_short"),
    )
    for key, template in _instructions_to_show(config).items():
        window.set_instruction(template.format_map(values), NOW)
        # Those shown with the zone diagram beside them, at the narrower width it leaves.
        if key in WITH_DIAGRAM:
            window.set_target("primary", 1)
        label = window.instruction
        assert label.heightForWidth(window._left_width()) <= label.height(), (
            f"instructions.{key} runs past its region ({participant} participant, "
            f"{experimenter} experimenter)"
        )


@pytest.mark.parametrize("participant, experimenter", LANGUAGE_PAIRS)
def test_every_instruction_names_buttons_by_their_labels(participant, experimenter):
    """Code review of N7.F11b: an instruction names a button only through {controls[...]},
    so renaming a control cannot leave a dangling name; and every instruction formats."""
    config = cfg.load(participant, experimenter)
    text = config.experimenter_text
    labels = [label for label in text["controls"].values() if "{" not in label]
    for key, raw in text["instructions"].items():
        for label in labels:
            assert label not in raw, f"instructions.{key} types the button {label!r}"
        filled = cfg.instruction_template(config, key).format_map(_Filled())
        assert "{" not in filled and "}" not in filled, f"instructions.{key}: {filled!r}"
    for kind in ("emergency_stop", "pause"):
        # The one button these name; "Paused" holds the word Pause, which is no button name.
        assert text["controls"]["resume"] not in text["status"][f"interrupted_{kind}"]


def test_a_warning_outlives_the_routine_status_and_one_stage_start(drawn):
    """15 Oct 2026 pilot review: a warning set as the status was replaced by the next
    "Waiting for..." within seconds. Several are raised as a stage ends, so one survives the
    next stage's start and goes at the one after."""
    window, _ = drawn
    text = window.text
    warning = text["warnings"]["application_cap"].format(value="20")
    window.set_warning(warning)
    window.set_status(text["instructions"]["await_participant"])
    shown = window.status.text()
    assert warning in shown and text["instructions"]["await_participant"] in shown
    window.set_status(text["instructions"]["response_received"])
    assert warning in window.status.text()
    window.new_stage()
    assert warning in window.status.text()
    # The status was the stage before's, and went with it (S, 20 Oct 2026; LOG N7.F16c).
    assert text["instructions"]["response_received"] not in window.status.text()
    window.new_stage()
    assert warning not in window.status.text()
    assert window.status.text() == ""


@pytest.mark.parametrize("language", ["sv", "en"])
def test_every_warning_the_status_region_carries_fits_it(app, language):
    """The routine line gives way if both do not fit; the warning itself always fits."""
    config = cfg.load(language, language)
    text = config.experimenter_text
    warnings = text["warnings"]
    window = ExperimenterWindow(text, lambda: _all_keys())
    window.resize(1280, 800)
    window.show()
    values = _Filled()
    shown = [warnings[key].format_map(values) for key in (
        "catch_trials_felt", "masking_at_ceiling", "masking_failed",
        "masking_failed_after_earplugs", "equalisation_mismatch", "application_cap",
        "mapping_limit",
    )]
    # The long protocol can raise its two together, as `LongProtocol._warn` joins them.
    out_of_range = warnings["out_of_range"].format(
        value=max(text["terms"]["out_of_range"].values(), key=len)
    )
    shown.append(f"{out_of_range} {warnings['application_cap'].format_map(values)}")
    window.set_status(text["instructions"]["await_participant"])
    for filled in shown:
        window.set_warning(filled)
        assert filled in window.status.text()
        assert window.status.heightForWidth(window._status_width()) <= (
            window.status.height()), f"{filled!r} runs past the status region in {language}"


@pytest.mark.parametrize("language", ["sv", "en"])
def test_what_became_of_a_substitution_fits_beside_it(app, language):
    """S, 21 Oct 2026: a message beside what was entered, not in the middle of the screen."""
    config = cfg.load(language, language)
    text = config.experimenter_text
    window = screenshots._session_window(config, lambda: _all_keys())
    window.resize(LAPTOP_WIDTH_PX, LAPTOP_HEIGHT_PX)
    window.show()
    warnings = text["warnings"]
    for key, kind in (("substitution_recorded", CONFIRMED), ("substitution_not_lower", QUERIED),
                      ("substitution_not_recorded", QUERIED)):
        shown = warnings[key].format(filament="0.008", value="0.008",
                                     controls=text["controls"])
        window.show_substitution(shown, kind)
        QApplication.processEvents()
        line = window.substitution_message
        assert line.heightForWidth(line.width()) <= line.height(), (key, language)


def test_a_warning_is_dimmed_with_its_step_while_interrupted(drawn):
    """The status region dims while the session is interrupted (N7.F11a); the warning's own
    colour, set inside the text, dims with it, and comes back on the resume."""
    window, held = drawn
    window.set_warning("a warning")
    assert widgets.WARNING_COLOUR in window.status.text()
    held["view"] = _all_keys(interruption="emergency_stop")
    window.refresh()
    assert widgets.WARNING_COLOUR not in window.status.text()
    assert widgets.DISABLED in window.status.text()
    held["view"] = _all_keys()
    window.refresh()
    assert widgets.WARNING_COLOUR in window.status.text()


def test_a_cleared_warning_leaves_the_status(drawn):
    window, _ = drawn
    window.set_status("received")
    window.set_warning("a warning")
    window.clear_warning()
    assert window.status.text() == "received"


def test_the_window_fits_the_screenshot_size(drawn):
    """At 1280 x 800 nothing is squeezed below its minimum; the grab would grow otherwise."""
    window, _ = drawn
    assert window.minimumSizeHint().height() <= 800


def test_the_interruption_line_does_not_move_the_instruction(drawn):
    window, held = drawn
    window.set_instruction("x", experimenter_ui.NOW)
    window.show()
    before = window.instruction.pos().y()
    held["view"] = _all_keys(interruption="emergency_stop")
    window.refresh()
    assert window.instruction.pos().y() == before


def test_the_instruction_starts_at_the_same_place_in_every_step(drawn):
    """It was centred in its column's spare height, so its first line jumped about 100 px
    between a filament trial and a countdown (15 Oct 2026 pilot review; UI_PRINCIPLES.md
    5.5)."""
    window, _ = drawn
    window.show()
    window.set_instruction("x", experimenter_ui.NOW)
    plain = window.instruction.mapTo(window, window.instruction.rect().topLeft())
    window.set_target("primary", 3, filament=True)
    window.set_status("y")
    with_technique = window.instruction.mapTo(window, window.instruction.rect().topLeft())
    assert plain == with_technique


def test_nothing_moves_when_a_control_or_entry_is_offered(drawn):
    """UI_PRINCIPLES.md 3.3: every control that comes and goes keeps its place."""
    window, held = drawn
    window.show()
    watched = (window.proceed_button, window.abort_button, window.note, window.garment_button,
               window.instruction)

    def places():
        return [widget.mapTo(window, widget.rect().topLeft()) for widget in watched]

    before = places()
    window.set_actions_enabled(rebalance=True, fit_decision=True, discard=True,
                               substitution=True, skip_calibration=True,
                               recalibrate_rebalance=True, recalibrate_restart=True)
    window.set_mapping_phases(["post_sensitisation"])
    window.set_target("primary", 3, filament=True)
    assert places() == before
    held["view"] = _all_keys(interruption="emergency_stop",
                             hardware=_hardware(pressures={1: 40.0}, faults=["f"]))
    window.refresh()
    assert places() == before
    # The garment button takes on its emphasis when it reads Connect without changing size,
    # so Skip calibration above it stays put.
    QApplication.processEvents()
    skip = window.skip_button.mapTo(window, QPoint(0, 0))
    height = window.garment_button.height()
    held["view"] = _all_keys(hardware=_hardware(connected=False))
    window.refresh()
    QApplication.processEvents()
    assert places() == before
    assert window.garment_button.height() == height
    assert window.skip_button.mapTo(window, QPoint(0, 0)) == skip


def test_a_hidden_control_leaves_the_focus_with_the_window(drawn):
    """Hiding the control that has the focus made Qt pass it on: after Pause, to Abort, so a
    Space press opened the abort dialog. The window takes it, never a control or a text field
    (under any_keyboard a focused field takes the participant's keys, docs/LOG.md N7.I1)."""
    window, held = drawn
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    window.pause_button.setFocus()
    assert window.pause_button.hasFocus()
    held["view"] = _all_keys(interruption="pause")
    window.refresh()
    assert QApplication.focusWidget() is window
    window.resume_button.setFocus()
    held["view"] = _all_keys()
    window.refresh()
    assert QApplication.focusWidget() is window
    window.set_actions_enabled(substitution=True)
    window.substitution.setFocus()
    assert window.withdraw_substitution() == ""
    assert QApplication.focusWidget() is window


def test_withdrawing_the_substitution_hands_back_an_unrecorded_choice(drawn):
    window, _ = drawn
    window.set_filaments(["8", "15", "26"])
    window.set_actions_enabled(substitution=True)
    window.substitution.setCurrentIndex(window.substitution.findData("15"))
    with pytest.raises(AssertionError, match="withdraw_substitution"):
        window.set_actions_enabled(substitution=False)
    assert window.withdraw_substitution() == "15"
    assert window.substitution.currentData() == ""
    assert not window.substitution.isVisibleTo(window)
    window.refresh()
    assert window.withdraw_substitution() == "", "handed back once only"


def test_a_long_open_items_line_is_cut_visibly(app):
    """One line, so a long list is cut -- with an ellipsis that says so, and the whole list in
    the tooltip."""
    loaded = cfg.load("sv", "sv")
    items = [f"[L{n}] {'lång sammanfattning ' * 3}" for n in range(1, 61)]
    window = ExperimenterWindow(loaded.experimenter_text,
                                lambda: _all_keys(unresolved_open_items=items))
    window.resize(LAPTOP_WIDTH_PX, LAPTOP_HEIGHT_PX)
    window.refresh()
    shown = window.open_items.text()
    assert shown.endswith("…")
    assert window.open_items.fontMetrics().horizontalAdvance(shown) <= (
        LAPTOP_WIDTH_PX - 2 * experimenter_ui.MARGIN_PX
    )
    assert all(item in window.open_items.toolTip() for item in items)


def test_next_step_looks_the_same_whatever_is_awaited(drawn):
    """Its emphasis must not follow what a step awaits: at a touch start that could differ by
    condition (SPEC.md 16)."""
    window, _ = drawn
    style = window.proceed_button.styleSheet()
    assert style == widgets.primary_button_style()
    for awaited in (dict(discard=True), dict(rebalance=True), dict(fit_decision=True),
                    dict(discard=False, rebalance=False, fit_decision=False)):
        window.set_actions_enabled(**awaited)
        assert window.proceed_button.styleSheet() == style
        assert _offered(window, window.proceed_button)


def test_next_step_is_offered_only_while_a_press_would_do_something(drawn):
    """S, 20 Oct 2026 (LOG N7.F16d): "a lot of the time Next step doesn't do anything". It is
    pressable exactly while the rig says a go is awaited, and Space presses it."""
    window, _ = drawn
    awaited = {"now": False}
    window.set_proceed_source(lambda: awaited["now"])
    assert window.proceed_button.isVisibleTo(window)
    assert not window.proceed_button.isEnabled()
    seen = _emitted(window.proceed_requested)
    window._proceed_key()
    assert seen == []
    awaited["now"] = True
    window.refresh()
    assert _offered(window, window.proceed_button)
    assert window.proceed_shortcut.key() == QKeySequence(Qt.Key_Space)
    window.proceed_button.click()
    assert seen == [()]


@pytest.mark.parametrize("key, signal", [(Qt.Key_Space, "proceed_requested"),
                                         (Qt.Key_P, "pause_requested")])
def test_the_keys_work_whichever_window_is_active(app, loaded, key, signal):
    """S, 21 Oct 2026: "none of the experimenter shortcuts work". On one screen the
    participant's window is above this one, and once it was clicked it had the keys: the keys
    now work across the program."""
    window = ExperimenterWindow(loaded.experimenter_text, lambda: _all_keys())
    window.set_proceed_source(lambda: True)
    window.show()
    other = QWidget()
    other.show()
    other.activateWindow()
    QTest.qWaitForWindowActive(other)
    assert QApplication.activeWindow() is other
    seen = _emitted(getattr(window, signal))
    QTest.keyClick(other, key)
    QApplication.processEvents()
    assert seen == [()]
    other.close()
    window.close()


def test_a_text_field_keeps_its_keys(app, loaded):
    """A note being typed takes its spaces and letters: they never press Next or Pause."""
    window = ExperimenterWindow(loaded.experimenter_text, lambda: _all_keys())
    window.set_proceed_source(lambda: True)
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.note.setFocus()
    seen = _emitted(window.proceed_requested) + _emitted(window.pause_requested)
    QTest.keyClicks(window.note, "P ")
    assert window.note.text() == "P "
    assert seen == []
    window.close()


def test_the_step_on_hold_is_dimmed_while_interrupted(drawn):
    window, held = drawn
    running = (window.instruction.styleSheet(), window.status.styleSheet())
    held["view"] = _all_keys(interruption="emergency_stop")
    window.refresh()
    assert (window.instruction.styleSheet(), window.status.styleSheet()) != running
    assert widgets.FOREGROUND not in window.instruction.styleSheet()
    held["view"] = _all_keys()
    window.refresh()
    assert (window.instruction.styleSheet(), window.status.styleSheet()) == running


def test_the_zone_diagram_is_shown_only_with_a_target_beside_its_instruction(drawn):
    """S, 21 Oct 2026: "bigger and below/connected to the instructions so that it is part of
    the instructions": beside it, as tall as its region, and the instruction narrower then."""
    window, _ = drawn
    assert not window.zone.isVisibleTo(window)
    full = window._left_width()
    window.set_target("secondary", 2)
    assert window.zone.isVisibleTo(window)
    assert window.zone.height() > experimenter_ui.INSTRUCTION_LINES * window.instruction.font(
        ).pointSize(), "at least as tall as the instruction's lines"
    assert window._left_width() < full
    window.set_instruction("next", experimenter_ui.NOW)
    assert not window.zone.isVisibleTo(window)
    assert window._left_width() == full


def test_the_session_clock_is_secondary(drawn):
    """Looked up, not watched: small and grey beside who and where (15 Oct 2026 pilot)."""
    window, _ = drawn
    assert window.elapsed.font().pointSize() == widgets.SIZE_SMALL
    assert window.countdown.font().pointSize() == widgets.SIZE_LARGE


def test_open_items_appearing_mid_session_are_refused(app, loaded):
    """Like a banner (UI_PRINCIPLES.md 3.3): the banner region has no room kept for them."""
    held = {"view": _all_keys()}
    window = ExperimenterWindow(loaded.experimenter_text, lambda: held["view"])
    assert not window.open_items.isVisibleTo(window)
    held["view"] = _all_keys(unresolved_open_items=["[L3] audio"])
    with pytest.raises(AssertionError, match="open items appeared"):
        window.refresh()


def test_open_items_sit_in_the_banner_region(experimenter):
    window, _ = experimenter
    assert window.open_items.parentWidget() is window.banner_area
    assert window.banner_area.isVisibleTo(window)


@pytest.mark.parametrize("language", ["sv", "en"])
def test_every_banner_is_one_line_at_the_laptop_width(app, language):
    """One line each, the detail in the tooltip (15 Oct 2026 pilot review). A banner is cut
    rather than wrapped, so its headline must fit the narrowest screen the window is used on,
    with the longest garment name.

    Measured in the study's own font, which `tests/conftest.py` installs as the lab PC draws
    it (`tatp/ui/application.py`), with a margin for rendering differences between machines.
    """
    loaded = cfg.load(language, language)
    text = loaded.experimenter_text
    window = ExperimenterWindow(text, _all_keys)
    banners = text["banners"]
    available = BANNER_WIDTH_MARGIN * (
        LAPTOP_WIDTH_PX - 2 * experimenter_ui.MARGIN_PX - 2 * widgets.BANNER_PADDING_PX
    )
    font = window.placeholder_banner.font()
    assert QFontInfo(font).family() == loaded.hardware["screens"]["font_families"][0]
    font.setBold(True)
    metrics = QFontMetrics(font)
    headlines = [banners["placeholder_text"], banners["fit_preview"], banners["demo"]] + [
        banners["reduced_capability"].format(value=name)
        for name in text["terms"]["garments"].values()
    ]
    for headline in headlines:
        assert metrics.horizontalAdvance(headline) <= available, headline
    for key in ("placeholder_text", "reduced_capability", "fit_preview"):
        assert banners[f"{key}_detail"], key


def test_rebalance_and_the_fit_choice_wait_to_be_asked_for(drawn):
    """Hidden, not only disabled, until asked for (15 Oct 2026 pilot review)."""
    window, _ = drawn
    for widget in (window.rebalance_button, window.fit_accept_button, window.fit_rerun_button):
        assert not widget.isVisibleTo(window) and not widget.isEnabled()
    window.set_actions_enabled(rebalance=True)
    assert _offered(window, window.rebalance_button)
    assert not window.fit_accept_button.isVisibleTo(window)
    window.set_actions_enabled(fit_decision=True)
    assert _offered(window, window.fit_accept_button)
    assert _offered(window, window.fit_rerun_button)
    window.set_actions_enabled(rebalance=False, fit_decision=False)
    assert not window.rebalance_button.isVisibleTo(window)
    assert not window.fit_accept_button.isVisibleTo(window)


def test_the_recalibration_is_offered_running_or_stopped_never_paused(drawn):
    """docs/LOG.md N7.F12a1: while running and beside Resume after a stop, not during the
    experimenter's own pause; one control for both paths (S, 21 Oct 2026), in the place of
    the calibration's own rematch, which wins it when offered."""
    window, held = drawn
    button = window.recalibrate_button
    window.set_actions_enabled(recalibrate_rebalance=True, recalibrate_restart=True)
    for kind in (None, "emergency_stop"):
        held["view"] = _all_keys(interruption=kind)
        window.refresh()
        assert _offered(window, button), kind
    held["view"] = _all_keys(interruption="pause")
    window.refresh()
    assert not button.isVisibleTo(window)
    held["view"] = _all_keys()
    window.refresh()
    assert (window.controls.getItemPosition(window.controls.indexOf(window.rebalance_button))
            == window.controls.getItemPosition(window.controls.indexOf(button)))
    window.set_actions_enabled(rebalance=True)
    assert not button.isVisibleTo(window), "the rematch wins the place"
    assert _offered(window, window.rebalance_button)
    window.set_actions_enabled(rebalance=False, recalibrate_rebalance=False)
    assert _offered(window, button), "either path alone offers it"
    window.set_actions_enabled(recalibrate_restart=False)
    assert not button.isVisibleTo(window), "nothing to take"
    # Restart is not offered beside the procedure's own Re-run, which does the same free
    # (review of N7.F18i).
    window.set_actions_enabled(fit_rerun=True, recalibrate_restart=True)
    assert not button.isVisibleTo(window), "the re-run is the restart here"
    window.set_actions_enabled(recalibrate_rebalance=True)
    assert window.recalibration_dialog().actions.keys() == {"rebalance"}
    window.set_actions_enabled(fit_rerun=False, closed=True)
    assert not button.isVisibleTo(window), "none once closed"


def test_the_used_up_line_shows_only_while_stopped(drawn):
    window, held = drawn
    window.set_actions_enabled(recalibration_used=True)
    assert not window.recalibration_used.isVisibleTo(window), "running: nothing to explain"
    held["view"] = _all_keys(interruption="emergency_stop")
    window.refresh()
    assert window.recalibration_used.isVisibleTo(window)
    assert window.recalibration_used.text() == window.text["status"][
        "recalibration_used"].format(controls=window.text["controls"])


def test_a_recalibration_asks_what_to_repeat_and_why(drawn):
    """S, 21 Oct 2026: "the different options (which parts to repeat) should be clearer"."""
    window, held = drawn
    dialogs = window.text["dialogs"]
    reasons = dialogs["recalibration_reasons"]
    seen = _emitted(window.recalibration_requested)
    window.set_actions_enabled(recalibrate_rebalance=True, recalibrate_restart=True)
    for choice in ("rebalance", "restart"):
        dialog = window.open_recalibration_dialog()
        assert list(dialog.actions) == ["rebalance", "restart"]
        assert list(dialog.options) == list(reasons)
        assert dialog.windowTitle() == window.recalibrate_button.text()
        dialog.options["channel_uneven"].click()
        assert not dialog.confirm.isEnabled(), "not without what to repeat"
        dialog.actions[choice].click()
        assert dialog.confirm.isEnabled()
        dialog.options["too_strong"].click()
        dialog.options["channel_uneven"].click()
        assert [key for key, option in dialog.options.items() if option.isChecked()] == [
            "channel_uneven"], "one reason at a time"
        dialog.confirm.click()
        assert seen[-1] == (choice, "channel_uneven")
    window.set_actions_enabled(recalibrate_rebalance=False)
    dialog = window.open_recalibration_dialog()
    assert list(dialog.actions) == ["restart"], "only what can be taken"
    assert dialog.action() == "restart", "chosen already, being the only one"
    dialog.options["other"].click()
    dialog.cancel.click()
    assert len(seen) == 2, "cancelling chooses nothing"


@pytest.mark.parametrize("language", ["sv", "en"])
def test_the_recalibration_used_line_is_one_line_at_the_laptop_width(app, language):
    text = cfg.load(language, language).experimenter_text
    window = ExperimenterWindow(text, lambda: _all_keys(interruption="emergency_stop"))
    window.resize(LAPTOP_WIDTH_PX, LAPTOP_HEIGHT_PX)
    window.set_actions_enabled(recalibration_used=True)
    window.show()
    QApplication.processEvents()
    line = window.recalibration_used
    assert line.fontMetrics().horizontalAdvance(line.text()) <= line.width(), language


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
    assert _offered(window, window.fit_accept_button)
    assert not window.rebalance_button.isVisibleTo(window)
    window.fit_accept_button.click()
    assert not window.fit_accept_button.isVisibleTo(window), "hidden again once answered"


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


def test_play_before_the_marker_says_what_to_do_until_the_marker_moves(participant):
    """A press that did nothing visible read as a lost one (LOG N7.F17e)."""
    vas = participant.vas
    vas.show_scale("pain", participant.text["vas"]["pain"])
    assert vas.training == ""
    _press(vas, "f5")
    assert vas.training == participant.text["vas_marker_hint"]
    _press(vas, "pagedown")
    assert vas.training == "", "gone with the press that moves the marker"


def test_abort_is_withdrawn_once_the_session_is_closed(drawn):
    """Code review of N7.F17e: an aborted session waits on its end screen, and a second abort
    ran on the closed session."""
    window, _ = drawn
    assert _offered(window, window.abort_button)
    window.set_actions_enabled(closed=True)
    assert not window.abort_button.isVisibleTo(window) and not window.abort_button.isEnabled()


def test_the_participant_is_not_awaited_through_a_pause(drawn):
    """Code review of N7.F17e: the no-response wait ran on through a pause, and a resumed
    trial carried the old start."""
    window, held = drawn
    window.set_no_response_s(60.0)
    awaiting = window.text["instructions"]["await_participant"]
    window.set_status(awaiting)
    window._awaited_since_s -= 120.0  # two minutes waited
    held["view"] = _all_keys(interruption="pause")
    window.refresh()
    assert window._awaited_since_s is None and window._no_response_shown is None
    held["view"] = _all_keys()
    window.set_status(awaiting)  # the repeated trial asks again
    window.refresh()
    assert time.monotonic() - window._awaited_since_s < 60.0, "timed afresh from the resume"
    assert window._no_response_shown is None


def test_opening_the_abort_pauses_first(drawn):
    """LOG N7.F17e: the garment goes to zero while the reason is typed, and nothing runs on
    behind the dialog. Not a second pause over a stop already in place."""
    window, held = drawn
    pauses = _emitted(window.pause_requested)
    window.open_abort_dialog().reject()
    assert pauses == [()]
    held["view"] = _all_keys(interruption="pause")
    window.refresh()
    window.open_abort_dialog().reject()
    assert pauses == [()]


def test_the_note_field_asks_for_a_note_again_after_saying_one_was_saved(app, drawn):
    window, _ = drawn
    window.set_note_saved_s(0.01)
    window.confirm_note("12:34:56")
    assert "12:34:56" in window.note.placeholderText()
    deadline = time.monotonic() + SPIN_TIMEOUT_S
    while window.note.placeholderText() != window.text["controls"]["note"]:
        assert time.monotonic() < deadline, "the saved note's time was left up"
        QApplication.processEvents()


def test_the_rerun_reason_confirms_with_enter_and_each_recalibration_says_what_it_repeats(
        drawn):
    window, _ = drawn
    assert window.rerun_dialog().confirm.isDefault()
    window.set_actions_enabled(recalibrate_rebalance=True, recalibrate_restart=True)
    dialog = window.recalibration_dialog()
    dialogs = window.text["dialogs"]
    shown = {widget.text() for widget in dialog.findChildren(QLabel)}
    for choice in ("rebalance", "restart"):
        assert dialog.actions[choice].text() == dialogs["recalibrate_choices"][choice]
        assert dialogs["recalibrate_choices_detail"][choice] in shown


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
    window.set_filaments(["8", "15", "26"])
    window.set_actions_enabled(substitution=True)
    window.substitution.setCurrentIndex(window.substitution.findData("15"))
    window.substitution_button.click()
    assert notes == [("participant sneezed",)]
    assert substitutions == [("15",)]
    assert window.note.text() == "" and window.substitution.currentData() == ""
    window.substitution_button.click()
    assert substitutions == [("15",)], "nothing chosen is nothing recorded"
    window.note_button.click()
    assert notes == [("participant sneezed",)], "an empty note is not a note"


def test_the_distance_fields_follow_the_configured_path_order(drawn, loaded):
    """The ledger reads the tuple in mapping.path_ids order; the fields come from the text."""
    window, _ = drawn
    assert window.distances.path_ids == loaded.study1["mapping"]["path_ids"]


def test_distances_are_entered_in_the_window_against_their_own_time_point(drawn):
    """S, 21 Oct 2026: embedded, not a window of its own; and a column per time point, since
    one set of fields with a choice of time point sent post-intervention's distances as
    post-sensitisation's corrections in S's demo."""
    window, _ = drawn
    distances = window.distances
    seen = _emitted(window.distances_entered)
    assert not distances.isVisibleTo(window), "nothing mapped yet"
    assert distances.parent() is not None and not distances.isWindow()
    window.set_mapping_phases(["post_sensitisation"])
    assert _offered(window, distances)
    distances.fields("post_sensitisation")[0].setText("42,5")
    distances.fields("post_sensitisation")[2].setText("-3")
    distances.enter_button.click()
    assert seen == [("post_sensitisation", (42.5, None, -3.0, None))]

    # A new mapping adds its own column and leaves what is typed where it was.
    window.set_mapping_phases(["post_sensitisation", "post_intervention"])
    assert distances.fields("post_sensitisation")[0].text() == "42,5"
    distances.fields("post_intervention")[1].setText("31")
    distances.fields("post_intervention")[1].returnPressed.emit()
    assert seen[-1] == ("post_intervention", (None, 31.0, None, None))
    # Only what changed is sent again: saving one time point never re-enters another's, which
    # would confirm a queried value nobody entered again (review of N7.F18f).
    assert len(seen) == 2
    distances.fields("post_intervention")[2].setText("40")
    distances.enter_button.click()
    assert seen[-1] == ("post_intervention", (None, None, 40.0, None))
    # Enter in a field sends it again, unchanged: that is how a query is confirmed.
    distances.fields("post_sensitisation")[0].returnPressed.emit()
    assert seen[-1] == ("post_sensitisation", (42.5, None, None, None))
    unit = window.text["distances"]["unit"]
    assert distances.fields("post_intervention")[0].placeholderText() == unit


def test_what_became_of_a_distance_is_said_beside_it(drawn):
    window, _ = drawn
    window.set_mapping_phases(["post_sensitisation"])
    box = window.distances
    box.show_outcome("post_sensitisation", {1: 42.0}, {2: 4.0}, "queried", QUERIED)
    fields = box.fields("post_sensitisation")
    assert widgets.TARGET_COLOUR in fields[0].styleSheet(), "recorded"
    assert widgets.WARNING_COLOUR in fields[1].styleSheet(), "queried"
    assert fields[2].styleSheet() == "", "nothing yet"
    assert box.message.text() == "queried"
    assert widgets.WARNING_COLOUR in box.message.styleSheet()


@pytest.mark.parametrize("language", ["sv", "en"])
def test_what_the_distances_box_says_fits_its_lines(app, language):
    """Its column is narrow (S, 21 Oct 2026: the distances beside the garment), so what it
    says is held to its lines: a query, and all four recorded at once."""
    text = cfg.load(language, language).experimenter_text
    words, short = text["distances"], text["terms"]["mapping_paths_short"]
    line = widgets.label(widgets.SIZE_SMALL, wrap=True)
    room = line.fontMetrics().lineSpacing() * experimenter_ui.DISTANCE_MESSAGE_LINES
    values = ", ".join(words["value"].format(path=name, value="123.5")
                       for name in short.values())
    for shown in (words["inside_primary"].format(value="12.5"),
                  words["too_far"].format(value="1234.5"),
                  words["recorded"].format(phase=text["timeline"]["post_intervention"],
                                           values=values)):
        line.setText(shown)
        assert line.heightForWidth(experimenter_ui.DISTANCES_COLUMN_PX) <= room, shown


def test_an_unfinished_distance_is_not_sent(drawn):
    window, _ = drawn
    seen = _emitted(window.distances_entered)
    window.set_mapping_phases(["post_sensitisation"])
    window.distances.fields("post_sensitisation")[1].setText("12.")
    window.distances.enter_button.click()
    assert seen == []


@pytest.mark.parametrize(
    "event, key",
    [
        ({"kind": "block", "label_key": "block", "block_index": 3, "block_type": "touch",
          "due_in_s": 125.2, "due_soon": False, "overdue": False}, "next_event"),
        ({"kind": "block", "label_key": "block", "block_index": 3, "block_type": "touch",
          "due_in_s": 25.2, "due_soon": True, "overdue": False}, "block_due_soon"),
        ({"kind": "block", "label_key": "block", "block_index": 3, "block_type": "touch",
          "due_in_s": -4.0, "due_soon": True, "overdue": False}, "block_due"),
        ({"kind": "block", "label_key": "block", "block_index": 3, "block_type": "touch",
          "due_in_s": -400.0, "due_soon": True, "overdue": True}, "block_overdue"),
        ({"kind": "rekindle", "label_key": "rekindle", "block_index": None, "block_type": None,
          "due_in_s": -1.0, "due_soon": True, "overdue": False}, "event_due"),
    ],
)
def test_the_countdown_states(drawn, event, key):
    """Calm until near, then due; how late once it is, beside the clock, red only past the
    overdue alert's margin (S, 21 Oct 2026: "This overdue notice is a bit alarming")."""
    window, held = drawn
    held["view"] = _all_keys(next_event=event)
    window.refresh()
    status = window.text["status"]
    late = event["due_in_s"] < 0
    assert bool(window.behind.text()) == late
    if late:
        assert window.behind.text() == status["behind_schedule"].format(
            time=experimenter_ui.clock_text(-event["due_in_s"]))
        red = experimenter_ui.DISCONNECTED_COLOUR in window.behind.styleSheet()
        assert red == event["overdue"]
    if key == "block_due_soon":
        assert window.countdown.text() == status["block_due_soon"].format(
            block=3, type=window.text["terms"]["block_types"]["touch"], time="00:26")
    elif key == "block_overdue":
        assert window.countdown.text() == status["block_due"].format(
            block=3, type=window.text["terms"]["block_types"]["touch"])
    elif key == "next_event":
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
        # The block's type too, so the due line says what to get ready (LOG N7.F11b7).
        assert window.countdown.text() == status[key].format(
            block=3, type=window.text["terms"]["block_types"]["touch"]
        )


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


def _with_channels(window, per_channel_pressure=True):
    """The channel display, as the rig sets it up (LOG N7.F16i)."""
    window.set_garment([1, 2, 3], 250.0, per_channel_pressure, 1.0)
    return window.garment_display


def test_the_hardware_panel_shows_the_channels_only_when_given(drawn):
    window, held = drawn
    display = _with_channels(window)
    held["view"] = _all_keys(hardware=_hardware(pressures={1: 12.0, 2: 30.25}, on=[2]))
    window.refresh()
    assert display.isVisibleTo(window)
    assert display.states[2] == (True, 30.25)
    assert display.states[1] == (False, 12.0)

    held["view"] = _all_keys(hardware=_hardware(pressures=None, faults=["valve 3 stuck"]))
    window.refresh()
    assert not display.isVisibleTo(window)
    assert "valve 3 stuck" in window.faults.text()


def test_no_channel_is_drawn_during_the_intervention_even_if_the_view_leaks_it(drawn):
    """SPEC.md 16. The view withholds them; the window holds the same line on its own."""
    window, held = drawn
    display = _with_channels(window)
    for phase in ("intervention", "rekindle"):
        held["view"] = _all_keys(phase=phase, hardware=_hardware(pressures={1: 55.0}, on=[1]))
        window.refresh()
        assert not display.isVisibleTo(window)
        assert display.states[1] == (False, 0.0), "never handed what the view leaked"


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


def test_a_lost_link_is_warned_of_in_the_experimenters_language_first(drawn):
    """docs/LOG.md N7.U16: the outputs may still be on, which the driver's own detail -- the
    operating system's words -- does not say. In the alert row, red, over even a stop's line
    (review of N7.F16: in the side column's small print it was missed)."""
    window, held = drawn
    fault = "serial write failed on COM3: WriteFile failed"
    held["view"] = _all_keys(phase="setup", interruption="emergency_stop", hardware=_hardware(
        connected=False, faults=[fault], link_lost=True))
    window.refresh()
    words = window.text["hardware"]
    assert window.alert.text() == words["link_lost"]
    assert window.faults.text() == words["fault"].format(value=fault)
    held["view"] = _all_keys(phase="setup", hardware=_hardware(faults=[fault]))
    window.refresh()
    assert window.alert.text() == "", "reconnected, it is gone"


def test_accumulating_faults_do_not_grow_the_side_column(drawn):
    """Pre-merge reviews: faults accumulate for the session, and a line that grew with each
    would move the side column (UI_PRINCIPLES.md 3.3) and push the window off a laptop."""
    window, held = drawn
    window.resize(1280, 800)
    window.show()
    # What the prototype driver actually reports, at full length.
    faults = [f"serial write failed on COM{n}: WriteFile failed (PermissionError(13, 'The "
              f"device does not recognize the command.', None, 22))" for n in range(1, 9)]
    app = QApplication.instance()
    limit = window.faults.fontMetrics().lineSpacing() * experimenter_ui.FAULT_LINES
    for count in (1, len(faults)):
        held["view"] = _all_keys(phase="setup", hardware=_hardware(faults=faults[:count]))
        window.refresh()
        app.processEvents()
        assert window.faults.height() <= limit
    words = window.text["hardware"]
    earlier = words["faults_earlier"].format(value=len(faults) - 1)
    newest = words["fault"].format(value=faults[-1])
    # The short count first, then the newest fault: a bound cuts only that fault's tail.
    assert window.faults.text() == f"{earlier}\n{newest}"
    assert faults[0] in window.faults.toolTip(), "every fault in full, off the screen too"
    hint = window.minimumSizeHint()
    assert hint.height() <= LAPTOP_HEIGHT_PX, "still fits the laptop with faults showing"


def test_refresh_does_not_refit_unchanged_text(drawn, monkeypatch):
    window, _ = drawn
    window.set_instruction("apply", experimenter_ui.NOW)
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
    """S, 21 Oct 2026: "The diagram should show the sites, rather than writing the site
    number"; and a mapping path on it rather than in words."""
    window, _ = drawn
    window.set_instruction("apply", experimenter_ui.NOW)
    window.set_target("secondary", 4)
    assert (window.zone.region, window.zone.site, window.zone.path) == ("secondary", 4, None)
    window.set_instruction("next", experimenter_ui.NOW)
    assert window.zone.region is None and window.zone.site is None
    window.set_target("secondary", path="lateral")
    assert window.zone.path == "lateral"


def test_every_site_a_protocol_uses_is_on_the_diagram(loaded):
    """The figure carries a numbered site for each of the rotation's (open item 11)."""
    zone = widgets.ZoneDiagram(loaded.experimenter_text["zones"],
                               loaded.experimenter_text["terms"]["mapping_paths_short"])
    for region in ("primary", "secondary"):
        assert zone.sites(region) == int(loaded.study1["pinprick"]["n_sites"])
        assert zone.sites(region) == int(loaded.study1["brush"]["n_sites"])


@pytest.mark.parametrize("limb, mirrored", [("left", True), ("right", False)])
def test_the_hand_is_mirrored_for_a_left_limb(drawn, limb, mirrored):
    """The figure is a right hand's back; a left one is its mirror image, so the thumb, and
    the lateral path, are on the side they are on the participant (S, 21 Oct 2026)."""
    window, held = drawn
    held["view"] = _all_keys(limb=limb)
    window.refresh()
    assert window.zone.mirrored is mirrored


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
    # A child of the window it draws on, so its timers die with that window when the test ends
    # (tests/conftest.py). Parentless, it fired into a deleted window in a later test.
    trial = PinprickTrial(session, participant, window, application, parent=participant)
    done = []
    trial.finished.connect(done.append)
    trial.start()
    return window, (participant, done, trial)


def test_the_window_never_draws_a_rating(rig_trial):
    """Bilaga 1 3.3. The rating is in the data file; nothing on the lab screen carries it."""
    window, (participant, done, trial) = rig_trial
    _spin(lambda: trial.awaits_proceed)
    window.proceed_requested.emit()  # applied (docs/LOG.md N7.F16f)
    _spin(lambda: participant.stack.currentWidget() is participant.vas)
    _press(participant.vas, "pagedown")
    for _ in range(RATING_PRESSES):
        _press(participant.vas, "pagedown")
    assert participant.vas.state.percent == float(RATING_SHOWN)
    _press(participant.vas, "f5")
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
    assert not window.fit_accept_button.isVisibleTo(window)
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
    assert not preview.accept_button.isEnabled(), (
        "what it offers is the procedure's, not the preview's (code review of N7.F17e)")
    window.set_actions_enabled(fit_decision=True)  # as the procedure offers both
    assert preview.isVisible() and not preview.isModal()
    assert preview.plot.points and preview.plot.line
    assert _offered(window, window.fit_accept_button)
    assert _offered(window, window.fit_rerun_button)
    assert preview.accept_button.isEnabled() and preview.rerun_button.isEnabled()
    assert preview.derived.text() and preview.quality.text()
    seen = _emitted(window.fit_accepted)
    preview.accept_button.click()
    assert seen == [()], "the preview's Accept is the window's"

    window.hide_fit_preview()
    assert not preview.isVisible()
    assert preview.plot.points == ()
    assert preview.derived.text() == preview.quality.text() == ""
    assert not window.fit_accept_button.isVisibleTo(window)


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
    window.set_instruction("x", experimenter_ui.NOW)
    status_y = window.status.pos().y()
    assert window.instruction.font().pointSize() == experimenter_ui.SIZE_HEADLINE
    longest = max(window.text["instructions"].values(), key=len)
    window.set_instruction(longest, experimenter_ui.NOW)
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
