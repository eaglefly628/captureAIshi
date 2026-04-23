"""Replay / export .rdc files to RGB / depth / normal PNGs via renderdoccmd.

These wrap the C++ ``exportframe`` command -- the RenderDoc Python module
crashes with ACCESS_VIOLATION when loaded outside qrenderdoc, so we use
our in-house subcommand instead.
"""

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import numpy as np

from grabbers.renderdoc.image_loader import (
    load_depth_image,
    load_normal_image,
    load_rgb_image,
)
from grabbers.renderdoc.paths import resolve_renderdoccmd

logger = logging.getLogger(__name__)


def capture_export_args(capture_profile: dict) -> list:
    """Build per-game exportframe CLI flags from ``capture_profile``."""
    args = []
    rgb_index = capture_profile.get("rgb_index", -1)
    if rgb_index is not None and rgb_index >= 0:
        args += ["--rgb-index", str(rgb_index)]
    normal_index = capture_profile.get("normal_index", -1)
    if normal_index is not None and normal_index >= 0:
        args += ["--normal-index", str(normal_index)]
    depth_index = capture_profile.get("depth_index", -1)
    if depth_index is not None and depth_index >= 0:
        args += ["--depth-index", str(depth_index)]
    if not capture_profile.get("depth_reversed_z", True):
        args.append("--no-reverse-depth")
    return args


