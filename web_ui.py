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
    args = _build_args(data)

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


def _build_args(data: dict) -> Namespace:
    """Convert JSON form data to an argparse-like Namespace."""
    args = Namespace()
    args.volume_min = data.get("volume_min", [-5, 0, -5])
    args.volume_max = data.get("volume_max", [5, 3, 5])
    args.spacing = float(data.get("spacing", 2.0))
    args.smooth = bool(data.get("smooth", False))
    args.smooth_points = int(data.get("smooth_points", 5))
    args.cone_angle = float(data.get("cone_angle", 0))
    args.cone_samples = int(data.get("cone_samples", 8))
    args.cone_rings = int(data.get("cone_rings", 2))
    args.driver = data.get("driver", "manual")
    args.driver_host = data.get("driver_host", "127.0.0.1")
    args.driver_port = int(data.get("driver_port", 9999))
    args.ce_mode = data.get("ce_mode", "file")
    args.grabber = data.get("grabber", "none")
    args.target_exe = data.get("target_exe") or None
    args.no_hide_ui = bool(data.get("no_hide_ui", False))
    args.output_dir = Path(data.get("output_dir", "./output"))
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
