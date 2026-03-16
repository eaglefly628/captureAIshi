"""UE5 console command driver.

Controls the camera in UE5 released games by sending console commands
over TCP. Requires the game to have console access enabled (e.g., via
Universal Unreal Engine Unlocker / UUU).

The driver sends commands like:
  - ToggleDebugCamera (to enter free camera mode)
  - SetViewLocation X Y Z
  - SetViewRotation Pitch Yaw Roll
"""

import socket
import time
import logging
from typing import Optional

from drivers.base import CameraDriver
from core.waypoint import CameraPose
from utils.coords import pipeline_to_ue5_position, pipeline_to_ue5_rotation

logger = logging.getLogger(__name__)


class UE5ConsoleDriver(CameraDriver):
    """Control UE5 camera via console commands over TCP."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9998,
        settle_time: float = 0.1,
    ):
        self.host = host
        self.port = port
        self.settle_time = settle_time
        self._socket: Optional[socket.socket] = None

    def connect(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(5.0)
        self._socket.connect((self.host, self.port))
        logger.info(f"Connected to UE5 console at {self.host}:{self.port}")

    def disconnect(self) -> None:
        if self._socket:
            self._socket.close()
            self._socket = None
            logger.info("Disconnected from UE5 console")

    def send_command(self, command: str) -> None:
        """Send a console command to the game."""
        if not self._socket:
            raise RuntimeError("Not connected")
        msg = (command + "\n").encode("utf-8")
        self._socket.sendall(msg)
        logger.debug(f"Sent: {command}")

    def set_pose(self, pose: CameraPose) -> None:
        ue_pos = pipeline_to_ue5_position(pose.position)
        ue_rot = pipeline_to_ue5_rotation(pose.rotation)

        self.send_command(
            f"SetViewLocation {ue_pos[0]:.2f} {ue_pos[1]:.2f} {ue_pos[2]:.2f}"
        )
        self.send_command(
            f"SetViewRotation {ue_rot[0]:.2f} {ue_rot[1]:.2f} {ue_rot[2]:.2f}"
        )

        if pose.fov != 90.0:
            self.send_command(f"FOV {pose.fov:.1f}")

        time.sleep(self.settle_time)

    def enable_debug_camera(self) -> None:
        """Toggle the debug camera mode."""
        self.send_command("ToggleDebugCamera")
        time.sleep(0.5)
