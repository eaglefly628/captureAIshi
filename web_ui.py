#!/usr/bin/env python3
"""captureAIshi - Web UI server entry point.

All routes live in blueprints under ``web.routes``. Shared state and
helpers are in ``web.state`` / ``web.helpers``. This file wires them up
and runs the Flask app.
"""

import importlib
import logging
import subprocess
import sys
import webbrowser

from flask import Flask, render_template

from web.routes import ALL_BLUEPRINTS


# EXR depth maps emitted by renderdoccmd exportframe (FileType::EXR)
# require one of cv2 / imageio[freeimage] / OpenEXR for Python-side
# loading. Probe at startup and pip-install opencv-python if none is
# present so depth doesn't silently disappear from the gallery.
_EXR_LOADERS = ("cv2", "imageio.v3", "OpenEXR")


def _ensure_exr_loader() -> None:
    log = logging.getLogger("startup")
    for name in _EXR_LOADERS:
        try:
            importlib.import_module(name)
            log.debug(f"EXR loader '{name}' available")
            return
        except ImportError:
            continue
    log.warning(
        "No EXR loader found (cv2 / imageio[freeimage] / OpenEXR all "
        "missing). Depth maps from RDC capture will fail to load. "
        "Auto-installing opencv-python..."
    )
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", "opencv-python>=4.5.0"],
            timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as e:
        log.error(
            f"Auto-install of opencv-python failed: {e}. Run manually: "
            f"`{sys.executable} -m pip install -r requirements.txt`"
        )
        return
    # Re-import to verify and warm up the module cache.
    try:
        importlib.import_module("cv2")
        log.info("opencv-python installed; EXR depth loading now available")
    except ImportError as e:
        log.error(f"opencv-python installed but cv2 still not importable: {e}")

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

    _ensure_exr_loader()

    port = 5000
    print(f"captureAIshi Web UI: http://127.0.0.1:{port}")
    webbrowser.open(f"http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
