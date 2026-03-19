"""Shared test fixtures for captureAIshi."""

import socket
import threading
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.waypoint import BoundingVolume, CameraPose, Waypoint


# ── Camera poses and waypoints ───────────────────────────────────────────────

@pytest.fixture
def sample_pose():
    """A simple camera pose at origin looking forward."""
    return CameraPose(
        position=np.array([1.0, 2.0, 3.0]),
        rotation=np.array([10.0, 20.0, 0.0]),
        fov=90.0,
    )


@pytest.fixture
def sample_waypoints():
    """A list of 4 waypoints for path testing."""
    return [
        Waypoint(position=np.array([0.0, 0.0, 0.0]), fov=90.0),
        Waypoint(position=np.array([2.0, 0.0, 0.0]), fov=90.0),
        Waypoint(position=np.array([4.0, 0.0, 0.0]), fov=80.0),
        Waypoint(position=np.array([6.0, 0.0, 0.0]), fov=80.0),
    ]


@pytest.fixture
def sample_volume():
    """A 10x3x10 meter bounding volume."""
    return BoundingVolume(
        min_corner=np.array([-5.0, 0.0, -5.0]),
        max_corner=np.array([5.0, 3.0, 5.0]),
    )


# ── Fake RGB/depth frames ───────────────────────────────────────────────────

@pytest.fixture
def fake_rgb():
    """A 4x4 RGB test image."""
    return np.random.randint(0, 255, (4, 4, 3), dtype=np.uint8)


@pytest.fixture
def fake_depth():
    """A 4x4 depth map."""
    return np.random.rand(4, 4).astype(np.float32)


# ── TCP echo server (for socket driver tests) ───────────────────────────────

class EchoServer:
    """A simple TCP server that records received data."""

    def __init__(self):
        self.received: List[bytes] = []
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._thread = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._server.settimeout(2.0)
        while self._running:
            try:
                conn, _ = self._server.accept()
                conn.settimeout(1.0)
                while self._running:
                    try:
                        data = conn.recv(4096)
                        if not data:
                            break
                        self.received.append(data)
                        try:
                            conn.sendall(b'{"status":"ok"}\n')
                        except (BrokenPipeError, ConnectionResetError):
                            break
                    except (socket.timeout, ConnectionResetError):
                        continue
                conn.close()
            except (socket.timeout, OSError):
                continue

    def stop(self):
        self._running = False
        self._server.close()
        if self._thread:
            self._thread.join(timeout=3)

    @property
    def received_text(self) -> str:
        return b"".join(self.received).decode("utf-8")


@pytest.fixture
def echo_server():
    """TCP echo server that records all received messages."""
    server = EchoServer()
    server.start()
    yield server
    server.stop()


# ── Temporary directories ────────────────────────────────────────────────────

@pytest.fixture
def tmp_output(tmp_path):
    """A temporary output directory."""
    out = tmp_path / "output"
    out.mkdir()
    return out
