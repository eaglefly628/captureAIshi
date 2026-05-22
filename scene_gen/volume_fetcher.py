"""Fetch PCGBuilderVolume bounds from UE5 via bridge.

Flow:
    1. Python sends `ke * SceneFoundry_QueryVolume <name>` via bridge TCP.
    2. A Blueprint actor in the UE5 level (typically the Level Blueprint or
       a dedicated manager) implements a custom function with that exact
       name. The function finds the actor by Tag/Label, queries
       UPrimitiveComponent->Bounds (origin + box extent), writes JSON to
       VOLUME_FILE.
    3. Python polls VOLUME_FILE; on appearance/refresh, parses and returns.

UE5-side Blueprint contract (write to <cwd>/output/scene_volume.json):
    {
      "name":       "PCGBuilderVolume",
      "actor_path": "/Game/Maps/Warehouse.Warehouse:PersistentLevel.PCGBuilderVolume_1",
      "bounds_min": [x, y, z],
      "bounds_max": [x, y, z],
      "origin":     [x, y, z],
      "extent":     [hx, hy, hz],
      "ts":         <unix_seconds>
    }
"""

from __future__ import annotations

import json
import logging
import socket
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VOLUME_FILE = Path("output/scene_volume.json")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9998
DEFAULT_TIMEOUT = 5.0


class VolumeFetchError(RuntimeError):
    """Raised on bridge connect failure, command send failure, or timeout."""


def _send_query(host: str, port: int, name: str) -> None:
    """Open one-shot TCP to bridge and send ke command."""
    try:
        with socket.create_connection((host, port), timeout=3.0) as sock:
            cmd = f"ke * SceneFoundry_QueryVolume {name}\n"
            sock.sendall(cmd.encode())
            try:
                sock.settimeout(1.0)
                sock.recv(256)
            except OSError:
                pass
    except OSError as e:
        raise VolumeFetchError(f"Bridge {host}:{port} unreachable: {e}") from e


def fetch_volume(
    name: str = "PCGBuilderVolume",
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT,
    volume_file: Optional[Path] = None,
) -> dict:
    """Query UE5 for the named volume's bounds.

    Returns the parsed JSON dict, or raises VolumeFetchError on timeout /
    bridge unreachable / no listener BP in scene.
    """
    fpath = volume_file or VOLUME_FILE
    fpath.parent.mkdir(parents=True, exist_ok=True)

    prev_mtime = fpath.stat().st_mtime if fpath.exists() else 0.0

    _send_query(host, port, name)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fpath.exists() and fpath.stat().st_mtime > prev_mtime:
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                # Sanity-check required fields
                if "bounds_min" in data and "bounds_max" in data:
                    return data
                raise VolumeFetchError(
                    f"Volume file {fpath} missing bounds_min/bounds_max"
                )
            except (OSError, json.JSONDecodeError) as e:
                raise VolumeFetchError(f"Failed to parse {fpath}: {e}") from e
        time.sleep(0.1)

    raise VolumeFetchError(
        f"Timed out after {timeout:.1f}s waiting for {fpath}. "
        f"Is the SceneFoundry_QueryVolume Blueprint loaded in UE5?"
    )


def read_cached_volume(volume_file: Optional[Path] = None) -> Optional[dict]:
    """Return the last-written volume JSON, or None if not present/invalid."""
    fpath = volume_file or VOLUME_FILE
    if not fpath.exists():
        return None
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        if "bounds_min" in data and "bounds_max" in data:
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def bounds_to_area(bounds_min: list[float], bounds_max: list[float]) -> tuple[int, int, float]:
    """Convert XY bounds to (area_x, area_y, floor_z).

    area_x/y = full span in cm; floor_z = bounds_min[2].
    """
    ax = max(1, int(round(bounds_max[0] - bounds_min[0])))
    ay = max(1, int(round(bounds_max[1] - bounds_min[1])))
    fz = float(bounds_min[2])
    return ax, ay, fz


def center_xy(bounds_min: list[float], bounds_max: list[float]) -> tuple[float, float]:
    """Return XY centre of the volume in world coords."""
    return (
        (bounds_min[0] + bounds_max[0]) / 2.0,
        (bounds_min[1] + bounds_max[1]) / 2.0,
    )
