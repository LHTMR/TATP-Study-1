"""The launcher. SPEC.md 4.1, 6, 15.

Stream D's `preflight` and `build` are replaced by fakes that record what they were given:
what is tested here is what the launcher collects and how it answers what they say.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from tatp import config as cfg
from tatp import launcher
from tatp import schedule as sched
from tatp.launcher import REFUSE, RESUME_KEY, WARN, LauncherWindow
from tools import preview_schedule

T_ZERO = datetime(2026, 9, 24, 9, 30)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


class Fakes:
    def __init__(self, findings=()):
        self.findings = list(findings)
        self.checked = []
        self.built = []
        self.started = False

    def preflight(self, config, args):
        self.checked.append((config, args))
        return self.findings

    def build(self, config, args):
        self.built.append((config, args))
        fakes = self

        class Runner:
            completed = True

            def start(self):
                fakes.started = True

        return Runner()


def _choose(combo, value) -> None:
    combo.setCurrentIndex(combo.findData(value))


def _filled(window, tmp_path):
    dialog = window.session_dialog()
    dialog.participant.setText("07")
    dialog.experimenter.setText("SM")
    _choose(dialog.session_number, 1)
    _choose(dialog.participant_language, "sv")
    _choose(dialog.experimenter_language, "en")
    _choose(dialog.garment, "mock")
    dialog.data_folder.setText(str(tmp_path / "data"))
    dialog.pattern_folder.setText(str(cfg.CONFIG_DIR / "patterns" / "examples"))
    return dialog


def test_the_garment_starts_unchosen_and_is_required(app, loaded, tmp_path):
    """Chosen at launch, never defaulted: a pilot on the wrong rig is wrong data."""
    fakes = Fakes()
    dialog = _filled(LauncherWindow(loaded, fakes.preflight, fakes.build), tmp_path)
    dialog.garment.setCurrentIndex(0)
    assert dialog.garment.currentData() is None
    words = loaded.experimenter_text["launcher"]
    assert words["garment"] in dialog.missing()


def test_the_chosen_garment_is_the_session_driver(app, loaded, tmp_path):
    """hardware.yaml stays on the mock; the dialog's choice reaches the session's config."""
    fakes = Fakes()
    dialog = _filled(LauncherWindow(loaded, fakes.preflight, fakes.build), tmp_path)
    configured = loaded.hardware["garment"]["driver"]
    _choose(dialog.garment, "arduino_mosfet")
    args = dialog.args()
    assert args.garment == "arduino_mosfet"
    assert dialog.config(args).hardware["garment"]["driver"] == "arduino_mosfet"
    assert loaded.hardware["garment"]["driver"] == configured, "the loaded config is untouched"


RESUME ={"completed": "blocks 1-4", "since_sensitisation": "1 h 12 min"}


def test_the_four_entries_are_all_enabled(app, loaded):
    """SPEC.md 4.1."""
    window = LauncherWindow(loaded, Fakes().preflight, Fakes().build)
    assert list(window.entries) == [
        "run_session", "instruments", "design_pattern", "preview_schedule"
    ]
    for entry in window.entries.values():
        assert entry.isEnabled()


def test_entry_3_opens_the_pattern_designer(app, loaded):
    """SPEC.md 12.2: launcher entry 3 is tools/design_pattern.py."""
    from tools.design_pattern import DesignerWindow

    window = LauncherWindow(loaded, Fakes().preflight, Fakes().build)
    window.entries["design_pattern"].click()
    assert isinstance(window.designer, DesignerWindow)
    assert window.designer.isVisible()
    assert window.designer.windowTitle() == loaded.experimenter_text["designer"]["title"]
    window.designer.close()


def test_a_second_click_raises_the_open_designer_and_keeps_its_work(app, loaded):
    """Review item 3: a new window each click discarded the unsaved work in the old one."""
    window = LauncherWindow(loaded, Fakes().preflight, Fakes().build)
    first = window.open_designer()
    first.name_field.setText("unsaved")
    window.entries["design_pattern"].click()
    assert window.designer is first
    assert first.name_field.text() == "unsaved"
    first.close()
    assert window.open_designer() is not first
    window.designer.close()


def test_starting_a_session_closes_the_designer(app, loaded, tmp_path):
    """A designer left open would show pattern names beside a running session (SPEC.md 16)."""
    fakes = Fakes()
    window = LauncherWindow(loaded, fakes.preflight, fakes.build)
    designer = window.open_designer()
    dialog = _filled(window, tmp_path)
    dialog.start()
    assert fakes.started
    assert not designer.isVisible()


def test_the_dialog_asks_for_exactly_what_spec_6_lists(app, loaded, tmp_path):
    window = LauncherWindow(loaded, Fakes().preflight, Fakes().build)
    dialog = _filled(window, tmp_path)
    args = dialog.args()
    assert (args.participant, args.session, args.experimenter) == ("07", 1, "SM")
    assert (args.participant_language, args.experimenter_language) == ("sv", "en")
    assert args.data_folder == tmp_path / "data"
    assert args.patterns == cfg.CONFIG_DIR / "patterns" / "examples"


def test_there_is_no_default_pattern_folder(app, loaded):
    """LOG N6.14: a default would quietly run the provisional example patterns."""
    dialog = LauncherWindow(loaded, Fakes().preflight, Fakes().build).session_dialog()
    assert dialog.pattern_folder.text() == ""
    assert dialog.data_folder.text(), "the data folder does default, from hardware.yaml"


@pytest.mark.parametrize("combo", ["session_number", "participant_language",
                                   "experimenter_language"])
def test_the_session_number_and_languages_start_unchosen(app, loaded, tmp_path, combo):
    """SPEC.md 6: nothing the experimenter supplies is defaulted."""
    fakes = Fakes()
    window = LauncherWindow(loaded, fakes.preflight, fakes.build)
    assert getattr(window.session_dialog(), combo).currentData() is None
    dialog = _filled(window, tmp_path)
    getattr(dialog, combo).setCurrentIndex(0)
    assert not dialog.check()
    assert not dialog.start_button.isEnabled()
    assert fakes.checked == []
    assert dialog.text["launcher"][combo] in dialog.report.text()


def test_a_missing_field_stops_the_check_before_preflight(app, loaded):
    fakes = Fakes()
    dialog = LauncherWindow(loaded, fakes.preflight, fakes.build).session_dialog()
    assert not dialog.check()
    assert fakes.checked == []
    assert not dialog.start_button.isEnabled()
    assert dialog.text["launcher"]["pattern_folder"] in dialog.report.text()


def test_a_refusal_keeps_start_disabled(app, loaded, tmp_path):
    fakes = Fakes([(REFUSE, "warnings.cloud_sync", "OneDrive")])
    dialog = _filled(LauncherWindow(loaded, fakes.preflight, fakes.build), tmp_path)
    assert not dialog.check()
    assert not dialog.start_button.isEnabled()
    assert "OneDrive" in dialog.report.text()
    dialog.start()
    assert fakes.built == [], "a refused session is never built"


def test_a_warning_is_shown_and_the_session_may_start(app, loaded, tmp_path):
    fakes = Fakes([(WARN, "warnings.experimenter_changed", "")])
    dialog = _filled(LauncherWindow(loaded, fakes.preflight, fakes.build), tmp_path)
    assert dialog.check()
    assert dialog.start_button.isEnabled()
    assert dialog.text["warnings"]["experimenter_changed"] in dialog.report.text()


def test_editing_after_a_check_makes_it_stale(app, loaded, tmp_path):
    fakes = Fakes()
    dialog = _filled(LauncherWindow(loaded, fakes.preflight, fakes.build), tmp_path)
    assert dialog.check()
    dialog.participant.setText("08")
    assert not dialog.start_button.isEnabled()


def test_an_unknown_severity_is_an_error_not_a_guess(app, loaded, tmp_path):
    fakes = Fakes([("maybe", "warnings.cloud_sync", "x")])
    dialog = _filled(LauncherWindow(loaded, fakes.preflight, fakes.build), tmp_path)
    with pytest.raises(ValueError, match="severity"):
        dialog.check()


def test_start_builds_with_the_chosen_folder_and_the_room(app, loaded, tmp_path):
    fakes = Fakes()
    window = LauncherWindow(loaded, fakes.preflight, fakes.build)
    window.set_environment(21.5, None)
    dialog = _filled(window, tmp_path)
    _choose(dialog.participant_language, "en")
    dialog.start()
    assert fakes.started and window.runner is not None
    config, args = fakes.built[0]
    assert config.hardware["data"]["folder"] == str(tmp_path / "data")
    assert config.participant_language == "en"
    assert args.room_temperature_c == 21.5
    assert args.relative_humidity_pct is None
    assert args.resume is None, "no unfinished session, so no question was asked"
    assert "21.5" in window.environment_line.text()


@pytest.mark.parametrize("answer", [True, False])
def test_an_unfinished_session_is_put_as_a_question(app, loaded, tmp_path, monkeypatch,
                                                    answer):
    """SPEC.md 15. The offer is not a warning and is not listed as one."""
    fakes = Fakes([(WARN, RESUME_KEY, RESUME)])
    dialog = _filled(LauncherWindow(loaded, fakes.preflight, fakes.build), tmp_path)
    asked = []
    monkeypatch.setattr(dialog, "ask_resume", lambda value: asked.append(value) or answer)
    dialog.start()
    assert asked == [RESUME]
    assert fakes.built[0][1].resume is answer
    assert "1 h 12 min" not in dialog.report.text()


def test_the_resume_question_says_what_was_done_and_when(app, loaded, tmp_path):
    """SPEC.md 15: what was completed and how long ago sensitisation began."""
    dialog = _filled(LauncherWindow(loaded, Fakes().preflight, Fakes().build), tmp_path)
    shown = dialog.resume_dialog(RESUME).message.text()
    assert "blocks 1-4" in shown and "1 h 12 min" in shown


def test_dismissing_the_resume_question_starts_nothing(app, loaded, tmp_path, monkeypatch):
    fakes = Fakes([(WARN, RESUME_KEY, RESUME)])
    dialog = _filled(LauncherWindow(loaded, fakes.preflight, fakes.build), tmp_path)
    monkeypatch.setattr(dialog, "ask_resume", lambda value: None)
    dialog.start()
    assert fakes.built == []


@pytest.mark.parametrize(
    "press, expected",
    [("accept_button", True), ("reject_button", False), (None, None)],
)
def test_only_an_explicit_choice_answers_the_resume_question(app, loaded, tmp_path,
                                                            monkeypatch, press, expected):
    """Esc or the close box is no answer; only Start a new session means False."""
    dialog = _filled(LauncherWindow(loaded, Fakes().preflight, Fakes().build), tmp_path)
    made = dialog.resume_dialog(RESUME)
    monkeypatch.setattr(dialog, "resume_dialog", lambda value: made)

    def exec_():
        if press is None:
            made.reject()
        else:
            getattr(made, press).click()
        return made.result()

    monkeypatch.setattr(made, "exec", exec_)
    assert dialog.ask_resume(RESUME) is expected


def test_a_dict_value_fills_named_fields():
    assert launcher.formatted("{a} and {b}", {"a": 1, "b": 2}) == "1 and 2"
    assert launcher.formatted("got {value}", 3) == "got 3"


def test_the_preview_shows_the_tools_report(app, loaded):
    """SPEC.md 7.2: the same report as tools/preview_schedule.py, every block in it."""
    schedule = sched.generate(loaded.schedule)
    shown = launcher.preview_lines(loaded, T_ZERO)
    assert shown == preview_schedule.render(schedule, T_ZERO, separator="\t")
    padded = preview_schedule.render(schedule, T_ZERO)
    assert len(shown) == len(padded), "the same report, only the separator differs"
    assert [line.split() for line in shown] == [line.split() for line in padded]
    for row in schedule.preview_rows(T_ZERO):
        assert any(line.startswith(f"{row['index']}\t") for line in shown)
    window = LauncherWindow(loaded, Fakes().preflight, Fakes().build)
    dialog = window.preview_dialog(T_ZERO)
    assert dialog.report.isReadOnly()
    assert dialog.report.toPlainText() == "\n".join(shown)


def test_finish_reports_whether_the_session_completed():
    assert launcher.finish(None) == 0

    class Session:
        closed = 0

        def close(self):
            Session.closed += 1

    class Runner:
        session = Session()
        completed = False

    assert launcher.finish(Runner()) == 1
    assert Session.closed == 1


def test_the_entry_points_are_stream_ds(monkeypatch):
    """`preflight` and `build` are run_session's, reached when called."""
    import run_session

    monkeypatch.setattr(run_session, "preflight", lambda config, args: ["found"], raising=False)
    monkeypatch.setattr(run_session, "build", lambda config, args: "built")
    assert launcher.preflight(None, None) == ["found"]
    assert launcher.build(None, None) == "built"


def test_lookup_reads_a_dotted_key(loaded):
    text = loaded.experimenter_text
    assert launcher.lookup(text, "dialogs.resume_found") == text["dialogs"]["resume_found"]
    with pytest.raises(KeyError):
        launcher.lookup(text, "dialogs.no_such_key")


def test_run_launcher_is_importable_with_its_signature():
    import inspect

    assert list(inspect.signature(launcher.run_launcher).parameters) == ["argv"]
    assert Path(launcher.__file__).name == "launcher.py"
