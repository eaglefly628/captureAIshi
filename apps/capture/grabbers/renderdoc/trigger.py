"""Capture-trigger helpers: renderdoccmd triggercapture, Python API, keypress."""

import ctypes
import logging
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Optional

from grabbers.renderdoc.paths import find_latest_rdc, resolve_renderdoccmd

logger = logging.getLogger(__name__)


def start_trigger_process(renderdoc_path: str, capture_dir: Path) -> Optional[subprocess.Popen]:
    """Start the persistent ``renderdoccmd triggercapture --interactive`` process.

    Returns the Popen once it prints READY, or None on failure. Interactive
    mode keeps a single TargetControl connection alive so subsequent
    captures only need a ``trigger <path>\\n`` line on stdin.
    """
    try:
        rdoc_cmd = resolve_renderdoccmd(renderdoc_path)
    except FileNotFoundError:
        return None

    cmd = [
        rdoc_cmd, "triggercapture",
        "--interactive",
        "--frames", "1",
        "--out", str(capture_dir),
    ]
    logger.info(f"[CAPTURE] Starting persistent trigger process: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # Don't pipe stderr: fills buffer and deadlocks on Windows
    )

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            logger.error(f"[CAPTURE] Trigger process exited early (rc={proc.returncode})")
            return None
        line = proc.stdout.readline().decode("utf-8", errors="replace").strip()
        if line:
            logger.info(f"[CAPTURE trigger] {line}")
        if "READY" in line:
            logger.info("[CAPTURE] Persistent trigger process ready")
            return proc

    logger.error("[CAPTURE] Trigger process did not become ready in 30s")
    proc.kill()
    return None


def trigger_interactive(
    proc: subprocess.Popen,
    rdc_path: Path,
    capture_dir: Path,
) -> bool:
    """Send a trigger command to the persistent trigger process via stdin.

    Reads lines until "OK id=..." or "ERR ..." arrives. We match "OK id="
    specifically, NOT just "OK" -- the C++ process also prints "OK copied
    -> ..." / "OK rgb ..." lines which would cause premature return and
    desync stdin/stdout.
    """
    if proc is None or proc.poll() is not None:
        return False

    try:
        cmd_line = f"trigger {rdc_path}\n"
        proc.stdin.write(cmd_line.encode("utf-8"))
        proc.stdin.flush()

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            line = proc.stdout.readline().decode("utf-8", errors="replace").strip()
            if not line:
                if proc.poll() is not None:
                    logger.error("[CAPTURE] Trigger process died during capture")
                    return False
                continue
            logger.debug(f"[CAPTURE trigger] {line}")
            if line.startswith("OK id="):
                logger.info(f"[CAPTURE] {line}")
                if rdc_path.exists():
                    return True
                latest = find_latest_rdc(capture_dir)
                if latest and latest != rdc_path:
                    latest.rename(rdc_path)
                    return True
                return rdc_path.exists()
            if line.startswith("ERR"):
                logger.warning(f"[CAPTURE] {line}")
                return False

        logger.warning("[CAPTURE] Interactive trigger timed out")
        return False
    except (BrokenPipeError, OSError) as e:
        logger.warning(f"[CAPTURE] Interactive trigger pipe error: {e}")
        return False


