"""Adore Robot -- UE5 PCG robot training scene foundry.

Flask app on :5001. Three views:

  /        ADORE operator console (claude design, SVG iso viewport)
  /3d      Three.js interactive 3D viewport (show-and-tell demo)
  /dev     developer MCP bridge (老白 v0.3.3 #4)

Setup (real MCP):
  1. UE5.8 Editor: enable AI Assistant + Toolset Registry + Unreal MCP +
     All Toolsets plugins, restart.
  2. UE editor console: ModelContextProtocol.StartServer  (or set
     bAutoStartServer in Editor Preferences -> Model Context Protocol).
  3. python apps/adore_robot/main.py  -> http://127.0.0.1:5001

Setup (demo only, no UE):
  pip install flask requests
  set DEEPSEEK_API_KEY=...        # optional, real LLM
  python apps/adore_robot/main.py
"""

from __future__ import annotations

import collections
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path


def _load_dotenv():
    """Minimal .env loader -- no external dependency.

    Reads apps/adore_robot/.env if present and sets KEY=VALUE pairs into
    os.environ. Real shell env vars always win (we never overwrite). The
    .env file is gitignored, so keys never reach the repo.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    loaded = []
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
            loaded.append(key)
    if loaded:
        print(f"[adore_robot] .env loaded: {', '.join(loaded)}", flush=True)


_load_dotenv()

from flask import Flask, Response, jsonify, render_template, request, send_file

from mcp_client import UnrealMCPClient
from demo.prompts import SYSTEM_PROMPT, UPDATE_SCENE_TOOL
from demo.demo_tools import (
    DEMO_TOOLS, DEMO_TOOL_NAMES, dispatch as dispatch_demo, _clamp_xy,
    dispatch_warehouse,
)
from demo.runner import DemoJobRegistry
from demo.thumbnail import render_thumbnail_svg
from llm import Message, make_llm_client
from llm.factory import auto_detect_provider

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "web" / "templates"
STATIC = ROOT / "web" / "static"
CONFIGS_SCENES = ROOT / "configs" / "scenes"

# Surfaced in /api/status and the TopBar brand chip. Bump per
# .claude/rules/versioning.md when changes affect inter-agent contracts.
APP_VERSION = "0.4.0"
APP_CHANNEL = "demo-v0"

MCP_URL = os.environ.get("UNREAL_MCP_URL", "http://127.0.0.1:8000/mcp")

app = Flask(
    __name__,
    template_folder=str(TEMPLATES),
    static_folder=str(STATIC),
    static_url_path="/static",
)
mcp = UnrealMCPClient(url=MCP_URL)
jobs = DemoJobRegistry()


# ── MCP init progress (real-time progress bar source) ───────────────────
# UI polls /api/mcp/init to know which toolset is loading right now.
INIT_PROGRESS: dict = {
    "started": False,
    "done": False,
    "ok": None,
    "phase": "idle",
    "toolset": "",
    "current": 0,
    "total": 5,  # 1 handshake + 1 prime + 4 toolsets (typical)
    "steps": [],
    "started_at": 0.0,
    "elapsed_ms": 0,
    "error": None,
}
_init_lock = threading.Lock()


def _init_reset() -> None:
    INIT_PROGRESS.update({
        "started": True, "done": False, "ok": None,
        "phase": "handshake", "toolset": "",
        "current": 0, "total": 5,
        "steps": [], "started_at": time.time(),
        "elapsed_ms": 0, "error": None,
    })


def _init_step(phase: str, current: int, total: int, toolset: str,
               status: str) -> None:
    INIT_PROGRESS["phase"] = phase
    INIT_PROGRESS["toolset"] = toolset
    INIT_PROGRESS["current"] = current
    INIT_PROGRESS["total"] = total
    INIT_PROGRESS["elapsed_ms"] = int((time.time() - INIT_PROGRESS["started_at"]) * 1000)
    INIT_PROGRESS["steps"].append({
        "phase": phase, "toolset": toolset, "status": status,
        "at_ms": INIT_PROGRESS["elapsed_ms"],
    })


def _run_init() -> None:
    try:
        mcp.initialize()
        _init_step("handshake", 1, 5, "session", "done")

        def cb(ev: dict) -> None:
            total = 1 + (ev.get("total") or 4)  # +1 for handshake
            _init_step(ev.get("phase", "loading"),
                       1 + (ev.get("current") or 0),
                       total,
                       ev.get("toolset", ""),
                       ev.get("status", "running"))

        mcp.auto_load_toolsets(progress_cb=cb)
        INIT_PROGRESS["done"] = True
        INIT_PROGRESS["ok"] = True
        INIT_PROGRESS["phase"] = "ready"
        INIT_PROGRESS["elapsed_ms"] = int((time.time() - INIT_PROGRESS["started_at"]) * 1000)
    except Exception as e:
        INIT_PROGRESS["done"] = True
        INIT_PROGRESS["ok"] = False
        INIT_PROGRESS["phase"] = "error"
        INIT_PROGRESS["error"] = f"{type(e).__name__}: {e}"


def _kick_init(force: bool = False) -> None:
    """Idempotent kick: start init thread if not running. force=True
    re-runs even if a previous run succeeded (e.g. UE was restarted)."""
    with _init_lock:
        if INIT_PROGRESS["started"] and not INIT_PROGRESS["done"]:
            return
        if INIT_PROGRESS["done"] and INIT_PROGRESS["ok"] and not force:
            return
        _init_reset()
        threading.Thread(target=_run_init, daemon=True).start()


def _load_scenes() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not CONFIGS_SCENES.exists():
        return out
    for f in sorted(CONFIGS_SCENES.glob("*_v0.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            scene_type = data.get("scene_type") or f.stem.replace("_v0", "")
            out[scene_type] = data
        except Exception:
            continue
    return out


SCENES = _load_scenes()

# Per-level PCG status cache. Refreshed lazily when the cached level
# differs from mcp's current_level cache. {level_path: {has_graph,
# graph_path, pcg_component_ref, checked_at}}
PCG_STATUS_CACHE: dict = {}

PCG_AVAILABLE_HINT = """
=== PCG MODE AVAILABLE IN THIS LEVEL ===

This level has a PCG Volume with a bound graph asset.  In addition to
the direct-actor tools, you can use:

- update_scene(scene_id, pcg_params, rationale) -- write to PCG Graph
  Parameters. Use this when the user is adjusting parameters that
  affect the WHOLE scene at once -- "shelf 密度 0.9 / seed 换一个 /
  房间宽 25 米 / 通道留 3 米 / 加 2 个工人". The PCG graph re-sims
  with the new params and 30+ actors refresh in one call.

