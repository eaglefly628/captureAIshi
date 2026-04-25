#!/usr/bin/env python3
"""captureAIshi — Standalone desktop application.

Wraps the Flask web UI in a native desktop window using pywebview.
This produces the same interface as the browser-based web_ui.py but
runs as a self-contained desktop app — no browser needed.

Can be packaged into a single .exe via PyInstaller:
    pyinstaller desktop_app.spec
"""

import logging
import socket
import sys
import threading

import webview

from web_ui import _ensure_exr_loader, app


def _find_free_port() -> int:
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_flask(port: int) -> None:
    """Run Flask in a background thread with logging suppressed."""
    # Suppress Flask/Werkzeug request logs in desktop mode
    wlog = logging.getLogger("werkzeug")
    wlog.setLevel(logging.ERROR)

    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    _ensure_exr_loader()

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    # Start Flask in background
    server = threading.Thread(target=_run_flask, args=(port,), daemon=True)
    server.start()

    # Create native window
    window = webview.create_window(
        "captureAIshi",
        url,
        width=1200,
        height=800,
        min_size=(900, 600),
        background_color="#1c1c1e",
        text_select=True,
    )

    # webview.start() blocks until the window is closed
    webview.start(debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
