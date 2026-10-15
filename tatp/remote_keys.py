"""Which keyboard a key came from: the participant's remote, or anything else. LOG N7.D22.

The R400 is a USB keyboard as far as the operating system is concerned, and Qt reports a key,
never the device that sent it. So the remote's emergency stop -- a full stop -- was the same key
as the experimenter typing a decimal point, and the session had to guess from which window had
focus (open item L15). Windows itself knows the device: its **Raw Input** API reports every
keystroke from every keyboard to a window registered for it, with the handle of the device that
sent it, even when another window or another application has focus. The handle's device path
carries the USB vendor and product IDs, which `responder.device_match` in `hardware.yaml` names.

`responder.key_source` chooses, explicitly, as `audio.backend` does:

- `raw_input` -- the lab. Windows only. Described below.
- `any_keyboard` -- every keyboard is the remote, as before this module: development machines,
  the headless tests and the validator, none of which has the remote or a native window.

**Under `raw_input` the remote's buttons are read from its raw reports alone** (`on_key`), and
never from Qt's key events. Windows keeps one keyboard state for every keyboard, so a Qt key
event for the remote's key is shaped by the other keyboards: with Shift held on the laptop the
remote's full stop arrives as a colon, and with the laptop's full stop held down it arrives as
an auto-repeat. A raw report carries the remote's own key, and whether the press is a repeat is
decided from the remote's own reports. The safety path -- the emergency stop -- depends on
nothing else, whichever window or application has focus.

**The remote's ordinary key messages are dropped** while this application has focus, so its keys
are not typed into whatever has focus as well: each key message is paired with the raw report it
came from (by scan code and direction) and consumed when that report was the remote's. A message
that cannot be paired is let through as typing. Either way the stop has already been delivered
from the raw report. While another program has focus the remote's keys reach it too: Windows can
withhold key messages only from every keyboard at once (`RIDEV_NOLEGACY`), not from one.
"""

from __future__ import annotations

import ctypes
import functools
import sys
from collections import deque
from collections.abc import Callable
from types import SimpleNamespace

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication, QWidget

RAW_INPUT = "raw_input"
ANY_KEYBOARD = "any_keyboard"
KEY_SOURCES = (RAW_INPUT, ANY_KEYBOARD)

# The Windows virtual key of each key name the responder's keys use (WinUser.h). The raw report
# names the key the remote sent by these, independent of Shift or any other keyboard's state.
VIRTUAL_KEYS = {
    "pageup": 0x21, "pagedown": 0x22, "f5": 0x74, "escape": 0x1B, "period": 0xBE,
}

# Windows constants (WinUser.h, winerror.h), not study parameters.
WM_INPUT_DEVICE_CHANGE = 0x00FE
WM_INPUT = 0x00FF
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
KEY_MESSAGES = {WM_KEYDOWN: False, WM_SYSKEYDOWN: False, WM_KEYUP: True, WM_SYSKEYUP: True}
WANTED_MESSAGES = frozenset({WM_INPUT_DEVICE_CHANGE, WM_INPUT, *KEY_MESSAGES})
GIDC_ARRIVAL = 1
GIDC_REMOVAL = 2
RID_INPUT = 0x10000003
RIM_TYPEKEYBOARD = 1
RIDI_DEVICENAME = 0x20000007
RIDEV_INPUTSINK = 0x00000100
RIDEV_DEVNOTIFY = 0x00002000
RIDEV_REMOVE = 0x00000001
RI_KEY_BREAK = 0x0001
RI_KEY_E0 = 0x0002
RIM_INPUT = 0  # GET_RAWINPUT_CODE_WPARAM: the report came while this application had focus
RIM_CODE_MASK = 0xFF
RAW_INPUT_ERROR = 0xFFFFFFFF  # the (UINT)-1 the Raw Input calls return on failure
ERROR_INSUFFICIENT_BUFFER = 122
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_KEYBOARD = 0x06
# A key message's lParam: bits 16-23 the scan code, bit 24 the extended-key flag.
LPARAM_SCAN_SHIFT = 16
SCAN_CODE_MASK = 0xFF
LPARAM_EXTENDED_BIT = 24
# The native message's id sits after its window handle (the MSG structure).
MSG_ID_OFFSET = ctypes.sizeof(ctypes.c_void_p)
# How many raw reports may wait for their key message. Each is taken within a turn of the event
# loop; the bound only stops strays piling up.
PENDING_REPORTS = 64
# The keyboard list can change between asking its length and reading it; Windows then asks for
# the call to be repeated.
DEVICE_LIST_ATTEMPTS = 5
# Key messages in a row with no raw report before Raw Input is taken to have stopped. More than
# one, so a single key a driver synthesises without a report of its own does not trip it.
UNPAIRED_LIMIT = 3

