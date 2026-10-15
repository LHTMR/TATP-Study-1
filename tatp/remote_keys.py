"""Which keyboard a key came from: the participant's remote, or anything else. LOG N7.D22.

The R400 is a USB keyboard as far as the operating system is concerned, and Qt reports a key,
never the device that sent it. So the remote's emergency stop -- a full stop -- was the same key
as the experimenter typing a decimal point, and the session had to guess from which window had
focus (open item L15). Windows itself knows the device: its **Raw Input** API reports every
keystroke from every keyboard to a window registered for it, with the handle of the device that
sent it, even when another window has focus. The handle's device path carries the USB vendor and
product IDs, which `responder.device_match` in `hardware.yaml` names.

`responder.key_source` chooses, explicitly, as `audio.backend` does:

- `raw_input` -- the lab. A key counts as the remote's only if Raw Input says it came from the
  device `device_match` names. Windows only.
- `any_keyboard` -- every keyboard is the remote, as before this module: development machines,
  the headless tests and the validator, none of which has the remote or a native window.

**Matching a Qt key event to its raw report** is done where Windows still has both, in the
native message stream. Each keystroke reaches this application twice: first as a raw report
(`WM_INPUT`), then as the ordinary key message (`WM_KEYDOWN`, `WM_KEYUP`) that Qt turns into a
key event. The two are paired by scan code and direction -- not by virtual key, which differs
between them for numpad keys -- and the verdict is filed under what Qt copies into the event:
the message's time, its virtual key and its direction. A Qt key event then takes its verdict
from there. A key event with no verdict -- which should not happen -- is taken as the remote's:
a spurious stop is recoverable, and a lost one is not.
"""

from __future__ import annotations

import ctypes
import functools
import sys
from collections import OrderedDict, deque
from collections.abc import Callable
from types import SimpleNamespace

import shiboken6
from PySide6.QtCore import QAbstractNativeEventFilter, QEvent
from PySide6.QtWidgets import QApplication, QWidget

RAW_INPUT = "raw_input"
ANY_KEYBOARD = "any_keyboard"
KEY_SOURCES = (RAW_INPUT, ANY_KEYBOARD)

# Windows constants (WinUser.h), not study parameters.
WM_INPUT = 0x00FF
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
KEY_MESSAGES = {WM_KEYDOWN: False, WM_SYSKEYDOWN: False, WM_KEYUP: True, WM_SYSKEYUP: True}
RID_INPUT = 0x10000003
RIM_TYPEKEYBOARD = 1
RIDI_DEVICENAME = 0x20000007
RIDEV_INPUTSINK = 0x00000100
RIDEV_REMOVE = 0x00000001
RI_KEY_BREAK = 0x0001
RI_KEY_E0 = 0x0002
RIM_INPUT = 0  # GET_RAWINPUT_CODE_WPARAM: the report came while this application had focus
RIM_CODE_MASK = 0xFF
RAW_INPUT_ERROR = 0xFFFFFFFF  # GetRawInputData's (UINT)-1
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_KEYBOARD = 0x06
# A key message's lParam: bits 16-23 the scan code, bit 24 the extended-key flag.
LPARAM_SCAN_SHIFT = 16
SCAN_CODE_MASK = 0xFF
LPARAM_EXTENDED_BIT = 24
# How many raw reports may wait for their key message, and verdicts for their Qt event. Each is
# taken within a turn or two of the event loop; the bounds only stop strays piling up.
PENDING_REPORTS = 64
FILED_VERDICTS = 256


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
    win = _win()
    length = win.wintypes.UINT(0)
    win.user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(length))
    name = ctypes.create_unicode_buffer(length.value)
    win.user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, name, ctypes.byref(length))
    return name.value


