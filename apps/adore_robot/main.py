"""Adore Robot — UE5 PCG robot training scene foundry (preview).

Stub Flask app on :5001. Renders the initial dashboard; PCG backend pending
(see docs/ui_pcg_redesign_plan.md Phase B).
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "web" / "templates"

app = Flask(__name__, template_folder=str(TEMPLATES))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    return jsonify({
        "ok": True,
        "version": "0.0.1-preview",
        "phase": "scaffold",
        "available_routes": ["/", "/api/status"],
    })


def main():
    port = 5001
    print(f"[adore_robot] serving on http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
