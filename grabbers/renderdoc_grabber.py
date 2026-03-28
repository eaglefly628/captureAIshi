"""RenderDoc-based frame grabber.

Uses RenderDoc's Python replay API to capture RGB and depth buffers
from any DirectX/Vulkan/OpenGL application. Works with both UE5 and Unity.

Capture strategy (in priority order):
  1. Native bridge (capture_bridge) — C++ linked against RenderDoc, fastest
  2. RenderDoc Python module (renderdoc) — official Python bindings
  3. Keypress simulation — fallback for attached-but-no-API scenarios

Requirements:
  - RenderDoc installed (renderdoc module or native bridge built)
  - Game launched through renderdoccmd or with RenderDoc attached

Usage flow:
  1. Launch game via `renderdoccmd capture <game.exe>`
  2. Trigger capture at each pose
  3. Replay the .rdc file to extract RGB + depth textures
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, Set, Tuple

import numpy as np

from grabbers.base import FrameGrabber

logger = logging.getLogger(__name__)

# Try to import the native bridge (built from renderdoc_ext/)
try:
    import capture_bridge as _bridge
    _HAS_NATIVE_BRIDGE = True
    logger.debug("Native capture_bridge loaded")
except ImportError:
    _bridge = None
    _HAS_NATIVE_BRIDGE = False


class RenderDocGrabber(FrameGrabber):
    """Capture frames using RenderDoc's replay API.

    Prefers the native C++ bridge (capture_bridge) when available for
    better performance and deeper integration. Falls back to the
    RenderDoc Python module or keypress simulation.
    """

    def __init__(
        self,
        renderdoc_path: str = "renderdoccmd",
        capture_dir: str = "./captures",
        target_exe: Optional[str] = None,
        target_args: Optional[list] = None,
        capture_key: str = "F12",
        auto_launch: bool = False,
        ui_hider=None,
        ui_tail_fraction: float = 0.2,
        ui_extra_keywords: Optional[list] = None,
        startup_timeout: float = 60.0,
        wait_for_port: Optional[int] = None,
    ):
        """
        Args:
            renderdoc_path: Path to renderdoccmd executable.
            capture_dir: Directory to store .rdc capture files.
            target_exe: Game executable path (for auto-launch).
            target_args: Extra arguments passed to the game executable.
            capture_key: Key to trigger capture.
            auto_launch: Whether to launch the game through RenderDoc.
            ui_hider: Optional RenderDocUIHider for filtering UI draw calls.
            ui_tail_fraction: Fraction of late draw calls to consider as UI (0-1).
            ui_extra_keywords: Additional keywords for UI draw call detection.
            startup_timeout: Max seconds to wait for game to start (default 60).
            wait_for_port: If set, poll this TCP port to detect when the game is ready.
        """
        self.renderdoc_path = renderdoc_path
        self.capture_dir = Path(capture_dir)
        self.target_exe = target_exe
        self.target_args = target_args or []
        self.capture_key = capture_key
        self.auto_launch = auto_launch
        self.ui_hider = ui_hider
        self.ui_tail_fraction = ui_tail_fraction
        self.ui_extra_keywords = ui_extra_keywords or []
        self.startup_timeout = startup_timeout
        self.wait_for_port = wait_for_port
        self._process = None
        self._capture_count = 0
        self._use_native = _HAS_NATIVE_BRIDGE
        self._replay_session = None  # Persistent native ReplaySession

    def setup(self) -> None:
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        # Try to initialize native bridge capture API
        if self._use_native:
            if _bridge.init_capture_api():
                logger.info("Native RenderDoc bridge initialized (in-app API)")
                _bridge.set_capture_path(str(self.capture_dir / "frame"))
            else:
                logger.info("Native bridge loaded but in-app API not available "
                            "(game may not be launched through RenderDoc)")

        if self.auto_launch and self.target_exe:
            # If user put exe + args all in one string, split them apart
            if not Path(self.target_exe).is_file() and " " in self.target_exe:
                import shlex
                parts = shlex.split(self.target_exe, posix=False)
                self.target_exe = parts[0]
                self.target_args = parts[1:] + self.target_args
                logger.info(
                    f"Split target_exe into exe={self.target_exe}, "
                    f"args={self.target_args}"
                )

            # Resolve renderdoccmd path with auto-discovery
            rdoc_cmd = self._resolve_renderdoccmd()
            logger.info(f"Launching {self.target_exe} via RenderDoc ({rdoc_cmd})...")
            # renderdoccmd syntax: capture [--opts] <exe> [game args]
            # All --opt flags must come BEFORE the executable path.
            # See renderdoc/renderdoccmd/renderdoccmd.cpp lines 1628-1687.
            cmd = [
                rdoc_cmd, "capture",
                "--opt-hook-children",
                "--opt-ref-all-resources",
                "--capture-file", str(self.capture_dir / "frame"),
                "--wait-for-exit",
                self.target_exe,
            ] + self.target_args
            logger.info(f"renderdoccmd command: {' '.join(cmd)}")
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Drain stdout/stderr in background threads to prevent pipe deadlock
            # (renderdoccmd with --wait-for-exit stays alive for the game's lifetime)
            self._rdoc_stdout_lines: list = []
            self._rdoc_stderr_lines: list = []
            import threading
            def _drain(stream, sink, label):
                for raw_line in stream:
                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                    if line:
                        sink.append(line)
                        logger.info(f"[renderdoccmd {label}] {line}")
            threading.Thread(
                target=_drain, args=(self._process.stdout, self._rdoc_stdout_lines, "out"),
                daemon=True,
            ).start()
            threading.Thread(
                target=_drain, args=(self._process.stderr, self._rdoc_stderr_lines, "err"),
                daemon=True,
            ).start()
            self._wait_for_game_ready()
        else:
            logger.info(
                "RenderDoc grabber ready. Attach RenderDoc to your game manually "
                f"or launch with: {self.renderdoc_path} capture <game.exe>"
            )

    def _resolve_renderdoccmd(self) -> str:
        """Find renderdoccmd executable.

        Search order:
          1. User-provided path (if it's a valid file or in PATH)
          2. Sibling 'renderdoc' directory relative to project root
             (e.g. ../renderdoc/x64/Development/renderdoccmd.exe)
          3. Common install locations
        """
        import shutil
        import sys

        user_path = self.renderdoc_path
        exe_name = "renderdoccmd.exe" if sys.platform == "win32" else "renderdoccmd"

        # 1. User-provided path — exact file or in PATH
        if Path(user_path).is_file():
            logger.debug(f"renderdoccmd: using user path (file): {user_path}")
            return user_path
        resolved = shutil.which(user_path)
        if resolved:
            logger.debug(f"renderdoccmd: found in PATH: {resolved}")
            return resolved

        # 2. Search relative to project root (parent of this file's package)
        #    Covers layouts like:  captureAIshi/  and  renderdoc/  as siblings
        project_root = Path(__file__).resolve().parent.parent
        search_roots = [project_root, project_root.parent]
        # Typical build output directories
        relative_candidates = [
            Path("renderdoc") / "x64" / "Development" / exe_name,
            Path("renderdoc") / "x64" / "Release" / exe_name,
            Path("renderdoc") / "build" / "bin" / exe_name,
            Path("renderdoc") / "bin" / exe_name,
        ]
        for root in search_roots:
            for candidate in relative_candidates:
                full = root / candidate
                if full.is_file():
                    found = str(full)
                    logger.info(f"renderdoccmd: auto-discovered at {found}")
                    return found

        # 3. Common system install locations (Windows)
        if sys.platform == "win32":
            for prog_dir in [Path("C:/Program Files"), Path("C:/Program Files (x86)")]:
                for rdoc_dir in prog_dir.glob("RenderDoc*"):
                    candidate = rdoc_dir / exe_name
                    if candidate.is_file():
                        found = str(candidate)
                        logger.info(f"renderdoccmd: found in system install: {found}")
                        return found

        searched = ", ".join(str(r) for r in search_roots)
        raise FileNotFoundError(
            f"renderdoccmd not found. Searched: PATH, {searched}/renderdoc/..., "
            f"Program Files. Set full path in UI or add to PATH."
        )

    def _wait_for_game_ready(self) -> None:
        """Poll until the game is ready or renderdoccmd exits.

        Checks every second and logs progress every 5s. If wait_for_port
        is set, also probes that TCP port — once it responds, the game's
        control channel is confirmed up.
        """
        import socket as _socket

        poll_interval = 1.0
        elapsed = 0.0
        port_ready = False

        logger.info(
            f"Waiting for game to start (timeout={self.startup_timeout}s"
            + (f", port={self.wait_for_port}" if self.wait_for_port else "")
            + ")..."
        )

        # RenderDoc ResultCode mapping for actionable error messages
        _RESULT_CODES = {
            0: "Succeeded", 1: "UnknownError", 2: "InternalError",
            3: "FileNotFound", 4: "InjectionFailed", 5: "IncompatibleProcess",
            6: "NetworkIOFailed", 7: "NetworkRemoteBusy",
        }

        while elapsed < self.startup_timeout:
            # Check if renderdoccmd died
            rc = self._process.poll()
            if rc is not None:
                # Give drain threads a moment to flush remaining output
                time.sleep(0.2)
                code_name = _RESULT_CODES.get(rc, f"code {rc}")
                logger.error(
                    f"renderdoccmd exited after {elapsed:.0f}s: {code_name} ({rc})"
                )
                if rc == 4:
                    logger.error(
                        "InjectionFailed: RenderDoc could not inject into the process. "
                        "Common causes:\n"
                        "  - Architecture mismatch (32-bit renderdoccmd vs 64-bit game or vice versa)\n"
                        "  - Anti-cheat or process protection blocking injection\n"
                        "  - UE5 launcher exited before injection completed "
                        "(try launching the actual game exe, not the launcher)"
                    )
                elif rc == 3:
                    logger.error(
                        f"FileNotFound: RenderDoc could not find the executable: "
                        f"{self.target_exe}"
                    )
                elif rc == 5:
                    logger.error(
                        "IncompatibleProcess: The target process architecture doesn't "
                        "match renderdoccmd. Check if both are x64 or both are x86."
                    )
                raise RuntimeError(
                    f"renderdoccmd failed: {code_name} (exit code {rc}). "
                    f"Cannot proceed without a running game."
                )

            # If a port is specified, probe it
            if self.wait_for_port and not port_ready:
                try:
                    with _socket.create_connection(
                        ("127.0.0.1", self.wait_for_port), timeout=0.3
                    ):
                        port_ready = True
                        logger.info(
                            f"Game port {self.wait_for_port} is open after {elapsed:.0f}s"
                        )
                        return  # Game is ready
                except (ConnectionRefusedError, OSError):
                    pass  # Not ready yet

            time.sleep(poll_interval)
            elapsed += poll_interval

            if int(elapsed) % 5 == 0:
                logger.info(f"Still waiting for game... ({elapsed:.0f}s elapsed)")

        # Timeout reached
        if self._process.poll() is None:
            if self.wait_for_port and not port_ready:
                logger.warning(
                    f"Timeout: game process alive but port {self.wait_for_port} "
                    f"not open after {elapsed:.0f}s. Proceeding anyway."
                )
            else:
                logger.info(f"Game appears to be running after {elapsed:.0f}s")
        else:
            raise RuntimeError(
                "Game process is not running after timeout. "
                "Check renderdoccmd output above for details."
            )

    def teardown(self) -> None:
        if self._replay_session is not None:
            try:
                self._replay_session.close()
            except Exception as e:
                logger.warning(f"[TEARDOWN] Failed to close replay session: {e}")
            self._replay_session = None

        if self._process:
            logger.info("[TEARDOWN] Stopping renderdoccmd and game process...")
            try:
                # Kill the entire process tree (renderdoccmd + game children)
                import sys
                if sys.platform == "win32":
                    # On Windows, terminate() only kills renderdoccmd, not child
                    # processes. Use taskkill /T to kill the whole tree.
                    import subprocess as _sp
                    _sp.run(
                        ["taskkill", "/F", "/T", "/PID", str(self._process.pid)],
                        capture_output=True, timeout=10,
                    )
                else:
                    import os
                    import signal
                    # Send SIGTERM to the process group
                    os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
            except Exception as e:
                logger.warning(f"[TEARDOWN] Process tree kill failed, trying terminate: {e}")
                try:
                    self._process.terminate()
                except Exception:
                    pass

            # Wait for process to actually exit
            try:
                self._process.wait(timeout=5)
                logger.info("[TEARDOWN] renderdoccmd process exited")
            except Exception:
                logger.warning("[TEARDOWN] renderdoccmd did not exit in 5s, killing")
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        logger.info(f"RenderDoc grabber: {self._capture_count} frames captured")

    # ── Capture triggering ───────────────────────────────────────────────────

    def trigger_capture(self) -> Optional[Path]:
        """Trigger a frame capture in the attached game.

        Uses the native bridge API if available, then falls back to
        RenderDoc Python module, then to keypress simulation.

        Returns the path to the .rdc file if successful.
        """
        self._capture_count += 1
        rdc_path = self.capture_dir / f"frame_{self._capture_count:06d}.rdc"
        logger.info(f"Triggering capture #{self._capture_count}...")

        # Method 1: Native bridge API (fastest, most reliable)
        if self._use_native:
            path = _bridge.trigger_capture(str(self.capture_dir))
            if path:
                rdc_path = Path(path) if Path(path).exists() else rdc_path
                if rdc_path.exists():
                    return rdc_path

        # Method 2: renderdoccmd triggercapture (most reliable for external capture)
        if self._trigger_via_renderdoccmd(rdc_path):
            return rdc_path

        # Method 3: RenderDoc Python module API
        if self._trigger_via_python_api(rdc_path):
            return rdc_path

        # Method 4: Simulate capture key press
        if self._trigger_via_keypress():
            if self._wait_for_capture(rdc_path, timeout=5.0):
                return rdc_path

        # Log what's actually in the capture directory
        existing_rdcs = list(self.capture_dir.glob("*.rdc"))
        logger.warning(
            f"Capture #{self._capture_count} may not have triggered. "
            f"Existing .rdc files in {self.capture_dir}: {[f.name for f in existing_rdcs]}"
        )
        return rdc_path  # Return expected path; caller checks existence

    def _trigger_via_renderdoccmd(self, rdc_path: Path) -> bool:
        """Trigger capture via renderdoccmd triggercapture command.

        Uses RenderDoc's TargetControl API to connect to the injected game
        and trigger a capture programmatically — no keypress simulation needed.
        """
        try:
            rdoc_cmd = self._resolve_renderdoccmd()
        except FileNotFoundError:
            return False

        cmd = [
            rdoc_cmd, "triggercapture",
            "--frames", "1",
            "--out", str(self.capture_dir),
        ]
        logger.debug(f"[CAPTURE] triggercapture command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=15,
            )
            stdout = result.stdout.decode("utf-8", errors="replace").strip()
            stderr = result.stderr.decode("utf-8", errors="replace").strip()

            if stdout:
                for line in stdout.splitlines():
                    logger.info(f"[CAPTURE trigger] {line}")
            if stderr:
                for line in stderr.splitlines():
                    logger.warning(f"[CAPTURE trigger err] {line}")

            if result.returncode == 0:
                # Find the captured file — triggercapture saves as capture_1.rdc
                captured = self.capture_dir / "capture_1.rdc"
                if captured.exists():
                    captured.rename(rdc_path)
                    logger.info(f"[CAPTURE] Got capture via triggercapture → {rdc_path}")
                    return True
                # Also scan for any new .rdc
                if self._wait_for_capture(rdc_path, timeout=3.0):
                    return True
            else:
                logger.debug(f"[CAPTURE] triggercapture returned {result.returncode}")
        except subprocess.TimeoutExpired:
            logger.debug("[CAPTURE] triggercapture timed out")
        except Exception as e:
            logger.debug(f"[CAPTURE] triggercapture failed: {e}")

        return False

    def _trigger_via_python_api(self, rdc_path: Path) -> bool:
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

    def _trigger_via_keypress(self) -> bool:
        """Simulate the capture key press to trigger RenderDoc.

        On Windows: find the game window, bring it to foreground, then
        send the key using SendInput (more reliable than keybd_event).
        """
        import sys
        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes

                vk_map = {
                    "F12": 0x7B, "F11": 0x7A, "F10": 0x79, "F9": 0x78,
                    "PRINT_SCREEN": 0x2C, "PRINTSCREEN": 0x2C,
                }
                vk = vk_map.get(self.capture_key.upper())
                if vk is None:
                    vk = ord(self.capture_key.upper())

                # Try to focus the game window first
                if self._process:
                    self._focus_game_window()

                # Use SendInput instead of keybd_event (works with more apps)
                INPUT_KEYBOARD = 1
                KEYEVENTF_KEYUP = 0x0002

                class KEYBDINPUT(ctypes.Structure):
                    _fields_ = [
                        ("wVk", wintypes.WORD),
                        ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                    ]

                class INPUT(ctypes.Structure):
                    class _INPUT_UNION(ctypes.Union):
                        _fields_ = [("ki", KEYBDINPUT)]
                    _fields_ = [
                        ("type", wintypes.DWORD),
                        ("union", _INPUT_UNION),
                    ]

                def send_key(vk_code, up=False):
                    inp = INPUT()
                    inp.type = INPUT_KEYBOARD
                    inp.union.ki.wVk = vk_code
                    inp.union.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
                    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

                send_key(vk)
                time.sleep(0.05)
                send_key(vk, up=True)
                logger.debug(f"[CAPTURE] Sent {self.capture_key} (vk=0x{vk:02X}) via SendInput")
                return True
            else:
                result = subprocess.run(
                    ["xdotool", "key", self.capture_key],
                    capture_output=True, timeout=3,
                )
                return result.returncode == 0
        except Exception as e:
            logger.warning(f"Keypress simulation failed: {e}")
        return False

    def _focus_game_window(self) -> None:
        """Find and focus the game window by process ID."""
        import ctypes
        try:
            pid = self._process.pid
            found_hwnd = None

            # EnumWindows callback to find window belonging to our process tree
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))

            def enum_callback(hwnd, _):
                nonlocal found_hwnd
                window_pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                # Check if window is visible and belongs to a child process
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    title_buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 256)
                    title = title_buf.value
                    if title and len(title) > 0:
                        # Game windows typically have non-empty titles
                        # Skip known non-game windows
                        skip = ("renderdoc", "cmd.exe", "python", "conhost")
                        if not any(s in title.lower() for s in skip):
                            found_hwnd = hwnd
                            logger.debug(f"[CAPTURE] Found game window: '{title}' (pid={window_pid.value})")
                            return False  # Stop enumeration
                return True  # Continue

            ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

            if found_hwnd:
                ctypes.windll.user32.SetForegroundWindow(found_hwnd)
                time.sleep(0.1)  # Brief pause for window to come to front
                logger.debug("[CAPTURE] Game window focused")
            else:
                logger.debug("[CAPTURE] Could not find game window to focus")
        except Exception as e:
            logger.debug(f"[CAPTURE] Failed to focus game window: {e}")

    def _wait_for_capture(self, rdc_path: Path, timeout: float = 5.0) -> bool:
        """Wait for a capture file to appear on disk."""
        start = time.time()
        existing = set(self.capture_dir.glob("*.rdc"))
        while time.time() - start < timeout:
            if rdc_path.exists():
                return True
            new_files = set(self.capture_dir.glob("*.rdc")) - existing
            if new_files:
                newest = max(new_files, key=lambda p: p.stat().st_mtime)
                newest.rename(rdc_path)
                return True
            time.sleep(0.2)
        return False

    # ── Frame capture + replay ───────────────────────────────────────────────

    def capture_frame(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Capture current frame via RenderDoc.

        Triggers a capture and replays it to extract RGB + depth.
        Prefers native bridge for replay, falls back to Python API.
        """
        import time as _time
        t0 = _time.monotonic()

        rdc_path = self.trigger_capture()
        trigger_elapsed = _time.monotonic() - t0
        logger.debug(f"[RDOC] Capture trigger took {trigger_elapsed:.3f}s → {rdc_path}")
        if rdc_path is None:
            logger.warning("[RDOC] Capture trigger returned None")
            return None, None

        # Try native bridge replay first
        if self._use_native:
            try:
                rgb, depth = self._replay_native(rdc_path)
                if rgb is not None or depth is not None:
                    return rgb, depth
            except Exception as e:
                logger.warning(f"Native bridge replay failed: {e}")

        # Fall back to Python API replay
        logger.debug("[RDOC] Trying Python API replay fallback")
        try:
            rgb, depth = self._replay_python(rdc_path)
            logger.debug(f"[RDOC] Python replay result: rgb={'ok' if rgb is not None else 'None'}, "
                         f"depth={'ok' if depth is not None else 'None'}")
            return rgb, depth
        except Exception as e:
            logger.warning(f"RenderDoc replay failed: {e}")
            return None, None

    def _replay_native(self, rdc_path: Path):
        """Replay using the native C++ bridge. Returns (rgb, depth)."""
        session = _bridge.ReplaySession()
        if not session.open(str(rdc_path)):
            logger.warning(f"Native bridge: failed to open {rdc_path}")
            return None, None

        try:
            # Classify and exclude UI draw calls
            excluded: Set[int] = set()
            if self.ui_hider is not None or self.ui_tail_fraction > 0:
                excluded = session.classify_ui_events(
                    self.ui_tail_fraction,
                    self.ui_extra_keywords,
                )
                if excluded:
                    logger.debug(f"Native bridge: excluding {len(excluded)} UI draw calls")

            # Extract frame
            fb = session.extract_frame(0, excluded)

            rgb = fb.rgb if fb.has_rgb else None
            depth = fb.depth if fb.has_depth else None

            # Log depth format
            if fb.has_depth:
                fmt = session.detect_depth_format()
                logger.debug(f"Depth format: {fmt}")

            return rgb, depth
        finally:
            session.close()

    def _replay_python(self, rdc_path: Path):
        """Replay using renderdoccmd exportframe (custom C++ command).

        The renderdoc.pyd Python module crashes with ACCESS_VIOLATION when
        loaded outside of qrenderdoc, so we use our custom `exportframe`
        command compiled into renderdoccmd instead. It saves:
          - rgb.png   (backbuffer, uint8)
          - depth.exr (depth target, float32)

        We then load these files back as numpy arrays.
        """
        if not rdc_path.exists():
            logger.warning(f"[RDOC] Capture file does not exist: {rdc_path}")
            return None, None

        # Resolve renderdoccmd (same logic as setup)
        try:
            rdoc_cmd = self._resolve_renderdoccmd()
        except FileNotFoundError as e:
            logger.error(f"[RDOC] {e}")
            return None, None

        # Output directory for exported frames
        replay_out = self.capture_dir / f"_replay_{rdc_path.stem}"
        replay_out.mkdir(parents=True, exist_ok=True)

        cmd = [
            rdoc_cmd, "exportframe",
            str(rdc_path),
            "--out", str(replay_out),
            "--format", "png",
        ]
        logger.debug(f"[RDOC] Export command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60,
            )

            stdout = result.stdout.decode("utf-8", errors="replace").strip()
            stderr = result.stderr.decode("utf-8", errors="replace").strip()

            if stdout:
                for line in stdout.splitlines():
                    logger.info(f"[RDOC export] {line}")
            if stderr:
                for line in stderr.splitlines():
                    logger.warning(f"[RDOC export stderr] {line}")

            if result.returncode not in (0,):
                if result.returncode == 3:
                    logger.warning("[RDOC] exportframe found neither RGB nor depth in capture")
                else:
                    logger.error(f"[RDOC] exportframe exited with code {result.returncode}")
                    return None, None

        except subprocess.TimeoutExpired:
            logger.error("[RDOC] exportframe timed out (60s)")
            return None, None
        except Exception as e:
            logger.error(f"[RDOC] Failed to run exportframe: {e}")
            return None, None

        # Load exported images
        rgb = self._load_rgb_image(replay_out)
        depth = self._load_depth_exr(replay_out)

        # Normalize depth and save preview
        if depth is not None:
            depth = self._normalize_depth(depth, replay_out)

        # Copy preview files to session output before cleanup
        session_out = self.capture_dir.parent
        for keep_name in ("depth_preview.png",):
            src = replay_out / keep_name
            if src.exists():
                dst = session_out / f"{rdc_path.stem}_{keep_name}"
                try:
                    import shutil
                    shutil.copy2(str(src), str(dst))
                    logger.info(f"[RDOC] Preview saved: {dst}")
                except Exception as e:
                    logger.debug(f"[RDOC] Could not copy preview: {e}")

        # Clean up temp exported files
        for f in replay_out.iterdir():
            try:
                f.unlink()
            except OSError:
                pass
        try:
            replay_out.rmdir()
        except OSError:
            pass

        return rgb, depth

    def _load_rgb_image(self, directory: Path) -> Optional[np.ndarray]:
        """Load exported RGB image (png/jpg/bmp) as uint8 numpy array (H, W, 3)."""
        for ext in ("png", "jpg", "bmp", "tga"):
            rgb_file = directory / f"rgb.{ext}"
            if rgb_file.exists():
                try:
                    from PIL import Image
                    img = Image.open(str(rgb_file)).convert("RGB")
                    arr = np.array(img, dtype=np.uint8)
                    logger.debug(f"[RDOC] Loaded RGB: {arr.shape[1]}x{arr.shape[0]} from {rgb_file.name}")
                    return arr
                except ImportError:
                    logger.warning("[RDOC] Pillow not installed — trying imageio for RGB")
                    try:
                        import imageio.v3 as iio
                        arr = iio.imread(str(rgb_file))
                        if arr.ndim == 3 and arr.shape[2] == 4:
                            arr = arr[:, :, :3]
                        logger.debug(f"[RDOC] Loaded RGB: {arr.shape[1]}x{arr.shape[0]} from {rgb_file.name}")
                        return arr
                    except ImportError:
                        logger.error("[RDOC] Neither Pillow nor imageio installed — cannot load RGB")
                        return None
                except Exception as e:
                    logger.error(f"[RDOC] Failed to load RGB from {rgb_file}: {e}")
                    return None
        logger.debug("[RDOC] No RGB image found in export directory")
        return None

    def _load_depth_exr(self, directory: Path) -> Optional[np.ndarray]:
        """Load exported depth EXR as float32 numpy array (H, W)."""
        depth_file = directory / "depth.exr"
        if not depth_file.exists():
            logger.debug("[RDOC] No depth.exr found in export directory")
            return None

        # Try OpenEXR first (most reliable for float data)
        try:
            import OpenEXR
            import Imath
            exr = OpenEXR.InputFile(str(depth_file))
            header = exr.header()
            dw = header["dataWindow"]
            w = dw.max.x - dw.min.x + 1
            h = dw.max.y - dw.min.y + 1
            # Read the first channel (R) as float
            channels = list(header["channels"].keys())
            ch_name = channels[0] if channels else "R"
            raw = exr.channel(ch_name, Imath.PixelType(Imath.PixelType.FLOAT))
            arr = np.frombuffer(raw, dtype=np.float32).reshape(h, w)
            logger.debug(f"[RDOC] Loaded depth: {w}x{h} from depth.exr (OpenEXR)")
            return arr
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[RDOC] OpenEXR failed to load depth: {e}")

        # Try imageio with freeimage backend
        try:
            import imageio.v3 as iio
            arr = iio.imread(str(depth_file))
            if arr.ndim == 3:
                arr = arr[:, :, 0]  # Take first channel
            arr = arr.astype(np.float32)
            logger.debug(f"[RDOC] Loaded depth: {arr.shape[1]}x{arr.shape[0]} from depth.exr (imageio)")
            return arr
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[RDOC] imageio failed to load depth.exr: {e}")

        # Try cv2
        try:
            import cv2
            arr = cv2.imread(str(depth_file), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
            if arr is not None:
                if arr.ndim == 3:
                    arr = arr[:, :, 0]
                arr = arr.astype(np.float32)
                logger.debug(f"[RDOC] Loaded depth: {arr.shape[1]}x{arr.shape[0]} from depth.exr (cv2)")
                return arr
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[RDOC] cv2 failed to load depth.exr: {e}")

        logger.error(
            "[RDOC] Cannot load depth.exr — install one of: OpenEXR, imageio[freeimage], opencv-python"
        )
        return None

    def _normalize_depth(self, depth: np.ndarray, output_dir: Path) -> np.ndarray:
        """Normalize raw depth buffer to linear 0-1 range.

        UE5 uses reversed-Z: near=1.0, far=0.0.
        We invert so that near=0 (dark), far=1 (bright) — standard convention.
        Also saves a depth_preview.png for visual inspection.
        """
        # Read depth_range.txt if available (written by exportframe)
        reversed_z = True  # Default for UE5
        range_file = output_dir / "depth_range.txt"
        if range_file.exists():
            try:
                text = range_file.read_text()
                for line in text.splitlines():
                    if line.startswith("reversed_z="):
                        reversed_z = line.split("=")[1].strip() == "1"
            except Exception:
                pass

        # Compute percentile-based range to handle outliers
        # (reversed-Z: most values cluster near 1.0 for near, 0.0 for far)
        dmin_raw, dmax_raw = float(depth.min()), float(depth.max())
        logger.info(f"[RDOC] Raw depth range: [{dmin_raw:.6f}, {dmax_raw:.6f}], reversed_z={reversed_z}")

        # Use percentiles for robust normalization (ignore extreme outliers)
        dmin = float(np.percentile(depth, 1))
        dmax = float(np.percentile(depth, 99))
        logger.info(f"[RDOC] Percentile depth range (1-99%): [{dmin:.6f}, {dmax:.6f}]")

        drange = dmax - dmin
        if drange < 1e-10:
            logger.warning(f"[RDOC] Depth range too small ({drange}), skipping normalization")
            return depth

        normalized = np.clip((depth - dmin) / drange, 0, 1).astype(np.float32)

        # Invert for reversed-Z (UE5): so near=dark, far=bright
        if reversed_z:
            normalized = 1.0 - normalized

        # Save preview PNG
        try:
            preview_u8 = (normalized * 255).astype(np.uint8)
            from PIL import Image
            preview = Image.fromarray(preview_u8, mode="L")
            preview_path = output_dir / "depth_preview.png"
            preview.save(str(preview_path))
            logger.info(f"[RDOC] Saved depth preview: {preview_path}")
        except Exception as e:
            logger.debug(f"[RDOC] Could not save depth preview: {e}")

        return normalized

    def _find_renderdoc_dirs(self):
        """Find renderdoc.pyd and renderdoc.dll directories.

        Returns (pyd_dir, dll_dir) or (None, None) if not found.
        """
        import sys as _sys

        pyd_name = "renderdoc.pyd" if _sys.platform == "win32" else "renderdoc.so"
        project_root = Path(__file__).resolve().parent.parent
        search_roots = [project_root, project_root.parent]
        candidates = [
            Path("renderdoc") / "x64" / "Development" / "pymodules",
            Path("renderdoc") / "x64" / "Release" / "pymodules",
            Path("renderdoc") / "build" / "lib" / "pymodules",
        ]
        for root in search_roots:
            for candidate in candidates:
                pyd_dir = root / candidate
                pyd_file = pyd_dir / pyd_name
                if pyd_file.is_file():
                    dll_dir = pyd_dir.parent  # e.g. x64/Development/
                    logger.debug(f"[RDOC] Found {pyd_name} at {pyd_dir}, DLLs at {dll_dir}")
                    return pyd_dir, dll_dir

        logger.error(
            f"[RDOC] renderdoc Python bindings ({pyd_name}) not found. "
            f"Build 'pyrenderdoc_module' in Visual Studio. "
            f"Searched: {', '.join(str(r) for r in search_roots)}"
        )
        return None, None
