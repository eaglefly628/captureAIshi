"""Demo mode: cloud-deployable client demo.

Active when env ``DEMOAISHI=1``. Short-circuits every route that would
otherwise drive a local subprocess, TCP socket, or OBS WebSocket so the
Flask app can be deployed to any PaaS without RenderDoc / a game / an
OBS instance.

Runtime behaviour:
- ``DemoSession`` runs a scripted timeline in a background thread that
  pushes realistic-looking log lines into ``_capture_state.logs`` and
  increments a fake pose counter, so the existing UI progress bar +
  log viewer animate exactly as in a real capture.
- ``canned_*`` helpers return shaped responses for the bridge / hacks /
  OBS endpoints so 注入菜单 and friends never see an error.

Step-1 scope: scaffolding only. No pre-baked frames yet (Output gallery
will be empty until step 2 ships ``demo/scenarios/<name>/frames/``).
"""

import logging
import os
import threading
import time

from web.state import _capture_state, _lock


def is_demo_mode() -> bool:
    """True when the process was started with ``DEMOAISHI=1`` in the env."""
    return os.environ.get("DEMOAISHI", "").strip() == "1"


# ── Scripted timeline ────────────────────────────────────────────────────────

# Pre-amble lines (emitted before the per-pose loop). Each tuple is
# (delay_seconds_after_previous, message). Times are spaced so the user
# can read along.
_PREAMBLE = [
    (0.0, "[CLEAN] Removing previous output: ./output/demo"),
    (0.4, "[STARTUP] Launching capture target via 爱萌捕捉"),
    (1.0, "[STARTUP] Game window detected on adapter 0 (NVIDIA RTX 4080)"),
    (0.6, "[BRIDGE] Connecting to renderdoc.dll (127.0.0.1:9999)..."),
    (0.5, "[BRIDGE] Connected. UWorld=0x12A4E0000 LocalPlayer=0x12A6F8240"),
    (0.4, "[INJECT] Loading hack profile: cyberpunk2077"),
    (0.6, "[INJECT] AOB scan @ camwrite (24 bytes): hit at 0x7FF6A2C18E40"),
    (0.4, "[INJECT] All sites switched to NOP, base register captured"),
    (0.5, "[CAPTURE] Trajectory loaded: 30 waypoints (smooth, 5 pts/segment)"),
    (0.3, "[CAPTURE] Beginning capture loop @ 1.5s/pose"),
]

_POSTAMBLE = [
    (0.4, "[CAPTURE] All poses done. Decoding 30 .rdc files..."),
    (1.2, "[CAPTURE] Decoded 30 captures: RGB + Depth + Normal triplets"),
    (0.3, "[CAPTURE] Wrote trajectory.json + frame index"),
    (0.2, "[BRIDGE] Disconnecting"),
    (0.2, "Capture finished."),
]


class DemoSession:
    """Background thread that emits the scripted timeline."""

    _instance = None  # type: ignore[assignment]
    _lock = threading.Lock()

    def __init__(self, total_poses: int = 30, capture_dwell_s: float = 0.45):
        self.total = total_poses
        self.dwell = capture_dwell_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _emit(self, msg: str) -> None:
        line = time.strftime("%Y-%m-%d %H:%M:%S") + f" [INFO] {msg}"
        with _lock:
            _capture_state["logs"].append(line)
            if len(_capture_state["logs"]) > 500:
                _capture_state["logs"] = _capture_state["logs"][-500:]

    def _sleep(self, seconds: float) -> bool:
        """Sleep, returning True when interrupted by stop()."""
        return self._stop.wait(timeout=seconds)

    def _run(self) -> None:
        try:
            self._emit("Demo capture session starting (DEMO_MODE)")
            self._emit(f"Total camera poses: {self.total}")
            for delay, msg in _PREAMBLE:
                if self._sleep(delay):
                    return
                self._emit(msg)
            for i in range(self.total):
                if self._sleep(self.dwell):
                    return
                self._emit(f"Pose {i + 1}/{self.total} captured")
            for delay, msg in _POSTAMBLE:
                if self._sleep(delay):
                    return
                self._emit(msg)
        except Exception as e:  # pragma: no cover -- defensive
            logging.exception("DemoSession crashed: %s", e)
            with _lock:
                _capture_state["error"] = str(e)
        finally:
            with _lock:
                _capture_state["running"] = False
            with DemoSession._lock:
                DemoSession._instance = None

    @classmethod
    def start(cls) -> bool:
        """Spawn a session if none is active. Returns False if one already runs."""
        with cls._lock:
            if cls._instance is not None:
                return False
            sess = cls()
            cls._instance = sess
        with _lock:
            _capture_state["running"] = True
            _capture_state["logs"] = []
            _capture_state["error"] = None
            _capture_state["output_dir"] = "./output/demo"
        sess._thread.start()
        return True

    @classmethod
    def stop(cls) -> None:
        with cls._lock:
            inst = cls._instance
        if inst is not None:
            inst._stop.set()


