from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable

from mini_hermes.interaction.schema import InputEvent, new_id, now_ts


InputCallback = Callable[[InputEvent], None]

WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_KEYUP = 0x0002


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class WindowsInputRecorder:
    def __init__(
        self,
        episode_id: str,
        callback: InputCallback,
        record_key_text: bool = False,
        mouse_move_interval: float = 0.05,
    ) -> None:
        _require_windows()
        self.episode_id = episode_id
        self.callback = callback
        self.record_key_text = record_key_text
        self.mouse_move_interval = mouse_move_interval
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._mouse_hook = None
        self._keyboard_hook = None
        self._mouse_proc = HOOKPROC(self._mouse_callback)
        self._keyboard_proc = HOOKPROC(self._keyboard_callback)
        self._last_move_at = 0.0
        self._last_move_xy: tuple[int, int] | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_message_loop, name="mini-hermes-input-recorder", daemon=True)
        self._thread.start()
        deadline = time.time() + 2.0
        while self._thread_id == 0 and time.time() < deadline:
            time.sleep(0.01)

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = 0

    def _run_message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_proc, kernel32.GetModuleHandleW(None), 0)
        self._keyboard_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._keyboard_proc,
            kernel32.GetModuleHandleW(None),
            0,
        )
        if not self._mouse_hook or not self._keyboard_hook:
            self._unhook()
            return
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._unhook()

    def _unhook(self) -> None:
        user32 = ctypes.windll.user32
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
        if self._keyboard_hook:
            user32.UnhookWindowsHookEx(self._keyboard_hook)
            self._keyboard_hook = None

    def _mouse_callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            action, button = _mouse_action(int(w_param))
            if action:
                timestamp = now_ts()
                x, y = int(info.pt.x), int(info.pt.y)
                if action == "move" and not self._should_record_move(timestamp, x, y):
                    return ctypes.windll.user32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)
                wheel_delta = _wheel_delta(info.mouseData) if int(w_param) == WM_MOUSEWHEEL else 0
                self.callback(
                    InputEvent(
                        event_id=new_id("input"),
                        episode_id=self.episode_id,
                        timestamp=timestamp,
                        kind="mouse",
                        action=action,
                        x=x,
                        y=y,
                        button=button,
                        metadata={"wheel_delta": wheel_delta} if wheel_delta else {},
                    )
                )
        return ctypes.windll.user32.CallNextHookEx(self._mouse_hook, n_code, w_param, l_param)

    def _keyboard_callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0:
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            action = _keyboard_action(int(w_param))
            if action:
                vk_code = int(info.vkCode)
                self.callback(
                    InputEvent(
                        event_id=new_id("input"),
                        episode_id=self.episode_id,
                        timestamp=now_ts(),
                        kind="keyboard",
                        action=action,
                        key_code=vk_code,
                        key_name=vk_name(vk_code),
                        key_text=_key_text(vk_code) if self.record_key_text else "",
                        modifiers=current_modifiers(),
                        metadata={
                            "scan_code": int(info.scanCode),
                            "raw_key_text_recorded": self.record_key_text,
                        },
                    )
                )
        return ctypes.windll.user32.CallNextHookEx(self._keyboard_hook, n_code, w_param, l_param)

    def _should_record_move(self, timestamp: float, x: int, y: int) -> bool:
        if self._last_move_xy is None:
            self._last_move_at = timestamp
            self._last_move_xy = (x, y)
            return True
        last_x, last_y = self._last_move_xy
        if timestamp - self._last_move_at < self.mouse_move_interval and abs(x - last_x) < 5 and abs(y - last_y) < 5:
            return False
        self._last_move_at = timestamp
        self._last_move_xy = (x, y)
        return True


class WindowsInputReplayer:
    def replay(
        self,
        events: list[dict[str, object]],
        dry_run: bool = True,
        speed: float = 1.0,
        start_delay: float = 2.0,
    ) -> list[str]:
        if speed <= 0:
            raise ValueError("speed must be positive")
        summary: list[str] = []
        sorted_events = sorted(events, key=lambda item: float(item["timestamp"]))
        if dry_run:
            for event in sorted_events:
                summary.append(_event_summary(event))
            return summary

        _require_windows()
        time.sleep(max(0.0, start_delay))
        previous_ts: float | None = None
        for event in sorted_events:
            timestamp = float(event["timestamp"])
            if previous_ts is not None:
                time.sleep(max(0.0, (timestamp - previous_ts) / speed))
            previous_ts = timestamp
            self._send_event(event)
            summary.append(_event_summary(event))
        return summary

    def _send_event(self, event: dict[str, object]) -> None:
        kind = str(event.get("kind", ""))
        if kind == "mouse":
            _send_mouse_event(event)
        elif kind == "keyboard":
            _send_keyboard_event(event)


