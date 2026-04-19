"""60 Hz trajectory player for IGCS-style intercepted games.

Takes a ``list[PosePoint]`` from ``drivers.trajectory_presets`` and
streams the interpolated pose to the captured camera struct (written
by ``camera_intercept.h`` in the bridge DLL) over the bridge TCP port.

Lifecycle
---------
    player = TrajectoryPlayer()
    player.play("batman_ak", trajectory_presets.orbit(center=(0,0,0), radius=300))
    ...
    player.pause()        # hold at current t
    player.resume()
    player.stop()         # kill thread, release socket

Threading model: one persistent worker thread per player instance.
``play()`` rejects if another trajectory is already running -- call
``stop()`` first. Socket is reused across all ticks to avoid 420
connect/close/s at 60 Hz * 7 pokes/tick.

Dependencies
------------
- ``drivers.game_profile.load_profile`` for the per-game
  ``camera_write_profile`` (offsets / types).
- ``drivers.game_profile.get_captured_addr`` to resolve the struct
  pointer (Commit A's pointer capture must have fired at least once).
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any

from . import game_profile
from .trajectory_presets import PosePoint, interp_linear, total_duration

logger = logging.getLogger(__name__)

_BRIDGE_HOST = "127.0.0.1"
_BRIDGE_PORT = 9998
_BRIDGE_TIMEOUT = 2.0


# ---------------------------------------------------------------------------
# Write-plan (pre-baked offsets / types for hot path)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PokeField:
    """One field to write per tick: offset + bridge type + pose attribute."""
    name: str
    offset: int
    v_type: str  # "f32" / "f64" / "i32" / "u32"
    attr: str    # "x" / "y" / "z" / "pitch" / "yaw" / "roll" / "fov"


def _coerce_type(t: str) -> str:
    """Profile schema type -> bridge poke type. Mirrors game_profile.write_camera."""
    if t in ("float32", "f32"):
        return "f32"
    if t in ("double64", "f64"):
        return "f64"
    if t in ("int32", "i32", "ue3_packed_int"):
        return "i32"
    if t in ("uint32", "u32"):
        return "u32"
    return "f32"


def _parse_off(s: Any) -> int:
    if isinstance(s, int):
        return s
    s = str(s).strip().lower()
    return int(s, 16) if s.startswith("0x") else int(s, 10)


def _build_plan(profile_id: str) -> list[_PokeField]:
    """Load ``profile_id`` and return the full per-tick poke plan.

    Raises ``ValueError`` if the profile disables camera writes.
    """
    prof = game_profile.load_profile(profile_id)
    cw = prof.camera_write_profile
    if not cw.get("enabled"):
        raise ValueError(
            f"profile {profile_id!r} has camera_write_profile.enabled = false"
        )

    loc = cw.get("location", {})
    rot = cw.get("rotation", {})
    fov = cw.get("fov", {})
    loc_t = _coerce_type(loc.get("type", "float32"))
    rot_t = _coerce_type(rot.get("type", "float32"))
    fov_t = _coerce_type(fov.get("type", "float32"))

    plan: list[_PokeField] = []
    for attr, key in (("x", "x"), ("y", "y"), ("z", "z")):
        if key in loc:
            plan.append(_PokeField(attr, _parse_off(loc[key]), loc_t, attr))
    for attr, key in (("pitch", "pitch"), ("yaw", "yaw"), ("roll", "roll")):
        if key in rot:
            plan.append(_PokeField(attr, _parse_off(rot[key]), rot_t, attr))
    if "off" in fov:
        plan.append(_PokeField("fov", _parse_off(fov["off"]), fov_t, "fov"))
    if not plan:
        raise ValueError(f"profile {profile_id!r} has empty camera_write_profile")
    return plan


_AUTO_CAPTURE_TIMEOUT = 2.0
_AUTO_CAPTURE_POLL = 0.05
# UX delay so the user can alt-tab to the game window before we snapshot
# or start writing. Diagnostic aid for focus-dependent camera paths.
_PRE_CAPTURE_DELAY = 5.0
_PRE_PLAY_DELAY = 5.0


def _auto_capture(slot: int) -> int:
    """Switch sites to CAPTURE, poll for addr, restore PASS. Raise on timeout.

    One-shot helper so callers don't need to orchestrate capture_all +
    game-tick + unlock_camera manually. The game must be running and
    executing the hooked code path at least once inside the timeout.
    """
    logger.info("slot %d not captured; waiting %.1fs for you to focus "
                "the game window...", slot, _PRE_CAPTURE_DELAY)
    time.sleep(_PRE_CAPTURE_DELAY)
    logger.info("triggering one-shot capture at slot %d", slot)
    game_profile.capture_all()
    try:
        deadline = time.monotonic() + _AUTO_CAPTURE_TIMEOUT
        while time.monotonic() < deadline:
            addr = game_profile.get_captured_addr(slot)
            if addr:
                return addr
            time.sleep(_AUTO_CAPTURE_POLL)
    finally:
        game_profile.unlock_camera()
    logger.warning("auto-capture timed out after %.1fs at slot %d",
                   _AUTO_CAPTURE_TIMEOUT, slot)
    raise RuntimeError(
        f"no capture at slot {slot}: auto-capture timed out after "
        f"{_AUTO_CAPTURE_TIMEOUT:.1f}s. Verify the game is running "
        "and the hooked code path is being executed."
    )


# ---------------------------------------------------------------------------
# Persistent bridge session
# ---------------------------------------------------------------------------


class _PokeSession:
    """Single persistent TCP connection used for streaming pokes.

    Not safe for concurrent use -- player threads own one session each.
    """

    def __init__(self, host: str = _BRIDGE_HOST, port: int = _BRIDGE_PORT,
                 timeout: float = _BRIDGE_TIMEOUT):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""

    def open(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self._timeout)
        s.connect((self._host, self._port))
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = s
        self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            self._buf = b""

    def _send_line(self, line: str) -> str:
        """Send a single newline-terminated command, return response line."""
        if self._sock is None:
            raise ConnectionError("session not open")
        self._sock.sendall((line + "\n").encode("utf-8"))
        # Read until newline
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("bridge closed connection")
            self._buf += chunk
        nl = self._buf.index(b"\n")
        reply = self._buf[:nl].decode("utf-8", errors="replace").strip()
        self._buf = self._buf[nl + 1:]
        return reply

    def poke(self, addr: int, offset: int, v_type: str, value: float) -> str:
        if v_type in ("f32", "f64"):
            val_s = repr(float(value))
        else:
            val_s = str(int(value))
        cmd = f"__cam_mem_poke {addr:X} 0x{offset:X} {v_type} {val_s}"
        return self._send_line(cmd)

    def __enter__(self) -> "_PokeSession":
        self.open()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------


@dataclass
class PlayerStatus:
    state: str  # "idle" / "playing" / "paused" / "error"
    profile_id: str = ""
    preset_name: str = ""
    rate_hz: float = 60.0
    t: float = 0.0
    duration: float = 0.0
    loop: bool = False
    ticks: int = 0
    writes_ok: int = 0
    writes_fail: int = 0
    # When True, the active trajectory intends to trigger a RenderDoc
    # capture per waypoint (wired in a later commit).  The flag is
    # already plumbed through play() and surfaced in status() so the UI
    # can show "RDC capture armed" while we finish the backend.
    renderdoc_capture: bool = False
    last_error: str = ""
    last_pose: dict | None = None


class TrajectoryPlayer:
    """Drives ``write_camera`` at a fixed rate from a sampled trajectory.

    One player owns one worker thread. The writer thread ticks at
    ``rate_hz`` (default 60), interpolates the pose for the current
    ``t``, and sends one poke per camera field over a persistent TCP
    session.

    Thread-safety: ``play`` / ``stop`` / ``pause`` / ``resume`` /
    ``status`` may be called from any thread. ``status`` always reflects
    a snapshot under ``_lock``.
    """

    # Abort after this many consecutive write failures.
    MAX_WRITE_FAILS = 8

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._pause_evt = threading.Event()
        self._status = PlayerStatus(state="idle")

    # -------------- public API --------------

    def play(
        self,
        profile_id: str,
        points: list[PosePoint],
        *,
        slot: int = 0,
        rate_hz: float = 60.0,
        loop: bool = False,
        preset_name: str = "",
        renderdoc_capture: bool = False,
    ) -> dict:
        """Start streaming ``points`` to the camera at ``rate_hz``.

        Returns immediately; writer runs on a background thread. Raises
        ``RuntimeError`` if a trajectory is already playing; call
        ``stop()`` first.
        """
        if rate_hz <= 0.0 or rate_hz > 500.0:
            raise ValueError(f"rate_hz out of range: {rate_hz}")
        if not points or len(points) < 2:
            raise ValueError("need at least 2 points")

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("player already running; call stop() first")
            plan = _build_plan(profile_id)
            addr = game_profile.get_captured_addr(slot)
            if not addr:
                addr = _auto_capture(slot)

            self._stop_evt.clear()
            self._pause_evt.clear()
            self._status = PlayerStatus(
                state="playing",
                profile_id=profile_id,
                preset_name=preset_name,
                rate_hz=rate_hz,
                duration=total_duration(points),
                loop=loop,
                renderdoc_capture=renderdoc_capture,
            )
            t = threading.Thread(
                target=self._run,
                args=(plan, addr, points, rate_hz, loop),
                name="trajectory-player",
                daemon=True,
            )
            self._thread = t
            t.start()

        return {
            "ok": True,
            "profile": profile_id,
            "addr": f"0x{addr:X}",
            "samples": len(points),
            "duration": total_duration(points),
            "rate_hz": rate_hz,
            "loop": loop,
        }

    def stop(self, timeout: float = 2.0) -> dict:
        """Signal the writer to exit and join. Safe to call when idle."""
        self._stop_evt.set()
        self._pause_evt.clear()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout)
        with self._lock:
            self._thread = None
            if self._status.state in ("playing", "paused"):
                self._status.state = "idle"
        return {"ok": True}

    def pause(self) -> dict:
        """Hold the writer at the current t (no more pokes until resume)."""
        with self._lock:
            if self._status.state != "playing":
                return {"ok": False, "error": f"not playing (state={self._status.state})"}
            self._status.state = "paused"
        self._pause_evt.set()
        return {"ok": True}

    def resume(self) -> dict:
        """Resume from pause. No-op if already playing."""
        with self._lock:
            if self._status.state != "paused":
                return {"ok": False, "error": f"not paused (state={self._status.state})"}
            self._status.state = "playing"
        self._pause_evt.clear()
        return {"ok": True}

    def is_playing(self) -> bool:
        with self._lock:
            return self._status.state in ("playing", "paused")

    def status(self) -> dict:
        """Return a snapshot of the current player state."""
        with self._lock:
            s = self._status
            return {
                "state": s.state,
                "profile_id": s.profile_id,
                "preset_name": s.preset_name,
                "rate_hz": s.rate_hz,
                "t": round(s.t, 4),
                "duration": round(s.duration, 4),
                "loop": s.loop,
                "ticks": s.ticks,
                "writes_ok": s.writes_ok,
                "writes_fail": s.writes_fail,
                "renderdoc_capture": s.renderdoc_capture,
                "last_error": s.last_error,
                "last_pose": s.last_pose,
            }

    # -------------- writer thread --------------

    def _run(
        self,
        plan: list[_PokeField],
        addr: int,
        points: list[PosePoint],
        rate_hz: float,
        loop: bool,
    ) -> None:
        dt = 1.0 / rate_hz
        duration = total_duration(points)
        # Accumulated paused time so ``t`` stays at the pause point.
        pause_budget = 0.0
        consecutive_fails = 0

        try:
            session = _PokeSession()
            session.open()
        except OSError as e:
            with self._lock:
                self._status.state = "error"
                self._status.last_error = f"bridge unreachable: {e}"
            logger.error("[PLAYER] could not open bridge session: %s", e)
            return

        logger.info(
            "[PLAYER] waiting %.1fs before streaming (focus the game window)...",
            _PRE_PLAY_DELAY,
        )
        # Break the sleep into small chunks so stop() can abort the wait.
        deadline = time.monotonic() + _PRE_PLAY_DELAY
        while time.monotonic() < deadline and not self._stop_evt.is_set():
            time.sleep(0.1)
        if self._stop_evt.is_set():
            session.close()
            return

        start = time.monotonic()
        logger.info(
            "[PLAYER] start profile_id=%s samples=%d rate=%.1fHz duration=%.2fs loop=%s addr=0x%X",
            self._status.profile_id, len(points), rate_hz, duration, loop, addr,
        )

        try:
            next_tick = start
            while not self._stop_evt.is_set():
                now = time.monotonic()

                # Handle pause: hold current t, bump pause_budget so t
                # doesn't advance when we resume.
                if self._pause_evt.is_set():
                    pause_wake = now
                    # Sleep in short chunks while paused, but remain responsive
                    # to stop / resume signals.
                    while self._pause_evt.is_set() and not self._stop_evt.is_set():
                        time.sleep(0.01)
                    pause_budget += time.monotonic() - pause_wake
                    next_tick = time.monotonic()
                    continue

                elapsed = now - start - pause_budget
                if elapsed >= duration:
                    if loop and duration > 0:
                        # Fold the overshoot back to [0, duration) so
                        # accumulated drift doesn't skip frames.
                        overshoot = elapsed - duration
                        whole = int(overshoot // duration) + 1
                        pause_budget -= whole * duration
                        elapsed = (now - start - pause_budget)
                    else:
                        break

                pose = interp_linear(points, elapsed)

                # Issue the per-tick pokes.
                tick_ok = 0
                tick_fail = 0
                for f in plan:
                    val = getattr(pose, f.attr)
                    try:
                        reply = session.poke(addr, f.offset, f.v_type, val)
                        if reply.strip() == "ok":
                            tick_ok += 1
                        else:
                            tick_fail += 1
                    except (OSError, ConnectionError) as e:
                        tick_fail += 1
                        consecutive_fails += 1
                        logger.warning("[PLAYER] poke %s failed: %s", f.name, e)
                        break  # socket likely dead; we'll bail below

                if tick_fail == 0:
                    consecutive_fails = 0
                else:
                    consecutive_fails += 1

                with self._lock:
                    self._status.t = elapsed
                    self._status.ticks += 1
                    self._status.writes_ok += tick_ok
                    self._status.writes_fail += tick_fail
                    self._status.last_pose = {
                        "x": round(pose.x, 4), "y": round(pose.y, 4), "z": round(pose.z, 4),
                        "pitch": round(pose.pitch, 4), "yaw": round(pose.yaw, 4),
                        "roll": round(pose.roll, 4), "fov": round(pose.fov, 4),
                    }

                if consecutive_fails >= self.MAX_WRITE_FAILS:
                    with self._lock:
                        self._status.state = "error"
                        self._status.last_error = (
                            f"aborted after {consecutive_fails} consecutive "
                            "poke failures"
                        )
                    logger.error("[PLAYER] aborting after repeated poke failures")
                    return

                # Fixed-rate scheduling: next_tick advances by dt regardless
                # of how long this tick took. If we fall behind, skip sleep.
                next_tick += dt
                sleep_for = next_tick - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    # We're behind -- catch up by resetting the schedule
                    # to "now" so drift doesn't accumulate indefinitely.
                    next_tick = time.monotonic()
        finally:
            session.close()
            with self._lock:
                if self._status.state != "error":
                    self._status.state = "idle"
            logger.info(
                "[PLAYER] stop state=%s ticks=%d ok=%d fail=%d t=%.2fs",
                self._status.state, self._status.ticks,
                self._status.writes_ok, self._status.writes_fail,
                self._status.t,
            )


# ---------------------------------------------------------------------------
# Module-level singleton -- Flask routes share one player
# ---------------------------------------------------------------------------


_default_player: TrajectoryPlayer | None = None
_default_lock = threading.Lock()


def get_default_player() -> TrajectoryPlayer:
    """Return the module-wide singleton player (lazy-init, thread-safe)."""
    global _default_player
    with _default_lock:
        if _default_player is None:
            _default_player = TrajectoryPlayer()
        return _default_player
