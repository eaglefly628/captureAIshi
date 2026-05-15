#!/usr/bin/env python3
"""captureAIshi root entry -- launches the landing page.

Run from the repo root:
    python main.py

Equivalent to:
    python apps/launcher/server.py

The launcher serves a small Flask landing page (port 5050) from which
each sub-app (capture / adore_robot) can be spawned as a subprocess.
To run the capture pipeline directly without the launcher, use:
    python apps/capture/web_ui.py
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    launcher = Path(__file__).resolve().parent / "apps" / "launcher" / "server.py"
    sys.argv[0] = str(launcher)
    runpy.run_path(str(launcher), run_name="__main__")