def trigger_oneshot(renderdoc_path: str, rdc_path: Path, capture_dir: Path) -> bool:
    """Fallback: trigger via one-shot renderdoccmd process."""
    try:
        rdoc_cmd = resolve_renderdoccmd(renderdoc_path)
    except FileNotFoundError:
        return False

    existing_rdcs = set(capture_dir.glob("*.rdc"))

    cmd = [
        rdoc_cmd, "triggercapture",
        "--frames", "1",
        "--out", str(capture_dir),
    ]
    logger.debug(f"[CAPTURE] triggercapture oneshot: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        stderr = result.stderr.decode("utf-8", errors="replace").strip()

        if stdout:
            for line in stdout.splitlines():
                logger.info(f"[CAPTURE trigger] {line}")
        if stderr:
            for line in stderr.splitlines():
                logger.warning(f"[CAPTURE trigger err] {line}")

        if result.returncode == 0:
            captured = capture_dir / "capture_1.rdc"
            if captured.exists():
                captured.rename(rdc_path)
                return True
            new_rdcs = set(capture_dir.glob("*.rdc")) - existing_rdcs
            if new_rdcs:
                newest = max(new_rdcs, key=lambda p: p.stat().st_mtime)
                newest.rename(rdc_path)
                return True
    except subprocess.TimeoutExpired:
        logger.debug("[CAPTURE] triggercapture oneshot timed out")
    except Exception as e:
        logger.debug(f"[CAPTURE] triggercapture oneshot failed: {e}")

    return False


def trigger_via_python_api(rdc_path: Path) -> bool:
    """Try triggering capture through RenderDoc's Python API."""
    try:
        import renderdoc as rd
        if hasattr(rd, "TriggerCapture"):
            rd.TriggerCapture()
            time.sleep(0.5)
            return rdc_path.exists()
        if hasattr(rd, "StartFrameCapture") and hasattr(rd, "EndFrameCapture"):
            rd.StartFrameCapture(None, None)
            time.sleep(0.1)
            rd.EndFrameCapture(None, None)
            time.sleep(0.5)
            return rdc_path.exists()
    except ImportError:
        logger.debug("renderdoc Python module not available")
    except Exception as e:
        logger.debug(f"RenderDoc Python API capture failed: {e}")
    return False


def trigger_via_keypress(capture_key: str, game_process: Optional[subprocess.Popen]) -> bool:
    """Simulate the capture key press to trigger RenderDoc.

    On Windows: find the game window, bring it to foreground, then send
    the key via SendInput (more reliable than keybd_event).
    """
    try:
        if sys.platform == "win32":
            vk_map = {
                "F12": 0x7B, "F11": 0x7A, "F10": 0x79, "F9": 0x78,
                "PRINT_SCREEN": 0x2C, "PRINTSCREEN": 0x2C,
            }
            vk = vk_map.get(capture_key.upper()) or ord(capture_key.upper())

            if game_process is not None:
                _focus_game_window(game_process.pid)

            _send_key(vk)
            time.sleep(0.05)
            _send_key(vk, up=True)
            logger.debug(f"[CAPTURE] Sent {capture_key} (vk=0x{vk:02X}) via SendInput")
            return True
        else:
            result = subprocess.run(
                ["xdotool", "key", capture_key],
                capture_output=True, timeout=3,
            )
            return result.returncode == 0
    except Exception as e:
        logger.warning(f"Keypress simulation failed: {e}")
    return False


# Windows-specific SendInput scaffolding
if sys.platform == "win32":
    _INPUT_KEYBOARD = 1
    _KEYEVENTF_KEYUP = 0x0002

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _INPUT(ctypes.Structure):
        class _INPUT_UNION(ctypes.Union):
            _fields_ = [("ki", _KEYBDINPUT)]
        _fields_ = [
            ("type", wintypes.DWORD),
            ("union", _INPUT_UNION),
        ]

    def _send_key(vk_code: int, up: bool = False) -> None:
        inp = _INPUT()
        inp.type = _INPUT_KEYBOARD
        inp.union.ki.wVk = vk_code
        inp.union.ki.dwFlags = _KEYEVENTF_KEYUP if up else 0
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
else:
    def _send_key(vk_code: int, up: bool = False) -> None:
        pass


def _focus_game_window(pid: int) -> None:
    """Find and focus the game window belonging to ``pid`` or its children."""
    try:
        found_hwnd = None
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)
        )

        def enum_callback(hwnd, _):
            nonlocal found_hwnd
            window_pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                title_buf = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 256)
                title = title_buf.value
                if title and len(title) > 0:
                    skip = ("renderdoc", "cmd.exe", "python", "conhost")
                    if not any(s in title.lower() for s in skip):
                        found_hwnd = hwnd
                        logger.debug(f"[CAPTURE] Found game window: '{title}' (pid={window_pid.value})")
                        return False
            return True

        ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

        if found_hwnd:
            ctypes.windll.user32.SetForegroundWindow(found_hwnd)
            time.sleep(0.1)
            logger.debug("[CAPTURE] Game window focused")
        else:
            logger.debug("[CAPTURE] Could not find game window to focus")
    except Exception as e:
        logger.debug(f"[CAPTURE] Failed to focus game window: {e}")


def wait_for_capture(rdc_path: Path, capture_dir: Path, timeout: float = 5.0) -> bool:
    """Wait for a capture file to appear on disk."""
    start = time.time()
    existing = set(capture_dir.glob("*.rdc"))
    while time.time() - start < timeout:
        if rdc_path.exists():
            return True
        new_files = set(capture_dir.glob("*.rdc")) - existing
        if new_files:
            newest = max(new_files, key=lambda p: p.stat().st_mtime)
            newest.rename(rdc_path)
            return True
        time.sleep(0.2)
    return False
