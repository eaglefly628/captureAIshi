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

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