# `log` event names (docs/DATA_SCHEMA.md), reported through a source's `on_event`.
REMOTE_DISCONNECTED = "remote_disconnected"
REMOTE_RECONNECTED = "remote_reconnected"
REMOTE_KEY_UNKNOWN = "remote_key_unknown"
RAW_INPUT_FAILED = "raw_input_failed"


class RemoteKeyError(RuntimeError):
    """`raw_input` was chosen but cannot work here."""


def raw_input_available() -> bool:
    return sys.platform == "win32"


def with_key_source(hardware: dict, source: str) -> dict:
    """`hardware` with `responder.key_source` set: how headless tools ask for any_keyboard."""
    return {**hardware, "responder": {**hardware["responder"], "key_source": source}}


@functools.cache
def _win() -> SimpleNamespace:
    """user32 with its signatures declared, and the structures it fills. Windows only."""
    if not raw_input_available():
        raise RemoteKeyError("responder.key_source raw_input needs Windows")
    from ctypes import wintypes

    class RawInputDeviceList(ctypes.Structure):
        _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]

    class RawInputDevice(ctypes.Structure):
        _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                    ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]

    class Header(ctypes.Structure):
        _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                    ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]

    class Keyboard(ctypes.Structure):
        _fields_ = [("MakeCode", wintypes.USHORT), ("Flags", wintypes.USHORT),
                    ("Reserved", wintypes.USHORT), ("VKey", wintypes.USHORT),
                    ("Message", wintypes.UINT), ("ExtraInformation", wintypes.ULONG)]

    class Report(ctypes.Structure):
        _fields_ = [("header", Header), ("keyboard", Keyboard)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    puint = ctypes.POINTER(wintypes.UINT)
    user32.GetRawInputDeviceList.argtypes = [ctypes.c_void_p, puint, wintypes.UINT]
    user32.GetRawInputDeviceList.restype = wintypes.UINT
    user32.GetRawInputDeviceInfoW.argtypes = [
        wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, puint,
    ]
    user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
    user32.GetRawInputData.argtypes = [
        wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, puint, wintypes.UINT,
    ]
    user32.GetRawInputData.restype = wintypes.UINT
    user32.RegisterRawInputDevices.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
    user32.RegisterRawInputDevices.restype = wintypes.BOOL
    return SimpleNamespace(
        user32=user32, wintypes=wintypes, RawInputDeviceList=RawInputDeviceList,
        RawInputDevice=RawInputDevice, Header=Header, Report=Report,
    )


def _device_path(handle) -> str:
    """The device path, or "" for a handle Windows no longer knows."""
    win = _win()
    length = win.wintypes.UINT(0)
    win.user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(length))
    name = ctypes.create_unicode_buffer(length.value)
    if win.user32.GetRawInputDeviceInfoW(
        handle, RIDI_DEVICENAME, name, ctypes.byref(length)
    ) == RAW_INPUT_ERROR:
        return ""
    return name.value


