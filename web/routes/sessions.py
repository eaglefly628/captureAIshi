"""Session list / capture file listing / thumbnails / size stats."""

from pathlib import Path

from flask import Blueprint, jsonify, send_from_directory

from web.demo import filter_files_by_pose, is_demo_mode
from web.state import _capture_state, _lock

bp = Blueprint("sessions", __name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".exr"}


def _output_dir() -> str:
    with _lock:
        return _capture_state.get("output_dir", "./output")


def _safe_session_path(session: str, base: Path) -> Path | None:
    """Resolve a session name to a path, rejecting traversal attempts."""
    target = (base / session).resolve()
    if not target.is_relative_to(base.resolve()):
        return None
    return target


@bp.route("/api/sessions")
def list_sessions():
    """List capture session subdirectories under the base output dir."""
    output_dir = _output_dir()
    base = Path(output_dir).parent
    if not base.is_dir():
        return jsonify({"sessions": [], "active": ""})
    sessions = sorted(d.name for d in base.iterdir() if d.is_dir())
    active = Path(output_dir).name if Path(output_dir).is_dir() else ""
    return jsonify({"sessions": sessions, "active": active})


@bp.route("/api/captures")
@bp.route("/api/captures/<session>")
def list_captures(session=None):
    """List captured image files from a session directory."""
    output_dir = _output_dir()
    base = Path(output_dir).parent
    if session:
        target = _safe_session_path(session, base)
        if target is None:
            return jsonify({"error": "Invalid session path"}), 403
    else:
        target = Path(output_dir)
    files = []
    if target.is_dir():
        for f in sorted(target.rglob("*")):
            if f.suffix.lower() in _IMAGE_EXTS:
                files.append(f.relative_to(target).as_posix())
    if is_demo_mode():
        files = filter_files_by_pose(files)
    return jsonify({"files": files, "session": target.name if target.is_dir() else ""})


@bp.route("/api/captures/<session>/<path:filename>")
def serve_capture(session, filename):
    """Serve a captured image file from a session directory."""
    output_dir = _output_dir()
    base = Path(output_dir).parent
    target = _safe_session_path(session, base)
    if target is None:
        return jsonify({"error": "Invalid session path"}), 403
    return send_from_directory(str(target), filename)


@bp.route("/api/session-stats")
@bp.route("/api/session-stats/<session>")
def session_stats(session=None):
    """Return file count and total size for a session directory."""
    output_dir = _output_dir()
    base = Path(output_dir).parent
    if session:
        target = _safe_session_path(session, base)
        if target is None:
            return jsonify({"error": "Invalid session path"}), 403
    else:
        target = Path(output_dir)
    pairs = []
    if target.is_dir():
        for f in sorted(target.rglob("*")):
            if f.suffix.lower() in _IMAGE_EXTS:
                pairs.append((f.relative_to(target).as_posix(), f.stat().st_size))
    if is_demo_mode():
        allowed = set(filter_files_by_pose([n for n, _ in pairs]))
        pairs = [(n, s) for n, s in pairs if n in allowed]
    return jsonify({"count": len(pairs), "size_bytes": sum(s for _, s in pairs)})
