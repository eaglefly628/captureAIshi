"""Trajectory preset generation + 60 Hz player + saved trajectory files."""

import json
import re
from pathlib import Path

from flask import Blueprint, jsonify, request

bp = Blueprint("trajectory", __name__)


@bp.route("/api/trajectory/presets", methods=["GET"])
def trajectory_presets():
    """List available presets and their input schemas (for UI forms)."""
    from drivers import trajectory_presets as tp
    return jsonify({
        "ok": True,
        "presets": sorted(tp.PRESETS.keys()),
        "schemas": tp.PRESET_SCHEMA,
    })


def _generate_points(body: dict):
    """Parse {preset, params} and return (preset_name, fine_path, capture_indices).

    The returned ``fine_path`` is a dense sampling (``FINE_PATH_SAMPLES``) for
    smooth 3D preview and smooth camera streaming; ``capture_indices`` are
    the user's sample-count evenly-spaced indices into that path, i.e. the
    waypoints where RDC captures are fired.
    """
    from drivers import trajectory_presets as tp
    preset = body.get("preset")
    if not isinstance(preset, str):
        raise ValueError("missing 'preset'")
    params = body.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("'params' must be an object")
    fine_path, indices = tp.generate_smooth(preset, params)
    return preset, fine_path, indices


@bp.route("/api/trajectory/preview", methods=["POST"])
def trajectory_preview():
    """Generate a preset and return the sampled points (no playback).

    JSON body: {"preset": "orbit", "params": {...}}
    Response:  {"ok": true, "duration": 10.0, "points": [[t,x,y,z,p,y,r,fov], ...]}
    """
    body = request.get_json(silent=True) or {}
    try:
        _, pts, indices = _generate_points(body)
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({
        "ok": True,
        "duration": pts[-1].t if pts else 0.0,
        "count": len(pts),
        # Fine path for the 3D preview polyline + live camera streaming.
        "points": [p.as_tuple() for p in pts],
        # Indices into ``points`` where RDC captures are fired (user's
        # sample count, evenly spaced). UI draws FOV + arrow at each.
        "capture_indices": indices,
        "capture_count": len(indices),
    })


@bp.route("/api/trajectory/play", methods=["POST"])
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
        preset, pts, capture_indices = _generate_points(body)
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # If the active session is a RenderDoc grabber, route post-loop .rdc
    # files through its export_batch for PNG decode. Without a live
    # grabber (Start button not pressed, or non-renderdoc grabber), the
    # player just streams poses / fires triggers and skips decode.
    from web import state as _web_state
    grabber = _web_state.get_active_grabber()
    capture_dir = None
    decode_callback = None
    if grabber is not None and hasattr(grabber, "export_batch"):
        capture_dir = getattr(grabber, "capture_dir", None)
        if capture_dir is not None:
            # Canonical output_dir = the one /api/start recorded for this
            # session. Fall back to "./output" if not set yet.
            with _web_state._lock:
                out_str = _web_state._capture_state.get(
                    "output_dir", "./output",
                )
            output_dir = Path(out_str)

            def _decode(rdc_paths):
                import logging as _log
                _log.info("[DECODE] exporting %d .rdc -> %s",
                          len(rdc_paths), output_dir)
                try:
                    results = grabber.export_batch(rdc_paths, output_dir)
                    _log.info("[DECODE] export_batch returned %d results",
                              len(results))
                    frames_dir = output_dir / "frames"
                    for i, ((rgb, depth, normal), rdc_path) in enumerate(
                        zip(results, rdc_paths)
                    ):
                        if rdc_path is None:
                            continue
                        try:
                            grabber.save_frame(
                                rgb, depth, frames_dir, i,
                                base_name=Path(rdc_path).stem, normal=normal,
                            )
                        except Exception as _se:
                            _log.error("[DECODE] save_frame %d failed: %s", i, _se)
                except Exception as _e:
                    _log.error("[DECODE] export_batch failed: %s", _e)

            decode_callback = _decode

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
            capture_interval=max(0.1, float(body.get("capture_interval", 1.5))),
            capture_dir=capture_dir,
            decode_callback=decode_callback,
            capture_indices=capture_indices,
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


@bp.route("/api/trajectory/stop", methods=["POST"])
def trajectory_stop():
    from drivers.trajectory_player import get_default_player
    return jsonify(get_default_player().stop())


@bp.route("/api/trajectory/pause", methods=["POST"])
def trajectory_pause():
    from drivers.trajectory_player import get_default_player
    return jsonify(get_default_player().pause())


