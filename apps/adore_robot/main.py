"""Adore Robot -- UE5 PCG robot training scene foundry.

Flask app on :5001. Two views:

  /        customer-facing demo (three.js + NL chat + scripted batch)
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

import json
import os
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

from mcp_client import UnrealMCPClient
from demo.prompts import SYSTEM_PROMPT, UPDATE_SCENE_TOOL
from demo.runner import DemoJobRegistry
from demo.thumbnail import render_thumbnail_svg
from llm import detect_available_provider, make_llm_client

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


@app.route("/")
def demo_view():
    provider = detect_available_provider()
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
        "llm_provider": detect_available_provider(),
    })


@app.route("/api/scenes")
def api_scenes():
    return jsonify({"scenes": SCENES})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    current_spec = body.get("current_spec") or {}
    if not text:
        return jsonify({"ok": False, "error": "missing 'text'"}), 400

    provider_override = body.get("provider")
    try:
        client = make_llm_client(provider_override)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 503

    user_msg = (
        f'current_spec: {json.dumps(current_spec, ensure_ascii=False)}\n'
        f'scene_id: {current_spec.get("scene_id", "warehouse")}\n\n'
        f'user request: {text}'
    )

    try:
        result = client.chat_with_tools(
            system=SYSTEM_PROMPT,
            user=user_msg,
            tools=[UPDATE_SCENE_TOOL],
            force_tool=UPDATE_SCENE_TOOL.name,
            max_tokens=512,
        )
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "provider": client.provider,
        }), 502

    tc = result.tool_calls[0] if result.tool_calls else None
    return jsonify({
        "ok": True,
        "provider": result.provider,
        "model": result.model,
        "elapsed_ms": result.elapsed_ms,
        "tool_call": {
            "name": tc.name,
            "arguments": tc.arguments,
        } if tc else None,
        "text": result.text,
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
    provider = detect_available_provider()
    print(f"[adore_robot] serving on http://127.0.0.1:{port}")
    print(f"[adore_robot]   demo view: /")
    print(f"[adore_robot]   dev view:  /dev  (MCP -> {MCP_URL})")
    print(f"[adore_robot]   LLM provider: {provider}"
          f"{' (offline keyword fallback)' if provider == 'keyword' else ''}")
    print(f"[adore_robot]   scenes loaded: {list(SCENES.keys()) or '(none)'}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
