#!/usr/bin/env python3
"""One-shot OBS Studio installer + configurer for captureAIshi video recording.

Usage:
    python scripts/setup_obs.py             # detect, download if missing,
                                            # install silently, configure scene
    python scripts/setup_obs.py --check     # 0 if ready, 1 otherwise

The OBS Studio installer is GPLv2; this script downloads the unmodified
official binary from https://github.com/obsproject/obs-studio/releases.
We do not redistribute OBS in this repo.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import shutil
import socket
import string
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("setup_obs")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INSTALL_DIR = REPO_ROOT / "3rdparty" / "obs-studio"
GITHUB_LATEST = "https://api.github.com/repos/obsproject/obs-studio/releases/latest"
INSTALLER_PATTERN = "Full-Installer-x64.exe"


def _appdata_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "obs-studio"
    return Path.home() / ".config" / "obs-studio"


def _common_obs_paths() -> list[Path]:
    candidates: list[Path] = [
        DEFAULT_INSTALL_DIR / "bin" / "64bit" / "obs64.exe",
    ]
    if sys.platform == "win32":
        for env_key in ("ProgramFiles", "ProgramW6432"):
            base = os.environ.get(env_key)
            if base:
                candidates.append(Path(base) / "obs-studio" / "bin" / "64bit" / "obs64.exe")
    return candidates


def detect() -> Optional[Path]:
    """Return the obs64.exe path if installed, otherwise None."""
    for c in _common_obs_paths():
        if c.is_file():
            return c
    return None


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(24))


def _download_installer(dest: Path) -> Path:
    try:
        import requests  # type: ignore
    except ImportError as e:
        raise RuntimeError("requests not installed; pip install requests") from e
    logger.info("Querying GitHub for latest OBS release ...")
    r = requests.get(GITHUB_LATEST, timeout=30)
    r.raise_for_status()
    release = r.json()
    asset = next(
        (a for a in release.get("assets", []) if INSTALLER_PATTERN in a["name"]),
        None,
    )
    if asset is None:
        raise RuntimeError(
            f"No asset matching {INSTALLER_PATTERN!r} in release "
            f"{release.get('tag_name')}"
        )
    url = asset["browser_download_url"]
    size = asset.get("size", 0)
    logger.info(f"Downloading {asset['name']} ({size/1024/1024:.0f} MiB) ...")
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
        logger.info(f"Downloaded {downloaded/1024/1024:.0f} MiB to {dest}")
    return dest


def install(installer_path: Path, install_dir: Path) -> Path:
    """Run the NSIS silent installer and return obs64.exe path."""
    install_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(installer_path), "/S", f"/D={install_dir}"]
    logger.info(f"Running silent install: {' '.join(cmd)}")
    rc = subprocess.call(cmd)
    if rc != 0:
        raise RuntimeError(f"OBS installer exited with code {rc}")
    obs_exe = install_dir / "bin" / "64bit" / "obs64.exe"
    if not obs_exe.is_file():
        raise RuntimeError(f"Install completed but obs64.exe not found at {obs_exe}")
    return obs_exe


def configure_scene(scene_name: str = "Capture", source_name: str = "Game Capture") -> Path:
    """Write a scene-collection JSON so OBS opens with our default scene."""
    scenes_dir = _appdata_dir() / "basic" / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    target = scenes_dir / "captureAIshi.json"
    collection = {
        "current_scene": scene_name,
        "current_program_scene": scene_name,
        "name": "captureAIshi",
        "scene_order": [{"name": scene_name}],
        "sources": [
            {
                "name": source_name,
                "id": "game_capture",
                "versioned_id": "game_capture",
                "settings": {
                    "capture_mode": "any_fullscreen",
                    "priority": 1,
                    "anti_cheat_hook": True,
                    "capture_overlays": False,
                },
            },
            {
                "name": scene_name,
                "id": "scene",
                "versioned_id": "scene",
                "settings": {
                    "items": [{"name": source_name, "visible": True}],
                },
            },
        ],
    }
    target.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    logger.info(f"Wrote scene collection to {target}")
    return target


def configure_websocket(port: int = 4455, password: Optional[str] = None) -> str:
    """Enable obs-websocket on ``port`` with ``password`` (auto-generated if None).

    Returns the password used.
    """
    if password is None:
        password = _generate_password()
    cfg_dir = _appdata_dir() / "plugin_config" / "obs-websocket"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "config.json"
    cfg = {
        "alerts_enabled": False,
        "auth_required": bool(password),
        "first_load": False,
        "server_enabled": True,
        "server_password": password,
        "server_port": int(port),
    }
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    logger.info(f"Wrote obs-websocket config to {cfg_path} (port {port})")
    return password


def persist_password_to_config(password: str) -> None:
    """Update configs/obs.json with the generated password."""
    target = REPO_ROOT / "configs" / "obs.json"
    try:
        cfg = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    cfg["obs_password"] = password
    target.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    logger.info(f"Saved password to {target}")


def run_check(host: str = "127.0.0.1", port: int = 4455) -> int:
    """Return 0 iff OBS is installed and the websocket port is reachable."""
    obs_exe = detect()
    if obs_exe is None:
        print("OBS not installed.")
        return 1
    print(f"OBS installed at {obs_exe}")
    if _port_open(host, port):
        print(f"WebSocket reachable on {host}:{port}")
        return 0
    print(f"WebSocket NOT reachable on {host}:{port} (is OBS running?)")
    return 1


def run_setup(install_dir: Path, port: int) -> int:
    obs_exe = detect()
    if obs_exe is None:
        with tempfile.TemporaryDirectory() as tmp:
            installer = _download_installer(Path(tmp) / "obs_installer.exe")
            obs_exe = install(installer, install_dir)
    else:
        logger.info(f"OBS already installed at {obs_exe}")
    configure_scene()
    password = configure_websocket(port=port)
    persist_password_to_config(password)
    print("OBS setup complete.")
    print(f"  obs64.exe : {obs_exe}")
    print(f"  websocket : 127.0.0.1:{port}")
    print("  password  : (saved to configs/obs.json)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Probe install + websocket; exit 0 if ready, 1 otherwise.")
    parser.add_argument("--install-dir", type=Path, default=DEFAULT_INSTALL_DIR)
    parser.add_argument("--port", type=int, default=4455)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if args.check:
        return run_check(port=args.port)
    return run_setup(install_dir=args.install_dir, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
