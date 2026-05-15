"""Game hack profile loader and applier.

Reads ``configs/hacks/<id>.json`` profiles and drives the bridge TCP
interface at 127.0.0.1:9998 to install AOB intercepts.

This is the "tools engineering" layer: data-driven (profile JSON),
idempotent (``apply`` always starts by uninstalling), and per-game.

CLI usage::

    python -m drivers.game_profile list
    python -m drivers.game_profile apply batman_ak
    python -m drivers.game_profile lock
    python -m drivers.game_profile unlock
    python -m drivers.game_profile uninstall
    python -m drivers.game_profile status

Web UI / other callers import the functions directly.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BRIDGE_HOST = "127.0.0.1"
_BRIDGE_PORT = 9998
_BRIDGE_TIMEOUT = 6.0
_PROFILE_DIR = Path(__file__).resolve().parent.parent / "configs" / "hacks"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Intercept:
    name: str
    size: int
    aob_literal: str | None = None
    aob_wildcard: str | None = None
    prefer: str = "literal"          # "literal" or "wildcard"
    default_mode: str = "pass"       # "pass" or "nop"
    description: str = ""
    occurrence: int = 1              # which match to install (1 = first)


@dataclass
class Profile:
    id: str
    display_name: str
    process_names: list[str]
    engine: str
    engine_version: str = ""
    credits: str = ""
    source: str = ""
    notes: str = ""
    intercepts: list[Intercept] = field(default_factory=list)
    camera_write_profile: dict[str, Any] = field(default_factory=dict)
    capture: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Profile":
        ints = [
            Intercept(
                name=i["name"],
                size=int(i["size"]),
                aob_literal=i.get("aob_literal"),
                aob_wildcard=i.get("aob_wildcard"),
                prefer=i.get("prefer", "literal"),
                default_mode=i.get("default_mode", "pass"),
                description=i.get("description", ""),
                occurrence=max(1, int(i.get("occurrence", 1))),
            )
            for i in data.get("intercepts", [])
        ]
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            id=data["id"],
            display_name=data["display_name"],
            process_names=list(data.get("process_names", [])),
            engine=data.get("engine", ""),
            engine_version=data.get("engine_version", ""),
            credits=data.get("credits", ""),
            source=data.get("source", ""),
            notes=data.get("notes", ""),
            intercepts=ints,
            camera_write_profile=data.get("camera_write_profile", {}),
            capture=data.get("capture", {}),
        )


# ---------------------------------------------------------------------------
# Bridge TCP helper
# ---------------------------------------------------------------------------


def _send(cmd: str, timeout: float = _BRIDGE_TIMEOUT) -> str:
    """Send one newline-terminated command and return the decoded response.

    Raises ``ConnectionError`` if the bridge is not reachable. The bridge
    always sends a short response per command; we read until the peer either
    stops sending or the timeout elapses.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((_BRIDGE_HOST, _BRIDGE_PORT))
        except OSError as e:
            raise ConnectionError(f"bridge unreachable: {e}") from e
        s.sendall((cmd + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        try:
            while True:
                buf = s.recv(8192)
                if not buf:
                    break
                chunks.append(buf)
                # Most responses fit in one recv. Shadow read to avoid
                # blocking for the full timeout on short replies.
                s.settimeout(0.2)
        except TimeoutError:
            pass
    return b"".join(chunks).decode("utf-8", errors="replace").strip()


# ---------------------------------------------------------------------------
# Profile IO
# ---------------------------------------------------------------------------


def list_profiles() -> list[dict[str, Any]]:
    """Return summaries of every profile in ``configs/hacks/``."""
    out: list[dict[str, Any]] = []
    if not _PROFILE_DIR.exists():
        return out
    for path in sorted(_PROFILE_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append({
                "id": data["id"],
                "display_name": data["display_name"],
                "engine": data.get("engine", ""),
                "engine_version": data.get("engine_version", ""),
                "intercept_count": len(data.get("intercepts", [])),
                "process_names": data.get("process_names", []),
            })
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            out.append({
                "id": path.stem,
                "display_name": path.stem,
                "error": str(e),
            })
    return out


def load_profile(profile_id: str) -> Profile:
    """Load and validate a single profile by id."""
    path = _PROFILE_DIR / f"{profile_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"no such profile: {profile_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Profile.from_json(data)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _install_one(inter: Intercept) -> tuple[bool, str]:
    """Install one intercept. Tries preferred AOB, falls back to the other.

    Returns (success, last_response_line).
    """
    order: list[tuple[str, str]] = []
    if inter.prefer == "wildcard":
        if inter.aob_wildcard:
            order.append(("wildcard", inter.aob_wildcard))
        if inter.aob_literal:
            order.append(("literal", inter.aob_literal))
    else:
        if inter.aob_literal:
            order.append(("literal", inter.aob_literal))
        if inter.aob_wildcard:
            order.append(("wildcard", inter.aob_wildcard))

    last = ""
    for kind, aob in order:
        cmd = f"__cam_intercept_install_aob {inter.size} {inter.occurrence} {inter.name}_{kind} | {aob}"
        last = _send(cmd)
        if last.strip() == "ok":
            return True, f"{kind}: ok"
    return False, last or "no aob provided"


def apply_profile(profile_id: str) -> dict[str, Any]:
    """Uninstall any existing sites, then install all intercepts in profile.

    Starts in "pass" mode by default; caller invokes :func:`lock_camera`
    to switch to NOP.
    """
    prof = load_profile(profile_id)
    steps: list[dict[str, Any]] = []

    # Clean slate
    r = _send("__cam_intercept_uninstall")
    steps.append({"step": "uninstall_existing", "response": r})

    all_ok = True
    for inter in prof.intercepts:
        ok, detail = _install_one(inter)
        steps.append({
            "step": "install",
            "intercept": inter.name,
            "ok": ok,
            "detail": detail,
        })
        if not ok:
            all_ok = False

    # List current state
    r = _send("__cam_intercept_list")
    steps.append({"step": "list", "response": r})

    return {
        "profile": profile_id,
        "display_name": prof.display_name,
        "ok": all_ok,
        "installed": sum(1 for s in steps if s.get("step") == "install" and s.get("ok")),
        "expected": len(prof.intercepts),
        "steps": steps,
    }


def lock_camera() -> dict[str, Any]:
    """Switch all installed sites to NOP (block game writes)."""
    r = _send("__cam_intercept_nop")
    return {"step": "nop", "response": r}


def unlock_camera() -> dict[str, Any]:
    """Switch all installed sites to pass-through (let game drive camera)."""
    r = _send("__cam_intercept_pass")
    return {"step": "pass", "response": r}


def uninstall_all() -> dict[str, Any]:
    """Restore all patched bytes and clear site list."""
    r = _send("__cam_intercept_uninstall")
    return {"step": "uninstall", "response": r}


def capture_all() -> dict[str, Any]:
    """Switch all installed sites to CAPTURE mode.

    CAPTURE = NOP + snapshot base register. First time the hooked code
    runs, the stub saves the register value (rbx/rsi/rdi/...) into a
    slot we can read via :func:`get_captured_addr`.
    """
    r = _send("__cam_intercept_capture")
    return {"step": "capture", "response": r}


def get_captured_addr(slot: int = 0) -> int | None:
    """Return captured struct address as int, or None if nothing captured yet.

    The bridge returns ``addr=0x<hex> slot=N`` on success or ``null slot=N``
    before the game has hit the patched site.
    """
    r = _send(f"__cam_intercept_get_capture {slot}")
    r = (r or "").strip()
    if r.startswith("addr=0x"):
        hex_part = r[7:].split()[0]
        try:
            return int(hex_part, 16)
        except ValueError:
            return None
    return None


# type IDs in bridge: 0=f32, 1=f64, 2=i32, 3=u32
_TYPE_NAMES = {0: "f32", 1: "f64", 2: "i32", 3: "u32"}


def _poke_str(v_type: str, v: float | int) -> str:
    if v_type in ("f32", "f64"):
        return repr(float(v))
    return str(int(v))


def _deg_to_ue3_packed(deg: float) -> int:
    """Degrees -> UE3 FRotator int32 (0x10000 = 360 deg).

    UE3 stores pitch/yaw/roll as int32 with one full turn = 0x10000 units.
    We normalize to [-32768, 32768) so the wire value stays inside signed
    int32 and, more importantly, inside any clamp-style limits the game
    may apply (e.g. ViewPitchMin/Max). Game-side modular wrap then handles
    the small-overflow edge correctly.
    """
    packed = int(round(deg * 65536.0 / 360.0)) & 0xFFFF
    if packed >= 0x8000:
        packed -= 0x10000
    return packed


def _ue3_packed_to_deg(packed: float | int) -> float:
    """UE3 FRotator int -> degrees (accepts float from mem_peek)."""
    i = int(packed) & 0xFFFF
    if i >= 0x8000:
        i -= 0x10000
    return i * (360.0 / 65536.0)


def _euler_deg_to_matrix(
    pitch_deg: float, yaw_deg: float, roll_deg: float, convention: str = "ac6"
) -> list[list[float]]:
    """Build a 3x3 rotation matrix (rows = right/up/fwd) from euler angles.

    convention="ac6"   : M = Mz(-roll)*Mx(-pitch)*My(yaw)  [IGCS-GITC, DirectX LH row-vector]
    convention="metro" : M = Mx(-roll)*Mz(-pitch)*My(yaw)  [4A Engine cryengine-specific]
    """
    import math
    p, y, r = math.radians(pitch_deg), math.radians(yaw_deg), math.radians(roll_deg)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    cr, sr = math.cos(r), math.sin(r)
    if convention == "metro":
        # M = Mx(-r)*Mz(-p)*My(y)
        return [
            [ cp*cy,                sp,   cp*sy              ],
            [-cr*sp*cy - sr*sy,  cr*cp,  -cr*sp*sy + sr*cy   ],
            [ sr*sp*cy - cr*sy, -sr*cp,   sr*sp*sy + cr*cy   ],
        ]
    # "ac6" default: M = Mz(-r)*Mx(-p)*My(y)
    return [
        [ cy*cr + sy*sp*sr,  sr*cp,   sy*cr - cy*sp*sr],
        [-cy*sr + sy*sp*cr,  cr*cp,  -sy*sr - cy*sp*cr],
        [-sy*cp,              sp,     cy*cp             ],
    ]


def _matrix_to_euler_deg(
    m: list[list[float]], convention: str = "ac6"
) -> tuple[float, float, float]:
    """Decompose 3x3 rotation matrix (rows = right/up/fwd) to (pitch, yaw, roll) degrees.

    Inverse of _euler_deg_to_matrix for the same convention.
    """
    import math
    clamp = lambda v: max(-1.0, min(1.0, v))
    if convention == "metro":
        pitch = math.degrees(math.asin(clamp(m[0][1])))
        yaw   = math.degrees(math.atan2(m[0][2], m[0][0]))
        roll  = math.degrees(math.atan2(-m[2][1], m[1][1]))
        return pitch, yaw, roll
    # "ac6" default
    pitch = math.degrees(math.asin(clamp(m[2][1])))
    yaw   = math.degrees(math.atan2(-m[2][0], m[2][2]))
    roll  = math.degrees(math.atan2(m[0][1], m[1][1]))
    return pitch, yaw, roll


def mem_poke(addr: int, offset: int, v_type: str, value: float | int) -> str:
    """Send one typed write to the camera struct. Returns bridge response."""
    cmd = f"__cam_mem_poke {addr:X} 0x{offset:X} {v_type} {_poke_str(v_type, value)}"
    return _send(cmd)


def _coerce_type(t: str) -> str:
    """Convert schema type name to bridge poke/peek type token."""
    if t in ("float32", "f32"): return "f32"
    if t in ("double64", "f64"): return "f64"
    if t in ("int32", "i32", "ue3_packed_int"): return "i32"
    if t in ("uint32", "u32"): return "u32"
    return "f32"


def mem_peek(addr: int, offset: int, v_type: str) -> float | None:
    """Read one typed value from addr+offset. Returns float or None on error."""
    r = _send(f"__cam_mem_peek {addr:X} 0x{offset:X} {v_type}")
    r = (r or "").strip()
    if r.startswith("value="):
        try:
            return float(r[6:])
        except ValueError:
            return None
    return None


def read_camera_pose(profile_id: str, slot: int = 0) -> dict[str, Any]:
    """Read current camera pose from captured struct using profile offsets.

    Returns {"ok": bool, "x","y","z","pitch","yaw","roll","fov": float}.
    """
    prof = load_profile(profile_id)
    cam = prof.camera_write_profile
    if not cam.get("enabled"):
        return {"ok": False, "error": f"profile {profile_id} camera_write_profile disabled"}
    addr = get_captured_addr(slot)
    if not addr:
        return {"ok": False, "error": f"no capture at slot {slot}"}
    loc = cam.get("location", {})
    rot = cam.get("rotation", {})
    rot_mat = cam.get("rotation_matrix", {})
    fov_cfg = cam.get("fov", {})
    loc_t = _coerce_type(loc.get("type", "float32"))
    fov_t = _coerce_type(fov_cfg.get("type", "float32"))

    def rd(where: dict, key: str, vt: str) -> float:
        if key not in where:
            return 0.0
        v = mem_peek(addr, _parse_hex_or_dec(where[key]), vt)
        return v if v is not None else 0.0

    pitch, yaw, roll = 0.0, 0.0, 0.0
    if rot_mat:
        mat_t = _coerce_type(rot_mat.get("type", "float32"))
        convention = rot_mat.get("rotation_convention", "ac6")
        def _rd_row(row_key: str) -> list[float]:
            base = _parse_hex_or_dec(rot_mat[row_key])
            return [
                mem_peek(addr, base + i * 4, mat_t) or 0.0
                for i in range(3)
            ]
        m = [_rd_row("row0"), _rd_row("row1"), _rd_row("row2")]
        pitch, yaw, roll = _matrix_to_euler_deg(m, convention)
    else:
        rot_type_raw = rot.get("type", "float32")
        rot_t = _coerce_type(rot_type_raw)
        pitch = rd(rot, "pitch", rot_t)
        yaw   = rd(rot, "yaw",   rot_t)
        roll  = rd(rot, "roll",  rot_t)
        if rot_type_raw == "ue3_packed_int":
            pitch = _ue3_packed_to_deg(pitch)
            yaw   = _ue3_packed_to_deg(yaw)
            roll  = _ue3_packed_to_deg(roll)

    return {
        "ok": True,
        "addr": f"0x{addr:X}",
        "x":     rd(loc, "x", loc_t),
        "y":     rd(loc, "y", loc_t),
        "z":     rd(loc, "z", loc_t),
        "pitch": pitch,
        "yaw":   yaw,
        "roll":  roll,
        "fov":   rd(fov_cfg, "off", fov_t),
    }


def _parse_hex_or_dec(s: Any) -> int:
    if isinstance(s, int):
        return s
    s = str(s).strip().lower()
    if s.startswith("0x"):
        return int(s, 16)
    return int(s, 10)


def write_camera(profile_id: str,
                 x: float, y: float, z: float,
                 pitch: float, yaw: float, roll: float,
                 fov: float,
                 slot: int = 0) -> dict[str, Any]:
    """Write a pose to the captured camera struct using a profile's offsets.

    Requires :func:`capture_all` to have run AND the game to have executed
    the hooked code at least once so the base register was captured.

    Returns {"ok": bool, "addr": int, "writes": [{field, type, ok, response}]}.
    """
    prof = load_profile(profile_id)
    cam = prof.camera_write_profile
    if not cam.get("enabled"):
        return {"ok": False, "error": f"profile {profile_id} has camera_write_profile disabled"}

    addr = get_captured_addr(slot)
    if not addr:
        return {"ok": False, "error": f"no capture at slot {slot} -- run capture_all and let game tick"}

    loc = cam.get("location", {})
    rot = cam.get("rotation", {})
    rot_mat = cam.get("rotation_matrix", {})
    fov_cfg = cam.get("fov", {})

    loc_type = loc.get("type", "float32")
    fov_type = fov_cfg.get("type", "float32")

    writes: list[dict[str, Any]] = []

    def push(field: str, off_key: str, where: dict[str, Any], type_: str,
             val: float | int):
        if off_key not in where:
            return
        off = _parse_hex_or_dec(where[off_key])
        tn = _coerce_type(type_)
        resp = mem_poke(addr, off, tn, val)
        writes.append({
            "field": field,
            "offset": f"0x{off:X}",
            "type": tn,
            "value": val,
            "ok": resp.strip() == "ok",
            "response": resp,
        })

    push("x", "x", loc, loc_type, x)
    push("y", "y", loc, loc_type, y)
    push("z", "z", loc, loc_type, z)

    if rot_mat:
        mat_t = _coerce_type(rot_mat.get("type", "float32"))
        convention = rot_mat.get("rotation_convention", "ac6")
        m = _euler_deg_to_matrix(pitch, yaw, roll, convention)
        for row_idx, row_key in enumerate(("row0", "row1", "row2")):
            if row_key not in rot_mat:
                continue
            base = _parse_hex_or_dec(rot_mat[row_key])
            for col in range(3):
                off = base + col * 4
                resp = mem_poke(addr, off, mat_t, m[row_idx][col])
                writes.append({
                    "field": f"mat[{row_idx}][{col}]",
                    "offset": f"0x{off:X}",
                    "type": mat_t,
                    "value": m[row_idx][col],
                    "ok": resp.strip() == "ok",
                    "response": resp,
                })
    else:
        rot_type = rot.get("type", "float32")
        if rot_type == "ue3_packed_int":
            pitch_v = _deg_to_ue3_packed(pitch)
            yaw_v   = _deg_to_ue3_packed(yaw)
            roll_v  = _deg_to_ue3_packed(roll)
        else:
            pitch_v, yaw_v, roll_v = pitch, yaw, roll
        push("pitch", "pitch", rot, rot_type, pitch_v)
        push("yaw",   "yaw",   rot, rot_type, yaw_v)
        push("roll",  "roll",  rot, rot_type, roll_v)

    if "off" in fov_cfg:
        off = _parse_hex_or_dec(fov_cfg["off"])
        resp = mem_poke(addr, off, _coerce_type(fov_type), fov)
        writes.append({"field": "fov", "offset": f"0x{off:X}", "type": _coerce_type(fov_type),
                       "value": fov, "ok": resp.strip() == "ok", "response": resp})

    return {
        "ok": all(w["ok"] for w in writes),
        "addr": f"0x{addr:X}",
        "writes": writes,
    }


def status() -> dict[str, Any]:
    """Return bridge intercept state: site count + nop flag + full list."""
    try:
        stat = _send("__bridge_status")
    except ConnectionError as e:
        return {"ok": False, "error": str(e)}
    sites = _send("__cam_intercept_list")
    return {"ok": True, "bridge_status": stat, "sites": sites}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m drivers.game_profile "
              "<list|apply ID|lock|unlock|capture|get-capture [slot]|"
              "write ID x y z pitch yaw roll fov|uninstall|status>")
        return 2
    cmd = argv[1]
    try:
        if cmd == "list":
            for p in list_profiles():
                print(f"  {p['id']:24} {p['display_name']:32} "
                      f"engine={p.get('engine','?'):6} "
                      f"intercepts={p.get('intercept_count', 0)}")
            return 0
        if cmd == "apply":
            if len(argv) < 3:
                print("usage: python -m drivers.game_profile apply <id>")
                return 2
            result = apply_profile(argv[2])
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if cmd == "lock":
            print(json.dumps(lock_camera(), indent=2))
            return 0
        if cmd == "unlock":
            print(json.dumps(unlock_camera(), indent=2))
            return 0
        if cmd == "uninstall":
            print(json.dumps(uninstall_all(), indent=2))
            return 0
        if cmd == "capture":
            print(json.dumps(capture_all(), indent=2))
            return 0
        if cmd == "get-capture":
            slot = int(argv[2]) if len(argv) >= 3 else 0
            a = get_captured_addr(slot)
            print(f"slot={slot} addr={('0x%X' % a) if a else 'null'}")
            return 0 if a else 1
        if cmd == "write":
            if len(argv) < 10:
                print("usage: ... write <id> <x> <y> <z> <pitch> <yaw> <roll> <fov>")
                return 2
            pid = argv[2]
            xs = list(map(float, argv[3:10]))
            result = write_camera(pid, *xs)
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok") else 1
        if cmd == "status":
            print(json.dumps(status(), indent=2))
            return 0
    except ConnectionError as e:
        print(f"bridge unreachable: {e}")
        return 3
    except FileNotFoundError as e:
        print(f"profile not found: {e}")
        return 4
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv))