# ── Canned responses (no real IO) ────────────────────────────────────────────

_FAKE_PTRS = {
    "world_ptr": "0x12A4E0000",
    "localplayer_ptr": "0x12A6F8240",
    "camera_manager_ptr": "0x12A8B1000",
}


def canned_bridge_scan() -> dict:
    return {
        "ok": True,
        "uworld_found": True,
        "localplayer_found": True,
        "camera_manager_found": True,
        "engine_found": True,
        "gamethread_dispatch": True,
        **_FAKE_PTRS,
    }


def canned_bridge_rescan() -> dict:
    return {**canned_bridge_scan(), "raw": "uworld_found=1 localplayer_found=1 camera_manager_found=1"}


def canned_bridge_test(cmd: str) -> dict:
    """Single dispatcher for /api/bridge-test in demo mode."""
    cmd_low = (cmd or "").lower().strip()
    if cmd_low.startswith("__bridge_status"):
        resp = "uworld_found=1 localplayer_found=1 camera_manager_found=1 engine_found=1"
    elif "intercept_list" in cmd_low:
        resp = "site=0 name=camwrite addr=0x7FF6A2C18E40 mode=NOP size=24"
    elif "cam_mem_find" in cmd_low:
        resp = "found FMinimalViewInfo @ 0x12B7A8000"
    elif "cam_mem_read" in cmd_low:
        resp = "x=120.5 y=43.2 z=88.7 pitch=0.0 yaw=45.0 roll=0.0 fov=90.0"
    else:
        resp = "ok"
    return {"ok": True, "response": resp, "cmd": cmd}


def canned_inject() -> dict:
    return {"ok": True, "pid": 13337, "msg": "Bridge injected (demo mode, no real process)"}


def canned_hacks_apply(profile_id: str) -> dict:
    return {"ok": True, "result": {
        "installed": 1, "expected": 1, "profile_id": profile_id,
        "steps": [
            {"step": "uninstall", "ok": True, "response": "0 sites cleared"},
            {"step": "install", "intercept": "camwrite", "ok": True,
             "response": "matched at 0x7FF6A2C18E40"},
        ],
    }}


def canned_hacks_simple(label: str) -> dict:
    return {"ok": True, "result": {"action": label, "sites": 1}}


def canned_hacks_get_capture() -> dict:
    return {"ok": True, "slot": 0, "addr_hex": "0x12B7A8000", "addr_int": 0x12B7A8000}


def canned_hacks_read_pose(profile_id: str) -> dict:
    return {
        "ok": True, "profile_id": profile_id,
        "x": 120.5, "y": 43.2, "z": 88.7,
        "pitch": 0.0, "yaw": 45.0, "roll": 0.0, "fov": 90.0,
    }


def canned_hacks_write(profile_id: str) -> dict:
    return {"ok": True, "result": {"ok": True, "profile_id": profile_id, "wrote": True}}


def canned_obs_test() -> dict:
    return {"ok": True, "msg": "Connected to OBS at 127.0.0.1:4455 (demo)"}


def canned_obs_status() -> dict:
    return {"ok": True, "connected": True, "recording": False, "scene": "Capture"}


def canned_obs_setup() -> dict:
    return {"ok": True, "msg": "Demo: OBS scene 'Capture' would be auto-configured here."}


def canned_tools_analyze() -> dict:
    return {"ok": False, "error": "Demo mode: .rdc analysis is disabled (no renderdoccmd available)."}


def canned_trajectory_action(label: str) -> dict:
    return {"ok": True, "msg": f"Demo: trajectory {label} acknowledged."}
