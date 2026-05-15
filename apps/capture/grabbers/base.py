"""Abstract base class for frame grabbers."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FrameData:
    """All buffers captured for a single frame.

    Extensible container — add new buffers as fields. Grabbers populate
    whichever buffers they can extract; the rest stay None.
    """
    rgb: Optional[np.ndarray] = None      # HxWx3 uint8
    depth: Optional[np.ndarray] = None    # HxW uint8 or float32
    normal: Optional[np.ndarray] = None   # HxWx3 uint8 (world-space normals)


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

    def capture_frame_ex(self) -> FrameData:
        """Capture all available buffers for the current frame.

        Default implementation wraps capture_frame(). Subclasses can override
        to provide additional buffers (normal, etc.).
        """
        rgb, depth = self.capture_frame()
        return FrameData(rgb=rgb, depth=depth)

    def save_frame(
        self,
        rgb: Optional[np.ndarray],
        depth: Optional[np.ndarray],
        output_dir: Path,
        frame_idx: int,
        *,
        base_name: str = "",
        normal: Optional[np.ndarray] = None,
    ) -> Dict[str, str]:
        """Save captured frame data to disk.

        Args:
            rgb: RGB image array.
            depth: Depth image array.
            output_dir: Directory to save into.
            frame_idx: Frame index for filename fallback.
            base_name: Base filename (e.g. "scene_20260306143818065_cone0").
                       If empty, falls back to frame_idx numbering.
            normal: Optional normal map array.

        Returns:
            Dict mapping buffer names to saved filenames:
            {"rgb": "scene_cone0.png", "depth": "scene_cone0_d.png", ...}
        """
        from PIL import Image

        output_dir.mkdir(parents=True, exist_ok=True)
        saved = {}

        if base_name:
            rgb_name = f"{base_name}.png"
            depth_name = f"{base_name}_d.png"
            normal_name = f"{base_name}_n.png"
        else:
            rgb_name = f"rgb_{frame_idx:06d}.png"
            depth_name = f"depth_{frame_idx:06d}.png"
            normal_name = f"normal_{frame_idx:06d}.png"

        if rgb is not None:
            rgb_path = output_dir / rgb_name
            img = Image.fromarray(rgb)
            img.save(rgb_path)
            saved["rgb"] = rgb_name
            logger.debug(f"[SAVE] RGB frame {frame_idx}: {rgb_path} "
                         f"({rgb.shape[1]}x{rgb.shape[0]}, {rgb_path.stat().st_size} bytes)")
        else:
            logger.debug(f"[SAVE] RGB frame {frame_idx}: skipped (None)")

        if depth is not None:
            depth_path = output_dir / depth_name
            if depth.dtype == np.uint8:
                img = Image.fromarray(depth, mode="L")
            else:
                d_min, d_max = float(depth.min()), float(depth.max())
                if d_max - d_min > 1e-8:
                    depth_norm = (depth - d_min) / (d_max - d_min)
                else:
                    depth_norm = np.zeros_like(depth)
                depth_u8 = (depth_norm * 255).astype(np.uint8)
                img = Image.fromarray(depth_u8, mode="L")
            img.save(depth_path)
            saved["depth"] = depth_name
            logger.debug(f"[SAVE] Depth frame {frame_idx}: {depth.dtype}, "
                         f"{depth.shape[1]}x{depth.shape[0]}")
        else:
            logger.debug(f"[SAVE] Depth frame {frame_idx}: skipped (None)")

        if normal is not None:
            normal_path = output_dir / normal_name
            img = Image.fromarray(normal)
            img.save(normal_path)
            saved["normal"] = normal_name
            logger.debug(f"[SAVE] Normal frame {frame_idx}: "
                         f"{normal.shape[1]}x{normal.shape[0]}")

        return saved

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.teardown()
        return False
