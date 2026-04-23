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


def custom(
    waypoints: Sequence[Sequence[float]],
    duration: float | None = None,
    samples_per_segment: int = 0,
    fov: float = 70.0,
    look_at: Sequence[float] | None = None,
) -> list[PosePoint]:
    """User-defined waypoint list (the 'data-driven' preset).

    Parameters
    ----------
    waypoints : list of either
        ``[x, y, z]`` (position only; rotation follows travel direction
        unless ``look_at`` is set),
        ``[x, y, z, pitch, yaw, roll]`` (explicit rotation, fov=default),
        or ``[x, y, z, pitch, yaw, roll, fov]`` (per-waypoint fov).
    duration : total seconds. If None, uses len(waypoints) * 0.5s as a
        reasonable default.
    samples_per_segment : interpolation density. ``0`` = use the raw
        waypoints; > 0 inserts that many linear samples between each
        pair (useful when feeding a smooth 60 Hz player).
    fov : fallback FOV if waypoints don't carry one.
    look_at : optional (tx, ty, tz) -- when set, every sample faces this
        point regardless of explicit rotation in waypoints.

    This is what the UI 'custom' preset uses. Save / load writes the
    ``waypoints`` list verbatim into ``configs/trajectories/<name>.json``.
    """
    if not waypoints or len(waypoints) < 2:
        raise ValueError("custom trajectory needs at least 2 waypoints")
    if duration is None:
        duration = max(0.5, len(waypoints) * 0.5)
    _validate(max(len(waypoints), 2), duration)

    def expand(wp):
        wp = list(wp)
        if len(wp) == 3:
            return wp[0], wp[1], wp[2], None, None, 0.0, fov
        if len(wp) == 6:
            return wp[0], wp[1], wp[2], wp[3], wp[4], wp[5], fov
        if len(wp) == 7:
            return wp[0], wp[1], wp[2], wp[3], wp[4], wp[5], wp[6]
        raise ValueError(f"waypoint must have 3, 6 or 7 numbers (got {len(wp)})")

    raw: list[tuple[float, ...]] = [expand(w) for w in waypoints]

    # If samples_per_segment > 0, linearly insert intermediate points
    # between consecutive waypoints. Rotation/FOV interp uses
    # shortest-path yaw.
    if samples_per_segment and samples_per_segment > 0:
        expanded: list[tuple[float, ...]] = []
        n_seg = len(raw) - 1
        for i in range(n_seg):
            a = raw[i]
            b = raw[i + 1]
            for k in range(samples_per_segment + 1):
                u = k / (samples_per_segment + 1)
                expanded.append((
                    a[0] + u * (b[0] - a[0]),
                    a[1] + u * (b[1] - a[1]),
                    a[2] + u * (b[2] - a[2]),
                    None if (a[3] is None or b[3] is None) else a[3] + u * (b[3] - a[3]),
                    None if (a[4] is None or b[4] is None) else a[4] + u * _short_delta(a[4], b[4]),
                    a[5] + u * (b[5] - a[5]),
                    a[6] + u * (b[6] - a[6]),
                ))
        expanded.append(raw[-1])
        raw = expanded

    # If some waypoints omitted rotation, fill it from travel direction
    # (or look_at target if supplied).
    pts: list[PosePoint] = []
    n = len(raw)
    for i, p in enumerate(raw):
        x, y, z, pitch, yaw, roll, pt_fov = p
        if look_at is not None:
            lp_pitch, lp_yaw = _look_at_yaw_pitch(x, y, z, *look_at)
            pitch, yaw = lp_pitch, lp_yaw
        elif pitch is None or yaw is None:
            # Aim toward the next waypoint (or back toward the prev one
            # for the last sample).
            nxt = raw[i + 1] if i + 1 < n else raw[i - 1]
            dir_sign = 1.0 if i + 1 < n else -1.0
            dx = (nxt[0] - x) * dir_sign
            dy = (nxt[1] - y) * dir_sign
            dz = (nxt[2] - z) * dir_sign
            ground = math.hypot(dx, dy)
            yaw = math.degrees(math.atan2(dy, dx)) if ground > 1e-9 else 0.0
            pitch = math.degrees(math.atan2(dz, ground)) if ground > 1e-9 else 0.0
        t = (i / (n - 1)) * duration
        pts.append(PosePoint(
            t=t, x=x, y=y, z=z,
            pitch=pitch, yaw=yaw, roll=roll,
            fov=pt_fov,
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
    "custom": custom,
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
        {"key": "speed", "kind": "num", "default": 200.0, "help": "Camera speed (units/second); duration = circumference / speed"},
        {"key": "samples", "kind": "int", "default": 8, "help": "Capture sample count (positions evenly along path)"},
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
        {"key": "speed", "kind": "num", "default": 400.0, "help": "Camera speed (units/second); duration = arc-length / speed"},
        {"key": "samples", "kind": "int", "default": 8, "help": "Capture sample count"},
        {"key": "fov", "kind": "num", "default": 70.0, "help": "Vertical FOV (deg)"},
        {"key": "look_at_center", "kind": "bool", "default": True, "help": "Auto-face center"},
        {"key": "direction", "kind": "int", "default": 1, "help": "+1 CCW, -1 CW"},
    ],
    "line": [
        {"key": "start", "kind": "vec3", "default": [0.0, 0.0, 0.0], "help": "Start position"},
        {"key": "end", "kind": "vec3", "default": [500.0, 0.0, 0.0], "help": "End position"},
        {"key": "speed", "kind": "num", "default": 100.0, "help": "Camera speed (units/second); duration = distance / speed"},
        {"key": "samples", "kind": "int", "default": 8, "help": "Capture sample count"},
        {"key": "fov", "kind": "num", "default": 70.0, "help": "Vertical FOV (deg)"},
    ],
    "figure8": [
        {"key": "center", "kind": "vec3", "default": [0.0, 0.0, 0.0], "help": "Figure-8 center"},
        {"key": "radius", "kind": "num", "default": 300.0, "help": "Lobe radius"},
        {"key": "height", "kind": "num", "default": 0.0, "help": "Height above center"},
        {"key": "speed", "kind": "num", "default": 300.0, "help": "Camera speed (units/second); duration = 4*pi*r / speed"},
        {"key": "samples", "kind": "int", "default": 8, "help": "Capture sample count"},
        {"key": "fov", "kind": "num", "default": 70.0, "help": "Vertical FOV (deg)"},
        {"key": "look_at_center", "kind": "bool", "default": True, "help": "Auto-face center"},
        {"key": "axis", "kind": "choice", "default": "z", "choices": ["z", "y"], "help": "Plane axis"},
    ],
    # 'custom' -- user supplies a waypoint list in JSON. The UI form for
    # custom doesn't fit the vec3/num/int scheme, so it renders a
    # free-form textarea (handled client-side). See docs in custom().
    "custom": [
        {"key": "waypoints", "kind": "waypoints", "default": [],
         "help": "List of [x,y,z] / [x,y,z,pitch,yaw,roll] / [x,y,z,p,y,r,fov] (game coords)"},
        {"key": "speed", "kind": "num", "default": 100.0, "help": "Camera speed (units/second); duration = polyline-length / speed"},
        {"key": "samples_per_segment", "kind": "int", "default": 0, "help": "0 = raw waypoints, >0 = linear subdivision"},
        {"key": "fov", "kind": "num", "default": 70.0, "help": "Fallback FOV"},
    ],
}


