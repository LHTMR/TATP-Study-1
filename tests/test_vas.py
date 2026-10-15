"""The VAS. SPEC.md 10.2, 10.6.

The state machine is tested directly. The widget is tested through real Qt key events under
QT_QPA_PLATFORM=offscreen, which is what SPEC.md 17.1 requires of the whole suite.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest
import yaml
from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QPainter,
)
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp.clock import Clock
from tatp.responder import Action, Responder
from tatp.ui import vas as vas_module
from tatp.ui.participant import (
    ADJUST_CONFIRM_Y_FRACTION,
    BUTTON_LABEL_POINT_SIZE,
    BUTTON_LABEL_WIDTH_FRACTION,
    BUTTON_Y_FRACTION,
    MESSAGE_POINT_SIZE,
    _MessageScreen,
)
from tatp.ui.vas import (
    ANCHOR_POINT_SIZE,
    INTRODUCTION_POINT_SIZE,
    LAYOUTS,
    LINE_WIDTH_PX,
    LINE_Y_FRACTION,
    MARKER_GAP_PX,
    MARKER_HEIGHT_PX,
    MAX_PCT,
    QT_KEYS,
    QUESTION_POINT_SIZE,
    QUESTION_Y_FRACTION,
    SIDE_MARGIN_FRACTION,
    STUDY_LAYOUT,
    TEXT_TO_SCALE_GAP_PX,
    TICK_RISE_PX,
    TICK_WIDTH_PX,
    TRAINING_Y_FRACTION,
    VasState,
    VasWidget,
)

SCALES = ("pain", "intensity", "pleasantness", "relaxation", "alertness")


class FakeClock(Clock):
    def __init__(self):
        super().__init__()
        self.now = 0.0

    def elapsed_s(self) -> float:
        return self.now

    def real_elapsed_s(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def state(loaded):
    return VasState(loaded.study1["vas"], FakeClock())


# -- the rules of SPEC.md 10.2 ---------------------------------------------------------


def test_the_marker_is_hidden_until_the_first_press(state):
    state.cue()
    assert not state.visible
    assert state.confirm() is None, "there is no response to record before a press"


def test_the_first_press_puts_the_marker_on_the_side_that_was_pressed(state):
    state.cue()
    state.press(Action.DECREASE, 0.0)
    assert state.visible
    assert state.percent == state.start_left_pct == 25.0
    assert state.first_press_side == "left"


def test_the_right_button_starts_on_the_right(state):
    state.cue()
    state.press(Action.INCREASE, 0.0)
    assert state.percent == state.start_right_pct == 75.0
    assert state.first_press_side == "right"


def test_the_first_press_reveals_rather_than_moves(state):
    state.cue()
    state.press(Action.INCREASE, 0.0)
    state.press(Action.INCREASE, 0.0)
    assert state.percent == pytest.approx(state.start_right_pct + state.step_pct)


def test_the_marker_cannot_leave_the_line(state):
    state.cue()
    state.press(Action.DECREASE, 0.0)
    for _ in range(200):
        state.press(Action.DECREASE, 0.0)
    assert state.percent == 0.0
    for _ in range(400):
        state.press(Action.INCREASE, 0.0)
    assert state.percent == 100.0


def test_direction_changes_are_counted(state):
    state.cue()
    state.press(Action.INCREASE, 0.0)
    assert state.direction_changes == 0
    state.press(Action.INCREASE, 0.0)
    assert state.direction_changes == 0
    state.press(Action.DECREASE, 0.0)
    # The first press has a direction even though it does not move, so this is a real reversal.
    assert state.direction_changes == 1
    state.press(Action.DECREASE, 0.0)
    assert state.direction_changes == 1
    state.press(Action.INCREASE, 0.0)
    assert state.direction_changes == 2


def test_reaction_time_runs_from_the_rating_cue(state):
    state.clock.now = 100.0
    state.cue()
    state.clock.now = 101.5
    state.press(Action.INCREASE, 0.0)
    state.clock.now = 103.25
    response = state.confirm()
    assert response.rt_s == pytest.approx(3.25)
    assert response.cue_iso == state.cue_iso
    assert response.rating_percent == 75.0


def test_a_press_before_the_cue_is_a_defect_not_a_rating(state):
    with pytest.raises(RuntimeError, match="before it was cued"):
        state.press(Action.INCREASE, 0.0)


def test_cueing_again_clears_the_previous_response(state):
    state.cue()
    state.press(Action.INCREASE, 0.0)
    state.cue()
    assert not state.visible
    assert state.direction_changes == 0
    assert state.first_press_side == ""


def test_waiting_time_is_reported_and_never_auto_advances(state):
    state.cue()
    state.clock.now += 90.0
    assert state.waiting_s == pytest.approx(90.0)
    assert state.waiting_s > state.no_response_warning_s
    assert state.confirm() is None, "waiting does not produce a rating"


# -- holding a button: the accelerating hold (S's lab-run list, 5 Oct 2026) --------------


def _revealed_and_held(state, at_s=0.0):
    """The marker shown at 75 %, then a second right press held from `at_s`."""
    state.cue()
    state.press(Action.INCREASE, 0.0)
    state.press(Action.INCREASE, at_s)
    return state.percent


def test_a_tap_with_a_time_is_the_same_single_step(state):
    """Single taps behave exactly as before: one step, on the press, nothing on release."""
    before = _revealed_and_held(state)
    assert before == pytest.approx(state.start_right_pct + state.step_pct)
    state.tick(state.hold_delay_s / 2)
    state.release(Action.INCREASE, state.hold_delay_s / 2)
    assert state.percent == pytest.approx(before)


def test_a_hold_accelerates_from_the_initial_to_the_final_rate(state):
    start = _revealed_and_held(state, at_s=0.0)
    early_s = 0.1
    state.tick(state.hold_delay_s + early_s)
    assert state.percent - start == pytest.approx(
        state.rate_initial_pct_s * early_s, rel=0.2
    ), "a hold begins at the initial rate"
    # The rest of the ramp by its rate: the marker reaches the end of the line before the ramp
    # ends, from either start position.
    assert state.rate_pct_s(state.ramp_duration_s / 2) == pytest.approx(
        (state.rate_initial_pct_s + state.rate_final_pct_s) / 2
    )
    assert state.rate_pct_s(state.ramp_duration_s) == state.rate_final_pct_s
    assert state.rate_pct_s(state.ramp_duration_s * 3) == state.rate_final_pct_s
    assert state._travel(state.ramp_duration_s * 2) - state._travel(
        state.ramp_duration_s
    ) == pytest.approx(state.rate_final_pct_s * state.ramp_duration_s)
    assert state.rate_final_pct_s > state.rate_initial_pct_s


def test_the_distance_depends_on_the_hold_not_on_the_ticks(state, loaded):
    # Short enough that neither reaches the end of the line, where both would read 100 %.
    held_s = state.hold_delay_s + state.ramp_duration_s / 3
    start = _revealed_and_held(state)
    state.tick(held_s)
    one_tick = state.percent
    assert start < one_tick < MAX_PCT
    other = VasState(loaded.study1["vas"], FakeClock())
    _revealed_and_held(other)
    for index in range(1, 101):
        other.tick(held_s * index / 100)
    assert other.percent == pytest.approx(one_tick)


def test_a_hold_crosses_the_line_faster_than_the_old_fixed_rate(state):
    """The point of the change: the old hold took about 8 s for the whole line."""
    state.cue()
    state.press(Action.DECREASE, 0.0)
    state.press(Action.DECREASE, 0.0)
    for index in range(1, 1000):
        state.tick(index * 0.01)
        if state.percent == 0.0:
            break
    assert index * 0.01 < 2.0, "a hold from 25 % to 0 % took two seconds or more"
    assert state.percent == 0.0, "the marker cannot leave the line"


def test_a_tap_released_late_by_a_stall_is_still_one_step(state):
    """A stall can let a tick run before the release is handled. The release's own time says
    it was a tap, so the hold travel is taken back (docs/LOG.md N2.9)."""
    tapped = _revealed_and_held(state)
    state.tick(state.hold_delay_s + 0.5)  # the tick the stall let through
    assert state.percent > tapped
    state.release(Action.INCREASE, state.hold_delay_s / 3)
    assert state.percent == pytest.approx(tapped)


def test_a_device_repeat_after_a_hold_carries_the_hold_on(state):
    """A held button may arrive as fresh down/up pairs (docs/LOG.md N7.F1)."""
    _revealed_and_held(state)
    released_s = state.hold_delay_s + 0.5
    state.tick(released_s)
    state.release(Action.INCREASE, released_s)
    held_at = state.percent
    changes = state.direction_changes
    pressed_s = released_s + state.regrip_max_s / 2
    assert state.regrips(Action.INCREASE, pressed_s)
    state.press(Action.INCREASE, pressed_s, regrip=True)
    assert state.percent == pytest.approx(held_at), "a repeat is not a tap"
    state.tick(released_s + 0.2)
    assert state.percent > held_at, "the hold carries on"
    assert state.direction_changes == changes


def test_a_press_after_a_hold_that_let_go_long_enough_ago_is_a_tap(state):
    _revealed_and_held(state)
    released_s = state.hold_delay_s + 0.5
    state.tick(released_s)
    state.release(Action.INCREASE, released_s)
    held_at = state.percent
    assert not state.regrips(Action.INCREASE, released_s + state.regrip_max_s * 2)
    state.press(Action.INCREASE, released_s + state.regrip_max_s * 2)
    assert state.percent == pytest.approx(held_at + state.step_pct)


def test_a_tap_after_a_tap_is_always_a_tap(state):
    """However quickly: only a hold can be carried on, so taps are never lost or merged."""
    tapped = _revealed_and_held(state)
    state.release(Action.INCREASE, 0.0)
    for index in range(1, 11):
        state.press(Action.INCREASE, 0.0)
        state.release(Action.INCREASE, 0.0)
        assert state.percent == pytest.approx(tapped + index * state.step_pct)


def test_the_other_button_after_a_hold_is_a_tap_and_a_reversal(state):
    _revealed_and_held(state)
    released_s = state.hold_delay_s + 0.5
    state.tick(released_s)
    state.release(Action.INCREASE, released_s)
    held_at = state.percent
    assert not state.regrips(Action.DECREASE, released_s + state.regrip_max_s / 2)
    state.press(Action.DECREASE, released_s + state.regrip_max_s / 2)
    assert state.percent == pytest.approx(held_at - state.step_pct)
    assert state.direction_changes == 1


def test_confirming_ends_a_hold(state):
    _revealed_and_held(state)
    state.tick(state.hold_delay_s + 0.5)
    response = state.confirm()
    state.tick(state.hold_delay_s + 2.0)
    assert state.percent == response.rating_percent


# -- the widget ------------------------------------------------------------------------


def _press(widget, name, release=True):
    key = QT_KEYS[name]
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    if release:
        widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


@pytest.fixture
def widget(app, loaded):
    made = VasWidget(
        loaded.study1["vas"],
        Responder(loaded.hardware),
        FakeClock(),
    )
    made.resize(1280, 800)
    made.show_scale("pain", loaded.participant_text["vas"]["pain"])
    return made


def test_the_widget_carries_no_wording_of_its_own(widget, loaded):
    """SPEC.md 10.4: no user-facing string in any .py file."""
    assert widget.question == loaded.participant_text["vas"]["pain"]["question"]
    assert [a["label"] for a in widget.anchors] == [
        a["label"] for a in loaded.participant_text["vas"]["pain"]["anchors"]
    ]


# -- anchor layout -----------------------------------------------------------------------
#
# Found by the SPEC.md 17.4 screenshots, not by reasoning: on the `pain` and `intensity`
# scales the labels at 0 and 10 % were drawn on top of each other and neither was readable.
# `intensity` is the scale the whole touch calibration is rated against, so "just noticeable"
# and "just uncomfortable" being illegible is not cosmetic.


def _boxes(widget, scale, text):
    """Each anchor as (left, right, row), in the layout the widget would paint."""
    from PySide6.QtGui import QFont, QFontMetrics

    widget.show_scale(scale, text)
    font = QFont(widget.font())
    font.setPointSize(ANCHOR_POINT_SIZE)
    metrics = QFontMetrics(font)
    return [
        (left, left + metrics.horizontalAdvance(label), row)
        for label, left, row, _ in widget._anchor_layout(metrics)
    ]


@pytest.fixture(scope="module")
def configs():
    """Loaded once. `cfg.load` hashes every config file it reads, so calling it per parameter
    turned a 60-second suite into a three-minute one."""
    return {language: cfg.load(language, language) for language in ("sv", "en")}


@pytest.fixture
def by_language(app, configs):
    """One widget per language, built per test: every window is deleted when its test ends
    (tests/conftest.py), so a module-wide widget would be gone by the second test."""
    made = {}
    for language, config in configs.items():
        widget = VasWidget(config.study1["vas"], Responder(config.hardware), FakeClock())
        widget.resize(1280, 800)
        made[language] = (widget, config)
    return made


@pytest.mark.parametrize("scale", ("pain", "intensity", "pleasantness"))
@pytest.mark.parametrize("language", ("sv", "en"))
def test_no_two_anchor_labels_overlap(by_language, scale, language):
    """Every scale, both languages -- the collision depends on how long the words are."""
    widget, config = by_language[language]
    boxes = _boxes(widget, scale, config.participant_text["vas"][scale])
    for index, (left, right, row) in enumerate(boxes):
        for other_left, other_right, other_row in boxes[index + 1 :]:
            if row != other_row:
                continue
            assert right <= other_left or other_right <= left, (
                f"{language} {scale}: two anchor labels overlap on row {row}"
            )


@pytest.mark.parametrize("scale", ("pain", "intensity", "pleasantness"))
@pytest.mark.parametrize("language", ("sv", "en"))
def test_every_anchor_is_ticked_at_its_own_percentage(by_language, scale, language):
    """UI_PRINCIPLES.md 1.3, and the reason stacking is allowed at all.

    A label may be clamped at the ends or dropped to a lower row; the tick may not move. It is
    what tells the participant that "just noticeable" means 10 % of the line and not wherever
    the words happened to fit. Without it, English `intensity` row 0 reads as a complete scale
    running "no sensation at all ... just uncomfortable".
    """
    from PySide6.QtGui import QFont, QFontMetrics

    widget, config = by_language[language]
    text = config.participant_text["vas"][scale]
    widget.show_scale(scale, text)
    font = QFont(widget.font())
    font.setPointSize(ANCHOR_POINT_SIZE)
    placed = widget._anchor_layout(QFontMetrics(font))

    by_label = {label: tick_x for label, _, _, tick_x in placed}
    assert len(by_label) == len(text["anchors"]), "every anchor is drawn exactly once"
    for anchor in text["anchors"]:
        assert by_label[anchor["label"]] == pytest.approx(
            widget._x_for(float(anchor["pct"]))
        )


def test_anchors_far_apart_stay_on_one_row(widget, loaded):
    """Stacking is the exception. Two anchors at 0 and 100 % have no reason to be stacked."""
    boxes = _boxes(widget, "pleasantness", loaded.participant_text["vas"]["pleasantness"])
    assert {row for _, _, row in boxes} == {0}


# -- the tick, UI_PRINCIPLES.md 1.4 --------------------------------------------------------


def test_the_tick_straddles_the_line_and_stays_under_the_marker():
    """The rules the chosen numbers must obey, stated so a later retune cannot break them."""
    assert TICK_RISE_PX > 0, "a tick that only descends reads as a bracket around its label"
    assert TICK_WIDTH_PX < LINE_WIDTH_PX, "the line is the scale; the tick annotates it"
    assert TICK_RISE_PX < MARKER_GAP_PX, "the marker would touch the tick at an anchor"


def _pixel_above_the_first_anchor(widget, config):
    """What is drawn just above the line at the 0 % anchor, and a background pixel to match."""
    widget.show_scale("pleasantness", config.participant_text["vas"]["pleasantness"])
    image = widget.grab().toImage()
    line_y = int(widget.height() * LINE_Y_FRACTION)
    x = int(widget._x_for(0.0))
    # Inside the tick's rise but clear of the line's own antialiasing.
    return (
        image.pixel(x, line_y - TICK_RISE_PX + 2),
        image.pixel(x, line_y - MARKER_GAP_PX * 3),
    )


def test_the_tick_is_drawn_above_the_line_as_well_as_below(by_language, monkeypatch):
    """Straddling, in the pixels -- the rendered screens are what found the bracket reading.

    With the negative control, because a pixel probe that cannot fail is not a check. The
    hanging tick this replaced is the control: at rise 0 the same sample is background.
    """
    widget, config = by_language["en"]
    above, background = _pixel_above_the_first_anchor(widget, config)
    assert above != background, "nothing is drawn above the line at the 0 % anchor"

    monkeypatch.setattr(vas_module, "TICK_RISE_PX", 0)
    above, background = _pixel_above_the_first_anchor(widget, config)
    assert above == background, "the probe finds a tick above the line where there is none"


# -- where the labels go, S's decision of 10 Sep 2026 ---------------------------------------


def _placed(widget, config, scale):
    widget.show_scale(scale, config.participant_text["vas"][scale])
    metrics = QFontMetrics(widget._anchor_font())
    return widget._anchor_layout(metrics), metrics


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("language", ("sv", "en"))
def test_the_end_labels_share_the_row_nearest_the_line(
    by_language, scale, language, layout, monkeypatch
):
    """The extremes of the scale read as a pair at one height, in either layout."""
    widget, config = by_language[language]
    monkeypatch.setattr(widget, "layout", LAYOUTS[layout])
    placed, _ = _placed(widget, config, scale)
    ends = {float(a["pct"]) for a in config.participant_text["vas"][scale]["anchors"]} & {
        0.0,
        100.0,
    }
    end_rows, interior_rows = [], []
    for _, _, row, tick_x in placed:
        is_end = any(tick_x == pytest.approx(widget._x_for(pct)) for pct in ends)
        (end_rows if is_end else interior_rows).append(row)
    assert end_rows == [0] * len(ends), f"{language} {scale}: end labels on rows {end_rows}"
    assert 0 not in interior_rows, f"{language} {scale}: an interior label took row 0"


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("language", ("sv", "en"))
def test_the_marker_can_never_cover_an_anchor_name(by_language, scale, language):
    """In the study layout interior labels sit above the line, clear of the marker's height.

    The marker is drawn above the line wherever the rating is, and 10 % and 90 % are exactly
    where participants are trained to aim -- so a label in its band would be hidden at the
    moment it is needed. This is what sank the first above-line render.
    """
    widget, config = by_language[language]
    assert widget.layout is LAYOUTS[STUDY_LAYOUT]
    placed, metrics = _placed(widget, config, scale)
    line_y = widget.height() * LINE_Y_FRACTION
    marker_top = line_y - MARKER_GAP_PX - MARKER_HEIGHT_PX
    for label, _, row, _ in placed:
        baseline, _ = widget._label_geometry(row, metrics, line_y)
        if row < 0:
            assert baseline + metrics.descent() <= marker_top, f"{language}: {label!r}"
        else:
            assert baseline - metrics.ascent() > line_y, f"{language}: {label!r}"


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("language", ("sv", "en"))
def test_the_alternative_hangs_its_end_labels_without_hitting_the_screen_edge(
    by_language, scale, language, monkeypatch
):
    """The shorter line is what makes the alternative work: no end label is clamped.

    At the study's line length the long Swedish end labels ran into the screen edge, so the
    overhang differed with the length of the words -- the inconsistency the row rule removed.
    """
    widget, config = by_language[language]
    layout = LAYOUTS["ends_outside"]
    monkeypatch.setattr(widget, "layout", layout)
    placed, metrics = _placed(widget, config, scale)
    inside = layout.end_inside_fraction
    for label, left, _, tick_x in placed:
        width = metrics.horizontalAdvance(label)
        if tick_x == pytest.approx(widget._x_for(0.0)):
            assert left == pytest.approx(tick_x - (1 - inside) * width), f"{label!r} clamped"
        elif tick_x == pytest.approx(widget._x_for(100.0)):
            assert left == pytest.approx(tick_x - inside * width), f"{label!r} clamped"


# -- the heading, UI_PRINCIPLES.md 5.3 and 1.7 ---------------------------------------------


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("language", ("sv", "en"))
def test_a_statement_outranks_the_question_that_introduces_it(by_language, scale, language):
    """The RSQ scales rate the statement; the question only frames it."""
    widget, config = by_language[language]
    text = config.participant_text["vas"][scale]
    widget.show_scale(scale, text)
    blocks = widget.heading_blocks()

    if not text.get("statement"):
        assert blocks == [(text["question"], QUESTION_POINT_SIZE)]
        return
    (question, question_size), (statement, statement_size) = blocks
    assert (question, statement) == (text["question"], text["statement"])
    assert question_size == INTRODUCTION_POINT_SIZE
    assert question_size < statement_size, "the framing question is set larger than the item"


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("language", ("sv", "en"))
def test_the_text_block_clears_the_scale(by_language, scale, language):
    """The line cannot move down to make room (UI_PRINCIPLES.md 1.6), so the text must fit.

    Measured to the highest thing the scale draws -- an interior label above the line, or the
    marker's top. At the lab window size, both languages, every scale. A failure means the
    wording needs shortening or the size reducing, never the line moving.
    """
    widget, config = by_language[language]
    widget.show_scale(scale, config.participant_text["vas"][scale])
    clearance = widget.heading_clearance()
    assert clearance >= TEXT_TO_SCALE_GAP_PX, (
        f"{language} {scale}: {clearance:.0f} px between the text and the scale, "
        f"where {TEXT_TO_SCALE_GAP_PX} px are required"
    )


# -- the proportionality training (SPEC.md 10.6) ------------------------------------------

TRAINED_SCALES = ("pain", "intensity", "pleasantness")


def _show_training(widget, config, scale, accepting=True):
    text = config.participant_text
    if accepting:
        widget.show_practice(scale, text["vas"][scale], text["training"][scale])
    else:
        widget.show_explanation(scale, text["vas"][scale])


def test_every_trained_scale_has_its_sentence_in_both_languages(configs):
    """The scales the spec names, and no others: relaxation and alertness have none. The
    proportionality sentence is the experimenter's, for the same scales."""
    for config in configs.values():
        assert set(config.participant_text["training"]) == set(TRAINED_SCALES)
        assert set(config.experimenter_text["vas_training_explain"]) == set(TRAINED_SCALES)