def current_modifiers() -> list[str]:
    _require_windows()
    user32 = ctypes.windll.user32
    modifiers = []
    for name, vk in (("shift", 0x10), ("ctrl", 0x11), ("alt", 0x12), ("win", 0x5B)):
        if user32.GetAsyncKeyState(vk) & 0x8000:
            modifiers.append(name)
    return modifiers


def vk_name(vk_code: int) -> str:
    names = {
        0x08: "BACKSPACE",
        0x09: "TAB",
        0x0D: "ENTER",
        0x10: "SHIFT",
        0x11: "CTRL",
        0x12: "ALT",
        0x1B: "ESC",
        0x20: "SPACE",
        0x25: "LEFT",
        0x26: "UP",
        0x27: "RIGHT",
        0x28: "DOWN",
        0x2E: "DELETE",
    }
    if 0x30 <= vk_code <= 0x39 or 0x41 <= vk_code <= 0x5A:
        return chr(vk_code)
    return names.get(vk_code, f"VK_{vk_code}")


def _send_mouse_event(event: dict[str, object]) -> None:
    action = str(event.get("action", ""))
    x = int(event.get("x") or 0)
    y = int(event.get("y") or 0)
    user32 = ctypes.windll.user32
    screen_w = max(1, user32.GetSystemMetrics(0) - 1)
    screen_h = max(1, user32.GetSystemMetrics(1) - 1)
    absolute_x = int(x * 65535 / screen_w)
    absolute_y = int(y * 65535 / screen_h)
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    mouse_data = 0
    if action == "left_down":
        flags |= MOUSEEVENTF_LEFTDOWN
    elif action == "left_up":
        flags |= MOUSEEVENTF_LEFTUP
    elif action == "right_down":
        flags |= MOUSEEVENTF_RIGHTDOWN
    elif action == "right_up":
        flags |= MOUSEEVENTF_RIGHTUP
    elif action == "middle_down":
        flags |= MOUSEEVENTF_MIDDLEDOWN
    elif action == "middle_up":
        flags |= MOUSEEVENTF_MIDDLEUP
    elif action == "wheel":
        flags |= MOUSEEVENTF_WHEEL
        metadata = _json_dict(event.get("metadata_json"))
        mouse_data = int(metadata.get("wheel_delta") or 0)
    _send_input(INPUT(type=INPUT_MOUSE, union=INPUT_UNION(mi=MOUSEINPUT(absolute_x, absolute_y, mouse_data, flags, 0, None))))


def _send_keyboard_event(event: dict[str, object]) -> None:
    action = str(event.get("action", ""))
    key_code = int(event.get("key_code") or 0)
    if not key_code:
        return
    flags = KEYEVENTF_KEYUP if action == "key_up" else 0
    _send_input(INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(key_code, 0, flags, 0, None))))


def _send_input(item: INPUT) -> None:
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))
    if sent != 1:
        raise RuntimeError("SendInput failed")


def _mouse_action(message: int) -> tuple[str, str]:
    mapping = {
        WM_MOUSEMOVE: ("move", ""),
        WM_LBUTTONDOWN: ("left_down", "left"),
        WM_LBUTTONUP: ("left_up", "left"),
        WM_RBUTTONDOWN: ("right_down", "right"),
        WM_RBUTTONUP: ("right_up", "right"),
        WM_MBUTTONDOWN: ("middle_down", "middle"),
        WM_MBUTTONUP: ("middle_up", "middle"),
        WM_MOUSEWHEEL: ("wheel", "wheel"),
    }
    return mapping.get(message, ("", ""))


def _keyboard_action(message: int) -> str:
    if message in {WM_KEYDOWN, WM_SYSKEYDOWN}:
        return "key_down"
    if message in {WM_KEYUP, WM_SYSKEYUP}:
        return "key_up"
    return ""


def _wheel_delta(mouse_data: int) -> int:
    high_word = (int(mouse_data) >> 16) & 0xFFFF
    return high_word - 0x10000 if high_word & 0x8000 else high_word


def _key_text(vk_code: int) -> str:
    if 0x30 <= vk_code <= 0x39 or 0x41 <= vk_code <= 0x5A:
        return chr(vk_code)
    if vk_code == 0x20:
        return " "
    return ""


def _event_summary(event: dict[str, object]) -> str:
    if str(event.get("kind")) == "mouse":
        return f"mouse {event.get('action')} x={event.get('x')} y={event.get('y')}"
    return f"keyboard {event.get('action')} key={event.get('key_name') or event.get('key_code')}"


def _json_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = __import__("json").loads(str(value))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows input recording/replay requires Windows 10/11.")
