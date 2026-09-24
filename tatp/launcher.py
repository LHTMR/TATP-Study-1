"""The launcher. SPEC.md 4.1, 6, 8.1, 15.

Four entries, so the auxiliary tools are reachable without the command line:

1. **Run a session.** A dialog collecting exactly what SPEC.md 6 lists -- participant code,
   session number, experimenter initials, both languages, the data folder and the pattern
   folder, which has no default (docs/LOG.md N6.14). *Check* runs the session's preflight and
   shows what it found, refusals apart from warnings; *Start* is offered only once nothing
   refuses. An unfinished session found by the preflight is put to the experimenter as a
   question (SPEC.md 15).
2. **Instruments and environment** (`tatp/instruments.py`).
3. **Design a pattern.** Not built: shown, disabled, with the reason (Milestone 6).
4. **Preview schedule.** `tools/preview_schedule.py`'s report, in a window.

**The session is started by `run_session`'s `preflight` and `build`, not here.** Both are
reached through `preflight()` and `build()` below, imported when called: `run_session.py`
imports this module to open the launcher, so importing it back at module level is a cycle.
`LauncherWindow` takes them as arguments, which is how the tests drive it with fakes.

What `preflight(config, args)` returns: a list of `(severity, text_key, value)`. `severity` is
`REFUSE` or `WARN`; `text_key` is a dotted key into the experimenter text, formatted with
`**value` when `value` is a dict and with `value=value` otherwise. One finding is special:
`dialogs.resume_found`, the offer to resume an unfinished session, whose `value` is
`{"completed": str, "since_sensitisation": str}` (SPEC.md 15). The answer goes to `build` as
`args.resume`, True or False; a dismissed question starts nothing.

The session number and both languages start unchosen, and Start stays disabled until each has
been picked (SPEC.md 6: nothing supplied by the experimenter is defaulted).
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import yaml
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tatp import config as cfg
from tatp import schedule as sched
from tatp.instruments import FILAMENTS_PATH, InstrumentsDialog
from tatp.ui.application import application
from tatp.ui.widgets import (
    DISCONNECTED_COLOUR,
    GROUP_GAP_PX,
    ITEM_GAP_PX,
    MARGIN_PX,
    SECONDARY,
    SIZE_BODY,
    SIZE_HEADLINE,
    SIZE_LARGE,
    SIZE_SMALL,
    WARNING_COLOUR,
    MessageDialog,
    button,
    label,
    line_edit,
    sized,
    stylesheet,
)

LANGUAGES = ("sv", "en")
# The launcher's own screens open before anyone has chosen a language, so they are drawn in the
# experimenter language run_session.py defaults to. The config is loaded with a participant
# language only because loading needs one; the session's own are chosen in the dialog.
DEFAULT_LANGUAGE = "en"
DEFAULT_PARTICIPANT_LANGUAGE = "sv"

REFUSE = "refuse"
WARN = "warn"
SEVERITIES = (REFUSE, WARN)
RESUME_KEY = "dialogs.resume_found"
# The resume question's result codes: QDialog's Accepted is resume, Rejected (Esc, the close
# box) is no answer at all, and this is the explicit new session.
NEW_SESSION = 2
RESUME_ANSWERS = {QDialog.DialogCode.Accepted.value: True, NEW_SESSION: False}

LAUNCHER_WIDTH_PX = 720
PREVIEW_WIDTH_PX = 900
PREVIEW_HEIGHT_PX = 640
PREVIEW_TAB_PX = 110
TAB = "\t"

Finding = tuple[str, str, object]


# -- Stream D's session entry points, SPEC.md 4.1 ------------------------------------------


def preflight(config: cfg.Config, args: argparse.Namespace) -> list[Finding]:
    """`run_session.preflight`: what would stop or qualify this session, before it starts."""
    import run_session

    return run_session.preflight(config, args)


def build(config: cfg.Config, args: argparse.Namespace):
    """`run_session.build`: the session and both windows, returned unstarted."""
    import run_session

    return run_session.build(config, args)


def formatted(template: str, value: object) -> str:
    """A finding's wording: a dict fills named fields, anything else fills `{value}`."""
    return template.format(**value) if isinstance(value, dict) else template.format(value=value)


