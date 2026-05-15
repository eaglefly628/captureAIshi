"""OBS Studio video recorder driven via OBS WebSocket v5 (port 4455 default).

Lifecycle:
    ctx.__enter__   ->  optional spawn obs64.exe; poll TCP until reachable;
                        ReqClient.connect; SetCurrentProgramScene;
                        SetRecordDirectory.
    ctx.start       ->  StartRecord (after FilenameFormatting set to session).
    ctx.stop        ->  StopRecord; rename output to <session>/video.mp4;
                        write video_metadata.json with pose timestamps.
    ctx.__exit__    ->  disconnect; terminate spawned obs64.exe.

Failure policy: when ``strict`` is False, a connect/start failure is logged
and the recorder degrades to a no-op (``is_recording == False``); the wider
capture session is unaffected.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class OBSRecorder:
    """OBS WebSocket v5 client wrapping start/stop record + metadata write."""

    def __init__(
        self,
        output_dir: Path,
        host: str = "127.0.0.1",
        port: int = 4455,
        password: str = "",
        scene: str = "Capture",
        source_name: str = "Game Capture",
        bitrate_kbps: int = 50000,
        framerate: float = 60.0,
        auto_launch_obs: bool = True,
        obs_exe_path: Optional[str] = None,
        target_exe: Optional[str] = None,
        strict: bool = False,
        connect_timeout_seconds: float = 30.0,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.host = host
        self.port = int(port)
        self.password = password
        self.scene = scene
        self.source_name = source_name
        self.bitrate_kbps = int(bitrate_kbps)
        self.framerate = float(framerate)
        self.auto_launch_obs = bool(auto_launch_obs)
        self.obs_exe_path = obs_exe_path
        self.target_exe = target_exe
        self.strict = bool(strict)
        self.connect_timeout_seconds = float(connect_timeout_seconds)

        self._client = None  # obsws_python.ReqClient
        self._spawned_obs: Optional[subprocess.Popen] = None
        self._recording = False
        self._t0_monotonic: Optional[float] = None
        self._started_at_iso: Optional[str] = None
        self._session_name: Optional[str] = None
        self._obs_version: Optional[str] = None
        self._rpc_version: int = 1
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._recording

    def get_status(self) -> dict:
        elapsed = 0.0
        if self._recording and self._t0_monotonic is not None:
            elapsed = time.monotonic() - self._t0_monotonic
        return {
            "recording": self._recording,
            "elapsed_seconds": round(elapsed, 1),
            "obs_version": self._obs_version,
        }

    def __enter__(self) -> "OBSRecorder":
        try:
            self._connect_or_launch()
        except Exception as e:
            self._handle_failure(f"OBS connect failed: {e}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._recording:
            try:
                self.stop()
            except Exception as e:
                logger.warning(f"[VIDEO] stop() during __exit__ failed: {e}")
        self._heartbeat_stop.set()
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception as e:
                logger.debug(f"[VIDEO] disconnect: {e}")
            self._client = None
        if self._spawned_obs is not None:
            self._terminate_spawned_obs()
        return False

    def start(self, session_name: str) -> None:
        if self._recording:
            logger.debug("[VIDEO] start() called while already recording")
            return
        if self._client is None:
            logger.info("[VIDEO] no OBS client; recording skipped")
            return
        self._session_name = session_name
        try:
            self._configure_recording_target()
            self._client.start_record()
            self._t0_monotonic = time.monotonic()
            self._started_at_iso = datetime.now(timezone.utc).isoformat()
            self._recording = True
            try:
                from web import state as web_state
                web_state.reset_pose_timestamps()
                web_state.set_recorder_t0(self._t0_monotonic)
            except Exception as e:
                logger.debug(f"[VIDEO] publish t0 to web.state: {e}")
            logger.info(f"[VIDEO] Recording started (scene={self.scene})")
            self._start_heartbeat()
        except Exception as e:
            self._handle_failure(f"OBS StartRecord failed: {e}")

    def stop(self) -> Optional[Path]:
        if not self._recording:
            return None
        self._heartbeat_stop.set()
        output_path: Optional[Path] = None
        try:
            resp = self._client.stop_record()
            output_path = self._resolve_output_path(resp)
        except Exception as e:
            logger.warning(f"[VIDEO] StopRecord failed: {e}")
        finally:
            self._recording = False
            try:
                from web import state as web_state
                web_state.clear_recorder_t0()
            except Exception:
                pass

        elapsed = (time.monotonic() - self._t0_monotonic) if self._t0_monotonic else 0.0

        canonical: Optional[Path] = None
        if output_path is not None:
            canonical = self.output_dir / "video.mp4"
            try:
                if output_path.resolve() != canonical.resolve():
                    if canonical.exists():
                        canonical.unlink()
                    shutil.move(str(output_path), str(canonical))
            except Exception as e:
                logger.warning(f"[VIDEO] rename {output_path} -> {canonical}: {e}")
                canonical = output_path

        self._write_metadata(canonical, elapsed)
        logger.info(
            f"[VIDEO] Recording stopped after {elapsed:.1f}s -> "
            f"{canonical.name if canonical else '(no file)'}"
        )
        return canonical

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _connect_or_launch(self) -> None:
        if self.auto_launch_obs and not self._port_open():
            self._spawn_obs()
            self._wait_for_port()
        elif not self._port_open():
            raise RuntimeError(
                f"OBS WebSocket not reachable at {self.host}:{self.port} "
                f"(auto_launch_obs disabled). Start OBS Studio manually."
            )

        try:
            import obsws_python as obsws  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "obsws-python not installed. Run: pip install obsws-python"
            ) from e

        self._client = obsws.ReqClient(
            host=self.host,
            port=self.port,
            password=self.password or "",
            timeout=10,
        )

        version = self._client.get_version()
        self._obs_version = getattr(version, "obs_version", None)
        rpc = getattr(version, "rpc_version", 1)
        try:
            self._rpc_version = int(rpc)
        except (TypeError, ValueError):
            self._rpc_version = 1
        logger.info(
            f"[VIDEO] Connected to OBS {self._obs_version} "
            f"(rpc v{self._rpc_version})"
        )

        try:
            self._client.set_current_program_scene(self.scene)
        except Exception as e:
            try:
                scenes_resp = self._client.get_scene_list()
                available = [s.get("sceneName", "") for s in getattr(scenes_resp, "scenes", [])]
            except Exception:
                available = []
            logger.warning(
                f"[VIDEO] could not set scene '{self.scene}': {e}. "
                f"Available scenes: {available}. Update the Scene field in OBS Settings."
            )

        try:
            self._client.set_record_directory(str(self.output_dir.resolve()))
        except Exception as e:
            logger.warning(f"[VIDEO] set_record_directory: {e}")

    def _configure_recording_target(self) -> None:
        if self._client is None:
            return
        if self._session_name:
            try:
                self._client.set_profile_parameter(
                    "Output", "FilenameFormatting", self._session_name
                )
            except Exception as e:
                logger.debug(f"[VIDEO] set FilenameFormatting: {e}")
        if self.target_exe:
            try:
                self._client.set_input_settings(
                    name=self.source_name,
                    settings={
                        "capture_mode": "window",
                        "priority": 1,
                        "executable": Path(self.target_exe).name,
                    },
                    overlay=True,
                )
            except Exception as e:
                logger.debug(f"[VIDEO] set_input_settings: {e}")

    def _resolve_output_path(self, resp) -> Optional[Path]:
        for attr in ("output_path", "outputPath"):
            val = getattr(resp, attr, None)
            if val:
                return Path(val)
        candidates = sorted(
            self.output_dir.glob("*.mp4"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates += sorted(
            self.output_dir.glob("*.mkv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _write_metadata(self, video_path: Optional[Path], duration_seconds: float) -> None:
        try:
            from web import state as web_state
            pose_timestamps = web_state.drain_pose_timestamps()
        except Exception:
            pose_timestamps = []

        metadata = {
            "schema_version": 1,
            "video_file": video_path.name if video_path else None,
            "started_at_iso": self._started_at_iso,
            "stopped_at_iso": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration_seconds, 3),
            "framerate": self.framerate,
            "resolution": None,
            "codec": "h264",
            "bitrate_kbps": self.bitrate_kbps,
            "obs_version": self._obs_version,
            "obs_scene": self.scene,
            "trajectory_alignment": {
                "method": "wall_clock",
                "session_start_offset_seconds": 0.0,
                "pose_timestamps_seconds": pose_timestamps,
            },
        }

        if self._client is not None:
            try:
                vs = self._client.get_video_settings()
                width = getattr(vs, "output_width", None) or getattr(vs, "base_width", None)
                height = getattr(vs, "output_height", None) or getattr(vs, "base_height", None)
                if width and height:
                    metadata["resolution"] = {"width": int(width), "height": int(height)}
                fps_num = getattr(vs, "fps_numerator", None)
                fps_den = getattr(vs, "fps_denominator", None) or 1
                if fps_num:
                    metadata["framerate"] = round(float(fps_num) / float(fps_den), 3)
            except Exception as e:
                logger.debug(f"[VIDEO] get_video_settings: {e}")

        target = self.output_dir / "video_metadata.json"
        try:
            target.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning(f"[VIDEO] write {target}: {e}")

    def _start_heartbeat(self) -> None:
        self._heartbeat_stop = threading.Event()

        def _loop():
            while not self._heartbeat_stop.wait(2.0):
                if not self._recording or self._t0_monotonic is None:
                    return
                elapsed = time.monotonic() - self._t0_monotonic
                mm, ss = divmod(int(elapsed), 60)
                logger.debug(f"[VIDEO] Recording {mm:02d}:{ss:02d}")

        self._heartbeat_thread = threading.Thread(
            target=_loop, name="OBSRecorder-Heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    def _port_open(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=0.5):
                return True
        except OSError:
            return False

    def _wait_for_port(self) -> None:
        deadline = time.monotonic() + self.connect_timeout_seconds
        last_err: Optional[str] = None
        while time.monotonic() < deadline:
            if self._port_open():
                return
            try:
                if self._spawned_obs and self._spawned_obs.poll() is not None:
                    last_err = (
                        f"obs64.exe exited with code {self._spawned_obs.returncode}"
                    )
                    break
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError(
            f"OBS WebSocket not reachable at {self.host}:{self.port} "
            f"within {self.connect_timeout_seconds:.0f}s"
            + (f" ({last_err})" if last_err else "")
        )

    def _spawn_obs(self) -> None:
        exe = self._resolve_obs_exe()
        if exe is None:
            raise RuntimeError(
                "obs64.exe not found. Run scripts/setup_obs.py to install OBS, "
                "or set obs_exe_path in configs/obs.json."
            )
        cwd = exe.parent
        cmd = [
            str(exe),
            "--minimize-to-tray",
            "--disable-shutdown-check",
            "--startreplaybuffer",
        ]
        kwargs = {"cwd": str(cwd)}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
        logger.info(f"[VIDEO] launching OBS: {exe}")
        self._spawned_obs = subprocess.Popen(cmd, **kwargs)

    def _terminate_spawned_obs(self) -> None:
        if self._spawned_obs is None:
            return
        try:
            if self._spawned_obs.poll() is None:
                self._spawned_obs.terminate()
                try:
                    self._spawned_obs.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._spawned_obs.kill()
            logger.info("[VIDEO] OBS process terminated")
        except Exception as e:
            logger.debug(f"[VIDEO] terminate spawned obs: {e}")
        finally:
            self._spawned_obs = None

    def _resolve_obs_exe(self) -> Optional[Path]:
        if self.obs_exe_path:
            p = Path(self.obs_exe_path)
            if p.is_file():
                return p
            logger.warning(f"[VIDEO] configured obs_exe_path not found: {p}")
        repo_root = Path(__file__).resolve().parent.parent
        candidates = [
            repo_root / "3rdparty" / "obs-studio" / "bin" / "64bit" / "obs64.exe",
        ]
        if sys.platform == "win32":
            for env_key in ("ProgramFiles", "ProgramW6432"):
                base = os.environ.get(env_key)
                if base:
                    candidates.append(Path(base) / "obs-studio" / "bin" / "64bit" / "obs64.exe")
        for c in candidates:
            if c.is_file():
                return c
        return None

    def _handle_failure(self, message: str) -> None:
        if self.strict:
            raise RuntimeError(message)
        logger.warning(f"[VIDEO] {message} -- continuing without video")
        self._recording = False
        self._client = None