def _keyboards() -> list[tuple[int, str]]:
    """Every keyboard Raw Input reports, as (handle, device path). Windows only."""
    win = _win()
    size = ctypes.sizeof(win.RawInputDeviceList)
    for _ in range(DEVICE_LIST_ATTEMPTS):
        count = win.wintypes.UINT(0)
        if win.user32.GetRawInputDeviceList(None, ctypes.byref(count), size) == RAW_INPUT_ERROR:
            raise RemoteKeyError(
                f"GetRawInputDeviceList failed, error {ctypes.get_last_error()}"
            )
        devices = (win.RawInputDeviceList * count.value)()
        listed = win.user32.GetRawInputDeviceList(devices, ctypes.byref(count), size)
        if listed != RAW_INPUT_ERROR:
            return [(device.hDevice or 0, _device_path(device.hDevice))
                    for device in devices[:listed] if device.dwType == RIM_TYPEKEYBOARD]
        if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
            break
    raise RemoteKeyError(f"GetRawInputDeviceList failed, error {ctypes.get_last_error()}")


def remote_present(responder: dict) -> bool:
    """Whether the remote `device_match` names is plugged in. Only asked for `raw_input`."""
    match = responder["device_match"].upper()
    return any(match in path.upper() for _, path in _keyboards())


class RemoteButtons:
    """The remote's raw key reports as button presses: which key, and whether a repeat.

    A repeat is a press of a key the remote already holds down -- its own state, so another
    keyboard's held key cannot make the remote's press look like one. No Windows calls.
    """

    def __init__(self, key_names: list[str]):
        unknown = sorted(set(key_names) - set(VIRTUAL_KEYS))
        assert not unknown, f"responder keys with no Windows virtual key: {unknown}"
        self._names = {VIRTUAL_KEYS[name]: name for name in key_names}
        self._down: set[int] = set()

    def report(self, vkey: int, released: bool) -> tuple[str, bool, bool] | None:
        """(key name, released, repeat) for a key the remote has, else None."""
        name = self._names.get(vkey)
        if name is None:
            return None
        if released:
            self._down.discard(vkey)
            return name, True, False
        repeat = vkey in self._down
        self._down.add(vkey)
        return name, False, repeat

    def release_all(self) -> None:
        """Forget every held key: the remote went, and their releases will not come."""
        self._down.clear()


class Pairing:
    """Each key message paired with the raw report it came from. No Windows calls.

    Windows sends a keystroke's raw report before its key message. `report` queues the report
    with whether it was the remote's; `message` finds the key message's own report, by scan code
    and direction (not by virtual key, which differs between the two for numpad keys), and says
    whether to drop the message. Reports ahead of the match belong to keystrokes whose message
    never came (a key some other window took), and are dropped too. A message with no report
    of its own leaves the queue alone, is let through, and is told apart (`None`).
    """

    def __init__(self):
        self._reports: deque[tuple[int, bool, bool, bool]] = deque(maxlen=PENDING_REPORTS)

    def report(self, scan_code: int, extended: bool, released: bool, remote: bool) -> None:
        self._reports.append((scan_code, extended, released, remote))

    def message(self, scan_code: int, extended: bool, released: bool) -> bool | None:
        """Whether this key message is the remote's, and so to be dropped; None if it has no
        report."""
        for index, (code, ext, up, remote) in enumerate(self._reports):
            if (code, ext, up) == (scan_code, extended, released):
                for _ in range(index + 1):
                    self._reports.popleft()
                return remote
        return None


class AnyKeyboard:
    """Every keyboard is the remote, through Qt's key events (`distinguishes` False): the router
    forwards them, except a key typed into an experimenter text field (LOG N7.I1)."""

    distinguishes = False

    def close(self) -> None:
        pass


# The sources open now, newest last. Windows keeps one keyboard registration per process, so
# the newest has it, and closing it hands it back to the one before.
_open: list[RawInputKeyboards] = []


