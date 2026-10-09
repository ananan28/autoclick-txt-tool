# -*- coding: utf-8 -*-
"""Windows 全局快捷键 + 鼠标点击 + Unicode 文本输入（无第三方依赖）。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes as wt
import queue
import threading

if not hasattr(ctypes, "WinDLL"):
    raise RuntimeError("该程序仅支持 Windows 10 / Windows 11。")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", PTR)]


class INPUTDATA(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("data", INPUTDATA)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM),
                ("lParam", wt.LPARAM), ("time", wt.DWORD), ("pt", POINT),
                ("lPrivate", wt.DWORD)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wt.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL  # -1 仍为真；下面单独判断
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.PeekMessageW.restype = wt.BOOL
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
kernel32.GetCurrentThreadId.restype = wt.DWORD
kernel32.GetCurrentProcessId.restype = wt.DWORD

KEYBOARD_INPUT = 1
MOUSE_INPUT = 0
KEY_UP = 0x0002
KEY_UNICODE = 0x0004
MOUSE_FLAGS = {
    "左键": (0x0002, 0x0004),
    "右键": (0x0008, 0x0010),
    "中键": (0x0020, 0x0040),
}
_io_lock = threading.RLock()


def _send(events: list[INPUT]) -> None:
    if not events:
        return
    arr = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))
    if sent != len(arr):
        err = ctypes.get_last_error()
        raise OSError(err, f"Windows 输入注入失败（发送 {sent}/{len(arr)} 个事件）。可能是目标窗口以管理员权限运行。")


def _make_key(scan: int, flags: int, virtual: int = 0) -> INPUT:
    event = INPUT()
    event.type = KEYBOARD_INPUT
    event.data.ki = KEYBDINPUT(virtual, scan, flags, 0, 0)
    return event


def send_text(text: str) -> None:
    """Unicode 模拟键入，不使用剪贴板，不额外按 Enter。"""
    with _io_lock:
        # UTF-16LE 包括代理对，可以输入中文、英文、常见 emoji。
        data = text.encode("utf-16-le")
        chunk: list[INPUT] = []
        for index in range(0, len(data), 2):
            unit = int.from_bytes(data[index:index + 2], "little")
            chunk.append(_make_key(unit, KEY_UNICODE))
            chunk.append(_make_key(unit, KEY_UNICODE | KEY_UP))
            if len(chunk) >= 256:
                _send(chunk)
                chunk = []
        _send(chunk)


def click_mouse(button: str) -> None:
    down, up = MOUSE_FLAGS[button]
    with _io_lock:
        events = []
        for flag in (down, up):
            item = INPUT()
            item.type = MOUSE_INPUT
            item.data.mi = MOUSEINPUT(0, 0, 0, flag, 0, 0)
            events.append(item)
        _send(events)


def foreground_is_this_app() -> bool:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return True
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == kernel32.GetCurrentProcessId()


class HotkeyListener(threading.Thread):
    """Windows 注册全局热键；独立消息线程与 Tk 通过队列通信。"""

    WM_HOTKEY = 0x0312
    WM_UPDATE = 0x8001
    WM_EXIT = 0x8002
    MOD_NOREPEAT = 0x4000
    IDS = {"mouse": 2001, "text": 2003}

    def __init__(self, actions: queue.Queue, initial_bindings: dict[str, tuple[int, int]]):
        super().__init__(daemon=True, name="GlobalHotkeys")
        self.actions = actions
        self._thread_id = None
        self._lock = threading.Lock()
        self._pending = initial_bindings.copy()
        self._bindings = {}
        self._ready = threading.Event()

    def update_bindings(self, bindings: dict[str, tuple[int, int]]) -> None:
        with self._lock:
            self._pending = bindings.copy()
        self._ready.wait(timeout=3)
        if self._thread_id and not user32.PostThreadMessageW(self._thread_id, self.WM_UPDATE, 0, 0):
            self.actions.put(("error", "提交快捷键设置失败，Windows 热键监听不可用。"))

    def stop(self) -> None:
        self._ready.wait(timeout=2)
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, self.WM_EXIT, 0, 0)

    def _unregister(self, bindings: dict[str, tuple[int, int]]) -> None:
        for name in bindings:
            user32.UnregisterHotKey(None, self.IDS[name])

    def _apply(self) -> None:
        with self._lock:
            desired = self._pending.copy()
        previous = self._bindings.copy()
        self._unregister(previous)
        activated = {}
        for name, (mods, vk) in desired.items():
            if user32.RegisterHotKey(None, self.IDS[name], mods | self.MOD_NOREPEAT, vk):
                activated[name] = (mods, vk)
            else:
                error = ctypes.get_last_error()
                self._unregister(activated)
                restored = {}
                for old_name, (old_mods, old_vk) in previous.items():
                    if user32.RegisterHotKey(None, self.IDS[old_name], old_mods | self.MOD_NOREPEAT, old_vk):
                        restored[old_name] = (old_mods, old_vk)
                self._bindings = restored
                self.actions.put(("error", f"快捷键绑定失败（{name}，错误码 {error}）。该热键可能已被其他软件占用。已尝试恢复旧设置。"))
                return
        self._bindings = activated
        self.actions.put(("bound", list(activated)))

    def run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._ready.set()
        self._apply()
        id_to_name = {value: key for key, value in self.IDS.items()}
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if msg.message == self.WM_EXIT:
                    break
                if msg.message == self.WM_UPDATE:
                    self._apply()
                if msg.message == self.WM_HOTKEY:
                    name = id_to_name.get(int(msg.wParam))
                    if name and name in self._bindings:
                        self.actions.put(("hotkey", name))
        finally:
            self._unregister(self._bindings)
