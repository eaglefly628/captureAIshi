"""Camera path CRUD + node CRUD + interpolation."""

from flask import Blueprint, jsonify, request

from core.path_player import interpolate_path
from web.state import _path_store

bp = Blueprint("paths", __name__)


@bp.route("/api/paths")
def list_paths():
    """List all saved camera paths."""
    return jsonify(_path_store.list_all())


@bp.route("/api/path", methods=["POST"])
def create_path():
    """Create a new camera path."""
    data = request.json or {}
    name = str(data.get("name", "Untitled")).strip() or "Untitled"
    cp = _path_store.create(name=name)
    return jsonify(cp.to_dict()), 201


@bp.route("/api/path/<path_id>")
def get_path(path_id):
    """Get a camera path by ID."""
    cp = _path_store.get(path_id)
    if not cp:
        return jsonify({"error": "Path not found"}), 404
    return jsonify(cp.to_dict())


@bp.route("/api/path/<path_id>", methods=["PUT"])
def update_path(path_id):
    """Update path properties (name, loop, nodes)."""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    cp = _path_store.update(path_id, data)
    if not cp:
        return jsonify({"error": "Path not found"}), 404
    return jsonify(cp.to_dict())


@bp.route("/api/path/<path_id>", methods=["DELETE"])
def delete_path(path_id):
    """Delete a camera path."""
    if _path_store.delete(path_id):
        return jsonify({"ok": True})
    return jsonify({"error": "Path not found"}), 404


@bp.route("/api/path/<path_id>/node", methods=["POST"])
def add_path_node(path_id):
    """Add a node to a camera path."""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    index = data.pop("index", -1)
    cp = _path_store.add_node(path_id, data, index=index)
    if not cp:
        return jsonify({"error": "Path not found"}), 404
    return jsonify(cp.to_dict())


@bp.route("/api/path/<path_id>/node/<int:node_idx>", methods=["PUT"])
def update_path_node(path_id, node_idx):
    """Update a specific node in a camera path."""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    cp = _path_store.update_node(path_id, node_idx, data)
    if not cp:
        return jsonify({"error": "Path or node not found"}), 404
    return jsonify(cp.to_dict())


@bp.route("/api/path/<path_id>/node/<int:node_idx>", methods=["DELETE"])
def delete_path_node(path_id, node_idx):
    """Delete a specific node from a camera path."""
    cp = _path_store.delete_node(path_id, node_idx)
    if not cp:
        return jsonify({"error": "Path or node not found"}), 404
    return jsonify(cp.to_dict())


@bp.route("/api/path/<path_id>/interpolate")
def interpolate_path_route(path_id):
    """Get interpolated path samples for 3D visualization."""
    cp = _path_store.get(path_id)
    if not cp:
        return jsonify({"error": "Path not found"}), 404
    samples_str = request.args.get("samples", "20")
    try:
        samples_per_seg = max(2, min(100, int(samples_str)))
    except ValueError:
        samples_per_seg = 20
    samples = interpolate_path(cp, samples_per_segment=samples_per_seg)
    return jsonify({"samples": samples, "total_duration": cp.total_duration})
