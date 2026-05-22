"""AI scene generation endpoints.

POST /api/scene/generate          -- generate + spawn (blocking, JSON result)
GET  /api/scene/generate_stream   -- SSE streaming: per-actor progress events
GET  /api/scene/catalog           -- list available warehouse asset classes
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from queue import Empty, Queue

from flask import Blueprint, Response, jsonify, request, stream_with_context

logger = logging.getLogger(__name__)

bp = Blueprint("scene", __name__)

_LAYOUT_DIR = Path("output/scene_layouts")

# ── catalog ────────────────────────────────────────────────────────────────


@bp.route("/api/scene/catalog", methods=["GET"])
def scene_catalog():
    from scene_gen.layout_gen import WAREHOUSE_CATALOG
    return jsonify({
        "ok": True,
        "catalog": [{"class": c[0]} for c in WAREHOUSE_CATALOG],
    })


# ── PCG volume bounds ──────────────────────────────────────────────────────


@bp.route("/api/scene/volume", methods=["GET"])
def scene_volume_get():
    """Return the last cached volume bounds, if any."""
    from scene_gen.volume_fetcher import read_cached_volume
    data = read_cached_volume()
    if data is None:
        return jsonify({"ok": False, "error": "no cached volume"}), 404
    return jsonify({"ok": True, "volume": data})


@bp.route("/api/scene/volume_fetch", methods=["POST"])
def scene_volume_fetch():
    """Query UE5 for a named volume's bounds.

    JSON body: {
        "name": "PCGBuilderVolume",
        "bridge_host": "127.0.0.1",
        "bridge_port": 9998,
        "timeout": 5.0
    }
    """
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "PCGBuilderVolume")).strip() or "PCGBuilderVolume"
    host = str(body.get("bridge_host", "127.0.0.1"))
    port = int(body.get("bridge_port", 9998))
    timeout = float(body.get("timeout", 5.0))

    from scene_gen.volume_fetcher import fetch_volume, VolumeFetchError
    try:
        data = fetch_volume(name=name, host=host, port=port, timeout=timeout)
    except VolumeFetchError as e:
        return jsonify({"ok": False, "error": str(e)}), 504
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "volume": data})


@bp.route("/api/scene/recommend_count", methods=["GET"])
def scene_recommend_count():
    """Recommend object count given volume size and density preset.

    Query: area_x (cm), area_y (cm), density (sparse|medium|dense)
    """
    try:
        ax = int(request.args.get("area_x", 3000))
        ay = int(request.args.get("area_y", 2000))
        density = request.args.get("density", "medium")
    except ValueError:
        return jsonify({"ok": False, "error": "bad area params"}), 400
    from scene_gen.layout_gen import recommend_count
    rec = recommend_count(ax, ay, density)
    return jsonify({"ok": True, **rec})


# ── blocking generate ───────────────────────────────────────────────────────


@bp.route("/api/scene/generate", methods=["POST"])
def scene_generate():
    """Generate layout + spawn actors (blocking).

    JSON body: {
        "prompt": str,
        "count": int (default 40),
        "floor_z": float (default 0.0),
        "area_x": int (cm, default 3000),
        "area_y": int (cm, default 2000),
        "min_gap": int (cm, default 150),
        "bridge_host": str (default "127.0.0.1"),
        "bridge_port": int (default 9998),
        "api_key": str (optional, else DEEPSEEK_API_KEY env),
        "spawn": bool (default true, set false to only generate JSON)
    }
    """
    body = request.get_json(silent=True) or {}
    prompt = str(body.get("prompt", "warehouse with mixed storage equipment")).strip()
    count = max(1, min(200, int(body.get("count", 40))))
    floor_z = float(body.get("floor_z", 0.0))
    area_x = int(body.get("area_x", 3000))
    area_y = int(body.get("area_y", 2000))
    min_gap = int(body.get("min_gap", 150))
    bridge_host = str(body.get("bridge_host", "127.0.0.1"))
    bridge_port = int(body.get("bridge_port", 9998))
    api_key = str(body.get("api_key", "")).strip() or None
    do_spawn = bool(body.get("spawn", True))

    try:
        from scene_gen.layout_gen import generate_layout
        actors = generate_layout(
            prompt=prompt, count=count, area_x=area_x, area_y=area_y,
            min_gap=min_gap, floor_z=floor_z, api_key=api_key,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": f"Layout generation failed: {e}"}), 500

    # Save to disk
    ts = int(time.time())
    layout_path = _LAYOUT_DIR / f"layout_{ts}.json"
    from scene_gen.ue_spawner import save_layout_json
    save_layout_json(actors, layout_path)

    result = {
        "ok": True,
        "count": len(actors),
        "layout_file": str(layout_path),
        "actors": actors,
        "bridge_connected": False,
        "spawned": 0,
    }

    if do_spawn:
        from scene_gen.ue_spawner import UESpawner
        spawner = UESpawner(host=bridge_host, port=bridge_port)
        spawn_result = spawner.spawn_layout(actors)
        result.update(spawn_result)

    return jsonify(result)


# ── SSE streaming generate ──────────────────────────────────────────────────


@bp.route("/api/scene/generate_stream")
def scene_generate_stream():
    """Server-Sent Events endpoint for real-time progress.

    Query params: same as POST /api/scene/generate body fields.
    Streams events:
      data: {"phase": "llm",   "msg": "Calling deepseek..."}
      data: {"phase": "spawn", "i": 1, "total": 40, "class": "SM_Crate_Large",
             "x": 100, "y": 200}
      data: {"phase": "done",  "total": 40, "spawned": 40, "failed": 0,
             "bridge_connected": false}
      data: {"phase": "error", "msg": "..."}
    """
    prompt = request.args.get("prompt", "warehouse with mixed storage equipment").strip()
    count = max(1, min(200, int(request.args.get("count", 40))))
    floor_z = float(request.args.get("floor_z", 0.0))
    area_x = int(request.args.get("area_x", 3000))
    area_y = int(request.args.get("area_y", 2000))
    centre_x = float(request.args.get("centre_x", 0.0))
    centre_y = float(request.args.get("centre_y", 0.0))
    min_gap = int(request.args.get("min_gap", 150))
    bridge_host = request.args.get("bridge_host", "127.0.0.1")
    bridge_port = int(request.args.get("bridge_port", 9998))
    api_key = request.args.get("api_key", "").strip() or None
    do_spawn = request.args.get("spawn", "true").lower() not in ("false", "0", "no")
    refresh_every = int(request.args.get("refresh_every", 1))

    q: Queue[str] = Queue()

    def _run():
        def _emit(obj: dict) -> None:
            q.put(json.dumps(obj, ensure_ascii=False))

        _emit({"phase": "llm", "msg": f"Calling deepseek-chat (count={count})..."})

        try:
            from scene_gen.layout_gen import generate_layout
            actors = generate_layout(
                prompt=prompt, count=count, area_x=area_x, area_y=area_y,
                min_gap=min_gap, floor_z=floor_z,
                centre_xy=(centre_x, centre_y), api_key=api_key,
            )
        except Exception as e:
            _emit({"phase": "error", "msg": str(e)})
            q.put(None)
            return

        _emit({"phase": "llm_done", "msg": f"Layout ready: {len(actors)} actors", "total": len(actors)})

        ts = int(time.time())
        layout_path = _LAYOUT_DIR / f"layout_{ts}.json"
        from scene_gen.ue_spawner import save_layout_json
        save_layout_json(actors, layout_path)

        if not do_spawn:
            _emit({"phase": "done", "total": len(actors), "spawned": 0,
                   "failed": 0, "bridge_connected": False, "spawn_skipped": True})
            q.put(None)
            return

        from scene_gen.ue_spawner import UESpawner
        spawner = UESpawner(host=bridge_host, port=bridge_port)

        connected = spawner.connect()
        _emit({"phase": "spawn_start", "bridge_connected": connected,
               "msg": "Bridge connected" if connected else "Bridge offline (logging only)"})

        total = len(actors)
        spawned = 0
        failed = 0

        for i, actor in enumerate(actors):
            from scene_gen.ue_spawner import _build_spawn_cmd
            cmd = _build_spawn_cmd(actor)
            if connected:
                resp = spawner._send(cmd)  # noqa: SLF001 -- internal helper
                ok = not resp.startswith("error")
                if refresh_every > 0 and (i + 1) % refresh_every == 0:
                    spawner._send("ke * SceneFoundry_RefreshViewport")  # noqa: SLF001
            else:
                ok = True  # offline: count as success for display

            if ok:
                spawned += 1
            else:
                failed += 1

            _emit({
                "phase": "spawn",
                "i": i + 1,
                "total": total,
                "class": actor["class"],
                "x": actor["x"],
                "y": actor["y"],
                "ok": ok,
            })

            if i < total - 1:
                time.sleep(0.04)

        if connected and refresh_every > 0:
            spawner._send("ke * SceneFoundry_RefreshViewport")  # noqa: SLF001

        spawner.disconnect()
        _emit({
            "phase": "done",
            "total": total,
            "spawned": spawned,
            "failed": failed,
            "bridge_connected": connected,
        })
        q.put(None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    @stream_with_context
    def _generator():
        yield "retry: 1000\n\n"
        while True:
            try:
                item = q.get(timeout=90)
            except Empty:
                yield ": keepalive\n\n"
                continue
            if item is None:
                break
            yield f"data: {item}\n\n"

    return Response(
        _generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
