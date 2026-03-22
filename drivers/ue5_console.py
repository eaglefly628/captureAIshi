"""UE5 console command driver.

Controls the camera in UE5 released games by sending console commands
over TCP. Requires the game to have console access enabled (e.g., via
Universal Unreal Engine Unlocker / UUU).

The driver sends commands like:
  - ToggleDebugCamera (to enter free camera mode)
  - SetViewLocation X Y Z
  - SetViewRotation Pitch Yaw Roll

Streaming management:
  The driver can force UE5's texture/level streaming system to load
  assets around the free camera position instead of the player pawn.
  This is critical for capturing high-quality training data — without
  it, areas far from the player will have low-LOD meshes and blurry
  textures.
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
    """Control UE5 camera via console commands over TCP.

    Streaming strategy (applied in order of reliability):
      1. Teleport player pawn to camera position — moves the engine's
         primary streaming source so level streaming and texture mips
         load correctly.
      2. Force texture streaming pool to a large size and request full
         mip loading for visible textures.
      3. Configurable settle time to allow assets to stream in before
         the frame is captured.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9998,
        settle_time: float = 0.1,
        streaming_settle: float = 0.5,
        streaming_pool_mb: int = 4096,
        teleport_player: bool = True,
        force_texture_streaming: bool = True,
    ):
        self.host = host
        self.port = port
        self.settle_time = settle_time
        self.streaming_settle = streaming_settle
        self.streaming_pool_mb = streaming_pool_mb
        self.teleport_player = teleport_player
        self.force_texture_streaming = force_texture_streaming
        self._socket: Optional[socket.socket] = None
        self._streaming_initialized = False
        self._last_streaming_pos = None

    def connect(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(5.0)
        self._socket.connect((self.host, self.port))
        logger.info(f"Connected to UE5 console at {self.host}:{self.port}")

    def disconnect(self) -> None:
        if self._socket:
            # Restore default streaming settings
            if self._streaming_initialized:
                self._restore_streaming_defaults()
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

        logger.debug(
            f"[UE5] Pipeline pos=({pose.position[0]:.2f}, {pose.position[1]:.2f}, {pose.position[2]:.2f}) "
            f"→ UE5 pos=({ue_pos[0]:.2f}, {ue_pos[1]:.2f}, {ue_pos[2]:.2f})"
        )
        logger.debug(
            f"[UE5] Pipeline rot=({pose.rotation[0]:.1f}, {pose.rotation[1]:.1f}, {pose.rotation[2]:.1f}) "
            f"→ UE5 rot=({ue_rot[0]:.1f}, {ue_rot[1]:.1f}, {ue_rot[2]:.1f})"
        )

        self.send_command(
            f"SetViewLocation {ue_pos[0]:.2f} {ue_pos[1]:.2f} {ue_pos[2]:.2f}"
        )
        self.send_command(
            f"SetViewRotation {ue_rot[0]:.2f} {ue_rot[1]:.2f} {ue_rot[2]:.2f}"
        )

        if pose.fov != 90.0:
            self.send_command(f"FOV {pose.fov:.1f}")

        time.sleep(self.settle_time)

    def update_streaming(self, pose: CameraPose) -> None:
        """Force UE5 streaming system to load assets around camera position.

        This addresses the core problem: in released games, the streaming
        center follows the player pawn, not the debug camera. Without
        updating the streaming source, captured frames will show low-LOD
        meshes and blurry textures at locations far from the player.
        """
        ue_pos = pipeline_to_ue5_position(pose.position)

        # One-time streaming initialization
        if not self._streaming_initialized:
            self._init_streaming()
            self._streaming_initialized = True

        # Skip if camera hasn't moved significantly (< 50cm in UE units)
        if self._last_streaming_pos is not None:
            dx = abs(ue_pos[0] - self._last_streaming_pos[0])
            dy = abs(ue_pos[1] - self._last_streaming_pos[1])
            dz = abs(ue_pos[2] - self._last_streaming_pos[2])
            if dx < 50 and dy < 50 and dz < 50:
                return

        # Strategy 1: Teleport player pawn to camera position
        # This moves the primary streaming source so level streaming
        # and texture mip selection work correctly
        if self.teleport_player:
            # Teleport slightly below camera to avoid visual interference
            pawn_z = ue_pos[2] - 200  # 2m below camera in UE units
            self.send_command(
                f"Teleport {ue_pos[0]:.2f} {ue_pos[1]:.2f} {pawn_z:.2f}"
            )
            logger.debug(
                f"[STREAMING] Teleported player to "
                f"({ue_pos[0]:.0f}, {ue_pos[1]:.0f}, {pawn_z:.0f})"
            )

        # Strategy 2: Force texture streaming to prioritize current view
        if self.force_texture_streaming:
            self.send_command("r.Streaming.FullyLoadUsedTextures 1")

        self._last_streaming_pos = list(ue_pos)

    def wait_for_streaming(self, timeout: float = 0.0) -> None:
        """Wait for UE5 texture and level streaming to settle.

        Uses streaming_settle as the default wait time, which gives the
        engine time to load textures at full mip and stream in level chunks.
        """
        wait = timeout if timeout > 0 else self.streaming_settle
        if wait > 0:
            logger.debug(f"[STREAMING] Waiting {wait:.2f}s for streaming to settle")
            time.sleep(wait)

    def _init_streaming(self) -> None:
        """One-time streaming configuration for the capture session."""
        logger.info("[STREAMING] Initializing UE5 streaming overrides")

        # Increase texture streaming pool size (default is often 1000MB)
        self.send_command(
            f"r.Streaming.PoolSize {self.streaming_pool_mb}"
        )

        # Force highest quality texture mips
        self.send_command("r.Streaming.FullyLoadUsedTextures 1")

        # Boost LOD bias — negative values force higher LOD (more detail)
        self.send_command("r.StaticMeshLODDistanceScale 0.1")

        # Disable distance-based LOD for foliage
        self.send_command("foliage.LODDistanceScale 10.0")

        # Force HLOD (Hierarchical LOD) to show detailed meshes
        self.send_command("r.HLOD 0")

        # Set forced streaming distance to a large value so the engine
        # loads textures within a wide radius
        self.send_command("r.Streaming.MinMipForSplitRequest 0")

        # Hide the player pawn mesh so it doesn't appear in captures
        if self.teleport_player:
            self.send_command("ShowFlag.SkeletalMeshes 0")
            # Re-enable after a brief moment so only the player is hidden
            # during debug camera (this is a best-effort approach)

        logger.info(
            f"[STREAMING] Pool={self.streaming_pool_mb}MB, "
            f"teleport={self.teleport_player}, "
            f"settle={self.streaming_settle}s"
        )

    def _restore_streaming_defaults(self) -> None:
        """Restore default streaming settings when disconnecting."""
        logger.info("[STREAMING] Restoring UE5 default streaming settings")
        try:
            self.send_command("r.Streaming.FullyLoadUsedTextures 0")
            self.send_command("r.Streaming.PoolSize 1000")
            self.send_command("r.StaticMeshLODDistanceScale 1.0")
            self.send_command("foliage.LODDistanceScale 1.0")
            self.send_command("r.HLOD 1")
            if self.teleport_player:
                self.send_command("ShowFlag.SkeletalMeshes 1")
        except Exception as e:
            logger.warning(f"[STREAMING] Failed to restore defaults: {e}")

    def enable_debug_camera(self) -> None:
        """Toggle the debug camera mode."""
        self.send_command("ToggleDebugCamera")
        time.sleep(0.5)
