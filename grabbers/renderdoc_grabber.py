"""RenderDoc-based frame grabber (orchestrator).

Capture RGB, depth, and normal buffers from any RenderDoc-compatible
application. Tries the native C++ ``capture_bridge`` first, then the
RenderDoc Python module, then keypress simulation. The concrete work
lives in ``grabbers.renderdoc.{paths,launch,trigger,exporter,image_loader}``.
"""

import logging
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from grabbers.base import FrameData, FrameGrabber
from grabbers.renderdoc import launch as _launch
from grabbers.renderdoc import trigger as _trigger
from grabbers.renderdoc.exporter import export_batch, replay_native, replay_via_exportframe
from grabbers.renderdoc.paths import find_renderdoc_dirs

logger = logging.getLogger(__name__)

try:
    import capture_bridge as _bridge
    _HAS_NATIVE_BRIDGE = True
    logger.debug("Native capture_bridge loaded")
except ImportError:
    _bridge = None
    _HAS_NATIVE_BRIDGE = False


class RenderDocGrabber(FrameGrabber):
    """Capture frames using RenderDoc's replay API.

    Prefers the native C++ bridge (``capture_bridge``) for speed and
    deeper integration; falls back to RenderDoc's Python module or
    keypress simulation.
    """

    def __init__(
        self,
        renderdoc_path: str = "renderdoccmd",
        capture_dir: str = "./captures",
        target_exe: Optional[str] = None,
        target_args: Optional[list] = None,
        capture_key: str = "F12",
        auto_launch: bool = False,
        inject_mode: bool = False,
        inject_delay: float = 5.0,
        ui_hider=None,
        ui_tail_fraction: float = 0.2,
        ui_extra_keywords: Optional[list] = None,
        startup_timeout: float = 60.0,
        wait_for_port: Optional[int] = None,
        export_normal: bool = True,
        capture_profile: Optional[dict] = None,
    ):
        # inject_mode: wait for the game to start then inject instead of
        # launching via renderdoccmd. Needed for games where the RenderDoc
        # launch path triggers D3D12 device-integrity checks and crashes
        # (e.g. Cyberpunk 2077 2.x ray-tracing init).
        self.renderdoc_path = renderdoc_path
        self.capture_dir = Path(capture_dir)
        self.target_exe = target_exe
        self.target_args = target_args or []
        self.capture_key = capture_key
        self.auto_launch = auto_launch
        self.inject_mode = inject_mode
        self.ui_hider = ui_hider
        self.ui_tail_fraction = ui_tail_fraction
        self.ui_extra_keywords = ui_extra_keywords or []
        self.startup_timeout = startup_timeout
        self.wait_for_port = wait_for_port
        self.inject_delay = inject_delay
        self._process: Optional[subprocess.Popen] = None
        self._game_direct_process: Optional[subprocess.Popen] = None
        self._capture_count = 0
        self.export_normal = export_normal
        self.capture_profile = capture_profile or {}
        self._use_native = _HAS_NATIVE_BRIDGE
        self._replay_session = None
        self._trigger_process: Optional[subprocess.Popen] = None

    # ── Setup / teardown ─────────────────────────────────────────────────────

    def setup(self) -> None:
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        if self._use_native:
            if _bridge.init_capture_api():
                logger.info("Native RenderDoc bridge initialized (in-app API)")
                _bridge.set_capture_path(str(self.capture_dir / "frame"))
            else:
                logger.info(
                    "Native bridge loaded but in-app API not available "
                    "(game may not be launched through RenderDoc)"
                )

        if self.inject_mode and self.target_exe:
            process_name = os.path.basename(self.target_exe)
            if self.auto_launch:
                self._game_direct_process = _launch.launch_game_direct(
                    self.target_exe, self.target_args
                )
            _launch.inject_into_process(
                process_name,
                self.renderdoc_path,
                self.startup_timeout,
                self.inject_delay,
                have_direct_launch=(self._game_direct_process is not None),
            )
            _launch.wait_for_game_ready(
                self._process, self.startup_timeout, self.wait_for_port, self.target_exe
            )
        elif self.auto_launch and self.target_exe:
            # If exe + args came as one string, split them
            if not Path(self.target_exe).is_file() and " " in self.target_exe:
                parts = shlex.split(self.target_exe, posix=False)
                self.target_exe = parts[0]
                self.target_args = parts[1:] + self.target_args
                logger.info(f"Split target_exe into exe={self.target_exe}, args={self.target_args}")

            self._process, _, _ = _launch.start_renderdoccmd_capture(
                self.renderdoc_path, self.target_exe, self.target_args, self.capture_dir
            )
            _launch.wait_for_game_ready(
                self._process, self.startup_timeout, self.wait_for_port, self.target_exe
            )
        else:
            logger.info(
                "RenderDoc grabber ready. Attach RenderDoc to your game manually "
                f"or launch with: {self.renderdoc_path} capture <game.exe>"
            )

    def teardown(self) -> None:
        if self._trigger_process is not None:
            try:
                self._trigger_process.stdin.write(b"quit\n")
                self._trigger_process.stdin.flush()
                self._trigger_process.wait(timeout=5)
            except Exception:
                try:
                    self._trigger_process.kill()
                except Exception:
                    pass
            self._trigger_process = None

        if self._replay_session is not None:
            try:
                self._replay_session.close()
            except Exception as e:
                logger.warning(f"[TEARDOWN] Failed to close replay session: {e}")
            self._replay_session = None

        if self._process:
            logger.info("[TEARDOWN] Stopping renderdoccmd and game process...")
            _launch.kill_renderdoccmd_tree(self._process)
            self._process = None

        logger.info(f"RenderDoc grabber: {self._capture_count} frames captured")

    # ── Capture triggering ───────────────────────────────────────────────────

    def trigger_capture(self) -> Optional[Path]:
        """Trigger a frame capture in the attached game.

        Tries, in order: native bridge, persistent/oneshot renderdoccmd
        triggercapture, RenderDoc Python API, keypress simulation.
        Returns the .rdc path (may not yet exist if all methods failed --
        caller should check).
        """
        self._capture_count += 1
        rdc_path = self.capture_dir / f"frame_{self._capture_count:06d}.rdc"
        logger.info(f"Triggering capture #{self._capture_count}...")

        if self._use_native:
            path = _bridge.trigger_capture(str(self.capture_dir))
            if path:
                candidate = Path(path)
                if candidate.exists():
                    return candidate

        if self._trigger_via_renderdoccmd(rdc_path):
            return rdc_path

        if _trigger.trigger_via_python_api(rdc_path):
            return rdc_path

        if _trigger.trigger_via_keypress(self.capture_key, self._process):
            if _trigger.wait_for_capture(rdc_path, self.capture_dir, timeout=5.0):
                return rdc_path

        existing_rdcs = list(self.capture_dir.glob("*.rdc"))
        logger.warning(
            f"Capture #{self._capture_count} may not have triggered. "
            f"Existing .rdc files in {self.capture_dir}: {[f.name for f in existing_rdcs]}"
        )
        return rdc_path

    def _trigger_via_renderdoccmd(self, rdc_path: Path) -> bool:
        """Persistent interactive trigger with one-shot fallback."""
        if self._ensure_trigger_process():
            if _trigger.trigger_interactive(self._trigger_process, rdc_path, self.capture_dir):
                return True
            # Interactive can lose pipe after errors; fall through to oneshot.
            if self._trigger_process is None or self._trigger_process.poll() is not None:
                self._trigger_process = None
        return _trigger.trigger_oneshot(self.renderdoc_path, rdc_path, self.capture_dir)

    def _ensure_trigger_process(self) -> bool:
        """Start or re-verify the persistent triggercapture process."""
        if self._trigger_process is not None:
            if self._trigger_process.poll() is None:
                return True
            logger.warning("[CAPTURE] Persistent trigger process died, restarting")
            self._trigger_process = None

        self._trigger_process = _trigger.start_trigger_process(
            self.renderdoc_path, self.capture_dir
        )
        return self._trigger_process is not None

    # ── Two-phase batch capture ──────────────────────────────────────────────

    def trigger_only(self) -> Optional[Path]:
        """Phase 1: trigger a capture without replaying. Returns .rdc path."""
        return self.trigger_capture()

    def export_batch(self, rdc_paths: list, output_dir: Path) -> list:
        """Phase 2: batch-export a list of .rdc files to PNG.

        ``output_dir`` is accepted for API compatibility but not used --
        results are returned in memory and the caller writes them out.
        """
        return export_batch(
            rdc_paths, self.renderdoc_path, self.export_normal, self.capture_profile
        )

    # ── Frame capture + replay ───────────────────────────────────────────────

    def capture_frame(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Capture current frame: trigger + replay, return (rgb, depth)."""
        fd = self.capture_frame_ex()
        return fd.rgb, fd.depth

    def capture_frame_ex(self) -> FrameData:
        """Capture all available buffers (RGB, depth, normal) via RenderDoc."""
        t0 = time.monotonic()
        rdc_path = self.trigger_capture()
        logger.debug(f"[RDOC] Capture trigger took {time.monotonic() - t0:.3f}s -> {rdc_path}")
        if rdc_path is None:
            logger.warning("[RDOC] Capture trigger returned None")
            return FrameData()

        if self._use_native:
            try:
                rgb, depth = replay_native(
                    _bridge.ReplaySession, rdc_path,
                    self.ui_tail_fraction, self.ui_extra_keywords,
                )
                if rgb is not None or depth is not None:
                    return FrameData(rgb=rgb, depth=depth)
            except Exception as e:
                logger.warning(f"Native bridge replay failed: {e}")

        logger.debug("[RDOC] Trying exportframe replay fallback")
        try:
            rgb, depth, normal = replay_via_exportframe(
                rdc_path, self.capture_dir, self.renderdoc_path,
                self.export_normal, self.capture_profile,
            )
            logger.debug(
                f"[RDOC] Export result: rgb={'ok' if rgb is not None else 'None'}, "
                f"depth={'ok' if depth is not None else 'None'}, "
                f"normal={'ok' if normal is not None else 'None'}"
            )
            return FrameData(rgb=rgb, depth=depth, normal=normal)
        except Exception as e:
            logger.warning(f"RenderDoc replay failed: {e}")
            return FrameData()

    # ── Module discovery (optional, for renderdoc.pyd Python bindings) ──────

    @staticmethod
    def _find_renderdoc_dirs():
        """Locate renderdoc.pyd and its sibling DLL directory."""
        return find_renderdoc_dirs()