Routing rule: single-object intent -> spawn_object/spawn_batch. Whole-
scene parameter intent -> update_scene. If user says "加 1 个叉车" use
spawn_object even when PCG is available (it's a single-object intent).
"""


def _get_cached_pcg_status() -> dict:
    """Returns current level's PCG status, refreshing the cache if the
    UE current_level changed.  Falls back to {} on MCP errors -- caller
    treats absent has_graph as 'no PCG mode'."""
    try:
        lvl = mcp._current_level_cached()
    except Exception:
        return {}
    cached = PCG_STATUS_CACHE.get(lvl)
    if cached is None:
        try:
            status = mcp.pcg_status()
            status["checked_at"] = time.time()
            PCG_STATUS_CACHE[lvl] = status
            cached = status
        except Exception:
            return {}
    return cached or {}

CHAT_LOG: collections.deque = collections.deque(maxlen=50)


def _log(tag: str, *parts):
    line = f"[{time.strftime('%H:%M:%S')}] [{tag}] " + " ".join(str(p) for p in parts)
    print(line, flush=True)


def _short_key(env: str) -> str:
    v = os.environ.get(env, "")
    return f"{v[:7]}...{v[-4:]}" if len(v) >= 12 else "(unset)"


@app.route("/")
def console_view():
    return render_template("console.html")


@app.route("/3d")
def view3d():
    return render_template("view3d.html", scenes=SCENES)


@app.route("/dev")
def dev_view():
    return render_template("index.html", mcp_url=MCP_URL)


@app.route("/api/status")
def status():
    return jsonify({
        "ok": True,
        "version": APP_VERSION,
        "channel": APP_CHANNEL,
        "phase": "demo+mcp-bridge",
        "mcp_url": MCP_URL,
        "mcp_session_id": mcp.session_id,
        "llm_provider": auto_detect_provider(),
    })


@app.route("/api/scenes")
def api_scenes():
    return jsonify({"scenes": SCENES})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    current_spec = body.get("current_spec") or {}
    mode = (body.get("mode") or "scene").lower()
    history = body.get("history") or []
    if not text:
        return jsonify({"ok": False, "error": "missing 'text'"}), 400

    provider_override = body.get("provider")
    provider_resolved = provider_override or auto_detect_provider()
    _log("CHAT-IN", f"provider={provider_resolved}", f"mode={mode}",
         f"scene={current_spec.get('scene_id')}", f"text={text!r}")

    log_entry: dict = {
        "ts": time.strftime("%H:%M:%S"),
        "text": text,
        "scene_id": current_spec.get("scene_id"),
        "provider": provider_resolved,
        "key_fingerprint": (
            _short_key("DEEPSEEK_API_KEY") if provider_resolved == "deepseek"
            else _short_key("ANTHROPIC_API_KEY") if provider_resolved == "anthropic"
            else "n/a (offline)"
        ),
    }

    try:
        client = make_llm_client(provider_override)
    except RuntimeError as e:
        _log("CHAT-ERR", "make_llm_client RuntimeError:", e)
        log_entry["error"] = str(e)
        CHAT_LOG.appendleft(log_entry)
        return jsonify({"ok": False, "error": str(e)}), 503

    if mode == "free":
        messages: list = []
        for h in history[-10:]:
            role = h.get("role")
            content = h.get("content")
            if role in ("user", "assistant") and content:
                messages.append(Message(role=role, content=str(content)))
        messages.append(Message(role="user", content=text))
        chat_kwargs = dict(
            messages=messages,
            tools=None,
            tool_choice=None,
            system=None,
            max_tokens=600,
        )
    else:
        user_msg = (
            f'current_spec: {json.dumps(current_spec, ensure_ascii=False)}\n'
            f'scene_id: {current_spec.get("scene_id", "warehouse")}\n\n'
            f'user request: {text}'
        )
        # Conditionally expose update_scene only when the current UE
        # level has a PCG Volume with a bound graph asset. Otherwise the
        # LLM may pick update_scene in maps that don't support it and
        # apply_pcg_delta fails with 'no PCG actor'. Status is cached
        # per-level in PCG_STATUS_CACHE (refreshed on level change).
        pcg_status = _get_cached_pcg_status()
        active_tools = list(DEMO_TOOLS)
        sys_prompt = SYSTEM_PROMPT
        if pcg_status.get("has_graph"):
            active_tools = [UPDATE_SCENE_TOOL] + active_tools
            sys_prompt = SYSTEM_PROMPT + "\n" + PCG_AVAILABLE_HINT
        chat_kwargs = dict(
            messages=[Message(role="user", content=user_msg)],
            tools=active_tools,
            tool_choice="auto",
            system=sys_prompt,
            max_tokens=600,
        )

    t0 = time.time()
    try:
        result = client.chat_with_tools(**chat_kwargs)
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        tb = traceback.format_exc(limit=2)
        _log("CHAT-ERR", f"{type(e).__name__}: {e}", f"elapsed={elapsed_ms}ms")
        print(tb, file=sys.stderr, flush=True)
        log_entry.update({"error": f"{type(e).__name__}: {e}", "elapsed_ms": elapsed_ms})
        CHAT_LOG.appendleft(log_entry)
        return jsonify({
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "provider": provider_resolved,
        }), 502
    elapsed_ms = int((time.time() - t0) * 1000)

    tcs = list(result.tool_calls or [])
    primary = tcs[0] if tcs else None
    args_preview = json.dumps(primary.arguments if primary else {}, ensure_ascii=False)[:300]
    _log("CHAT-OUT", f"provider={provider_resolved}",
         f"model={getattr(client, 'model', '?')}", f"elapsed={elapsed_ms}ms",
         f"n_calls={len(tcs)}", f"primary={primary.name if primary else None}",
         f"args={args_preview}")

    log_entry.update({
        "elapsed_ms": elapsed_ms,
        "model": getattr(client, "model", "?"),
        "tool_calls": [{"name": t.name, "arguments": t.arguments} for t in tcs],
        "text": result.text,
    })
    CHAT_LOG.appendleft(log_entry)

    # ── MCP relay (scene mode only) ─────────────────────────────────────
    # Iterate every tool_call returned in this turn. Strong models
    # (Claude, GPT-4o, DeepSeek-reasoner) emit N parallel calls for
    # "5 forklifts in a row"; weak models fall back to spawn_batch
    # which packs the same intent into one call (server fans out).
    mcp_relays: list = []
    if mode == "scene":
        for t in tcs:
            args = t.arguments if isinstance(t.arguments, dict) else {}
            relay = None
            if t.name == "update_scene" and args.get("pcg_params"):
                relay = _try_mcp_relay(args["pcg_params"])
            elif t.name in DEMO_TOOL_NAMES:
                relay = _try_demo_tool(t.name, args)
            if relay is not None:
                relay["tool"] = relay.get("tool") or t.name
                mcp_relays.append(relay)
                _log("MCP-RELAY", f"tool={t.name}", f"ok={relay.get('ok')}",
                     f"target={relay.get('pcg_component') or relay.get('reason') or '?'}")

    # Back-compat: front-end currently reads `tool_call` + `mcp_relay`
    # (singular). Keep those pointing at the first call; surface the full
    # list as `tool_calls` + `mcp_relays` so newer UI can show every step.
    return jsonify({
        "ok": True,
        "provider": provider_resolved,
        "model": getattr(client, "model", "unknown"),
        "elapsed_ms": elapsed_ms,
        "tool_call": ({"name": primary.name, "arguments": primary.arguments}
                      if primary else None),
        "tool_calls": [{"name": t.name, "arguments": t.arguments} for t in tcs],
        "text": result.text,
        "mcp_relay": mcp_relays[0] if mcp_relays else None,
        "mcp_relays": mcp_relays,
    })


def _try_demo_tool(tool_name: str, args: dict) -> dict:
    """Run a v0 demo tool_call (spawn/delete/move/list/clear/generate)
    via native SceneTools/ObjectTools RPCs. Same graceful error envelope
    as _try_mcp_relay.

    `generate_warehouse_layout` is special: it is *deferred* to the SSE
    endpoint /api/demo/generate_warehouse_stream so the UI can show
    per-spawn progress. The chat endpoint returns the args back and the
    front-end re-issues the call as a stream. Without this defer the
    chat response blocks for ~5-15s until every actor lands, giving the
    user zero feedback (the "MCP -> UE: layout · 113 actors" message
    arrived all at once).
    """
    if tool_name == "generate_warehouse_layout":
        clamped, warns = _clamp_xy(args)
        out = {
            "ok": True,
            "tool": tool_name,
            "args": clamped,
            "deferred": True,
            "stream_url": "/api/demo/generate_warehouse_stream",
            "result": {},  # filled in by the SSE consumer
        }
        if warns:
            out["warnings"] = warns
        return out

    try:
        clamped, warns = _clamp_xy(args)
        result = dispatch_demo(mcp, tool_name, clamped)
        out = {"ok": True, "tool": tool_name, "args": clamped, "result": result}
        if warns:
            out["warnings"] = warns
        return out
    except ConnectionError as e:
        return {"ok": False, "skipped": True,
                "reason": "UE MCP server unreachable",
                "detail": str(e),
                "hint": "start UE Editor + run `ModelContextProtocol.StartServer`"}
    except KeyError as e:
        return {"ok": False, "skipped": False, "reason": str(e)}
    except Exception as e:
        return {"ok": False, "skipped": False,
                "reason": f"{type(e).__name__}: {e}"}


def _try_mcp_relay(pcg_params: dict) -> dict:
    """Push a pcg_params delta to live UE Editor via MCP. Always returns
    a dict (no exceptions escape) so the chat endpoint always replies."""
    try:
        return mcp.apply_pcg_delta(pcg_params)
    except ConnectionError as e:
        return {"ok": False, "skipped": True,
                "reason": "UE MCP server unreachable",
                "detail": str(e),
                "hint": "start UE Editor + run `ModelContextProtocol.StartServer`"}
    except RuntimeError as e:
        return {"ok": False, "skipped": False,
                "reason": str(e),
                "hint": ("select a PCG Volume in UE Editor or drop one into the level"
                         if "no PCG actor" in str(e) else None)}
    except Exception as e:
        return {"ok": False, "skipped": False,
                "reason": f"{type(e).__name__}: {e}"}


@app.route("/api/mcp/apply_pcg", methods=["POST"])
def api_mcp_apply_pcg():
    """Direct apply endpoint -- POST {"pcg_params": {...}} bypasses the
    LLM, useful for the right-panel param sliders to push directly to
    UE without going through chat."""
    body = request.get_json(silent=True) or {}
    params = body.get("pcg_params") or {}
    if not params:
        return jsonify({"ok": False, "error": "missing 'pcg_params'"}), 400
    return jsonify(_try_mcp_relay(params))


@app.route("/api/mcp/probe_graph", methods=["POST", "GET"])
def api_mcp_probe_graph():
    """Plan-B exploration endpoint: drill into the selected PCG actor's
    graphInstance to surface the OverrideParams / GraphParameters struct
    layout so we know how to address the 21 exposed contract params.
    Returns the raw list_properties dump for graphInstance plus any
    nested OverrideParams payload we can resolve."""
    try:
        mcp.auto_load_toolsets()
        pcg_ref = mcp.find_pcg_component_refpath()
        # get graphInstance refPath
        gi_field = mcp.get_actor_properties(pcg_ref, ["graphInstance"])
        gi_obj = gi_field.get("graphInstance") if isinstance(gi_field, dict) else None
        gi_ref = gi_obj.get("refPath") if isinstance(gi_obj, dict) else None
        if not gi_ref:
            return jsonify({
                "ok": True,
                "pcg_component": pcg_ref,
                "graph_instance": None,
                "note": "PCG Component has no graphInstance -- assign a PCG Graph asset to the Volume in Details panel first",
            })
        gi_schema = mcp.list_actor_properties(gi_ref)
        # Try to also read the actual values of fields most likely to hold
        # the 21 contract params (UPCGGraphInstance commonly exposes Graph
        # asset ref + ParametersOverrides / OverrideParameters / Overrides).
        candidate_fields = []
        if isinstance(gi_schema, dict):
            for k in gi_schema:
                lk = k.lower()
                if any(s in lk for s in ("override", "param", "graph")):
                    candidate_fields.append(k)
        gi_values = mcp.get_actor_properties(gi_ref, candidate_fields) if candidate_fields else {}
        return jsonify({
            "ok": True,
            "pcg_component": pcg_ref,
            "graph_instance": gi_ref,
            "graph_instance_schema": gi_schema,
            "interesting_fields": candidate_fields,
            "interesting_values": gi_values,
        })
    except ConnectionError as e:
        return jsonify({"ok": False, "skipped": True, "reason": str(e)}), 503
    except RuntimeError as e:
        return jsonify({"ok": False, "reason": str(e)}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/mcp/auto_load", methods=["POST"])
def api_mcp_auto_load():
    """Manually trigger the 4 default toolset loads. Useful for /dev
    bridge after UE restart."""
    try:
        return jsonify({"ok": True, **mcp.auto_load_toolsets()})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": str(e)}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/mcp/screenshot.png")
def api_mcp_screenshot():
    """Live UE viewport PNG. Front-end re-requests after each spawn so
    the picture-in-picture refreshes in sync with the schematic."""
    try:
        png = mcp.capture_editor_image()
        if png:
            return Response(png, mimetype="image/png",
                            headers={"Cache-Control": "no-store"})
        return Response(b"", status=204)
    except ConnectionError:
        return Response(b"", status=503)
    except Exception as e:
        return Response(str(e).encode(), status=500, mimetype="text/plain")


@app.route("/api/mcp/pcg_status")
def api_mcp_pcg_status():
    """Reports PCG availability for the CURRENT UE level. UI uses this
    to render a 'PCG · ready' / 'PCG · n/a' chip + decide whether to
    surface PCG-only example chat prompts."""
    refresh = request.args.get("refresh") == "1"
    try:
        if refresh:
            lvl = mcp._current_level_cached()
            PCG_STATUS_CACHE.pop(lvl, None)
        status = _get_cached_pcg_status()
        return jsonify({"ok": True, **status})
    except ConnectionError as e:
        return jsonify({"ok": False, "skipped": True, "reason": str(e)}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/mcp/current_level")
def api_mcp_current_level():
    """Returns whichever .umap is open in the editor. Polled by the UI
    to detect level changes and re-sync the actor mirror."""
    try:
        lvl = mcp.get_current_level()
        return jsonify({"ok": True, "level_path": lvl or ""})
    except ConnectionError as e:
        return jsonify({"ok": False, "skipped": True, "reason": str(e)}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/demo/list_objects")
def api_demo_list_objects():
    """Sync UE Demo/v0 folder -> client. Used on page load and Sync button.
    Returns the same {objects: [...]} shape as the LLM list_objects tool."""
    try:
        result = mcp.demo_list()
        objs = result.get("objects", [])
        try:
            lvl = mcp._current_level_cached()
        except Exception:
            lvl = "?"
        # Log enough to tell the user "loaded? pushed? data what?" without
        # dumping the full payload.  Each line one-shot grep-able.
        _log("DEMO-LIST",
             f"level={lvl}",
             f"count={len(objs)}",
             f"handles={[o.get('actor_handle') for o in objs][:10]}")
        return jsonify({"ok": True, **result})
    except ConnectionError as e:
        _log("DEMO-LIST", "skipped (UE unreachable)", str(e))
        return jsonify({"ok": False, "skipped": True,
                        "reason": "UE MCP server unreachable",
                        "detail": str(e)}), 503
    except Exception as e:
        _log("DEMO-LIST", "error", f"{type(e).__name__}: {e}")
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/demo/clear", methods=["POST"])
def api_demo_clear():
    try:
        return jsonify({"ok": True, **mcp.demo_clear()})
    except ConnectionError as e:
        return jsonify({"ok": False, "skipped": True, "reason": str(e)}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/mcp/init", methods=["GET", "POST"])
def api_mcp_init():
    """UI progress feed. GET returns current state. POST kicks init
    (idempotent; pass {"force":true} to re-init after UE restart)."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        _kick_init(force=bool(body.get("force")))
    return jsonify(INIT_PROGRESS)


@app.route("/api/chat/ping", methods=["POST"])
def api_chat_ping():
    """Bare LLM call -- no tool, no system prompt, no scene context.
    Verifies the LLM is actually live and returns its self-description."""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "你是什么模型? 用一句中文回答.").strip()

    provider_resolved = auto_detect_provider()
    _log("PING-IN", f"provider={provider_resolved}", f"text={text!r}")

    try:
        client = make_llm_client()
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 503

    t0 = time.time()
    try:
        result = client.chat_with_tools(
            messages=[Message(role="user", content=text)],
            tools=None,
            tool_choice=None,
            system=None,
            max_tokens=200,
        )
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        _log("PING-ERR", f"{type(e).__name__}: {e}", f"elapsed={elapsed_ms}ms")
        return jsonify({
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "provider": provider_resolved,
        }), 502
    elapsed_ms = int((time.time() - t0) * 1000)
    _log("PING-OUT", f"provider={provider_resolved}",
         f"model={getattr(client, 'model', '?')}", f"elapsed={elapsed_ms}ms",
         f"text={(result.text or '')[:120]!r}")

    return jsonify({
        "ok": True,
        "provider": provider_resolved,
        "model": getattr(client, "model", "unknown"),
        "elapsed_ms": elapsed_ms,
        "text": result.text,
        "question": text,
    })


