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
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# opencv-python disables EXR support by default; opt in before any
# module triggers an `import cv2` (image_loader is imported lazily by
# the grabber, so we set the env var first).
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import numpy as np

from core.waypoint import BoundingVolume, CameraPose
from core.snake_path import generate_snake_path
from core.cone_rotation import generate_cone_poses
from core.tangent_smoothing import smooth_waypoints


def _find_hider_in_chain(hider, cls):
    """Walk a UIHider chain and return the first instance of cls, or None."""
    current = hider
    while current is not None:
        if isinstance(current, cls):
            return current
        current = getattr(current, '_fallback', None)
    return None


def create_driver(args):
    """Create camera driver from CLI arguments."""
    logging.debug(f"[INIT] Creating driver: type={args.driver}, host={args.driver_host}, port={args.driver_port}")
    if args.driver == "manual":
        from drivers.manual import ManualDriver
        return ManualDriver(auto_confirm=args.dry_run)
    elif args.driver == "ue5":
        from drivers.ue5_console import UE5ConsoleDriver
        return UE5ConsoleDriver(
            host=args.driver_host,
            port=args.driver_port,
            capture_resolution=getattr(args, 'capture_resolution', None),
            disable_upscaler=not getattr(args, 'no_disable_upscaler', False),
        )
    elif args.driver == "unity":
        from drivers.unity_socket import UnitySocketDriver
        return UnitySocketDriver(
            host=args.driver_host,
            port=args.driver_port,
        )
    elif args.driver == "cheatengine":
        from drivers.cheat_engine import CheatEngineDriver
        logging.debug(f"[INIT] CheatEngine mode={args.ce_mode}")
        return CheatEngineDriver(
            mode=args.ce_mode,
            host=args.driver_host,
            port=args.driver_port,
        )
    elif args.driver == "memory":
        from drivers.external_memory import ExternalMemoryDriver
        logging.debug(f"[INIT] ExternalMemory offsets={args.memory_offsets}")
        return ExternalMemoryDriver(
            offsets_file=args.memory_offsets,
        )
    else:
        raise ValueError(f"Unknown driver: {args.driver}")


def create_grabber(args):
    """Create frame grabber from CLI arguments."""
    logging.debug(f"[INIT] Creating grabber: type={args.grabber}, dry_run={args.dry_run}")
    if args.dry_run:
        logging.debug("[INIT] Dry run — skipping grabber creation")
        return None
    if args.grabber == "renderdoc":
        from grabbers.renderdoc_grabber import RenderDocGrabber
        # Get the RenderDoc UI hider if available
        rdoc_ui_hider = getattr(args, '_rdoc_ui_hider', None)
        logging.debug(f"[INIT] RenderDoc grabber: capture_dir={args.output_dir / 'captures'}, "
                       f"target_exe={args.target_exe}, ui_hider={'yes' if rdoc_ui_hider else 'no'}")
        # Pass the driver port so the grabber can detect when the game is ready
        # Only poll port for drivers that actually use a network connection
        driver_port = getattr(args, 'driver_port', None)
        if getattr(args, 'driver', 'manual') == 'manual':
            driver_port = None
        inject_mode = getattr(args, 'inject', False)
        # Load per-game capture profile if --game is specified
        capture_profile = {}
        game_id = getattr(args, 'game', None)
        if game_id:
            try:
                from drivers.game_profile import load_profile
                prof = load_profile(game_id)
                capture_profile = prof.capture
                logging.info(f"[INIT] Loaded game profile '{game_id}': capture={capture_profile}")
            except FileNotFoundError:
                logging.warning(f"[INIT] Game profile '{game_id}' not found, using auto-detect")
        return RenderDocGrabber(
            renderdoc_path=getattr(args, 'renderdoc_path', 'renderdoccmd'),
            capture_dir=str(args.output_dir / "captures"),
            target_exe=args.target_exe,
            target_args=getattr(args, 'target_args', []),
            auto_launch=bool(args.target_exe),
            inject_mode=inject_mode,
            inject_delay=getattr(args, 'inject_delay', 5.0),
            ui_hider=rdoc_ui_hider,
            wait_for_port=int(driver_port) if driver_port else None,
            capture_profile=capture_profile,
        )
    elif args.grabber == "reshade":
        from grabbers.reshade_grabber import ReShadeGrabber
        target_exe = getattr(args, 'target_exe', None)
        if not target_exe:
            raise ValueError("ReShade grabber requires --target-exe (game dir is derived from it)")
        game_dir = Path(target_exe).parent
        out_dir = args.output_dir / "frames"
        logging.debug(f"[INIT] ReShade grabber: game_dir={game_dir}, output_dir={out_dir}")
        return ReShadeGrabber(output_dir=out_dir, game_dir=game_dir)
    elif args.grabber == "screenshot":
        from grabbers.screenshot_grabber import ScreenshotGrabber
        logging.debug(f"[INIT] Screenshot grabber: dir={args.output_dir / 'screenshots'}")
        return ScreenshotGrabber(
            screenshot_dir=str(args.output_dir / "screenshots"),
        )
    elif args.grabber in ("none", "obs"):
        logging.debug(f"[INIT] No frame grabber (grabber={args.grabber})")
        return None
    else:
        raise ValueError(f"Unknown grabber: {args.grabber}")


