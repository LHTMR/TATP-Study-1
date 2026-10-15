"""The hardware page: shown first, before the launcher, and again from its entry 5.

S's first lab run (30 Sep 2026) found two faults only a participant would otherwise have met:
the remote's keys mapped the wrong way round, and no sound in the headphones (docs/LOG.md
N7.F4). And a session could only run on the lab's own hardware, because hardware.yaml named it
(S, 15 Oct 2026). So, as a videoconferencing program does before a call, this page puts every
device the session uses in front of the experimenter, chosen from what is connected, with
hardware.yaml's lab setup as the default, and tests each through the session's own code
(docs/LOG.md N7.F12e1):

- **The participant's responses.** The remote, found or not; or, when it is missing, an
  alternative for a pilot code or a demonstration -- the keyboard, or buttons on the participant
  window for a mouse or trackpad (N7.F12e4). Each button counts its presses through the
  session's own `Responder`, so a wrong mapping shows as the wrong button counting. The page
  takes every response key while it is open: ▶'s second key is `escape`, which would otherwise
  close it every other press.
- **The screens.** Each connected display, or a window on the experimenter's screen; and a label
  put up where the participant's window will be.
- **The sound.** Each output device present, or the system's default, for the participant's
  headphones and the experimenter's speakers. The noise runs through the session's own `Audio`,
  bounded by the participant's own range, so the page adds no sound level and the ceiling still
  holds (SPEC.md 10.7).
- **The garment.** The prototype sleeve's serial port from those present, and each channel on
  and off through the session's own driver. A valve garment is set to the masking check's
  pressure, the setup's existing low one, so the page adds no pressure either.

**Found without restarting** (N7.F12e2). Screens are Qt's own signals; serial ports and the
remote are read again every `devices.poll_interval_s`; sound devices are listed by a child
process every `devices.audio_poll_interval_s`, and the page's test sounds play in one too, so
this process never loads PortAudio before a session does (`tatp/devices.py` says why).

Each choice follows what is connected until it is changed by hand: the lab's device while it is
there, and what stands in for it while it is not. A choice made by hand stays as made, missing
or not, and says so.

Nothing is recorded: no participant is involved. The page is modal, so no session can start
while it holds the garment's port or the headphones, and closing it lets both go.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import NamedTuple

import serial
import shiboken6
from PySide6.QtCore import QEvent, QObject, QProcess, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from tatp.audio import SOUNDDEVICE, Audio, AudioError
from tatp.clock import Clock
from tatp.config import REPO_ROOT
from tatp.devices import (
    ALERT,
    CUE,
    FAILED,
    KEYBOARD,
    PARTICIPANT_INPUTS,
    REMOTE,
    SET_LEVEL,
    START_NOISE,
    STOP_NOISE,
    HardwareChoices,
    configured,
    matching_outputs,
    on_lab_platform,
    probe_command,
    serve_command,
)
from tatp.garment.base import GarmentController, GarmentError, Limits
from tatp.remote_keys import (
    RAW_INPUT,
    RAW_INPUT_FAILED,
    REMOTE_DISCONNECTED,
    REMOTE_RECONNECTED,
    AnyKeyboard,
    key_source,
    raw_input_available,
    remote_present,
)
from tatp.responder import Action, Responder
from tatp.session import DRIVERS, hardware_with_choices
from tatp.ui.vas import QT_KEYS
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
    button,
    fit_to_screen,
    label,
    primary_button_style,
    sized,
    stylesheet,
)
from tatp.units import MS_PER_S

HARDWARE_CHECK_WIDTH_PX = 1200
HARDWARE_CHECK_HEIGHT_PX = 790
SLIDER_MIN_WIDTH_PX = 200
CAPTION_WIDTH_PX = 240
COMBO_MIN_CHARACTERS = 16
# Between the sections of a column: less than between the columns, so the four sections fit the
# laptop's height (docs/LOG.md N7.F12e1).
SECTION_GAP_PX = 14
# A failure to open a port or a sound device is what this page exists to show, so these are
# reported on screen rather than raised. Anything else still raises (CLAUDE.md, fail fast).
GARMENT_ERRORS = (GarmentError, serial.SerialException)
AUDIO_ERRORS = (AudioError, ValueError, OSError)

PARTICIPANT = "participant"
EXPERIMENTER = "experimenter"
SCREEN_CHOICES = {PARTICIPANT: "participant_screen_index",
                  EXPERIMENTER: "experimenter_screen_index"}
AUDIO_CHOICES = {PARTICIPANT: "participant_audio_device",
                 EXPERIMENTER: "experimenter_audio_device"}
PORT = "garment_port"
INPUT = "participant_input"
# How a choice's line is drawn: as expected, standing in for the lab's, or missing.
OK, STAND_IN, MISSING = "ok", "stand_in", "missing"
STATE_COLOURS = {OK: SECONDARY, STAND_IN: WARNING_COLOUR, MISSING: DISCONNECTED_COLOUR}


class Present(NamedTuple):
    """What is connected now. `remote` is None where it cannot be told from a keyboard;
    `outputs` is None until the sound devices have first been listed."""

    screens: list[tuple[int, int]]
    ports: list[str]
    remote: bool | None
    outputs: list[str] | None = None
    default_output: str | None = None
    audio_error: str = ""


class Detectors(NamedTuple):
    """How the page finds what is connected; the tests and the screenshots pass their own.
    `probe(audio_config, on_done)` lists the sound devices without waiting, then calls
    `on_done(result, error)` with `tatp.devices.probe`'s dict, or None and why not."""

    screens: Callable[[], list[tuple[int, int]]]
    ports: Callable[[], list[str]]
    remote: Callable[[], bool | None]
    probe: Callable[[dict, Callable[[dict | None, str], None]], None]