def test_proportionality_is_not_on_the_participant_screen(configs):
    """S's lab-run list (5 Oct 2026): "a mark twice as far" is said by the experimenter."""
    for config in configs.values():
        participant = yaml.safe_dump(config.participant_text, allow_unicode=True, width=10**6)
        for scale in TRAINED_SCALES:
            explanation = config.experimenter_text["vas_training_explain"][scale]
            assert explanation not in participant


def test_an_explanation_for_a_scale_that_is_not_trained_is_refused(tmp_path):
    shutil.copytree(cfg.CONFIG_DIR, tmp_path / "config")
    for language in ("sv", "en"):
        path = tmp_path / "config" / "text" / f"experimenter_{language}.yaml"
        text = yaml.safe_load(path.read_text(encoding="utf-8"))
        text["vas_training_explain"]["relaxation"] = text["vas_training_explain"]["pain"]
        path.write_text(yaml.safe_dump(text, allow_unicode=True), encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="vas_training_explain"):
        cfg.load("en", "en", config_dir=tmp_path / "config")


def test_a_training_key_that_is_not_a_scale_is_refused(tmp_path):
    """A misspelt key would be a scale silently never trained (SPEC.md 10.6)."""
    shutil.copytree(cfg.CONFIG_DIR, tmp_path / "config")
    for language in ("sv", "en"):  # both, so the languages still share their keys
        path = tmp_path / "config" / "text" / f"participant_{language}.yaml"
        text = yaml.safe_load(path.read_text(encoding="utf-8"))
        text["training"]["painn"] = text["training"].pop("pain")
        path.write_text(yaml.safe_dump(text, allow_unicode=True), encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="painn"):
        cfg.load("en", "en", config_dir=tmp_path / "config")


