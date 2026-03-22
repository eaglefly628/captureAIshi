"""Abstract base class for camera control drivers."""

from abc import ABC, abstractmethod
from core.waypoint import CameraPose


class CameraDriver(ABC):
    """Interface for controlling a game camera externally."""

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the game / control mechanism."""

    @abstractmethod
    def disconnect(self) -> None:
        """Clean up and disconnect."""

    @abstractmethod
    def set_pose(self, pose: CameraPose) -> None:
        """Move the game camera to the specified pose."""

    def update_streaming(self, pose: CameraPose) -> None:
        """Update the engine streaming center to match camera position.

        Override in subclasses to send engine-specific commands that
        force the streaming system (texture/level/LOD) to load assets
        around the camera position rather than the player position.
        Default is no-op for drivers that don't support this.
        """

    def wait_for_streaming(self, timeout: float = 2.0) -> None:
        """Wait for streaming / LOD to finish loading around current position.

        Override in subclasses for engine-specific readiness checks.
        Default is a simple sleep-based wait.
        """
        import time
        time.sleep(timeout)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
