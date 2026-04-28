"""OBS WebSocket helpers exposed to the Web UI.

Three endpoints power the "Video Recording" panel:
    POST /api/obs/test    -- one-shot connect, return version + scenes
    POST /api/obs/setup   -- spawn scripts/setup_obs.py, stream stdout to log
    GET  /api/obs/status  -- "is OBS reachable / is recorder armed" probe
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

from web.demo import (
    canned_obs_setup, canned_obs_status, canned_obs_test, is_demo_mode,
)

bp = Blueprint("obs", __name__)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup_obs.py"
OBS_CONFIG = REPO_ROOT / "configs" / "obs.json"


def _load_obs_config() -> dict:
    try:
        return json.loads(OBS_CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@bp.route("/api/obs/test", methods=["POST"])
def obs_test():
    """Probe OBS WebSocket. Returns version + available scenes if reachable."""
    if is_demo_mode():
        return jsonify(canned_obs_test())
    body = request.get_json(silent=True) or {}
    cfg = _load_obs_config()
    host = str(body.get("obs_host") or cfg.get("obs_host", "127.0.0.1"))
    port = int(body.get("obs_port") or cfg.get("obs_port", 4455))
    password = str(body.get("obs_password") or cfg.get("obs_password", ""))

    if not _port_open(host, port):
        return jsonify({
            "ok": False,
            "error": f"port {host}:{port} unreachable. Is OBS running?",
        }), 503

    try:
        import obsws_python as obsws  # type: ignore
    except ImportError:
        return jsonify({
            "ok": False,
            "error": "obsws-python not installed. Run: pip install obsws-python",
        }), 500

    try:
        client = obsws.ReqClient(host=host, port=port, password=password, timeout=5)
        version = client.get_version()
        scenes_resp = client.get_scene_list()
        scenes = [
            s.get("sceneName") for s in (scenes_resp.scenes or [])
            if s.get("sceneName")
        ]
        client.disconnect()
        return jsonify({
            "ok": True,
            "obs_version": getattr(version, "obs_version", None),
            "rpc_version": getattr(version, "rpc_version", None),
            "scenes": scenes,
            "current_scene": getattr(scenes_resp, "current_program_scene_name", None),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"connect failed: {e}"}), 500


_OBS_SAVEABLE_KEYS = {
    "obs_host", "obs_port", "obs_password", "obs_scene",
    "hide_hud_during_recording", "strict_video",
}


@bp.route("/api/obs/config", methods=["GET"])
def obs_config_get():
    """Return current configs/obs.json for pre-filling the OBS Settings modal."""
    return jsonify({"ok": True, **_load_obs_config()})


@bp.route("/api/obs/config", methods=["POST"])
def obs_config_save():
    """Persist OBS UI settings to configs/obs.json."""
    body = request.get_json(silent=True) or {}
    cfg = _load_obs_config()
    for k, v in body.items():
        if k in _OBS_SAVEABLE_KEYS:
            cfg[k] = v
    try:
        OBS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        OBS_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


@bp.route("/api/obs/status", methods=["GET"])
def obs_status():
    if is_demo_mode():
        return jsonify(canned_obs_status())
    cfg = _load_obs_config()
    host = cfg.get("obs_host", "127.0.0.1")
    port = int(cfg.get("obs_port", 4455))
    return jsonify({
        "ok": True,
        "obs_installed": (REPO_ROOT / "3rdparty" / "obs-studio" /
                          "bin" / "64bit" / "obs64.exe").is_file(),
        "websocket_reachable": _port_open(host, port),
        "host": host,
        "port": port,
        "video_enabled_default": bool(cfg.get("enabled", False)),
    })


_setup_lock = threading.Lock()
_setup_running = False


@bp.route("/api/obs/setup", methods=["POST"])
def obs_setup():
    """Run scripts/setup_obs.py in the background; route stdout to log."""
    global _setup_running
    if is_demo_mode():
        return jsonify(canned_obs_setup())
    if not SETUP_SCRIPT.is_file():
        return jsonify({"ok": False, "error": f"{SETUP_SCRIPT} not found"}), 500

    with _setup_lock:
        if _setup_running:
            return jsonify({"ok": False, "error": "setup already running"}), 409
        _setup_running = True

    def _run():
        global _setup_running
        try:
            logger.info("[OBS-SETUP] starting scripts/setup_obs.py")
            proc = subprocess.Popen(
                [sys.executable, str(SETUP_SCRIPT)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(REPO_ROOT),
            )
            for line in proc.stdout or []:
                logger.info(f"[OBS-SETUP] {line.rstrip()}")
            rc = proc.wait()
            logger.info(f"[OBS-SETUP] exit code {rc}")
        except Exception as e:
            logger.error(f"[OBS-SETUP] failed: {e}")
        finally:
            with _setup_lock:
                _setup_running = False

    threading.Thread(target=_run, name="obs-setup", daemon=True).start()
    return jsonify({"ok": True, "message": "setup started; watch the log"})