def test_nothing_but_the_stop_works_while_the_experimenter_explains(widget, loaded):
    confirmed, empty, responses, stops = [], [], [], []
    widget.training_confirmed.connect(confirmed.append)
    widget.pressed_without_marker.connect(lambda: empty.append(1))
    widget.confirmed.connect(responses.append)
    widget.emergency_stop.connect(lambda: stops.append(1))
    _show_training(widget, loaded, "pain", accepting=False)
    assert widget.training == "", "nothing below the scale while the experimenter explains"
    for name in ("pagedown", "pageup", "f5"):
        _press(widget, name)
    assert not widget.state.visible, "a marker appeared while the experimenter explained"
    assert confirmed == empty == responses == []
    _press(widget, "period")
    assert stops == [1]


@pytest.mark.parametrize("scale", TRAINED_SCALES)
@pytest.mark.parametrize("language", ("sv", "en"))
def test_the_training_text_clears_the_scale_and_the_screen_edge(by_language, scale, language):
    widget, config = by_language[language]
    _show_training(widget, config, scale)
    below_labels, above_edge = widget.training_clearance()
    assert below_labels >= TEXT_TO_SCALE_GAP_PX, (
        f"{language} {scale}: {below_labels:.0f} px between the lowest anchor label and the "
        f"training text, where {TEXT_TO_SCALE_GAP_PX} px are required"
    )
    assert above_edge >= 0, f"{language} {scale}: the training text runs off the screen"
    # The scale above it is drawn as it is rated (UI_PRINCIPLES.md 1.6).
    assert widget.heading_clearance() >= TEXT_TO_SCALE_GAP_PX


