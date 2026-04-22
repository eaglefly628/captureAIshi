"""Game Library listing + per-game capture config load/save."""

import json

from flask import Blueprint, jsonify, request

from web.helpers import _game_slug
from web.state import (
    _DEFAULT_GAME_CONFIG,
    _GAME_CONFIGS_DIR,
    _GAME_LIBRARY_FILE,
)

bp = Blueprint("games", __name__)


@bp.route("/api/games")
def list_games():
    """Return the game library with search/filter support."""
    if not _GAME_LIBRARY_FILE.exists():
        return jsonify({"games": []})
    try:
        data = json.loads(_GAME_LIBRARY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"games": []})

    games = data.get("games", [])
    q = request.args.get("q", "").strip().lower()
    engine = request.args.get("engine", "").strip().lower()

    if q:
        games = [g for g in games if q in g["name"].lower()]
    if engine:
        games = [g for g in games if g.get("engine", "").lower() == engine]

    for g in games:
        slug = _game_slug(g["name"])
        g["slug"] = slug
        g["has_config"] = (_GAME_CONFIGS_DIR / f"{slug}.json").exists()

    return jsonify({"games": games, "total": len(games)})


@bp.route("/api/games/<slug>/config", methods=["GET"])
def get_game_config(slug):
    """Load per-game capture config. Returns defaults if none saved."""
    slug = _game_slug(slug)
    if not slug:
        return jsonify({"error": "Invalid game slug"}), 400
    path = _GAME_CONFIGS_DIR / f"{slug}.json"
    config = dict(_DEFAULT_GAME_CONFIG)
    if path.exists():
        try:
            config.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    config["_slug"] = slug
    return jsonify(config)


@bp.route("/api/games/<slug>/config", methods=["POST"])
def save_game_config(slug):
    """Save per-game capture config."""
    slug = _game_slug(slug)
    if not slug:
        return jsonify({"error": "Invalid game slug"}), 400
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    _GAME_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    data.pop("_slug", None)
    data.pop("_profile_name", None)
    path = _GAME_CONFIGS_DIR / f"{slug}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True})
