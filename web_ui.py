#!/usr/bin/env python3
"""captureAIshi - Web UI server entry point.

All routes live in blueprints under ``web.routes``. Shared state and
helpers are in ``web.state`` / ``web.helpers``. This file wires them up
and runs the Flask app.
"""

import logging
import webbrowser

from flask import Flask, render_template

from web.routes import ALL_BLUEPRINTS

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")

for _bp in ALL_BLUEPRINTS:
    app.register_blueprint(_bp)


@app.route("/")
def index():
    return render_template("index.html")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    # Suppress noisy Werkzeug request logs for polling endpoints.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    port = 5000
    print(f"captureAIshi Web UI: http://127.0.0.1:{port}")
    webbrowser.open(f"http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
