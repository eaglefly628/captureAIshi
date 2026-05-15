"""Tests for cone rotation pose generation."""

import numpy as np
from core.waypoint import Waypoint
from core.cone_rotation import generate_cone_poses, _direction_to_euler


def test_cone_center_only():
    wp = Waypoint(position=np.array([1.0, 2.0, 3.0]))
    poses = generate_cone_poses(wp, num_rings=0, include_center=True)
    assert len(poses) == 1
    assert np.allclose(poses[0].position, [1.0, 2.0, 3.0])


def test_cone_pose_count():
    wp = Waypoint(position=np.array([0.0, 0.0, 0.0]))
    poses = generate_cone_poses(
        wp, half_angle_deg=30.0, num_ring_samples=8, num_rings=3, include_center=True
    )
    # 1 center + 3 rings * 8 samples = 25
    assert len(poses) == 25


def test_cone_without_center():
    wp = Waypoint(position=np.array([0.0, 0.0, 0.0]))
    poses = generate_cone_poses(
        wp, num_ring_samples=4, num_rings=2, include_center=False
    )
    assert len(poses) == 8


def test_direction_to_euler_forward():
    # Looking along -Z should be (pitch=0, yaw=0)
    rot = _direction_to_euler(np.array([0.0, 0.0, -1.0]))
    assert abs(rot[0]) < 1e-6  # pitch
    assert abs(rot[1]) < 1e-6  # yaw


def test_direction_to_euler_right():
    # Looking along +X → yaw should be -90 (or 270)
    rot = _direction_to_euler(np.array([1.0, 0.0, 0.0]))
    assert abs(rot[0]) < 1e-6  # pitch ~0
    assert abs(rot[1] - (-90.0)) < 1e-4  # yaw = -90


def test_all_poses_same_position():
    wp = Waypoint(position=np.array([5.0, 10.0, -3.0]))
    poses = generate_cone_poses(wp, num_rings=2, num_ring_samples=6)
    for p in poses:
        assert np.allclose(p.position, wp.position)
