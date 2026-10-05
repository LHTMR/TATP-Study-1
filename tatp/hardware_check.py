"""The hardware check: launcher entry 5, run before the participant arrives (docs/LOG.md N7.B4).

S's first lab run (30 Sep 2026) found two faults only a participant would otherwise have met:
the remote's keys mapped the wrong way round, and no sound in the headphones. This puts every
device the session uses in front of the experimenter, through the session's own code:

- **The remote.** Each button counts its presses, through the session's own `Responder`, so a
  wrong mapping shows as the wrong button counting. The dialog takes every remote key while it
  is open: ▶'s second key is `escape`, which would otherwise close it every other press.
- **The screens.** Where each configured index lands, and a label put up on the participant's.
- **The sound.** Each configured device resolved by name, or why not, with every output device
  listed, so a renamed or unplugged one is found here rather than at the masking check. The
  noise runs through the session's own `Audio`, bounded by the participant's own range, so the
  check adds no sound level and the ceiling still holds (SPEC.md 10.7).
- **The garment.** Each channel on and off, through the session's own driver. A valve garment
  is set to the masking check's pressure, the setup's existing low one, so the check adds no
  pressure either.

Nothing is recorded: no participant is involved. The dialog is modal to the launcher, so no
session can start while it holds the garment's port or the headphones, and closing it lets
both go.
"""

from __future__ import annotations

from collections.abc import Callable

import serial
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from tatp.audio import Audio, AudioError
from tatp.clock import Clock
from tatp.garment.base import GarmentController, GarmentError, Limits
from tatp.responder import Action, Responder
from tatp.session import DRIVERS
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
    button,
    fit_to_screen,
    label,
    sized,
    stylesheet,
)

HARDWARE_CHECK_WIDTH_PX = 1100
HARDWARE_CHECK_HEIGHT_PX = 760
DEVICE_LIST_LINES = 6
SLIDER_MIN_WIDTH_PX = 240
# A failure to open a port or a sound device is what this dialog exists to show, so these are
# reported on screen rather than raised. Anything else still raises (CLAUDE.md, fail fast).
GARMENT_ERRORS = (GarmentError, serial.SerialException)
AUDIO_ERRORS = (AudioError, ValueError, OSError)

PARTICIPANT = "participant"
EXPERIMENTER = "experimenter"


def query_sounddevice():
    """PortAudio, loaded only when the check asks: the tests and the screenshot run never do."""
    import sounddevice

    return sounddevice


def device_lines(audio_config: dict, words: dict, sd) -> tuple[list[str], str]:
    """Each configured output device resolved by name, or why not; and every output device.

    Resolved exactly as `SounddeviceOutput` will resolve it, by sounddevice's own matching, so
    a name that works here works in the session.
    """
    hostapis = [api["name"] for api in sd.query_hostapis()]
    lines = []
    for role in (PARTICIPANT, EXPERIMENTER):
        name = audio_config[f"{role}_device"]
        role_words = words[f"role_{role}_audio"]
        try:
            found = sd.query_devices(name, "output")
        except ValueError as error:
            lines.append(words["device_missing"].format(role=role_words, value=error))
            continue
        lines.append(words["device_found"].format(
            role=role_words, value=f"{found['name']}, {hostapis[found['hostapi']]}",
        ))
    available = [
        f"{device['name']}, {hostapis[device['hostapi']]}"
        for device in sd.query_devices()
        if device["max_output_channels"] > 0
    ]
    return lines, "\n".join(available)


