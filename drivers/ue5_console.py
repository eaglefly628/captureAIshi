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
        capture_resolution: Optional[str] = None,
        disable_upscaler: bool = True,
    ):
        self.host = host
        self.port = port
        self.settle_time = settle_time
        self.streaming_settle = streaming_settle
        self.streaming_pool_mb = streaming_pool_mb
        self.teleport_player = teleport_player
        self.force_texture_streaming = force_texture_streaming
        self.capture_resolution = capture_resolution  # e.g. "3840x2160"
        self.disable_upscaler = disable_upscaler
        self._socket: Optional[socket.socket] = None
        self._streaming_initialized = False
        self._last_streaming_pos = None

    def connect(self) -> None:
        logger.info(f"[UE5] Connecting to {self.host}:{self.port}...")
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(5.0)
        try:
            self._socket.connect((self.host, self.port))
        except ConnectionRefusedError:
            logger.error(
                f"[UE5] Connection refused at {self.host}:{self.port}. "
                f"Is the game running with console enabled (UUU)?"
            )
            raise
        except socket.timeout:
            logger.error(
                f"[UE5] Connection timed out to {self.host}:{self.port}. "
                f"Check firewall and that the game's TCP console is active."
            )
            raise
        except OSError as e:
            logger.error(f"[UE5] Socket error connecting to {self.host}:{self.port}: {e}")
            raise
        logger.info(f"[UE5] Connected to UE5 console at {self.host}:{self.port}")

    def disconnect(self) -> None:
        if self._socket:
            # Restore default streaming settings
            if self._streaming_initialized:
                self._restore_streaming_defaults()
            # Restore rendering/upscaler settings
            self._restore_rendering_defaults()
            try:
                self._socket.close()
            except OSError as e:
                logger.warning(f"[UE5] Error closing socket: {e}")
            self._socket = None
            logger.info("[UE5] Disconnected from UE5 console")

    def send_command(self, command: str) -> None:
        """Send a console command to the game."""
        if not self._socket:
            raise RuntimeError("Not connected to UE5 console")
        msg = (command + "\n").encode("utf-8")
        try:
            self._socket.sendall(msg)
            logger.debug(f"[UE5] Sent: {command}")
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.error(f"[UE5] Failed to send command '{command}': {e}")
            raise

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

        # Wait for UE5 to process camera commands before capture
        # 0.1s is too short — UE5 needs time to apply view changes
        settle = max(self.settle_time, 0.3)
        time.sleep(settle)

    def update_streaming(self, pose: CameraPose) -> None:
        """Force UE5 streaming system to load assets around camera position."""
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

        if self.teleport_player:
            pawn_z = ue_pos[2] - 200
            self.send_command(
                f"Teleport {ue_pos[0]:.2f} {ue_pos[1]:.2f} {pawn_z:.2f}"
            )
            logger.debug(
                f"[STREAMING] Teleported player to "
                f"({ue_pos[0]:.0f}, {ue_pos[1]:.0f}, {pawn_z:.0f})"
            )

        if self.force_texture_streaming:
            self.send_command("r.Streaming.FullyLoadUsedTextures 1")

        self._last_streaming_pos = list(ue_pos)

    def wait_for_streaming(self, timeout: float = 0.0) -> None:
        """Wait for UE5 texture and level streaming to settle."""
        wait = timeout if timeout > 0 else self.streaming_settle
        if wait > 0:
            logger.debug(f"[STREAMING] Waiting {wait:.2f}s for streaming to settle")
            time.sleep(wait)

    def _init_streaming(self) -> None:
        """One-time streaming configuration for the capture session."""
        logger.info("[STREAMING] Initializing UE5 streaming overrides")

        cmds = [
            (f"r.Streaming.PoolSize {self.streaming_pool_mb}", "texture pool size"),
            ("r.Streaming.FullyLoadUsedTextures 1", "full mip loading"),
            ("r.StaticMeshLODDistanceScale 0.1", "static mesh LOD bias"),
            ("foliage.LODDistanceScale 10.0", "foliage LOD"),
            ("r.HLOD 0", "HLOD disable"),
            ("r.Streaming.MinMipForSplitRequest 0", "min mip for streaming"),
        ]
        if self.teleport_player:
            cmds.append(("ShowFlag.SkeletalMeshes 0", "hide player mesh"))

        for cmd, desc in cmds:
            try:
                self.send_command(cmd)
            except Exception as e:
                logger.warning(f"[STREAMING] Failed to set {desc}: {e}")

        logger.info(
            f"[STREAMING] Pool={self.streaming_pool_mb}MB, "
            f"teleport={self.teleport_player}, "
            f"settle={self.streaming_settle}s"
        )

    def _restore_streaming_defaults(self) -> None:
        """Restore default streaming settings when disconnecting."""
        logger.info("[STREAMING] Restoring UE5 default streaming settings")
        restore_cmds = [
            "r.Streaming.FullyLoadUsedTextures 0",
            "r.Streaming.PoolSize 1000",
            "r.StaticMeshLODDistanceScale 1.0",
            "foliage.LODDistanceScale 1.0",
            "r.HLOD 1",
        ]
        if self.teleport_player:
            restore_cmds.append("ShowFlag.SkeletalMeshes 1")

        for cmd in restore_cmds:
            try:
                self.send_command(cmd)
            except Exception as e:
                logger.warning(f"[STREAMING] Failed to restore '{cmd}': {e}")

    def enable_debug_camera(self) -> None:
        """Toggle the debug camera mode and configure rendering for capture."""
        self.send_command("ToggleDebugCamera")
        time.sleep(0.5)
        self._configure_rendering_for_capture()

    def _configure_rendering_for_capture(self) -> None:
        """Disable DLSS/FSR/TSR and set resolution for pixel-aligned buffer output.

        AI training data requires all buffers (RGB, Depth, Normal) at the same
        resolution with pixel-perfect alignment. Upscalers like DLSS/FSR render
        GBuffers at a lower internal resolution and only upscale the final RGB,
        breaking buffer alignment. This method disables all upscaling so every
        buffer is rendered at the full output resolution.
        """
        if not self.disable_upscaler:
            return

        logger.info("[RENDER] Configuring rendering for capture (disabling upscalers)")

        cmds = [
            # DLSS (NVIDIA NGX)
            ("r.NGX.Enable 0", "disable NGX framework"),
            ("r.NGX.DLSS.Enable 0", "disable DLSS"),
            ("r.NGX.DLSS.Quality.Mode -1", "disable DLSS quality mode"),

            # FSR (AMD FidelityFX)
            ("r.FidelityFX.FSR3.Enabled 0", "disable FSR3"),
            ("r.FidelityFX.FSR2.Enabled 0", "disable FSR2"),

            # UE5 Temporal Super Resolution (TSR)
            ("r.TemporalAA.Upscaler 0", "disable TSR, fall back to native TAA"),
            ("r.AntiAliasingMethod 2", "use TAA (method 2)"),

            # Force native resolution rendering (no internal downscale)
            ("r.ScreenPercentage 100", "render at 100% of output resolution"),

            # Disable dynamic resolution scaling
            ("r.DynamicRes.OperationMode 0", "disable dynamic resolution"),
        ]

        for cmd, desc in cmds:
            try:
                self.send_command(cmd)
            except Exception as e:
                logger.debug(f"[RENDER] {desc} skipped: {e}")

        # Set capture resolution if specified
        if self.capture_resolution:
            try:
                self.send_command(f"r.SetRes {self.capture_resolution}w")
                logger.info(f"[RENDER] Resolution set to {self.capture_resolution} (windowed)")
            except Exception as e:
                logger.warning(f"[RENDER] Failed to set resolution: {e}")

        logger.info("[RENDER] Upscaler disabled, native resolution rendering active")

    def _restore_rendering_defaults(self) -> None:
        """Restore default rendering/upscaler settings."""
        if not self.disable_upscaler:
            return

        logger.info("[RENDER] Restoring default rendering settings")
        restore_cmds = [
            "r.NGX.Enable 1",
            "r.NGX.DLSS.Enable 1",
            "r.TemporalAA.Upscaler 1",
            "r.ScreenPercentage 100",
            "r.DynamicRes.OperationMode 2",
        ]
        for cmd in restore_cmds:
            try:
                self.send_command(cmd)
            except Exception as e:
                logger.debug(f"[RENDER] Restore '{cmd}' skipped: {e}")
