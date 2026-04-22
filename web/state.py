"""Shared Flask app state: capture status, log handler, thread runner.

Routes in ``web.routes.*`` import from here instead of from ``web_ui`` to
avoid the circular import ``web_ui -> routes -> web_ui``.
"""

import logging
import threading
from pathlib import Path

from core.path_player import PathStore


# ── Capture session state (shared across routes) ─────────────────────────────

_capture_state = {
    "running": False,
    "logs": [],
    "error": None,
}
_lock = threading.Lock()
_stop_event = threading.Event()

_path_store = PathStore()


class WebLogHandler(logging.Handler):
    """Route log records into ``_capture_state['logs']`` for the UI poll."""

    def emit(self, record):
        msg = self.format(record)
        with _lock:
            _capture_state["logs"].append(msg)
            if len(_capture_state["logs"]) > 500:
                _capture_state["logs"] = _capture_state["logs"][-500:]


def _run_in_thread(args):
    """Run ``main.run_capture`` in a background thread, routing logs to UI."""
    from main import run_capture

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


# ── Config/validation constants (reused by /api/start + /api/games) ──────────

_VALID_DRIVERS = {"manual", "ue5", "unity", "cheatengine"}
_VALID_GRABBERS = {"none", "renderdoc", "screenshot"}
_VALID_CE_MODES = {"file", "socket"}

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
