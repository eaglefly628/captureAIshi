"""Camera path data model and playback engine.

Manages camera paths: create, edit, delete nodes, save/load JSON,
and interpolate poses along the path using Catmull-Rom splines + SLERP.

Storage: configs/camera_paths.json
"""

import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.tangent_smoothing import catmull_rom_segment
from core.waypoint import euler_to_quaternion

logger = logging.getLogger(__name__)

_PATHS_FILE = Path("configs/camera_paths.json")


# ── Data model ──


class PathNode:
    """A single keyframe node in a camera path."""

    __slots__ = ("position", "rotation", "fov", "duration")

    def __init__(
        self,
        position: List[float],
        rotation: List[float],
        fov: float = 90.0,
        duration: float = 2.0,
    ):
        self.position = list(position)      # [x, y, z]
        self.rotation = list(rotation)      # [pitch, yaw, roll] degrees
        self.fov = fov
        self.duration = duration            # seconds to NEXT node

    def to_dict(self) -> dict:
        return {
            "position": self.position,
            "rotation": self.rotation,
            "fov": self.fov,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PathNode":
        return cls(
            position=d["position"],
            rotation=d["rotation"],
            fov=d.get("fov", 90.0),
            duration=d.get("duration", 2.0),
        )


class CameraPath:
    """A named camera path with ordered keyframe nodes."""

    def __init__(
        self,
        path_id: str = "",
        name: str = "Untitled",
        nodes: Optional[List[PathNode]] = None,
        loop: bool = False,
    ):
        self.id = path_id or uuid.uuid4().hex[:8]
        self.name = name
        self.nodes: List[PathNode] = nodes or []
        self.loop = loop
        self.created = datetime.now(timezone.utc).isoformat()

    @property
    def total_duration(self) -> float:
        if len(self.nodes) < 2:
            return 0.0
        return sum(n.duration for n in self.nodes[:-1])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created": self.created,
            "loop": self.loop,
            "nodes": [n.to_dict() for n in self.nodes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CameraPath":
        path = cls(
            path_id=d["id"],
            name=d.get("name", "Untitled"),
            loop=d.get("loop", False),
        )
        path.created = d.get("created", path.created)
        path.nodes = [PathNode.from_dict(n) for n in d.get("nodes", [])]
        return path


# ── Storage ──


class PathStore:
    """Persistent storage for camera paths in configs/camera_paths.json."""

    def __init__(self, path: Path = _PATHS_FILE):
        self._path = path
        self._paths: Dict[str, CameraPath] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for pd in data.get("paths", []):
                cp = CameraPath.from_dict(pd)
                self._paths[cp.id] = cp
            logger.info(f"[PATH] Loaded {len(self._paths)} paths from {self._path}")
        except Exception as e:
            logger.warning(f"[PATH] Failed to load paths: {e}")

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"paths": [p.to_dict() for p in self._paths.values()]}
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def list_all(self) -> List[dict]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "node_count": len(p.nodes),
                "duration": p.total_duration,
                "loop": p.loop,
            }
            for p in self._paths.values()
        ]

    def get(self, path_id: str) -> Optional[CameraPath]:
        return self._paths.get(path_id)

    def create(self, name: str = "Untitled") -> CameraPath:
        cp = CameraPath(name=name)
        self._paths[cp.id] = cp
        self._save()
        return cp

    def update(self, path_id: str, data: dict) -> Optional[CameraPath]:
        cp = self._paths.get(path_id)
        if not cp:
            return None
        if "name" in data:
            cp.name = str(data["name"])
        if "loop" in data:
            cp.loop = bool(data["loop"])
        if "nodes" in data:
            cp.nodes = [PathNode.from_dict(n) for n in data["nodes"]]
        self._save()
        return cp

    def delete(self, path_id: str) -> bool:
        if path_id in self._paths:
            del self._paths[path_id]
            self._save()
            return True
        return False

    def add_node(self, path_id: str, node_data: dict, index: int = -1) -> Optional[CameraPath]:
        cp = self._paths.get(path_id)
        if not cp:
            return None
        node = PathNode.from_dict(node_data)
        if index < 0 or index >= len(cp.nodes):
            cp.nodes.append(node)
        else:
            cp.nodes.insert(index, node)
        self._save()
        return cp

    def update_node(self, path_id: str, node_idx: int, node_data: dict) -> Optional[CameraPath]:
        cp = self._paths.get(path_id)
        if not cp or node_idx < 0 or node_idx >= len(cp.nodes):
            return None
        node = cp.nodes[node_idx]
        if "position" in node_data:
            node.position = list(node_data["position"])
        if "rotation" in node_data:
            node.rotation = list(node_data["rotation"])
        if "fov" in node_data:
            node.fov = float(node_data["fov"])
        if "duration" in node_data:
            node.duration = float(node_data["duration"])
        self._save()
        return cp

    def delete_node(self, path_id: str, node_idx: int) -> Optional[CameraPath]:
        cp = self._paths.get(path_id)
        if not cp or node_idx < 0 or node_idx >= len(cp.nodes):
            return None
        cp.nodes.pop(node_idx)
        self._save()
        return cp


