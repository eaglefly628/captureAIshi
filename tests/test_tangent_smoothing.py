"""Tests for Catmull-Rom spline smoothing."""

import numpy as np
import pytest

from core.tangent_smoothing import catmull_rom_segment, smooth_waypoints
from core.waypoint import Waypoint


class TestCatmullRomSegment:
    """Tests for the low-level spline segment function."""

    def test_output_shape(self):
        """Segment produces the correct number of points."""
        p0 = np.array([0.0, 0.0, 0.0])
        p1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([2.0, 1.0, 0.0])
        p3 = np.array([3.0, 1.0, 0.0])
        result = catmull_rom_segment(p0, p1, p2, p3, num_points=10)
        assert result.shape == (10, 3)

    def test_starts_at_p1(self):
        """First interpolated point should be close to p1."""
        p0 = np.array([0.0, 0.0, 0.0])
        p1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([2.0, 0.0, 0.0])
        p3 = np.array([3.0, 0.0, 0.0])
        result = catmull_rom_segment(p0, p1, p2, p3, num_points=20)
        assert np.allclose(result[0], p1, atol=0.01)

    def test_collinear_points_stay_on_line(self):
        """Points along a straight line should produce a straight segment."""
        p0 = np.array([0.0, 0.0, 0.0])
        p1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([2.0, 0.0, 0.0])
        p3 = np.array([3.0, 0.0, 0.0])
        result = catmull_rom_segment(p0, p1, p2, p3, num_points=10)
        # All Y and Z should be 0
        assert np.allclose(result[:, 1], 0.0, atol=1e-6)
        assert np.allclose(result[:, 2], 0.0, atol=1e-6)
        # X should be monotonically increasing between p1.x and p2.x
        assert np.all(np.diff(result[:, 0]) > 0)

    def test_different_alpha_values(self):
        """Different alpha values should produce different curves."""
        pts = [
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
            np.array([2.0, 2.0, 0.0]),
            np.array([3.0, 2.0, 0.0]),
        ]
        uniform = catmull_rom_segment(*pts, num_points=10, alpha=0.0)
        centripetal = catmull_rom_segment(*pts, num_points=10, alpha=0.5)
        chordal = catmull_rom_segment(*pts, num_points=10, alpha=1.0)
        # They should differ (not identical)
        assert not np.allclose(uniform, centripetal, atol=1e-4)
        assert not np.allclose(centripetal, chordal, atol=1e-4)


class TestSmoothWaypoints:
    """Tests for the high-level smooth_waypoints function."""

    def test_single_waypoint_unchanged(self):
        """A single waypoint should be returned as-is."""
        wp = [Waypoint(position=np.array([1.0, 2.0, 3.0]))]
        result = smooth_waypoints(wp)
        assert len(result) == 1
        assert np.allclose(result[0].position, [1.0, 2.0, 3.0])

    def test_two_waypoints_produces_more(self, sample_waypoints):
        """Smoothing 2+ waypoints should produce more points."""
        wps = sample_waypoints[:2]
        result = smooth_waypoints(wps, points_per_segment=5)
        assert len(result) > len(wps)

    def test_smoothed_count(self, sample_waypoints):
        """Verify the expected number of smoothed points."""
        # n waypoints → (n-1) segments * points_per_segment + 1 (final point)
        n = len(sample_waypoints)
        pps = 8
        result = smooth_waypoints(sample_waypoints, points_per_segment=pps)
        expected = (n - 1) * pps + 1
        assert len(result) == expected

    def test_endpoints_preserved(self, sample_waypoints):
        """First and last positions should be (approximately) preserved."""
        result = smooth_waypoints(sample_waypoints, points_per_segment=10)
        assert np.allclose(result[0].position, sample_waypoints[0].position, atol=0.1)
        assert np.allclose(result[-1].position, sample_waypoints[-1].position, atol=1e-6)

    def test_fov_interpolation(self, sample_waypoints):
        """FOV should be linearly interpolated between waypoints."""
        result = smooth_waypoints(sample_waypoints, points_per_segment=10)
        # First point FOV should match first waypoint
        assert result[0].fov == pytest.approx(sample_waypoints[0].fov, abs=0.1)
        # Last point should match last waypoint
        assert result[-1].fov == pytest.approx(sample_waypoints[-1].fov)

    def test_continuity(self, sample_waypoints):
        """Consecutive smoothed points should be close together."""
        result = smooth_waypoints(sample_waypoints, points_per_segment=20)
        for i in range(len(result) - 1):
            dist = np.linalg.norm(result[i + 1].position - result[i].position)
            assert dist < 1.0, f"Gap between points {i} and {i+1}: {dist}"
