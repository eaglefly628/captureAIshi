"""Windows-only Play-In-Editor remote control.

UE5.8 MCP exposes no PIE-control tool. The only zero-UE-changes way to
start/stop PIE from ADORE is to find the UE Editor window and synthesize
its default hotkeys via Win32 SendInput:

  start PIE   = Alt+P    (Editor preference 'Play In Editor' default)
  stop  PIE   = Esc      (with Editor / PIE viewport focused)

This module degrades to a no-op + clear error message on non-Windows
hosts; ADORE Flask running on the same Windows box as UE is the
supported deployment.
"""

from __future__ import annotations

import sys
import time
from typing import Optional


WINDOWS = sys.platform.startswith("win")

VK_MENU   = 0x12  # Alt
VK_SHIFT  = 0x10
VK_ESCAPE = 0x1B
VK_P      = 0x50


def _setup_win32():
    """Lazy import + struct setup; returns (user32, INPUT, KEYBDINPUT) or None."""
    if not WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG), ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD),
        ]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", _HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

    return user32, INPUT, KEYBDINPUT


def _find_unreal_window(user32) -> Optional[int]:
    """EnumWindows -> first top-level whose title contains 'Unreal Editor'."""
    import ctypes
    from ctypes import wintypes

    found = [None]
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if "Unreal Editor" in title or "UnrealEditor" in title:
            found[0] = hwnd
            return False
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0]


def _focus_unreal(user32, hwnd: int) -> None:
    """Restore-if-minimized + bring foreground. Returns silently if any
    step fails; the caller will see a no-op key send."""
    SW_RESTORE = 9
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
    except Exception:
        pass
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _send_key(user32, INPUT, KEYBDINPUT, vk: int, up: bool = False) -> None:
    import ctypes
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    flags = KEYEVENTF_KEYUP if up else 0
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _focus_and_send(combo: list[int]) -> dict:
    """Find UE window, focus, send key combo (down... then up reversed)."""
    if not WINDOWS:
        return {"ok": False, "error": "PIE remote requires Windows host",
                "platform": sys.platform}
    setup = _setup_win32()
    if setup is None:
        return {"ok": False, "error": "win32 init failed"}
    user32, INPUT, KEYBDINPUT = setup

    hwnd = _find_unreal_window(user32)
    if hwnd is None:
        return {"ok": False, "error": "Unreal Editor window not found"}

    _focus_unreal(user32, hwnd)
    time.sleep(0.12)  # let foreground change settle

    for vk in combo:
        _send_key(user32, INPUT, KEYBDINPUT, vk, up=False)
        time.sleep(0.02)
    for vk in reversed(combo):
        _send_key(user32, INPUT, KEYBDINPUT, vk, up=True)
        time.sleep(0.02)

    return {"ok": True, "hwnd": int(hwnd), "combo_vk": combo}


def play_in_editor() -> dict:
    """Send Alt+P to the UE Editor window."""
    return _focus_and_send([VK_MENU, VK_P])


def end_play_in_editor() -> dict:
    """Send Esc to stop the active PIE session. UE's PIE viewport
    intercepts Esc as 'request close', which works from any focus state
    inside the editor."""
    return _focus_and_send([VK_ESCAPE])