@app.route("/api/debug/last")
def api_debug_last():
    n = int(request.args.get("n", 10))
    return jsonify({
        "ok": True,
        "llm_provider": auto_detect_provider(),
        "key_fingerprints": {
            "DEEPSEEK_API_KEY": _short_key("DEEPSEEK_API_KEY"),
            "ANTHROPIC_API_KEY": _short_key("ANTHROPIC_API_KEY"),
        },
        "recent_chats": list(CHAT_LOG)[:n],
    })


@app.route("/api/demo/submit", methods=["POST"])
def api_demo_submit():
    body = request.get_json(silent=True) or {}
    scene_id = body.get("scene_id") or "warehouse"
    params = body.get("pcg_params") or {}
    rationale = body.get("rationale") or ""
    n = int(body.get("variants", 1))

    submitted: list[dict] = []
    for _ in range(max(1, min(n, 10))):
        st = jobs.submit(scene_id, params, rationale)
        submitted.append({
            "job_id": st.job_id,
            "scene_id": st.scene_id,
            "variant_id": st.variant_id,
            "status": st.status,
        })
    return jsonify({"ok": True, "jobs": submitted})


@app.route("/api/demo/jobs")
def api_demo_jobs():
    return jsonify({
        "ok": True,
        "jobs": [
            {
                "job_id": j.job_id,
                "scene_id": j.scene_id,
                "variant_id": j.variant_id,
                "status": j.status,
                "frame_index": j.frame_index,
                "frame_total": j.frame_total,
                "rationale": j.rationale,
            }
            for j in jobs.list_jobs()
        ],
    })


