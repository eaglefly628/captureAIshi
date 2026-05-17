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
from demo.runner import DemoJobRegistry
from demo.thumbnail import render_thumbnail_svg
from llm import Message, make_llm_client
from llm.factory import auto_detect_provider

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "web" / "templates"
STATIC = ROOT / "web" / "static"
CONFIGS_SCENES = ROOT / "configs" / "scenes"

MCP_URL = os.environ.get("UNREAL_MCP_URL", "http://127.0.0.1:8000/mcp")

app = Flask(
    __name__,
    template_folder=str(TEMPLATES),
    static_folder=str(STATIC),
    static_url_path="/static",
)
mcp = UnrealMCPClient(url=MCP_URL)
jobs = DemoJobRegistry()


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

CHAT_LOG: collections.deque = collections.deque(maxlen=50)


def _log(tag: str, *parts):
    line = f"[{time.strftime('%H:%M:%S')}] [{tag}] " + " ".join(str(p) for p in parts)
    print(line, flush=True)


def _short_key(env: str) -> str:
    v = os.environ.get(env, "")
    return f"{v[:7]}...{v[-4:]}" if len(v) >= 12 else "(unset)"


@app.route("/")
def design_view():
    return render_template("design.html")


@app.route("/3d")
def demo_view():
    provider = auto_detect_provider()
    return render_template(
        "demo.html",
        scenes=SCENES,
        mcp_url=MCP_URL,
        llm_provider=provider,
        offline_mode=(provider == "keyword"),
    )


@app.route("/dev")
def dev_view():
    return render_template("index.html", mcp_url=MCP_URL)


@app.route("/api/status")
def status():
    return jsonify({
        "ok": True,
        "version": "0.3.3-dev",
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
        chat_kwargs = dict(
            messages=[Message(role="user", content=user_msg)],
            tools=[UPDATE_SCENE_TOOL],
            tool_choice="auto",
            system=SYSTEM_PROMPT,
            max_tokens=512,
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

    tc = result.tool_calls[0] if result.tool_calls else None
    args_preview = json.dumps(tc.arguments if tc else {}, ensure_ascii=False)[:300]
    _log("CHAT-OUT", f"provider={provider_resolved}",
         f"model={getattr(client, 'model', '?')}", f"elapsed={elapsed_ms}ms",
         f"tool={tc.name if tc else None}", f"args={args_preview}")

    log_entry.update({
        "elapsed_ms": elapsed_ms,
        "model": getattr(client, "model", "?"),
        "tool_call": {"name": tc.name, "arguments": tc.arguments} if tc else None,
        "text": result.text,
    })
    CHAT_LOG.appendleft(log_entry)

    return jsonify({
        "ok": True,
        "provider": provider_resolved,
        "model": getattr(client, "model", "unknown"),
        "elapsed_ms": elapsed_ms,
        "tool_call": {
            "name": tc.name,
            "arguments": tc.arguments,
        } if tc else None,
        "text": result.text,
    })


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
        return jsonify({"ok": True, "session_id": mcp.session_id, "url": MCP_URL})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": str(e), "url": MCP_URL}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}", "url": MCP_URL}), 500


@app.route("/api/mcp/tools")
def mcp_tools():
    try:
        tools = mcp.list_tools()
        return jsonify({"ok": True, "count": len(tools), "tools": tools})
    except ConnectionError as e:
        return jsonify({"ok": False, "error": str(e)}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


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
    print(f"[adore_robot]   design view: /          (operator console, mock-driven for now)")
    print(f"[adore_robot]   3d demo:     /3d        (three.js viewport + real LLM)")
    print(f"[adore_robot]   dev MCP:     /dev       (MCP bridge -> {MCP_URL})")
    print(f"[adore_robot]   debug:       /api/debug/last")
    print(f"[adore_robot]   LLM provider: {provider}"
          f"{' (offline keyword fallback)' if provider == 'keyword' else ''}")
    print(f"[adore_robot]   DEEPSEEK_API_KEY:  {_short_key('DEEPSEEK_API_KEY')}")
    print(f"[adore_robot]   ANTHROPIC_API_KEY: {_short_key('ANTHROPIC_API_KEY')}")
    print(f"[adore_robot]   scenes loaded: {list(SCENES.keys()) or '(none)'}")
    print(f"[adore_robot] ----- chat events will be logged below -----")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
