"""Waypoint data structures for camera path generation."""

from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np


@dataclass
class CameraPose:
    """A single camera pose with position, rotation, and optional FOV."""
    position: np.ndarray  # (3,) xyz in pipeline coordinates (meters, Y-up)
    rotation: np.ndarray  # (3,) pitch, yaw, roll in degrees
    fov: float = 90.0

    def to_dict(self) -> dict:
        return {
            "position": self.position.tolist(),
            "rotation": self.rotation.tolist(),
            "fov": self.fov,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CameraPose":
        return cls(
            position=np.array(d["position"], dtype=np.float64),
            rotation=np.array(d["rotation"], dtype=np.float64),
            fov=d.get("fov", 90.0),
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
