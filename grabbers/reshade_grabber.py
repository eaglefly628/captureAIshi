"""ReShade-based frame grabber (Path B injection vehicle).

Consumes the BMP/PNG + EXR triplets written by captureAIshi_bridge.addon
(embedded frame_capture subsystem) when the game runs under the dxgi.dll
proxy. The addon is timer-driven: it writes a new triplet every ~33ms
(configurable via FC_TargetFPS in unicap.ini). This grabber polls the
output directory for the latest triplet that postdates the previous capture
and returns its arrays.

For trajectory capture where the camera holds still ~33ms+ at each pose
this is sufficient; precise per-pose capture is a Phase 2 addition (would
add an `__fc_capture_now` TCP command on the bridge channel).

Output filename convention from frame_capture.cpp:
  <exe_basename> YYYY-MM-DD HH-MM-SS mmm BackBuffer.{bmp,png}
  <exe_basename> YYYY-MM-DD HH-MM-SS mmm DepthBuffer.exr
  <exe_basename> YYYY-MM-DD HH-MM-SS mmm NormalBuffer.exr  (only when FC_ExportNormal=1)

The "<exe_basename> <ts> " prefix groups a triplet -- we match by prefix.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from grabbers.base import FrameData, FrameGrabber

logger = logging.getLogger(__name__)


class ReShadeGrabber(FrameGrabber):
    """Grab frames produced by the ReShade addon (Path B vehicle).

    Args:
        output_dir: directory the addon writes frames into (must match the
            path written by setup() into <game_dir>/fc_output_dir.txt).
        game_dir: directory containing the game exe and the deployed
            captureAIshi_bridge.addon + dxgi.dll proxy. Used for the
            sidecar protocol (fc_output_dir.txt etc.).
        poll_timeout_s: how long capture_frame() waits for a new triplet
            before returning (None, None). Default 5s.
        poll_interval_s: directory poll interval. Default 50ms (~20Hz).
    """

    def __init__(
        self,
        output_dir: str | Path,
        game_dir: str | Path,
        *,
        poll_timeout_s: float = 5.0,
        poll_interval_s: float = 0.05,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.game_dir = Path(game_dir)
        self.poll_timeout_s = poll_timeout_s
        self.poll_interval_s = poll_interval_s
        self._last_prefix: Optional[str] = None

    # ── lifecycle ─────────────────────────────────────────────────────

    def setup(self) -> None:
        """Prepare the addon to write into our output dir.

        Does NOT deploy binaries (caller is expected to have placed
        dxgi.dll + captureAIshi_bridge.addon + shaders/ next to the game
        exe). Phase 1 keeps deployment as a separate step; a deploy script
        will land in scripts/ as part of Phase 2 work.
        """
        if not self.game_dir.exists():
            raise FileNotFoundError(
                f"[ReShadeGrabber] game_dir not found: {self.game_dir}")

        addon_path = self.game_dir / "captureAIshi_bridge.addon"
        if not addon_path.exists():
            logger.warning(
                "[ReShadeGrabber] %s missing -- did you deploy the addon "
                "+ dxgi.dll proxy to the game directory? Continuing in "
                "case the user is about to do so manually.", addon_path)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Sidecar: tell the addon where to write frames.
        sidecar = self.game_dir / "fc_output_dir.txt"
        sidecar.write_text(str(self.output_dir.resolve()), encoding="utf-8")
        logger.info(
            "[ReShadeGrabber] sidecar -> %s (output_dir=%s)",
            sidecar, self.output_dir)

        # Latch baseline so capture_frame() ignores any pre-existing files.
        self._last_prefix = self._latest_prefix()
        logger.info(
            "[ReShadeGrabber] baseline prefix=%r", self._last_prefix)

    def teardown(self) -> None:
        sidecar = self.game_dir / "fc_output_dir.txt"
        try:
            if sidecar.exists():
                sidecar.unlink()
                logger.info("[ReShadeGrabber] removed sidecar %s", sidecar)
        except OSError as exc:
            logger.warning("[ReShadeGrabber] sidecar cleanup: %s", exc)

    # ── capture ────────────────────────────────────────────────────────

    def capture_frame(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        data = self.capture_frame_ex()
        return data.rgb, data.depth

    def capture_frame_ex(self) -> FrameData:
        deadline = time.monotonic() + self.poll_timeout_s
        prefix: Optional[str] = None
        while time.monotonic() < deadline:
            prefix = self._latest_prefix()
            if prefix and prefix != self._last_prefix:
                break
            time.sleep(self.poll_interval_s)
        else:
            logger.warning(
                "[ReShadeGrabber] no new frame within %.1fs (last=%r)",
                self.poll_timeout_s, self._last_prefix)
            return FrameData()

        self._last_prefix = prefix
        return self._load_triplet(prefix)

    # ── internals ──────────────────────────────────────────────────────

    _COLOR_SUFFIXES = (" BackBuffer.png", " BackBuffer.bmp")
    _DEPTH_SUFFIX   = " DepthBuffer.exr"
    _NORMAL_SUFFIX  = " NormalBuffer.exr"

    def _latest_prefix(self) -> Optional[str]:
        """Return the prefix of the most recent triplet (newest color file).

        Prefix = filename minus the color suffix; depth/normal share it.
        """
        if not self.output_dir.exists():
            return None
        newest_mtime = -1.0
        newest_prefix: Optional[str] = None
        for p in self.output_dir.iterdir():
            if not p.is_file():
                continue
            name = p.name
            for suf in self._COLOR_SUFFIXES:
                if name.endswith(suf):
                    mtime = p.stat().st_mtime
                    if mtime > newest_mtime:
                        newest_mtime = mtime
                        newest_prefix = name[: -len(suf)]
                    break
        return newest_prefix

    def _load_triplet(self, prefix: str) -> FrameData:
        rgb = self._load_color(prefix)
        depth = self._load_exr(self.output_dir / f"{prefix}{self._DEPTH_SUFFIX}")
        normal = self._load_exr(self.output_dir / f"{prefix}{self._NORMAL_SUFFIX}")
        return FrameData(rgb=rgb, depth=depth, normal=normal)

    def _load_color(self, prefix: str) -> Optional[np.ndarray]:
        from PIL import Image
        for suf in self._COLOR_SUFFIXES:
            p = self.output_dir / f"{prefix}{suf}"
            if p.exists():
                img = Image.open(p).convert("RGB")
                return np.asarray(img)
        return None

    def _load_exr(self, path: Path) -> Optional[np.ndarray]:
        if not path.exists():
            return None
        try:
            import cv2
        except ImportError:
            logger.warning(
                "[ReShadeGrabber] cv2 not installed; cannot load %s", path)
            return None
        # OpenCV needs IMREAD_UNCHANGED to keep float EXR intact.
        flags = cv2.IMREAD_UNCHANGED
        arr = cv2.imread(str(path), flags)
        if arr is None:
            logger.warning("[ReShadeGrabber] cv2 failed to load %s", path)
            return None
        # tinyexr writes BGR -> swap to RGB for normal; depth is single-channel.
        if arr.ndim == 3 and arr.shape[2] >= 3:
            arr = arr[..., ::-1]
        return arr
