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


def create_ui_hider(args):
    """Create UI hider chain from CLI arguments."""
    from ui_hiders.chain import build_ui_hider_chain

    # Determine engine from driver type
    engine_map = {"ue5": "ue5", "unity": "unity"}
    engine = engine_map.get(args.driver)

    return build_ui_hider_chain(
        engine=engine,
        console_host=args.driver_host,
        console_port=args.driver_port,
        use_renderdoc=(args.grabber == "renderdoc"),
    )


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
    ui_hider = create_ui_hider(args) if not args.no_hide_ui else None

    with driver:
        grabber_ctx = grabber if grabber else None
        if grabber_ctx:
            grabber_ctx.setup()

        # Attempt to hide UI before capture loop
        ui_method = None
        if ui_hider:
            result = ui_hider.hide()
            ui_method = ui_hider.active_method
            logging.info(f"UI hide result: {result.method} — {result.message}")

        try:
            for i, pose in enumerate(all_poses):
                logging.info(f"Capturing pose {i + 1}/{len(all_poses)}")
                driver.set_pose(pose)

                if grabber_ctx:
                    rgb, depth = grabber_ctx.capture_frame()
                    grabber_ctx.save_frame(rgb, depth, output_dir / "frames", i)
        finally:
            # Restore UI after capture
            if ui_hider:
                ui_hider.restore()
            if grabber_ctx:
                grabber_ctx.teardown()

    # Update poses metadata with UI removal info
    ui_removed = ui_method is not None and ui_method != "noop"
    for p in poses_data:
        p["ui_removed"] = ui_removed
        p["ui_hide_method"] = ui_method or "none"
    poses_file.write_text(json.dumps(poses_data, indent=2))

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

    # UI hiding
    parser.add_argument(
        "--no-hide-ui", action="store_true",
        help="Disable automatic UI/HUD hiding",
    )

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
