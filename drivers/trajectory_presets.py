"""Parametric trajectory generators.

Each preset returns a ``list[PosePoint]`` where ``t`` is seconds from the
start of playback. The trajectory player (drivers/trajectory_player.py)
samples this list at 60 Hz, linearly interpolates between adjacent
points, and pushes the pose to the captured game camera struct via
``game_profile.write_camera``.

Coordinate convention
---------------------
All presets emit **game-space** positions (UE convention: ``Z`` is up,
``XY`` is ground). Game memory is written verbatim, so units match the
target game (UE4/UE5 use centimeters; 100 = 1 m). Pass ``center`` /
``radius`` / ``height`` in the game's native units.

Rotation is degrees: ``pitch`` down-negative, ``yaw`` around world Z
(increases counter-clockwise looking down -Z), ``roll`` around camera
forward. Presets that orbit a target auto-compute ``yaw`` / ``pitch`` to
keep the target centered.

Density
-------
Presets default to 256 samples per full trajectory. The player does
linear interpolation between samples, so 256 points over a 10 s path =
25.6 pts/s, which is already denser than any realistic camera motion.
Upstream callers may override ``samples`` for longer paths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass
class PosePoint:
    """One sampled pose along a trajectory.

    All fields are in game coordinates / degrees. ``t`` is seconds from
    the start of the trajectory; the player interpolates between
    consecutive ``PosePoint`` entries by linear blend of ``t``.
    """

    t: float
    x: float
    y: float
    z: float
    pitch: float
    yaw: float
    roll: float
    fov: float

    def as_tuple(self) -> tuple[float, float, float, float, float, float, float, float]:
        return (self.t, self.x, self.y, self.z, self.pitch, self.yaw, self.roll, self.fov)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _look_at_yaw_pitch(
    cam_x: float, cam_y: float, cam_z: float,
    tgt_x: float, tgt_y: float, tgt_z: float,
) -> tuple[float, float]:
    """Return (pitch_deg, yaw_deg) for a camera at (cam_*) looking at (tgt_*).

    UE-style: yaw 0 faces +X, increases toward +Y. Pitch is rotation
    around camera-right axis; positive pitch tilts camera up.
    """
    dx = tgt_x - cam_x
    dy = tgt_y - cam_y
    dz = tgt_z - cam_z
    ground = math.hypot(dx, dy)
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.atan2(dz, ground)) if ground > 1e-9 else (90.0 if dz > 0 else -90.0)
    return pitch, yaw


def _validate(samples: int, duration: float) -> None:
    if samples < 2:
        raise ValueError(f"samples must be >= 2 (got {samples})")
    if duration <= 0.0:
        raise ValueError(f"duration must be > 0 (got {duration})")


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


def orbit(
    center: Sequence[float],
    radius: float,
    height: float = 0.0,
    duration: float = 10.0,
    samples: int = 256,
    fov: float = 70.0,
    look_at_center: bool = True,
    start_angle_deg: float = 0.0,
    direction: int = 1,
) -> list[PosePoint]:
    """Circular orbit around ``center`` at fixed ``height`` above it.

    Parameters
    ----------
    center : (cx, cy, cz) in game coords.
    radius : orbit radius in game units.
    height : vertical offset above center.z (default 0 = at center height).
    duration : seconds for one full lap.
    samples : number of sample points.
    fov : vertical FOV in degrees (constant).
    look_at_center : auto-yaw/pitch toward (cx, cy, cz).
    start_angle_deg : yaw of orbit start (0 = +X side of center).
    direction : +1 counter-clockwise (looking -Z), -1 clockwise.
    """
    _validate(samples, duration)
    cx, cy, cz = center
    start = math.radians(start_angle_deg)
    pts: list[PosePoint] = []
    for i in range(samples):
        s = i / (samples - 1)
        theta = start + direction * s * 2.0 * math.pi
        x = cx + radius * math.cos(theta)
        y = cy + radius * math.sin(theta)
        z = cz + height
        if look_at_center:
            pitch, yaw = _look_at_yaw_pitch(x, y, z, cx, cy, cz)
        else:
            pitch, yaw = 0.0, math.degrees(theta) + 90.0 * direction
        pts.append(PosePoint(
            t=s * duration,
            x=x, y=y, z=z,
            pitch=pitch, yaw=yaw, roll=0.0,
            fov=fov,
        ))
    return pts


def helix(
    center: Sequence[float],
    radius: float,
    height: float,
    turns: float = 2.0,
    duration: float = 10.0,
    samples: int = 256,
    fov: float = 70.0,
    look_at_center: bool = True,
    direction: int = 1,
) -> list[PosePoint]:
    """Vertical helix: rises from ``center.z - height/2`` to ``center.z + height/2``
    while orbiting ``center`` at ``radius``.

    ``turns`` controls how many full laps occur over the full climb.
    ``direction`` is +1 CCW or -1 CW (looking -Z).
    """
    _validate(samples, duration)
    cx, cy, cz = center
    z0 = cz - height / 2.0
    pts: list[PosePoint] = []
    for i in range(samples):
        s = i / (samples - 1)
        theta = direction * s * turns * 2.0 * math.pi
        x = cx + radius * math.cos(theta)
        y = cy + radius * math.sin(theta)
        z = z0 + s * height
        if look_at_center:
            pitch, yaw = _look_at_yaw_pitch(x, y, z, cx, cy, cz)
        else:
            pitch, yaw = 0.0, math.degrees(theta) + 90.0 * direction
        pts.append(PosePoint(
            t=s * duration,
            x=x, y=y, z=z,
            pitch=pitch, yaw=yaw, roll=0.0,
            fov=fov,
        ))
    return pts


def line(
    start: Sequence[float],
    end: Sequence[float],
    duration: float = 5.0,
    samples: int = 64,
    fov: float = 70.0,
    look_at: Sequence[float] | None = None,
    start_rot: Sequence[float] | None = None,
    end_rot: Sequence[float] | None = None,
) -> list[PosePoint]:
    """Straight line from ``start`` to ``end``.

    Rotation control (priority order):
      1. ``look_at`` = (tx, ty, tz): camera faces this point at every sample.
      2. ``start_rot`` / ``end_rot`` = (pitch, yaw, roll): interpolated.
      3. Neither: camera faces along the travel direction.
    """
    _validate(samples, duration)
    sx, sy, sz = start
    ex, ey, ez = end
    if look_at is None and start_rot is None and end_rot is None:
        # Travel-direction facing
        dx, dy, dz = ex - sx, ey - sy, ez - sz
        ground = math.hypot(dx, dy)
        travel_yaw = math.degrees(math.atan2(dy, dx)) if ground > 1e-9 else 0.0
        travel_pitch = math.degrees(math.atan2(dz, ground)) if ground > 1e-9 else 0.0
        start_rot = (travel_pitch, travel_yaw, 0.0)
        end_rot = (travel_pitch, travel_yaw, 0.0)

    pts: list[PosePoint] = []
    for i in range(samples):
        s = i / (samples - 1)
        x = sx + s * (ex - sx)
        y = sy + s * (ey - sy)
        z = sz + s * (ez - sz)
        if look_at is not None:
            tx, ty, tz = look_at
            pitch, yaw = _look_at_yaw_pitch(x, y, z, tx, ty, tz)
            roll = 0.0
        else:
            # Linear blend of start_rot / end_rot with shortest-path yaw
            sp, sy_, sr = start_rot
            ep, ey_, er = end_rot
            pitch = sp + s * (ep - sp)
            yaw = sy_ + s * _short_delta(sy_, ey_)
            roll = sr + s * (er - sr)
        pts.append(PosePoint(
            t=s * duration,
            x=x, y=y, z=z,
            pitch=pitch, yaw=yaw, roll=roll,
            fov=fov,
        ))
    return pts


def figure8(
    center: Sequence[float],
    radius: float,
    height: float = 0.0,
    duration: float = 12.0,
    samples: int = 256,
    fov: float = 70.0,
    look_at_center: bool = True,
    axis: str = "z",
) -> list[PosePoint]:
    """Horizontal figure-8 (lemniscate-of-Gerono) through ``center``.

    One full 8 over ``duration``. ``axis`` selects the plane:
      - ``"z"``: 8 lies in XY plane at ``z = cz + height`` (bird's eye).
      - ``"y"``: 8 lies in XZ plane (vertical roller-coaster).
    """
    _validate(samples, duration)
    if axis not in ("z", "y"):
        raise ValueError(f"axis must be 'z' or 'y' (got {axis!r})")
    cx, cy, cz = center
    pts: list[PosePoint] = []
    for i in range(samples):
        s = i / (samples - 1)
        theta = s * 2.0 * math.pi
        # Lemniscate of Gerono: x = sin(t), y = sin(t)*cos(t)
        u = math.sin(theta)
        v = math.sin(theta) * math.cos(theta)
        if axis == "z":
            x = cx + radius * u
            y = cy + radius * v
            z = cz + height
        else:
            x = cx + radius * u
            y = cy
            z = cz + height + radius * v
        if look_at_center:
            pitch, yaw = _look_at_yaw_pitch(x, y, z, cx, cy, cz)
        else:
            pitch, yaw = 0.0, 0.0
        pts.append(PosePoint(
            t=s * duration,
            x=x, y=y, z=z,
            pitch=pitch, yaw=yaw, roll=0.0,
            fov=fov,
        ))
    return pts


# ---------------------------------------------------------------------------
# Registry + dispatcher (used by the Flask API)
# ---------------------------------------------------------------------------


PRESETS: dict[str, Callable[..., list[PosePoint]]] = {
    "orbit": orbit,
    "helix": helix,
    "line": line,
    "figure8": figure8,
}


# Per-preset schema for the UI to render an input form. Each entry is a
# list of (key, kind, default, help). ``kind`` drives the input control:
# "vec3" = three number boxes; "num" = one number; "int" = integer box;
# "bool" = checkbox; "choice" / "axis" = dropdown.
PRESET_SCHEMA: dict[str, list[dict]] = {
    "orbit": [
        {"key": "center", "kind": "vec3", "default": [0.0, 0.0, 0.0], "help": "Orbit center (game coords)"},
        {"key": "radius", "kind": "num", "default": 300.0, "help": "Orbit radius"},
        {"key": "height", "kind": "num", "default": 0.0, "help": "Height above center"},
        {"key": "duration", "kind": "num", "default": 10.0, "help": "Seconds per lap"},
        {"key": "samples", "kind": "int", "default": 256, "help": "Sample points"},
        {"key": "fov", "kind": "num", "default": 70.0, "help": "Vertical FOV (deg)"},
        {"key": "look_at_center", "kind": "bool", "default": True, "help": "Auto-face center"},
        {"key": "start_angle_deg", "kind": "num", "default": 0.0, "help": "Start angle (deg)"},
        {"key": "direction", "kind": "int", "default": 1, "help": "+1 CCW, -1 CW"},
    ],
    "helix": [
        {"key": "center", "kind": "vec3", "default": [0.0, 0.0, 0.0], "help": "Helix center"},
        {"key": "radius", "kind": "num", "default": 300.0, "help": "Radius"},
        {"key": "height", "kind": "num", "default": 400.0, "help": "Total vertical rise"},
        {"key": "turns", "kind": "num", "default": 2.0, "help": "Number of turns"},
        {"key": "duration", "kind": "num", "default": 10.0, "help": "Seconds total"},
        {"key": "samples", "kind": "int", "default": 256, "help": "Sample points"},
        {"key": "fov", "kind": "num", "default": 70.0, "help": "Vertical FOV (deg)"},
        {"key": "look_at_center", "kind": "bool", "default": True, "help": "Auto-face center"},
        {"key": "direction", "kind": "int", "default": 1, "help": "+1 CCW, -1 CW"},
    ],
    "line": [
        {"key": "start", "kind": "vec3", "default": [0.0, 0.0, 0.0], "help": "Start position"},
        {"key": "end", "kind": "vec3", "default": [500.0, 0.0, 0.0], "help": "End position"},
        {"key": "duration", "kind": "num", "default": 5.0, "help": "Seconds"},
        {"key": "samples", "kind": "int", "default": 64, "help": "Sample points"},
        {"key": "fov", "kind": "num", "default": 70.0, "help": "Vertical FOV (deg)"},
    ],
    "figure8": [
        {"key": "center", "kind": "vec3", "default": [0.0, 0.0, 0.0], "help": "Figure-8 center"},
        {"key": "radius", "kind": "num", "default": 300.0, "help": "Lobe radius"},
        {"key": "height", "kind": "num", "default": 0.0, "help": "Height above center"},
        {"key": "duration", "kind": "num", "default": 12.0, "help": "Seconds"},
        {"key": "samples", "kind": "int", "default": 256, "help": "Sample points"},
        {"key": "fov", "kind": "num", "default": 70.0, "help": "Vertical FOV (deg)"},
        {"key": "look_at_center", "kind": "bool", "default": True, "help": "Auto-face center"},
        {"key": "axis", "kind": "choice", "default": "z", "choices": ["z", "y"], "help": "Plane axis"},
    ],
}


def _short_delta(a: float, b: float) -> float:
    """Shortest signed angular distance from ``a`` to ``b`` in degrees."""
    d = (b - a) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


def generate(preset: str, params: dict) -> list[PosePoint]:
    """Dispatch to the named preset with a dict of parameters.

    Raises ``KeyError`` if ``preset`` is unknown, ``ValueError`` if
    ``params`` violates the preset's constraints (via the underlying
    generator's validation).
    """
    fn = PRESETS.get(preset)
    if fn is None:
        raise KeyError(f"unknown preset: {preset!r} (known: {list(PRESETS)})")
    # Shallow copy so we don't mutate the caller's dict.
    kwargs = dict(params)
    # Tuple coercion for vec3 inputs (JSON sends lists).
    for key in ("center", "start", "end", "look_at", "start_rot", "end_rot"):
        if key in kwargs and kwargs[key] is not None:
            kwargs[key] = tuple(float(v) for v in kwargs[key])
    return fn(**kwargs)


def interp_linear(points: list[PosePoint], t: float) -> PosePoint:
    """Sample ``points`` at time ``t`` (seconds) with linear interpolation.

    ``t`` is clamped to ``[points[0].t, points[-1].t]``. Rotation uses
    shortest-path yaw wrapping so orbits don't snap at the 360 -> 0 seam.

    Complexity: O(log N) via bisection.
    """
    if not points:
        raise ValueError("points is empty")
    if len(points) == 1:
        p = points[0]
        return PosePoint(t=t, x=p.x, y=p.y, z=p.z,
                         pitch=p.pitch, yaw=p.yaw, roll=p.roll, fov=p.fov)
    if t <= points[0].t:
        return points[0]
    if t >= points[-1].t:
        return points[-1]

    # Bisect on t
    lo, hi = 0, len(points) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if points[mid].t <= t:
            lo = mid
        else:
            hi = mid
    a, b = points[lo], points[hi]
    span = b.t - a.t
    u = 0.0 if span <= 0.0 else (t - a.t) / span
    return PosePoint(
        t=t,
        x=a.x + u * (b.x - a.x),
        y=a.y + u * (b.y - a.y),
        z=a.z + u * (b.z - a.z),
        pitch=a.pitch + u * (b.pitch - a.pitch),
        yaw=a.yaw + u * _short_delta(a.yaw, b.yaw),
        roll=a.roll + u * (b.roll - a.roll),
        fov=a.fov + u * (b.fov - a.fov),
    )


def total_duration(points: list[PosePoint]) -> float:
    """Return t of the last point (==total length in seconds). 0 for empty."""
    return points[-1].t if points else 0.0
