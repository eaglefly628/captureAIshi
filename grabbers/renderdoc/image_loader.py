"""Load exported PNG/JPG/BMP/TGA images as uint8 numpy arrays.

The C++ ``exportframe`` command writes rgb.png / depth.png / normal.png
(and optionally ct_*.png color-target dumps); these helpers deserialize
them back into numpy. Pure functions, no RenderDocGrabber state.
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def load_rgb_image(
    directory: Path,
    capture_profile: Optional[dict] = None,
) -> Optional[np.ndarray]:
    """Load exported RGB image (png/jpg/bmp/tga) as uint8 (H, W, 3).

    If ``capture_profile["rgb_linear"]`` is True, applies linear-to-sRGB gamma
    correction after loading.  Use this when the C++ exported a Float SceneColor
    texture which was saved linearly (RenderDoc does NOT apply gamma on PNG save).
    """
    for ext in ("png", "jpg", "bmp", "tga"):
        rgb_file = directory / f"rgb.{ext}"
        if rgb_file.exists():
            try:
                from PIL import Image
                img = Image.open(str(rgb_file)).convert("RGB")
                arr = np.array(img, dtype=np.uint8)
                logger.debug(f"[RDOC] Loaded RGB: {arr.shape[1]}x{arr.shape[0]} from {rgb_file.name}")
            except ImportError:
                logger.warning("[RDOC] Pillow not installed -- trying imageio for RGB")
                try:
                    import imageio.v3 as iio
                    arr = iio.imread(str(rgb_file))
                    if arr.ndim == 3 and arr.shape[2] == 4:
                        arr = arr[:, :, :3]
                    arr = arr.astype(np.uint8)
                    logger.debug(f"[RDOC] Loaded RGB: {arr.shape[1]}x{arr.shape[0]} from {rgb_file.name}")
                except ImportError:
                    logger.error("[RDOC] Neither Pillow nor imageio installed -- cannot load RGB")
                    return None
            except Exception as e:
                logger.error(f"[RDOC] Failed to load RGB from {rgb_file}: {e}")
                return None

            profile = capture_profile or {}
            if profile.get("rgb_linear", False):
                arr = _linear_to_srgb(arr)
                logger.debug(f"[RDOC] Applied linear->sRGB gamma to RGB")
            return arr

    logger.debug("[RDOC] No RGB image found in export directory")
    return None


def _linear_to_srgb(arr: np.ndarray) -> np.ndarray:
    """Apply linear-to-sRGB gamma correction to a uint8 RGB array.

    RenderDoc saves Float SceneColor textures with no gamma applied.
    This maps the linear [0,255] values through the sRGB transfer function
    so the image looks correct on a standard gamma-corrected display.
    """
    f = arr.astype(np.float32) / 255.0
    # sRGB piecewise transfer function
    linear_mask = f <= 0.0031308
    f = np.where(linear_mask, f * 12.92, 1.055 * np.power(np.maximum(f, 1e-9), 1.0 / 2.4) - 0.055)
    return (np.clip(f, 0.0, 1.0) * 255.0).astype(np.uint8)


def load_depth_image(
    directory: Path,
    capture_profile: Optional[dict] = None,
) -> Optional[np.ndarray]:
    """Load raw depth EXR and normalize to uint8 grayscale (H, W).

    C++ ``exportframe`` writes ``depth.exr`` as raw 32-bit float; this
    function applies the per-game ``depth_range`` and ``depth_reversed_z``
    from ``capture_profile`` to produce a display-ready uint8 image.

    ``capture_profile`` fields honoured:
      - ``depth_range``: ``[bp, wp]`` for normalization. ``None`` = auto
        (1st/99th percentile of valid pixels).
      - ``depth_reversed_z``: ``True`` (UE5) = near(1.0)->white, far(0.0)->black.
        ``False`` (UE3/standard) = near(0.0)->white, far(1.0)->black.
        Default ``True``.

    Falls back to legacy ``depth.png`` if no EXR is found (used when
    renderdoccmd is older than the raw-EXR cutover).
    """
    profile = capture_profile or {}
    depth_range = profile.get("depth_range")
    reversed_z = profile.get("depth_reversed_z", True)

    exr_file = directory / "depth.exr"
    if exr_file.exists():
        raw = _read_exr_red(exr_file)
        if raw is None:
            return None
        return _normalize_depth(raw, depth_range, reversed_z)

    png_file = directory / "depth.png"
    if png_file.exists():
        logger.debug("[RDOC] Using legacy depth.png (renderdoccmd pre-EXR)")
        try:
            from PIL import Image
            return np.array(Image.open(str(png_file)).convert("L"), dtype=np.uint8)
        except Exception as e:
            logger.error(f"[RDOC] Failed to load legacy depth.png: {e}")
            return None

    logger.debug("[RDOC] No depth.exr or depth.png found in export directory")
    return None


def _read_exr_red(path: Path) -> Optional[np.ndarray]:
    """Read red channel of an EXR as float32 (H, W).

    Tries cv2 (most common), then imageio, then OpenEXR.
    Install any one: ``pip install opencv-python`` / ``pip install "imageio[freeimage]"`` / ``pip install OpenEXR``.
    """
    try:
        import cv2
        arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if arr is None:
            raise RuntimeError("cv2.imread returned None")
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        return arr.astype(np.float32)
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[RDOC] cv2 EXR read failed ({e}), trying imageio")

    try:
        import imageio.v3 as iio
        arr = iio.imread(str(path))
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        return arr.astype(np.float32)
    except Exception as e:
        logger.debug(f"[RDOC] imageio EXR read failed ({e}), trying OpenEXR")

    try:
        import OpenEXR
        import Imath
        f = OpenEXR.InputFile(str(path))
        header = f.header()
        dw = header["dataWindow"]
        w = dw.max.x - dw.min.x + 1
        h = dw.max.y - dw.min.y + 1
        pt = Imath.PixelType(Imath.PixelType.FLOAT)
        channel = "R" if "R" in header["channels"] else next(iter(header["channels"]))
        raw = f.channel(channel, pt)
        arr = np.frombuffer(raw, dtype=np.float32).reshape(h, w)
        return arr.copy()
    except Exception as e:
        logger.error(
            f"[RDOC] Cannot read EXR {path}: "
            f"install opencv-python, imageio[freeimage], or OpenEXR ({e})"
        )
        return None


def _normalize_depth(
    raw: np.ndarray,
    depth_range: Optional[list],
    reversed_z: bool,
) -> np.ndarray:
    """Normalize float depth [0,1] to uint8 grayscale.

    For ``reversed_z=True``, near=1.0 should render white, far=0.0 black.
    For ``reversed_z=False``, near=0.0 should render white, far=1.0 black.
    """
    if depth_range is not None and len(depth_range) == 2:
        bp, wp = float(depth_range[0]), float(depth_range[1])
    else:
        valid = raw[(raw > 0.0) & (raw < 1.0) & np.isfinite(raw)]
        if valid.size > 100:
            bp = float(np.percentile(valid, 1))
            wp = float(np.percentile(valid, 99))
            if wp - bp < 1e-9:
                bp, wp = 0.0, 1.0
        else:
            bp, wp = 0.0, 1.0
        logger.debug(f"[RDOC] depth auto-range: [{bp:.4f}, {wp:.4f}]")

    lo, hi = (bp, wp) if wp >= bp else (wp, bp)
    clipped = np.clip(raw, lo, hi)
    if hi - lo < 1e-9:
        return np.zeros(clipped.shape, dtype=np.uint8)

    if reversed_z:
        # near=1.0 -> white, far=0.0 -> black. Map wp (near) -> 1, bp (far) -> 0.
        norm = (clipped - bp) / (wp - bp) if wp > bp else (bp - clipped) / (bp - wp)
    else:
        # near=0.0 -> white, far=1.0 -> black. Map bp (near) -> 1, wp (far) -> 0.
        norm = (wp - clipped) / (wp - bp) if wp > bp else (clipped - wp) / (bp - wp)

    return (np.clip(norm, 0.0, 1.0) * 255.0).astype(np.uint8)


def load_normal_image(directory: Path) -> Optional[np.ndarray]:
    """Load normal map, auto-detecting from ct_*.png if normal.png absent.

    Auto-detection: scan all ct_*.png files, pick the one with highest
    pixel coverage (non-black pixels) and blue-channel dominance.
    Normal maps fill the viewport and have blue-dominant colors because
    surfaces facing up have normal.z > 0 -> B channel high.
    """
    normal_file = directory / "normal.png"
    if normal_file.exists():
        return load_image_as_rgb(normal_file)

    ct_files = sorted(directory.glob("ct_*.png"))
    if not ct_files:
        logger.debug("[RDOC] No ct_*.png files for normal auto-detect")
        return None

    try:
        from PIL import Image
    except ImportError:
        logger.warning("[RDOC] Pillow required for normal auto-detect")
        return None

    best_file = None
    best_score = -1.0

    for ct_file in ct_files:
        try:
            img = Image.open(str(ct_file)).convert("RGB")
            arr = np.array(img, dtype=np.uint8)

            # Subsample for speed: every 8th pixel
            flat = arr.reshape(-1, 3)[::8]
            total = len(flat)
            if total == 0:
                continue

            nonzero_mask = np.any(flat > 2, axis=1)
            coverage = nonzero_mask.sum() / total
            if nonzero_mask.sum() > 0:
                means = flat[nonzero_mask].mean(axis=0).astype(float)
                channel_sum = means.sum()
                blue_ratio = means[2] / channel_sum if channel_sum > 0 else 0
            else:
                blue_ratio = 0

            score = coverage
            if blue_ratio > 0.35:
                score += 1.0

            logger.debug(
                f"[RDOC] normal probe {ct_file.name}: "
                f"cov={coverage:.0%} blue={blue_ratio:.0%} score={score:.2f}"
            )

            if score > best_score:
                best_score = score
                best_file = ct_file

        except Exception as e:
            logger.debug(f"[RDOC] Failed to analyze {ct_file.name}: {e}")

    if best_file is None or best_score < 0.5:
        logger.info("[RDOC] Normal auto-detect: no suitable candidate found")
        return None

    logger.info(f"[RDOC] Normal auto-detected: {best_file.name} (score={best_score:.2f})")
    return load_image_as_rgb(best_file)


def load_image_as_rgb(filepath: Path) -> Optional[np.ndarray]:
    """Load any image file as uint8 RGB numpy array."""
    try:
        from PIL import Image
        img = Image.open(str(filepath)).convert("RGB")
        arr = np.array(img, dtype=np.uint8)
        logger.debug(f"[RDOC] Loaded image: {arr.shape[1]}x{arr.shape[0]} from {filepath.name}")
        return arr
    except ImportError:
        try:
            import imageio.v3 as iio
            arr = iio.imread(str(filepath))
            if arr.ndim == 3 and arr.shape[2] == 4:
                arr = arr[:, :, :3]
            return arr.astype(np.uint8)
        except ImportError:
            logger.error("[RDOC] Neither Pillow nor imageio installed")
            return None
    except Exception as e:
        logger.error(f"[RDOC] Failed to load {filepath}: {e}")
        return None
