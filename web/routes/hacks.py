"""Game hack profile operations: list/apply/lock/capture/write/read + inject."""

import subprocess
import sys

from flask import Blueprint, jsonify, request

bp = Blueprint("hacks", __name__)


@bp.route("/api/hacks/list", methods=["GET"])
def hacks_list():
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "profiles": game_profile.list_profiles()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/inject", methods=["POST"])
def inject_bridge():
    """Inject renderdoc.dll (bridge) into a running game process via renderdoccmd inject."""
    data = request.get_json(silent=True) or {}
    process_name = data.get("process_name", "").strip()
    renderdoc_path = data.get("renderdoc_path", "renderdoccmd").strip() or "renderdoccmd"
    if not process_name:
        return jsonify({"ok": False, "error": "process_name required"}), 400

    pid = _find_pid(process_name)
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


def _find_pid(process_name: str) -> int | None:
    """Return the PID for a process name, trying psutil then tasklist."""
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name"]):
            if proc.info["name"].lower() == process_name.lower():
                return proc.info["pid"]
        return None
    except ImportError:
        pass

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
                        return int(parts[1].strip('"'))
                    except ValueError:
                        pass
    return None


@bp.route("/api/hacks/apply/<profile_id>", methods=["POST"])
def hacks_apply(profile_id: str):
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


@bp.route("/api/hacks/lock", methods=["POST"])
def hacks_lock():
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "result": game_profile.lock_camera()})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503


@bp.route("/api/hacks/unlock", methods=["POST"])
def hacks_unlock():
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "result": game_profile.unlock_camera()})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503


@bp.route("/api/hacks/uninstall", methods=["POST"])
def hacks_uninstall():
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "result": game_profile.uninstall_all()})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503


@bp.route("/api/hacks/capture", methods=["POST"])
def hacks_capture():
    """Switch all sites to CAPTURE mode (NOP + snapshot base register)."""
    try:
        from drivers import game_profile
        return jsonify({"ok": True, "result": game_profile.capture_all()})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": f"bridge unreachable: {e}"}), 503


@bp.route("/api/hacks/get_capture", methods=["GET"])
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


@bp.route("/api/hacks/write/<profile_id>", methods=["POST"])
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


@bp.route("/api/hacks/read_pose/<profile_id>", methods=["GET"])
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