def create_ui_hider(args):
    """Create UI hider chain from CLI arguments."""
    from ui_hiders.chain import build_ui_hider_chain

    # Determine engine from driver type
    engine_map = {"ue5": "ue5", "unity": "unity"}
    engine = engine_map.get(args.driver)
    logging.debug(f"[INIT] Building UI hider chain: engine={engine}, use_renderdoc={args.grabber == 'renderdoc'}")

    return build_ui_hider_chain(
        engine=engine,
        console_host=args.driver_host,
        console_port=args.driver_port,
        use_renderdoc=(args.grabber == "renderdoc"),
    )



def run_capture(args):
    """Prepare a capture session: launch the game via the grabber, connect
    the driver, and hold the session open until the user presses Stop.

    Legacy volume + snake path + cone rotation pose generation has been
    removed; per-waypoint RDC capture and pose streaming are now driven
    from the Web UI (Bridge Debug -> Capture button / Trajectory panel ->
    Play button), which talk to the bridge console server directly. All
    this entry point does is:

    1. Create driver / UI hider / grabber (RenderDoc auto-launch).
    2. Wait for UWorld + LocalPlayer readiness (so scan has resolved
       before the user presses Capture / Play).
    3. Block on stop_event until Stop is pressed, cleaning up on exit.

    Raises if the grabber fails to launch the game. Returns cleanly when
    stop_event fires or an outer KeyboardInterrupt arrives.
    """
    import time as _time

    t_start = _time.monotonic()

    logging.info(
        f"[CONFIG] driver={args.driver}, grabber={args.grabber}, "
        f"target_exe={getattr(args, 'target_exe', None)}, "
        f"target_args={getattr(args, 'target_args', [])}, "
        f"output_dir={args.output_dir}"
    )

    # Output directory still useful for per-pose captures triggered
    # from the Debug panel.
    output_dir = Path(args.output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.error(f"[IO] Failed to create output directory {output_dir}: {e}")
        raise

    if args.dry_run:
        logging.info("Dry run: skipping driver/grabber setup.")
        return

    from recorders import create_recorder
    recorder = create_recorder(args, output_dir)

    try:
        driver = create_driver(args)
    except Exception as e:
        logging.error(f"[INIT] Failed to create driver '{args.driver}': {e}")
        raise

    ui_hider = None
    if not args.no_hide_ui:
        try:
            ui_hider = create_ui_hider(args)
        except Exception as e:
            logging.warning(f"[INIT] Failed to create UI hider (continuing without): {e}")

    if ui_hider and args.grabber == "renderdoc":
        from ui_hiders.renderdoc_hider import RenderDocUIHider
        rdoc_hider = _find_hider_in_chain(ui_hider, RenderDocUIHider)
        if rdoc_hider:
            args._rdoc_ui_hider = rdoc_hider

    try:
        grabber = create_grabber(args)
    except Exception as e:
        logging.error(f"[INIT] Failed to create grabber '{args.grabber}': {e}")
        raise

    stop_event = getattr(args, '_stop_event', None)
    grabber_ctx = grabber if grabber else None

    _direct_game_process = None
    if grabber_ctx is None and getattr(args, "target_exe", None) and not args.dry_run:
        from grabbers.renderdoc import launch as _launch
        _direct_game_process = _launch.launch_game_direct(
            args.target_exe, getattr(args, "target_args", [])
        )
        _wait_port = None
        if getattr(args, "driver", "manual") != "manual":
            _wait_port = getattr(args, "driver_port", None)
        try:
            _launch.wait_for_game_ready(_direct_game_process, 90.0, _wait_port, args.target_exe)
        except RuntimeError as e:
            logging.warning(f"[LAUNCH] Game exited unexpectedly: {e}")

    if grabber_ctx:
        try:
            grabber_ctx.setup()
            logging.info("[GRABBER] Grabber setup complete, game should be running")
            # Publish the grabber so the trajectory Play route can dispatch
            # post-loop .rdc -> PNG decode through grabber.export_batch.
            try:
                from web import state as _web_state
                _web_state.set_active_grabber(grabber_ctx)
            except Exception as _e:
                logging.debug(f"[GRABBER] Could not publish active grabber: {_e}")
        except Exception as e:
            logging.error(f"[GRABBER] Grabber setup failed: {e}")
            raise

    driver_connected = False
    hud_hidden_via_bridge = False
    try:
        try:
            driver.connect()
            driver_connected = True
            logging.info(f"[DRIVER] Connected to {args.driver} at {args.driver_host}:{args.driver_port}")
        except (ConnectionRefusedError, ConnectionError, OSError) as e:
            if args.driver != "manual":
                logging.warning(
                    f"[DRIVER] Could not connect {args.driver} driver ({e}). "
                    f"Falling back to manual mode -- capture will proceed without camera control."
                )
                from drivers.manual import ManualDriver
                driver = ManualDriver(auto_confirm=True)
                driver.connect()
                driver_connected = True
            else:
                raise

        if hasattr(driver, 'enable_debug_camera'):
            try:
                driver.enable_debug_camera()
                logging.info("[DRIVER] Debug camera mode enabled")
            except Exception as e:
                logging.warning(f"[DRIVER] Failed to enable debug camera: {e}")

        # Start video recording early so it captures the full session,
        # including the time the player spends in the readiness gate below.
        if (
            getattr(args, "recorder_enabled", False)
            and getattr(args, "hide_hud_during_recording", True)
            and hasattr(driver, "send_console_command")
        ):
            try:
                driver.send_console_command("__hud_toggle")
                hud_hidden_via_bridge = True
                logging.info("[VIDEO] HUD toggled via bridge for clean footage")
            except Exception as e:
                logging.debug(f"[VIDEO] bridge __hud_toggle failed: {e}")

        if getattr(args, "recorder_enabled", False):
            _obs_port = getattr(args, "obs_port", 4455)
            if args.driver_port == _obs_port:
                logging.warning(
                    f"[VIDEO] driver_port ({args.driver_port}) matches obs_port ({_obs_port}). "
                    f"Driver may have connected to OBS instead of the game bridge. "
                    f"Set driver_port to your bridge port (default 9998)."
                )
            try:
                recorder.__enter__()
                _session_name = output_dir.name or "captureAIshi"
                recorder.start(_session_name)
            except Exception as e:
                logging.warning(f"[VIDEO] recorder start failed: {e}")

        # UE object readiness gate: wait for UWorld + LocalPlayer so the
        # Debug panel's Capture / Play buttons can find addresses.
        if hasattr(driver, 'wait_for_objects_ready'):
            poll_interval = 2.0
            gate_timeout = 600.0
            elapsed = 0.0
            logging.info(
                "[GATE] Waiting for UWorld + LocalPlayer "
                "(click 'Re-scan UE' in Debug panel after map loads)"
            )
            while elapsed < gate_timeout:
                if stop_event is not None and stop_event.is_set():
                    logging.info("[GATE] Stop requested during readiness gate.")
                    return
                if driver.is_objects_ready():
                    logging.info(f"[GATE] Engine objects ready after {elapsed:.0f}s.")
                    break
                _time.sleep(poll_interval)
                elapsed += poll_interval
            else:
                logging.warning("[GATE] Timed out waiting for engine objects. Session stays open.")

        if ui_hider:
            try:
                result = ui_hider.hide()
                logging.info(f"[UI] Hide result: {result.method} -- {result.message}")
            except Exception as e:
                logging.warning(f"[UI] Failed to hide UI (continuing): {e}")

        logging.info(
            "[SESSION] Game is running and bridge is connected. Use the "
            "Web UI (Bridge Debug -> Capture / Trajectory -> Play) to "
            "drive captures. Press Stop to exit."
        )
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    logging.info("[SESSION] Stop requested.")
                    break
                _time.sleep(1.0)
        except KeyboardInterrupt:
            logging.info("[SESSION] Interrupted by user.")
    finally:
        try:
            if recorder.is_recording:
                recorder.stop()
        except Exception as e:
            logging.warning(f"[VIDEO] stop failed: {e}")
        try:
            recorder.__exit__(None, None, None)
        except Exception as e:
            logging.debug(f"[VIDEO] recorder __exit__: {e}")
        if hud_hidden_via_bridge and driver_connected and hasattr(driver, "send_console_command"):
            try:
                driver.send_console_command("__hud_toggle")
            except Exception as e:
                logging.debug(f"[VIDEO] HUD restore failed: {e}")
        if ui_hider:
            try:
                ui_hider.restore()
            except Exception as e:
                logging.warning(f"[UI] Failed to restore UI: {e}")
        if grabber_ctx:
            try:
                grabber_ctx.teardown()
            except Exception as e:
                logging.warning(f"[GRABBER] Teardown failed: {e}")
            try:
                from web import state as _web_state
                _web_state.set_active_grabber(None)
            except Exception:
                pass
        if driver_connected:
            try:
                driver.disconnect()
            except Exception as e:
                logging.warning(f"[DRIVER] Disconnect failed: {e}")

    elapsed_total = _time.monotonic() - t_start
    logging.info(f"Session ended after {elapsed_total:.1f}s.")
    return
    # ------------------------------------------------------------------
    # Dead code below kept temporarily to avoid churn while core/snake_path,
    # core/cone_rotation, BoundingVolume, smooth_waypoints, and their tests
    # are removed in the next sweep. Will be deleted in the same commit.
    # ------------------------------------------------------------------

    logging.info(
        f"Capture volume: {volume.min_corner} → {volume.max_corner} "
        f"(size: {volume.size})"
    )

    # ── Step 1: Generate waypoints ──
    t0 = _time.monotonic()
    waypoints = generate_snake_path(volume, spacing=args.spacing)
    elapsed = _time.monotonic() - t0
    logging.info(f"Generated {len(waypoints)} raw waypoints (spacing={args.spacing}m)")
    logging.debug(f"[PERF] Snake path generation took {elapsed:.3f}s")
    if waypoints:
        logging.debug(f"[PATH] First waypoint: {waypoints[0].position}, "
                       f"Last waypoint: {waypoints[-1].position}")

    # ── Step 2: Smooth path ──
    if args.smooth and len(waypoints) >= 2:
        count_before = len(waypoints)
        t0 = _time.monotonic()
        waypoints = smooth_waypoints(
            waypoints,
            points_per_segment=args.smooth_points,
        )
        elapsed = _time.monotonic() - t0
        logging.info(f"Smoothed {count_before} → {len(waypoints)} waypoints "
                     f"(points_per_segment={args.smooth_points})")
        logging.debug(f"[PERF] Path smoothing took {elapsed:.3f}s")
    else:
        logging.debug(f"[PATH] Smoothing skipped (smooth={args.smooth}, "
                       f"waypoint_count={len(waypoints)})")

    # ── Step 3: Generate all camera poses (with cone rotation) ──
    spline_mode = "catmull-rom" if args.smooth else "manual"
    fov_v = getattr(args, 'fov', 90.0)
    aspect = getattr(args, 'aspect', 16.0 / 9.0)

    t0 = _time.monotonic()
    all_poses = []
    for wp_idx, wp in enumerate(waypoints):
        if args.cone_angle > 0:
            poses = generate_cone_poses(
                wp,
                half_angle_deg=args.cone_angle,
                num_ring_samples=args.cone_samples,
                num_rings=args.cone_rings,
            )
            for ci, pose in enumerate(poses):
                pose.fov = fov_v
                pose.aspect = aspect
                pose.point_index = wp_idx
                pose.spline_mode = spline_mode
                pose.view_name = f"cone{ci}"
            all_poses.extend(poses)
        else:
            all_poses.append(CameraPose(
                position=wp.position,
                rotation=np.array([0.0, 0.0, 0.0]),
                fov=fov_v,
                aspect=aspect,
                view_name="center",
                point_index=wp_idx,
                spline_mode=spline_mode,
            ))
    elapsed = _time.monotonic() - t0

    if args.cone_angle > 0:
        poses_per_wp = 1 + args.cone_samples * args.cone_rings
        logging.info(f"Total camera poses: {len(all_poses)} "
                     f"({len(waypoints)} waypoints x {poses_per_wp} cone poses)")
    else:
        logging.info(f"Total camera poses: {len(all_poses)} (no cone rotation)")
    logging.debug(f"[PERF] Pose generation took {elapsed:.3f}s")

    # ── Step 4: Save poses metadata ──
    output_dir = Path(args.output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.error(f"[IO] Failed to create output directory {output_dir}: {e}")
        raise

    poses_data = [p.to_dict() for p in all_poses]
    poses_file = output_dir / "poses.json"
    try:
        poses_file.write_text(json.dumps(poses_data, indent=2))
        logging.info(f"Poses saved to {poses_file}")
        logging.debug(f"[IO] poses.json size: {poses_file.stat().st_size} bytes")
    except OSError as e:
        logging.error(f"[IO] Failed to write poses file {poses_file}: {e}")
        raise

    if args.dry_run:
        elapsed_total = _time.monotonic() - t_start
        logging.info(f"Dry run complete. No frames captured. (total time: {elapsed_total:.2f}s)")
        return

    # ── Step 5: Initialize driver, UI hider, grabber ──
    logging.info("Initializing capture components...")

    try:
        driver = create_driver(args)
    except Exception as e:
        logging.error(f"[INIT] Failed to create driver '{args.driver}': {e}")
        raise

    # For RenderDoc grabber, extract the RenderDoc UI hider from the chain
    # so it can be integrated into per-frame replay instead of pre-loop
    ui_hider = None
    if not args.no_hide_ui:
        try:
            ui_hider = create_ui_hider(args)
        except Exception as e:
            logging.warning(f"[INIT] Failed to create UI hider (continuing without): {e}")

    if ui_hider and args.grabber == "renderdoc":
        from ui_hiders.renderdoc_hider import RenderDocUIHider
        rdoc_hider = _find_hider_in_chain(ui_hider, RenderDocUIHider)
        if rdoc_hider:
            args._rdoc_ui_hider = rdoc_hider
            logging.debug("[INIT] RenderDoc UI hider attached to grabber for per-frame filtering")

    try:
        grabber = create_grabber(args)
    except Exception as e:
        logging.error(f"[INIT] Failed to create grabber '{args.grabber}': {e}")
        raise

    stop_event = getattr(args, '_stop_event', None)

    # ── Step 6: Launch game via grabber BEFORE connecting driver ──
    # RenderDoc auto-launch must happen first so the game is running
    # by the time the driver tries to connect its socket.
    grabber_ctx = grabber if grabber else None
    if grabber_ctx:
        try:
            grabber_ctx.setup()
            logging.info("[GRABBER] Grabber setup complete, game should be running")
        except Exception as e:
            logging.error(f"[GRABBER] Grabber setup failed: {e}")
            raise

    # ── Step 7: Execute capture loop ──
    # Note: Console server starts automatically inside renderdoc.dll
    # when the game is launched via renderdoccmd. No separate injection needed.
    streaming_enabled = getattr(args, 'streaming', True)
    streaming_settle = getattr(args, 'streaming_settle', 0.5)
    logging.info(
        f"Starting capture loop: {len(all_poses)} poses "
        f"(streaming={'on' if streaming_enabled else 'off'}, "
        f"settle={streaming_settle}s)"
    )

    driver_connected = False
    try:
        try:
            driver.connect()
            driver_connected = True
            logging.info(f"[DRIVER] Connected to {args.driver} at {args.driver_host}:{args.driver_port}")
        except (ConnectionRefusedError, ConnectionError, OSError) as e:
            if args.driver != "manual":
                logging.warning(
                    f"[DRIVER] Could not connect {args.driver} driver ({e}). "
                    f"Falling back to manual mode — capture will proceed without camera control."
                )
                from drivers.manual import ManualDriver
                driver = ManualDriver(auto_confirm=True)
                driver.connect()
                driver_connected = True
            else:
                raise

        # Enter debug/free camera mode so SetViewLocation/Rotation works
        if hasattr(driver, 'enable_debug_camera'):
            try:
                driver.enable_debug_camera()
                logging.info("[DRIVER] Debug camera mode enabled")
            except Exception as e:
                logging.warning(f"[DRIVER] Failed to enable debug camera: {e}")

        # ── Debug-scan mode: skip capture, keep process alive ──
        if getattr(args, 'debug_scan', False):
            logging.info(
                "[DEBUG-SCAN] Bridge connected. Capture loop SKIPPED. "
                "Use Web UI to inspect scan status, send test commands, "
                "and click Re-scan UE. Press Ctrl+C to exit."
            )
            try:
                while True:
                    if stop_event is not None and stop_event.is_set():
                        logging.info("[DEBUG-SCAN] Stop requested.")
                        break
                    import time as _time_ds
                    _time_ds.sleep(1.0)
            except KeyboardInterrupt:
                logging.info("[DEBUG-SCAN] Interrupted by user.")
            return  # skip to finally block for teardown

        # Attempt to hide UI before capture loop (console-based hiding)
        ui_method = None
        if ui_hider:
            try:
                result = ui_hider.hide()
                ui_method = ui_hider.active_method
                logging.info(f"[UI] Hide result: {result.method} — {result.message}")
            except Exception as e:
                logging.warning(f"[UI] Failed to hide UI (continuing): {e}")
        else:
            logging.debug("[UI] UI hiding disabled (no_hide_ui={})".format(args.no_hide_ui))

        # ── UE object readiness gate ──
        # Wait for UWorld + LocalPlayer before starting capture.
        # Bridge finds these via GUObjectArray+FName scan after map load.
        # Click "Re-scan UE" in the Debug panel after the game's map is loaded.
        if hasattr(driver, 'wait_for_objects_ready'):
            poll_interval = 2.0
            gate_timeout = 600.0  # 10 min; user clicks Re-scan to unblock
            elapsed = 0.0
            logging.info(
                "[GATE] Waiting for UWorld + LocalPlayer "
                "(click 'Re-scan UE' in Debug panel after map loads)"
            )
            while elapsed < gate_timeout:
                if stop_event is not None and stop_event.is_set():
                    logging.info("[GATE] Stop requested, aborting capture.")
                    break
                if driver.is_objects_ready():
                    logging.info(f"[GATE] Engine objects ready after {elapsed:.0f}s, starting capture.")
                    break
                import time as _time_gate
                _time_gate.sleep(poll_interval)
                elapsed += poll_interval
            else:
                logging.warning("[GATE] Timed out waiting for engine objects. Proceeding anyway.")

        frames_ok = 0
        frames_no_rgb = 0
        frames_no_depth = 0
        frames_failed = 0
        trajectory = []  # Trajectory entries matching user's JSON schema

        # Session prefix for filenames: project_timestamp
        session_prefix = getattr(args, 'session_prefix', '')
        if not session_prefix:
            session_prefix = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]

        batch_export = not getattr(args, 'no_batch_export', False) and grabber_ctx is not None
        rdc_paths = []  # For batch mode: collect .rdc paths
        base_names = []  # For batch mode: parallel list of base_names

        # ── Phase 1: Capture loop (trigger only in batch mode) ──
        for i, pose in enumerate(all_poses):
            # Check stop event (from GUI or external signal)
            if stop_event is not None and stop_event.is_set():
                logging.info(f"Capture stopped by user at pose {i + 1}/{len(all_poses)}.")
                break

            logging.info(f"Capturing pose {i + 1}/{len(all_poses)}")
            logging.debug(
                f"[POSE {i+1}] pos=({pose.position[0]:.2f}, {pose.position[1]:.2f}, {pose.position[2]:.2f}) "
                f"rot=({pose.rotation[0]:.1f}, {pose.rotation[1]:.1f}, {pose.rotation[2]:.1f}) "
                f"fov={pose.fov:.0f}"
            )

            # Update streaming center BEFORE setting camera pose
            if streaming_enabled:
                try:
                    t_stream = _time.monotonic()
                    driver.update_streaming(pose)
                    stream_elapsed = _time.monotonic() - t_stream
                    logging.debug(f"[POSE {i+1}] Streaming update took {stream_elapsed:.3f}s")
                except Exception as e:
                    logging.warning(f"[POSE {i+1}] Streaming update failed (continuing): {e}")

            try:
                t_pose = _time.monotonic()
                driver.set_pose(pose)
                driver_elapsed = _time.monotonic() - t_pose
                logging.debug(f"[POSE {i+1}] Driver set_pose took {driver_elapsed:.3f}s")
            except Exception as e:
                logging.error(
                    f"[POSE {i+1}] Driver set_pose failed: {e}\n"
                    f"  pose: pos={pose.position}, rot={pose.rotation}, fov={pose.fov}"
                )
                frames_failed += 1
                if batch_export:
                    rdc_paths.append(None)
                    base_names.append("")
                continue

            # Wait for streaming to settle after camera has moved
            if streaming_enabled:
                driver.wait_for_streaming(streaming_settle)

            # Build filename base
            base_name = f"{session_prefix}_p{pose.point_index}_{pose.view_name}"
            rgb_filename = f"{base_name}.png"
            depth_filename = f"{base_name}_d.png"
            normal_filename = ""

            if grabber_ctx:
                if batch_export:
                    # Phase 1 batch: trigger only, defer export
                    try:
                        t_grab = _time.monotonic()
                        rdc_path = grabber_ctx.trigger_only()
                        grab_elapsed = _time.monotonic() - t_grab
                        rdc_paths.append(rdc_path)
                        base_names.append(base_name)
                        logging.debug(
                            f"[POSE {i+1}] Trigger took {grab_elapsed:.3f}s -> {rdc_path}"
                        )
                    except Exception as e:
                        logging.error(f"[POSE {i+1}] Trigger failed: {e}")
                        rdc_paths.append(None)
                        base_names.append(base_name)
                        frames_failed += 1
                else:
                    # Original mode: capture + export per frame
                    rgb, depth, normal = None, None, None
                    try:
                        t_grab = _time.monotonic()
                        frame_data = grabber_ctx.capture_frame_ex()
                        rgb = frame_data.rgb
                        depth = frame_data.depth
                        normal = frame_data.normal
                        grab_elapsed = _time.monotonic() - t_grab

                        rgb_info = f"{rgb.shape[1]}x{rgb.shape[0]}" if rgb is not None else "None"
                        depth_info = f"{depth.shape[1]}x{depth.shape[0]}" if depth is not None else "None"
                        logging.debug(
                            f"[POSE {i+1}] Frame captured in {grab_elapsed:.3f}s — "
                            f"rgb={rgb_info}, depth={depth_info}"
                        )

                        if rgb is None:
                            frames_no_rgb += 1
                        if depth is None:
                            frames_no_depth += 1
                        if rgb is not None:
                            frames_ok += 1
                    except Exception as e:
                        logging.error(f"[POSE {i+1}] Frame capture failed: {e}")
                        frames_failed += 1

                    try:
                        t_save = _time.monotonic()
                        saved = grabber_ctx.save_frame(
                            rgb, depth, output_dir / "frames", i,
                            base_name=base_name, normal=normal,
                        )
                        rgb_filename = saved.get("rgb", rgb_filename)
                        depth_filename = saved.get("depth", depth_filename)
                        normal_filename = saved.get("normal", f"{base_name}_n.png") if normal is not None else ""
                        save_elapsed = _time.monotonic() - t_save
                        logging.debug(f"[POSE {i+1}] Frame saved in {save_elapsed:.3f}s")
                    except Exception as e:
                        logging.error(f"[POSE {i+1}] Frame save failed: {e}")

            if not batch_export:
                trajectory.append(pose.to_trajectory_dict(
                    rgb_filename=rgb_filename,
                    depth_filename=depth_filename,
                    normal_filename=normal_filename,
                ))

            # Progress logging every 10%
            if len(all_poses) >= 10 and (i + 1) % max(1, len(all_poses) // 10) == 0:
                pct = (i + 1) / len(all_poses) * 100
                logging.info(f"Progress: {pct:.0f}% ({i + 1}/{len(all_poses)})")

        # ── Phase 2: Batch export (if enabled) ──
        if batch_export and rdc_paths:
            logging.info(f"Phase 2: Batch exporting {len(rdc_paths)} captures...")
            t_export = _time.monotonic()

            export_results = grabber_ctx.export_batch(
                rdc_paths, Path(str(grabber_ctx.capture_dir)),
            )

            total_export = len(export_results)
            for idx, ((rgb, depth, normal), bname, pose) in enumerate(
                zip(export_results, base_names, all_poses)
            ):
                if not bname:
                    trajectory.append(pose.to_trajectory_dict())
                    continue

                rgb_filename = f"{bname}.png"
                depth_filename = f"{bname}_d.png"
                normal_filename = f"{bname}_n.png" if normal is not None else ""

                logging.info(
                    f"Saving frame {idx + 1}/{total_export}: "
                    f"rgb={'ok' if rgb is not None else 'skip'} "
                    f"depth={'ok' if depth is not None else 'skip'} "
                    f"normal={'ok' if normal is not None else 'skip'}"
                )

                try:
                    saved = grabber_ctx.save_frame(
                        rgb, depth, output_dir / "frames", idx,
                        base_name=bname, normal=normal,
                    )
                    rgb_filename = saved.get("rgb", rgb_filename)
                    depth_filename = saved.get("depth", depth_filename)
                    normal_filename = saved.get("normal", normal_filename)
                    if rgb is not None:
                        frames_ok += 1
                    else:
                        frames_no_rgb += 1
                    if depth is None:
                        frames_no_depth += 1
                    logging.debug(f"[BATCH] Frame {idx} saved: {saved}")
                except Exception as e:
                    logging.error(f"[BATCH] Frame {idx} save failed: {e}")
                    frames_failed += 1

                trajectory.append(pose.to_trajectory_dict(
                    rgb_filename=rgb_filename,
                    depth_filename=depth_filename,
                    normal_filename=normal_filename,
                ))

            export_elapsed = _time.monotonic() - t_export
            logging.info(f"Batch export complete in {export_elapsed:.1f}s")

    except Exception as e:
        logging.error(f"[CAPTURE] Unexpected error: {e}\n{traceback.format_exc()}")
        raise
    finally:
        # Debug: pause before teardown so a debugger can be attached
        if getattr(args, 'wait_attach', False):
            logging.info(
                "[DEBUG] --wait-attach: capture done. "
                "Attach debugger to game/renderdoc process now, then press Enter to continue teardown."
            )
            try:
                input()
            except EOFError:
                pass

        # Restore UI
        if ui_hider:
            try:
                logging.debug("[UI] Restoring UI...")
                ui_hider.restore()
            except Exception as e:
                logging.warning(f"[UI] Failed to restore UI: {e}")

        # Teardown grabber
        if grabber_ctx:
            try:
                logging.debug("[GRABBER] Tearing down grabber...")
                grabber_ctx.teardown()
            except Exception as e:
                logging.warning(f"[GRABBER] Teardown failed: {e}")

        # Disconnect driver
        if driver_connected:
            try:
                logging.debug("[DRIVER] Disconnecting driver...")
                driver.disconnect()
            except Exception as e:
                logging.warning(f"[DRIVER] Disconnect failed: {e}")

    # Update poses metadata with UI removal info
    ui_removed = ui_method is not None and ui_method != "noop"
    for p in poses_data:
        p["ui_removed"] = ui_removed
        p["ui_hide_method"] = ui_method or "none"
    try:
        poses_file.write_text(json.dumps(poses_data, indent=2))
        logging.debug(f"[IO] Updated poses.json with ui_removed={ui_removed}, method={ui_method or 'none'}")
    except OSError as e:
        logging.warning(f"[IO] Failed to update poses.json: {e}")

    # Write trajectory JSON in the user-specified camera parameter format
    trajectory_file = output_dir / "trajectory.json"
    try:
        trajectory_file.write_text(json.dumps(trajectory, indent=2))
        logging.info(f"Trajectory saved to {trajectory_file} ({len(trajectory)} entries)")
    except OSError as e:
        logging.warning(f"[IO] Failed to write trajectory.json: {e}")

    elapsed_total = _time.monotonic() - t_start
    logging.info(
        f"Capture complete! {len(all_poses)} poses in {elapsed_total:.1f}s "
        f"(rgb_ok={frames_ok}, no_rgb={frames_no_rgb}, "
        f"no_depth={frames_no_depth}, failed={frames_failed})"
    )


def main():
    parser = argparse.ArgumentParser(
        description="captureAIshi — Cross-engine game capture framework",
    )

    # Camera intrinsics
    parser.add_argument("--fov", type=float, default=90.0, help="Vertical FOV in degrees")
    parser.add_argument("--aspect", type=float, default=16.0/9.0, help="Aspect ratio (width/height)")

    # Driver
    parser.add_argument(
        "--driver",
        choices=["manual", "ue5", "unity", "cheatengine", "memory"],
        default="manual",
    )
    parser.add_argument("--driver-host", default="127.0.0.1")
    parser.add_argument("--driver-port", type=int, default=9999)
    parser.add_argument("--ce-mode", choices=["socket", "file"], default="file")
    parser.add_argument(
        "--memory-offsets", type=str, default="",
        help="JSON file with camera memory offsets (for --driver memory). "
             "Use Cheat Engine to find offsets per game.",
    )

    # Rendering quality (UE5)
    parser.add_argument(
        "--capture-resolution", type=str, default=None,
        help="Force game render resolution (e.g. '3840x2160' for 4K). UE5 only.",
    )
    parser.add_argument(
        "--no-disable-upscaler", action="store_true",
        help="Keep DLSS/FSR/TSR enabled (default: disabled for pixel-aligned buffers)",
    )

    # Grabber
    parser.add_argument("--grabber", choices=["renderdoc", "reshade", "screenshot", "none", "obs"], default="none")
    parser.add_argument("--target-exe", help="Game executable for RenderDoc auto-launch")
    parser.add_argument(
        "--inject", action="store_true",
        help="Inject into already-running game instead of launching via renderdoccmd. "
             "Use for games that crash on RenderDoc launch (e.g. Cyberpunk 2077 2.x D3D12 check). "
             "Launch the game manually first, then run with --inject --target-exe Cyberpunk2077.exe.",
    )
    parser.add_argument(
        "--game", metavar="ID",
        help="Game profile id from configs/hacks/ (e.g. batman_ak). "
             "Sets per-game texture indices and depth flags for exportframe.",
    )
    parser.add_argument(
        "--no-batch-export", action="store_true",
        help="Disable batch export: export each frame immediately after capture. "
             "Slower but allows inspecting frames during capture.",
    )

    # UI hiding
    parser.add_argument(
        "--no-hide-ui", action="store_true",
        help="Disable automatic UI/HUD hiding",
    )

    # Streaming / LOD management
    parser.add_argument(
        "--no-streaming", action="store_true",
        help="Disable streaming center updates (camera-only mode, may cause low LOD/textures)",
    )
    parser.add_argument(
        "--streaming-settle", type=float, default=0.5,
        help="Seconds to wait for texture/level streaming after each camera move (default: 0.5)",
    )

    # Video recording (OBS WebSocket v5)
    parser.add_argument(
        "--video", dest="recorder_enabled", action="store_true",
        help="Record gameplay video via OBS WebSocket (off by default).",
    )
    parser.add_argument(
        "--no-video", dest="recorder_enabled", action="store_false",
        help="Disable video recording (default).",
    )
    parser.set_defaults(recorder_enabled=False)
    parser.add_argument("--obs-host", default="127.0.0.1")
    parser.add_argument("--obs-port", type=int, default=4455)
    parser.add_argument("--obs-password", default="")
    parser.add_argument("--obs-scene", default="Capture")
    parser.add_argument("--obs-source-name", default="Game Capture")
    parser.add_argument("--obs-exe-path", default=None)
    parser.add_argument(
        "--strict-video", action="store_true",
        help="Abort the session if OBS connect/start fails (default: degrade silently).",
    )

    # Output
    parser.add_argument("--output-dir", type=str, default="./output")
    parser.add_argument("--dry-run", action="store_true", help="Generate poses only, no capture")

    # Debug
    parser.add_argument(
        "--debug-scan", action="store_true",
        help="Launch game + connect driver, but skip the capture loop. "
             "Keeps process alive so the Web UI can debug the bridge scan.",
    )
    parser.add_argument(
        "--wait-attach", action="store_true",
        help="After capture completes (before teardown), wait for Enter key. "
             "Use to attach a debugger to the game or renderdoc process.",
    )

    # Logging
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    args.output_dir = Path(args.output_dir)
    args.streaming = not args.no_streaming

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    run_capture(args)


if __name__ == "__main__":
    main()
