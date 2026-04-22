#!/usr/bin/env python3
"""captureAIshi — Web UI server.

Provides a browser-based interface to configure and launch captures.
All capture logic is reused from main.py — this is just a GUI shell.
"""

import json
import logging
import re
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
    """Send a command to the bridge for visual verification.
    Accepts JSON body {"cmd": "slomo 0.1"}. Only bridge internal commands
    (__bridge_*) and a safe allowlist of UE5 commands are permitted."""

    _SAFE_PREFIXES = (
        "__bridge_", "__cam_", "__timestop", "__hud_", "__hotsample",
        "__smooth", "__path_",
        "slomo ", "stat ", "showflag.", "r.", "t.",
        "toggledebugcamera", "showhud",
    )

    cmd = "__bridge_test"
    body = request.get_json(silent=True)
    if body and body.get("cmd"):
        cmd = str(body["cmd"]).strip()

    if not any(cmd.lower().startswith(p) for p in _SAFE_PREFIXES):
        return jsonify({"ok": False, "error": f"Command not in allowlist: {cmd}"}), 403

    try:
        resp = _bridge_send(cmd, timeout=8.0)
        return jsonify({"ok": True, "response": resp, "cmd": cmd})
    except Exception as e:
        return jsonify({"ok": False, "error": "Bridge connection failed"}), 500


# ---------------------------------------------------------------------------
# Game hack profiles (configs/hacks/*.json)
# ---------------------------------------------------------------------------


@app.route("/api/hacks/list", methods=["GET"])
def hacks_list():
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "profiles": game_profile.list_profiles()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/inject", methods=["POST"])
def inject_bridge():
    """Inject renderdoc.dll (bridge) into a running game process via renderdoccmd inject."""
    import subprocess
    import sys
    data = request.get_json(silent=True) or {}
    process_name = data.get("process_name", "").strip()
    renderdoc_path = data.get("renderdoc_path", "renderdoccmd").strip() or "renderdoccmd"
    if not process_name:
        return jsonify({"ok": False, "error": "process_name required"}), 400

    # Find PID of running process
    pid = None
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name"]):
            if proc.info["name"].lower() == process_name.lower():
                pid = proc.info["pid"]
                break
    except ImportError:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True,
            )
            for line in result.stdout.splitlines():
                if process_name.lower() in line.lower():
                    parts = line.split(",")
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1].strip('"'))
                            break
                        except ValueError:
                            pass

    if not pid:
        return jsonify({"ok": False, "error": f"Process '{process_name}' not found. Start the game first."}), 404

    try:
        inject_cmd = [renderdoc_path, "inject", "--PID", str(pid)]
        result = subprocess.run(inject_cmd, capture_output=True, text=True, timeout=30)
        out = (result.stdout or result.stderr or "").strip()
        inject_ok = (result.returncode == pid) or (result.returncode > 100) or \
                    (result.returncode == 0) or "Launched as ID" in out
        if not inject_ok:
            return jsonify({"ok": False, "error": f"renderdoccmd inject failed: {out}"}), 500
        return jsonify({"ok": True, "pid": pid, "msg": f"Bridge injected into {process_name} (PID={pid})"})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": f"renderdoccmd not found at: {renderdoc_path}"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "renderdoccmd inject timed out"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/hacks/apply/<profile_id>", methods=["POST"])
def hacks_apply(profile_id: str):
    # Validate slug: only a-z0-9_ allowed to avoid path traversal
    if not profile_id.replace("_", "").isalnum():
        return jsonify({"ok": False, "error": "bad profile id"}), 400
    try:
        from drivers import game_profile
        result = game_profile.apply_profile(profile_id)
        return jsonify({"ok": result["ok"], "result": result})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "profile not found"}), 404
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/hacks/lock", methods=["POST"])
def hacks_lock():
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "result": game_profile.lock_camera()})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503


@app.route("/api/hacks/unlock", methods=["POST"])
def hacks_unlock():
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "result": game_profile.unlock_camera()})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503


@app.route("/api/hacks/uninstall", methods=["POST"])
def hacks_uninstall():
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "result": game_profile.uninstall_all()})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503


@app.route("/api/hacks/capture", methods=["POST"])
def hacks_capture():
    """Switch all sites to CAPTURE mode (NOP + snapshot base register)."""
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "result": game_profile.capture_all()})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503


@app.route("/api/hacks/get_capture", methods=["GET"])
def hacks_get_capture():
    """Return captured struct address for a slot. ?slot=0 by default."""
    try:
        from drivers import game_profile
        slot = int(request.args.get("slot", "0"))
        addr = game_profile.get_captured_addr(slot)
        return jsonify({
            "ok": True,
            "slot": slot,
            "addr_hex": f"0x{addr:X}" if addr else None,
            "addr_int": addr,
        })
    except (ValueError, ConnectionError) as e:
        return jsonify({"ok": False, "error": str(e)}), 503


