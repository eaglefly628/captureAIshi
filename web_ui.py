#!/usr/bin/env python3
"""captureAIshi — Web UI server.

Provides a browser-based interface to configure and launch captures.
All capture logic is reused from main.py — this is just a GUI shell.
"""

import json
import logging
import shutil
import threading
import time
import webbrowser
from argparse import Namespace
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from core.path_player import PathStore, interpolate_path
from main import run_capture

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
_path_store = PathStore()

# Shared state for capture progress
_capture_state = {
    "running": False,
    "logs": [],
    "error": None,
}
_lock = threading.Lock()
_stop_event = threading.Event()


class WebLogHandler(logging.Handler):
    """Capture log records into the shared state for the frontend."""

    def emit(self, record):
        msg = self.format(record)
        with _lock:
            _capture_state["logs"].append(msg)
            # Keep last 500 lines
            if len(_capture_state["logs"]) > 500:
                _capture_state["logs"] = _capture_state["logs"][-500:]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_capture():
    with _lock:
        if _capture_state["running"]:
            return jsonify({"ok": False, "error": "Capture already running"}), 409

    data = request.json
    if data is None:
        return jsonify({"ok": False, "error": "Request body must be JSON"}), 400

    try:
        args = _build_args(data)
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # Clean start: remove previous output in this session dir
    if args.clean_start and args.output_dir.exists():
        logging.info(f"[CLEAN] Removing previous output: {args.output_dir}")
        try:
            shutil.rmtree(args.output_dir)
            logging.info(f"[CLEAN] Cleaned output directory: {args.output_dir}")
        except OSError as e:
            logging.warning(f"[CLEAN] Failed to clean {args.output_dir}: {e}")

    _stop_event.clear()
    args._stop_event = _stop_event

    with _lock:
        _capture_state["running"] = True
        _capture_state["logs"] = []
        _capture_state["error"] = None
        _capture_state["output_dir"] = str(args.output_dir)

    _push_recent(data)

    thread = threading.Thread(target=_run_in_thread, args=(args,), daemon=True)
    thread.start()

    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop_capture():
    _stop_event.set()
    logging.info("Stop requested by user")
    return jsonify({"ok": True})


@app.route("/api/status")
def capture_status():
    with _lock:
        return jsonify({
            "running": _capture_state["running"],
            "logs": _capture_state["logs"],
            "error": _capture_state["error"],
        })


def _bridge_send(cmd: str, port: int = 9998, timeout: float = 35.0) -> str:
    """One-shot: connect to bridge, send cmd, return response, close."""
    import socket as _sock
    s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(("127.0.0.1", port))
    s.sendall((cmd + "\n").encode("utf-8"))
    resp = s.recv(4096).decode("utf-8", errors="replace")
    s.close()
    return resp.strip()


@app.route("/api/bridge-test", methods=["POST"])
def bridge_test():
    """Send __bridge_test to the bridge for visual verification.
    Also supports custom commands via JSON body {"cmd": "slomo 0.1"}."""
    cmd = "__bridge_test"
    body = request.get_json(silent=True)
    if body and body.get("cmd"):
        cmd = body["cmd"]
    try:
        resp = _bridge_send(cmd, timeout=35.0)
        return jsonify({"ok": True, "response": resp, "cmd": cmd})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/bridge/scan_status", methods=["GET"])
