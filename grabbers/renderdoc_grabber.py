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
            self._replay_session.close()
            self._replay_session = None
        if self._process:
            self._process.terminate()
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

        # Method 2: RenderDoc Python module API
        if self._trigger_via_python_api(rdc_path):
            return rdc_path

        # Method 3: Simulate capture key press
        if self._trigger_via_keypress():
            if self._wait_for_capture(rdc_path, timeout=5.0):
                return rdc_path

        logger.warning(f"Capture #{self._capture_count} may not have triggered")
        return rdc_path  # Return expected path; caller checks existence

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
        """Simulate the capture key press to trigger RenderDoc."""
        import sys
        try:
            if sys.platform == "win32":
                import ctypes
                vk_map = {
                    "F12": 0x7B, "F11": 0x7A, "F10": 0x79, "F9": 0x78,
                    "PRINT_SCREEN": 0x2C, "PRINTSCREEN": 0x2C,
                }
                vk = vk_map.get(self.capture_key.upper())
                if vk is None:
                    vk = ord(self.capture_key.upper())
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.05)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
                return True
            else:
                result = subprocess.run(
                    ["xdotool", "key", self.capture_key],
                    capture_output=True, timeout=3,
                )
                return result.returncode == 0
        except Exception as e:
            logger.debug(f"Keypress simulation failed: {e}")
        return False

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
        """Replay using the RenderDoc Python module. Returns (rgb, depth)."""
        try:
            import renderdoc as rd
        except ImportError:
            logger.error(
                "renderdoc Python module not found. "
                "Build the native bridge or add RenderDoc Python bindings to PYTHONPATH. "
                "Typically: export PYTHONPATH=/path/to/renderdoc/lib"
            )
            return None, None

        cap = rd.OpenCaptureFile()
        result = cap.OpenFile(str(rdc_path), "", None)
        if result != rd.ResultCode.Succeeded:
            logger.error(f"Failed to open capture: {rdc_path}")
            cap.Shutdown()
            return None, None

        controller = cap.OpenCapture(rd.ReplayOptions(), None)
        if controller is None:
            logger.error("Failed to create replay controller")
            cap.Shutdown()
            return None, None

        try:
            # If a RenderDoc UI hider is configured, set up its replay
            # context and filter UI draw calls for this frame
            if self.ui_hider is not None and hasattr(self.ui_hider, "set_replay_context"):
                self.ui_hider.set_replay_context(controller, rd)
                self.ui_hider.hide()
                excluded = self.ui_hider.get_excluded_events()
                if excluded:
                    logger.debug(f"Excluding {len(excluded)} UI draw calls")

            rgb = self._extract_backbuffer(controller, rd)
            depth = self._extract_depth(controller, rd)
            return rgb, depth
        finally:
            if self.ui_hider is not None and hasattr(self.ui_hider, "set_replay_context"):
                self.ui_hider.restore()
            controller.Shutdown()
            cap.Shutdown()

    def _extract_backbuffer(self, controller, rd):
        """Extract the RGB backbuffer from a replay."""
        textures = controller.GetTextures()
        for tex in textures:
            if tex.creationFlags & rd.TextureCategory.SwapBuffer:
                data = controller.GetTextureData(tex.resourceId, rd.Subresource())
                if data is not None:
                    w, h = tex.width, tex.height
                    arr = np.frombuffer(data, dtype=np.uint8)
                    if len(arr) >= w * h * 4:
                        rgba = arr[:w * h * 4].reshape(h, w, 4)
                        return rgba[:, :, :3]  # Drop alpha
        logger.warning("Backbuffer not found in capture")
        return None

    def _extract_depth(self, controller, rd):
        """Extract the depth buffer from a replay."""
        textures = controller.GetTextures()
        for tex in textures:
            if tex.creationFlags & rd.TextureCategory.DepthTarget:
                data = controller.GetTextureData(tex.resourceId, rd.Subresource())
                if data is not None:
                    w, h = tex.width, tex.height
                    arr = np.frombuffer(data, dtype=np.float32)
                    if len(arr) >= w * h:
                        depth = arr[:w * h].reshape(h, w)
                        return depth
        logger.warning("Depth buffer not found in capture")
        return None