def qt_screens() -> list[tuple[int, int]]:
    return [(screen.size().width(), screen.size().height())
            for screen in QGuiApplication.screens()]


def serial_ports() -> list[str]:
    return sorted(port.device for port in list_ports.comports())


class ChildProbe(QObject):
    """Lists the sound devices in a child process (`tatp.devices`), one listing at a time, and
    without waiting for it: the page stays live while PortAudio starts."""

    def __init__(self, timeout_s: float, parent: QObject):
        super().__init__(parent)
        self.timeout_ms = int(timeout_s * MS_PER_S)
        self.process: QProcess | None = None

    def __call__(self, audio_config: dict, on_done) -> None:
        if self.process is not None:
            return
        process = self.process = QProcess(self)
        process.setWorkingDirectory(str(REPO_ROOT))
        process.finished.connect(lambda *_: self._finished(process, on_done))
        program, arguments = probe_command(audio_config)
        process.start(program, arguments)
        QTimer.singleShot(self.timeout_ms, process, process.kill)

    def _finished(self, process: QProcess, on_done) -> None:
        # A page deleted with a listing under way kills the child as it goes, and that says
        # finished from a process already half gone, with nobody left to tell.
        if not shiboken6.isValid(process):
            return
        self.process = None
        output = bytes(process.readAllStandardOutput()).decode()
        if process.exitStatus() == QProcess.NormalExit and process.exitCode() == 0:
            on_done(json.loads(output), "")
        else:
            error = bytes(process.readAllStandardError()).decode().strip().splitlines()
            on_done(None, error[-1] if error else process.errorString())
        process.deleteLater()

    def stop(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process.waitForFinished()


def live_detectors(hardware: dict, parent: QObject) -> Detectors:
    """What the lab uses: Qt's screens, pyserial's ports, Raw Input's keyboards, and a child
    process for the sound devices."""
    responder = hardware["responder"]

    def remote() -> bool | None:
        if responder["key_source"] != RAW_INPUT or not raw_input_available():
            return None
        return remote_present(responder)

    return Detectors(qt_screens, serial_ports, remote,
                     ChildProbe(hardware["devices"]["probe_timeout_s"], parent))


class ChildAudio(QObject):
    """The page's test sounds, played by a child process through the session's own `Audio`
    (`tatp.devices serve`), so this process never loads PortAudio. What the page asks of an
    `Audio`, sent as commands; a sound that fails comes back as a line, to `on_failed`."""

    def __init__(self, audio_config: dict, on_failed: Callable[[str], None], parent: QObject):
        super().__init__(parent)
        self.backend_name = SOUNDDEVICE
        self.start_dbfs = float(audio_config["white_noise_start_dbfs"])
        self.max_dbfs = float(audio_config["white_noise_max_dbfs"])
        self.noise_level_dbfs: float | None = None
        self.noise_running = False
        self.on_failed = on_failed
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(REPO_ROOT))
        self.process.readyReadStandardOutput.connect(self._read)
        program, arguments = serve_command(audio_config)
        self.process.start(program, arguments)

    def _send(self, line: str) -> None:
        self.process.write(f"{line}\n".encode())

    def _read(self) -> None:
        for line in bytes(self.process.readAllStandardOutput()).decode().splitlines():
            if not line.startswith(FAILED):
                continue
            command, _, why = line.removeprefix(FAILED).partition(" ")
            if command == START_NOISE:
                self.noise_running = False
            self.on_failed(why)

    def start_noise(self, level_dbfs: float) -> None:
        self.noise_level_dbfs = min(float(level_dbfs), self.max_dbfs)
        self._send(f"{START_NOISE} {level_dbfs}")
        self.noise_running = True

    def set_noise_level(self, level_dbfs: float) -> None:
        self.noise_level_dbfs = min(float(level_dbfs), self.max_dbfs)
        self._send(f"{SET_LEVEL} {level_dbfs}")

    def stop_noise(self, _reason: str) -> None:
        self._send(STOP_NOISE)
        self.noise_running = False

    def participant_cue(self) -> None:
        self._send(CUE)

    def experimenter_alert(self, _reason: str) -> None:
        self._send(ALERT)

    def close(self) -> None:
        # End of input ends the child, which closes its streams first.
        self.process.closeWriteChannel()
        self.process.waitForFinished()