def bridge_scan_status():
    """Query current UWorld + LocalPlayer scan state from bridge."""
    try:
        raw = _bridge_send("__bridge_status", timeout=5.0)
        status = {}
        for pair in raw.split():
            if "=" in pair:
                k, v = pair.split("=", 1)
                status[k] = v
        return jsonify({
            "ok": True,
            "uworld_found": status.get("uworld_found") == "1",
            "localplayer_found": status.get("localplayer_found") == "1",
            "world_ptr": status.get("world_ptr", "0x0"),
            "localplayer_ptr": status.get("localplayer_ptr", "0x0"),
            "engine_found": status.get("engine_found") == "1",
            "gamethread_dispatch": status.get("gamethread_dispatch") == "1",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/bridge/rescan", methods=["POST"])
def bridge_rescan():
    """Trigger UWorld + LocalPlayer re-scan in the bridge.
    Call this after map load. Bridge clears stale pointers and rescans."""
    try:
        raw = _bridge_send("__bridge_rescan_objects", timeout=35.0)
        result = {}
        for pair in raw.split():
            if "=" in pair:
                k, v = pair.split("=", 1)
                result[k] = v
        return jsonify({
            "ok": True,
            "uworld_found": result.get("uworld_found") == "1",
            "localplayer_found": result.get("localplayer_found") == "1",
            "world_ptr": result.get("world_ptr", "0x0"),
            "localplayer_ptr": result.get("localplayer_ptr", "0x0"),
            "raw": raw,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


_CONFIG_DIR = Path("./configs")
_CONFIG_FILE = _CONFIG_DIR / "_last.json"
_RECENT_FILE = _CONFIG_DIR / "_recent.json"
_MAX_RECENT = 10


def _ensure_config_dir():
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


@app.route("/api/config", methods=["GET"])
def load_config():
    """Load saved config from disk. Falls back to defaults."""
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            return jsonify(data)
        except Exception as e:
            logging.warning(f"[CONFIG] Failed to load config from {_CONFIG_FILE}: {e}")
    return defaults()


@app.route("/api/config", methods=["POST"])
def save_config():
    """Auto-save current form config to disk."""
    data = request.json
    if data is None:
        return jsonify({"ok": False}), 400
    _ensure_config_dir()
    _CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/config/profiles", methods=["GET"])
def list_profiles():
    """List all saved config profiles."""
    _ensure_config_dir()
    profiles = []
    for f in sorted(_CONFIG_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            profiles.append({
                "name": f.stem,
                "driver": data.get("driver", "?"),
                "grabber": data.get("grabber", "?"),
                "spacing": data.get("spacing", "?"),
            })
        except Exception as e:
            logging.warning(f"[CONFIG] Failed to parse profile {f.name}: {e}")
            profiles.append({"name": f.stem, "driver": "?", "grabber": "?", "spacing": "?"})
    return jsonify(profiles)


@app.route("/api/config/profiles/<name>", methods=["GET"])
def load_profile(name):
    """Load a named config profile."""
    path = _CONFIG_DIR / f"{name}.json"
    if not path.exists():
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    data = json.loads(path.read_text(encoding="utf-8"))
    return jsonify(data)


@app.route("/api/config/profiles/<name>", methods=["PUT"])
def save_profile(name):
    """Save current form data as a named profile."""
    data = request.json
    if data is None:
        return jsonify({"ok": False}), 400
    _ensure_config_dir()
    path = _CONFIG_DIR / f"{name}.json"
    data.pop("_profile_name", None)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/config/profiles/<name>", methods=["DELETE"])
def delete_profile(name):
    """Delete a named config profile."""
    path = _CONFIG_DIR / f"{name}.json"
    if path.exists():
        path.unlink()
    return jsonify({"ok": True})


@app.route("/api/config/recent", methods=["GET"])
def list_recent():
    """List recent capture configs (last N runs)."""
    if _RECENT_FILE.exists():
        try:
            data = json.loads(_RECENT_FILE.read_text(encoding="utf-8"))
            return jsonify(data)
        except Exception as e:
            logging.warning(f"[CONFIG] Failed to load recent history: {e}")
    return jsonify([])


def _push_recent(config: dict):
    """Add a config to the recent history."""
    _ensure_config_dir()
    recent = []
    if _RECENT_FILE.exists():
        try:
            recent = json.loads(_RECENT_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logging.warning(f"[CONFIG] Failed to parse recent file: {e}")
            recent = []
    import datetime
    entry = {
        "timestamp": datetime.datetime.now().strftime("%m-%d %H:%M"),
        "driver": config.get("driver", "?"),
        "grabber": config.get("grabber", "?"),
        "spacing": config.get("spacing", "?"),
        "config": config,
    }
    recent.insert(0, entry)
    recent = recent[:_MAX_RECENT]
    _RECENT_FILE.write_text(json.dumps(recent, indent=2, ensure_ascii=False), encoding="utf-8")


@app.route("/api/defaults")
def defaults():
    """Return default parameter values for the form."""
    return jsonify({
        "volume_min": [-5, 0, -5],
        "volume_max": [5, 3, 5],
        "spacing": 2.0,
        "smooth": False,
        "smooth_points": 5,
        "cone_angle": 0,
        "cone_samples": 8,
        "cone_rings": 2,
        "driver": "manual",
        "driver_host": "127.0.0.1",
        "driver_port": 9999,
        "ce_mode": "file",
        "grabber": "none",
        "target_exe": "",
        "launch_resx": 1024,
        "launch_resy": 768,
        "launch_windowed": True,
        "launch_log": False,
        "no_hide_ui": False,
        "output_dir": "./output",
        "dry_run": False,
        "streaming": True,
        "streaming_settle": 0.5,
        "fov": 90.0,
        "aspect": 1.7778,
    })


@app.route("/api/sessions")
def list_sessions():
    """List capture session subdirectories under the base output dir."""
    with _lock:
        output_dir = _capture_state.get("output_dir", "./output")
    # Walk up to the base dir (parent of session subdir)
    base = Path(output_dir).parent
    if not base.is_dir():
        return jsonify({"sessions": [], "active": ""})
    sessions = sorted(
        [d.name for d in base.iterdir() if d.is_dir()],
        key=lambda n: n,
    )
    active = Path(output_dir).name if Path(output_dir).is_dir() else ""
    return jsonify({"sessions": sessions, "active": active})


def _safe_session_path(session: str, base: Path) -> Path:
    """Resolve a session name to a path, rejecting traversal attempts."""
    target = (base / session).resolve()
    if not target.is_relative_to(base.resolve()):
        return None
    return target


@app.route("/api/captures")
@app.route("/api/captures/<session>")
def list_captures(session=None):
    """List captured image files from a session directory."""
    with _lock:
        output_dir = _capture_state.get("output_dir", "./output")
    base = Path(output_dir).parent
    if session:
        target = _safe_session_path(session, base)
        if target is None:
            return jsonify({"error": "Invalid session path"}), 403
    else:
        target = Path(output_dir)
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".exr"}
    files = []
    if target.is_dir():
        for f in sorted(target.rglob("*")):
            if f.suffix.lower() in exts:
                # Always use forward slashes for URL compatibility
                files.append(f.relative_to(target).as_posix())
    return jsonify({"files": files, "session": target.name if target.is_dir() else ""})


@app.route("/api/captures/<session>/<path:filename>")
def serve_capture(session, filename):
    """Serve a captured image file from a session directory."""
    with _lock:
        output_dir = _capture_state.get("output_dir", "./output")
    base = Path(output_dir).parent
    target = _safe_session_path(session, base)
    if target is None:
        return jsonify({"error": "Invalid session path"}), 403
    return send_from_directory(str(target), filename)


@app.route("/api/session-stats")
@app.route("/api/session-stats/<session>")
def session_stats(session=None):
    """Return file count and total size for a session directory."""
    with _lock:
        output_dir = _capture_state.get("output_dir", "./output")
    base = Path(output_dir).parent
    if session:
        target = _safe_session_path(session, base)
        if target is None:
            return jsonify({"error": "Invalid session path"}), 403
    else:
        target = Path(output_dir)
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".exr"}
    total_size = 0
    count = 0
    if target.is_dir():
        for f in target.rglob("*"):
            if f.suffix.lower() in exts:
                count += 1
                total_size += f.stat().st_size
    return jsonify({"count": count, "size_bytes": total_size})


@app.route("/api/presets")
def presets():
    """Return available capture presets for the quick-start UI."""
    return jsonify(_PRESETS)


_PRESETS = [
    {
        "id": "ue5_quick",
        "name": "UE5 Quick Capture",
        "icon": "gamepad",
        "desc": "UE5 game via bridge + RenderDoc, small area, fast preview",
        "tags": ["UE5", "RenderDoc"],
        "params": {
            "volume_min": [-10, 0, -10],
            "volume_max": [10, 5, 10],
            "spacing": 3.0,
            "smooth": True,
            "smooth_points": 3,
            "cone_angle": 0,
            "cone_samples": 8,
            "cone_rings": 2,
            "driver": "ue5",
            "driver_host": "127.0.0.1",
            "driver_port": 9998,
            "ce_mode": "file",
            "grabber": "renderdoc",
            "target_exe": "",
            "no_hide_ui": False,
            "output_dir": "./output",
            "dry_run": False,
            "streaming": True,
            "streaming_settle": 0.5,
        },
    },
    {
        "id": "ue5_full",
        "name": "UE5 Full Scene",
        "icon": "cube",
        "desc": "Large area + multi-angle cone rotation for dense coverage",
        "tags": ["UE5", "RenderDoc", "Cone"],
        "params": {
            "volume_min": [-100, 0, -100],
            "volume_max": [100, 50, 100],
            "spacing": 5.0,
            "smooth": True,
            "smooth_points": 5,
            "cone_angle": 30,
            "cone_samples": 8,
            "cone_rings": 2,
            "driver": "ue5",
            "driver_host": "127.0.0.1",
            "driver_port": 9998,
            "ce_mode": "file",
            "grabber": "renderdoc",
            "target_exe": "",
            "no_hide_ui": False,
            "output_dir": "./output",
            "dry_run": False,
            "streaming": True,
            "streaming_settle": 1.0,
        },
    },
    {
        "id": "unity_quick",
        "name": "Unity Quick Capture",
        "icon": "unity",
        "desc": "Unity game via BepInEx plugin + RenderDoc",
        "tags": ["Unity", "RenderDoc"],
        "params": {
            "volume_min": [-10, 0, -10],
            "volume_max": [10, 5, 10],
            "spacing": 2.0,
            "smooth": True,
            "smooth_points": 3,
            "cone_angle": 0,
            "cone_samples": 8,
            "cone_rings": 2,
            "driver": "unity",
            "driver_host": "127.0.0.1",
            "driver_port": 9999,
            "ce_mode": "file",
            "grabber": "renderdoc",
            "target_exe": "",
            "no_hide_ui": False,
            "output_dir": "./output",
            "dry_run": False,
            "streaming": True,
            "streaming_settle": 0.3,
        },
    },
    {
        "id": "unity_full",
        "name": "Unity Full Scene",
        "icon": "cube",
        "desc": "Large area + cone rotation for Unity games",
        "tags": ["Unity", "RenderDoc", "Cone"],
        "params": {
            "volume_min": [-50, 0, -50],
            "volume_max": [50, 20, 50],
            "spacing": 4.0,
            "smooth": True,
            "smooth_points": 5,
            "cone_angle": 45,
            "cone_samples": 8,
            "cone_rings": 2,
            "driver": "unity",
            "driver_host": "127.0.0.1",
            "driver_port": 9999,
            "ce_mode": "file",
            "grabber": "renderdoc",
            "target_exe": "",
            "no_hide_ui": False,
            "output_dir": "./output",
            "dry_run": False,
            "streaming": True,
            "streaming_settle": 0.5,
        },
    },
    {
        "id": "ce_screenshot",
        "name": "CheatEngine + Screenshot",
        "icon": "wrench",
        "desc": "Any game via CheatEngine memory control + screenshots",
        "tags": ["CheatEngine", "Screenshot"],
        "params": {
            "volume_min": [-20, 0, -20],
            "volume_max": [20, 10, 20],
            "spacing": 3.0,
            "smooth": True,
            "smooth_points": 3,
            "cone_angle": 0,
            "cone_samples": 8,
            "cone_rings": 2,
            "driver": "cheatengine",
            "driver_host": "127.0.0.1",
            "driver_port": 9999,
            "ce_mode": "file",
            "grabber": "screenshot",
            "target_exe": "",
            "no_hide_ui": False,
            "output_dir": "./output",
            "dry_run": False,
            "streaming": True,
            "streaming_settle": 0.5,
        },
    },
    {
        "id": "dry_run_test",
        "name": "Dry Run (Test)",
        "icon": "flask",
        "desc": "Generate poses only, no game connection needed",
        "tags": ["Test", "No Game"],
        "params": {
            "volume_min": [-5, 0, -5],
            "volume_max": [5, 3, 5],
            "spacing": 2.0,
            "smooth": True,
            "smooth_points": 5,
            "cone_angle": 15,
            "cone_samples": 6,
            "cone_rings": 1,
            "driver": "manual",
            "driver_host": "127.0.0.1",
            "driver_port": 9999,
            "ce_mode": "file",
            "grabber": "none",
            "target_exe": "",
            "no_hide_ui": False,
            "output_dir": "./output",
            "dry_run": True,
            "streaming": False,
            "streaming_settle": 0.0,
        },
    },
]


# ── Camera Path API ──


@app.route("/api/paths")
def list_paths():
    """List all saved camera paths."""
    return jsonify(_path_store.list_all())


@app.route("/api/path", methods=["POST"])
def create_path():
    """Create a new camera path."""
    data = request.json or {}
    name = str(data.get("name", "Untitled")).strip() or "Untitled"
    cp = _path_store.create(name=name)
    return jsonify(cp.to_dict()), 201


@app.route("/api/path/<path_id>")
def get_path(path_id):
    """Get a camera path by ID."""
    cp = _path_store.get(path_id)
    if not cp:
        return jsonify({"error": "Path not found"}), 404
    return jsonify(cp.to_dict())


@app.route("/api/path/<path_id>", methods=["PUT"])
def update_path(path_id):
    """Update path properties (name, loop, nodes)."""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    cp = _path_store.update(path_id, data)
    if not cp:
        return jsonify({"error": "Path not found"}), 404
    return jsonify(cp.to_dict())


@app.route("/api/path/<path_id>", methods=["DELETE"])
def delete_path(path_id):
    """Delete a camera path."""
    if _path_store.delete(path_id):
        return jsonify({"ok": True})
    return jsonify({"error": "Path not found"}), 404


@app.route("/api/path/<path_id>/node", methods=["POST"])
def add_path_node(path_id):
    """Add a node to a camera path."""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    index = data.pop("index", -1)
    cp = _path_store.add_node(path_id, data, index=index)
    if not cp:
        return jsonify({"error": "Path not found"}), 404
    return jsonify(cp.to_dict())


@app.route("/api/path/<path_id>/node/<int:node_idx>", methods=["PUT"])
def update_path_node(path_id, node_idx):
    """Update a specific node in a camera path."""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    cp = _path_store.update_node(path_id, node_idx, data)
    if not cp:
        return jsonify({"error": "Path or node not found"}), 404
    return jsonify(cp.to_dict())


@app.route("/api/path/<path_id>/node/<int:node_idx>", methods=["DELETE"])
def delete_path_node(path_id, node_idx):
    """Delete a specific node from a camera path."""
    cp = _path_store.delete_node(path_id, node_idx)
    if not cp:
        return jsonify({"error": "Path or node not found"}), 404
    return jsonify(cp.to_dict())


@app.route("/api/path/<path_id>/interpolate")
def interpolate_path_route(path_id):
    """Get interpolated path samples for 3D visualization."""
    cp = _path_store.get(path_id)
    if not cp:
        return jsonify({"error": "Path not found"}), 404
    samples_str = request.args.get("samples", "20")
    try:
        samples_per_seg = max(2, min(100, int(samples_str)))
    except ValueError:
        samples_per_seg = 20
    samples = interpolate_path(cp, samples_per_segment=samples_per_seg)
    return jsonify({"samples": samples, "total_duration": cp.total_duration})


# ── Game Library & Per-Game Profiles ──

_GAME_LIBRARY_FILE = Path("configs/game_library.json")
_GAME_CONFIGS_DIR = Path("configs/games")

_DEFAULT_GAME_CONFIG = {
    "volume_min": [-10, 0, -10],
    "volume_max": [10, 5, 10],
    "spacing": 3.0,
    "smooth": True,
    "smooth_points": 5,
    "cone_angle": 0,
    "cone_samples": 8,
    "cone_rings": 2,
    "fov": 90.0,
    "aspect": 1.7778,
    "driver": "ue5",
    "driver_host": "127.0.0.1",
    "driver_port": 9998,
    "grabber": "renderdoc",
    "notes": "",
}


def _game_slug(name: str) -> str:
    """Convert a game name to a filesystem-safe slug."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:80]


@app.route("/api/games")
def list_games():
    """Return the game library with search/filter support."""
    if not _GAME_LIBRARY_FILE.exists():
        return jsonify({"games": []})
    try:
        data = json.loads(_GAME_LIBRARY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"games": []})

    games = data.get("games", [])
    q = request.args.get("q", "").strip().lower()
    engine = request.args.get("engine", "").strip().lower()

    if q:
        games = [g for g in games if q in g["name"].lower()]
    if engine:
        games = [g for g in games if g.get("engine", "").lower() == engine]

    # Add slug and has_config flag
    for g in games:
        slug = _game_slug(g["name"])
        g["slug"] = slug
        g["has_config"] = (_GAME_CONFIGS_DIR / f"{slug}.json").exists()

    return jsonify({"games": games, "total": len(games)})


@app.route("/api/games/<slug>/config", methods=["GET"])
def get_game_config(slug):
    """Load per-game capture config. Returns defaults if none saved."""
    slug = _game_slug(slug)
    if not slug:
        return jsonify({"error": "Invalid game slug"}), 400
    path = _GAME_CONFIGS_DIR / f"{slug}.json"
    if not path.exists():
        config = dict(_DEFAULT_GAME_CONFIG)
        config["_slug"] = slug
        return jsonify(config)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        config["_slug"] = slug
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/games/<slug>/config", methods=["POST"])
def save_game_config(slug):
    """Save per-game capture config."""
    slug = _game_slug(slug)
    if not slug:
        return jsonify({"error": "Invalid game slug"}), 400
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    _GAME_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    # Strip internal fields
    data.pop("_slug", None)
    data.pop("_profile_name", None)
    path = _GAME_CONFIGS_DIR / f"{slug}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True})


_VALID_DRIVERS = {"manual", "ue5", "unity", "cheatengine"}
_VALID_GRABBERS = {"none", "renderdoc", "screenshot"}
_VALID_CE_MODES = {"file", "socket"}


def _validate_float_list(val, length: int, name: str) -> list:
    """Validate that val is a list of floats with the expected length."""
    if not isinstance(val, list) or len(val) != length:
        raise ValueError(f"{name} must be a list of {length} numbers")
    return [float(v) for v in val]


def _build_args(data: dict) -> Namespace:
    """Convert and validate JSON form data to an argparse-like Namespace."""
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")

    args = Namespace()
    args.volume_min = _validate_float_list(data.get("volume_min", [-5, 0, -5]), 3, "volume_min")
    args.volume_max = _validate_float_list(data.get("volume_max", [5, 3, 5]), 3, "volume_max")
    args.spacing = max(0.01, float(data.get("spacing", 2.0)))
    args.smooth = bool(data.get("smooth", False))
    args.smooth_points = max(2, int(data.get("smooth_points", 5)))
    args.cone_angle = max(0.0, min(90.0, float(data.get("cone_angle", 0))))
    args.cone_samples = max(1, int(data.get("cone_samples", 8)))
    args.cone_rings = max(1, int(data.get("cone_rings", 2)))

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

    # Game executable path
    _exe = str(data.get("target_exe", "")).strip()
    args.target_exe = _exe or None

    # Build launch args from separate UI fields
    launch_args = []
    resx = int(data.get("launch_resx", 0) or 0)
    resy = int(data.get("launch_resy", 0) or 0)
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

    # Streaming / LOD management
    args.streaming = bool(data.get("streaming", True))
    args.streaming_settle = max(0.0, min(10.0, float(data.get("streaming_settle", 0.5))))

    # Camera intrinsics
    args.fov = max(1.0, min(180.0, float(data.get("fov", 90.0))))
    args.aspect = max(0.1, float(data.get("aspect", 1.7778)))

    # Build output dir: base_dir / <session_name>
    base_dir = Path(str(data.get("output_dir", "./output")))
    session_name = _build_session_name(driver, grabber, args.dry_run)
    args.output_dir = base_dir / session_name
    args.clean_start = bool(data.get("clean_start", True))
    return args


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


def _run_in_thread(args):
    """Run capture in a background thread."""
    # Install log handler to capture output
    handler = WebLogHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        run_capture(args)
    except Exception as e:
        import traceback
        with _lock:
            _capture_state["error"] = str(e)
        logging.error(f"Capture failed: {e}\n{traceback.format_exc()}")
    finally:
        with _lock:
            _capture_state["running"] = False
        root_logger.removeHandler(handler)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Suppress noisy Werkzeug request logs for polling endpoints
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    port = 5000
    print(f"captureAIshi Web UI: http://127.0.0.1:{port}")
    webbrowser.open(f"http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
