"""Cone rotation — generate multiple camera orientations at each waypoint.

At each waypoint position, generates a set of camera rotations that sweep
a cone around a base look direction. This provides multi-angle coverage
for 3D reconstruction or NeRF-style capture.
"""

import logging
from typing import List
import numpy as np

from core.waypoint import CameraPose, Waypoint

logger = logging.getLogger(__name__)


def generate_cone_poses(
    waypoint: Waypoint,
    half_angle_deg: float = 30.0,
    num_ring_samples: int = 8,
    num_rings: int = 3,
    include_center: bool = True,
    base_direction: np.ndarray = None,
) -> List[CameraPose]:
    """Generate camera poses in a cone pattern around a waypoint.

    Args:
        waypoint: The position to generate rotations at.
        half_angle_deg: Maximum cone half-angle in degrees.
        num_ring_samples: Number of samples around each ring of the cone.
        num_rings: Number of concentric rings (excluding center).
        include_center: Whether to include the center (straight) direction.
        base_direction: Base look direction. If None, uses waypoint's
                       look_direction or defaults to (0, 0, -1).

    Returns:
        List of CameraPose with the waypoint's position and varied rotations.
    """
    if base_direction is None:
        if waypoint.look_direction is not None:
            base_direction = waypoint.look_direction.copy()
        else:
            base_direction = np.array([0.0, 0.0, -1.0])

    base_direction = base_direction / np.linalg.norm(base_direction)

    # Build a local coordinate frame around base_direction
    up = np.array([0.0, 1.0, 0.0])
    if abs(np.dot(base_direction, up)) > 0.99:
        up = np.array([1.0, 0.0, 0.0])
    right = np.cross(base_direction, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, base_direction)
    up /= np.linalg.norm(up)

    expected_count = (1 if include_center else 0) + num_ring_samples * num_rings
    logger.debug(
        f"[CONE] half_angle={half_angle_deg}°, rings={num_rings}, "
        f"samples/ring={num_ring_samples}, include_center={include_center}, "
        f"expected_poses={expected_count}, base_dir={base_direction}"
    )

    poses: List[CameraPose] = []

    if include_center:
        rotation = _direction_to_euler(base_direction)
        poses.append(CameraPose(
            position=waypoint.position.copy(),
            rotation=rotation,
            fov=waypoint.fov,
        ))

    for ring_idx in range(1, num_rings + 1):
        ring_angle = half_angle_deg * (ring_idx / num_rings)
        ring_angle_rad = np.radians(ring_angle)

        for sample_idx in range(num_ring_samples):
            azimuth = 2.0 * np.pi * sample_idx / num_ring_samples

            # Tilt the base direction by ring_angle in the plane defined by azimuth
            offset = (np.cos(azimuth) * right + np.sin(azimuth) * up)
            direction = (
                base_direction * np.cos(ring_angle_rad)
                + offset * np.sin(ring_angle_rad)
            )
            direction /= np.linalg.norm(direction)

            rotation = _direction_to_euler(direction)
            poses.append(CameraPose(
                position=waypoint.position.copy(),
                rotation=rotation,
                fov=waypoint.fov,
            ))

    return poses


def _direction_to_euler(direction: np.ndarray) -> np.ndarray:
    """Convert a look direction vector to (pitch, yaw, roll) in degrees.

    Convention: Y-up, looking along -Z is (pitch=0, yaw=0).
    Pitch: rotation around X axis (up/down).
    Yaw: rotation around Y axis (left/right).
    Roll: always 0 for cone rotation.
    """
    dx, dy, dz = direction
    # Yaw: angle in XZ plane from -Z
    yaw = np.degrees(np.arctan2(-dx, -dz))
    # Pitch: angle from horizontal
    horizontal = np.sqrt(dx * dx + dz * dz)
    pitch = np.degrees(np.arctan2(dy, horizontal))
    return np.array([pitch, yaw, 0.0])
