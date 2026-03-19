"""Tests for coordinate system conversions."""

import numpy as np
import pytest
from utils.coords import (
    pipeline_to_ue5_position, ue5_to_pipeline_position,
    pipeline_to_ue5_rotation, ue5_to_pipeline_rotation,
    pipeline_to_unity_position, unity_to_pipeline_position,
    pipeline_to_unity_rotation, unity_to_pipeline_rotation,
    ue5_to_unity_position,
)


def test_pipeline_ue5_roundtrip():
    pos = np.array([1.0, 2.0, 3.0])
    ue5 = pipeline_to_ue5_position(pos)
    back = ue5_to_pipeline_position(ue5)
    assert np.allclose(pos, back), f"Roundtrip failed: {pos} → {ue5} → {back}"


def test_pipeline_unity_roundtrip():
    pos = np.array([1.0, 2.0, 3.0])
    unity = pipeline_to_unity_position(pos)
    back = unity_to_pipeline_position(unity)
    assert np.allclose(pos, back)


def test_ue5_units_are_centimeters():
    pos = np.array([1.0, 0.0, 0.0])  # 1 meter
    ue5 = pipeline_to_ue5_position(pos)
    # Should contain 100 somewhere (centimeter conversion)
    assert np.any(np.abs(ue5) == 100.0), f"Expected centimeters: {ue5}"


def test_unity_z_flip():
    pos = np.array([1.0, 2.0, 3.0])
    unity = pipeline_to_unity_position(pos)
    assert unity[0] == 1.0  # x stays
    assert unity[1] == 2.0  # y stays
    assert unity[2] == -3.0  # z flips


def test_origin_stays_origin():
    origin = np.array([0.0, 0.0, 0.0])
    assert np.allclose(pipeline_to_ue5_position(origin), [0, 0, 0])
    assert np.allclose(pipeline_to_unity_position(origin), [0, 0, 0])


# ── Rotation roundtrip tests ────────────────────────────────────────────────

@pytest.mark.parametrize("rot", [
    np.array([10.0, 20.0, 30.0]),
    np.array([0.0, 0.0, 0.0]),
    np.array([-45.0, 90.0, -15.0]),
    np.array([180.0, -180.0, 0.0]),
])
def test_ue5_rotation_roundtrip(rot):
    """Pipeline→UE5→Pipeline rotation should roundtrip exactly."""
    ue5 = pipeline_to_ue5_rotation(rot)
    back = ue5_to_pipeline_rotation(ue5)
    assert np.allclose(rot, back), f"Roundtrip failed: {rot} → {ue5} → {back}"


@pytest.mark.parametrize("rot", [
    np.array([10.0, 20.0, 30.0]),
    np.array([0.0, 0.0, 0.0]),
    np.array([-45.0, 90.0, -15.0]),
])
def test_unity_rotation_roundtrip(rot):
    """Pipeline→Unity→Pipeline rotation should roundtrip exactly."""
    unity = pipeline_to_unity_rotation(rot)
    back = unity_to_pipeline_rotation(unity)
    assert np.allclose(rot, back), f"Roundtrip failed: {rot} → {unity} → {back}"


def test_ue5_rotation_not_identity():
    """UE5 rotation conversion should actually remap axes (not no-op)."""
    rot = np.array([10.0, 20.0, 30.0])
    ue5 = pipeline_to_ue5_rotation(rot)
    # Should NOT be identical to input (axes are remapped)
    assert not np.allclose(rot, ue5), "Rotation conversion should not be identity"


def test_rotation_origin_stays_origin():
    """Zero rotation should stay zero in all systems."""
    zero = np.array([0.0, 0.0, 0.0])
    assert np.allclose(pipeline_to_ue5_rotation(zero), [0, 0, 0])
    assert np.allclose(pipeline_to_unity_rotation(zero), [0, 0, 0])