@bp.route("/api/trajectory/resume", methods=["POST"])
def trajectory_resume():
    from drivers.trajectory_player import get_default_player
    return jsonify(get_default_player().resume())


@bp.route("/api/trajectory/status", methods=["GET"])
def trajectory_status():
    from drivers.trajectory_player import get_default_player
    return jsonify({"ok": True, "status": get_default_player().status()})


@bp.route("/api/trajectory/decode", methods=["POST"])
def trajectory_decode():
    """Manually kick ``grabber.export_batch`` for .rdc files on disk.

    Normally the rdc-step Play path auto-decodes on loop completion. This
    endpoint is for re-running the decode, or decoding after a session
    where auto-decode was skipped.

    Body (optional): {"paths": ["abs.rdc", ...]}. If ``paths`` is absent
    or empty, every .rdc file in the active grabber's capture_dir is
    exported (sorted by mtime so the output order matches capture order).

    Requires an active RenderDoc grabber (the Start button must have
    been used to launch the session). Returns immediately; decode runs
    on a background thread and the player state -> ``exporting`` while
    it's in flight.
    """
    from web import state as _web_state
    grabber = _web_state.get_active_grabber()
    if grabber is None or not hasattr(grabber, "export_batch"):
        return jsonify({
            "ok": False,
            "error": "no active RenderDoc grabber (Start a session first)",
        }), 409
    capture_dir = getattr(grabber, "capture_dir", None)
    if capture_dir is None:
        return jsonify({
            "ok": False,
            "error": "active grabber has no capture_dir",
        }), 500

    body = request.get_json(silent=True) or {}
    raw_paths = body.get("paths")
    if isinstance(raw_paths, list) and raw_paths:
        rdc_paths = [Path(str(p)) for p in raw_paths]
    else:
        rdc_paths = sorted(
            Path(capture_dir).glob("*.rdc"),
            key=lambda q: q.stat().st_mtime,
        )
    if not rdc_paths:
        return jsonify({
            "ok": False,
            "error": f"no .rdc files in {capture_dir}",
        }), 404

    with _web_state._lock:
        out_str = _web_state._capture_state.get("output_dir", "./output")
    output_dir = Path(out_str)

    from drivers.trajectory_player import get_default_player
    player = get_default_player()

    import threading as _threading
    import logging as _logging

    def _run_decode():
        with player._lock:
            prev_state = player._status.state
            player._status.state = "exporting"
        _logging.info(
            "[DECODE] (manual) exporting %d .rdc -> %s",
            len(rdc_paths), output_dir,
        )
        try:
            results = grabber.export_batch(rdc_paths, output_dir)
            _logging.info(
                "[DECODE] export_batch returned %d results", len(results),
            )
            frames_dir = output_dir / "frames"
            for i, ((rgb, depth, normal), rdc_path) in enumerate(
                zip(results, rdc_paths)
            ):
                if rdc_path is None:
                    continue
                try:
                    grabber.save_frame(
                        rgb, depth, frames_dir, i,
                        base_name=Path(rdc_path).stem, normal=normal,
                    )
                except Exception as se:
                    _logging.error("[DECODE] save_frame %d failed: %s", i, se)
        except Exception as e:
            _logging.error("[DECODE] export_batch failed: %s", e)
        finally:
            with player._lock:
                if player._status.state == "exporting":
                    player._status.state = prev_state if prev_state != "exporting" else "idle"

    _threading.Thread(
        target=_run_decode, name="manual-decode", daemon=True,
    ).start()

    return jsonify({
        "ok": True,
        "count": len(rdc_paths),
        "output_dir": str(output_dir),
        "capture_dir": str(capture_dir),
    })


# ── Saved trajectories ───────────────────────────────────────────────────────
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


@bp.route("/api/trajectory/saved", methods=["GET"])
def trajectory_saved_list():
    if not _TRAJECTORY_DIR.exists():
        return jsonify({"ok": True, "items": []})
    items = sorted(p.stem for p in _TRAJECTORY_DIR.glob("*.json"))
    return jsonify({"ok": True, "items": items})


@bp.route("/api/trajectory/saved/<name>", methods=["GET"])
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


@bp.route("/api/trajectory/save", methods=["POST"])
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


@bp.route("/api/trajectory/saved/<name>", methods=["DELETE"])
def trajectory_saved_delete(name: str):
    path = _trajectory_path(name)
    if path is None:
        return jsonify({"ok": False, "error": "bad name"}), 400
    if not path.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    path.unlink()
    return jsonify({"ok": True})
