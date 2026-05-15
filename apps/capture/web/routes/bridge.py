"""Bridge UWorld/LocalPlayer/CameraManager scan status + rescan."""

from flask import Blueprint, jsonify

from web.demo import canned_bridge_rescan, canned_bridge_scan, is_demo_mode
from web.helpers import _bridge_send

bp = Blueprint("bridge", __name__)


def _parse_kv(raw: str) -> dict:
    """Parse space-separated 'key=value' pairs (bridge status format)."""
    out = {}
    for pair in raw.split():
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k] = v
    return out


@bp.route("/api/bridge/scan_status", methods=["GET"])
def bridge_scan_status():
    """Query current UWorld + LocalPlayer + CameraManager scan state."""
    if is_demo_mode():
        return jsonify(canned_bridge_scan())
    try:
        status = _parse_kv(_bridge_send("__bridge_status", timeout=5.0))
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


@bp.route("/api/bridge/rescan", methods=["POST"])
def bridge_rescan():
    """Trigger UWorld + LocalPlayer + CameraManager re-scan in the bridge.
    Call this after map load. Bridge clears stale pointers and rescans."""
    if is_demo_mode():
        return jsonify(canned_bridge_rescan())
    try:
        raw = _bridge_send("__bridge_rescan_objects", timeout=35.0)
        result = _parse_kv(raw)
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