class RawInputKeyboards(QAbstractNativeEventFilter):
    """Reads the remote's buttons from Raw Input and keeps its keys out of Qt. Windows only.

    Registered to `window`, whose native window receives every keystroke's raw report whichever
    window or application has focus (`RIDEV_INPUTSINK`), and every keyboard's arrival and
    removal (`RIDEV_DEVNOTIFY`). Unregistered by `close()`, or when that window is destroyed.
    Only the newest open source acts: Windows sends the reports to its window alone.

    `on_key(name, released, repeat, time_ms)` is called for each of the remote's key reports.
    `on_event(event, severity, detail)` reports what the session's log must show: the remote
    unplugged and back (`REMOTE_DISCONNECTED`, `REMOTE_RECONNECTED`), a key the remote sent that
    no button is configured for (`REMOTE_KEY_UNKNOWN`), and Raw Input failing
    (`RAW_INPUT_FAILED`). On that last, `distinguishes` becomes False: every keyboard is then
    the remote, as under any_keyboard, rather than none -- a spurious stop is recoverable, and a
    lost one is not.
    """

    def __init__(self, responder: dict, window: QWidget,
                 on_key: Callable[[str, bool, bool, int], None],
                 on_event: Callable[[str, str, str], None]):
        super().__init__()
        self._win = _win()
        if QApplication.platformName() != "windows":
            raise RemoteKeyError(
                f"responder.key_source raw_input needs a real display, not the "
                f"{QApplication.platformName()!r} platform"
            )
        self.distinguishes = True
        self._match = responder["device_match"].upper()
        self._buttons = RemoteButtons(
            [name for names in responder["keys"].values() for name in names]
        )
        self._on_key = on_key
        self._on_event = on_event
        self._remotes = {handle for handle, path in _keyboards() if self._is_remote(path)}
        self._pairing = Pairing()
        self._unpaired = 0
        self._unknown: set[int] = set()
        # The last native message acted on: each reaches this filter twice (below).
        self._last_message: tuple | None = None
        self._hwnd = int(window.winId())
        self._register(self._hwnd, RIDEV_INPUTSINK | RIDEV_DEVNOTIFY)
        _open.append(self)
        QApplication.instance().installNativeEventFilter(self)
        window.destroyed.connect(self.close)

    @property
    def remote_present(self) -> bool:
        return bool(self._remotes)

    def _is_remote(self, path: str) -> bool:
        return self._match in path.upper()

    def _register(self, hwnd: int, flags: int) -> None:
        device = self._win.RawInputDevice(
            HID_USAGE_PAGE_GENERIC, HID_USAGE_GENERIC_KEYBOARD, flags, hwnd or None
        )
        if not self._win.user32.RegisterRawInputDevices(
            ctypes.byref(device), 1, ctypes.sizeof(device)
        ):
            raise RemoteKeyError(
                f"RegisterRawInputDevices failed, error {ctypes.get_last_error()}"
            )

    def close(self, *_args) -> None:
        if self not in _open:
            return
        newest = _open[-1] is self
        _open.remove(self)
        app = QApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(self)
        if not newest:
            return
        if _open:
            _open[-1]._register(_open[-1]._hwnd, RIDEV_INPUTSINK | RIDEV_DEVNOTIFY)
        else:
            self._register(0, RIDEV_REMOVE)

    # -- the native message stream -------------------------------------------------------

    def nativeEventFilter(self, event_type, message):  # noqa: N802 -- Qt's name
        # Called for every native message, so the cheap tests first.
        message_id = ctypes.c_uint.from_address(int(message) + MSG_ID_OFFSET).value
        if message_id not in WANTED_MESSAGES or not _open or _open[-1] is not self:
            return False, 0
        # Acted on once. Qt 6.11 passes keyboard and raw-input messages to this filter once,
        # from the window procedure, but other posted messages twice, and other Qt versions
        # also pass the dispatcher's copy. A key message dropped here leaves no character
        # behind: Qt's key mapper translates it into one only after the filter lets it pass
        # (checked with a probe on the lab laptop, 15 Oct 2026).
        msg = self._win.wintypes.MSG.from_address(int(message))
        identity = (msg.message, msg.wParam, msg.lParam, msg.time)
        if identity == self._last_message:
            return False, 0
        self._last_message = identity
        if msg.message == WM_INPUT:
            self._read(msg.lParam, msg.time, (msg.wParam & RIM_CODE_MASK) == RIM_INPUT)
            return False, 0
        if msg.message == WM_INPUT_DEVICE_CHANGE:
            self._device_changed(msg.wParam, msg.lParam or 0)
            return False, 0
        return self._key_message(msg), 0

    def _key_message(self, msg) -> bool:
        """Pair a key message with its report; True to drop it as the remote's."""
        remote = self._pairing.message(
            (msg.lParam >> LPARAM_SCAN_SHIFT) & SCAN_CODE_MASK,
            bool((msg.lParam >> LPARAM_EXTENDED_BIT) & 1),
            KEY_MESSAGES[msg.message],
        )
        if remote is not None:
            self._unpaired = 0
            return remote
        # Every keystroke this application receives brings its raw report first, so a run of
        # key messages without one means Raw Input has stopped -- and with it the remote.
        self._unpaired += 1
        if self.distinguishes and self._unpaired >= UNPAIRED_LIMIT:
            self.distinguishes = False
            self._on_event(RAW_INPUT_FAILED, "error",
                           f"{self._unpaired} keystrokes in a row without a raw report")
        return False

    def _device_changed(self, change: int, handle: int) -> None:
        # A removed device's path cannot be asked for any more, so the remote's handles are
        # remembered from when they arrived.
        was_present = self.remote_present
        if change == GIDC_ARRIVAL and self._is_remote(_device_path(handle)):
            self._remotes.add(handle)
        elif change == GIDC_REMOVAL:
            self._remotes.discard(handle)
        if self.remote_present == was_present:
            return
        if self.remote_present:
            self._on_event(REMOTE_RECONNECTED, "warning", "")
        else:
            # A button held as it went has no release to come; its next press is not a repeat.
            self._buttons.release_all()
            self._on_event(REMOTE_DISCONNECTED, "error", "")

    def _read(self, handle, time_ms: int, foreground: bool) -> None:
        win = self._win
        report = win.Report()
        size = win.wintypes.UINT(ctypes.sizeof(report))
        read = win.user32.GetRawInputData(
            handle, RID_INPUT, ctypes.byref(report), ctypes.byref(size),
            ctypes.sizeof(win.Header),
        )
        if read in (0, RAW_INPUT_ERROR) or report.header.dwType != RIM_TYPEKEYBOARD:
            return
        flags = report.keyboard.Flags
        released = bool(flags & RI_KEY_BREAK)
        vkey = report.keyboard.VKey
        remote = (report.header.hDevice or 0) in self._remotes
        button = self._buttons.report(vkey, released) if remote else None
        # Only a report made while this application has focus becomes a key message here. A
        # remote key no button is configured for is let through as a key, not silently lost.
        if foreground:
            self._pairing.report(
                report.keyboard.MakeCode, bool(flags & RI_KEY_E0), released,
                button is not None,
            )
        if remote and button is None and vkey not in self._unknown:
            self._unknown.add(vkey)
            self._on_event(REMOTE_KEY_UNKNOWN, "warning", f"virtual key 0x{vkey:02X}")
        if button is not None and self.distinguishes:
            self._on_key(*button, time_ms)


def key_source(responder: dict, window: QWidget,
               on_key: Callable[[str, bool, bool, int], None],
               on_event: Callable[[str, str, str], None]):
    """The configured key source, registered to `window` (callbacks: `RawInputKeyboards`)."""
    source = responder["key_source"]
    assert source in KEY_SOURCES, f"responder.key_source is {source!r}; one of {KEY_SOURCES}"
    if source == ANY_KEYBOARD:
        return AnyKeyboard()
    return RawInputKeyboards(responder, window, on_key, on_event)
