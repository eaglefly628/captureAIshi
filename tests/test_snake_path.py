"""Tests for snake path generation."""

import numpy as np
from core.waypoint import BoundingVolume
from core.snake_path import generate_snake_path, generate_grid_path


def test_snake_path_covers_volume():
    volume = BoundingVolume(
        min_corner=np.array([0.0, 0.0, 0.0]),
        max_corner=np.array([4.0, 2.0, 4.0]),
    )
    waypoints = generate_snake_path(volume, spacing=2.0)
    assert len(waypoints) > 0

    # All waypoints should be within the volume (with floating point tolerance)
    for wp in waypoints:
        assert np.all(wp.position >= volume.min_corner - 0.01)
        assert np.all(wp.position <= volume.max_corner + 0.01)


def test_snake_path_count():
    volume = BoundingVolume(
        min_corner=np.array([0.0, 0.0, 0.0]),
        max_corner=np.array([4.0, 4.0, 4.0]),
    )
    waypoints = generate_snake_path(volume, spacing=2.0)
    # 3 points per axis (0, 2, 4) = 27 total
    assert len(waypoints) == 27


def test_grid_path():
    volume = BoundingVolume(
        min_corner=np.array([0.0, 0.0, 0.0]),
        max_corner=np.array([10.0, 5.0, 10.0]),
    )
    waypoints = generate_grid_path(volume, counts=(3, 2, 3))
    assert len(waypoints) == 3 * 2 * 3


def test_snake_path_serpentine_pattern():
    """Verify that consecutive waypoints are close (serpentine, not random)."""
    volume = BoundingVolume(
        min_corner=np.array([0.0, 0.0, 0.0]),
        max_corner=np.array([10.0, 0.0, 10.0]),  # flat plane
    )
    waypoints = generate_snake_path(volume, spacing=2.0)

    for i in range(1, len(waypoints)):
        dist = np.linalg.norm(waypoints[i].position - waypoints[i - 1].position)
        # Adjacent waypoints should be within spacing distance (plus tolerance)
        assert dist <= 2.0 + 0.01, f"Gap at {i}: {dist:.2f}"