def _short_delta(a: float, b: float) -> float:
    """Shortest signed angular distance from ``a`` to ``b`` in degrees."""
    d = (b - a) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


def _path_length(preset: str, params: dict) -> float:
    """Approximate trajectory path length in game units for a given preset.

    Used by ``generate`` to turn a ``speed`` (units/second) input into a
    ``duration`` so users don't have to compute seconds-per-lap manually.
    Closed-form where possible; ``custom`` sums the polyline segments.
    Returns 0.0 if the preset's parameters don't define a length yet.
    """
    if preset == "orbit":
        r = float(params.get("radius", 300.0))
        return 2.0 * math.pi * abs(r)
    if preset == "helix":
        r = float(params.get("radius", 300.0))
        h = float(params.get("height", 400.0))
        turns = abs(float(params.get("turns", 2.0)))
        circ = turns * 2.0 * math.pi * abs(r)
        return math.hypot(circ, h)
    if preset == "line":
        s = params.get("start") or [0.0, 0.0, 0.0]
        e = params.get("end") or [500.0, 0.0, 0.0]
        return math.sqrt(sum((float(e[i]) - float(s[i])) ** 2 for i in range(3)))
    if preset == "figure8":
        # Two circles of radius r that touch at the center: 2 * 2*pi*r.
        r = float(params.get("radius", 300.0))
        return 4.0 * math.pi * abs(r)
    if preset == "custom":
        wps = params.get("waypoints") or []
        total = 0.0
        for a, b in zip(wps, wps[1:]):
            total += math.sqrt(sum((float(b[i]) - float(a[i])) ** 2 for i in range(3)))
        return total
    return 0.0


def generate(preset: str, params: dict) -> list[PosePoint]:
    """Dispatch to the named preset with a dict of parameters.

    If ``params`` contains ``speed`` (> 0, units/second) the effective
    ``duration`` is replaced with ``_path_length(preset, params) / speed``
    so the user can drive playback by speed instead of seconds. ``speed``
    is consumed here (not forwarded to the preset fn). A ``duration`` key
    still in ``params`` is honored when ``speed`` is missing or zero.

    Raises ``KeyError`` if ``preset`` is unknown, ``ValueError`` if
    ``params`` violates the preset's constraints (via the underlying
    generator's validation).
    """
    fn = PRESETS.get(preset)
    if fn is None:
        raise KeyError(f"unknown preset: {preset!r} (known: {list(PRESETS)})")
    # Shallow copy so we don't mutate the caller's dict.
    kwargs = dict(params)
    # Speed -> duration bridge. ``speed`` is a UI-level convenience that
    # the underlying preset fns don't understand, so we pop it.
    speed = kwargs.pop("speed", 0.0)
    try:
        speed_f = float(speed)
    except (TypeError, ValueError):
        speed_f = 0.0
    if speed_f > 0.0:
        length = _path_length(preset, kwargs)
        if length > 0.0:
            kwargs["duration"] = length / speed_f
    # Tuple coercion for vec3 inputs (JSON sends lists).
    for key in ("center", "start", "end", "look_at", "start_rot", "end_rot"):
        if key in kwargs and kwargs[key] is not None:
            kwargs[key] = tuple(float(v) for v in kwargs[key])
    # 'custom' takes a waypoint list of variable-arity rows -- coerce each
    # row to a tuple of floats but leave the outer list alone.
    if "waypoints" in kwargs and kwargs["waypoints"] is not None:
        kwargs["waypoints"] = [tuple(float(v) for v in row)
                               for row in kwargs["waypoints"]]
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
