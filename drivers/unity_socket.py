"""Unity BepInEx mod socket driver.

Controls the camera in Unity games by sending JSON pose commands
to a BepInEx plugin (CameraCapturePlugin) over TCP.

Protocol: Send JSON lines, each containing:
  {"cmd": "set_pose", "x": ..., "y": ..., "z": ..., "pitch": ..., "yaw": ..., "roll": ..., "fov": ...}
  {"cmd": "ping"}
"""

import json
import socket
import time
import logging
from typing import Optional

from drivers.base import CameraDriver
from core.waypoint import CameraPose
from utils.coords import pipeline_to_unity_position, pipeline_to_unity_rotation

logger = logging.getLogger(__name__)


class UnitySocketDriver(CameraDriver):
    """Control Unity camera via BepInEx companion plugin TCP socket."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9999,
        settle_time: float = 0.05,
    ):
        self.host = host
        self.port = port
        self.settle_time = settle_time
        self._socket: Optional[socket.socket] = None

    def connect(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(5.0)
        self._socket.connect((self.host, self.port))
        logger.info(f"Connected to Unity plugin at {self.host}:{self.port}")

        # Send a ping to verify connection
        self._send_json({"cmd": "ping"})
        resp = self._recv_line()
        logger.info(f"Unity plugin response: {resp}")

    def disconnect(self) -> None:
        if self._socket:
            self._socket.close()
            self._socket = None
            logger.info("Disconnected from Unity plugin")

    def _send_json(self, data: dict) -> None:
        if not self._socket:
            raise RuntimeError("Not connected")
        msg = (json.dumps(data) + "\n").encode("utf-8")
        self._socket.sendall(msg)

    def _recv_line(self) -> str:
        if not self._socket:
            raise RuntimeError("Not connected")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = self._socket.recv(1024)
            if not chunk:
                break
            buf += chunk
        return buf.decode("utf-8").strip()

    def set_pose(self, pose: CameraPose) -> None:
        unity_pos = pipeline_to_unity_position(pose.position)
        unity_rot = pipeline_to_unity_rotation(pose.rotation)

        self._send_json({
            "cmd": "set_pose",
            "x": float(unity_pos[0]),
            "y": float(unity_pos[1]),
            "z": float(unity_pos[2]),
            "pitch": float(unity_rot[0]),
            "yaw": float(unity_rot[1]),
            "roll": float(unity_rot[2]),
            "fov": float(pose.fov),
        })

        time.sleep(self.settle_time)
