"""Tangent smoothing via Catmull-Rom spline interpolation.

Smoothly interpolates between waypoints using Catmull-Rom splines,
producing a continuous camera path with smooth tangents.
"""

import logging
from typing import List
import numpy as np

from core.waypoint import Waypoint

logger = logging.getLogger(__name__)


def catmull_rom_segment(
    p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray,
    num_points: int, alpha: float = 0.5,
) -> np.ndarray:
    """Compute points along a Catmull-Rom spline segment between p1 and p2.

    Args:
        p0, p1, p2, p3: Control points. The segment runs from p1 to p2.
        num_points: Number of interpolated points to generate.
        alpha: Parameterization (0=uniform, 0.5=centripetal, 1=chordal).

    Returns:
        Array of shape (num_points, 3) with interpolated positions.
    """
    def tj(ti, pi, pj):
        d = np.linalg.norm(pj - pi)
        return ti + max(d ** alpha, 1e-8)

    t0 = 0.0
    t1 = tj(t0, p0, p1)
    t2 = tj(t1, p1, p2)
    t3 = tj(t2, p2, p3)

    t_vals = np.linspace(t1, t2, num_points, endpoint=False)
    points = []

    for t in t_vals:
        a1 = (t1 - t) / max(t1 - t0, 1e-8) * p0 + (t - t0) / max(t1 - t0, 1e-8) * p1
        a2 = (t2 - t) / max(t2 - t1, 1e-8) * p1 + (t - t1) / max(t2 - t1, 1e-8) * p2
        a3 = (t3 - t) / max(t3 - t2, 1e-8) * p2 + (t - t2) / max(t3 - t2, 1e-8) * p3

        b1 = (t2 - t) / max(t2 - t0, 1e-8) * a1 + (t - t0) / max(t2 - t0, 1e-8) * a2
        b2 = (t3 - t) / max(t3 - t1, 1e-8) * a2 + (t - t1) / max(t3 - t1, 1e-8) * a3

        c = (t2 - t) / max(t2 - t1, 1e-8) * b1 + (t - t1) / max(t2 - t1, 1e-8) * b2
        points.append(c)

    return np.array(points)


def smooth_waypoints(
    waypoints: List[Waypoint],
    points_per_segment: int = 10,
    alpha: float = 0.5,
) -> List[Waypoint]:
    """Smooth a list of waypoints using Catmull-Rom spline interpolation.

    Args:
        waypoints: Input waypoints to smooth.
        points_per_segment: Number of interpolated points between each
                           pair of consecutive waypoints.
        alpha: Catmull-Rom parameterization (0.5 = centripetal, recommended).

    Returns:
        Smoothed list of waypoints with interpolated positions.
    """
    if len(waypoints) < 2:
        logger.debug("[SMOOTH] Fewer than 2 waypoints — skipping smoothing")
        return list(waypoints)

    positions = np.array([w.position for w in waypoints])
    n = len(positions)
    expected_out = (n - 1) * points_per_segment + 1
    logger.debug(
        f"[SMOOTH] input={n} waypoints, points_per_segment={points_per_segment}, "
        f"alpha={alpha}, expected_output~={expected_out}"
    )

    # Extend endpoints for the spline boundary condition
    p_ext = np.zeros((n + 2, 3))
    p_ext[0] = 2 * positions[0] - positions[1]  # mirror first
    p_ext[1:n + 1] = positions
    p_ext[n + 1] = 2 * positions[-1] - positions[-2]  # mirror last

    smoothed: List[Waypoint] = []

    for i in range(n - 1):
        segment = catmull_rom_segment(
            p_ext[i], p_ext[i + 1], p_ext[i + 2], p_ext[i + 3],
            num_points=points_per_segment,
            alpha=alpha,
        )
        # Interpolate FOV linearly
        fov_start = waypoints[i].fov
        fov_end = waypoints[i + 1].fov
        for j, pos in enumerate(segment):
            t = j / max(points_per_segment - 1, 1)
            fov = fov_start + t * (fov_end - fov_start)
            smoothed.append(Waypoint(position=pos, fov=fov))

    # Add the final waypoint
    smoothed.append(Waypoint(
        position=positions[-1].copy(),
        fov=waypoints[-1].fov,
    ))

    return smoothed