def test_the_practice_is_a_rating_that_is_never_confirmed_as_one(widget, loaded):
    """The participant moves the marker and confirms, as on a rating -- and the response goes
    out on `training_confirmed` only, never on `confirmed`, which ratings are recorded from."""
    practised, empty, responses = [], [], []
    widget.training_confirmed.connect(practised.append)
    widget.pressed_without_marker.connect(lambda: empty.append(1))
    widget.confirmed.connect(responses.append)
    _show_training(widget, loaded, "pain")
    assert widget.practising and widget.training == loaded.participant_text["training"]["pain"]
    _press(widget, "f5")
    assert empty == [1] and practised == [], "a confirm with no marker is not a practice"
    _press(widget, "pagedown")
    _press(widget, "pageup")
    _press(widget, "pageup")
    _press(widget, "f5")
    assert responses == []
    (practice,) = practised
    assert practice.rating_percent == pytest.approx(75.0 - 2 * widget.state.step_pct)
    assert practice.first_press_side == "right" and practice.direction_changes == 1


def test_the_emergency_stop_works_on_the_training_screen(widget, loaded):
    stops = []
    widget.emergency_stop.connect(lambda: stops.append(1))
    _show_training(widget, loaded, "pain")
    _press(widget, "period")
    assert stops == [1]


