"""Unit tests for recorders.OBSRecorder.

The OBS WebSocket client and obs64.exe spawn are both patched so the test
runs fully offline. We assert the call sequence (connect -> set scene ->
set record dir -> set filename -> start_record -> stop_record), the
metadata schema written to disk, and the strict-vs-tolerant failure mode.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from recorders.base import NullRecorder
from recorders.obs_recorder import OBSRecorder
from recorders.factory import create_recorder


def _fake_client_factory() -> MagicMock:
    client = MagicMock()
    client.get_version.return_value = SimpleNamespace(
        obs_version="30.1.2", rpc_version=1
    )
    client.stop_record.return_value = SimpleNamespace(output_path="dummy.mp4")
    client.get_video_settings.return_value = SimpleNamespace(
        output_width=1920, output_height=1080, fps_numerator=60, fps_denominator=1,
    )
    return client


def _make_recorder(tmp_path: Path, **overrides) -> OBSRecorder:
    kwargs = dict(
        output_dir=tmp_path,
        host="127.0.0.1",
        port=4455,
        password="",
        scene="Capture",
        source_name="Game Capture",
        bitrate_kbps=50000,
        framerate=60.0,
        auto_launch_obs=False,
        target_exe="game.exe",
        strict=False,
    )
    kwargs.update(overrides)
    return OBSRecorder(**kwargs)


@patch("recorders.obs_recorder.OBSRecorder._port_open", return_value=True)
def test_full_lifecycle_writes_metadata(mock_port, tmp_path: Path):
    client = _fake_client_factory()

    fake_video_path = tmp_path / "session.mp4"
    fake_video_path.write_bytes(b"\x00" * 1024)
    client.stop_record.return_value = SimpleNamespace(output_path=str(fake_video_path))

    fake_module = MagicMock()
    fake_module.ReqClient.return_value = client

    with patch.dict("sys.modules", {"obsws_python": fake_module}):
        rec = _make_recorder(tmp_path)
        rec.__enter__()
        rec.start("session_ue5_rdoc")
        rec.stop()
        rec.__exit__(None, None, None)

    client.set_current_program_scene.assert_called_with("Capture")
    client.set_record_directory.assert_called_with(str(tmp_path.resolve()))
    client.set_profile_parameter.assert_called_with(
        "Output", "FilenameFormatting", "session_ue5_rdoc"
    )
    client.start_record.assert_called_once()
    client.stop_record.assert_called_once()

    canonical = tmp_path / "video.mp4"
    assert canonical.exists(), "stop() should rename to video.mp4"

    meta_path = tmp_path / "video_metadata.json"
    assert meta_path.exists(), "stop() should write video_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["schema_version"] == 1
    assert meta["video_file"] == "video.mp4"
    assert meta["obs_version"] == "30.1.2"
    assert meta["resolution"] == {"width": 1920, "height": 1080}
    assert meta["framerate"] == 60.0
    assert "trajectory_alignment" in meta
    assert "pose_timestamps_seconds" in meta["trajectory_alignment"]


@patch("recorders.obs_recorder.OBSRecorder._port_open", return_value=False)
def test_strict_false_swallows_connect_failure(mock_port, tmp_path: Path):
    rec = _make_recorder(tmp_path, strict=False)
    rec.__enter__()
    assert rec.is_recording is False
    rec.start("anything")
    assert rec.is_recording is False
    rec.__exit__(None, None, None)


@patch("recorders.obs_recorder.OBSRecorder._port_open", return_value=False)
def test_strict_true_raises_on_connect_failure(mock_port, tmp_path: Path):
    rec = _make_recorder(tmp_path, strict=True)
    with pytest.raises(RuntimeError, match="OBS WebSocket not reachable"):
        rec.__enter__()


def test_factory_disabled_returns_null(tmp_path: Path):
    args = SimpleNamespace(recorder_enabled=False)
    rec = create_recorder(args, tmp_path)
    assert isinstance(rec, NullRecorder)
    assert rec.is_recording is False
    rec.start("x")
    assert rec.stop() is None


def test_factory_unknown_backend_returns_null(tmp_path: Path):
    args = SimpleNamespace(recorder_enabled=True, recorder_backend="ffmpeg")
    rec = create_recorder(args, tmp_path)
    assert isinstance(rec, NullRecorder)


@patch("recorders.obs_recorder.OBSRecorder._port_open", return_value=True)
def test_pose_timestamps_drained_into_metadata(mock_port, tmp_path: Path):
    from web import state as web_state

    fake_video_path = tmp_path / "session.mp4"
    fake_video_path.write_bytes(b"\x00" * 1024)
    client = _fake_client_factory()
    client.stop_record.return_value = SimpleNamespace(output_path=str(fake_video_path))

    fake_module = MagicMock()
    fake_module.ReqClient.return_value = client
    with patch.dict("sys.modules", {"obsws_python": fake_module}):
        rec = _make_recorder(tmp_path)
        rec.__enter__()
        rec.start("s")
        # Push three pose timestamps during the active recording. start()
        # resets the buffer, so any pre-start values are discarded.
        web_state.record_pose_timestamp(0.0)
        web_state.record_pose_timestamp(1.5)
        web_state.record_pose_timestamp(3.2)
        rec.stop()
        rec.__exit__(None, None, None)

    meta = json.loads((tmp_path / "video_metadata.json").read_text(encoding="utf-8"))
    pts = meta["trajectory_alignment"]["pose_timestamps_seconds"]
    assert pts == [0.0, 1.5, 3.2]
