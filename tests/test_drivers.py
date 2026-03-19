"""Tests for camera control drivers."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from core.waypoint import CameraPose
from drivers.manual import ManualDriver
from drivers.ue5_console import UE5ConsoleDriver
from drivers.unity_socket import UnitySocketDriver
from drivers.cheat_engine import CheatEngineDriver


# ── ManualDriver ─────────────────────────────────────────────────────────────

class TestManualDriver:

    def test_context_manager(self):
        """Manual driver should work as a context manager."""
        driver = ManualDriver(auto_confirm=True)
        with driver:
            pass  # connect/disconnect should not raise

    def test_set_pose_auto_confirm(self, sample_pose, capsys):
        """set_pose in auto mode should print but not block."""
        driver = ManualDriver(auto_confirm=True)
        driver.connect()
        driver.set_pose(sample_pose)
        out = capsys.readouterr().out
        assert "Pose #1" in out
        assert "1.00" in out  # x position
        driver.disconnect()

    def test_pose_counter(self, sample_pose):
        """Pose counter should increment."""
        driver = ManualDriver(auto_confirm=True)
        driver.connect()
        driver.set_pose(sample_pose)
        driver.set_pose(sample_pose)
        assert driver._pose_count == 2

    def test_set_pose_blocks_on_input(self, sample_pose):
        """Without auto_confirm, set_pose should call input()."""
        driver = ManualDriver(auto_confirm=False)
        driver.connect()
        with patch("builtins.input", return_value=""):
            driver.set_pose(sample_pose)
        driver.disconnect()


# ── UE5ConsoleDriver ────────────────────────────────────────────────────────

class TestUE5ConsoleDriver:

    def test_connect_and_set_pose(self, echo_server, sample_pose):
        """UE5 driver should send SetViewLocation/SetViewRotation commands."""
        driver = UE5ConsoleDriver(
            host="127.0.0.1",
            port=echo_server.port,
            settle_time=0.01,
        )
        driver.connect()
        driver.set_pose(sample_pose)
        driver.disconnect()

        time.sleep(0.1)
        received = echo_server.received_text
        assert "SetViewLocation" in received
        assert "SetViewRotation" in received

    def test_custom_fov_sent(self, echo_server):
        """Non-90 FOV should trigger a FOV command."""
        pose = CameraPose(
            position=np.array([0.0, 0.0, 0.0]),
            rotation=np.array([0.0, 0.0, 0.0]),
            fov=60.0,
        )
        driver = UE5ConsoleDriver(
            host="127.0.0.1",
            port=echo_server.port,
            settle_time=0.01,
        )
        driver.connect()
        driver.set_pose(pose)
        driver.disconnect()

        time.sleep(0.1)
        assert "FOV 60.0" in echo_server.received_text

    def test_default_fov_skipped(self, echo_server, sample_pose):
        """FOV=90 should NOT send a FOV command."""
        sample_pose.fov = 90.0
        driver = UE5ConsoleDriver(
            host="127.0.0.1",
            port=echo_server.port,
            settle_time=0.01,
        )
        driver.connect()
        driver.set_pose(sample_pose)
        driver.disconnect()

        time.sleep(0.1)
        assert "FOV" not in echo_server.received_text

    def test_send_without_connect_raises(self, sample_pose):
        """Sending a command without connecting should raise."""
        driver = UE5ConsoleDriver()
        with pytest.raises(RuntimeError, match="Not connected"):
            driver.send_command("test")

    def test_context_manager(self, echo_server):
        """Context manager should connect/disconnect."""
        driver = UE5ConsoleDriver(
            host="127.0.0.1",
            port=echo_server.port,
        )
        with driver:
            assert driver._socket is not None
        assert driver._socket is None

    def test_coordinate_conversion(self, echo_server):
        """Position should be converted from pipeline to UE5 coords."""
        pose = CameraPose(
            position=np.array([1.0, 0.0, 0.0]),  # 1m on pipeline X
            rotation=np.array([0.0, 0.0, 0.0]),
            fov=90.0,
        )
        driver = UE5ConsoleDriver(
            host="127.0.0.1",
            port=echo_server.port,
            settle_time=0.01,
        )
        driver.connect()
        driver.set_pose(pose)
        driver.disconnect()

        time.sleep(0.1)
        # Pipeline X=1m → UE5 Y=100cm
        assert "100.00" in echo_server.received_text


# ── UnitySocketDriver ───────────────────────────────────────────────────────

class TestUnitySocketDriver:

    def test_connect_sends_ping(self, echo_server):
        """Connecting should send a ping command."""
        driver = UnitySocketDriver(
            host="127.0.0.1",
            port=echo_server.port,
            settle_time=0.01,
        )
        driver.connect()
        driver.disconnect()

        time.sleep(0.1)
        received = echo_server.received_text
        assert '"cmd": "ping"' in received or '"cmd":"ping"' in received

    def test_set_pose_sends_json(self, echo_server, sample_pose):
        """set_pose should send a JSON set_pose command."""
        driver = UnitySocketDriver(
            host="127.0.0.1",
            port=echo_server.port,
            settle_time=0.01,
        )
        driver.connect()
        driver.set_pose(sample_pose)
        driver.disconnect()

        time.sleep(0.1)
        received = echo_server.received_text
        assert "set_pose" in received
        # Check JSON structure
        lines = [l for l in received.strip().split("\n") if "set_pose" in l]
        assert len(lines) >= 1
        data = json.loads(lines[0])
        assert data["cmd"] == "set_pose"
        assert "x" in data and "y" in data and "z" in data
        assert "pitch" in data and "yaw" in data

    def test_unity_z_flip(self, echo_server):
        """Unity position should have Z flipped."""
        pose = CameraPose(
            position=np.array([0.0, 0.0, 5.0]),
            rotation=np.array([0.0, 0.0, 0.0]),
            fov=90.0,
        )
        driver = UnitySocketDriver(
            host="127.0.0.1",
            port=echo_server.port,
            settle_time=0.01,
        )
        driver.connect()
        driver.set_pose(pose)
        driver.disconnect()

        time.sleep(0.1)
        lines = [l for l in echo_server.received_text.strip().split("\n") if "set_pose" in l]
        data = json.loads(lines[0])
        assert data["z"] == pytest.approx(-5.0)


# ── CheatEngineDriver ───────────────────────────────────────────────────────

class TestCheatEngineDriver:

    def test_file_mode_writes_json(self, tmp_path, sample_pose):
        """File mode should write pose to a JSON file."""
        shared_file = tmp_path / "ce_pose.json"
        driver = CheatEngineDriver(
            mode="file",
            shared_file=str(shared_file),
            settle_time=0.01,
        )
        driver.connect()
        driver.set_pose(sample_pose)
        driver.disconnect()

        assert shared_file.exists()
        data = json.loads(shared_file.read_text())
        assert "position" in data
        assert "rotation" in data
        assert "fov" in data
        assert "timestamp" in data
        assert len(data["position"]) == 3
        assert data["fov"] == 90.0

    def test_file_mode_updates_on_each_pose(self, tmp_path):
        """Each set_pose should update the file."""
        shared_file = tmp_path / "ce_pose.json"
        driver = CheatEngineDriver(
            mode="file",
            shared_file=str(shared_file),
            settle_time=0.01,
        )
        driver.connect()

        pose1 = CameraPose(np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0]))
        driver.set_pose(pose1)
        data1 = json.loads(shared_file.read_text())

        pose2 = CameraPose(np.array([99.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0]))
        driver.set_pose(pose2)
        data2 = json.loads(shared_file.read_text())

        assert data2["position"][0] == pytest.approx(99.0)
        assert data2["timestamp"] >= data1["timestamp"]
        driver.disconnect()

    def test_socket_mode_sends_lua(self, echo_server, sample_pose):
        """Socket mode should send Lua camera commands."""
        driver = CheatEngineDriver(
            mode="socket",
            host="127.0.0.1",
            port=echo_server.port,
            settle_time=0.01,
        )
        driver.connect()
        driver.set_pose(sample_pose)
        driver.disconnect()

        time.sleep(0.1)
        received = echo_server.received_text
        assert "setCameraPos" in received
        assert "setCameraRot" in received
        assert "setCameraFOV" in received

    def test_ue5_coord_conversion(self, tmp_path):
        """coord_system='ue5' should convert coordinates."""
        shared_file = tmp_path / "ce_pose.json"
        driver = CheatEngineDriver(
            mode="file",
            shared_file=str(shared_file),
            coord_system="ue5",
            settle_time=0.01,
        )
        driver.connect()
        pose = CameraPose(np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0]))
        driver.set_pose(pose)
        driver.disconnect()

        data = json.loads(shared_file.read_text())
        # Pipeline X=1m → UE5 Y=100cm
        assert data["position"][1] == pytest.approx(100.0)