def test_a_rating_after_the_training_is_an_ordinary_rating(widget, loaded):
    _show_training(widget, loaded, "pain")
    widget.show_scale("pain", loaded.participant_text["vas"]["pain"])
    assert widget.training == "" and not widget.practising and not widget.explaining
    got = []
    widget.confirmed.connect(got.append)
    _press(widget, "pagedown")
    _press(widget, "f5")
    assert len(got) == 1


def test_confirming_emits_the_response(widget):
    got = []
    widget.confirmed.connect(got.append)
    _press(widget, "pagedown")
    _press(widget, "f5")
    assert len(got) == 1
    assert got[0].rating_percent == 75.0
    assert got[0].first_press_side == "right"


def test_confirming_with_no_marker_emits_no_response(widget):
    got, empty = [], []
    widget.confirmed.connect(got.append)
    widget.pressed_without_marker.connect(lambda: empty.append(1))
    _press(widget, "f5")
    assert got == []
    assert empty == [1]


def test_escape_confirms_and_goes_no_further(widget):
    """SPEC.md 10.1: every other ▶ is escape, and it must not reach Qt, which would close the
    window."""
    got = []
    widget.confirmed.connect(got.append)
    _press(widget, "pagedown")
    event = QKeyEvent(QEvent.KeyPress, QT_KEYS["escape"], Qt.NoModifier)
    widget.keyPressEvent(event)
    assert event.isAccepted()
    assert len(got) == 1