@app.route("/api/demo/stream/<job_id>")
def api_demo_stream(job_id):
    def gen():
        for event in jobs.stream(job_id):
            yield event
    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/demo/generate_warehouse_stream", methods=["POST"])
def api_generate_warehouse_stream():
    """SSE-streamed warehouse generation. Stream events:

      event: plan   data: {total, by_asset, room_w, room_l, volume_anchored, ...}
      event: spawn  data: {i, total, asset_name, x, y, ok}
      event: done   data: {spawned, failed, elapsed_s, by_asset, errors}
      event: error  data: {message}

    POST body: same shape as generate_warehouse_layout tool args, e.g.
      {"object_budget": 40, "shelf_density": 0.6, "seed": 42, ...}
    """
    import queue as _q
    import threading

    args = request.get_json(silent=True) or {}
    q: _q.Queue = _q.Queue()
    SENTINEL = object()
    final: dict = {}

    def _emit(payload: dict) -> None:
        q.put(payload)

    def _worker() -> None:
        try:
            result = dispatch_warehouse(mcp, args, on_progress=_emit)
            final.update(result)
        except ConnectionError as e:
            _emit({"phase": "error",
                   "message": f"UE MCP unreachable: {e}",
                   "hint": "start UE Editor and ModelContextProtocol.StartServer"})
        except Exception as e:
            _emit({"phase": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            q.put(SENTINEL)

    threading.Thread(target=_worker, daemon=True).start()

    def gen():
        while True:
            payload = q.get()
            if payload is SENTINEL:
                # Attach the dispatch return summary onto the done event
                # so the client receives the by_asset/errors breakdown
                # without a follow-up GET.
                if final:
                    yield _sse("summary", {
                        "spawned": final.get("total", 0),
                        "by_asset": final.get("by_asset", {}),
                        "errors": final.get("errors", []),
                        "pcg_args": final.get("pcg_args", {}),
                        "workspace_offset_m": final.get("workspace_offset_m"),
                        "volume_size_m": final.get("volume_size_m"),
                        "room_overridden_by_volume":
                            final.get("room_overridden_by_volume"),
                        "elapsed_s": final.get("elapsed_s"),
                    })
                break
            phase = payload.get("phase", "msg")
            yield _sse(phase, payload)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/api/demo/thumbnail/<scene_id>")
def api_demo_thumbnail(scene_id):
    frame = int(request.args.get("frame", 1))
    variant = request.args.get("variant", "v0_1")
    channel = request.args.get("channel", "final")
    pcg_params = {}
    raw = request.args.get("params")
    if raw:
        try:
            pcg_params = json.loads(raw)
        except Exception:
            pass
    if not pcg_params and scene_id in SCENES:
        pcg_params = SCENES[scene_id].get("pcg_params", {})
    svg = render_thumbnail_svg(
        scene_id=scene_id,
        variant_id=variant,
        frame=frame,
        pcg_params=pcg_params,
        channel=channel,
    )
    return Response(svg, mimetype="image/svg+xml")


@app.route("/api/mcp/status")
def mcp_status():
    try:
        mcp.ensure_session()
        return jsonify({
            "ok": True,
            "session_id": mcp.session_id,
            "url": MCP_URL,
            "loaded_toolsets": mcp.loaded_toolsets,
        })
    except ConnectionError as e:
        return jsonify({"ok": False, "error": str(e), "url": MCP_URL}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}", "url": MCP_URL}), 500


@app.route("/api/demo/pie_start", methods=["POST", "GET"])
def pie_start():
    """Start Play-In-Editor via SlateInspectorToolset.

    Real MCP path (no OS keyboard synthesis): focus main editor window,
    then PressKey('Alt+P'). UE default hotkey for Play In Editor.
    Falls back to Win32 SendInput on hosts where SlateInspector RPC
    fails (e.g. UE not running, toolset not loaded).
    """
    # Step 1: focus main editor window
    try:
        mcp.call_tool_unwrapped(
            "SlateInspectorToolset.SlateInspectorToolset.Windows",
            {"action": "select", "index": 0},
        )
        # Step 2: send Alt+P to focused window
        mcp.call_tool_unwrapped(
            "SlateInspectorToolset.SlateInspectorToolset.PressKey",
            {"key": "Alt+P"},
        )
        return jsonify({"ok": True, "method": "slate_inspector",
                        "combo": "Alt+P"})
    except Exception as slate_err:
        # Fallback: Windows-only SendInput hack
        try:
            from demo.pie_control import play_in_editor as _sendinput_play
            result = _sendinput_play()
            result["slate_error"] = f"{type(slate_err).__name__}: {slate_err}"
            return jsonify(result)
        except Exception as fallback_err:
            return jsonify({"ok": False,
                            "slate_error": f"{type(slate_err).__name__}: {slate_err}",
                            "fallback_error": f"{type(fallback_err).__name__}: {fallback_err}"}), 500


@app.route("/api/demo/pie_stop", methods=["POST", "GET"])
def pie_stop():
    """Stop PIE via SlateInspectorToolset: focus window + PressKey('Esc')."""
    try:
        mcp.call_tool_unwrapped(
            "SlateInspectorToolset.SlateInspectorToolset.Windows",
            {"action": "select", "index": 0},
        )
        mcp.call_tool_unwrapped(
            "SlateInspectorToolset.SlateInspectorToolset.PressKey",
            {"key": "Esc"},
        )
        return jsonify({"ok": True, "method": "slate_inspector", "combo": "Esc"})
    except Exception as slate_err:
        try:
            from demo.pie_control import end_play_in_editor as _sendinput_stop
            result = _sendinput_stop()
            result["slate_error"] = f"{type(slate_err).__name__}: {slate_err}"
            return jsonify(result)
        except Exception as fallback_err:
            return jsonify({"ok": False,
                            "slate_error": f"{type(slate_err).__name__}: {slate_err}",
                            "fallback_error": f"{type(fallback_err).__name__}: {fallback_err}"}), 500


@app.route("/api/demo/refresh_volume", methods=["POST", "GET"])
def refresh_volume():
    """Drop cached workspace and re-resolve. Use after switching UE level
    or moving / replacing the PCGVolume actor in-editor.
    """
    from demo.demo_tools import invalidate_workspace_cache, _cached_workspace
    invalidate_workspace_cache()
    fresh = _cached_workspace(mcp)
    return jsonify({"ok": True, "workspace": fresh})


# ─── Worker patrol (fake-but-visible demo) ────────────────────────────────
# 2 workers spawn at fixed PCGVolume-local positions, a background thread
# steps them around a closed loop every step_s seconds via demo_move
# (delete + respawn). Visually flickers but the path is recognizable --
# real implementation will be a Robot13_Blueprint Tick on UE side.
_PATROL_STATE: dict = {"thread": None, "stop": None, "handles": {}}
_PATROL_PATH_A = [(-3, -3), ( 3, -3), ( 3,  3), (-3,  3)]  # rectangle CCW
_PATROL_PATH_B = [( 0, -3), ( 3,  0), ( 0,  3), (-3,  0)]  # diamond CCW


@app.route("/api/demo/set_worker_path", methods=["POST"])
def set_worker_path():
    """Write a Waypoints path into a Robot13_Blueprint actor and start
    it walking. BP-side requirements: docs/robot13_path_follower_bp.md.

    Body:
      {
        "actor_handle": "worker_1",
        "waypoints_local_m": [[-3,-3], [3,-3], [3,3], [-3,3]],
        "walk_speed_mps": 2.0,    # optional, default 2 m/s
        "loop": true              # optional, default true
      }
    """
    from demo.demo_tools import _cached_workspace
    body = request.get_json(silent=True) or {}
    handle = body.get("actor_handle")
    pts = body.get("waypoints_local_m") or []
    speed_mps = float(body.get("walk_speed_mps", 2.0))
    loop = bool(body.get("loop", True))
    if not handle or not pts:
        return jsonify({"ok": False,
                        "error": "missing actor_handle or waypoints_local_m"}), 400

    anchor = _cached_workspace(mcp).get("world_cm") or {"x": 0, "y": 0, "z": 0}
    # Volume-local meters -> world cm via the same anchor used at spawn time.
    waypoints_world_cm = []
    for p in pts:
        wx = anchor["x"] + float(p[0]) * 100.0
        wy = anchor["y"] + float(p[1]) * 100.0
        wz = anchor["z"] + (float(p[2]) if len(p) > 2 else 0.0) * 100.0
        waypoints_world_cm.append((wx, wy, wz))

    try:
        result = mcp.set_worker_path(
            handle=handle,
            waypoints_world_cm=waypoints_world_cm,
            walk_speed_cms=speed_mps * 100.0,
            loop=loop,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    return jsonify({"ok": result.get("ok", False), **result,
                    "anchor_cm": anchor,
                    "waypoints_world_cm": waypoints_world_cm})


@app.route("/api/demo/start_patrol", methods=["POST", "GET"])
def start_patrol():
    """Spawn two workers and run them around fixed loops."""
    import threading
    from demo.demo_tools import _cached_workspace
    from demo.asset_registry import resolve as resolve_asset, pivot_z

    if _PATROL_STATE["thread"] and _PATROL_STATE["thread"].is_alive():
        return jsonify({"ok": False, "error": "patrol already running",
                        "handles": _PATROL_STATE["handles"]})

    step_s = float(request.args.get("step_s", 2.0))
    anchor = _cached_workspace(mcp).get("world_cm")
    worker_path = resolve_asset("worker")
    worker_pivot = pivot_z("worker")

    try:
        w1 = mcp.demo_spawn(asset_path=worker_path, asset_name="worker",
                            x_m=_PATROL_PATH_A[0][0], y_m=_PATROL_PATH_A[0][1],
                            z_m=worker_pivot, anchor_override_cm=anchor)
        w2 = mcp.demo_spawn(asset_path=worker_path, asset_name="worker",
                            x_m=_PATROL_PATH_B[0][0], y_m=_PATROL_PATH_B[0][1],
                            z_m=worker_pivot, anchor_override_cm=anchor)
    except Exception as e:
        return jsonify({"ok": False, "error": f"spawn: {type(e).__name__}: {e}"}), 500

    state = _PATROL_STATE
    state["handles"] = {"A": w1["actor_handle"], "B": w2["actor_handle"]}
    state["stop"] = threading.Event()

    def loop(stop_evt: "threading.Event"):
        handles = {"A": w1["actor_handle"], "B": w2["actor_handle"]}
        idx_a, idx_b = 0, 0
        while not stop_evt.wait(step_s):
            idx_a = (idx_a + 1) % len(_PATROL_PATH_A)
            idx_b = (idx_b + 1) % len(_PATROL_PATH_B)
            for tag, path, idx in (("A", _PATROL_PATH_A, idx_a),
                                    ("B", _PATROL_PATH_B, idx_b)):
                try:
                    rec = mcp.demo_move(handles[tag], path[idx][0], path[idx][1],
                                        worker_pivot, anchor_override_cm=anchor)
                    new_h = rec.get("actor_handle")
                    if new_h:
                        handles[tag] = new_h
                        state["handles"][tag] = new_h
                except Exception as e:
                    print(f"[patrol] {tag} step failed: "
                          f"{type(e).__name__}: {e}", flush=True)

    t = threading.Thread(target=loop, args=(state["stop"],), daemon=True)
    state["thread"] = t
    t.start()
    return jsonify({"ok": True,
                    "workers": {"A": w1, "B": w2},
                    "paths": {"A": _PATROL_PATH_A, "B": _PATROL_PATH_B},
                    "step_s": step_s})


@app.route("/api/demo/stop_patrol", methods=["POST", "GET"])
def stop_patrol():
    state = _PATROL_STATE
    if not state["thread"] or not state["thread"].is_alive():
        return jsonify({"ok": True, "was_running": False})
    state["stop"].set()
    state["thread"].join(timeout=3.0)
    state["thread"] = None
    return jsonify({"ok": True, "was_running": True,
                    "final_handles": state["handles"]})


@app.route("/api/demo/dump_volume_raw")
def dump_volume_raw():
    """Hard-evidence dump: resolve the PCGVolume actor + show the LITERAL
    JSON returned for every prop name we could possibly want. No clever
    parsing -- just the raw bytes coming out of mcp.get_actor_properties.

    Use this when _resolve_pcg_workspace silently fails: paste the JSON
    here back into chat and we can match shapes (refPath string? dict?
    null?) without guessing.
    """
    try:
        actors = mcp.call_tool_unwrapped(
            "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
            {"tag": "PCGVolume"},
        )
        if isinstance(actors, dict):
            actors = actors.get("actors") or actors.get("results") or []
        if not actors:
            return jsonify({"ok": False, "error": "no PCGVolume tagged actor"}), 404
        first = actors[0]
        ref = first.get("refPath") if isinstance(first, dict) else first
    except Exception as e:
        return jsonify({"ok": False, "error": f"find: {type(e).__name__}: {e}"}), 500

    out: dict = {"ok": True, "ref": ref, "find_first_raw": first, "probes": {}}

    # Probe each candidate IN ISOLATION so we see exactly what each one
    # returns (even null / empty / refPath / nested dict).
    candidates = [
        "BrushComponent", "brush_component",
        "RootComponent", "root_component",
        "ActorLocation", "actor_location",
        "ActorTransform", "actor_transform",
        "Brush", "BrushBuilder", "brush_builder",
        "Tags", "tags",
    ]
    for k in candidates:
        try:
            v = mcp.get_actor_properties(ref, [k])
            out["probes"][k] = v
        except Exception as e:
            out["probes"][k] = {"__error__": f"{type(e).__name__}: {e}"}

    # Also try list_properties to know the actor schema universe.
    try:
        out["list_properties"] = mcp.list_actor_properties(ref)
    except Exception as e:
        out["list_properties_error"] = f"{type(e).__name__}: {e}"

    return jsonify(out)


@app.route("/api/demo/list_actor_props")
def list_actor_props():
    """Dump the full property schema for one actor.

    Usage:
      /api/demo/list_actor_props?ref=/Game/.../TriggerVolume_5
      /api/demo/list_actor_props?tag=PCGVolume       (resolves first tagged actor)
      /api/demo/list_actor_props?glob=*TriggerVolume* (resolves first matching)

    Returns:
      {ok, ref, list_properties: <full schema>, smoke_reads: {<probe>: <result>}}
    where smoke_reads tries every prop name we use anywhere in the
    codebase so the failing ones light up in red.
    """
    ref = request.args.get("ref")
    if not ref:
        # Resolve via tag/glob if user didn't pass an explicit ref.
        try:
            criteria = {}
            if request.args.get("tag"):
                criteria["tag"] = request.args["tag"]
            else:
                criteria["glob"] = request.args.get("glob", "*TriggerVolume*")
            actors = mcp.call_tool_unwrapped(
                "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
                criteria,
            )
            if isinstance(actors, dict):
                actors = actors.get("actors") or actors.get("results") or []
            if isinstance(actors, list) and actors:
                first = actors[0]
                ref = first.get("refPath") if isinstance(first, dict) else first
        except Exception as e:
            return jsonify({"ok": False, "error": f"resolve: {type(e).__name__}: {e}"}), 500
    if not ref:
        return jsonify({"ok": False, "error": "no actor resolved"}), 404

    out: dict = {"ok": True, "ref": ref}
    try:
        out["list_properties"] = mcp.list_actor_properties(ref)
    except Exception as e:
        out["list_properties_error"] = f"{type(e).__name__}: {e}"

    smoke = {}
    for probe in [
        "actor_location", "actor_world_location", "actor_transform",
        "actor_rotation", "actor_scale3d", "actor_label", "tags",
        "root_component", "RootComponent",
        "brush_component", "BrushComponent",
        "brush", "Brush",
    ]:
        try:
            v = mcp.get_actor_properties(ref, [probe])
            smoke[probe] = v
        except Exception as e:
            smoke[probe] = {"__error__": f"{type(e).__name__}: {e}"}
    out["smoke_reads"] = smoke
    return jsonify(out)


@app.route("/api/demo/find_pcg_actors")
def find_pcg_actors():
    """Wide net: list every actor whose label/path contains 'PCG' or
    'Builder' or 'Volume'. Used to figure out what kind of object the
    user's PCGBuilderVolume actually is when find_actors {tag: ...}
    returns 0.

    Returns:
        {ok: bool, by_glob: {pattern: [actors]}, error?: str}
    """
    patterns = ["*PCG*", "*Builder*", "*Volume*", "*Workspace*"]
    out: dict = {"ok": True, "by_glob": {}}
    for p in patterns:
        try:
            res = mcp.call_tool_unwrapped(
                "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
                {"glob": p},
            )
            if isinstance(res, dict):
                res = res.get("actors") or res.get("results") or []
            out["by_glob"][p] = res
        except Exception as e:
            out["by_glob"][p] = {"error": f"{type(e).__name__}: {e}"}
    # Also dump the current level path for context.
    try:
        out["current_level"] = mcp.get_current_level()
    except Exception as e:
        out["current_level_error"] = f"{type(e).__name__}: {e}"
    return jsonify(out)


@app.route("/api/demo/diagnose_workspace")
def diagnose_workspace():
    """Print everything we know about PCGVolume anchoring.

    Returns a fat envelope so xiaohuan can eyeball why dispatch_spawn
    ends up placing actors outside the volume:

      - tagged_actors:   raw find_actors {tag: PCGVolume} result
      - chosen_ref:      which one _resolve_pcg_workspace picked
      - workspace:       _resolve_pcg_workspace output (offset_m, size_m, ref)
      - bp_demo_origin:  what _demo_origin_world_cm sees (cm)
      - raw_root_props:  full root_component dump on the chosen actor
                         -- inspect relative_location vs actor_location
                         vs world_location to spot frame mismatch
      - effective_spawn: if you pass ?x=3&y=2, the cm coords that would
                         go into mcp.demo_spawn -> add_to_scene_from_asset
      - cache_state:     contents of _WORKSPACE_CACHE
      - asset_pivot_z:   what we add for the cube placeholder (m)

    Caller hint: GET /api/demo/diagnose_workspace?x=3&y=2&asset=forklift
    """
    from demo.demo_tools import (
        _resolve_pcg_workspace, _cached_workspace, _WORKSPACE_CACHE,
        invalidate_workspace_cache,
    )
    from demo.asset_registry import pivot_z

    # Force fresh fetch so the diagnostic isn't lying via cache.
    invalidate_workspace_cache()
    out: dict = {"ok": True}

    try:
        tagged = mcp.call_tool_unwrapped(
            "toolset_registry.toolsets.core.scene.SceneTools.find_actors",
            {"tag": "PCGVolume"},
        )
        out["tagged_actors_raw"] = tagged
    except Exception as e:
        out["ok"] = False
        out["error"] = f"find_actors failed: {type(e).__name__}: {e}"
        return jsonify(out), 200

    actors = tagged
    if isinstance(tagged, dict):
        actors = tagged.get("actors") or tagged.get("results") or []
    out["tagged_actor_count"] = len(actors) if isinstance(actors, list) else None

    chosen_ref = None
    if isinstance(actors, list) and actors:
        first = actors[0]
        chosen_ref = first.get("refPath") if isinstance(first, dict) else first
    out["chosen_ref"] = chosen_ref

    if chosen_ref:
        # Dump everything on root_component so frame issues are visible.
        try:
            rc_props = mcp.get_actor_properties(chosen_ref, ["root_component"])
            out["root_component_props"] = rc_props
        except Exception as e:
            out["root_component_error"] = f"{type(e).__name__}: {e}"
        # Also dump actor-level location fields if exposed
        try:
            actor_loc = mcp.get_actor_properties(
                chosen_ref,
                ["actor_location", "actor_world_location", "tags", "actor_label"],
            )
            out["actor_props"] = actor_loc
        except Exception as e:
            out["actor_props_error"] = f"{type(e).__name__}: {e}"

    out["workspace"] = _resolve_pcg_workspace(mcp)
    out["bp_demo_origin_cm"] = mcp._demo_origin_world_cm()
    out["cache_state"] = dict(_WORKSPACE_CACHE)

    # Effective spawn coords if user passed ?x=3&y=2&asset=forklift
    try:
        qx = float(request.args.get("x", "3"))
        qy = float(request.args.get("y", "2"))
        qasset = request.args.get("asset", "forklift")
        off = out["workspace"].get("offset_m", (0.0, 0.0))
        pz = pivot_z(qasset)
        anchor = out["bp_demo_origin_cm"]
        out["asset_pivot_z_m"] = pz
        out["effective_spawn"] = {
            "scene_local_x_m": qx + off[0],
            "scene_local_y_m": qy + off[1],
            "scene_local_z_m": pz,
            "world_cm": {
                "x": anchor["x"] + (qx + off[0]) * 100,
                "y": anchor["y"] + (qy + off[1]) * 100,
                "z": anchor["z"] + pz * 100,
            },
            "explain": (
                f"x_world_cm = BP_DemoOrigin.x ({anchor['x']}) "
                f"+ (user_x_m {qx} + workspace_offset_m {off[0]}) * 100"
            ),
        }
    except Exception as e:
        out["effective_spawn_error"] = f"{type(e).__name__}: {e}"
    return jsonify(out)


@app.route("/api/mcp/probe_sandbox")
def mcp_probe_sandbox():
    """Tell xiaohuan whether the MCP Python sandbox allows `import unreal`.

    UE5.8 MCP has 39 tools but NONE invalidate the viewport. The only
    indirect path is ProgrammaticToolset.execute_tool_script with the
    unreal module. This endpoint runs:
      - get_execution_environment (sandbox manifest)
      - one tiny `import unreal` smoke script

    Returns {ok: bool, unreal_importable: bool, env: <manifest>, ...}.
    Use this to decide whether to build a BP RefreshViewport function
    (only worth it if unreal_importable=true; otherwise build the BP
    AND we need a different trigger path).
    """
    env_info = None
    unreal_importable = False
    error = None
    try:
        env_info = mcp.call_tool_unwrapped(
            "toolset_registry.toolsets.core.programmatic."
            "ProgrammaticToolset.get_execution_environment",
            {},
        )
    except Exception as e:
        error = f"env_probe: {type(e).__name__}: {e}"
    try:
        smoke = mcp.call_tool_unwrapped(
            "toolset_registry.toolsets.core.programmatic."
            "ProgrammaticToolset.execute_tool_script",
            {"script": (
                "def run():\n"
                "    try:\n"
                "        import unreal  # noqa\n"
                "        return {'unreal_importable': True}\n"
                "    except Exception as e:\n"
                "        return {'unreal_importable': False, 'err': str(e)}\n"
            )},
        )
        if isinstance(smoke, dict):
            unreal_importable = bool(smoke.get("unreal_importable"))
    except Exception as e:
        if error is None:
            error = f"smoke: {type(e).__name__}: {e}"
    return jsonify({
        "ok": error is None,
        "unreal_importable": unreal_importable,
        "env": env_info,
        "error": error,
    })


@app.route("/api/mcp/tools")
def mcp_tools():
    try:
        tools = mcp.list_tools()
        return jsonify({"ok": True, "count": len(tools), "tools": tools})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": str(e)}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/mcp/toolsets")
def mcp_toolsets():
    """List the higher-level toolsets the server advertises.

    Different from /api/mcp/tools which returns 39 individual MCP tools
    (some are meta: list_toolsets / describe_toolset / load_toolset).
    Toolsets are bundles; the user reported '41 tools/sets' which may
    correspond to all-toolsets + loaded set count combined.
    """
    try:
        ts = mcp.call_tool_unwrapped(
            "list_toolsets", {}
        )
        return jsonify({"ok": True, "toolsets": ts})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/mcp/explore_all")
def mcp_explore_all():
    """One-shot full inventory: every toolset + every tool inside it.

    Calls list_toolsets to enumerate all 41 toolsets, then describe_toolset
    on each to pull tool schemas. Use this to find functionality hiding
    in toolsets we haven't auto_load_toolsets'd yet (e.g. PIE control,
    asset import, simulation start/stop, etc.).

    Query params:
      ?keyword=play     filter to toolset/tool with this substring (case-insensitive)
      ?short=true       drop inputSchema to keep payload small
      ?names_only=true  return just toolset.name + tool.name (very compact)
    """
    keyword = (request.args.get("keyword") or "").lower().strip()
    short = (request.args.get("short", "").lower() in ("1", "true", "yes"))
    names_only = (request.args.get("names_only", "").lower() in ("1", "true", "yes"))

    try:
        ts_raw = mcp.call_tool_unwrapped("list_toolsets", {})
    except Exception as e:
        return jsonify({"ok": False,
                        "error": f"list_toolsets: {type(e).__name__}: {e}"}), 500

    ts_list = ts_raw
    if isinstance(ts_raw, dict):
        ts_list = ts_raw.get("toolsets") or ts_raw.get("results") or []
    if not isinstance(ts_list, list):
        return jsonify({"ok": False,
                        "error": f"unexpected toolsets shape: {type(ts_list).__name__}",
                        "raw": ts_raw}), 500

    loaded = set(getattr(mcp, "loaded_toolsets", []) or [])
    entries = []
    total_tools = 0
    describe_errors = 0

    for ts in ts_list:
        name = ts.get("name") if isinstance(ts, dict) else str(ts)
        if not name:
            continue
        desc = (ts.get("description") if isinstance(ts, dict) else "") or ""
        entry: dict = {
            "name": name,
            "description": desc,
            "loaded": name in loaded,
        }
        # Try describe even if not loaded -- describe_toolset works on
        # unloaded ones too (it's a registry lookup, doesn't activate).
        try:
            details = mcp.call_tool_unwrapped(
                "describe_toolset", {"toolset_name": name}
            )
            tools = []
            if isinstance(details, dict):
                tools = details.get("tools") or details.get("results") or []
            if isinstance(tools, list):
                if names_only:
                    entry["tools"] = [t.get("name") if isinstance(t, dict) else str(t)
                                       for t in tools]
                elif short:
                    entry["tools"] = [
                        {"name": t.get("name"), "description": t.get("description")}
                        for t in tools if isinstance(t, dict)
                    ]
                else:
                    entry["tools"] = tools
                total_tools += len(tools)
        except Exception as e:
            entry["describe_error"] = f"{type(e).__name__}: {e}"
            describe_errors += 1

        if keyword:
            hay = (
                name.lower() + " " + desc.lower() + " "
                + " ".join(
                    (t.get("name", "") + " " + t.get("description", ""))
                    if isinstance(t, dict) else str(t)
                    for t in (entry.get("tools") or [])
                ).lower()
            )
            if keyword not in hay:
                continue
        entries.append(entry)

    return jsonify({
        "ok": True,
        "n_toolsets_seen": len(ts_list),
        "n_toolsets_returned": len(entries),
        "n_tools_total": total_tools,
        "describe_errors": describe_errors,
        "loaded": sorted(loaded),
        "filter_keyword": keyword or None,
        "toolsets": entries,
    })


@app.route("/tools")
def tools_page():
    """Browsable tools index. Fetches /api/mcp/tools + /api/mcp/toolsets
    client-side, groups by toolset prefix, renders cards with name +
    description + input schema summary. Filter box at the top.
    """
    return Response(_TOOLS_PAGE_HTML, mimetype="text/html")


_TOOLS_PAGE_HTML = r"""<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><title>ADORE · MCP Tools</title>
<style>
  body { background:#0e0f12; color:#e6e8eb; font:13px/1.4 -apple-system,
         "SF Pro Text", "PingFang SC", system-ui, sans-serif; margin:0; padding:18px; }
  h1 { font-size:18px; margin:0 0 4px; color:#7cf; }
  .sub { color:#888; font-size:11px; margin-bottom:14px; }
  .ctl { margin-bottom:12px; }
  input[type=search] { background:#1a1c20; border:1px solid #333; color:#eee;
         padding:6px 10px; border-radius:4px; width:280px; font:13px var(--mono); }
  .group { margin:18px 0 6px; padding:6px 10px; background:#1a1d24;
         border-left:3px solid #4af; font-weight:600; color:#9cf;
         display:flex; justify-content:space-between; }
  .group .cnt { color:#666; font-weight:400; font-size:11px; }
  .tool { padding:8px 12px; margin:3px 0; background:#15171b;
         border-left:2px solid #2a2d33; border-radius:3px; }
  .tool.hide { display:none; }
  .tool .n { font-family:Menlo, Consolas, monospace; color:#e8a; font-weight:600;
         font-size:12px; word-break:break-all; }
  .tool .d { color:#aab; font-size:11.5px; margin-top:3px; white-space:pre-wrap; }
  .tool .args { color:#5a8; font-family:Menlo, Consolas, monospace;
         font-size:10.5px; margin-top:4px; }
  .stat { display:inline-block; padding:1px 6px; margin-right:6px;
         background:#222; border-radius:2px; color:#888; font-size:10.5px; }
  .err { background:#321; border:1px solid #533; padding:10px;
         border-radius:4px; color:#faa; }
</style></head>
<body>
  <h1>MCP Tools / Toolsets</h1>
  <div class="sub">live snapshot from UE5.8 MCP · session-dependent ·
    <a href="/api/mcp/tools" style="color:#7cf">raw /api/mcp/tools JSON</a> ·
    <a href="/api/mcp/toolsets" style="color:#7cf">raw /api/mcp/toolsets JSON</a> ·
    <a href="/" style="color:#7cf">← back to ADORE</a>
  </div>
  <div class="ctl">
    <input id="q" type="search" placeholder="filter by name / description...">
    <span id="counts" class="stat">loading...</span>
  </div>
  <div id="root"></div>

<script>
async function load() {
  const root = document.getElementById('root');
  const counts = document.getElementById('counts');
  try {
    const [toolsResp, tsResp] = await Promise.all([
      fetch('/api/mcp/tools').then(r => r.json()),
      fetch('/api/mcp/toolsets').then(r => r.json()).catch(() => ({ok: false})),
    ]);
    if (!toolsResp.ok) {
      root.innerHTML = '<div class="err">tools fetch failed: ' +
        (toolsResp.error || 'unknown') +
        '</div><div class="sub">Is UE Editor running with ModelContextProtocol.StartServer?</div>';
      return;
    }
    const tools = toolsResp.tools || [];
    const tsCount = (tsResp && tsResp.ok && Array.isArray(tsResp.toolsets))
      ? tsResp.toolsets.length : '?';
    counts.textContent = `${tools.length} tools · ${tsCount} toolsets`;

    // Group by prefix before the last "."
    const groups = {};
    for (const t of tools) {
      const parts = t.name.split('.');
      const g = parts.length > 1 ? parts.slice(0, -1).join('.') : '<meta>';
      (groups[g] = groups[g] || []).push(t);
    }
    const sortedGroups = Object.keys(groups).sort();

    let html = '';
    if (tsResp && tsResp.ok && Array.isArray(tsResp.toolsets)) {
      html += '<div class="group">Available toolsets <span class="cnt">' +
              tsResp.toolsets.length + '</span></div>';
      for (const t of tsResp.toolsets) {
        html += '<div class="tool"><span class="n">' + (t.name || t) +
                '</span>' +
                (t.description ? '<div class="d">' + escapeHtml(t.description) + '</div>' : '') +
                '</div>';
      }
    }
    for (const g of sortedGroups) {
      html += '<div class="group group-tools">' + escapeHtml(g) +
              '<span class="cnt">' + groups[g].length + ' tool' +
              (groups[g].length===1?'':'s') + '</span></div>';
      for (const t of groups[g]) {
        const inputProps = (t.inputSchema && t.inputSchema.properties) || {};
        const argHints = Object.entries(inputProps).map(([k, v]) => {
          const ty = (v && v.type) || '?';
          return k + ':' + ty;
        }).join(', ');
        const req = (t.inputSchema && t.inputSchema.required) || [];
        html += '<div class="tool" data-name="' + escapeHtml(t.name) +
                '" data-desc="' + escapeHtml(t.description||'') + '">' +
                '<div class="n">' + escapeHtml(t.name) + '</div>';
        if (t.description) {
          html += '<div class="d">' + escapeHtml(t.description.slice(0, 280) +
                  (t.description.length > 280 ? '...' : '')) + '</div>';
        }
        if (argHints) {
          html += '<div class="args">args: { ' + escapeHtml(argHints) + ' }' +
                  (req.length ? ' · required: [' + req.join(', ') + ']' : '') +
                  '</div>';
        }
        html += '</div>';
      }
    }
    root.innerHTML = html;
    wireFilter();
  } catch (e) {
    root.innerHTML = '<div class="err">' + e.message + '</div>';
  }
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]);
}
function wireFilter() {
  const q = document.getElementById('q');
  q.addEventListener('input', () => {
    const term = q.value.trim().toLowerCase();
    document.querySelectorAll('.tool').forEach(el => {
      if (!term) { el.classList.remove('hide'); return; }
      const n = (el.dataset.name||'').toLowerCase();
      const d = (el.dataset.desc||'').toLowerCase();
      el.classList.toggle('hide', !(n.includes(term) || d.includes(term)));
    });
  });
}
load();
</script>
</body></html>
"""


@app.route("/api/mcp/call", methods=["POST"])
def mcp_call():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    arguments = body.get("arguments", {})
    if not name:
        return jsonify({"ok": False, "error": "missing 'name'"}), 400
    if not isinstance(arguments, dict):
        return jsonify({"ok": False, "error": "'arguments' must be an object"}), 400
    try:
        result = mcp.call_tool(name, arguments)
        return jsonify({"ok": True, "name": name, "result": result})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": str(e)}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


def main():
    port = int(os.environ.get("PORT", 5001))
    provider = auto_detect_provider()
    print(f"[adore_robot] serving on http://127.0.0.1:{port}")
    print(f"[adore_robot]   console:     /          (operator console -- real LLM + MCP relay)")
    print(f"[adore_robot]   3d demo:     /3d        (three.js viewport + real LLM)")
    print(f"[adore_robot]   dev MCP:     /dev       (MCP bridge -> {MCP_URL})")
    print(f"[adore_robot]   debug:       /api/debug/last")
    print(f"[adore_robot]   LLM provider: {provider}"
          f"{' (offline keyword fallback)' if provider == 'keyword' else ''}")
    print(f"[adore_robot]   DEEPSEEK_API_KEY:  {_short_key('DEEPSEEK_API_KEY')}")
    print(f"[adore_robot]   ANTHROPIC_API_KEY: {_short_key('ANTHROPIC_API_KEY')}")
    print(f"[adore_robot]   scenes loaded: {list(SCENES.keys()) or '(none)'}")
    # Kick MCP init in the background so the progress bar starts ticking
    # the moment the UI loads. Failure is non-fatal (sandbox / UE not up).
    _kick_init()
    print(f"[adore_robot] ----- chat events will be logged below -----")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
