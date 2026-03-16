#!/usr/bin/env python3
"""captureAIshi — Cross-engine game capture CLI.

Captures RGB + Depth from released UE5/Unity games without source code.
Generates camera paths (snake pattern + cone rotation), controls the
game camera via pluggable drivers, and grabs frames via RenderDoc
or screenshot fallback.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

from core.waypoint import BoundingVolume, CameraPose
from core.snake_path import generate_snake_path
from core.cone_rotation import generate_cone_poses
from core.tangent_smoothing import smooth_waypoints


def create_driver(args):
    """Create camera driver from CLI arguments."""
    if args.driver == "manual":
        from drivers.manual import ManualDriver
        return ManualDriver(auto_confirm=args.dry_run)
    elif args.driver == "ue5":
        from drivers.ue5_console import UE5ConsoleDriver
        return UE5ConsoleDriver(
            host=args.driver_host,
            port=args.driver_port,
        )
    elif args.driver == "unity":
        from drivers.unity_socket import UnitySocketDriver
        return UnitySocketDriver(
            host=args.driver_host,
            port=args.driver_port,
        )
    elif args.driver == "cheatengine":
        from drivers.cheat_engine import CheatEngineDriver
        return CheatEngineDriver(
            mode=args.ce_mode,
            host=args.driver_host,
            port=args.driver_port,
        )
    else:
        raise ValueError(f"Unknown driver: {args.driver}")


def create_grabber(args):
    """Create frame grabber from CLI arguments."""
    if args.dry_run:
        return None
    if args.grabber == "renderdoc":
        from grabbers.renderdoc_grabber import RenderDocGrabber
        return RenderDocGrabber(
            capture_dir=str(args.output_dir / "captures"),
            target_exe=args.target_exe,
        )
    elif args.grabber == "screenshot":
        from grabbers.screenshot_grabber import ScreenshotGrabber
        return ScreenshotGrabber(
            screenshot_dir=str(args.output_dir / "screenshots"),
        )
    elif args.grabber == "none":
        return None
    else:
        raise ValueError(f"Unknown grabber: {args.grabber}")


def run_capture(args):
    """Main capture loop."""
    # Define capture volume
    volume = BoundingVolume(
        min_corner=np.array(args.volume_min),
        max_corner=np.array(args.volume_max),
    )

    logging.info(
        f"Capture volume: {volume.min_corner} → {volume.max_corner} "
        f"(size: {volume.size})"
    )

    # Generate waypoints
    waypoints = generate_snake_path(volume, spacing=args.spacing)
    logging.info(f"Generated {len(waypoints)} raw waypoints")

    # Smooth path
    if args.smooth and len(waypoints) >= 2:
        waypoints = smooth_waypoints(
            waypoints,
            points_per_segment=args.smooth_points,
        )
        logging.info(f"Smoothed to {len(waypoints)} waypoints")

    # Generate all camera poses (with cone rotation)
    all_poses = []
    for wp in waypoints:
        if args.cone_angle > 0:
            poses = generate_cone_poses(
                wp,
                half_angle_deg=args.cone_angle,
                num_ring_samples=args.cone_samples,
                num_rings=args.cone_rings,
            )
            all_poses.extend(poses)
        else:
            all_poses.append(CameraPose(
                position=wp.position,
                rotation=np.array([0.0, 0.0, 0.0]),
                fov=wp.fov,
            ))

    logging.info(f"Total camera poses: {len(all_poses)}")

    # Save poses metadata
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    poses_data = [p.to_dict() for p in all_poses]
    poses_file = output_dir / "poses.json"
    poses_file.write_text(json.dumps(poses_data, indent=2))
    logging.info(f"Poses saved to {poses_file}")

    if args.dry_run:
        logging.info("Dry run complete. No frames captured.")
        return

    # Execute capture
    driver = create_driver(args)
    grabber = create_grabber(args)

    with driver:
        grabber_ctx = grabber if grabber else None
        if grabber_ctx:
            grabber_ctx.setup()

        try:
            for i, pose in enumerate(all_poses):
                logging.info(f"Capturing pose {i + 1}/{len(all_poses)}")
                driver.set_pose(pose)

                if grabber_ctx:
                    rgb, depth = grabber_ctx.capture_frame()
                    grabber_ctx.save_frame(rgb, depth, output_dir / "frames", i)
        finally:
            if grabber_ctx:
                grabber_ctx.teardown()

    logging.info("Capture complete!")


def main():
    parser = argparse.ArgumentParser(
        description="captureAIshi — Cross-engine game capture framework",
    )

    # Volume definition
    parser.add_argument(
        "--volume-min", type=float, nargs=3, default=[-5, 0, -5],
        help="Bounding volume min corner (x y z) in meters",
    )
    parser.add_argument(
        "--volume-max", type=float, nargs=3, default=[5, 3, 5],
        help="Bounding volume max corner (x y z) in meters",
    )
    parser.add_argument(
        "--spacing", type=float, default=2.0,
        help="Distance between waypoints in meters",
    )

    # Path smoothing
    parser.add_argument("--smooth", action="store_true", help="Enable path smoothing")
    parser.add_argument("--smooth-points", type=int, default=5, help="Points per smooth segment")

    # Cone rotation
    parser.add_argument("--cone-angle", type=float, default=0, help="Cone half-angle in degrees (0=disabled)")
    parser.add_argument("--cone-samples", type=int, default=8, help="Samples per cone ring")
    parser.add_argument("--cone-rings", type=int, default=2, help="Number of cone rings")

    # Driver
    parser.add_argument("--driver", choices=["manual", "ue5", "unity", "cheatengine"], default="manual")
    parser.add_argument("--driver-host", default="127.0.0.1")
    parser.add_argument("--driver-port", type=int, default=9999)
    parser.add_argument("--ce-mode", choices=["socket", "file"], default="file")

    # Grabber
    parser.add_argument("--grabber", choices=["renderdoc", "screenshot", "none"], default="none")
    parser.add_argument("--target-exe", help="Game executable for RenderDoc auto-launch")

    # Output
    parser.add_argument("--output-dir", type=str, default="./output")
    parser.add_argument("--dry-run", action="store_true", help="Generate poses only, no capture")

    # Logging
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    args.output_dir = Path(args.output_dir)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    run_capture(args)


if __name__ == "__main__":
    main()