@app.route("/api/hacks/write/<profile_id>", methods=["POST"])
def hacks_write(profile_id: str):
    """Write a pose to the captured camera struct via profile offsets.

    JSON body: {"x":..,"y":..,"z":..,"pitch":..,"yaw":..,"roll":..,"fov":..,"slot":0}
    """
    if not profile_id.replace("_", "").isalnum():
        return jsonify({"ok": False, "error": "bad profile id"}), 400
    body = request.get_json(silent=True) or {}
    try:
        from drivers import game_profile
        result = game_profile.write_camera(
            profile_id,
            x=float(body.get("x", 0.0)), y=float(body.get("y", 0.0)),
            z=float(body.get("z", 0.0)),
            pitch=float(body.get("pitch", 0.0)), yaw=float(body.get("yaw", 0.0)),
            roll=float(body.get("roll", 0.0)),
            fov=float(body.get("fov", 90.0)),
            slot=int(body.get("slot", 0)),
        )
        return jsonify({"ok": result.get("ok", False), "result": result})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "profile not found"}), 404
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/hacks/read_pose/<profile_id>", methods=["GET"])
def hacks_read_pose(profile_id: str):
    """Read current camera pose from captured struct using profile offsets."""
    if not profile_id.replace("_", "").isalnum():
        return jsonify({"ok": False, "error": "bad profile id"}), 400
    try:
        from drivers import game_profile
        slot = int(request.args.get("slot", 0))
        return jsonify(game_profile.read_camera_pose(profile_id, slot))
    except ConnectionRefusedError:
        return jsonify({"ok": False, "error": "Bridge connection failed"}), 500


# ---------------------------------------------------------------------------
# Trajectory presets + 60 Hz player (Commit B)
# ---------------------------------------------------------------------------


@app.route("/api/trajectory/presets", methods=["GET"])
def trajectory_presets():
    """List available presets and their input schemas (for UI forms)."""
    from drivers import trajectory_presets as tp
    return jsonify({
        "ok": True,
        "presets": sorted(tp.PRESETS.keys()),
        "schemas": tp.PRESET_SCHEMA,
    })


def _generate_points(body: dict):
    """Parse {preset, params} and return (preset_name, points)."""
    from drivers import trajectory_presets as tp
    preset = body.get("preset")
    if not isinstance(preset, str):
        raise ValueError("missing 'preset'")
    params = body.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("'params' must be an object")
    return preset, tp.generate(preset, params)


@app.route("/api/trajectory/preview", methods=["POST"])
def trajectory_preview():
    """Generate a preset and return the sampled points (no playback).

    JSON body: {"preset": "orbit", "params": {...}}
    Response:  {"ok": true, "duration": 10.0, "points": [[t,x,y,z,p,y,r,fov], ...]}
    """
    body = request.get_json(silent=True) or {}
    try:
        _, pts = _generate_points(body)
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({
        "ok": True,
        "duration": pts[-1].t if pts else 0.0,
        "count": len(pts),
        "points": [p.as_tuple() for p in pts],
    })


@app.route("/api/trajectory/play", methods=["POST"])
def trajectory_play():
    """Start streaming a generated trajectory at ``rate_hz``.

    JSON body: {
        "preset": str, "params": {...},
        "profile_id": str,
        "rate_hz": float (default 60), "loop": bool, "slot": int
    }
    """
    body = request.get_json(silent=True) or {}
    profile_id = body.get("profile_id", "")
    if not isinstance(profile_id, str) or not profile_id.replace("_", "").isalnum():
        return jsonify({"ok": False, "error": "bad profile_id"}), 400
    try:
        preset, pts = _generate_points(body)
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    from drivers.trajectory_player import get_default_player
    try:
        result = get_default_player().play(
            profile_id=profile_id,
            points=pts,
            slot=int(body.get("slot", 0)),
            rate_hz=float(body.get("rate_hz", 60.0)),
            loop=bool(body.get("loop", False)),
            preset_name=preset,
            renderdoc_capture=bool(body.get("renderdoc_capture", False)),
            relative_origin=bool(body.get("relative_origin", False)),
            focus_delay=max(0.0, float(body.get("focus_delay", 5.0))),
        )
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "profile not found"}), 404
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify(result)


@app.route("/api/trajectory/stop", methods=["POST"])
def trajectory_stop():
    from drivers.trajectory_player import get_default_player
    return jsonify(get_default_player().stop())


@app.route("/api/trajectory/pause", methods=["POST"])
def trajectory_pause():
    from drivers.trajectory_player import get_default_player
    return jsonify(get_default_player().pause())


@app.route("/api/trajectory/resume", methods=["POST"])
def trajectory_resume():
    from drivers.trajectory_player import get_default_player
    return jsonify(get_default_player().resume())


@app.route("/api/trajectory/status", methods=["GET"])
def trajectory_status():
    from drivers.trajectory_player import get_default_player
    return jsonify({"ok": True, "status": get_default_player().status()})


