"""Screenshot-based frame grabber (fallback).

Uses system-level screenshot capture for RGB. For depth, optionally
reads from ReShade depth buffer export or a shared file.

This is simpler than RenderDoc but has limitations:
  - Captures the full screen (may include UI overlay)
  - Depth precision depends on ReShade configuration
  - Requires the game window to be in focus
"""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from grabbers.base import FrameGrabber

logger = logging.getLogger(__name__)


class ScreenshotGrabber(FrameGrabber):
    """Capture frames via system screenshots + optional ReShade depth."""

    def __init__(
        self,
        screenshot_dir: str = "./screenshots",
        depth_dir: Optional[str] = None,
        capture_delay: float = 0.2,
        use_reshade_depth: bool = False,
    ):
        """
        Args:
            screenshot_dir: Directory to save/read screenshots.
            depth_dir: Directory where ReShade exports depth maps.
            capture_delay: Seconds to wait after triggering screenshot.
            use_reshade_depth: Whether to look for ReShade depth exports.
        """
        self.screenshot_dir = Path(screenshot_dir)
        self.depth_dir = Path(depth_dir) if depth_dir else None
        self.capture_delay = capture_delay
        self.use_reshade_depth = use_reshade_depth
        self._frame_count = 0

    def setup(self) -> None:
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        if self.depth_dir:
            self.depth_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Screenshot grabber ready")

    def teardown(self) -> None:
        logger.info(f"Screenshot grabber: {self._frame_count} frames captured")

    def capture_frame(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        self._frame_count += 1

        rgb = self._capture_screenshot()
        depth = None
        if self.use_reshade_depth and self.depth_dir:
            depth = self._read_reshade_depth()

        return rgb, depth

    def _capture_screenshot(self) -> Optional[np.ndarray]:
        """Take a screenshot of the active window."""
        try:
            from PIL import ImageGrab
            time.sleep(self.capture_delay)
            img = ImageGrab.grab()
            return np.array(img)
        except ImportError:
            logger.warning("PIL.ImageGrab not available (Linux?). Trying mss...")
        except Exception as e:
            logger.warning(f"ImageGrab failed: {e}")

        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # Primary monitor
                screenshot = sct.grab(monitor)
                arr = np.array(screenshot)
                return arr[:, :, :3]  # BGR to RGB handled by caller if needed
        except ImportError:
            logger.error("Neither PIL.ImageGrab nor mss available for screenshots")

        return None

    def _read_reshade_depth(self) -> Optional[np.ndarray]:
        """Read the latest depth map exported by ReShade."""
        if not self.depth_dir or not self.depth_dir.exists():
            return None

        # ReShade exports depth as PNG or raw binary
        depth_files = sorted(self.depth_dir.glob("*.png"), key=lambda p: p.stat().st_mtime)
        if not depth_files:
            depth_files = sorted(self.depth_dir.glob("*.raw"), key=lambda p: p.stat().st_mtime)

        if not depth_files:
            return None

        latest = depth_files[-1]
        try:
            if latest.suffix == ".png":
                from PIL import Image
                img = Image.open(latest)
                return np.array(img, dtype=np.float32) / 65535.0
            elif latest.suffix == ".raw":
                data = latest.read_bytes()
                return np.frombuffer(data, dtype=np.float32)
        except Exception as e:
            logger.warning(f"Failed to read depth from {latest}: {e}")

        return None
