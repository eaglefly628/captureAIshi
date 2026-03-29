"""Integration tests for the main capture pipeline."""

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from core.waypoint import CameraPose
from main import run_capture, create_driver, create_grabber, create_ui_hider


# ── Factory functions ────────────────────────────────────────────────────────

class TestCreateDriver:

    def test_create_manual(self):
        args = Namespace(driver="manual", dry_run=False,
                         driver_host="127.0.0.1", driver_port=9999)
        driver = create_driver(args)
        from drivers.manual import ManualDriver
        assert isinstance(driver, ManualDriver)

    def test_create_manual_dry_run(self):
        args = Namespace(driver="manual", dry_run=True,
                         driver_host="127.0.0.1", driver_port=9999)
        driver = create_driver(args)
        assert driver.auto_confirm is True

    def test_create_ue5(self):
        args = Namespace(driver="ue5", dry_run=False,
                         driver_host="127.0.0.1", driver_port=9998)
        driver = create_driver(args)
        from drivers.ue5_console import UE5ConsoleDriver
        assert isinstance(driver, UE5ConsoleDriver)

    def test_create_unity(self):
        args = Namespace(driver="unity", dry_run=False,
                         driver_host="127.0.0.1", driver_port=9999)
        driver = create_driver(args)
        from drivers.unity_socket import UnitySocketDriver
        assert isinstance(driver, UnitySocketDriver)

    def test_create_cheatengine(self):
        args = Namespace(driver="cheatengine", dry_run=False,
                         driver_host="127.0.0.1", driver_port=13370,
                         ce_mode="file")
        driver = create_driver(args)
        from drivers.cheat_engine import CheatEngineDriver
        assert isinstance(driver, CheatEngineDriver)

    def test_unknown_driver_raises(self):
        args = Namespace(driver="unknown", dry_run=False,
                         driver_host="127.0.0.1", driver_port=9999)
        with pytest.raises(ValueError, match="Unknown driver"):
            create_driver(args)


class TestCreateGrabber:

    def test_dry_run_returns_none(self, tmp_path):
        args = Namespace(dry_run=True, grabber="screenshot",
                         output_dir=tmp_path)
        assert create_grabber(args) is None

    def test_none_returns_none(self, tmp_path):
        args = Namespace(dry_run=False, grabber="none",
                         output_dir=tmp_path)
        assert create_grabber(args) is None

    def test_screenshot_grabber(self, tmp_path):
        args = Namespace(dry_run=False, grabber="screenshot",
                         output_dir=tmp_path)
        grabber = create_grabber(args)
        from grabbers.screenshot_grabber import ScreenshotGrabber
        assert isinstance(grabber, ScreenshotGrabber)

    def test_renderdoc_grabber(self, tmp_path):
        args = Namespace(dry_run=False, grabber="renderdoc",
                         output_dir=tmp_path, target_exe=None)
        grabber = create_grabber(args)
        from grabbers.renderdoc_grabber import RenderDocGrabber
        assert isinstance(grabber, RenderDocGrabber)


class TestCreateUIHider:

    def test_no_engine_no_renderdoc(self):
        args = Namespace(driver="manual", grabber="none",
                         driver_host="127.0.0.1", driver_port=9999)
        hider = create_ui_hider(args)
        from ui_hiders.noop_hider import NoopUIHider
        assert isinstance(hider, NoopUIHider)

    def test_ue5_engine_builds_console(self):
        args = Namespace(driver="ue5", grabber="none",
                         driver_host="127.0.0.1", driver_port=9998)
        hider = create_ui_hider(args)
        from ui_hiders.console_hider import ConsoleUIHider
        assert isinstance(hider, ConsoleUIHider)


# ── Dry-run integration ─────────────────────────────────────────────────────

