"""Waypoint data structures for camera path generation."""

from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np


def euler_to_quaternion(pitch_deg: float, yaw_deg: float, roll_deg: float) -> np.ndarray:
    """Convert (pitch, yaw, roll) in degrees to quaternion (x, y, z, w).

    Convention: intrinsic rotations, Y-up, looking along -Z.
    Rotation order: yaw (Y) -> pitch (X) -> roll (Z).
    """
    p = np.radians(pitch_deg) * 0.5
    y = np.radians(yaw_deg) * 0.5
    r = np.radians(roll_deg) * 0.5

    cp, sp = np.cos(p), np.sin(p)
    cy, sy = np.cos(y), np.sin(y)
    cr, sr = np.cos(r), np.sin(r)

    # YXZ rotation order (yaw-pitch-roll)
    w = cp * cy * cr + sp * sy * sr
    x = sp * cy * cr + cp * sy * sr
    yq = cp * sy * cr - sp * cy * sr
    z = cp * cy * sr - sp * sy * cr

    return np.array([x, yq, z, w])


@dataclass
class CameraPose:
    """A single camera pose with position, rotation, and capture metadata."""
    position: np.ndarray   # (3,) xyz in pipeline coordinates (meters, Y-up)
    rotation: np.ndarray   # (3,) pitch, yaw, roll in degrees
    fov: float = 90.0      # vertical FOV in degrees
    aspect: float = 1.7778  # width / height (default 16:9)
    view_name: str = ""     # e.g. "cone0", "cone1_ring1_s3"
    point_index: int = 0    # waypoint index in the path
    spline_mode: str = "manual"  # "manual", "catmull-rom", etc.

    def to_dict(self) -> dict:
        return {
            "position": self.position.tolist(),
            "rotation": self.rotation.tolist(),
            "fov": self.fov,
        }

    def to_trajectory_dict(
        self,
        rgb_filename: str = "",
        depth_filename: str = "",
        normal_filename: str = "",
    ) -> dict:
        """Export in the captureAIshi trajectory JSON format."""
        quat = euler_to_quaternion(
            self.rotation[0], self.rotation[1], self.rotation[2]
        )
        return {
            "Position": {
                "x": round(float(self.position[0]), 4),
                "y": round(float(self.position[1]), 4),
                "z": round(float(self.position[2]), 4),
            },
            "Rotation": {
                "x": round(float(quat[0]), 6),
                "y": round(float(quat[1]), 6),
                "z": round(float(quat[2]), 6),
                "w": round(float(quat[3]), 6),
            },
            "fov_v": round(float(self.fov), 4),
            "aspect": round(float(self.aspect), 4),
            "captureImg": rgb_filename,
            "depthImg": depth_filename,
            "normalImg": normal_filename,
            "viewName": self.view_name,
            "pointIndex": self.point_index,
            "splineMode": self.spline_mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CameraPose":
        return cls(
            position=np.array(d["position"], dtype=np.float64),
            rotation=np.array(d["rotation"], dtype=np.float64),
            fov=d.get("fov", 90.0),
            aspect=d.get("aspect", 1.7778),
            view_name=d.get("view_name", ""),
            point_index=d.get("point_index", 0),
            spline_mode=d.get("spline_mode", "manual"),
        )


@dataclass
class Waypoint:
    """A waypoint in a capture path — a position the camera visits."""
    position: np.ndarray  # (3,) xyz
    look_direction: Optional[np.ndarray] = None  # (3,) unit vector, optional
    fov: float = 90.0

    def __post_init__(self):
        self.position = np.asarray(self.position, dtype=np.float64)
        if self.look_direction is not None:
            self.look_direction = np.asarray(self.look_direction, dtype=np.float64)
            norm = np.linalg.norm(self.look_direction)
            if norm > 1e-8:
                self.look_direction = self.look_direction / norm


@dataclass
class BoundingVolume:
    """Axis-aligned bounding box defining the capture region."""
    min_corner: np.ndarray  # (3,) xyz
    max_corner: np.ndarray  # (3,) xyz

    def __post_init__(self):
        self.min_corner = np.asarray(self.min_corner, dtype=np.float64)
        self.max_corner = np.asarray(self.max_corner, dtype=np.float64)

    @property
    def center(self) -> np.ndarray:
        return (self.min_corner + self.max_corner) / 2.0

    @property
    def size(self) -> np.ndarray:
        return self.max_corner - self.min_corner

    @classmethod
    def from_center_extent(cls, center: np.ndarray, extent: np.ndarray) -> "BoundingVolume":
        center = np.asarray(center, dtype=np.float64)
        extent = np.asarray(extent, dtype=np.float64)
        return cls(min_corner=center - extent, max_corner=center + extent)
