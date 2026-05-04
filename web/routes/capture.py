"""Capture lifecycle + bridge-test + form defaults."""

import logging
import shutil
import threading

from flask import Blueprint, jsonify, request

from web.demo import (
    DemoSession, canned_bridge_test, is_demo_mode,
)
from web.helpers import _bridge_send, _build_args
from web.state import _capture_state, _lock, _run_in_thread, _stop_event

bp = Blueprint("capture", __name__)


@bp.route("/api/start", methods=["POST"])
def start_capture():
    with _lock:
        if _capture_state["running"]:
            return jsonify({"ok": False, "error": "Capture already running"}), 409

    if is_demo_mode():
        if not DemoSession.start():
            return jsonify({"ok": False, "error": "Demo session already running"}), 409
        return jsonify({"ok": True, "demo": True})

    data = request.json
    if data is None:
        return jsonify({"ok": False, "error": "Request body must be JSON"}), 400

    try:
        args = _build_args(data)
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

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


@bp.route("/api/stop", methods=["POST"])
def stop_capture():
    if is_demo_mode():
        DemoSession.stop()
        return jsonify({"ok": True, "demo": True})
    _stop_event.set()
    logging.info("Stop requested by user")
    return jsonify({"ok": True})


@bp.route("/api/status")
def capture_status():
    with _lock:
        out = {
            "running": _capture_state["running"],
            "logs": _capture_state["logs"],
            "error": _capture_state["error"],
        }
        # Demo mode only: tell the front-end how many poses are "done"
        # so the 3D viewer can render the trajectory progressively.
        if "demo_pose" in _capture_state:
            out["demo_pose"] = _capture_state["demo_pose"]
            out["demo_total"] = _capture_state.get("demo_total", 0)
        return jsonify(out)


@bp.route("/api/bridge-test", methods=["POST"])
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

    if is_demo_mode():
        return jsonify(canned_bridge_test(cmd))

    try:
        resp = _bridge_send(cmd, timeout=8.0)
        return jsonify({"ok": True, "response": resp, "cmd": cmd})
    except Exception:
        return jsonify({"ok": False, "error": "Bridge connection failed"}), 500


@bp.route("/api/defaults")
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
        "demo_mode": is_demo_mode(),
    })
