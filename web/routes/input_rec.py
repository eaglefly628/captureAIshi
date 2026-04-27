"""Input recording API: start/stop pynput recorder, list + load saved files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import Blueprint, jsonify, request

from utils.input_recorder import InputRecorder

bp = Blueprint("input_rec", __name__)
logger = logging.getLogger(__name__)

_recorder = InputRecorder()
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@bp.route("/api/input/start", methods=["POST"])
def input_start():
    body = request.get_json(silent=True) or {}
    out_dir = Path(str(body.get("output_dir", "output/ue5_obs")))
    if _recorder.is_recording:
        return jsonify({"ok": False, "error": "already recording"})
    _recorder.output_dir = REPO_ROOT / out_dir
    _recorder.start()
    try:
        import pynput  # noqa: F401
        backend = "pynput"
    except ImportError:
        backend = "stub (pynput not installed — no events will be captured)"
    logger.info(f"[INPUT] recording started, backend={backend}, dir={_recorder.output_dir}")
    return jsonify({"ok": True, "backend": backend})


@bp.route("/api/input/stop", methods=["POST"])
def input_stop():
    if not _recorder.is_recording:
        return jsonify({"ok": False, "error": "not recording"})
    saved = _recorder.stop()
    path_str = str(saved.relative_to(REPO_ROOT)) if saved else None
    logger.info(f"[INPUT] recording stopped, saved={path_str}, events={_recorder.event_count}")
    return jsonify({"ok": True, "file": path_str, "events": _recorder.event_count})


@bp.route("/api/input/status", methods=["GET"])
def input_status():
    return jsonify({
        "ok": True,
        "recording": _recorder.is_recording,
        "elapsed": round(_recorder.elapsed, 1),
        "events": _recorder.event_count,
    })


@bp.route("/api/input/files", methods=["GET"])
def input_files():
    """List input_*.json files under output/."""
    files = []
    for p in sorted(REPO_ROOT.glob("output/**/input_*.json"), reverse=True)[:50]:
        try:
            stat = p.stat()
            files.append({
                "path": str(p.relative_to(REPO_ROOT)),
                "name": p.name,
                "size": stat.st_size,
            })
        except OSError:
            pass
    return jsonify({"ok": True, "files": files})


@bp.route("/api/input/load", methods=["GET"])
def input_load():
    rel = request.args.get("path", "")
    if not rel:
        return jsonify({"ok": False, "error": "missing path"}), 400
    p = (REPO_ROOT / rel).resolve()
    if not str(p).startswith(str(REPO_ROOT)):
        return jsonify({"ok": False, "error": "invalid path"}), 400
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    return jsonify({"ok": True, **data})