class RemoteKeys(QObject):
    """Takes the participant's response keys from every window while the page is open, and
    counts them.

    Under any_keyboard only. Under raw_input the remote's presses come from its raw reports
    (`HardwareCheckDialog.remote_key`), and every key event is another keyboard's, which does
    not count and passes through: the session's own split, where the experimenter can see it.
    """

    def __init__(self, responder: Responder, on_press: Callable[[str, Action], None],
                 parent: QObject | None = None):
        super().__init__(parent)
        self.responder = responder
        self.on_press = on_press
        self._names = {QT_KEYS[name]: name for name in responder.keys}

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt's name
        if event.type() not in (QEvent.KeyPress, QEvent.KeyRelease):
            return False
        name = self._names.get(Qt.Key(event.key()))
        if name is None:
            return False
        # A held button repeats; the count is of presses, as the session's own handling is.
        if event.type() == QEvent.KeyPress and not event.isAutoRepeat():
            self.on_press(name, self.responder.action_for(name))
        return True


class HardwareCheckDialog(QDialog):
    """The hardware page. `choices()` is what it chose; `garment` and `audio` are what is in
    use, for the tests to drive.

    `choices` reopens the page as it was left; None starts from hardware.yaml. `detectors` are
    how it finds what is connected, the lab's own (`live_detectors`) unless given.
    """

    def __init__(self, text: dict, hardware: dict, choices: HardwareChoices | None = None,
                 detectors: Detectors | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.text = text
        self.hardware = hardware
        self.words = words = text["hardware_check"]
        self.garment_names = text["terms"]["garments"]
        self.setWindowTitle(words["title"])
        self.setStyleSheet(stylesheet())
        self.clock = Clock()
        self.detectors = detectors or live_detectors(hardware, self)

        self.lab = configured(hardware)
        start = choices or self.lab
        self.values = {name: getattr(start, name) for name in self._names()}
        self.chosen = set(start.chosen)
        self.present = Present(self.detectors.screens(), self.detectors.ports(),
                               self.detectors.remote())
        self.combos: dict[str, QComboBox] = {}
        self.options: dict[str, list] = {}
        self.status: dict[str, QLabel] = {}
        # What each choice last showed, so a poll that finds nothing new leaves an open list be.
        self._shown: dict[str, tuple] = {}
        # Made last (below); until then a change of input has nothing to count with.
        self.key_source = None
        self.remote_keys: RemoteKeys | None = None
        self.released = False

        self.responder = Responder(self.session_hardware())
        self.presses: dict[Action, int] = {action: 0 for action in Action}
        self.audio = None
        self.sound_status = label(SIZE_SMALL, wrap=True, colour=DISCONNECTED_COLOUR)
        self.garment: GarmentController | None = None
        self.label_window: QLabel | None = None

        title = label(SIZE_LARGE)
        title.setText(words["title"])
        hint = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        hint.setText(words["page_hint"])
        # Two columns, so the whole page fits the lab laptop without scrolling; on a shorter
        # screen it scrolls, and Continue stays in view below it.
        content = QWidget()
        columns = QHBoxLayout(content)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(GROUP_GAP_PX * 2)
        for sections in ((self._input(), self._screens()),
                         (self._sound_section(), self._garment())):
            column = QVBoxLayout()
            column.setSpacing(SECTION_GAP_PX)
            for section in sections:
                column.addLayout(section)
            column.addStretch(1)
            columns.addLayout(column, 1)
        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cancel_button = button(text["launcher"]["cancel"], SIZE_BODY)
        self.cancel_button.clicked.connect(self.reject)
        self.continue_button = button(words["continue"], SIZE_BODY)
        self.continue_button.setStyleSheet(primary_button_style())
        self.continue_button.clicked.connect(self.accept)
        closing = QHBoxLayout()
        closing.addStretch(1)
        closing.addWidget(self.cancel_button)
        closing.addSpacing(GROUP_GAP_PX)
        closing.addWidget(self.continue_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addWidget(scroll, 1)
        layout.addLayout(closing)
        self.finished.connect(self.release)
        fit_to_screen(self, HARDWARE_CHECK_WIDTH_PX, HARDWARE_CHECK_HEIGHT_PX)

        self._update()
        self._start_sound()
        devices = hardware["devices"]
        self.poll = QTimer(self)
        self.poll.setInterval(int(devices["poll_interval_s"] * MS_PER_S))
        self.poll.timeout.connect(self.detect)
        self.poll.start()
        self.audio_poll = QTimer(self)
        self.audio_poll.setInterval(int(devices["audio_poll_interval_s"] * MS_PER_S))
        self.audio_poll.timeout.connect(self.probe_audio)
        self.audio_poll.start()
        app = QGuiApplication.instance()
        app.screenAdded.connect(self.detect)
        app.screenRemoved.connect(self.detect)
        self.probe_audio()
        # Last, once nothing above can raise: a filter installed by a page that failed to
        # build would never be removed, and would swallow every remote press in a later session.
        responder = hardware["responder"]
        if responder["key_source"] == RAW_INPUT and raw_input_available():
            self.key_source = key_source(responder, self, self.remote_key, self._remote_event)
        else:
            self.key_source = AnyKeyboard()
        self._apply_input()

    @staticmethod
    def _names() -> tuple[str, ...]:
        return (*SCREEN_CHOICES.values(), *AUDIO_CHOICES.values(), PORT, INPUT)

    # -- what was chosen -----------------------------------------------------------------

    def choices(self) -> HardwareChoices:
        return HardwareChoices(**self.values, chosen=frozenset(self.chosen))

    def session_hardware(self) -> dict:
        """hardware.yaml with these choices, as a session would run with them."""
        return hardware_with_choices(self.hardware, self.choices())

    # -- sections ------------------------------------------------------------------------

    def _heading(self, key: str, hint_key: str | None = None) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(ITEM_GAP_PX)
        heading = label(SIZE_BODY)
        heading.setText(self.words[key])
        section.addWidget(heading)
        if hint_key is not None:
            hint = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
            hint.setText(self.words[hint_key])
            section.addWidget(hint)
        return section

    def _row(self, *widgets: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(GROUP_GAP_PX)
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        return row

    def _choice(self, section: QVBoxLayout, name: str, caption_key: str) -> None:
        """A caption, its choice, and the line under it saying whether it is there."""
        caption = label(SIZE_SMALL, colour=SECONDARY)
        caption.setText(self.words[caption_key])
        caption.setFixedWidth(CAPTION_WIDTH_PX)
        combo = sized(QComboBox(), SIZE_SMALL)
        # A device's name can be long, and a combo box sized to its longest would push the page
        # wider than the laptop's screen; the list itself opens as wide as it needs.
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(COMBO_MIN_CHARACTERS)
        combo.activated.connect(lambda index, name=name: self.choose(name, index))
        row = QHBoxLayout()
        row.setSpacing(ITEM_GAP_PX)
        row.addWidget(caption)
        row.addWidget(combo, 1)
        status = label(SIZE_SMALL, wrap=True)
        self.combos[name] = combo
        self.status[name] = status
        section.addLayout(row)
        section.addWidget(status)

    def _input(self) -> QVBoxLayout:
        section = self._heading("input", "remote_hint")
        self._choice(section, INPUT, "input_choice")
        self.press_labels: dict[Action, QLabel] = {}
        for action in Action:
            self.press_labels[action] = label(SIZE_LARGE)
        self.last_key = label(SIZE_SMALL, colour=SECONDARY)
        section.addLayout(self._row(*self.press_labels.values(), self.last_key))
        self._show_presses()
        return section

    def _screens(self) -> QVBoxLayout:
        section = self._heading("screens")
        for role, name in SCREEN_CHOICES.items():
            self._choice(section, name, f"role_{role}")
        self.label_button = button(self.words["show_label"])
        self.label_button.clicked.connect(self.toggle_label)
        section.addLayout(self._row(self.label_button))
        return section

    def _sound_section(self) -> QVBoxLayout:
        section = self._heading("sound", "sound_hint")
        for role, name in AUDIO_CHOICES.items():
            self._choice(section, name, f"role_{role}_audio")
        self.noise_button = button(self.words["start_noise"])
        self.noise_button.clicked.connect(self.toggle_noise)
        audio_config = self.hardware["audio"]
        self.level = QSlider(Qt.Horizontal)
        self.level.setRange(round(audio_config["white_noise_start_dbfs"]),
                            round(audio_config["white_noise_max_dbfs"]))
        self.level.setSingleStep(round(audio_config["white_noise_step_db"]))
        self.level.setValue(round(audio_config["white_noise_start_dbfs"]))
        self.level.valueChanged.connect(self.set_level)
        self.level_label = label(SIZE_SMALL)
        self.cue_button = button(self.words["play_cue"])
        self.cue_button.clicked.connect(self.play_cue)
        self.cue_button.setEnabled(False)
        self.alert_button = button(self.words["play_alert"])
        self.alert_button.clicked.connect(self.play_alert)
        self.level.setMinimumWidth(SLIDER_MIN_WIDTH_PX)
        section.addLayout(self._row(self.noise_button, self.level, self.level_label))
        row = self._row(self.cue_button, self.alert_button)
        row.insertWidget(row.count() - 1, self.sound_status, 1)
        section.addLayout(row)
        self._show_level()
        return section

    def _garment(self) -> QVBoxLayout:
        section = self._heading("garment", "garment_hint")
        self.garment_choice = sized(QComboBox(), SIZE_SMALL)
        for driver in sorted(DRIVERS):
            self.garment_choice.addItem(self.garment_names[driver], driver)
        self.garment_choice.setCurrentIndex(
            self.garment_choice.findData(self.hardware["garment"]["driver"])
        )
        self.connect_button = button(self.words["connect"])
        self.connect_button.clicked.connect(self.toggle_garment)
        self._choice(section, PORT, "port")
        self.channel_buttons: dict[int, QPushButton] = {}
        channels = QHBoxLayout()
        channels.setSpacing(ITEM_GAP_PX)
        # Named once here, so each button has room to say on or off and the page still fits
        # the laptop's 1280 px (docs/LOG.md N7.U10).
        named = label(SIZE_SMALL, colour=SECONDARY)
        named.setText(self.words["channels"])
        channels.addWidget(named)
        n_channels = max(driver.n_channels for driver in DRIVERS.values())
        for channel in range(1, n_channels + 1):
            made = button("")
            made.setCheckable(True)
            made.setEnabled(False)
            made.toggled.connect(lambda on, channel=channel: self.set_channel(channel, on))
            self.channel_buttons[channel] = made
            channels.addWidget(made)
        channels.addStretch(1)
        self.garment_status = label(SIZE_SMALL, wrap=True, colour=SECONDARY)
        section.addLayout(self._row(self.garment_choice, self.connect_button))
        section.addLayout(channels)
        section.addWidget(self.garment_status)
        self._show_garment()
        return section

    # -- what is connected ---------------------------------------------------------------

    def detect(self, *_args) -> None:
        """Screens, ports and the remote, read again. Not once the page has closed: a change
        of input then would take the response keys from the session that follows."""
        if self.released:
            return
        self.present = self.present._replace(
            screens=self.detectors.screens(), ports=self.detectors.ports(),
            remote=self.detectors.remote(),
        )
        self._update()

    def probe_audio(self) -> None:
        self.detectors.probe(self.hardware["audio"], self._probed)

    def _probed(self, result: dict | None, error: str) -> None:
        if self.released:
            return
        if result is None:
            self.present = self.present._replace(audio_error=error)
        else:
            self.present = self.present._replace(
                outputs=result["outputs"], default_output=result["default"], audio_error="",
            )
        before = {name: self.values[name] for name in AUDIO_CHOICES.values()}
        self._update()
        if {name: self.values[name] for name in AUDIO_CHOICES.values()} != before:
            self._start_sound()

    def _output_found(self, spec: str | None) -> bool:
        outputs = self.present.outputs
        if outputs is None:
            return False
        if spec is None:
            return self.present.default_output is not None
        return len(matching_outputs(spec, outputs)) == 1

    def automatic(self, name: str) -> object:
        """What a choice is while nobody has changed it: the lab's while it is there, and what
        stands in for it while it is not."""
        lab = getattr(self.lab, name)
        if name in SCREEN_CHOICES.values():
            return lab if lab is not None and lab < len(self.present.screens) else None
        if name in AUDIO_CHOICES.values():
            # Off the lab's platform its devices cannot exist; on it, a missing one is shown
            # missing, for someone to connect, rather than quietly replaced by the speakers.
            if self.present.outputs is None or self._output_found(lab):
                return lab
            return lab if on_lab_platform(self.hardware) else None
        if name == INPUT:
            return REMOTE if self.present.remote else KEYBOARD
        return lab

    def choose(self, name: str, index: int) -> None:
        """A choice made by hand."""
        self.values[name] = self.options[name][index]
        self.chosen.add(name)
        self._update()
        if name in AUDIO_CHOICES.values():
            self._start_sound()

    def _update(self) -> None:
        before = self.values[INPUT]
        for name in self._names():
            if name not in self.chosen:
                self.values[name] = self.automatic(name)
        for name in self._names():
            options = self._options(name)
            if self.values[name] not in [value for value, _ in options]:
                options.insert(0, (self.values[name], self.words["not_connected"].format(
                    value=self._describe(name, self.values[name]))))
            self.options[name] = [value for value, _ in options]
            shown = (tuple(options), self.values[name])
            if self._shown.get(name) != shown:
                self._shown[name] = shown
                combo = self.combos[name]
                combo.blockSignals(True)
                combo.clear()
                combo.addItems([text for _, text in options])
                combo.setCurrentIndex(self.options[name].index(self.values[name]))
                combo.blockSignals(False)
            state, line = self._state(name)
            self.status[name].setText(line)
            self.status[name].setStyleSheet(f"color: {STATE_COLOURS[state]};")
        if self.values[INPUT] != before:
            self._apply_input()

    def _options(self, name: str) -> list[tuple[object, str]]:
        """Every choice there is now, with how it is shown."""
        words = self.words
        if name in SCREEN_CHOICES.values():
            return [(index, self._describe(name, index))
                    for index in range(len(self.present.screens))] + [
                (None, words["screen_window"])]
        if name in AUDIO_CHOICES.values():
            lab = getattr(self.lab, name)
            outputs = self.present.outputs or []
            # The lab's device keeps the name hardware.yaml gives it, so choosing it is not
            # recorded as a change.
            lab_output = matching_outputs(lab, outputs) if lab is not None else []
            return [(None, self._describe(name, None))] + [
                (lab if [output] == lab_output else output, output) for output in outputs
            ]
        if name == PORT:
            return [(port, port) for port in self.present.ports]
        return [(method, words["inputs"][method]) for method in PARTICIPANT_INPUTS]

    def _describe(self, name: str, value: object) -> str:
        if name in SCREEN_CHOICES.values():
            if value is None:
                return self.words["screen_window"]
            if value < len(self.present.screens):
                width, height = self.present.screens[value]
                return self.words["screen_choice"].format(index=value, width=width,
                                                          height=height)
            return self.words["screen_numbered"].format(index=value)
        if name in AUDIO_CHOICES.values() and value is None:
            default = self.present.default_output or self.words["none"]
            return self.words["audio_default"].format(value=default)
        return str(value)

    def _state(self, name: str) -> tuple[str, str]:
        """How the line under a choice reads: as expected, standing in, or missing."""
        words, value = self.words, self.values[name]
        lab = getattr(self.lab, name)
        if name in SCREEN_CHOICES.values():
            if value is not None and value >= len(self.present.screens):
                return MISSING, words["screen_missing"]
            state = OK if value == lab else STAND_IN
            if value is None:
                role = PARTICIPANT if name == SCREEN_CHOICES[PARTICIPANT] else EXPERIMENTER
                return state, words[f"screen_unplaced_{role}"]
            return state, words["found"]
        if name in AUDIO_CHOICES.values():
            if self.present.audio_error:
                return MISSING, words["audio_list_failed"].format(
                    value=self.present.audio_error)
            if self.present.outputs is None:
                return OK, words["audio_listing"]
            if not self._output_found(value):
                return MISSING, words["audio_missing"]
            if value is None:
                return STAND_IN, words["audio_default_line"]
            return (OK if value == lab else STAND_IN), words["found"]
        if name == PORT:
            # Only the prototype sleeve uses it, and the session chooses its garment when it
            # starts, so a missing port stops nothing yet.
            if value not in self.present.ports:
                return STAND_IN, words["port_missing" if self.present.ports else "ports_none"]
            return (OK if value == lab else STAND_IN), words["found"]
        remote = self.present.remote
        if value == REMOTE:
            if remote is None:
                return STAND_IN, words["remote_unknown"]
            return (OK, words["remote_found"]) if remote else (MISSING, words["remote_missing"])
        prefix = words["remote_missing"] + " " if remote is False else ""
        return STAND_IN, prefix + words[f"input_{value}"]

    # -- the participant's responses -----------------------------------------------------

    def _apply_input(self) -> None:
        """Count the keys the chosen input uses, from where the session would read them."""
        if self.key_source is None:
            return
        if self.remote_keys is not None:
            QApplication.instance().removeEventFilter(self.remote_keys)
            self.remote_keys = None
        self.responder = Responder(self.session_hardware())
        self.presses = {action: 0 for action in Action}
        self._show_presses()
        self.last_key.setText("")
        if self.values[INPUT] != REMOTE or not self.key_source.distinguishes:
            self._count_key_events()

    def _count_key_events(self) -> None:
        """Count Qt's key events, as any_keyboard does: every keyboard is the remote."""
        self.remote_keys = RemoteKeys(self.responder, self.pressed, self)
        QApplication.instance().installEventFilter(self.remote_keys)

    def _remote_event(self, event: str, _severity: str, _detail: str) -> None:
        if event == RAW_INPUT_FAILED and self.remote_keys is None:
            # The source now takes every keyboard as the remote, and so does the count.
            self._count_key_events()
        elif event in (REMOTE_DISCONNECTED, REMOTE_RECONNECTED):
            self.detect()

    def remote_key(self, name: str, released: bool, repeat: bool, _time_ms: int) -> None:
        """One of the remote's raw key reports (raw_input). Counted as the filter counts."""
        if not released and not repeat and self.values[INPUT] == REMOTE:
            self.pressed(name, self.responder.action_for(name))

    def pressed(self, key: str, action: Action) -> None:
        self.presses[action] += 1
        self.last_key.setText(self.words["remote_last"].format(
            symbol=self.responder.symbol_for(action, pointing_at_stop=True), value=key,
        ))
        self._show_presses()

    def _show_presses(self) -> None:
        for action, shown in self.press_labels.items():
            symbol = self.responder.symbol_for(action, pointing_at_stop=True)
            shown.setText(f"{symbol} {self.presses[action]}")

    # -- the screens ---------------------------------------------------------------------

    def toggle_label(self) -> None:
        """The participant screen's label, full screen where the session will put its window,
        so a wrong choice shows as the label landing on the wrong display. A click on the label
        takes it down, in case it has landed on this one."""
        if self.label_window is not None:
            self._hide_label()
            return
        index = self.values[SCREEN_CHOICES[PARTICIPANT]]
        screens = QGuiApplication.screens()
        screen = screens[index] if index is not None and index < len(screens) else None
        shown = QLabel(self.words["label_text"])
        shown.setAlignment(Qt.AlignCenter)
        shown.setStyleSheet(stylesheet())
        shown.setFont(label(SIZE_HEADLINE).font())
        shown.mousePressEvent = lambda _event: self._hide_label()
        if screen is not None:
            shown.setScreen(screen)
            shown.setGeometry(screen.geometry())
        shown.showFullScreen()
        self.label_window = shown
        self.label_button.setText(self.words["hide_label"])

    def _hide_label(self) -> None:
        if self.label_window is not None:
            self.label_window.close()
            self.label_window.deleteLater()
            self.label_window = None
        self.label_button.setText(self.words["show_label"])

    # -- the sound -----------------------------------------------------------------------

    def _start_sound(self) -> None:
        """The test sounds, on the devices chosen now: in this process for the test double,
        which plays nothing, and in a child process for real sound (`ChildAudio`)."""
        self._stop_sound()
        audio_config = self.session_hardware()["audio"]
        if audio_config["backend"] == SOUNDDEVICE:
            self.audio = ChildAudio(audio_config, self._sound_failed, self)
        else:
            self.audio = Audio(audio_config, self.clock, lambda *_, **__: None)
        self._show_noise()

    def _stop_sound(self) -> None:
        if self.audio is None:
            return
        if self.audio.noise_running:
            self.audio.stop_noise("hardware page")
        if isinstance(self.audio, ChildAudio):
            self.audio.close()
        self.audio = None

    def _sound_failed(self, why: str) -> None:
        self.sound_status.setText(self.words["audio_failed"].format(value=why))
        self._show_noise()

    def toggle_noise(self) -> None:
        self.sound_status.clear()
        try:
            if self.audio.noise_running:
                self.audio.stop_noise("hardware page")
            else:
                self.audio.start_noise(self.level.value())
        except AUDIO_ERRORS as error:
            self.sound_status.setText(self.words["audio_failed"].format(value=error))
        self._show_noise()

    def _show_noise(self) -> None:
        running = self.audio is not None and self.audio.noise_running
        self.noise_button.setText(self.words["stop_noise" if running else "start_noise"])
        self.cue_button.setEnabled(running)
        self._show_level()

    def set_level(self, level_dbfs: int) -> None:
        if self.audio.noise_running:
            self.audio.set_noise_level(level_dbfs)
        self._show_level()

    def _show_level(self) -> None:
        self.level_label.setText(self.words["noise_level"].format(value=self.level.value()))

    def play_cue(self) -> None:
        self.audio.participant_cue()

    def play_alert(self) -> None:
        self.sound_status.clear()
        try:
            self.audio.experimenter_alert("hardware page")
        except AUDIO_ERRORS as error:
            self.sound_status.setText(self.words["audio_failed"].format(value=error))

    # -- the garment ---------------------------------------------------------------------

    @property
    def garment_name(self) -> str:
        return self.garment_names[self.garment_choice.currentData()]

    def toggle_garment(self) -> None:
        if self.garment is not None and self.garment.connected:
            self.release_garment()
            self._show_garment()
            return
        driver = self.garment_choice.currentData()
        hardware = self.session_hardware()
        self.garment = DRIVERS[driver](Limits.from_config(hardware), self.clock,
                                       hardware=hardware)
        self.garment_status.setText(self.words["connecting"].format(garment=self.garment_name))
        # Painted before the wait: opening the prototype's port resets its board.
        self.garment_status.repaint()
        try:
            self.garment.connect()
        except GARMENT_ERRORS as error:
            self.garment = None
            self._show_garment(self.words["garment_failed"].format(value=error))
            return
        self._show_garment()

    def set_channel(self, channel: int, on: bool) -> None:
        if self.garment is None or not self.garment.connected:
            return
        try:
            # Off is the valve alone; the pressure is only set for switching on.
            if on and self.garment.per_channel_pressure:
                self.garment.set_pressure(
                    channel, self.hardware["audio"]["masking_check_pressure_kpa"]
                )
            self.garment.set_channel(channel, on)
        except GARMENT_ERRORS as error:
            self._show_garment(self.words["garment_failed"].format(value=error))
            return
        self._show_garment()

    def release_garment(self) -> None:
        """All channels off and the port let go; a link found lost has let it go already."""
        if self.garment is None:
            return
        try:
            self.garment.stop()
            self.garment.disconnect()
        except GARMENT_ERRORS as error:
            self.garment_status.setText(self.words["garment_failed"].format(value=error))
        self.garment = None

    def _show_garment(self, problem: str | None = None) -> None:
        connected = self.garment is not None and self.garment.connected
        channels = self.garment.channels() if connected else ()
        channels_on = self.garment.status()["channels_on"] if connected else ()
        for channel, made in self.channel_buttons.items():
            on = channel in channels_on
            made.blockSignals(True)
            made.setChecked(on)
            made.blockSignals(False)
            state = "channel_on" if on else "channel_off"
            made.setText(self.words[state].format(value=channel))
            made.setEnabled(channel in channels)
        self.garment_choice.setEnabled(not connected)
        self.combos[PORT].setEnabled(not connected)
        self.connect_button.setText(self.words["disconnect" if connected else "connect"])
        if problem is not None:
            self.garment_status.setText(problem)
        elif connected:
            self.garment_status.setText(
                self.words["garment_connected"].format(garment=self.garment_name)
            )
        else:
            self.garment_status.setText(
                self.words["garment_disconnected"].format(garment=self.garment_name)
            )

    # -- closing -------------------------------------------------------------------------

    def release(self, *_result) -> None:
        """Everything let go, by Continue, Cancel, Esc from the keyboard or the window's X."""
        if self.released:
            return
        self.released = True
        self.poll.stop()
        self.audio_poll.stop()
        app = QGuiApplication.instance()
        app.screenAdded.disconnect(self.detect)
        app.screenRemoved.disconnect(self.detect)
        if isinstance(self.detectors.probe, ChildProbe):
            self.detectors.probe.stop()
        if self.remote_keys is not None:
            QApplication.instance().removeEventFilter(self.remote_keys)
            self.remote_keys = None
        self.key_source.close()
        self._hide_label()
        self._stop_sound()
        self.release_garment()
