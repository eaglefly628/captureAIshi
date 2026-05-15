"""Camera path control via captureAIshi bridge DLL.

Provides Python API for the bridge's camera path system:
  - Record keyframes
  - Play back paths with Catmull-Rom + SLERP interpolation
  - Capture frames at regular intervals along the path

This module talks to the bridge DLL over TCP using the same
connection as UE5ConsoleDriver. All __path_* and __bridge_*
commands are bridge-specific extensions; regular console
commands pass through to UE5's Exec().

Usage:
    from drivers.bridge_path import BridgePathController

    ctl = BridgePathController(host="127.0.0.1", port=9998)
    ctl.connect()

    # Add keyframes
    ctl.add_keyframe(100, 200, 300, pitch=-10, yaw=45, fov=90, duration=3.0)
    ctl.add_keyframe(500, 200, 800, pitch=-5, yaw=90, fov=90, duration=3.0)
    ctl.add_keyframe(900, 200, 300, pitch=0, yaw=135, fov=90, duration=3.0)

    # Play and capture
    ctl.play(speed=0.5)
    ctl.wait_for_completion()

    # Or: capture at intervals along the path
    frames = ctl.capture_along_path(grabber, interval=0.5)
"""

import logging
import socket
import time
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


class BridgePathController:
    """Control camera paths via the captureAIshi bridge TCP protocol."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9998):
        self.host = host
        self.port = port
        self._socket: Optional[socket.socket] = None

    def connect(self) -> None:
        """Connect to the bridge TCP server."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(5.0)
        self._socket.connect((self.host, self.port))
        logger.info(f"[BRIDGE] Connected to bridge at {self.host}:{self.port}")

    def disconnect(self) -> None:
        """Disconnect from the bridge."""
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _send(self, cmd: str) -> str:
        """Send a command and read the response line."""
        if not self._socket:
            raise RuntimeError("Not connected to bridge")
        self._socket.sendall((cmd + "\n").encode("utf-8"))
        # Read response (up to newline)
        data = b""
        while b"\n" not in data:
            chunk = self._socket.recv(4096)
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8", errors="replace").strip()

    def _send_no_reply(self, cmd: str) -> None:
        """Send a command without waiting for response."""
        if not self._socket:
            raise RuntimeError("Not connected to bridge")
        self._socket.sendall((cmd + "\n").encode("utf-8"))

    # ── Bridge status ──

    def ping(self) -> bool:
        """Check if bridge is alive."""
        try:
            resp = self._send("__bridge_ping")
            return resp == "pong"
        except Exception:
            return False

    def status(self) -> dict:
        """Get bridge status as dict."""
        resp = self._send("__bridge_status")
        result = {}
        for part in resp.split():
            if "=" in part:
                k, v = part.split("=", 1)
                result[k] = v
        return result

    # ── Camera control shortcuts ──

    def toggle_camera(self) -> None:
        """Toggle debug/free camera mode."""
        self._send("__cam_toggle")

    def toggle_pause(self) -> None:
        """Toggle game pause (timestop)."""
        self._send("__cam_pause")

    def set_game_speed(self, speed: float) -> None:
        """Set game speed (1.0 = normal, 0.5 = half, 0 = pause)."""
        self._send(f"__cam_speed {speed:.4f}")

    def toggle_hud(self) -> None:
        """Toggle HUD visibility."""
        self._send("__hud_toggle")

    def hotsample(self, width: int, height: int) -> None:
        """Resize game window for high-resolution capture."""
        self._send(f"__hotsample {width} {height}")

    def set_smoothing(self, factor: float) -> None:
        """Set camera smoothing factor (1=none, 100=very smooth)."""
        self._send(f"__smooth {factor:.1f}")

    # ── Console commands (pass-through to UE5) ──

    def exec_command(self, cmd: str) -> None:
        """Execute a UE5 console command."""
        self._send_no_reply(cmd)

    # ── Camera path ──

    def add_keyframe(
        self,
        x: float, y: float, z: float,
        pitch: float = 0, yaw: float = 0, roll: float = 0,
        fov: float = 90.0,
        duration: float = 2.0,
    ) -> None:
        """Add a camera path keyframe."""
        resp = self._send(
            f"__path_add {x:.2f} {y:.2f} {z:.2f} "
            f"{pitch:.2f} {yaw:.2f} {roll:.2f} {fov:.1f} {duration:.2f}"
        )
        logger.debug(f"[PATH] add_keyframe: {resp}")

    def add_current_position(self) -> None:
        """Add the current camera position as a keyframe."""
        self._send("__path_add")

    def clear_path(self) -> None:
        """Remove all keyframes."""
        self._send("__path_clear")

    def delete_keyframe(self, index: int) -> None:
        """Delete a specific keyframe by index."""
        self._send(f"__path_delete {index}")

    def list_keyframes(self) -> str:
        """Get formatted list of all keyframes."""
        return self._send("__path_list")

    def play(self, speed: float = 1.0) -> None:
        """Start path playback."""
        self._send(f"__path_play {speed:.2f}")

    def stop(self) -> None:
        """Stop path playback."""
        self._send("__path_stop")

    def pause(self) -> None:
        """Pause/resume path playback."""
        self._send("__path_pause")

    def set_loop(self, enabled: bool) -> None:
        """Enable/disable loop playback."""
        self._send(f"__path_loop {'1' if enabled else '0'}")

    def get_path_info(self) -> dict:
        """Get path playback info."""
        resp = self._send("__path_info")
        result = {}
        for part in resp.split():
            if "=" in part:
                k, v = part.split("=", 1)
                result[k] = v
        return result

    def is_playing(self) -> bool:
        """Check if path is currently playing."""
        info = self.get_path_info()
        return info.get("playing", "0") == "1"

    def wait_for_completion(self, poll_interval: float = 0.5) -> None:
        """Block until path playback finishes."""
        while self.is_playing():
            time.sleep(poll_interval)

    def get_visualized_path(self) -> List[Tuple[float, ...]]:
        """Get interpolated path points for visualization.

        Returns list of (x, y, z, pitch, yaw, roll, fov) tuples.
        """
        resp = self._send("__path_visualize")
        points = []
        for line in resp.strip().split("\n"):
            if line.startswith("("):
                continue
            parts = line.split(",")
            if len(parts) >= 7:
                points.append(tuple(float(p) for p in parts))
        return points

    # ── Trajectory capture ──

    def capture_along_path(
        self,
        grabber,
        num_captures: int = 0,
        interval_seconds: float = 0.0,
        pause_for_capture: bool = True,
    ) -> List:
        """Play path and capture frames at regular intervals.

        Two modes:
          1. num_captures > 0: Divide path into N equal segments,
             capture at each division point.
          2. interval_seconds > 0: Capture every N seconds of
             path time.

        If pause_for_capture is True, pause the game at each
        capture point to ensure clean frames (no motion blur
        from streaming).

        Args:
            grabber: FrameGrabber instance with capture_frame() method.
            num_captures: Number of frames to capture along path.
            interval_seconds: Time interval between captures.
            pause_for_capture: Pause game during each capture.

        Returns:
            List of (rgb, depth) tuples from each capture point.
        """
        info = self.get_path_info()
        total_dur = float(info.get("total_duration", "0"))
        kf_count = int(info.get("keyframes", "0"))

        if kf_count < 2:
            logger.error("[PATH] Need at least 2 keyframes for capture")
            return []

        if num_captures > 0:
            interval_seconds = total_dur / num_captures
        elif interval_seconds <= 0:
            interval_seconds = 1.0
            num_captures = int(total_dur / interval_seconds)
        else:
            num_captures = int(total_dur / interval_seconds)

        logger.info(
            f"[PATH] Capturing {num_captures} frames along "
            f"{total_dur:.1f}s path (interval={interval_seconds:.2f}s)"
        )

        frames = []

        # Play the path at a very slow speed so we can control timing
        # Actually, better approach: step through manually
        self.play(speed=1.0)

        capture_times = [i * interval_seconds for i in range(num_captures)]

        for i, target_time in enumerate(capture_times):
            # Wait until we reach the target time
            # (path is playing in real-time in the DLL tick thread)
            if i > 0:
                wait = capture_times[i] - capture_times[i - 1]
                time.sleep(wait)

            if pause_for_capture:
                self.toggle_pause()
                time.sleep(0.3)  # let streaming settle

            logger.info(
                f"[PATH] Capturing frame {i + 1}/{num_captures} "
                f"at t={target_time:.2f}s"
            )

            try:
                rgb, depth = grabber.capture_frame()
                frames.append((rgb, depth))
            except Exception as e:
                logger.error(f"[PATH] Capture failed at t={target_time:.2f}: {e}")
                frames.append((None, None))

            if pause_for_capture:
                self.toggle_pause()

        self.stop()
        logger.info(f"[PATH] Trajectory capture complete: {len(frames)} frames")
        return frames

    # ── Context manager ──

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()
