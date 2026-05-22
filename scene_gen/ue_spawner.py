"""UE5 actor spawner -- sends spawn commands via bridge TCP.

For each actor in the layout, sends a UE5 console command via the bridge
exec pass-through. Progress is reported via a callback so callers can
stream SSE events.

UE5 side requirement:
  A Blueprint Actor in the scene must handle the console command
  "SceneFoundry_Spawn <Class> <X> <Y> <Z> <Yaw> <Scale>"
  via its ReceiveExecuteConsoleCommand (override in BP or via ke command).

In editor mode, UE5 Python can also handle this. Without a receiver BP,
the commands are still sent (Exec pass-through) and logged in UE5 console.
"""

from __future__ import annotations

import json
import logging
import socket
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9998
_CONNECT_TIMEOUT = 5.0
_CMD_TIMEOUT = 3.0


class UESpawner:
    """Spawn actors in UE5 by sending console commands via bridge TCP.

    Usage:
        spawner = UESpawner()
        spawner.spawn_layout(actors, on_progress=callback)
    """

    def __init__(self, host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT):
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None

    # ── connection ─────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Try to connect to bridge. Returns True on success."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(_CONNECT_TIMEOUT)
            s.connect((self.host, self.port))
            self._sock = s
            logger.info("[SPAWNER] Connected to bridge %s:%d", self.host, self.port)
            return True
        except OSError as e:
            logger.warning("[SPAWNER] Cannot connect to bridge: %s", e)
            self._sock = None
            return False

    def disconnect(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _send(self, cmd: str) -> str:
        """Send one line and read response. Returns '' if no socket."""
        if not self._sock:
            return ""
        try:
            self._sock.settimeout(_CMD_TIMEOUT)
            self._sock.sendall((cmd + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            return buf.decode(errors="replace").strip()
        except OSError as e:
            logger.warning("[SPAWNER] Send error: %s", e)
            return ""

    # ── spawn ──────────────────────────────────────────────────────────

    def spawn_layout(
        self,
        actors: list[dict],
        on_progress: Callable[[int, int, dict], None] | None = None,
        inter_spawn_delay: float = 0.05,
    ) -> dict:
        """Spawn all actors. Calls on_progress(index, total, actor) for each.

        Args:
            actors:            List of actor dicts from layout_gen.generate_layout.
            on_progress:       Called after each spawn attempt.
            inter_spawn_delay: Seconds between spawn commands (avoid flooding).

        Returns:
            {"ok": bool, "spawned": int, "failed": int, "bridge_connected": bool}
        """
        connected = self.connect()
        spawned = 0
        failed = 0
        total = len(actors)

        for i, actor in enumerate(actors):
            cmd = _build_spawn_cmd(actor)
            if connected:
                resp = self._send(cmd)
                if resp.startswith("error"):
                    logger.warning("[SPAWNER] Actor %d/%d: %s -> %s", i + 1, total, cmd, resp)
                    failed += 1
                else:
                    spawned += 1
            else:
                # Offline / demo: log the command, count as spawned
                logger.debug("[SPAWNER] (no bridge) %s", cmd)
                spawned += 1

            if on_progress:
                on_progress(i + 1, total, actor)

            if inter_spawn_delay > 0 and i < total - 1:
                time.sleep(inter_spawn_delay)

        self.disconnect()
        return {
            "ok": failed == 0,
            "spawned": spawned,
            "failed": failed,
            "bridge_connected": connected,
        }


def _build_spawn_cmd(actor: dict) -> str:
    """Build the UE5 console command for spawning one actor.

    Format sent via bridge Exec pass-through:
        SceneFoundry_Spawn <Class> <X> <Y> <Z> <Yaw> <Scale>

    A Blueprint in the UE5 scene must implement ReceiveConsoleExec with
    this command to actually place the actor. Without a receiver the
    command is logged by UE5 and has no effect -- useful for testing.
    """
    cls = actor["class"]
    x = actor.get("x", 0.0)
    y = actor.get("y", 0.0)
    z = actor.get("z", 0.0)
    yaw = actor.get("yaw", 0.0)
    scale = actor.get("scale", 1.0)
    return f"SceneFoundry_Spawn {cls} {x:.1f} {y:.1f} {z:.1f} {yaw:.1f} {scale:.3f}"


def save_layout_json(actors: list[dict], path: Path) -> None:
    """Save layout to disk for use by external tools / UE5 Python."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"actors": actors}, indent=2, ensure_ascii=False))
    logger.info("[SPAWNER] Layout saved to %s", path)