def device_paths() -> list[str]:
    """Every keyboard Raw Input reports, by device path. Windows only."""
    win = _win()
    size = ctypes.sizeof(win.RawInputDeviceList)
    count = win.wintypes.UINT(0)
    if win.user32.GetRawInputDeviceList(None, ctypes.byref(count), size) == RAW_INPUT_ERROR:
        raise RemoteKeyError(f"GetRawInputDeviceList failed, error {ctypes.get_last_error()}")
    devices = (win.RawInputDeviceList * count.value)()
    listed = win.user32.GetRawInputDeviceList(devices, ctypes.byref(count), size)
    if listed == RAW_INPUT_ERROR:
        raise RemoteKeyError(f"GetRawInputDeviceList failed, error {ctypes.get_last_error()}")
    return [_device_path(device.hDevice) for device in devices[:listed]
            if device.dwType == RIM_TYPEKEYBOARD]


def remote_present(responder: dict) -> bool:
    """Whether the remote `device_match` names is plugged in. Only asked for `raw_input`."""
    match = responder["device_match"].upper()
    return any(match in path.upper() for path in device_paths())


class Pairing:
    """Raw reports paired with the key messages Qt turns into key events. No Windows calls.

    `report` takes a raw report as it arrives; `message` pairs the key message that follows it
    and files the verdict under what Qt copies into the event; `verdict` hands it to the event.
    """

    def __init__(self):
        self._reports: deque[tuple[int, bool, bool, bool]] = deque(maxlen=PENDING_REPORTS)
        self._filed: OrderedDict[tuple, deque[bool]] = OrderedDict()
        self._answered: tuple[int, tuple, bool] | None = None
        self.misses = 0  # key events that found no verdict

    def report(self, scan_code: int, extended: bool, released: bool, remote: bool) -> None:
        self._reports.append((scan_code, extended, released, remote))

    def message(self, time_ms: int, vkey: int, scan_code: int, extended: bool,
                released: bool) -> None:
        """A key message arrived: pair it with its report and file the verdict.

        Reports ahead of the match belong to keystrokes whose key message never came (a key
        some other window swallowed), and are dropped. With no match the queue is left alone,
        so a stray message cannot cost the keystrokes still on their way their own reports.
        """
        remote = None
        for index, (code, ext, up, verdict) in enumerate(self._reports):
            if (code, ext, up) == (scan_code, extended, released):
                remote = verdict
                for _ in range(index + 1):
                    self._reports.popleft()
                break
        if remote is None:
            return
        key = (time_ms, vkey, released)
        self._filed.setdefault(key, deque()).append(remote)
        self._filed.move_to_end(key)
        while len(self._filed) > FILED_VERDICTS:
            self._filed.popitem(last=False)

    def verdict(self, event_id: int, time_ms: int, vkey: int, released: bool) -> bool:
        """Whether the Qt key event these describe came from the remote.

        Asked again for the same event as it propagates to each parent, so the last answer is
        kept for that event (`event_id`, its C++ address) rather than taking a second verdict.
        """
        key = (time_ms, vkey, released)
        if self._answered is not None and self._answered[:2] == (event_id, key):
            return self._answered[2]
        filed = self._filed.get(key)
        if filed:
            answer = filed.popleft()
            if not filed:
                del self._filed[key]
        else:
            answer = True  # no verdict: the remote's, as the module says
            self.misses += 1
        self._answered = (event_id, key, answer)
        return answer


class AnyKeyboard:
    """Every keyboard is the remote. `distinguishes` is False, so the router keeps its rule
    that a key typed into an experimenter text field is the experimenter's (LOG N7.I1)."""

    distinguishes = False

    def from_remote(self, event) -> bool:
        return True

    def close(self) -> None:
        pass


# The source Windows is currently sending raw reports for. Windows keeps one keyboard
# registration per process, so a source closing must not remove a newer one's.
_registered: RawInputKeyboards | None = None


