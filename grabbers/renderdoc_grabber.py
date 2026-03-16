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
    ):
        """
        Args:
            renderdoc_path: Path to renderdoccmd executable.
            capture_dir: Directory to store .rdc capture files.
            target_exe: Game executable path (for auto-launch).
            capture_key: Key to trigger capture.
            auto_launch: Whether to launch the game through RenderDoc.
        """
        self.renderdoc_path = renderdoc_path
        self.capture_dir = Path(capture_dir)
        self.target_exe = target_exe
        self.capture_key = capture_key
        self.auto_launch = auto_launch
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

        Returns the path to the .rdc file if successful.
        """
        self._capture_count += 1
        rdc_path = self.capture_dir / f"frame_{self._capture_count:06d}.rdc"
        logger.info(f"Triggering capture #{self._capture_count}...")
        # In practice, this would use RenderDoc's API or send a capture key
        # For now, return the expected path
        return rdc_path

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
            rgb = self._extract_backbuffer(controller, rd)
            depth = self._extract_depth(controller, rd)
            return rgb, depth
        finally:
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