# -- Saved trajectories -----------------------------------------------------
#
# Files at configs/trajectories/<name>.json carry a full
# {preset, params, rate_hz, loop, notes} blob so the UI can round-trip a
# custom trajectory (including the user's waypoint list). The "name" is
# pass-through user input, so we slug it before touching disk and reject
# anything that tries to escape the directory.

_TRAJECTORY_DIR = Path("configs/trajectories")
_TRAJECTORY_SLUG_RE = re.compile(r"[^a-zA-Z0-9_\-\.]+")


def _trajectory_slug(name: str) -> str:
    s = _TRAJECTORY_SLUG_RE.sub("_", (name or "").strip())
    if not s or s in (".", "..") or s.startswith("."):
        return ""
    return s[:120]


def _trajectory_path(name: str) -> Path | None:
    slug = _trajectory_slug(name)
    if not slug:
        return None
    return _TRAJECTORY_DIR / f"{slug}.json"


@app.route("/api/trajectory/saved", methods=["GET"])
def trajectory_saved_list():
    if not _TRAJECTORY_DIR.exists():
        return jsonify({"ok": True, "items": []})
    items = sorted(p.stem for p in _TRAJECTORY_DIR.glob("*.json"))
    return jsonify({"ok": True, "items": items})


@app.route("/api/trajectory/saved/<name>", methods=["GET"])
def trajectory_saved_get(name: str):
    path = _trajectory_path(name)
    if path is None:
        return jsonify({"ok": False, "error": "bad name"}), 400
    if not path.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    data["ok"] = True
    return jsonify(data)


@app.route("/api/trajectory/save", methods=["POST"])
def trajectory_saved_save():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    path = _trajectory_path(name) if isinstance(name, str) else None
    if path is None:
        return jsonify({"ok": False, "error": "bad name"}), 400
    preset = body.get("preset")
    from drivers import trajectory_presets as tp
    if not isinstance(preset, str) or preset not in tp.PRESETS:
        return jsonify({"ok": False, "error": "preset must be one of "
                        + str(sorted(tp.PRESETS))}), 400
    params = body.get("params", {})
    if not isinstance(params, dict):
        return jsonify({"ok": False, "error": "'params' must be an object"}), 400
    # Validate by generating -- catches bad param values early.
    try:
        tp.generate(preset, params)
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": f"invalid params: {e}"}), 400

    payload = {
        "schema_version": 1,
        "name": path.stem,
        "preset": preset,
        "params": params,
        "rate_hz": float(body.get("rate_hz", 60.0)),
        "loop": bool(body.get("loop", False)),
        "notes": str(body.get("notes", "")),
    }
    _TRAJECTORY_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "path": str(path), "name": path.stem})


@app.route("/api/trajectory/saved/<name>", methods=["DELETE"])
def trajectory_saved_delete(name: str):
    path = _trajectory_path(name)
    if path is None:
        return jsonify({"ok": False, "error": "bad name"}), 400
    if not path.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    path.unlink()
    return jsonify({"ok": True})


@app.route("/api/bridge/scan_status", methods=["GET"])
def bridge_scan_status():
    """Query current UWorld + LocalPlayer + CameraManager scan state."""
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
            "camera_manager_found": status.get("camera_manager_found") == "1",
            "world_ptr": status.get("world_ptr", "0x0"),
            "localplayer_ptr": status.get("localplayer_ptr", "0x0"),
            "camera_manager_ptr": status.get("camera_manager_ptr", "0x0"),
            "engine_found": status.get("engine_found") == "1",
            "gamethread_dispatch": status.get("gamethread_dispatch") == "1",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/bridge/rescan", methods=["POST"])
def bridge_rescan():
    """Trigger UWorld + LocalPlayer + CameraManager re-scan in the bridge.
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
            "camera_manager_found": result.get("camera_manager_found") == "1",
            "world_ptr": result.get("world_ptr", "0x0"),
            "localplayer_ptr": result.get("localplayer_ptr", "0x0"),
            "camera_manager_ptr": result.get("camera_manager_ptr", "0x0"),
            "raw": raw,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": "Bridge connection failed"}), 500
    finally:
        s.close()


@app.route("/api/defaults")
def defaults():
    """Return default parameter values for the form."""
    return jsonify({
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
    "target_exe": "",
    "output_dir": "./output",
    "launch_resx": 1920,
    "launch_resy": 1080,
    "launch_windowed": True,
    "launch_log": False,
    "streaming": True,
    "streaming_settle": 0.5,
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
    config = dict(_DEFAULT_GAME_CONFIG)
    if path.exists():
        try:
            config.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    config["_slug"] = slug
    return jsonify(config)


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


def _hack_profile_data(profile_id: str, target_exe: str = "") -> dict:
    """Return the hack profile JSON dict, or {} if not found.

    Looks up by profile_id first; if empty or unknown, falls back to matching
    the basename of target_exe against each profile's process_names.
    """
    hacks_dir = Path(__file__).resolve().parent / "configs" / "hacks"

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
