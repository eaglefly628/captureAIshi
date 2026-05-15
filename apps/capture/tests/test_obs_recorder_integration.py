"""End-to-end OBS recorder test against a real OBS instance.

Skipped unless ``CAPTUREAISHI_OBS_INTEGRATION=1`` is set. Requires:
    - OBS Studio running with obs-websocket enabled (port 4455)
    - A scene named "Capture" with at least one source
    - Optional CAPTUREAISHI_OBS_PASSWORD env var if auth is on

Run manually:
    CAPTUREAISHI_OBS_INTEGRATION=1 pytest tests/test_obs_recorder_integration.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

INTEGRATION = os.environ.get("CAPTUREAISHI_OBS_INTEGRATION") == "1"
pytestmark = pytest.mark.skipif(
    not INTEGRATION,
    reason="set CAPTUREAISHI_OBS_INTEGRATION=1 to run against a live OBS",
)


@pytest.mark.integration
def test_real_obs_two_second_recording(tmp_path: Path):
    from recorders.obs_recorder import OBSRecorder

    rec = OBSRecorder(
        output_dir=tmp_path,
        host=os.environ.get("CAPTUREAISHI_OBS_HOST", "127.0.0.1"),
        port=int(os.environ.get("CAPTUREAISHI_OBS_PORT", "4455")),
        password=os.environ.get("CAPTUREAISHI_OBS_PASSWORD", ""),
        scene=os.environ.get("CAPTUREAISHI_OBS_SCENE", "Capture"),
        auto_launch_obs=False,
        strict=True,
    )
    rec.__enter__()
    rec.start("integration_test")
    time.sleep(2.0)
    video_path = rec.stop()
    rec.__exit__(None, None, None)

    assert video_path is not None and video_path.exists()
    assert video_path.stat().st_size > 0
    meta = json.loads((tmp_path / "video_metadata.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == 1
    assert meta["duration_seconds"] >= 1.5
