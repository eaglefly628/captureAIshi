"""Manual camera driver — prints pose and waits for user confirmation."""

import logging

from drivers.base import CameraDriver
from core.waypoint import CameraPose

logger = logging.getLogger(__name__)


class ManualDriver(CameraDriver):
    """Prints the desired pose and waits for the user to manually
    position the camera (useful for testing or games without
    automated camera control)."""

    def __init__(self, auto_confirm: bool = False):
        """
        Args:
            auto_confirm: If True, don't wait for user input (dry-run mode).
        """
        self.auto_confirm = auto_confirm
        self._pose_count = 0

    def connect(self) -> None:
        logger.info("Manual driver: ready (no connection needed)")

    def disconnect(self) -> None:
        logger.info(f"Manual driver: done. Total poses set: {self._pose_count}")

    def set_pose(self, pose: CameraPose) -> None:
        self._pose_count += 1
        pos = pose.position
        rot = pose.rotation

        print(
            f"[Pose #{self._pose_count}] "
            f"Position: ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f}) | "
            f"Rotation: (pitch={rot[0]:.1f}, yaw={rot[1]:.1f}, roll={rot[2]:.1f}) | "
            f"FOV: {pose.fov:.0f}"
        )

        if not self.auto_confirm:
            input("  Press Enter when camera is positioned...")
