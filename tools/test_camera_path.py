"""Camera path test tool.

Connects to the captureAIshi bridge DLL (127.0.0.1:9998), reads the
current camera position, builds a smooth demo path, and plays it.

Usage:
    python tools/test_camera_path.py                   # orbit demo
    python tools/test_camera_path.py --arc             # forward arc demo
    python tools/test_camera_path.py --read            # just print current camera pos
    python tools/test_camera_path.py --host 192.168.1.2 --port 9998
    python tools/test_camera_path.py --no-slomo        # skip timestop (debug cam active)

By default the script issues 'slomo 0.0001' before playback and 'slomo 1.0'
after.  This is necessary because APlayerCameraManager::UpdateCamera() runs
every game frame and writes the player-follow position back to the same POV
address our 60 Hz tick writes to -- without timestop the game wins the race
and the camera never visibly moves.

Use --no-slomo only when the debug camera (ToggleDebugCamera) is already
active, because the debug PCM has no game-side position lock.

The path is built in UE5 space (Z-up, centimeters).
"""

import argparse
import logging
import math
import socket
import sys
import time
from pathlib import Path

# Add project root to sys.path so we can import the driver
sys.path.insert(0, str(Path(__file__).parent.parent))

from drivers.ue5_console import UE5ConsoleDriver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_orbit_path(cx: float, cy: float, cz: float,
                     yaw_base: float, fov: float,
                     radius: float = 300.0,
                     segments: int = 8,
                     seg_duration: float = 2.0) -> list:
    """Build a horizontal orbit path centered on (cx, cy, cz).

    Each keyframe positions the camera on a circle of given radius,
    facing the center (yaw = angle + 180 so camera looks inward).

    Returns list of (x, y, z, pitch, yaw, roll, fov, duration) tuples.
    """
    keyframes = []
    for i in range(segments + 1):  # +1 to close the loop
        angle_deg = (360.0 / segments) * i
        angle_rad = math.radians(angle_deg)
        kx = cx + radius * math.cos(angle_rad)
        ky = cy + radius * math.sin(angle_rad)
        kz = cz
        # Camera yaw: look toward center.
        # In UE5 yaw convention: 0 = +X, 90 = +Y
        # Look toward center means yaw = atan2(cy - ky, cx - kx) in degrees
        look_yaw = math.degrees(math.atan2(cy - ky, cx - kx))
        keyframes.append((kx, ky, kz, 0.0, look_yaw, 0.0, fov, seg_duration))
    return keyframes


def build_arc_path(cx: float, cy: float, cz: float,
                   yaw_base: float, fov: float,
                   forward_dist: float = 400.0,
                   height_rise: float = 150.0,
                   seg_duration: float = 3.0) -> list:
    """Build a simple forward arc: move forward, rise, look down slightly.

    Demonstrates smooth camera movement in a straight line with altitude gain.
    Returns list of (x, y, z, pitch, yaw, roll, fov, duration) tuples.
    """
    rad = math.radians(yaw_base)
    # 5 keyframes: start, 25%, 50%, 75%, end
    keyframes = []
    for i in range(6):
        t = i / 5.0
        dist = forward_dist * t
        rise = height_rise * math.sin(math.pi * t)  # rises then falls back
        kx = cx + dist * math.cos(rad)
        ky = cy + dist * math.sin(rad)
        kz = cz + rise
        pitch = -10.0 * math.sin(math.pi * t)  # slight nose-down at peak
        keyframes.append((kx, ky, kz, pitch, yaw_base, 0.0, fov, seg_duration))
    return keyframes


