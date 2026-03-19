"""RenderDoc-based frame grabber.

Uses RenderDoc's Python replay API to capture RGB and depth buffers
from any DirectX/Vulkan/OpenGL application. Works with both UE5 and Unity.

Requirements:
  - RenderDoc installed with Python bindings (renderdoc module)
  - Game launched through renderdoccmd or with RenderDoc attached

Usage flow:
  1. Launch game via `renderdoccmd capture <game.exe>`
  2. Trigger capture at each pose (keyboard hook or API)
  3. Replay the .rdc file to extract RGB + depth textures
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from grabbers.base import FrameGrabber

logger = logging.getLogger(__name__)


class RenderDocGrabber(FrameGrabber):
    """Capture frames using RenderDoc's replay API."""

    def __init__(
        self,
        renderdoc_path: str = "renderdoccmd",
        capture_dir: str = "./captures",
        target_exe: Optional[str] = None,
        capture_key: str = "F12",
        auto_launch: bool = False,
        ui_hider=None,
    ):
        """
        Args:
            renderdoc_path: Path to renderdoccmd executable.
            capture_dir: Directory to store .rdc capture files.
            target_exe: Game executable path (for auto-launch).
            capture_key: Key to trigger capture.
            auto_launch: Whether to launch the game through RenderDoc.
            ui_hider: Optional RenderDocUIHider for filtering UI draw calls.
        """
        self.renderdoc_path = renderdoc_path
        self.capture_dir = Path(capture_dir)
        self.target_exe = target_exe
        self.capture_key = capture_key
        self.auto_launch = auto_launch
        self.ui_hider = ui_hider
        self._process = None
        self._capture_count = 0

    def setup(self) -> None:
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        if self.auto_launch and self.target_exe:
            logger.info(f"Launching {self.target_exe} via RenderDoc...")
            self._process = subprocess.Popen([
                self.renderdoc_path, "capture",
                "--opt-api-validation",
                "--opt-capture-callstacks",
                f"--opt-ref-all-resources",
                self.target_exe,
            ])
            time.sleep(5)  # Wait for game to start
            logger.info("Game launched with RenderDoc attached")
        else:
            logger.info(
                "RenderDoc grabber ready. Attach RenderDoc to your game manually "
                f"or launch with: {self.renderdoc_path} capture <game.exe>"
            )

    def teardown(self) -> None:
        if self._process:
            self._process.terminate()
            self._process = None
        logger.info(f"RenderDoc grabber: {self._capture_count} frames captured")

    def trigger_capture(self) -> Optional[Path]:
        """Trigger a frame capture in the attached game.

        Uses RenderDoc's in-application API if available, otherwise
        simulates the capture key press via platform input.

        Returns the path to the .rdc file if successful.
        """
        self._capture_count += 1
        rdc_path = self.capture_dir / f"frame_{self._capture_count:06d}.rdc"
        logger.info(f"Triggering capture #{self._capture_count}...")

        # Method 1: Try RenderDoc in-application API
        if self._trigger_via_api(rdc_path):
            return rdc_path

        # Method 2: Simulate capture key press
        if self._trigger_via_keypress():
            # Wait for the capture file to appear
            if self._wait_for_capture(rdc_path, timeout=5.0):
                return rdc_path

        logger.warning(f"Capture #{self._capture_count} may not have triggered")
        return rdc_path  # Return expected path; caller checks existence

    def _trigger_via_api(self, rdc_path: Path) -> bool:
        """Try triggering capture through RenderDoc's in-app API."""
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
            logger.debug("renderdoc module not available for API capture")
        except Exception as e:
            logger.debug(f"RenderDoc API capture failed: {e}")
        return False

    def _trigger_via_keypress(self) -> bool:
        """Simulate the capture key press to trigger RenderDoc."""
        import sys
        try:
            if sys.platform == "win32":
                import ctypes
                # Map common key names to virtual key codes
                vk_map = {
                    "F12": 0x7B, "F11": 0x7A, "F10": 0x79, "F9": 0x78,
                    "PRINT_SCREEN": 0x2C, "PRINTSCREEN": 0x2C,
                }
                vk = vk_map.get(self.capture_key.upper())
                if vk is None:
                    # Single character key
                    vk = ord(self.capture_key.upper())
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)  # key down
                time.sleep(0.05)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)  # key up
                return True
            else:
                # Linux/macOS: try xdotool
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
        # Also check for any new .rdc files in the capture dir
        existing = set(self.capture_dir.glob("*.rdc"))
        while time.time() - start < timeout:
            if rdc_path.exists():
                return True
            new_files = set(self.capture_dir.glob("*.rdc")) - existing
            if new_files:
                # Rename the newest capture to the expected path
                newest = max(new_files, key=lambda p: p.stat().st_mtime)
                newest.rename(rdc_path)
                return True
            time.sleep(0.2)
        return False

    def capture_frame(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Capture current frame via RenderDoc.

        This method triggers a capture and then replays it to extract
        the RGB backbuffer and depth buffer.
        """
        rdc_path = self.trigger_capture()
        if rdc_path is None:
            return None, None

        # Try to use RenderDoc Python API for replay
        try:
            rgb, depth = self._replay_capture(rdc_path)
            return rgb, depth
        except Exception as e:
            logger.warning(f"RenderDoc replay failed: {e}")
            logger.info("Falling back to waiting for manual capture export")
            return None, None

    def _replay_capture(self, rdc_path: Path):
        """Replay a .rdc capture file and extract textures.

        This requires the renderdoc Python module to be importable.
        """
        try:
            import renderdoc as rd
        except ImportError:
            logger.error(
                "renderdoc Python module not found. "
                "Install RenderDoc and add its Python bindings to PYTHONPATH. "
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
        # Find the final color output (backbuffer)
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
                    # UE5 uses reverse-Z float32 depth
                    arr = np.frombuffer(data, dtype=np.float32)
                    if len(arr) >= w * h:
                        depth = arr[:w * h].reshape(h, w)
                        return depth
        logger.warning("Depth buffer not found in capture")
        return None