def replay_via_exportframe(
    rdc_path: Path,
    capture_dir: Path,
    renderdoc_path: str,
    export_normal: bool,
    capture_profile: dict,
):
    """Replay a single .rdc via renderdoccmd exportframe.

    The renderdoc.pyd Python module crashes with ACCESS_VIOLATION when
    loaded outside of qrenderdoc, so this uses the custom `exportframe`
    subcommand compiled into renderdoccmd. It saves:
      - rgb.png    (backbuffer, uint8)
      - depth.exr  (depth target, raw 32-bit float -- Python normalizes)
      - normal.png (world-space normals, auto-detected GBufferA)

    Returns ``(rgb, depth, normal)`` as numpy arrays (any may be None).
    """
    if not rdc_path.exists():
        logger.warning(f"[RDOC] Capture file does not exist: {rdc_path}")
        return None, None, None

    try:
        rdoc_cmd = resolve_renderdoccmd(renderdoc_path)
    except FileNotFoundError as e:
        logger.error(f"[RDOC] {e}")
        return None, None, None

    replay_out = capture_dir / f"_replay_{rdc_path.stem}"
    replay_out.mkdir(parents=True, exist_ok=True)

    cmd = [
        rdoc_cmd, "exportframe",
        str(rdc_path),
        "--out", str(replay_out),
        "--format", "png",
    ]
    if not export_normal:
        cmd.append("--no-normal")
    cmd += capture_export_args(capture_profile)
    logger.debug(f"[RDOC] Export command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        stderr = result.stderr.decode("utf-8", errors="replace").strip()

        if stdout:
            for line in stdout.splitlines():
                logger.info(f"[RDOC export] {line}")
        if stderr:
            for line in stderr.splitlines():
                logger.warning(f"[RDOC export stderr] {line}")

        if result.returncode != 0:
            if result.returncode == 3:
                logger.warning("[RDOC] exportframe found neither RGB nor depth in capture")
            else:
                logger.error(f"[RDOC] exportframe exited with code {result.returncode}")
                return None, None, None

    except subprocess.TimeoutExpired:
        logger.error("[RDOC] exportframe timed out (60s)")
        return None, None, None
    except Exception as e:
        logger.error(f"[RDOC] Failed to run exportframe: {e}")
        return None, None, None

    rgb = load_rgb_image(replay_out, capture_profile)
    depth = load_depth_image(replay_out, capture_profile)
    normal = load_normal_image(replay_out)

    for f in replay_out.iterdir():
        try:
            f.unlink()
        except OSError:
            pass
    try:
        replay_out.rmdir()
    except OSError:
        pass

    return rgb, depth, normal


def export_batch(
    rdc_paths: list,
    renderdoc_path: str,
    export_normal: bool,
    capture_profile: dict,
) -> list:
    """Phase 2 of two-phase capture: batch-export a list of .rdc to PNG.

    Calls renderdoccmd exportframe with all files at once (single process).
    Returns ``[(rgb, depth, normal), ...]`` per frame; failed frames get
    ``(None, None, None)``.
    """
    if not rdc_paths:
        return []

    valid_paths = [p for p in rdc_paths if p is not None and p.exists()]
    if not valid_paths:
        logger.warning("[RDOC] No valid .rdc files to export")
        return [(None, None, None)] * len(rdc_paths)

    try:
        rdoc_cmd = resolve_renderdoccmd(renderdoc_path)
    except FileNotFoundError as e:
        logger.error(f"[RDOC] {e}")
        return [(None, None, None)] * len(rdc_paths)

    export_out = Path(tempfile.mkdtemp(prefix="captureai_export_"))
    logger.info(f"[RDOC] Batch export temp dir: {export_out}")

    cmd = [
        rdoc_cmd, "exportframe",
        "--out", str(export_out),
        "--format", "png",
    ]
    if not export_normal:
        cmd.append("--no-normal")
    cmd += capture_export_args(capture_profile)
    cmd += [str(p) for p in valid_paths]

    logger.info(f"[RDOC] Batch exporting {len(valid_paths)} captures...")
    logger.debug(f"[RDOC] Export command: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        timeout_s = 60 * len(valid_paths)
        t_start = time.monotonic()
        export_count = 0

        for raw_line in iter(proc.stdout.readline, b""):
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            if "Exporting" in line or "exported" in line.lower() or "processing" in line.lower():
                export_count += 1
                logger.info(f"[RDOC] Export {export_count}/{len(valid_paths)}: {line}")
            else:
                logger.info(f"[RDOC export] {line}")
            if time.monotonic() - t_start > timeout_s:
                proc.kill()
                logger.error("[RDOC] Batch export timed out")
                return [(None, None, None)] * len(rdc_paths)

        proc.wait()
        if proc.returncode != 0:
            logger.error(f"[RDOC] Batch export exited with code {proc.returncode}")
    except Exception as e:
        logger.error(f"[RDOC] Batch export failed: {e}")
        return [(None, None, None)] * len(rdc_paths)

    # Collect results: for multi-file input, exportframe creates subdirs named by stem.
    results = []
    for rdc_path in rdc_paths:
        if rdc_path is None or not rdc_path.exists():
            results.append((None, None, None))
            continue

        subdir = export_out / rdc_path.stem if len(valid_paths) > 1 else export_out

        logger.debug(f"[RDOC batch] Loading from {subdir} (exists={subdir.exists()})")
        if subdir.exists():
            logger.debug(f"[RDOC batch] Files: {[f.name for f in subdir.iterdir()]}")

        rgb = load_rgb_image(subdir, capture_profile)
        depth = load_depth_image(subdir, capture_profile)
        normal = load_normal_image(subdir)

        logger.debug(
            f"[RDOC batch] Loaded: rgb={'ok' if rgb is not None else 'None'}, "
            f"depth={'ok' if depth is not None else 'None'}, "
            f"normal={'ok' if normal is not None else 'None'}"
        )
        results.append((rgb, depth, normal))

        if subdir.exists() and subdir != export_out:
            for f in subdir.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass
            try:
                subdir.rmdir()
            except OSError:
                pass

    try:
        shutil.rmtree(str(export_out), ignore_errors=True)
    except OSError:
        pass

    logger.info(f"[RDOC] Batch export complete: {len(results)} frames")
    return results


def replay_native(session_ctor, rdc_path: Path, ui_tail_fraction: float, ui_extra_keywords: list):
    """Replay using the native C++ bridge's ReplaySession.

    ``session_ctor`` is ``_bridge.ReplaySession`` (passed in so we don't
    hard-depend on capture_bridge at import time). Returns ``(rgb, depth)``.
    """
    session = session_ctor()
    if not session.open(str(rdc_path)):
        logger.warning(f"Native bridge: failed to open {rdc_path}")
        return None, None

    try:
        excluded: set = set()
        if ui_tail_fraction > 0:
            excluded = session.classify_ui_events(ui_tail_fraction, ui_extra_keywords)
            if excluded:
                logger.debug(f"Native bridge: excluding {len(excluded)} UI draw calls")

        fb = session.extract_frame(0, excluded)
        rgb = fb.rgb if fb.has_rgb else None
        depth = fb.depth if fb.has_depth else None

        if fb.has_depth:
            fmt = session.detect_depth_format()
            logger.debug(f"Depth format: {fmt}")

        return rgb, depth
    finally:
        session.close()
