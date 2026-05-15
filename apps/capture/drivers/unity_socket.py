"""Unity BepInEx mod socket driver.

Controls the camera in Unity games by sending JSON pose commands
to a BepInEx plugin (CameraCapturePlugin) over TCP.

Protocol: Send JSON lines, each containing:
  {"cmd": "set_pose", "x": ..., "y": ..., "z": ..., "pitch": ..., "yaw": ..., "roll": ..., "fov": ...}
  {"cmd": "ping"}
  {"cmd": "update_streaming", "x": ..., "y": ..., "z": ...}
  {"cmd": "force_lod", "max_lod": 0, "lod_bias": 100.0}

Streaming management:
  Unity uses LOD Groups and addressable/scene streaming. The plugin
  must move the streaming reference point and force LOD0 to ensure
  captured frames have full-quality assets.
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
    """Control Unity camera via BepInEx companion plugin TCP socket.

    Streaming strategy:
      1. Send 'update_streaming' command to move the player/streaming
         reference point to the camera position — triggers scene
         streaming and asset loading around the capture area.
      2. Send 'force_lod' command to override LOD bias so all LOD
         Groups render at maximum detail (LOD0).
      3. Configurable settle time to wait for asset loading.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9999,
        settle_time: float = 0.05,
        streaming_settle: float = 0.3,
        force_lod: bool = True,
        teleport_player: bool = True,
    ):
        self.host = host
        self.port = port
        self.settle_time = settle_time
        self.streaming_settle = streaming_settle
        self.force_lod = force_lod
        self.teleport_player = teleport_player
        self._socket: Optional[socket.socket] = None
        self._streaming_initialized = False
        self._last_streaming_pos = None

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
            # Restore streaming defaults
            if self._streaming_initialized:
                self._restore_streaming_defaults()
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

        logger.debug(
            f"[UNITY] Pipeline pos=({pose.position[0]:.2f}, {pose.position[1]:.2f}, {pose.position[2]:.2f}) "
            f"→ Unity pos=({unity_pos[0]:.2f}, {unity_pos[1]:.2f}, {unity_pos[2]:.2f})"
        )
        logger.debug(
            f"[UNITY] Pipeline rot=({pose.rotation[0]:.1f}, {pose.rotation[1]:.1f}, {pose.rotation[2]:.1f}) "
            f"→ Unity rot=({unity_rot[0]:.1f}, {unity_rot[1]:.1f}, {unity_rot[2]:.1f})"
        )

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

    def update_streaming(self, pose: CameraPose) -> None:
        """Update Unity streaming and LOD to load assets around camera.

        Sends commands to the BepInEx companion plugin to:
        1. Move the player/streaming reference to camera position
        2. Force LOD Group bias so all meshes render at LOD0
        3. Set maximum texture quality around the capture area
        """
        unity_pos = pipeline_to_unity_position(pose.position)

        # One-time LOD/quality initialization
        if not self._streaming_initialized:
            self._init_streaming()
            self._streaming_initialized = True

        # Skip update if camera hasn't moved much (< 0.5m)
        if self._last_streaming_pos is not None:
            dx = abs(unity_pos[0] - self._last_streaming_pos[0])
            dy = abs(unity_pos[1] - self._last_streaming_pos[1])
            dz = abs(unity_pos[2] - self._last_streaming_pos[2])
            if dx < 0.5 and dy < 0.5 and dz < 0.5:
                return

        # Move streaming reference point (player transform)
        if self.teleport_player:
            self._send_json({
                "cmd": "update_streaming",
                "x": float(unity_pos[0]),
                "y": float(unity_pos[1]),
                "z": float(unity_pos[2]),
            })
            logger.debug(
                f"[STREAMING] Updated Unity streaming pos to "
                f"({unity_pos[0]:.2f}, {unity_pos[1]:.2f}, {unity_pos[2]:.2f})"
            )

        self._last_streaming_pos = list(unity_pos)

    def wait_for_streaming(self, timeout: float = 0.0) -> None:
        """Wait for Unity asset streaming and LOD transitions to settle."""
        wait = timeout if timeout > 0 else self.streaming_settle
        if wait > 0:
            logger.debug(f"[STREAMING] Waiting {wait:.2f}s for Unity streaming")
            time.sleep(wait)

    def _init_streaming(self) -> None:
        """One-time streaming and quality overrides for capture session."""
        logger.info("[STREAMING] Initializing Unity streaming overrides")

        if self.force_lod:
            # Force LOD bias to maximum — renders all LODGroups at LOD0
            self._send_json({
                "cmd": "force_lod",
                "max_lod": 0,
                "lod_bias": 100.0,
            })
            logger.info("[STREAMING] LOD forced to level 0 (max detail)")

        logger.info(
            f"[STREAMING] teleport={self.teleport_player}, "
            f"force_lod={self.force_lod}, settle={self.streaming_settle}s"
        )

    def _restore_streaming_defaults(self) -> None:
        """Restore default LOD and streaming settings."""
        logger.info("[STREAMING] Restoring Unity default streaming settings")
        try:
            self._send_json({
                "cmd": "force_lod",
                "max_lod": -1,
                "lod_bias": 1.0,
            })
        except Exception as e:
            logger.warning(f"[STREAMING] Failed to restore defaults: {e}")