def test_the_emergency_stop_key_is_wired(widget):
    stops = []
    widget.emergency_stop.connect(lambda: stops.append(1))
    _press(widget, "period")
    assert stops == [1]


def test_auto_repeat_events_are_ignored(widget):
    """A hold is driven by the widget's own timer, not by the platform's key repeat."""
    _press(widget, "pagedown")
    before = widget.state.percent
    widget.keyPressEvent(
        QKeyEvent(QEvent.KeyPress, QT_KEYS["pagedown"], Qt.NoModifier, autorep=True)
    )
    assert widget.state.percent == before


def _key(widget, kind, name, stamp_ms, autorep=False):
    event = QKeyEvent(kind, QT_KEYS[name], Qt.NoModifier, autorep=autorep)
    event.setTimestamp(stamp_ms)
    (widget.keyPressEvent if kind == QEvent.KeyPress else widget.keyReleaseEvent)(event)


def test_a_held_key_accelerates_through_the_widget_and_its_repeats_add_nothing(widget):
    """The keyboard's own auto-repeat: one press, repeats flagged as such, one release."""
    clock = widget.clock
    _press(widget, "pagedown")  # reveals at 75 %
    clock.now = 10.0
    _key(widget, QEvent.KeyPress, "pageup", 1000)
    tapped = widget.state.percent
    assert tapped == pytest.approx(75.0 - widget.state.step_pct)
    assert widget._tick.isActive()
    for index in range(1, 11):
        clock.now = 10.0 + widget.state.hold_delay_s + index * 0.05
        _key(widget, QEvent.KeyPress, "pageup", 1000 + index * 50, autorep=True)
        widget._on_tick()
    moved = tapped - widget.state.percent
    expected = widget.state._travel(0.5)
    assert moved == pytest.approx(expected), "the repeats moved the marker as well as the hold"
    _key(widget, QEvent.KeyRelease, "pageup", 1000 + 800)
    assert not widget._tick.isActive()
    clock.now += 1.0
    widget._on_tick()
    assert tapped - widget.state.percent == pytest.approx(expected), "it moved after release"


def test_a_hold_that_arrives_as_repeated_presses_still_accelerates(widget):
    """The other way a remote can repeat: fresh down/up pairs, close together, after the
    first press has already been held past the delay."""
    clock = widget.clock
    _press(widget, "pagedown")
    clock.now = 10.0
    _key(widget, QEvent.KeyPress, "pageup", 1000)
    tapped = widget.state.percent
    delay_ms = int(widget.state.hold_delay_s * 1000)
    stamp = 1000 + delay_ms + 100
    clock.now = 10.0 + (stamp - 1000) / 1000
    widget._on_tick()
    _key(widget, QEvent.KeyRelease, "pageup", stamp)
    for _ in range(10):
        stamp += 15
        _key(widget, QEvent.KeyPress, "pageup", stamp)
        stamp += 15
        clock.now = 10.0 + (stamp - 1000) / 1000
        widget._on_tick()
        _key(widget, QEvent.KeyRelease, "pageup", stamp)
    held_s = (stamp - 1000) / 1000 - widget.state.hold_delay_s
    assert tapped - widget.state.percent == pytest.approx(widget.state._travel(held_s))


def test_taps_through_the_widget_are_one_step_each_however_fast(widget):
    """Single taps behave exactly as before: the virtual participant's taps, with one stamp
    for both edges, and a person's quick ones, each move one step."""
    _press(widget, "pagedown")
    start = widget.state.percent
    for index in range(1, 21):
        _key(widget, QEvent.KeyPress, "pagedown", 5000 + index * 40)
        _key(widget, QEvent.KeyRelease, "pagedown", 5000 + index * 40 + 20)
        assert widget.state.percent == pytest.approx(start + index * widget.state.step_pct)


# -- review findings on the hold (integrator, 15 Oct 2026) -----------------------------------


def _hold_from(widget, start_s=10.0, stamp_ms=1000):
    """The marker revealed at 75 %, then the left button pressed at `start_s` and held."""
    _press(widget, "pagedown")
    widget.clock.now = start_s
    _key(widget, QEvent.KeyPress, "pageup", stamp_ms)
    return widget.state.percent