def play_path(driver: UE5ConsoleDriver, keyframes: list, loop: bool = False,
              slomo: bool = True) -> None:
    """Upload keyframes and start playback.

    slomo: issue 'slomo 0.0001' before playback so the bridge's 60 Hz
    memory writes dominate over the game's per-frame UpdateCamera().
    Without this, the game's camera lock (player-follow) overwrites our
    position writes every frame and the camera never visibly moves.
    Speed is restored to 1.0 when the path finishes or is interrupted.
    """
    logger.info(f"Uploading {len(keyframes)} keyframes...")
    driver.path_clear()
    for i, kf in enumerate(keyframes):
        x, y, z, pitch, yaw, roll, fov, dur = kf
        ok = driver.path_add(x, y, z, pitch, yaw, roll, fov, dur)
        logger.info(
            f"  [{i:02d}] ({x:.0f},{y:.0f},{z:.0f}) "
            f"p={pitch:.1f} y={yaw:.1f} fov={fov:.0f} dur={dur:.1f}s  -> {'ok' if ok else 'FAILED'}"
        )
    info = driver.path_info()
    logger.info(
        f"Path ready: {info['keyframes']} keyframes, "
        f"total={info['total_duration']:.1f}s"
    )

    if slomo:
        # APlayerCameraManager::UpdateCamera() runs every game frame and
        # writes the player-follow position to the same POV address.
        # At 0.0001x speed the game runs ~1 tick per 167s wall-clock time,
        # so our 60 Hz tick wins cleanly on every rendered frame.
        logger.info("Slowing game (slomo 0.0001) so camera writes win...")
        driver.send_command("slomo 0.0001")
        time.sleep(0.3)  # let at least one slomo tick process

    logger.info("Starting playback...")
    driver.path_play(speed=1.0)
    logger.info("Path is playing. Press Ctrl+C to stop early.")

    # Wait for path to finish (poll wall-clock time against total_duration)
    total = info["total_duration"]
    start = time.time()
    try:
        while True:
            elapsed = time.time() - start
            if elapsed >= total + 1.0:
                break
            remaining = max(0.0, total - elapsed)
            print(f"\r  Playing... {elapsed:.1f}s / {total:.1f}s  "
                  f"({remaining:.1f}s remaining)    ", end="", flush=True)
            time.sleep(0.25)
    except KeyboardInterrupt:
        print()
        logger.info("Stopping path playback.")
        driver.path_stop()
        if slomo:
            driver.send_command("slomo 1.0")
        return

    print()
    driver.path_stop()
    if slomo:
        logger.info("Restoring game speed (slomo 1.0)...")
        driver.send_command("slomo 1.0")
    logger.info("Path complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Camera path test for captureAIshi bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9998)
    parser.add_argument("--read", action="store_true",
                        help="Just print current camera position and exit")
    parser.add_argument("--arc", action="store_true",
                        help="Use forward-arc demo instead of orbit")
    parser.add_argument("--radius", type=float, default=300.0,
                        help="Orbit radius in UE5 cm (default 300)")
    parser.add_argument("--segments", type=int, default=8,
                        help="Number of orbit segments (default 8)")
    parser.add_argument("--duration", type=float, default=2.0,
                        help="Seconds per segment (default 2.0)")
    parser.add_argument("--no-slomo", action="store_true",
                        help="Skip slomo -- only use when debug camera is active "
                             "(game's UpdateCamera has no position lock)")
    args = parser.parse_args()

    driver = UE5ConsoleDriver(host=args.host, port=args.port)
    try:
        driver.connect()
    except ConnectionRefusedError as e:
        logger.error(f"Connection failed: {e}")
        sys.exit(1)

    if not driver._is_bridge:
        logger.error("Connected server is not a captureAIshi bridge (UUU?). "
                     "Camera memory commands require the bridge DLL.")
        driver.disconnect()
        sys.exit(1)

    # Make sure camera POV is located
    logger.info("Locating camera POV in game memory...")
    driver.cam_find()

    # Read current position
    pos = driver.cam_read()
    if pos["x"] == 0.0 and pos["y"] == 0.0 and pos["z"] == 0.0:
        logger.warning("Camera read returned all zeros -- may not be found yet")

    logger.info(
        f"Current camera: "
        f"xyz=({pos['x']:.1f},{pos['y']:.1f},{pos['z']:.1f})  "
        f"pyr=({pos['pitch']:.1f},{pos['yaw']:.1f},{pos['roll']:.1f})  "
        f"fov={pos['fov']:.1f}"
    )

    if args.read:
        driver.disconnect()
        return

    # Build the demo path
    if args.arc:
        logger.info(f"Building forward-arc path from current position (yaw={pos['yaw']:.1f})")
        keyframes = build_arc_path(
            pos["x"], pos["y"], pos["z"],
            pos["yaw"], pos["fov"],
            forward_dist=400.0,
            height_rise=150.0,
            seg_duration=args.duration,
        )
    else:
        logger.info(
            f"Building orbit path: center=({pos['x']:.0f},{pos['y']:.0f},{pos['z']:.0f}) "
            f"radius={args.radius:.0f}cm segments={args.segments}"
        )
        keyframes = build_orbit_path(
            pos["x"], pos["y"], pos["z"],
            pos["yaw"], pos["fov"],
            radius=args.radius,
            segments=args.segments,
            seg_duration=args.duration,
        )

    play_path(driver, keyframes, slomo=not args.no_slomo)

    driver.disconnect()


if __name__ == "__main__":
    main()
