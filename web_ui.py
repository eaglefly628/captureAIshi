#!/usr/bin/env python3
"""captureAIshi - Web UI server entry point.

All routes live in blueprints under ``web.routes``. Shared state and
helpers are in ``web.state`` / ``web.helpers``. This file wires them up
and runs the Flask app.
"""

import importlib
import logging
import os
import subprocess
import sys
import webbrowser

# opencv-python disables EXR by default (security policy since OpenCV
# 4.5; cv2.imread on a .exr silently returns None without it). Set
# this BEFORE the first ``import cv2`` anywhere in the process, since
# cv2 only checks the env var at import time.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

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
            log.info(f"[EXR] loader '{name}' is available")
            return
        except ImportError:
            continue
    log.warning(
        "[EXR] No depth loader found "
        "(cv2 / imageio[freeimage] / OpenEXR all missing). RDC depth "
        "captures will not be readable. Auto-installing opencv-python..."
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install",
             "--disable-pip-version-check", "--no-warn-script-location",
             "opencv-python>=4.5.0"],
            capture_output=True, text=True, timeout=240,
        )
        if result.returncode != 0:
            log.error(
                "[EXR] pip install opencv-python failed (exit=%d). "
                "stdout=%s | stderr=%s | run manually: %s -m pip install "
                "-r requirements.txt",
                result.returncode,
                (result.stdout or "").strip()[-500:],
                (result.stderr or "").strip()[-500:],
                sys.executable,
            )
            return
        # Show only the last few stdout lines (Successfully installed ...)
        tail = "\n".join((result.stdout or "").strip().splitlines()[-5:])
        if tail:
            log.info(f"[EXR] pip output:\n{tail}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.error(
            "[EXR] Auto-install of opencv-python failed: %s. Run "
            "manually: %s -m pip install -r requirements.txt",
            e, sys.executable,
        )
        return
    # Re-import. importlib may have cached the failed import; invalidate
    # caches so the just-installed module is found.
    importlib.invalidate_caches()
    try:
        importlib.import_module("cv2")
        log.info("[EXR] opencv-python installed; depth loading available")
    except ImportError as e:
        log.error(
            "[EXR] opencv-python installed but cv2 still not importable "
            "(sys.path=%s, executable=%s): %s",
            sys.path, sys.executable, e,
        )

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

    # In DEMOAISHI=1 the cloud image never reads .exr files, so skip the
    # cv2 auto-install probe (saves ~30 s + 80 MB on first cold start).
    from web.demo import is_demo_mode
    if not is_demo_mode():
        _ensure_exr_loader()

    port = 5000
    print(f"captureAIshi Web UI: http://127.0.0.1:{port}")
    webbrowser.open(f"http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