class TestDryRun:

    def test_dry_run_generates_poses(self, tmp_path):
        """Dry run should generate poses.json without capturing."""
        args = Namespace(
            volume_min=[-2, 0, -2],
            volume_max=[2, 1, 2],
            spacing=2.0,
            smooth=False,
            smooth_points=5,
            cone_angle=0,
            cone_samples=8,
            cone_rings=2,
            driver="manual",
            driver_host="127.0.0.1",
            driver_port=9999,
            ce_mode="file",
            grabber="none",
            target_exe=None,
            no_hide_ui=True,
            output_dir=tmp_path / "output",
            dry_run=True,
        )

        run_capture(args)

        poses_file = tmp_path / "output" / "poses.json"
        assert poses_file.exists()

        poses = json.loads(poses_file.read_text())
        assert len(poses) > 0
        assert "position" in poses[0]
        assert "rotation" in poses[0]

    def test_dry_run_with_cone(self, tmp_path):
        """Dry run with cone rotation should generate more poses."""
        args = Namespace(
            volume_min=[0, 0, 0],
            volume_max=[2, 0, 2],
            spacing=2.0,
            smooth=False,
            smooth_points=5,
            cone_angle=15,
            cone_samples=4,
            cone_rings=1,
            driver="manual",
            driver_host="127.0.0.1",
            driver_port=9999,
            ce_mode="file",
            grabber="none",
            target_exe=None,
            no_hide_ui=True,
            output_dir=tmp_path / "output",
            dry_run=True,
        )

        run_capture(args)
        poses = json.loads((tmp_path / "output" / "poses.json").read_text())
        # With cone rotation, each waypoint generates multiple poses
        # So total poses > number of waypoints
        assert len(poses) > 1

    def test_dry_run_with_smoothing(self, tmp_path):
        """Dry run with smoothing should generate more waypoints."""
        args = Namespace(
            volume_min=[-5, 0, -5],
            volume_max=[5, 3, 5],
            spacing=5.0,
            smooth=True,
            smooth_points=5,
            cone_angle=0,
            cone_samples=8,
            cone_rings=2,
            driver="manual",
            driver_host="127.0.0.1",
            driver_port=9999,
            ce_mode="file",
            grabber="none",
            target_exe=None,
            no_hide_ui=True,
            output_dir=tmp_path / "output",
            dry_run=True,
        )

        run_capture(args)
        poses = json.loads((tmp_path / "output" / "poses.json").read_text())
        assert len(poses) > 0


# ── Full pipeline with mocked driver/grabber ─────────────────────────────────

class TestFullPipeline:

    def test_capture_with_mock_driver_and_grabber(self, tmp_path):
        """Full pipeline should call driver.set_pose and grabber.capture_frame."""
        from grabbers.base import FrameData

        args = Namespace(
            volume_min=[0, 0, 0],
            volume_max=[2, 0, 0],
            spacing=2.0,
            smooth=False,
            smooth_points=5,
            cone_angle=0,
            cone_samples=8,
            cone_rings=2,
            fov=90.0,
            aspect=16.0 / 9.0,
            driver="manual",
            driver_host="127.0.0.1",
            driver_port=9999,
            ce_mode="file",
            grabber="screenshot",
            target_exe=None,
            no_hide_ui=True,
            no_batch_export=True,
            output_dir=tmp_path / "output",
            dry_run=False,
        )

        mock_grabber = MagicMock()
        mock_grabber.capture_frame_ex.return_value = FrameData(
            rgb=np.zeros((4, 4, 3), dtype=np.uint8),
            depth=np.zeros((4, 4), dtype=np.float32),
        )
        mock_grabber.save_frame.return_value = {"rgb": "test.png", "depth": "test_d.png"}

        # Mock create_driver to return auto_confirm manual driver
        from drivers.manual import ManualDriver
        mock_driver = ManualDriver(auto_confirm=True)

        with patch("main.create_grabber", return_value=mock_grabber), \
             patch("main.create_driver", return_value=mock_driver):
            run_capture(args)

        # Grabber should have been set up and frames captured
        mock_grabber.setup.assert_called_once()
        assert mock_grabber.capture_frame_ex.call_count > 0
        mock_grabber.teardown.assert_called_once()

    def test_stop_event_halts_capture(self, tmp_path):
        """Setting stop_event should halt the capture loop early."""
        import threading
        from grabbers.base import FrameData

        args = Namespace(
            volume_min=[-5, 0, -5],
            volume_max=[5, 3, 5],
            spacing=1.0,  # Many waypoints
            smooth=False,
            smooth_points=5,
            cone_angle=0,
            cone_samples=8,
            cone_rings=2,
            fov=90.0,
            aspect=16.0 / 9.0,
            driver="manual",
            driver_host="127.0.0.1",
            driver_port=9999,
            ce_mode="file",
            grabber="screenshot",
            target_exe=None,
            no_hide_ui=True,
            no_batch_export=True,
            output_dir=tmp_path / "output",
            dry_run=False,
            _stop_event=threading.Event(),
        )

        call_count = 0
        def mock_capture_ex():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                args._stop_event.set()
            return FrameData()

        mock_grabber = MagicMock()
        mock_grabber.capture_frame_ex.side_effect = mock_capture_ex
        mock_grabber.save_frame.return_value = {}

        from drivers.manual import ManualDriver
        mock_driver = ManualDriver(auto_confirm=True)

        with patch("main.create_grabber", return_value=mock_grabber), \
             patch("main.create_driver", return_value=mock_driver):
            run_capture(args)

        # Should have stopped early (not captured all waypoints)
        total_poses = json.loads(
            (tmp_path / "output" / "poses.json").read_text()
        )
        assert mock_grabber.capture_frame_ex.call_count < len(total_poses)
