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

# Active RenderDoc grabber instance from the currently running session
# (Start button -> main.run_capture). The trajectory Play route reads this
# to route the per-waypoint .rdc files through ``grabber.export_batch`` for
# PNG decode after the rdc-step loop ends. ``None`` when no session is
# active or when the session uses a non-renderdoc grabber.
_active_grabber = None

_path_store = PathStore()

# Per-pose timestamps (seconds since recorder.start()) accumulated during a
# session. Drained by the recorder on stop() and written to
# video_metadata.json. List-of-floats; index aligns with trajectory.json.
_pose_timestamps: list = []
_recorder_t0_monotonic = None  # float | None: time.monotonic() when recording started


def set_recorder_t0(t0: float) -> None:
    """Publish the recorder's start time so routes can compute pose offsets."""
    global _recorder_t0_monotonic
    with _lock:
        _recorder_t0_monotonic = float(t0)


def clear_recorder_t0() -> None:
    global _recorder_t0_monotonic
    with _lock:
        _recorder_t0_monotonic = None


def record_pose_timestamp_now() -> None:
    """If video recording is active, append the current offset to the buffer."""
    import time as _time
    with _lock:
        t0 = _recorder_t0_monotonic
    if t0 is None:
        return
    record_pose_timestamp(_time.monotonic() - t0)


def record_pose_timestamp(t_seconds: float) -> None:
    """Append a pose-capture timestamp to the active session buffer."""
    with _lock:
        _pose_timestamps.append(round(float(t_seconds), 4))


def drain_pose_timestamps() -> list:
    """Return and clear the accumulated pose timestamps."""
    global _pose_timestamps
    with _lock:
        out = list(_pose_timestamps)
        _pose_timestamps = []
    return out


def reset_pose_timestamps() -> None:
    """Discard any buffered timestamps. Called at session start."""
    global _pose_timestamps
    with _lock:
        _pose_timestamps = []


def set_active_grabber(grabber) -> None:
    """Record the grabber for the currently running capture session.

    Called by ``main.run_capture`` after ``grabber.setup()`` succeeds and
    again with ``None`` in its finally block.
    """
    global _active_grabber
    with _lock:
        _active_grabber = grabber


def get_active_grabber():
    """Return the active grabber, or ``None`` if no session is running."""
    with _lock:
        return _active_grabber


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
