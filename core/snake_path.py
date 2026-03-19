"""Snake path generation within a bounding volume.

Generates a serpentine (snake) pattern of waypoints that systematically
covers a 3D volume, similar to how SnakeCaptureVolume worked in UE5.
"""

import logging
from typing import List
import numpy as np

from core.waypoint import BoundingVolume, Waypoint

logger = logging.getLogger(__name__)


def generate_snake_path(
    volume: BoundingVolume,
    spacing: float = 2.0,
    axis_order: str = "xzy",
) -> List[Waypoint]:
    """Generate a snake (serpentine) path through a bounding volume.

    The path snakes back and forth along the primary axis, stepping
    along the secondary axis at each turn, and layering along the
    tertiary axis.

    Args:
        volume: The bounding box to fill with waypoints.
        spacing: Distance between waypoints in meters.
        axis_order: Which axes to traverse in order. Default "xzy" means
                    snake along X, step along Z, layer along Y.

    Returns:
        List of Waypoints covering the volume.
    """
    axis_map = {"x": 0, "y": 1, "z": 2}
    primary = axis_map[axis_order[0]]
    secondary = axis_map[axis_order[1]]
    tertiary = axis_map[axis_order[2]]

    min_c = volume.min_corner
    max_c = volume.max_corner

    def axis_range(axis_idx: int) -> np.ndarray:
        return np.arange(min_c[axis_idx], max_c[axis_idx] + spacing * 0.5, spacing)

    primary_vals = axis_range(primary)
    secondary_vals = axis_range(secondary)
    tertiary_vals = axis_range(tertiary)

    logger.debug(
        f"[SNAKE] axis_order={axis_order}, "
        f"primary({axis_order[0]})={len(primary_vals)} steps, "
        f"secondary({axis_order[1]})={len(secondary_vals)} steps, "
        f"tertiary({axis_order[2]})={len(tertiary_vals)} steps, "
        f"expected_total={len(primary_vals) * len(secondary_vals) * len(tertiary_vals)}"
    )

    waypoints: List[Waypoint] = []
    reverse_primary = False
    reverse_secondary = False

    for t_val in tertiary_vals:
        sec_iter = reversed(secondary_vals) if reverse_secondary else secondary_vals
        for s_val in sec_iter:
            pri_iter = reversed(primary_vals) if reverse_primary else primary_vals
            for p_val in pri_iter:
                pos = np.zeros(3)
                pos[primary] = p_val
                pos[secondary] = s_val
                pos[tertiary] = t_val
                waypoints.append(Waypoint(position=pos))
            reverse_primary = not reverse_primary
        reverse_secondary = not reverse_secondary

    return waypoints


def generate_grid_path(
    volume: BoundingVolume,
    counts: tuple = (5, 3, 5),
) -> List[Waypoint]:
    """Generate a regular grid of waypoints within a volume.

    Args:
        volume: Bounding box.
        counts: (nx, ny, nz) number of samples per axis.

    Returns:
        List of Waypoints on a regular grid.
    """
    nx, ny, nz = counts
    xs = np.linspace(volume.min_corner[0], volume.max_corner[0], nx)
    ys = np.linspace(volume.min_corner[1], volume.max_corner[1], ny)
    zs = np.linspace(volume.min_corner[2], volume.max_corner[2], nz)

    waypoints: List[Waypoint] = []
    for y in ys:
        for z in zs:
            for x in xs:
                waypoints.append(Waypoint(position=np.array([x, y, z])))
    return waypoints
