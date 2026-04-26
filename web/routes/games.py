"""Game Library listing + per-game capture config load/save."""

import json
from pathlib import Path

from flask import Blueprint, jsonify, request

from web.helpers import _game_slug
from web.state import (
    _DEFAULT_GAME_CONFIG,
    _GAME_CONFIGS_DIR,
    _GAME_LIBRARY_FILE,
)

bp = Blueprint("games", __name__)

_HACKS_DIR = Path("configs/hacks")


def _hack_only_games(library_profile_ids: set) -> list[dict]:
    """Synthesise library-shaped entries for ``configs/hacks/*.json`` profiles
    that are not already represented in ``game_library.json``.

    Why: lets a newly-added hack profile show up in the GAME LIBRARY panel
    without manually duplicating it in two catalogs.
    """
    extras: list[dict] = []
    if not _HACKS_DIR.exists():
        return extras
    for path in sorted(_HACKS_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        pid = data.get("id")
        if not pid or pid in library_profile_ids:
            continue
        extras.append({
            "name": data.get("display_name") or pid,
            "engine": data.get("engine", ""),
            "engine_version": data.get("engine_version", ""),
            "profile_id": pid,
            "process_name": (data.get("process_names") or [""])[0],
            "source": data.get("source", ""),
            "ac": "unknown",
            "test_status": "stub",
            "aob_source": data.get("credits", ""),
            "note": data.get("notes", ""),
        })
    return extras


@bp.route("/api/games")
def list_games():
    """Return the game library (curated + auto-merged hack profiles) with
    search/filter support.
    """
    games: list = []
    if _GAME_LIBRARY_FILE.exists():
        try:
            data = json.loads(_GAME_LIBRARY_FILE.read_text(encoding="utf-8"))
            games = list(data.get("games", []))
        except Exception:
            games = []

    existing_pids = {g.get("profile_id") for g in games if g.get("profile_id")}
    games += _hack_only_games(existing_pids)

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