def test_a_stalled_tick_cannot_carry_a_hold_past_its_release(widget):
    """The marker is where the hold put it at the release's own time, whatever ran late."""
    tapped = _hold_from(widget)
    widget.clock.now = 12.0  # a stall lets a tick run 1.2 s after the button went up
    widget._on_tick()
    _key(widget, QEvent.KeyRelease, "pageup", 1800)
    assert tapped - widget.state.percent == pytest.approx(widget.state._travel(0.5))


def test_a_clean_release_keeps_the_travel_since_the_last_tick(widget):
    tapped = _hold_from(widget)
    widget.clock.now = 10.78
    widget._on_tick()
    widget.clock.now = 10.8
    _key(widget, QEvent.KeyRelease, "pageup", 1800)
    assert tapped - widget.state.percent == pytest.approx(widget.state._travel(0.5), rel=1e-9)


def test_a_tap_just_after_a_hold_is_judged_on_the_stamps(widget):
    """Pressed 0.2 s after the hold let go by the device's stamps, it is a tap, even when its
    handler runs only 10 ms after the release's."""
    _hold_from(widget)
    widget.clock.now = 10.8
    widget._on_tick()
    _key(widget, QEvent.KeyRelease, "pageup", 1800)
    held_at = widget.state.percent
    widget.clock.now = 10.81
    _key(widget, QEvent.KeyPress, "pageup", 2000)
    assert widget.state.percent == pytest.approx(held_at - widget.state.step_pct)


@pytest.mark.parametrize("ending", ("focus_out", "hide", "show_scale"))
def test_a_hold_whose_release_never_arrives_ends(widget, loaded, ending):
    """A release routed to an experimenter text field, or lost when an emergency stop's screen
    takes the focus, must not leave the marker running to the end of the line."""
    widget.show()
    _hold_from(widget)
    if ending == "focus_out":
        widget.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    elif ending == "hide":
        widget.hide()
    else:
        widget.show_scale("pain", loaded.participant_text["vas"]["pain"])
    stopped_at = widget.state.percent
    assert widget.state.held is None
    assert not widget._tick.isActive()
    widget.clock.now = 20.0
    widget._on_tick()
    assert widget.state.percent == stopped_at


def test_the_timer_waits_out_the_hold_delay(widget):
    _hold_from(widget)
    assert widget._tick.interval() == round(widget.state.hold_delay_s * 1000)


def test_a_hold_repaints_only_when_the_marker_moves(widget, monkeypatch):
    _hold_from(widget)
    painted = []
    monkeypatch.setattr(widget, "update", lambda *args: painted.append(1))
    widget.clock.now = 10.0 + widget.state.hold_delay_s / 2
    widget._on_tick()
    assert painted == [], "repainted during the hold delay"
    widget.clock.now = 30.0
    widget._on_tick()
    assert widget.state.percent == 0.0 and painted == [1]
    widget.clock.now = 31.0
    widget._on_tick()
    assert painted == [1], "repainted with the marker clamped at the end of the line"


def test_a_press_always_says_when(state):
    state.cue()
    with pytest.raises(TypeError):
        state.press(Action.INCREASE)


def test_a_tick_interval_of_zero_is_refused(tmp_path):
    shutil.copytree(cfg.CONFIG_DIR, tmp_path / "config")
    path = tmp_path / "config" / "study1.yaml"
    text = path.read_text(encoding="utf-8")
    old = "hold_tick_interval_s: 0.02"
    assert old in text
    path.write_text(text.replace(old, "hold_tick_interval_s: 0"), encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="hold_tick_interval_s"):
        cfg.load("en", "en", config_dir=tmp_path / "config")


def test_the_widget_renders_headless(widget):
    """SPEC.md 17.1 and 17.4: the suite runs with no display and grabs real pixmaps."""
    _press(widget, "pageup")
    pixmap = widget.grab()
    assert pixmap.width() == 1280
    assert pixmap.height() == 800
    assert not pixmap.isNull()


# -- the play symbol in participant text (S, lab run 5 Oct 2026) ----------------------------


# Each (point size, box width as a fraction of the screen's width, box top as a fraction of its
# height) a participant screen draws text with: the message and question text, the adjustment's
# confirm sentence, a drawn button's label, an RSQ introduction, the training sentence.
PROSE_PLACES = (
    (MESSAGE_POINT_SIZE, 1 - 2 * SIDE_MARGIN_FRACTION, QUESTION_Y_FRACTION),
    (MESSAGE_POINT_SIZE, 1 - 2 * SIDE_MARGIN_FRACTION, ADJUST_CONFIRM_Y_FRACTION),
    (BUTTON_LABEL_POINT_SIZE, BUTTON_LABEL_WIDTH_FRACTION, BUTTON_Y_FRACTION),
    (INTRODUCTION_POINT_SIZE, 1 - 2 * SIDE_MARGIN_FRACTION, QUESTION_Y_FRACTION),
    (QUESTION_POINT_SIZE, 1 - 2 * SIDE_MARGIN_FRACTION, TRAINING_Y_FRACTION),
)
# The lab window at 100 %, and the lab laptop's 1920 x 1080 panel at 150 %, whose fractional
# metrics are where a layout that only approximates `drawText`'s rounding would show.
PROSE_SCREENS = ((1280, 800, 1.0), (1920, 1080, 1.0), (1280, 720, 1.5))


