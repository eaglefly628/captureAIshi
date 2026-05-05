"""Pure helpers reused across blueprints: bridge TCP, hack profile lookup,
form-data -> argparse.Namespace conversion.
"""

import json
import logging
import re
import socket
from argparse import Namespace
from pathlib import Path

from web.state import (
    _VALID_CE_MODES,
    _VALID_DRIVERS,
    _VALID_GRABBERS,
)


def _bridge_send(cmd: str, port: int = 9998, timeout: float = 35.0) -> str:
    """One-shot: connect to bridge TCP, send cmd, recv response, close."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(("127.0.0.1", port))
    s.sendall((cmd + "\n").encode("utf-8"))
    resp = s.recv(4096).decode("utf-8", errors="replace")
    s.close()
    return resp.strip()


def _game_slug(name: str) -> str:
    """Convert a game name to a filesystem-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:80]


def _hack_profile_data(profile_id: str, target_exe: str = "") -> dict:
    """Return the hack profile JSON dict, or {} if not found.

    Looks up by profile_id first; if empty or unknown, falls back to matching
    the basename of target_exe against each profile's process_names.
    """
    hacks_dir = Path(__file__).resolve().parent.parent / "configs" / "hacks"

    if profile_id and profile_id.replace("_", "").isalnum():
        path = hacks_dir / f"{profile_id}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    exe_name = Path(target_exe).name.lower() if target_exe else ""
    if exe_name and hacks_dir.exists():
        for path in hacks_dir.glob("*.json"):
            if path.name.startswith("_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for name in data.get("process_names", []):
                if name.lower() == exe_name:
                    return data
    return {}


def _hack_profile_launch_style(profile_id: str, target_exe: str = "") -> str:
    """Return the launch_arg_style for a hack profile ('unreal' if absent)."""
    return _hack_profile_data(profile_id, target_exe).get("launch_arg_style", "unreal")


def _load_obs_defaults() -> dict:
    """Load configs/obs.json once per call (cheap), fall back to empty dict."""
    path = Path(__file__).resolve().parent.parent / "configs" / "obs.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _build_session_name(driver: str, grabber: str, dry_run: bool) -> str:
    """Build a short session subdirectory name from capture config."""
    _driver_abbrev = {
        "manual": "man", "ue5": "ue5", "unity": "uni", "cheatengine": "ce",
    }
    _grabber_abbrev = {
        "none": "nograb", "renderdoc": "rdoc", "screenshot": "scrn",
    }
    parts = [_driver_abbrev.get(driver, driver), _grabber_abbrev.get(grabber, grabber)]
    if dry_run:
        parts.append("dry")
    return "_".join(parts)


def _build_args(data: dict) -> Namespace:
    """Convert and validate JSON form data to an argparse-like Namespace."""
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")

    args = Namespace()

    driver = str(data.get("driver", "manual"))
    if driver not in _VALID_DRIVERS:
        raise ValueError(f"Invalid driver: {driver}")
    args.driver = driver

    args.driver_host = str(data.get("driver_host", "127.0.0.1"))
    args.driver_port = max(1, min(65535, int(data.get("driver_port", 9999))))

    ce_mode = str(data.get("ce_mode", "file"))
    if ce_mode not in _VALID_CE_MODES:
        raise ValueError(f"Invalid ce_mode: {ce_mode}")
    args.ce_mode = ce_mode

    grabber = str(data.get("grabber", "none"))
    if grabber not in _VALID_GRABBERS:
        raise ValueError(f"Invalid grabber: {grabber}")
    args.grabber = grabber

    _exe = str(data.get("target_exe", "")).strip()
    args.target_exe = _exe or None

    # Build launch args from separate UI fields.
    # Arg style depends on the game engine: UE uses -ResX/-Windowed;
    # REDengine 4 (Cyberpunk) uses -width/-windowed (lowercase).
    launch_args = []
    resx = int(data.get("launch_resx", 0) or 0)
    resy = int(data.get("launch_resy", 0) or 0)
    _profile = _hack_profile_data(
        str(data.get("hack_profile_id", "")),
        str(data.get("target_exe", "")),
    )
    launch_arg_style = _profile.get("launch_arg_style", "unreal")
    launch_mode = _profile.get("launch_mode", "capture")
    args.inject = (launch_mode == "inject")
    args.inject_delay = float(_profile.get("inject_delay", 5.0))
    logging.info(
        f"[LAUNCH] arg_style={launch_arg_style} launch_mode={launch_mode} "
        f"(profile_id={data.get('hack_profile_id', '')!r}, "
        f"exe={Path(str(data.get('target_exe', ''))).name!r})"
    )
    if launch_arg_style == "redengine":
        if resx > 0:
            launch_args.append(f"-width={resx}")
        if resy > 0:
            launch_args.append(f"-height={resy}")
        if data.get("launch_windowed", False):
            launch_args.append("-windowed")
    else:  # "unreal" or unrecognised -- default UE style
        if resx > 0:
            launch_args.append(f"-ResX={resx}")
        if resy > 0:
            launch_args.append(f"-ResY={resy}")
        if data.get("launch_windowed", False):
            launch_args.append("-Windowed")
    if data.get("launch_log", False):
        launch_args.append("-log")
    args.target_args = launch_args
    args.renderdoc_path = str(data.get("renderdoc_path", "")) or "renderdoccmd"
    args.no_hide_ui = bool(data.get("no_hide_ui", False))
    args.dry_run = bool(data.get("dry_run", False))
    args.debug_scan = bool(data.get("debug_scan", False))

    args.streaming = bool(data.get("streaming", True))
    args.streaming_settle = max(0.0, min(10.0, float(data.get("streaming_settle", 0.5))))

    args.fov = max(1.0, min(180.0, float(data.get("fov", 90.0))))
    args.aspect = max(0.1, float(data.get("aspect", 1.7778)))

    base_dir = Path(str(data.get("output_dir", "./output")))
    session_name = _build_session_name(driver, grabber, args.dry_run)
    args.output_dir = base_dir / session_name
    args.clean_start = bool(data.get("clean_start", True))

    # Video recording (OBS WebSocket). Form keys live under "recorder" or
    # at the top level; missing keys fall through to configs/obs.json.
    rec = data.get("recorder")
    if not isinstance(rec, dict):
        rec = {}
    obs_defaults = _load_obs_defaults()

    def _rec(key: str, default):
        if key in rec:
            return rec[key]
        if key in obs_defaults:
            return obs_defaults[key]
        return default

    args.recorder_enabled = bool(_rec("enabled", False))
    args.recorder_backend = str(_rec("backend", "obs"))
    args.obs_host = str(_rec("obs_host", "127.0.0.1"))
    args.obs_port = max(1, min(65535, int(_rec("obs_port", 4455))))
    args.obs_password = str(_rec("obs_password", ""))
    args.obs_scene = str(_rec("obs_scene", "Capture"))
    args.obs_source_name = str(_rec("obs_source_name", "Game Capture"))
    args.obs_exe_path = _rec("obs_exe_path", None) or None
    args.auto_launch_obs = bool(_rec("auto_launch_obs", True))
    args.hide_hud_during_recording = bool(_rec("hide_hud_during_recording", True))
    args.strict_video = bool(_rec("strict_video", False))
    args.video_bitrate_kbps = int(_rec("video_bitrate_kbps", 50000))
    args.video_framerate = float(_rec("video_framerate", 60.0))
    return args
