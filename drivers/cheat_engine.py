"""Cheat Engine memory write driver.

Controls the camera by directly writing position/rotation values
to game memory via Cheat Engine's autoattach and table scripts.

This driver communicates with Cheat Engine via its built-in
Lua socket server or by writing to a shared memory-mapped file.

Note: This is the most universal approach but requires per-game
memory scanning to find camera struct offsets.
"""

import json
import socket
import time
import logging
from pathlib import Path
from typing import Optional

from drivers.base import CameraDriver
from core.waypoint import CameraPose

logger = logging.getLogger(__name__)


class CheatEngineDriver(CameraDriver):
    """Control camera via Cheat Engine Lua socket or shared file.

    Two modes:
      - socket: Connect to CE's Lua socket server, send Lua commands
      - file: Write poses to a JSON file that a CE Lua script polls
    """

    def __init__(
        self,
        mode: str = "file",
        host: str = "127.0.0.1",
        port: int = 13370,
        shared_file: str = "./ce_camera_pose.json",
        settle_time: float = 0.1,
        coord_system: str = "pipeline",
    ):
        """
        Args:
            mode: "socket" or "file".
            host: CE Lua socket host (socket mode only).
            port: CE Lua socket port (socket mode only).
            shared_file: Path to shared JSON file (file mode only).
            settle_time: Seconds to wait after setting pose.
            coord_system: Coordinate system of target game.
                          "pipeline" = Y-up meters (pass through),
                          "ue5" = convert to Z-up centimeters,
                          "unity" = Y-up, left-hand, meters.
        """
        self.mode = mode
        self.host = host
        self.port = port
        self.shared_file = Path(shared_file)
        self.settle_time = settle_time
        self.coord_system = coord_system
        self._socket: Optional[socket.socket] = None

    def connect(self) -> None:
        if self.mode == "socket":
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(5.0)
            self._socket.connect((self.host, self.port))
            logger.info(f"Connected to Cheat Engine Lua at {self.host}:{self.port}")
        elif self.mode == "file":
            self.shared_file.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Using shared file mode: {self.shared_file}")

    def disconnect(self) -> None:
        if self._socket:
            self._socket.close()
            self._socket = None
        logger.info("Cheat Engine driver disconnected")

    def set_pose(self, pose: CameraPose) -> None:
        pos = pose.position.copy()
        rot = pose.rotation.copy()

        if self.coord_system == "ue5":
            from utils.coords import pipeline_to_ue5_position, pipeline_to_ue5_rotation
            pos = pipeline_to_ue5_position(pos)
            rot = pipeline_to_ue5_rotation(rot)
        elif self.coord_system == "unity":
            from utils.coords import pipeline_to_unity_position, pipeline_to_unity_rotation
            pos = pipeline_to_unity_position(pos)
            rot = pipeline_to_unity_rotation(rot)

        logger.debug(
            f"[CE] mode={self.mode}, coord_system={self.coord_system}, "
            f"pos=({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f}), "
            f"rot=({rot[0]:.1f}, {rot[1]:.1f}, {rot[2]:.1f}), fov={pose.fov:.0f}"
        )

        if self.mode == "socket":
            self._send_lua(pos, rot, pose.fov)
        elif self.mode == "file":
            self._write_file(pos, rot, pose.fov)

        time.sleep(self.settle_time)

    def _send_lua(self, pos, rot, fov):
        lua_cmd = (
            f"setCameraPos({pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f})\n"
            f"setCameraRot({rot[0]:.4f}, {rot[1]:.4f}, {rot[2]:.4f})\n"
            f"setCameraFOV({fov:.1f})\n"
        )
        if self._socket:
            self._socket.sendall(lua_cmd.encode("utf-8"))

    def _write_file(self, pos, rot, fov):
        data = {
            "position": [float(pos[0]), float(pos[1]), float(pos[2])],
            "rotation": [float(rot[0]), float(rot[1]), float(rot[2])],
            "fov": float(fov),
            "timestamp": time.time(),
        }
        self.shared_file.write_text(json.dumps(data))

    def update_streaming(self, pose: CameraPose) -> None:
        """Write streaming position for CE Lua script to update.

        The companion Lua script in Cheat Engine should read this file
        and write the position to the game's streaming center address
        (which must be found via memory scanning per game).
        """
        pos = pose.position.copy()
        if self.coord_system == "ue5":
            from utils.coords import pipeline_to_ue5_position
            pos = pipeline_to_ue5_position(pos)
        elif self.coord_system == "unity":
            from utils.coords import pipeline_to_unity_position
            pos = pipeline_to_unity_position(pos)

        streaming_file = self.shared_file.parent / "ce_streaming_pos.json"
        data = {
            "streaming_position": [float(pos[0]), float(pos[1]), float(pos[2])],
            "timestamp": time.time(),
        }
        streaming_file.write_text(json.dumps(data))
        logger.debug(
            f"[STREAMING] Wrote streaming pos to {streaming_file}: "
            f"({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})"
        )
