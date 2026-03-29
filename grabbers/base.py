"""Abstract base class for frame grabbers."""

import logging
from abc import ABC, abstractmethod
from typing import Optional, Tuple
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class FrameGrabber(ABC):
    """Interface for capturing RGB and depth frames from a running game."""

    @abstractmethod
    def setup(self) -> None:
        """Initialize the grabber (e.g., start RenderDoc, configure hooks)."""

    @abstractmethod
    def teardown(self) -> None:
        """Clean up resources."""

    @abstractmethod
    def capture_frame(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Capture the current frame.

        Returns:
            (rgb, depth) tuple where:
              - rgb: HxWx3 uint8 numpy array, or None if unavailable.
              - depth: HxW float32 numpy array, or None if unavailable.
        """

    def save_frame(
        self,
        rgb: Optional[np.ndarray],
        depth: Optional[np.ndarray],
        output_dir: Path,
        frame_idx: int,
    ) -> None:
        """Save captured frame data to disk."""
        from PIL import Image

        output_dir.mkdir(parents=True, exist_ok=True)

        if rgb is not None:
            rgb_path = output_dir / f"rgb_{frame_idx:06d}.png"
            img = Image.fromarray(rgb)
            img.save(rgb_path)
            logger.debug(f"[SAVE] RGB frame {frame_idx}: {rgb_path} "
                         f"({rgb.shape[1]}x{rgb.shape[0]}, {rgb_path.stat().st_size} bytes)")
        else:
            logger.debug(f"[SAVE] RGB frame {frame_idx}: skipped (None)")

        if depth is not None:
            depth_png_path = output_dir / f"depth_{frame_idx:06d}.png"
            if depth.dtype == np.uint8:
                # Already normalized by C++ exportframe — save directly as 8-bit grayscale
                img = Image.fromarray(depth, mode="L")
            else:
                # Raw float depth — normalize to 8-bit for preview
                d_min, d_max = float(depth.min()), float(depth.max())
                if d_max - d_min > 1e-8:
                    depth_norm = (depth - d_min) / (d_max - d_min)
                else:
                    depth_norm = np.zeros_like(depth)
                depth_u8 = (depth_norm * 255).astype(np.uint8)
                img = Image.fromarray(depth_u8, mode="L")
            img.save(depth_png_path)
            logger.debug(f"[SAVE] Depth frame {frame_idx}: {depth.dtype}, "
                         f"{depth.shape[1]}x{depth.shape[0]}")
        else:
            logger.debug(f"[SAVE] Depth frame {frame_idx}: skipped (None)")

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.teardown()
        return False