def lookup(text: dict, dotted: str) -> str:
    node: object = text
    for part in dotted.split("."):
        node = node[part]
    assert isinstance(node, str), f"{dotted} is not a string in the experimenter text"
    return node


# -- the session dialog, SPEC.md 6 ----------------------------------------------------------


class SessionDialog(QDialog):
    """The seven things a session needs from the experimenter. Everything else is config."""

    def __init__(
        self,
        text: dict,
        hardware: dict,
        n_sessions: int,
        environment: dict,
        preflight: Callable[[cfg.Config, argparse.Namespace], list[Finding]],
        start: Callable[[cfg.Config, argparse.Namespace], None],
        load: Callable[[str, str], cfg.Config] = cfg.load,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.text = text
        self.environment = environment
        self._preflight = preflight
        self._start = start
        self._load = load
        self.findings: list[Finding] = []
        words = text["launcher"]
        self.setWindowTitle(words["session_title"])
        self.setStyleSheet(stylesheet())

        # The session number and both languages start unchosen (SPEC.md 6): a default would be
        # a value the experimenter never supplied, and a wrong session number or participant
        # language is a whole session run against the wrong allocation or in the wrong words.
        self.participant = line_edit(SIZE_BODY)
        self.session_number = self._choice(
            [(str(number), number) for number in range(1, n_sessions + 1)]
        )
        self.experimenter = line_edit(SIZE_BODY)
        languages = [(text["terms"]["languages"][code], code) for code in LANGUAGES]
        self.participant_language = self._choice(languages)
        self.experimenter_language = self._choice(languages)
        self.data_folder = line_edit(SIZE_BODY)
        self.data_folder.setText(str(_resolve(hardware["data"]["folder"])))
        # No default (docs/LOG.md N6.14): defaulting to config/patterns/examples/ would quietly
        # run the provisional mockups in place of the real patterns (open item 5).
        self.pattern_folder = line_edit(SIZE_BODY)
        self.pattern_folder.setPlaceholderText(words["no_pattern_folder"])

        form = QFormLayout()
        form.setVerticalSpacing(ITEM_GAP_PX)
        for key, widget in (
            ("participant_code", self.participant),
            ("session_number", self.session_number),
            ("experimenter_initials", self.experimenter),
            ("participant_language", self.participant_language),
            ("experimenter_language", self.experimenter_language),
            ("data_folder", self._with_browse(self.data_folder)),
            ("pattern_folder", self._with_browse(self.pattern_folder)),
        ):
            caption = label(SIZE_SMALL, colour=SECONDARY)
            caption.setText(words[key])
            form.addRow(caption, widget)

        self.report = label(SIZE_BODY, wrap=True)
        self.check_button = button(words["check"], SIZE_BODY)
        self.start_button = button(words["start"], SIZE_BODY)
        self.close_button = button(words["close"], SIZE_BODY)
        self.start_button.setEnabled(False)
        self.check_button.clicked.connect(self.check)
        self.start_button.clicked.connect(self.start)
        self.close_button.clicked.connect(self.reject)
        # Anything edited after a check makes the check stale.
        typed = (self.participant, self.experimenter, self.data_folder, self.pattern_folder)
        for field in typed:
            field.textChanged.connect(self._stale)
        chosen = (self.session_number, self.participant_language, self.experimenter_language)
        for combo in chosen:
            combo.currentIndexChanged.connect(self._stale)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.start_button)

        title = label(SIZE_LARGE)
        title.setText(words["session_title"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(title)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(form)
        layout.addSpacing(GROUP_GAP_PX)
        layout.addWidget(self.report)
        layout.addStretch(1)
        layout.addLayout(buttons)

    def _choice(self, options: list[tuple[str, object]]) -> QComboBox:
        """A choice that starts on a placeholder carrying no value, so nothing is assumed."""
        combo = sized(QComboBox(), SIZE_BODY)
        combo.addItem(self.text["launcher"]["choose"], None)
        for shown, value in options:
            combo.addItem(shown, value)
        combo.setCurrentIndex(0)
        return combo

    def _with_browse(self, field: QLineEdit) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field, 1)
        browse = button(self.text["launcher"]["browse"])
        browse.clicked.connect(lambda: self._browse(field))
        row.addWidget(browse)
        return holder

    def _browse(self, field: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "", field.text())
        if chosen:
            field.setText(chosen)

    def _stale(self, *_) -> None:
        self.start_button.setEnabled(False)

    # -- what was entered -------------------------------------------------------------

    def missing(self) -> list[str]:
        words = self.text["launcher"]
        empty = [
            words[key]
            for key, field in (
                ("participant_code", self.participant),
                ("experimenter_initials", self.experimenter),
                ("data_folder", self.data_folder),
                ("pattern_folder", self.pattern_folder),
            )
            if not field.text().strip()
        ]
        empty += [
            words[key]
            for key, combo in (
                ("session_number", self.session_number),
                ("participant_language", self.participant_language),
                ("experimenter_language", self.experimenter_language),
            )
            if combo.currentData() is None
        ]
        return empty

    def args(self) -> argparse.Namespace:
        """As `run_session.parse_args` returns them, plus the room and the resume answer."""
        return argparse.Namespace(
            participant=self.participant.text().strip(),
            session=self.session_number.currentData(),
            experimenter=self.experimenter.text().strip(),
            patterns=Path(self.pattern_folder.text().strip()),
            participant_language=self.participant_language.currentData(),
            experimenter_language=self.experimenter_language.currentData(),
            data_folder=Path(self.data_folder.text().strip()),
            clock_speed=1.0,
            seed=None,
            room_temperature_c=self.environment["room_temperature_c"],
            relative_humidity_pct=self.environment["relative_humidity_pct"],
            resume=None,
        )

    def config(self, args: argparse.Namespace) -> cfg.Config:
        """The configuration for these languages, with the data folder the dialog chose."""
        loaded = self._load(args.participant_language, args.experimenter_language)
        data = {**loaded.hardware["data"], "folder": str(args.data_folder)}
        return dataclasses.replace(loaded, hardware={**loaded.hardware, "data": data})

    # -- check, then start ------------------------------------------------------------

    def check(self) -> bool:
        """Run the preflight and show what it found. True when nothing refuses."""
        words = self.text["launcher"]
        missing = self.missing()
        if missing:
            self._show([words["missing_field"].format(value=", ".join(missing))], [])
            self.start_button.setEnabled(False)
            return False
        args = self.args()
        self.findings = list(self._preflight(self.config(args), args))
        refusals, warnings = [], []
        for severity, key, value in self.findings:
            if key == RESUME_KEY:
                continue
            if severity not in SEVERITIES:
                raise ValueError(f"preflight severity {severity!r} is not one of {SEVERITIES}")
            line = formatted(lookup(self.text, key), value)
            (refusals if severity == REFUSE else warnings).append(line)
        self._show(refusals, warnings)
        self.start_button.setEnabled(not refusals)
        return not refusals

    def _show(self, refusals: list[str], warnings: list[str]) -> None:
        words = self.text["launcher"]
        lines = []
        if refusals:
            lines.append(words["refusals"])
            lines.extend(f"• {line}" for line in refusals)
        if warnings:
            lines.append(words["warnings"])
            lines.extend(f"• {line}" for line in warnings)
        self.report.setText("\n".join(lines) if lines else words["no_findings"])
        # A refusal and a warning ask for different things, so they are not the same colour
        # (UI_PRINCIPLES.md 3.4).
        colour = DISCONNECTED_COLOUR if refusals else WARNING_COLOUR if warnings else SECONDARY
        self.report.setStyleSheet(f"color: {colour};")

    def resume_dialog(self, value: dict) -> MessageDialog:
        """SPEC.md 15: what was completed and how long ago sensitisation began.

        `value` is `{"completed": str, "since_sensitisation": str}`, both formatted by the
        session from its own text. Resume accepts, Start a new session finishes with
        `NEW_SESSION`, and anything else -- Esc, the close box -- rejects.
        """
        assert isinstance(value, dict), f"the resume offer carries a dict, not {value!r}"
        dialogs = self.text["dialogs"]
        dialog = MessageDialog(
            self.text["launcher"]["session_title"],
            dialogs["resume_found"].format(**value),
            dialogs["resume_yes"],
            dialogs["resume_no"],
            parent=self,
        )
        dialog.reject_button.clicked.disconnect()
        dialog.reject_button.clicked.connect(lambda: dialog.done(NEW_SESSION))
        return dialog

    def start(self) -> None:
        """Start, asking first about an unfinished session if the preflight found one.

        A dismissed question starts nothing: only an explicit choice decides between resuming
        a session and starting another over it.
        """
        if not self.check():
            return
        args = self.args()
        offer = [value for _, key, value in self.findings if key == RESUME_KEY]
        if offer:
            args.resume = self.ask_resume(offer[0])
            if args.resume is None:
                return
        self._start(self.config(args), args)
        self.accept()

    def ask_resume(self, value: dict) -> bool | None:
        """True to resume, False for a new session, None when the question was dismissed."""
        return RESUME_ANSWERS.get(self.resume_dialog(value).exec())


# -- the preview, SPEC.md 7.2 --------------------------------------------------------------


def preview_lines(config: cfg.Config, t_zero: datetime) -> list[str]:
    """`tools/preview_schedule.py`'s report, unchanged, with its columns tab-separated.

    The tool pads with spaces for a terminal, which only lines up in a fixed-pitch face, and
    the study font is proportional; the window sets tab stops instead.
    """
    from tools import preview_schedule

    return preview_schedule.render(sched.generate(config.schedule), t_zero, separator=TAB)


class PreviewDialog(QDialog):
    """`tools/preview_schedule.py`'s report, read-only, in a fixed-width font."""

    def __init__(self, text: dict, config: cfg.Config, t_zero: datetime, parent=None):
        super().__init__(parent)
        words = text["launcher"]
        self.setWindowTitle(words["preview_title"])
        self.setStyleSheet(stylesheet())
        self.resize(PREVIEW_WIDTH_PX, PREVIEW_HEIGHT_PX)
        self.report = sized(QPlainTextEdit(), SIZE_SMALL)
        self.report.setReadOnly(True)
        self.report.setTabStopDistance(PREVIEW_TAB_PX)
        self.report.setPlainText("\n".join(preview_lines(config, t_zero)))
        close = button(words["close"], SIZE_BODY)
        close.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(self.report, 1)
        layout.addWidget(close)


# -- the launcher window, SPEC.md 4.1 -------------------------------------------------------


class LauncherWindow(QWidget):
    """The four entries. `runner` is the started session, once there is one."""

    def __init__(
        self,
        config: cfg.Config,
        preflight: Callable = preflight,
        build: Callable = build,
        filaments_path: Path = FILAMENTS_PATH,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.config = config
        self.text = config.experimenter_text
        self._preflight = preflight
        self._build = build
        self.filaments_path = filaments_path
        self.runner = None
        # Handed from the instruments entry to the next session start (SPEC.md 8.1).
        self.environment = {"room_temperature_c": None, "relative_humidity_pct": None}
        words = self.text["launcher"]
        self.setWindowTitle(words["title"])
        self.setStyleSheet(stylesheet())
        self.setMinimumWidth(LAUNCHER_WIDTH_PX)

        title = label(SIZE_HEADLINE)
        title.setText(words["title"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(title)
        layout.addSpacing(GROUP_GAP_PX)
        self.entries: dict[str, QPushButton] = {}
        for key, action in (
            ("run_session", self.open_session_dialog),
            ("instruments", self.open_instruments),
            ("design_pattern", None),
            ("preview_schedule", self.open_preview),
        ):
            entry = button(words[key], SIZE_LARGE)
            detail = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
            detail.setText(words[f"{key}_detail"])
            if action is None:
                # SPEC.md 4.1 lists it, so it is shown; it does nothing yet, so it says why.
                entry.setEnabled(False)
            else:
                entry.clicked.connect(action)
            self.entries[key] = entry
            layout.addWidget(entry)
            layout.addWidget(detail)
            layout.addSpacing(ITEM_GAP_PX)
        self.environment_line = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        layout.addWidget(self.environment_line)
        layout.addStretch(1)

    # -- the entries --------------------------------------------------------------------

    def session_dialog(self) -> SessionDialog:
        return SessionDialog(
            self.text,
            self.config.hardware,
            int(self.config.study1["design"]["n_sessions"]),
            self.environment,
            self._preflight,
            self._start_session,
            parent=self,
        )

    def instruments_dialog(self) -> InstrumentsDialog:
        # Read afresh, not from the loaded config: a save since startup has changed the file.
        return InstrumentsDialog(
            self.text,
            yaml.safe_load(self.filaments_path.read_text(encoding="utf-8")),
            self.set_environment,
            path=self.filaments_path,
            parent=self,
        )

    def preview_dialog(self, t_zero: datetime | None = None) -> PreviewDialog:
        return PreviewDialog(self.text, self.config, t_zero or datetime.now(), parent=self)

    def open_session_dialog(self) -> SessionDialog:
        dialog = self.session_dialog()
        dialog.open()
        return dialog

    def open_instruments(self) -> InstrumentsDialog:
        dialog = self.instruments_dialog()
        dialog.open()
        return dialog

    def open_preview(self) -> PreviewDialog:
        dialog = self.preview_dialog()
        dialog.open()
        return dialog

    def set_environment(self, temperature_c: float | None, humidity_pct: float | None) -> None:
        self.environment["room_temperature_c"] = temperature_c
        self.environment["relative_humidity_pct"] = humidity_pct
        missing = self.text["fit_preview"]["missing"]
        self.environment_line.setText(
            self.text["launcher"]["environment_entered"].format(
                temperature=missing if temperature_c is None else f"{temperature_c:g}",
                humidity=missing if humidity_pct is None else f"{humidity_pct:g}",
            )
        )

    def _start_session(self, config: cfg.Config, args: argparse.Namespace) -> None:
        self.runner = self._build(config, args)
        self.hide()
        self.runner.start()


def _resolve(folder: str) -> Path:
    path = Path(folder)
    return path if path.is_absolute() else cfg.REPO_ROOT / path


def finish(runner) -> int:
    """After the event loop: close the session if one ran. 0 when it completed."""
    if runner is None:
        return 0
    # Closing twice is safe, and covers a window shut by hand (run_session.main does the same).
    runner.session.close()
    return 0 if runner.completed else 1


def run_launcher(argv: list[str] | None = None) -> int:
    """Open the launcher and run until it, or the session it started, is closed."""
    parser = argparse.ArgumentParser(description="TATP Study 1 launcher (SPEC.md 4.1).")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE, choices=LANGUAGES,
                        help="the launcher's own language; the session's are chosen in it")
    args = parser.parse_args(argv)
    config = cfg.load(DEFAULT_PARTICIPANT_LANGUAGE, args.language)
    app = QApplication.instance() or application(config.hardware)
    launcher = LauncherWindow(config)
    launcher.show()
    app.exec()
    return finish(launcher.runner)


if __name__ == "__main__":
    sys.exit(run_launcher())
