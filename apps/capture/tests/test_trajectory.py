"""Tests for drivers/trajectory_presets.py and trajectory_player._PokeSession.

These tests do not touch the bridge; they exercise the preset math, the
interp helper, and the _PokeSession wire format against a local echo
server (conftest.echo_server fixture).
"""

from __future__ import annotations

import math
import socket
import threading
import time

import pytest

from drivers import trajectory_presets as tp
from drivers.trajectory_player import (
    _PokeSession, _build_plan, _coerce_type, _parse_off, _PokeField,
    _pose_value,
)
from drivers.game_profile import _deg_to_ue3_packed, _ue3_packed_to_deg


# ---------------------------------------------------------------------------
# Preset generators
# ---------------------------------------------------------------------------


class TestPresets:
    def test_orbit_produces_circle(self):
        pts = tp.orbit(center=(0, 0, 100), radius=10.0, samples=64,
                       duration=2.0, look_at_center=True)
        assert len(pts) == 64
        # Every sample should sit on the radius-10 circle (XY) at z=100.
        for p in pts:
            r = math.hypot(p.x, p.y)
            assert abs(r - 10.0) < 1e-6
            assert p.z == pytest.approx(100.0)
        # First point at (10, 0) with start_angle=0.
        assert pts[0].x == pytest.approx(10.0)
        assert pts[0].y == pytest.approx(0.0)
        # Last point is t=duration.
        assert pts[-1].t == pytest.approx(2.0)

    def test_orbit_look_at_center_faces_inward(self):
        pts = tp.orbit(center=(0, 0, 0), radius=5.0, height=0.0, samples=8,
                       look_at_center=True)
        # At (5, 0, 0) looking at (0, 0, 0) => yaw points toward -X. atan2(0, -5)
        # returns exactly pi (180 deg) with our IEEE signs, so accept ±180.
        first = pts[0]
        assert abs(first.x - 5.0) < 1e-6
        assert abs(abs(first.yaw) - 180.0) < 1e-6

    def test_orbit_direction_reverses(self):
        pts_ccw = tp.orbit(center=(0, 0, 0), radius=5.0, samples=16, direction=1,
                           look_at_center=False)
        pts_cw = tp.orbit(center=(0, 0, 0), radius=5.0, samples=16, direction=-1,
                          look_at_center=False)
        # Symmetric across XZ plane: ccw y > 0 after one step, cw y < 0.
        assert pts_ccw[1].y > 0
        assert pts_cw[1].y < 0

    def test_helix_rises(self):
        pts = tp.helix(center=(0, 0, 50), radius=10.0, height=20.0, turns=2.0,
                       samples=64)
        assert pts[0].z == pytest.approx(40.0)   # 50 - 20/2
        assert pts[-1].z == pytest.approx(60.0)  # 50 + 20/2
        # z increases monotonically
        for a, b in zip(pts, pts[1:]):
            assert b.z >= a.z - 1e-9

    def test_line_endpoints(self):
        pts = tp.line(start=(0, 0, 0), end=(10, 0, 0), samples=16, duration=2.0)
        assert pts[0].x == pytest.approx(0.0)
        assert pts[-1].x == pytest.approx(10.0)
        assert pts[-1].t == pytest.approx(2.0)

    def test_line_look_at_constant_target(self):
        pts = tp.line(start=(0, 0, 0), end=(10, 0, 0), samples=8,
                      look_at=(5, 0, 100))
        # Look-at point is directly above the midpoint. Yaw at start should
        # point toward +X (0 deg), yaw at end toward -X (180 deg).
        assert abs(pts[0].yaw - 0.0) < 1.0
        assert abs(abs(pts[-1].yaw) - 180.0) < 1.0

    def test_figure8_passes_through_center(self):
        # Use odd sample count so the midpoint lands exactly on theta=pi.
        pts = tp.figure8(center=(0, 0, 0), radius=5.0, samples=257)
        mid = pts[len(pts) // 2]
        assert abs(mid.x) < 1e-9
        assert abs(mid.y) < 1e-9

    def test_validation_rejects_bad_samples(self):
        with pytest.raises(ValueError):
            tp.orbit(center=(0, 0, 0), radius=5.0, samples=1)

    def test_validation_rejects_bad_duration(self):
        with pytest.raises(ValueError):
            tp.orbit(center=(0, 0, 0), radius=5.0, duration=0.0, samples=64)


class TestInterp:
    def test_linear_midpoint(self):
        a = tp.PosePoint(t=0.0, x=0, y=0, z=0, pitch=0, yaw=0, roll=0, fov=70)
        b = tp.PosePoint(t=2.0, x=10, y=20, z=30, pitch=5, yaw=90, roll=0, fov=80)
        p = tp.interp_linear([a, b], 1.0)
        assert p.x == pytest.approx(5)
        assert p.y == pytest.approx(10)
        assert p.z == pytest.approx(15)
        assert p.pitch == pytest.approx(2.5)
        assert p.yaw == pytest.approx(45)
        assert p.fov == pytest.approx(75)

    def test_clamps_before_start(self):
        a = tp.PosePoint(t=5.0, x=1, y=2, z=3, pitch=0, yaw=0, roll=0, fov=70)
        b = tp.PosePoint(t=10.0, x=4, y=5, z=6, pitch=0, yaw=0, roll=0, fov=70)
        p = tp.interp_linear([a, b], -1.0)
        assert p.x == 1 and p.y == 2 and p.z == 3

    def test_clamps_after_end(self):
        a = tp.PosePoint(t=0.0, x=1, y=2, z=3, pitch=0, yaw=0, roll=0, fov=70)
        b = tp.PosePoint(t=5.0, x=4, y=5, z=6, pitch=0, yaw=0, roll=0, fov=70)
        p = tp.interp_linear([a, b], 999.0)
        assert p.x == 4 and p.y == 5 and p.z == 6

    def test_yaw_shortest_path_wrap(self):
        # 350 -> 10 should go +20 via 360, not -340.
        a = tp.PosePoint(t=0.0, x=0, y=0, z=0, pitch=0, yaw=350.0, roll=0, fov=70)
        b = tp.PosePoint(t=1.0, x=0, y=0, z=0, pitch=0, yaw=10.0, roll=0, fov=70)
        mid = tp.interp_linear([a, b], 0.5)
        # Expected yaw midpoint: 350 + 10 = 360 ≡ 0 deg. Raw interp value is 360.
        assert mid.yaw == pytest.approx(360.0, abs=1e-6) or \
               mid.yaw == pytest.approx(0.0, abs=1e-6)

    def test_bisect_on_dense_points(self):
        pts = tp.orbit(center=(0, 0, 0), radius=5.0, samples=128, duration=10.0)
        # Midway t should produce a point near the "opposite side".
        mid = tp.interp_linear(pts, 5.0)
        # Half orbit from (5,0) gets to (-5, ~0).
        assert mid.x == pytest.approx(-5.0, abs=0.1)

    def test_total_duration(self):
        assert tp.total_duration([]) == 0.0
        pts = tp.orbit(center=(0, 0, 0), radius=5.0, duration=7.25, samples=8)
        assert tp.total_duration(pts) == pytest.approx(7.25)


class TestShortDelta:
    def test_zero(self):
        assert tp._short_delta(10, 10) == pytest.approx(0.0)

    def test_wrap_plus(self):
        assert tp._short_delta(350, 10) == pytest.approx(20.0)

    def test_wrap_minus(self):
        assert tp._short_delta(10, 350) == pytest.approx(-20.0)

    def test_no_wrap(self):
        assert tp._short_delta(30, 60) == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_orbit_via_dispatcher(self):
        pts = tp.generate("orbit", {
            "center": [0, 0, 0], "radius": 5.0, "samples": 8, "duration": 4.0,
            "look_at_center": False,
        })
        assert len(pts) == 8
        assert pts[-1].t == pytest.approx(4.0)

    def test_unknown_preset(self):
        with pytest.raises(KeyError):
            tp.generate("does_not_exist", {})

    def test_list_accepted_for_vec3(self):
        # JSON sends lists; generate() must coerce to tuples.
        pts = tp.generate("line", {
            "start": [0, 0, 0], "end": [10, 10, 0], "samples": 4, "duration": 1.0,
        })
        assert len(pts) == 4


# ---------------------------------------------------------------------------
# Player plan builder + type coercions
# ---------------------------------------------------------------------------


class TestPlanHelpers:
    def test_coerce_types(self):
        assert _coerce_type("float32") == "f32"
        assert _coerce_type("double64") == "f64"
        assert _coerce_type("ue3_packed_int") == "i32"
        assert _coerce_type("uint32") == "u32"
        assert _coerce_type("whatever") == "f32"  # default

    def test_parse_off_hex_and_dec(self):
        assert _parse_off("0x574") == 0x574
        assert _parse_off(1396) == 1396
        assert _parse_off("1396") == 1396


class TestUE3PackedInt:
    """UE3 FRotator uses int32 with 0x10000 = 360 deg.

    batman_ak.json rotation type = "ue3_packed_int"; the trajectory
    player / game_profile.write_camera must convert deg -> packed before
    the i32 wire poke.
    """

    def test_deg_to_packed_known_values(self):
        assert _deg_to_ue3_packed(0.0) == 0
        assert _deg_to_ue3_packed(90.0) == 16384
        # 180 lands on the signed boundary; we normalize to negative.
        assert _deg_to_ue3_packed(180.0) == -32768
        assert _deg_to_ue3_packed(-90.0) == -16384
        assert _deg_to_ue3_packed(-45.0) == -8192
        # One full turn wraps to 0.
        assert _deg_to_ue3_packed(360.0) == 0
        assert _deg_to_ue3_packed(-360.0) == 0
        # Canonical range is half-open [-32768, 32768).
        for deg in (-180.0, 179.999, -45.5, 133.7):
            p = _deg_to_ue3_packed(deg)
            assert -32768 <= p < 32768, f"{deg} -> {p} out of range"

    def test_packed_to_deg_roundtrip(self):
        # Packed int has ~0.0055 deg resolution (360/65536); roundtrip
        # within one unit is the tightest achievable.
        step = 360.0 / 65536.0
        for deg in (0.0, 1.0, 45.0, 90.0, 179.0, -1.0, -45.0, -90.0, -179.0):
            p = _deg_to_ue3_packed(deg)
            back = _ue3_packed_to_deg(p)
            # Normalize input deg to (-180, 180] for comparison.
            norm = ((deg + 180.0) % 360.0) - 180.0
            assert abs(back - norm) <= step, \
                f"{deg} -> {p} -> {back} (norm={norm}, step={step})"

    def test_packed_to_deg_accepts_float_from_peek(self):
        # mem_peek returns float; the reverse must accept float input.
        assert _ue3_packed_to_deg(16384.0) == pytest.approx(90.0, abs=1e-3)
        assert _ue3_packed_to_deg(-16384.0) == pytest.approx(-90.0, abs=1e-3)

    def test_pose_value_converts_ue3_rotation(self):
        # _pose_value must apply the ue3_packed_int conversion when
        # _PokeField.raw_type flags it; other fields stay raw.
        class _P:
            pitch = 90.0
            yaw = -45.0
            roll = 0.0
            x = 1.5
            y = 2.5
            z = 3.5
            fov = 60.0

        f_pitch = _PokeField("pitch", 0x580, "i32", "pitch", "ue3_packed_int")
        f_yaw   = _PokeField("yaw",   0x584, "i32", "yaw",   "ue3_packed_int")
        f_roll  = _PokeField("roll",  0x588, "i32", "roll",  "ue3_packed_int")
        f_x     = _PokeField("x",     0x574, "f32", "x",     "float32")

        # 90 deg -> 16384
        assert _pose_value(_P(), f_pitch) == 16384.0
        # -45 deg -> -8192
        assert _pose_value(_P(), f_yaw) == -8192.0
        assert _pose_value(_P(), f_roll) == 0.0
        # Non-UE3 field: raw pass-through.
        assert _pose_value(_P(), f_x) == 1.5


# ---------------------------------------------------------------------------
# _PokeSession against the echo_server fixture
# ---------------------------------------------------------------------------


class _OkServer:
    """Accepts one connection, replies 'ok\\n' to each newline-terminated command.

    Records every command received. Used to verify the player's wire format
    without depending on the bridge.
    """

    def __init__(self):
        self.received: list[str] = []
        self._s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._s.bind(("127.0.0.1", 0))
        self._s.listen(1)
        self.port = self._s.getsockname()[1]
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._s.settimeout(2.0)
        try:
            conn, _ = self._s.accept()
        except socket.timeout:
            return
        conn.settimeout(2.0)
        buf = b""
        try:
            while self._running:
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    nl = buf.index(b"\n")
                    line = buf[:nl].decode("utf-8", errors="replace").strip()
                    buf = buf[nl + 1:]
                    self.received.append(line)
                    try:
                        conn.sendall(b"ok\n")
                    except OSError:
                        return
        finally:
            try: conn.close()
            except OSError: pass

    def stop(self):
        self._running = False
        try: self._s.close()
        except OSError: pass


@pytest.fixture
def ok_server():
    srv = _OkServer()
    yield srv
    srv.stop()


# ---------------------------------------------------------------------------
# Flask endpoints (Commit C relies on these -- /presets and /preview are the
# read-only pair that the 3D canvas uses before any bridge is involved).
# ---------------------------------------------------------------------------


@pytest.fixture
def flask_client():
    from web_ui import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestTrajectoryFlask:
    def test_presets_list(self, flask_client):
        r = flask_client.get("/api/trajectory/presets")
        assert r.status_code == 200
        d = r.get_json()
        assert d["ok"]
        assert set(d["presets"]) == {"orbit", "helix", "line", "figure8", "custom"}
        for name in d["presets"]:
            assert name in d["schemas"]
            assert isinstance(d["schemas"][name], list)

    def test_preview_orbit(self, flask_client):
        r = flask_client.post("/api/trajectory/preview", json={
            "preset": "orbit",
            "params": {"center": [0, 0, 0], "radius": 300.0, "samples": 16,
                       "duration": 4.0, "look_at_center": True},
        })
        assert r.status_code == 200
        d = r.get_json()
        assert d["ok"]
        assert d["count"] == 16
        assert d["duration"] == pytest.approx(4.0)
        # Each point is [t,x,y,z,pitch,yaw,roll,fov]
        assert len(d["points"][0]) == 8
        assert d["points"][0][0] == pytest.approx(0.0)         # t=0
        assert d["points"][-1][0] == pytest.approx(4.0)        # t=duration
        assert d["points"][0][1] == pytest.approx(300.0)       # x=radius
        assert abs(d["points"][0][2]) < 1e-6                   # y=0

    def test_preview_unknown_preset(self, flask_client):
        r = flask_client.post("/api/trajectory/preview", json={
            "preset": "does_not_exist", "params": {},
        })
        assert r.status_code == 400
        assert r.get_json()["ok"] is False

    def test_preview_bad_params(self, flask_client):
        r = flask_client.post("/api/trajectory/preview", json={
            "preset": "orbit",
            "params": {"center": [0, 0, 0], "radius": 5.0, "samples": 1},
        })
        assert r.status_code == 400
        assert "samples" in r.get_json()["error"].lower()

    def test_preview_missing_preset(self, flask_client):
        r = flask_client.post("/api/trajectory/preview", json={"params": {}})
        assert r.status_code == 400

    def test_status_idle(self, flask_client):
        r = flask_client.get("/api/trajectory/status")
        assert r.status_code == 200
        d = r.get_json()
        assert d["ok"]
        assert d["status"]["state"] in ("idle", "playing", "paused", "error")


class TestCustomPreset:
    def test_position_only_waypoints(self):
        pts = tp.generate("custom", {
            "waypoints": [[0, 0, 0], [10, 0, 0], [20, 0, 5]],
            "duration": 4.0,
        })
        assert len(pts) == 3
        assert pts[0].t == pytest.approx(0.0)
        assert pts[-1].t == pytest.approx(4.0)
        # First waypoint should face travel direction (+X).
        assert abs(pts[0].yaw) < 1e-6

    def test_full_waypoints_with_fov(self):
        pts = tp.generate("custom", {
            "waypoints": [[0, 0, 0, 0, 0, 0, 60], [5, 0, 0, 10, 90, 0, 80]],
            "duration": 2.0,
        })
        assert len(pts) == 2
        assert pts[0].fov == pytest.approx(60.0)
        assert pts[-1].fov == pytest.approx(80.0)
        assert pts[-1].yaw == pytest.approx(90.0)

    def test_subdivision(self):
        pts = tp.generate("custom", {
            "waypoints": [[0, 0, 0], [10, 0, 0]],
            "duration": 1.0,
            "samples_per_segment": 3,
        })
        # 2 raw + 3 inserts = 5 total (N+1 after inserts for N segments).
        assert len(pts) == 5
        # Linear interp in X.
        xs = [p.x for p in pts]
        assert xs == sorted(xs)

    def test_rejects_single_waypoint(self):
        with pytest.raises(ValueError):
            tp.generate("custom", {"waypoints": [[0, 0, 0]]})

    def test_look_at_overrides_rotation(self):
        pts = tp.generate("custom", {
            "waypoints": [[0, 0, 0], [10, 0, 0]],
            "duration": 1.0,
            "look_at": [5, 0, 10],
        })
        # Both should pitch up toward the look_at target above.
        for p in pts:
            assert p.pitch > 0


# ---------------------------------------------------------------------------
# Saved trajectories (Flask /api/trajectory/saved + save + delete)
# ---------------------------------------------------------------------------


class TestSavedTrajectories:
    @pytest.fixture
    def tmp_trajectory_dir(self, monkeypatch, tmp_path):
        from pathlib import Path as _P
        from web.routes import trajectory as trajectory_bp
        d = tmp_path / "trajectories"
        monkeypatch.setattr(trajectory_bp, "_TRAJECTORY_DIR", _P(d))
        return _P(d)

    def test_list_empty(self, flask_client, tmp_trajectory_dir):
        r = flask_client.get("/api/trajectory/saved")
        assert r.status_code == 200
        d = r.get_json()
        assert d["ok"] and d["items"] == []

    def test_save_and_load_roundtrip(self, flask_client, tmp_trajectory_dir):
        r = flask_client.post("/api/trajectory/save", json={
            "name": "my_orbit",
            "preset": "orbit",
            "params": {"center": [0, 0, 0], "radius": 5.0, "samples": 8},
            "rate_hz": 30.0,
            "loop": True,
        })
        assert r.status_code == 200
        assert r.get_json()["ok"]

        r = flask_client.get("/api/trajectory/saved")
        assert r.get_json()["items"] == ["my_orbit"]

        r = flask_client.get("/api/trajectory/saved/my_orbit")
        d = r.get_json()
        assert d["ok"]
        assert d["preset"] == "orbit"
        assert d["rate_hz"] == 30.0
        assert d["loop"] is True

    def test_save_rejects_bad_preset(self, flask_client, tmp_trajectory_dir):
        r = flask_client.post("/api/trajectory/save", json={
            "name": "bad", "preset": "nope", "params": {},
        })
        assert r.status_code == 400

    def test_save_rejects_bad_params(self, flask_client, tmp_trajectory_dir):
        r = flask_client.post("/api/trajectory/save", json={
            "name": "bad", "preset": "orbit",
            "params": {"center": [0, 0, 0], "radius": 5.0, "samples": 1},
        })
        assert r.status_code == 400

    def test_save_rejects_traversal(self, flask_client, tmp_trajectory_dir):
        # "../etc/passwd" style name must be slugged; the result should
        # NOT escape the trajectory dir.
        r = flask_client.post("/api/trajectory/save", json={
            "name": "../../etc/passwd",
            "preset": "orbit",
            "params": {"center": [0, 0, 0], "radius": 5.0, "samples": 8},
        })
        d = r.get_json()
        if d.get("ok"):
            # If accepted, the path must be under the trajectory dir.
            assert str(tmp_trajectory_dir) in d["path"]
            assert "/etc/" not in d["path"]
        # Nothing written outside of the trajectory dir.
        assert not (tmp_trajectory_dir.parent / "etc").exists()

    def test_delete(self, flask_client, tmp_trajectory_dir):
        flask_client.post("/api/trajectory/save", json={
            "name": "to_delete", "preset": "orbit",
            "params": {"center": [0, 0, 0], "radius": 5.0, "samples": 8},
        })
        r = flask_client.delete("/api/trajectory/saved/to_delete")
        assert r.status_code == 200 and r.get_json()["ok"]
        r = flask_client.get("/api/trajectory/saved")
        assert "to_delete" not in r.get_json()["items"]

    def test_delete_missing(self, flask_client, tmp_trajectory_dir):
        r = flask_client.delete("/api/trajectory/saved/nonexistent")
        assert r.status_code == 404

    def test_get_missing(self, flask_client, tmp_trajectory_dir):
        r = flask_client.get("/api/trajectory/saved/nonexistent")
        assert r.status_code == 404


class TestPresetsIncludesCustom:
    def test_custom_in_list(self, flask_client):
        r = flask_client.get("/api/trajectory/presets")
        d = r.get_json()
        assert "custom" in d["presets"]
        assert "custom" in d["schemas"]


class TestPokeSession:
    def test_roundtrip_and_wire_format(self, ok_server):
        sess = _PokeSession(host="127.0.0.1", port=ok_server.port, timeout=2.0)
        sess.open()
        try:
            reply = sess.poke(addr=0x1234ABCD, offset=0x574, v_type="f32", value=12.5)
            assert reply == "ok"
            reply = sess.poke(addr=0x1234ABCD, offset=0x580, v_type="i32", value=42)
            assert reply == "ok"
        finally:
            sess.close()

        # Let the server buffer drain.
        for _ in range(20):
            if len(ok_server.received) >= 2:
                break
            time.sleep(0.05)
        assert len(ok_server.received) == 2
        assert ok_server.received[0].startswith("__cam_mem_poke 1234ABCD 0x574 f32")
        assert ok_server.received[1] == "__cam_mem_poke 1234ABCD 0x580 i32 42"

    def test_float_formatting(self, ok_server):
        sess = _PokeSession(host="127.0.0.1", port=ok_server.port)
        sess.open()
        try:
            sess.poke(addr=0x1, offset=0x0, v_type="f32", value=1.5)
        finally:
            sess.close()
        for _ in range(20):
            if ok_server.received:
                break
            time.sleep(0.05)
        assert ok_server.received[0].endswith("f32 1.5")