# ── Interpolation ──


def _slerp(q0: np.ndarray, q1: np.ndarray, t: float) -> np.ndarray:
    """Spherical linear interpolation between two quaternions."""
    dot = np.dot(q0, q1)
    if dot < 0:
        q1 = -q1
        dot = -dot
    dot = min(dot, 1.0)
    if dot > 0.9995:
        result = q0 + t * (q1 - q0)
        return result / np.linalg.norm(result)
    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    a = math.sin((1 - t) * theta) / sin_theta
    b = math.sin(t * theta) / sin_theta
    result = a * q0 + b * q1
    return result / np.linalg.norm(result)


def interpolate_path(
    path: CameraPath,
    samples_per_segment: int = 20,
) -> List[dict]:
    """Interpolate a camera path into dense samples.

    Returns list of dicts with position, rotation (quaternion), fov, t.
    Uses Catmull-Rom for position, SLERP for rotation, linear for FOV.
    """
    nodes = path.nodes
    if len(nodes) < 2:
        if nodes:
            n = nodes[0]
            q = euler_to_quaternion(n.rotation[0], n.rotation[1], n.rotation[2])
            return [{
                "position": n.position,
                "rotation": q.tolist(),
                "fov": n.fov,
                "t": 0.0,
            }]
        return []

    n = len(nodes)
    positions = np.array([nd.position for nd in nodes], dtype=np.float64)

    # Build extended control points for Catmull-Rom
    p_ext = np.zeros((n + 2, 3))
    p_ext[0] = 2 * positions[0] - positions[1]
    p_ext[1 : n + 1] = positions
    p_ext[n + 1] = 2 * positions[-1] - positions[-2]

    # Precompute quaternions
    quats = []
    for nd in nodes:
        q = euler_to_quaternion(nd.rotation[0], nd.rotation[1], nd.rotation[2])
        quats.append(q)

    samples = []
    total_dur = path.total_duration

    for i in range(n - 1):
        seg_points = catmull_rom_segment(
            p_ext[i], p_ext[i + 1], p_ext[i + 2], p_ext[i + 3],
            num_points=samples_per_segment,
            alpha=0.5,
        )

        seg_duration = nodes[i].duration
        seg_start_t = sum(nd.duration for nd in nodes[:i])

        for j, pos in enumerate(seg_points):
            t_local = j / max(samples_per_segment - 1, 1)
            t_global = (seg_start_t + t_local * seg_duration) / max(total_dur, 1e-6)

            q = _slerp(quats[i], quats[i + 1], t_local)
            fov = nodes[i].fov + t_local * (nodes[i + 1].fov - nodes[i].fov)

            samples.append({
                "position": pos.tolist(),
                "rotation": q.tolist(),
                "fov": round(fov, 2),
                "t": round(t_global, 4),
            })

    # Final node
    last = nodes[-1]
    q = euler_to_quaternion(last.rotation[0], last.rotation[1], last.rotation[2])
    samples.append({
        "position": last.position,
        "rotation": q.tolist(),
        "fov": last.fov,
        "t": 1.0,
    })

    return samples