def _render(draw, box: QRect, point_size: int, ratio: float) -> QImage:
    image = QImage(
        round(box.width() * ratio), round(box.height() * ratio), QImage.Format_ARGB32
    )
    image.setDevicePixelRatio(ratio)
    image.fill(vas_module.BACKGROUND)
    painter = QPainter(image)
    font = QFont()
    font.setPointSize(point_size)
    painter.setFont(font)
    painter.setPen(vas_module.FOREGROUND)
    draw(painter)
    painter.end()
    return image


def _pixels(image: QImage) -> np.ndarray:
    """BGRA as one array, copied out of the image in one go rather than read pixel by pixel."""
    data = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
    rows = data.reshape(image.height(), image.bytesPerLine() // 4, 4)
    return rows[:, : image.width()].copy()


def _participant_texts(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _participant_texts(value)


def _prose_cases(language: str):
    path = cfg.CONFIG_DIR / "text" / f"participant_{language}.yaml"
    texts = sorted(set(_participant_texts(yaml.safe_load(path.read_text(encoding="utf-8")))))
    for width_px, height_px, ratio in PROSE_SCREENS:
        for point_size, width_fraction, top_fraction in PROSE_PLACES:
            top = int(height_px * top_fraction)
            box = QRect(0, 0, int(width_px * width_fraction), height_px - top)
            for text in texts:
                yield text, box, point_size, ratio


def _drawtext_and_prose(responder, text, box, point_size, ratio) -> tuple[QImage, QImage]:
    plain = _render(lambda p: p.drawText(box, vas_module.PROSE_FLAGS, text),
                    box, point_size, ratio)
    prose = _render(lambda p: vas_module.draw_prose(p, box, text, responder),
                    box, point_size, ratio)
    return plain, prose


@pytest.mark.parametrize("language", ["sv", "en"])
def test_participant_text_is_laid_out_exactly_as_drawtext_would(app, loaded, language):
    """Every participant string, wherever a screen draws it: the screens' clearance checks
    measure with `boundingRect`, which knows only `drawText`'s layout. With the symbol's colour
    set to the text's, the two must be the same image."""
    responder = Responder(loaded.hardware)
    responder.confirm_colour = vas_module.FOREGROUND.name()
    for case in _prose_cases(language):
        plain, prose = _drawtext_and_prose(responder, *case)
        assert prose == plain, case


def _symbol_in_box(text: str, symbol: str, box: QRect, point_size: int) -> bool:
    """Whether the symbol's line is laid out inside the box. The places are crossed with every
    string, so a long message meets a box it is never drawn in, and its symbol is clipped."""
    line_end = text.find("\n", text.index(symbol))
    through_symbol = text if line_end < 0 else text[:line_end]
    font = QFont()
    font.setPointSize(point_size)
    laid_out = QFontMetrics(font).boundingRect(box, vas_module.PROSE_FLAGS, through_symbol)
    return laid_out.height() <= box.height()


@pytest.mark.parametrize("language", ["sv", "en"])
def test_only_the_play_symbol_changes_colour(app, loaded, language):
    responder = Responder(loaded.hardware)
    symbol = responder.symbol_for(Action.CONFIRM)
    named = 0
    for case in _prose_cases(language):
        plain_image, prose_image = _drawtext_and_prose(responder, *case)
        if symbol not in case[0] or not _symbol_in_box(case[0], symbol, case[1], case[2]):
            assert prose_image == plain_image, case
            continue
        named += 1
        plain, prose = _pixels(plain_image), _pixels(prose_image)
        changed = (plain != prose).any(axis=2)
        assert changed.any(), case
        # The grey text has equal channels; only the blue glyph tints a pixel blue.
        blue, red = prose[..., 0], prose[..., 2]
        assert (blue[changed] > red[changed]).all(), case
    assert named, f"no participant text names {symbol}"


def test_a_message_screen_colours_the_symbol_from_its_first_paint(app, loaded):
    """No state in which the screen exists but does not yet know the symbol: Qt swallows an
    exception raised in a paint handler and leaves the participant a blank screen."""
    responder = Responder(loaded.hardware)
    screen = _MessageScreen(responder)
    screen.resize(1280, 800)
    screen.text = f"Press {responder.symbol_for(Action.CONFIRM)} to continue."
    pixels = _pixels(screen.grab().toImage().convertToFormat(QImage.Format_ARGB32))
    blue = QColor(responder.confirm_colour)
    assert ((pixels[..., 0] == blue.blue()) & (pixels[..., 1] == blue.green())
            & (pixels[..., 2] == blue.red())).any()
    screen.deleteLater()


def test_prose_is_clipped_to_its_box_as_drawtext_is(app, loaded):
    """Text that overflows its box must not paint over what is below it -- the VAS line, the
    anchors. `drawText` clips at the box and stops laying lines out past it."""
    responder = Responder(loaded.hardware)
    responder.confirm_colour = vas_module.FOREGROUND.name()
    symbol = responder.symbol_for(Action.CONFIRM)
    text = "\n".join(f"Line {n}: press {symbol}." for n in range(8))
    box = QRect(0, 0, 400, 120)
    tall = QRect(0, 0, 400, 600)

    def inside(draw):
        return _render(draw, tall, QUESTION_POINT_SIZE, 1.0)

    plain = inside(lambda p: p.drawText(box, vas_module.PROSE_FLAGS, text))
    prose = inside(lambda p: vas_module.draw_prose(p, box, text, responder))
    empty = inside(lambda p: None)
    below = _pixels(prose)[box.bottom() + 1:]
    assert (below == _pixels(empty)[box.bottom() + 1:]).all(), "drawn past the box"
    assert prose == plain
