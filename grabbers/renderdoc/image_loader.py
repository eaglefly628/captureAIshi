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


def load_rgb_image(directory: Path) -> Optional[np.ndarray]:
    """Load exported RGB image (png/jpg/bmp/tga) as uint8 (H, W, 3)."""
    for ext in ("png", "jpg", "bmp", "tga"):
        rgb_file = directory / f"rgb.{ext}"
        if rgb_file.exists():
            try:
                from PIL import Image
                img = Image.open(str(rgb_file)).convert("RGB")
                arr = np.array(img, dtype=np.uint8)
                logger.debug(f"[RDOC] Loaded RGB: {arr.shape[1]}x{arr.shape[0]} from {rgb_file.name}")
                return arr
            except ImportError:
                logger.warning("[RDOC] Pillow not installed -- trying imageio for RGB")
                try:
                    import imageio.v3 as iio
                    arr = iio.imread(str(rgb_file))
                    if arr.ndim == 3 and arr.shape[2] == 4:
                        arr = arr[:, :, :3]
                    logger.debug(f"[RDOC] Loaded RGB: {arr.shape[1]}x{arr.shape[0]} from {rgb_file.name}")
                    return arr
                except ImportError:
                    logger.error("[RDOC] Neither Pillow nor imageio installed -- cannot load RGB")
                    return None
            except Exception as e:
                logger.error(f"[RDOC] Failed to load RGB from {rgb_file}: {e}")
                return None
    logger.debug("[RDOC] No RGB image found in export directory")
    return None


def load_depth_image(directory: Path) -> Optional[np.ndarray]:
    """Load exported depth PNG as uint8 grayscale (H, W).

    The C++ exportframe already normalizes depth (percentile black/white
    point mapping + reversed-Z inversion) so the PNG is ready to use.
    """
    depth_file = directory / "depth.png"
    if not depth_file.exists():
        logger.debug("[RDOC] No depth.png found in export directory")
        return None

    try:
        from PIL import Image
        img = Image.open(str(depth_file)).convert("L")
        arr = np.array(img, dtype=np.uint8)
        logger.debug(f"[RDOC] Loaded depth: {arr.shape[1]}x{arr.shape[0]} from depth.png")
        return arr
    except ImportError:
        logger.warning("[RDOC] Pillow not installed -- trying imageio for depth")
        try:
            import imageio.v3 as iio
            arr = iio.imread(str(depth_file))
            if arr.ndim == 3:
                arr = arr[:, :, 0]
            logger.debug(f"[RDOC] Loaded depth: {arr.shape[1]}x{arr.shape[0]} from depth.png (imageio)")
            return arr.astype(np.uint8)
        except ImportError:
            logger.error("[RDOC] Neither Pillow nor imageio installed -- cannot load depth")
            return None
    except Exception as e:
        logger.error(f"[RDOC] Failed to load depth from {depth_file}: {e}")
        return None


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
