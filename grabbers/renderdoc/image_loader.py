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

    Applies linear->sRGB gamma if ``rgb.meta`` reports ``source=float_linear``
    (C++ picked a Float HDR SceneColor), OR if ``capture_profile["rgb_linear"]``
    is True. sRGB sources (UNorm pre-UI composite, SwapBuffer) are loaded as-is.
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

            # Auto-detect gamma via sidecar (written by C++ exportframe)
            needs_gamma = False
            meta_file = directory / "rgb.meta"
            if meta_file.exists():
                try:
                    for line in meta_file.read_text().splitlines():
                        if line.strip() == "source=float_linear":
                            needs_gamma = True
                            break
                except Exception:
                    pass
            # Profile override (wins over auto-detect)
            profile = capture_profile or {}
            if "rgb_linear" in profile:
                needs_gamma = bool(profile["rgb_linear"])
            if needs_gamma:
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
    """Load depth image as uint8 grayscale (H, W).

    C++ ``exportframe`` writes ``depth.png`` (normalized grayscale, percentile
    range, far=white convention). If ``depth.exr`` is present instead (future
    upgrade path), this function normalizes it using ``capture_profile``.
    """
    png_file = directory / "depth.png"
    if png_file.exists():
        try:
            from PIL import Image
            arr = np.array(Image.open(str(png_file)).convert("L"), dtype=np.uint8)
            logger.debug(f"[RDOC] Loaded depth: {arr.shape[1]}x{arr.shape[0]}")
            return arr
        except Exception as e:
            logger.error(f"[RDOC] Failed to load depth.png: {e}")
            return None

    exr_file = directory / "depth.exr"
    if exr_file.exists():
        profile = capture_profile or {}
        raw = _read_exr_red(exr_file)
        if raw is None:
            return None
        return _normalize_depth(
            raw,
            profile.get("depth_range"),
            profile.get("depth_reversed_z", True),
            curve=str(profile.get("depth_curve", "linear")),
        )

    logger.debug("[RDOC] No depth.png or depth.exr found in export directory")
    return None


def _read_exr_red(path: Path) -> Optional[np.ndarray]:
    """Read red channel of an EXR as float32 (H, W).

    Tries cv2 (most common), then imageio, then OpenEXR.
    Install any one: ``pip install opencv-python`` / ``pip install "imageio[freeimage]"`` / ``pip install OpenEXR``.

    Note: cv2 disables EXR by default (CVE-driven policy in OpenCV 4.5+).
    Set ``OPENCV_IO_ENABLE_OPENEXR=1`` BEFORE the first ``import cv2``.
    The opt-in is wired into the app entry points (web_ui.py /
    desktop_app.py); we set it again here for direct callers /
    main.py CLI to be safe, but if ``cv2.imread`` still returns None
    on a .exr the env var was probably set after cv2 was already
    imported elsewhere -- in that case use imageio[freeimage] or
    OpenEXR instead.
    """
    import os as _os
    _os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    try:
        import cv2
        arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if arr is None:
            raise RuntimeError(
                "cv2.imread returned None (opencv-python EXR support "
                "is disabled unless OPENCV_IO_ENABLE_OPENEXR=1 is set "
                "before the first 'import cv2')"
            )
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


def _read_exr_rgb(path: Path) -> Optional[np.ndarray]:
    """Read RGB channels of an EXR as float32 (H, W, 3).

    Mirror of ``_read_exr_red``, but returns the full RGB triple instead of
    just the red plane.  Used to visualise the ReShade addon's
    ``NormalBuffer.exr`` (RGB float, output of ``DepthToAddon.fx`` which
    already remaps the world-space normal to [0, 1] before storage).

    cv2 / imageio / OpenEXR fallback chain, same as ``_read_exr_red``.
    cv2 returns BGR; we swap to RGB before returning.
    """
    import os as _os
    _os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    try:
        import cv2
        arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if arr is None:
            raise RuntimeError(
                "cv2.imread returned None (opencv-python EXR support "
                "is disabled unless OPENCV_IO_ENABLE_OPENEXR=1 is set "
                "before the first 'import cv2')"
            )
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        elif arr.shape[2] >= 3:
            arr = arr[:, :, :3]
            arr = arr[:, :, ::-1]  # BGR -> RGB
        else:
            arr = np.concatenate(
                [arr] + [arr[:, :, :1]] * (3 - arr.shape[2]), axis=-1)
        return arr.astype(np.float32)
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[RDOC] cv2 EXR RGB read failed ({e}), trying imageio")

    try:
        import imageio.v3 as iio
        arr = iio.imread(str(path))
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        elif arr.shape[2] >= 3:
            arr = arr[:, :, :3]
        else:
            arr = np.concatenate(
                [arr] + [arr[:, :, :1]] * (3 - arr.shape[2]), axis=-1)
        return arr.astype(np.float32)
    except Exception as e:
        logger.debug(
            f"[RDOC] imageio EXR RGB read failed ({e}), trying OpenEXR")

    try:
        import OpenEXR
        import Imath
        f = OpenEXR.InputFile(str(path))
        header = f.header()
        dw = header["dataWindow"]
        w = dw.max.x - dw.min.x + 1
        h = dw.max.y - dw.min.y + 1
        pt = Imath.PixelType(Imath.PixelType.FLOAT)
        channels = header["channels"]
        planes = []
        for name in ("R", "G", "B"):
            if name in channels:
                raw = f.channel(name, pt)
                planes.append(
                    np.frombuffer(raw, dtype=np.float32).reshape(h, w))
            else:
                planes.append(np.zeros((h, w), dtype=np.float32))
        return np.stack(planes, axis=-1).copy()
    except Exception as e:
        logger.error(
            f"[RDOC] Cannot read EXR (RGB) {path}: "
            f"install opencv-python, imageio[freeimage], or OpenEXR ({e})"
        )
        return None