class RawInputKeyboards(QAbstractNativeEventFilter):
    """Tells the remote's keys from every other keyboard's, by Raw Input. Windows only.

    Registered to `window`, whose native window receives every keystroke's raw report whichever
    window has focus (`RIDEV_INPUTSINK`). Unregistered by `close()`, or when that window is
    destroyed. A newer source replaces this one's registration, and closing this one then
    leaves the newer one alone.
    """

    distinguishes = True

    def __init__(self, device_match: str, window: QWidget, on_unmatched: Callable[[], None]):
        super().__init__()
        global _registered
        self._win = _win()
        self._on_unmatched = on_unmatched
        if QApplication.platformName() != "windows":
            raise RemoteKeyError(
                f"responder.key_source raw_input needs a real display, not the "
                f"{QApplication.platformName()!r} platform"
            )
        self._match = device_match.upper()
        self._paths: dict[int, bool] = {}
        self._pairing = Pairing()
        self._register(int(window.winId()), RIDEV_INPUTSINK)
        _registered = self
        self._open = True
        QApplication.instance().installNativeEventFilter(self)
        window.destroyed.connect(self.close)

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
        global _registered
        if not self._open:
            return
        self._open = False
        app = QApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(self)
        if _registered is self:
            _registered = None
            self._register(0, RIDEV_REMOVE)

    # -- the native message stream -------------------------------------------------------

    def nativeEventFilter(self, event_type, message):  # noqa: N802 -- Qt's name
        if bytes(event_type) != b"windows_generic_MSG":
            return False, 0
        msg = self._win.wintypes.MSG.from_address(int(message))
        # A report made while another application has focus becomes no key event here.
        if msg.message == WM_INPUT and (msg.wParam & RIM_CODE_MASK) == RIM_INPUT:
            self._read(msg.lParam)
        elif msg.message in KEY_MESSAGES:
            self._pairing.message(
                msg.time, msg.wParam,
                (msg.lParam >> LPARAM_SCAN_SHIFT) & SCAN_CODE_MASK,
                bool((msg.lParam >> LPARAM_EXTENDED_BIT) & 1),
                KEY_MESSAGES[msg.message],
            )
        # Never consumed: Windows still turns the report into the key message, and Qt that
        # into the key event.
        return False, 0

    def _read(self, handle) -> None:
        win = self._win
        report = win.Report()
        size = win.wintypes.UINT(ctypes.sizeof(report))
        read = win.user32.GetRawInputData(
            handle, RID_INPUT, ctypes.byref(report), ctypes.byref(size),
            ctypes.sizeof(win.Header),
        )
        if read in (0, RAW_INPUT_ERROR) or report.header.dwType != RIM_TYPEKEYBOARD:
            return
        device = report.header.hDevice or 0
        if device not in self._paths:
            self._paths[device] = self._match in _device_path(report.header.hDevice).upper()
        flags = report.keyboard.Flags
        self._pairing.report(
            report.keyboard.MakeCode, bool(flags & RI_KEY_E0), bool(flags & RI_KEY_BREAK),
            self._paths[device],
        )

    # -- asked by the router -------------------------------------------------------------

    def from_remote(self, event) -> bool:
        """Whether this Qt key event came from the remote.

        The first event with no verdict is reported, once: if Raw Input stopped working, every
        keyboard would quietly be the remote, and that must show in the session's log.
        """
        missed = self._pairing.misses
        answer = self._pairing.verdict(
            shiboken6.getCppPointer(event)[0], event.timestamp(), event.nativeVirtualKey(),
            event.type() == QEvent.KeyRelease,
        )
        if missed == 0 and self._pairing.misses == 1:
            self._on_unmatched()
        return answer


def key_source(responder: dict, window: QWidget, on_unmatched: Callable[[], None]):
    """The configured key source, registered to `window`. `on_unmatched` is called the first
    time a key event cannot be told apart (raw_input only)."""
    source = responder["key_source"]
    assert source in KEY_SOURCES, f"responder.key_source is {source!r}; one of {KEY_SOURCES}"
    if source == ANY_KEYBOARD:
        return AnyKeyboard()
    return RawInputKeyboards(responder["device_match"], window, on_unmatched)
