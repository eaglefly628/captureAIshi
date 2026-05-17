"""Adore Robot -- UE5 PCG robot training scene foundry.

Flask app on :5001. Bridges browser UI to the UE5.8 MCP server running
in Unreal Editor (default http://127.0.0.1:8000/mcp).

Setup:
  1. UE5.8 Editor: enable AI Assistant + Toolset Registry + Unreal MCP +
     All Toolsets plugins, restart.
  2. UE editor console: ModelContextProtocol.StartServer  (or set
     bAutoStartServer in Editor Preferences -> Model Context Protocol).
  3. python apps/adore_robot/main.py  -> http://127.0.0.1:5001
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from mcp_client import UnrealMCPClient

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "web" / "templates"

MCP_URL = os.environ.get("UNREAL_MCP_URL", "http://127.0.0.1:8000/mcp")

app = Flask(__name__, template_folder=str(TEMPLATES))
mcp = UnrealMCPClient(url=MCP_URL)


@app.route("/")
def index():
    return render_template("index.html", mcp_url=MCP_URL)


@app.route("/api/status")
def status():
    return jsonify({
        "ok": True,
        "version": "0.3.3-dev",
        "phase": "mcp-bridge",
        "mcp_url": MCP_URL,
        "mcp_session_id": mcp.session_id,
    })


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
    print(f"[adore_robot] serving on http://127.0.0.1:{port}  (MCP -> {MCP_URL})")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