def _normalize_depth(
    raw: np.ndarray,
    depth_range: Optional[list],
    reversed_z: bool,
    curve: str = "linear",
) -> np.ndarray:
    """Normalize float depth [0,1] to uint8 grayscale.

    For ``reversed_z=True``, near=1.0 should render white, far=0.0 black.
    For ``reversed_z=False``, near=0.0 should render white, far=1.0 black.

    ``curve`` reshapes the depth distribution **before** percentile +
    stretch, which is what actually expands a tight mid-range cluster.
    NDC depth is already 1/z-like, so outdoor scenes (Batman / Gotham)
    pile mid-distance city pixels right next to the sky in raw depth
    space; a linear stretch can't separate them. Pre-curving fixes the
    distribution itself.

    - ``"linear"`` (default): legacy behaviour, raw -> percentile ->
      stretch.
    - ``"log"``: apply ``-log(raw + eps)`` first so far/sky values
      (raw close to 0 or 1) and near values get spread out
      logarithmically. Best for wide-range outdoor scenes; turns the
      washed-out city band into a real mid-gray.
    - ``"gamma"``: apply a fixed gamma to ``raw`` before percentile.
      Milder than log; useful when log overshoots.

    PNG depth is for human preview only; raw float depth is preserved
    in the EXR side-by-side, so any of these curves is safe wrt AI
    training pipelines reading EXR.
    """
    work = raw
    c = (curve or "linear").lower()
    eps = 1e-6
    if c == "log":
        # log(x + eps) preserves the monotonic ordering of the raw
        # depth (so reversed_z polarity stays correct) but spreads
        # values exponentially clustered near 0 or 1 across a much
        # wider range. After log, a [0.001, 0.05] city band that
        # linearly looks like a single 'near sky' tone becomes a real
        # mid-gray separated from both sky and Batman.
        work = np.log(np.clip(raw, eps, 1.0))
    elif c == "gamma":
        # Display-style gamma. 0.45 is mild; 2.2 the inverse direction.
        # We pick 0.45 so values near 0 expand and values near 1 compress
        # (matches log's intent but lighter).
        work = np.power(np.clip(raw, eps, 1.0), 0.45)
    elif c != "linear":
        logger.warning(f"[RDOC] unknown depth curve '{curve}', using linear")

    if depth_range is not None and len(depth_range) == 2:
        bp, wp = float(depth_range[0]), float(depth_range[1])
    else:
        # Validity mask: still use raw for the >0 / <1 filter so we
        # match the original semantics (skip exact-clear pixels), but
        # take percentiles on ``work`` (the curved values) so the
        # stretch is in curved space.
        mask = (raw > 0.0) & (raw < 1.0) & np.isfinite(raw) & np.isfinite(work)
        valid = work[mask]
        if valid.size > 100:
            bp = float(np.percentile(valid, 1))
            wp = float(np.percentile(valid, 99))
            if wp - bp < 1e-9:
                bp, wp = float(work.min()), float(work.max())
                if wp - bp < 1e-9:
                    bp, wp = 0.0, 1.0
        else:
            bp, wp = 0.0, 1.0
        logger.debug(f"[RDOC] depth auto-range ({c}): [{bp:.4f}, {wp:.4f}]")

    lo, hi = (bp, wp) if wp >= bp else (wp, bp)
    clipped = np.clip(work, lo, hi)
    if hi - lo < 1e-9:
        return np.zeros(clipped.shape, dtype=np.uint8)

    if reversed_z:
        norm = (clipped - bp) / (wp - bp) if wp > bp else (bp - clipped) / (bp - wp)
    else:
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
