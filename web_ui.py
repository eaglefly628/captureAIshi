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

from main import run_capture

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")

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


@app.route("/api/captures")
@app.route("/api/captures/<session>")
def list_captures(session=None):
    """List captured image files from a session directory."""
    with _lock:
        output_dir = _capture_state.get("output_dir", "./output")
    base = Path(output_dir).parent
    if session:
        target = base / session
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
    target = (base / session).resolve()
    return send_from_directory(str(target), filename)


@app.route("/api/session-stats")
@app.route("/api/session-stats/<session>")
def session_stats(session=None):
    """Return file count and total size for a session directory."""
    with _lock:
        output_dir = _capture_state.get("output_dir", "./output")
    base = Path(output_dir).parent
    target = (base / session) if session else Path(output_dir)
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
        "desc": "UE5 game via UUU + RenderDoc, small area, fast preview",
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

    # "Game Command" field: "C:\path\game.exe -Windowed -ResX=640"
    # Split into exe path + args. The grabber also does this defensively,
    # but splitting here keeps args clean for logging and config display.
    import shlex
    _game_cmd = str(data.get("target_exe", "")).strip()
    if _game_cmd:
        parts = shlex.split(_game_cmd, posix=False)
        args.target_exe = parts[0]
        args.target_args = parts[1:]
    else:
        args.target_exe = None
        args.target_args = []
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

    port = 5000
    print(f"captureAIshi Web UI: http://127.0.0.1:{port}")
    webbrowser.open(f"http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
