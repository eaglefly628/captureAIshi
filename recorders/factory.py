"""Factory mirroring drivers.create_driver / grabbers.create_grabber."""

import logging
from pathlib import Path

from recorders.base import BaseRecorder, NullRecorder
from recorders.obs_recorder import OBSRecorder

logger = logging.getLogger(__name__)


def create_recorder(args, output_dir: Path) -> BaseRecorder:
    """Build a recorder from an argparse-like ``args`` namespace.

    When ``args.recorder_enabled`` is False or absent, returns ``NullRecorder``.
    """
    if not getattr(args, "recorder_enabled", False):
        return NullRecorder("disabled in config")

    backend = getattr(args, "recorder_backend", "obs")
    if backend != "obs":
        logger.warning(f"[VIDEO] unknown recorder backend '{backend}', disabling")
        return NullRecorder(f"unknown backend {backend}")

    return OBSRecorder(
        output_dir=Path(output_dir),
        host=getattr(args, "obs_host", "127.0.0.1"),
        port=int(getattr(args, "obs_port", 4455)),
        password=getattr(args, "obs_password", "") or "",
        scene=getattr(args, "obs_scene", "Capture"),
        source_name=getattr(args, "obs_source_name", "Game Capture"),
        bitrate_kbps=int(getattr(args, "video_bitrate_kbps", 50000)),
        framerate=float(getattr(args, "video_framerate", 60.0)),
        auto_launch_obs=bool(getattr(args, "auto_launch_obs", True)),
        obs_exe_path=getattr(args, "obs_exe_path", None) or None,
        target_exe=getattr(args, "target_exe", None),
        strict=bool(getattr(args, "strict_video", False)),
    )
