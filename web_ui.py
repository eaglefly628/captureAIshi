#!/usr/bin/env python3
"""captureAIshi — Web UI server.

Provides a browser-based interface to configure and launch captures.
All capture logic is reused from main.py — this is just a GUI shell.
"""

import json
import logging
import threading
import time
import webbrowser
from argparse import Namespace
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from main import run_capture

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")

# Shared state for capture progress
_capture_state = {
    "running": False,
    "logs": [],
    "error": None,
}
_lock = threading.Lock()


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

    with _lock:
        _capture_state["running"] = True
        _capture_state["logs"] = []
        _capture_state["error"] = None

    thread = threading.Thread(target=_run_in_thread, args=(args,), daemon=True)
    thread.start()

    return jsonify({"ok": True})


@app.route("/api/status")
def capture_status():
    with _lock:
        return jsonify({
            "running": _capture_state["running"],
            "logs": _capture_state["logs"],
            "error": _capture_state["error"],
        })


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
    })


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

    args.target_exe = str(data.get("target_exe", "")) or None
    args.no_hide_ui = bool(data.get("no_hide_ui", False))
    args.output_dir = Path(str(data.get("output_dir", "./output")))
    args.dry_run = bool(data.get("dry_run", False))
    return args


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
        with _lock:
            _capture_state["error"] = str(e)
        logging.error(f"Capture failed: {e}")
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