class RemoteKeys(QObject):
    """Takes the remote's keys from every window while the check is open, and counts them."""

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
    """The four checks. `garment` and `audio` are what is in use, for the tests to drive."""

    def __init__(self, text: dict, hardware: dict, sound=query_sounddevice,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.text = text
        self.hardware = hardware
        self.words = words = text["hardware_check"]
        self.garment_names = text["terms"]["garments"]
        self.setWindowTitle(words["title"])
        self.setStyleSheet(stylesheet())
        self.clock = Clock()

        self.responder = Responder(hardware)
        self.presses: dict[Action, int] = {action: 0 for action in Action}
        self.remote_keys = RemoteKeys(self.responder, self.pressed, self)
        QApplication.instance().installEventFilter(self.remote_keys)

        audio_config = hardware["audio"]
        self.audio = Audio(audio_config, self.clock, lambda *_, **__: None)
        self._sound = sound
        self.garment: GarmentController | None = None
        self.label_window: QLabel | None = None

        title = label(SIZE_LARGE)
        title.setText(words["title"])
        # Two columns, so the whole check fits the lab laptop without scrolling; the sound's
        # device list is the tallest part and has a column to itself.
        columns = QHBoxLayout()
        columns.setSpacing(GROUP_GAP_PX * 2)
        for sections in ((self._remote(), self._screens(), self._garment()),
                         (self._sound_section(),)):
            column = QVBoxLayout()
            column.setSpacing(GROUP_GAP_PX)
            for section in sections:
                column.addLayout(section)
            column.addStretch(1)
            columns.addLayout(column, 1)
        self.close_button = button(text["launcher"]["close"], SIZE_BODY)
        self.close_button.clicked.connect(self.reject)
        closing = QHBoxLayout()
        closing.addStretch(1)
        closing.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_PX, MARGIN_PX, MARGIN_PX, MARGIN_PX)
        layout.addWidget(title)
        layout.addSpacing(ITEM_GAP_PX)
        layout.addLayout(columns, 1)
        layout.addLayout(closing)
        self.finished.connect(self.release)
        fit_to_screen(self, HARDWARE_CHECK_WIDTH_PX, HARDWARE_CHECK_HEIGHT_PX)

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

    def _remote(self) -> QVBoxLayout:
        section = self._heading("remote", "remote_hint")
        self.press_labels: dict[Action, QLabel] = {}
        for action in Action:
            self.press_labels[action] = label(SIZE_LARGE)
        self.last_key = label(SIZE_SMALL, colour=SECONDARY)
        self.last_key.setText(self.words["remote_none"])
        section.addLayout(self._row(*self.press_labels.values(), self.last_key))
        self._show_presses()
        return section

    def _screens(self) -> QVBoxLayout:
        section = self._heading("screens")
        screens = self.hardware["screens"]
        self.screen_lines = label(SIZE_SMALL, wrap=True)
        self.screen_lines.setText("\n".join(
            self._screen_line(role, screens[f"{role}_screen_index"])
            for role in (PARTICIPANT, EXPERIMENTER)
        ))
        section.addWidget(self.screen_lines)
        self.label_button = button(self.words["show_label"])
        self.label_button.clicked.connect(self.toggle_label)
        section.addLayout(self._row(self.label_button))
        return section

    def _screen_line(self, role: str, index: int | None) -> str:
        role_words = self.words[f"role_{role}"]
        if index is None:
            return self.words["screen_unset"].format(role=role_words)
        screens = QGuiApplication.screens()
        if index >= len(screens):
            return self.words["screen_missing"].format(
                role=role_words, index=index, count=len(screens),
            )
        size = screens[index].size()
        return self.words["screen_found"].format(
            role=role_words, index=index, width=size.width(), height=size.height(),
        )

    def _sound_section(self) -> QVBoxLayout:
        section = self._heading("sound", "sound_hint")
        self.device_lines = label(SIZE_SMALL, wrap=True)
        self.device_list = QPlainTextEdit()
        self.device_list.setReadOnly(True)
        self.device_list.setFixedHeight(
            self.device_list.fontMetrics().lineSpacing() * (DEVICE_LIST_LINES + 1)
        )
        self.audio_errors = AUDIO_ERRORS
        if self.audio.backend_name == "sounddevice":
            sd = self._sound()
            self.audio_errors = (*AUDIO_ERRORS, sd.PortAudioError)
            lines, available = device_lines(self.hardware["audio"], self.words, sd)
            self.device_lines.setText("\n".join(lines))
            self.device_list.setPlainText(
                self.words["devices_available"].format(value="\n" + available)
            )
        else:
            self.device_lines.setText(self.words["backend_recording"])
            self.device_list.hide()
        section.addWidget(self.device_lines)
        section.addWidget(self.device_list)

        self.noise_button = button(self.words["start_noise"])
        self.noise_button.clicked.connect(self.toggle_noise)
        self.level = QSlider(Qt.Horizontal)
        self.level.setRange(round(self.audio.start_dbfs), round(self.audio.max_dbfs))
        self.level.setSingleStep(round(self.hardware["audio"]["white_noise_step_db"]))
        self.level.setValue(round(self.audio.start_dbfs))
        self.level.valueChanged.connect(self.set_level)
        self.level_label = label(SIZE_SMALL)
        self.cue_button = button(self.words["play_cue"])
        self.cue_button.clicked.connect(self.play_cue)
        self.cue_button.setEnabled(False)
        self.alert_button = button(self.words["play_alert"])
        self.alert_button.clicked.connect(self.play_alert)
        self.level.setMinimumWidth(SLIDER_MIN_WIDTH_PX)
        self.sound_status = label(SIZE_SMALL, wrap=True, colour=DISCONNECTED_COLOUR)
        section.addLayout(self._row(self.noise_button, self.level, self.level_label))
        section.addLayout(self._row(self.cue_button, self.alert_button))
        section.addWidget(self.sound_status)
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
        self.channel_buttons: dict[int, QPushButton] = {}
        channels = QHBoxLayout()
        channels.setSpacing(ITEM_GAP_PX)
        n_channels = max(driver.n_channels for driver in DRIVERS.values())
        for channel in range(1, n_channels + 1):
            made = button(self.words["channel"].format(value=channel))
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

    # -- the remote ----------------------------------------------------------------------

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
        so a wrong index shows as the label landing on the wrong display. A click on the label
        takes it down, in case it has landed on this one."""
        if self.label_window is not None:
            self._hide_label()
            return
        index = self.hardware["screens"]["participant_screen_index"]
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

    def toggle_noise(self) -> None:
        self.sound_status.clear()
        try:
            if self.audio.noise_running:
                self.audio.stop_noise("hardware check")
            else:
                self.audio.start_noise(self.level.value())
        except self.audio_errors as error:
            self.sound_status.setText(self.words["audio_failed"].format(value=error))
        self.noise_button.setText(
            self.words["stop_noise" if self.audio.noise_running else "start_noise"]
        )
        self.cue_button.setEnabled(self.audio.noise_running)
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
            self.audio.experimenter_alert("hardware check")
        except self.audio_errors as error:
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
        self.garment = DRIVERS[driver](Limits.from_config(self.hardware), self.clock,
                                       hardware=self.hardware)
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
            if self.garment.per_channel_pressure:
                pressure = self.hardware["audio"]["masking_check_pressure_kpa"] if on else 0.0
                self.garment.set_pressure(channel, pressure)
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
        for channel, made in self.channel_buttons.items():
            made.blockSignals(True)
            made.setChecked(connected and channel in self.garment.status()["channels_on"])
            made.blockSignals(False)
            made.setEnabled(channel in channels)
        self.garment_choice.setEnabled(not connected)
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
        """Everything let go, by Close, Esc from the keyboard or the window's own X."""
        QApplication.instance().removeEventFilter(self.remote_keys)
        self._hide_label()
        if self.audio.noise_running:
            self.audio.stop_noise("hardware check closed")
        self.release_garment()
