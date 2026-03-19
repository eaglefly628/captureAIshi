"""Coordinate system conversions between Pipeline, UE5, and Unity.

Pipeline internal: right-hand, Y-up, meters. Looking along -Z.
UE5: left-hand, Z-up, centimeters. X=forward, Y=right, Z=up.
Unity: left-hand, Y-up, meters. X=right, Y=up, Z=forward.
"""

import numpy as np


# ── Pipeline ↔ UE5 ──────────────────────────────────────────────

def pipeline_to_ue5_position(pos: np.ndarray) -> np.ndarray:
    """Convert position from Pipeline (Y-up, meters) to UE5 (Z-up, centimeters).

    Pipeline (x, y, z) → UE5 (x_ue, y_ue, z_ue):
      x_ue = -z * 100  (pipeline -Z → UE5 +X forward)
      y_ue = x * 100   (pipeline +X → UE5 +Y right)
      z_ue = y * 100   (pipeline +Y → UE5 +Z up)
    """
    x, y, z = pos
    return np.array([-z * 100.0, x * 100.0, y * 100.0])


def ue5_to_pipeline_position(pos: np.ndarray) -> np.ndarray:
    """Convert position from UE5 (Z-up, cm) to Pipeline (Y-up, meters)."""
    x_ue, y_ue, z_ue = pos
    return np.array([y_ue / 100.0, z_ue / 100.0, -x_ue / 100.0])


def pipeline_to_ue5_rotation(rot: np.ndarray) -> np.ndarray:
    """Convert rotation (pitch, yaw, roll) from Pipeline to UE5 conventions.

    Pipeline: pitch=X-axis rotation, yaw=Y-axis rotation, roll=Z-axis.
              Right-hand, Y-up, looking along -Z.
    UE5: pitch=Y-axis (right), yaw=Z-axis (up), roll=X-axis (forward).
         Left-hand, Z-up. Values in degrees.

    Axis remapping (matching position conversion):
      Pipeline X-rot (pitch) → UE5 roll  (X-axis in UE5 = forward)
      Pipeline Y-rot (yaw)   → UE5 pitch (Y-axis in UE5 = right)
      Pipeline Z-rot (roll)  → UE5 yaw   (Z-axis in UE5 = up), sign flipped for handedness
    """
    pitch, yaw, roll = rot
    ue5_pitch = yaw
    ue5_yaw = -roll
    ue5_roll = pitch
    return np.array([ue5_pitch, ue5_yaw, ue5_roll])


def ue5_to_pipeline_rotation(rot: np.ndarray) -> np.ndarray:
    """Convert rotation from UE5 to Pipeline conventions (inverse of above)."""
    ue5_pitch, ue5_yaw, ue5_roll = rot
    pitch = ue5_roll
    yaw = ue5_pitch
    roll = -ue5_yaw
    return np.array([pitch, yaw, roll])


# ── Pipeline ↔ Unity ─────────────────────────────────────────────

def pipeline_to_unity_position(pos: np.ndarray) -> np.ndarray:
    """Convert position from Pipeline (right-hand Y-up) to Unity (left-hand Y-up).

    Pipeline (x, y, z) → Unity (x_u, y_u, z_u):
      x_u = x     (same right axis)
      y_u = y     (same up axis)
      z_u = -z    (flip Z for handedness)
    """
    x, y, z = pos
    return np.array([x, y, -z])


def unity_to_pipeline_position(pos: np.ndarray) -> np.ndarray:
    """Convert position from Unity (left-hand Y-up) to Pipeline."""
    x, y, z = pos
    return np.array([x, y, -z])


def pipeline_to_unity_rotation(rot: np.ndarray) -> np.ndarray:
    """Convert rotation from Pipeline to Unity conventions.

    Unity uses left-hand rule, so yaw and roll signs flip.
    """
    pitch, yaw, roll = rot
    return np.array([-pitch, -yaw, roll])


def unity_to_pipeline_rotation(rot: np.ndarray) -> np.ndarray:
    """Convert rotation from Unity to Pipeline conventions."""
    pitch, yaw, roll = rot
    return np.array([-pitch, -yaw, roll])


# ── UE5 ↔ Unity (convenience) ───────────────────────────────────

def ue5_to_unity_position(pos: np.ndarray) -> np.ndarray:
    """Convert position from UE5 to Unity."""
    return pipeline_to_unity_position(ue5_to_pipeline_position(pos))


def unity_to_ue5_position(pos: np.ndarray) -> np.ndarray:
    """Convert position from Unity to UE5."""
    return pipeline_to_ue5_position(unity_to_pipeline_position(pos))
