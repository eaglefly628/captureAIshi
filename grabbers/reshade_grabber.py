"""ReShade-based frame grabber (Path B injection vehicle).

Consumes the BMP/PNG + EXR triplets written by captureAIshi_bridge.addon
(embedded frame_capture subsystem) when the game runs under the dxgi.dll
proxy. The addon is timer-driven: it writes a new triplet every ~33ms
(configurable via FC_TargetFPS in unicap.ini). This grabber polls the
output directory for the latest triplet that postdates the previous capture
and returns its arrays.

For trajectory capture where the camera holds still ~33ms+ at each pose
this is sufficient; precise per-pose capture is a Phase 2 addition (would
add an `__fc_capture_now` TCP command on the bridge channel).

Output filename convention from frame_capture.cpp:
  <exe_basename> YYYY-MM-DD HH-MM-SS mmm BackBuffer.{bmp,png}
  <exe_basename> YYYY-MM-DD HH-MM-SS mmm DepthBuffer.exr
  <exe_basename> YYYY-MM-DD HH-MM-SS mmm NormalBuffer.exr  (only when FC_ExportNormal=1)

The "<exe_basename> <ts> " prefix groups a triplet -- we match by prefix.

Concurrency note: the addon writes color, depth, and normal from separate
worker threads with no atomic-rename, so a triplet can be partially on disk
when we discover it. `_wait_quiescent()` re-stat()s all three files until
their sizes are stable across two consecutive samples before we read them.
"""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from grabbers.base import FrameData, FrameGrabber

logger = logging.getLogger(__name__)


class ReShadeGrabber(FrameGrabber):
    """Grab frames produced by the ReShade addon (Path B vehicle).

    Args:
        output_dir: directory the addon writes frames into (must match the
            path written by setup() into <game_dir>/fc_output_dir.txt).
        game_dir: directory containing the game exe and the deployed
            captureAIshi_bridge.addon + dxgi.dll proxy. Used for the
            sidecar protocol (fc_output_dir.txt etc.).
        bridge_port: if set, setup() polls this TCP port until the bridge
            is reachable before returning -- the readiness gate analogue
            of RenderDocGrabber.wait_for_port. Set to None to skip.
        bridge_host: host for the readiness check. Default 127.0.0.1.
        readiness_timeout_s: max time to wait for the bridge port.
        poll_timeout_s: how long capture_frame() waits for a new triplet
            before giving up. Default 5s.
        poll_interval_s: directory poll interval. Default 50ms (~20Hz).
        quiescence_samples: how many consecutive identical-size samples
            confirm a file is fully written. 2 is the minimum useful value.
    """

    _COLOR_SUFFIXES = (" BackBuffer.png", " BackBuffer.bmp")
    _DEPTH_SUFFIX   = " DepthBuffer.exr"
    _NORMAL_SUFFIX  = " NormalBuffer.exr"

    def __init__(
        self,
        output_dir: str | Path,
        game_dir: str | Path,
        *,
        target_exe: Optional[str] = None,
        target_args: Optional[list] = None,
        auto_launch: bool = True,
        bridge_port: Optional[int] = 9998,
        bridge_host: str = "127.0.0.1",
        readiness_timeout_s: float = 60.0,
        poll_timeout_s: float = 5.0,
        poll_interval_s: float = 0.05,
        quiescence_samples: int = 2,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.game_dir = Path(game_dir)
        self.target_exe = target_exe
        self.target_args = list(target_args or [])
        self.auto_launch = bool(auto_launch and target_exe)
        self.bridge_port = bridge_port
        self.bridge_host = bridge_host
        self.readiness_timeout_s = readiness_timeout_s
        self.poll_timeout_s = poll_timeout_s
        self.poll_interval_s = poll_interval_s
        self.quiescence_samples = max(2, int(quiescence_samples))
        self._last_prefix: Optional[str] = None
        self._last_paths: Dict[str, Path] = {}
        self._game_proc = None  # type: ignore  # subprocess.Popen

    # ── lifecycle ─────────────────────────────────────────────────────

    def setup(self) -> None:
        """Prepare the addon to write into our output dir, gate on readiness.

        Does NOT deploy binaries (caller is expected to have run
        scripts/deploy_reshade.py). Phase 1 keeps deployment as a separate
        explicit step.
        """
        if not self.game_dir.exists():
            raise FileNotFoundError(
                f"[ReShadeGrabber] game_dir not found: {self.game_dir}")

        self._auto_deploy()

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Sidecar: tell the addon where to write frames.
        sidecar = self.game_dir / "fc_output_dir.txt"
        if sidecar.exists():
            existing = sidecar.read_text(encoding="utf-8", errors="replace").strip()
            if existing != str(self.output_dir.resolve()):
                logger.warning(
                    "[ReShadeGrabber] sidecar %s already targets %r; "
                    "overwriting to %r. Another grabber instance may be "
                    "running against the same game directory.",
                    sidecar, existing, str(self.output_dir.resolve()))
        sidecar.write_text(str(self.output_dir.resolve()), encoding="utf-8")
        logger.info(
            "[ReShadeGrabber] sidecar -> %s (output_dir=%s)",
            sidecar, self.output_dir)

        # Latch baseline so capture_frame() ignores any pre-existing files.
        self._last_prefix = self._latest_prefix()
        logger.info(
            "[ReShadeGrabber] baseline prefix=%r", self._last_prefix)

        # Launch the game (auto_launch flag mirrors RenderDocGrabber). The
        # game's LoadLibrary("dxgi.dll") triggers ReShade init, which calls
        # bridge_start() and opens TCP 9998. Without this, the readiness
        # gate just times out.
        if self.auto_launch:
            self._launch_game()

        # Readiness gate: wait for bridge TCP server, mirroring the
        # RenderDocGrabber wait_for_port behaviour.
        if self.bridge_port:
            self._wait_for_bridge()

    def _launch_game(self) -> None:
        if not self.target_exe:
            return
        exe = Path(self.target_exe)
        if not exe.exists():
            logger.error("[ReShadeGrabber] target_exe not found: %s", exe)
            return
        cmd = [str(exe), *self.target_args]
        logger.info("[ReShadeGrabber] launching game: %s (cwd=%s)", cmd, self.game_dir)
        try:
            self._game_proc = subprocess.Popen(
                cmd,
                cwd=str(self.game_dir),
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            logger.info("[ReShadeGrabber] game launched, pid=%d", self._game_proc.pid)
        except OSError as exc:
            logger.error("[ReShadeGrabber] game launch failed: %s", exc)
            self._game_proc = None

    def teardown(self) -> None:
        # Terminate the game we launched (best-effort; if user closed it
        # already poll() returns non-None and we skip).
        if self._game_proc is not None and self._game_proc.poll() is None:
            try:
                logger.info("[ReShadeGrabber] terminating game pid=%d",
                            self._game_proc.pid)
                self._game_proc.terminate()
                try:
                    self._game_proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._game_proc.kill()
            except OSError as exc:
                logger.warning("[ReShadeGrabber] terminate failed: %s", exc)

        sidecar = self.game_dir / "fc_output_dir.txt"
        try:
            if sidecar.exists():
                sidecar.unlink()
                logger.info("[ReShadeGrabber] removed sidecar %s", sidecar)
        except OSError as exc:
            logger.warning("[ReShadeGrabber] sidecar cleanup: %s", exc)

    # ── capture ────────────────────────────────────────────────────────

    def capture_frame(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        data = self.capture_frame_ex()
        return data.rgb, data.depth

    def capture_frame_ex(self) -> FrameData:
        deadline = time.monotonic() + self.poll_timeout_s
        prefix: Optional[str] = None
        while time.monotonic() < deadline:
            prefix = self._latest_prefix()
            if prefix and prefix != self._last_prefix:
                break
            time.sleep(self.poll_interval_s)
        else:
            logger.warning(
                "[ReShadeGrabber] no new frame within %.1fs (last=%r)",
                self.poll_timeout_s, self._last_prefix)
            return FrameData()

        # P0 fix: triplet may still be writing. Wait for sizes to stop
        # changing across consecutive samples on all candidate files.
        candidate_paths = self._candidate_paths(prefix)
        if not self._wait_quiescent(candidate_paths, deadline):
            logger.warning(
                "[ReShadeGrabber] triplet %r never quiesced before deadline",
                prefix)
            return FrameData()

        self._last_prefix = prefix
        return self._load_triplet(prefix)

    def save_frame(
        self,
        rgb: Optional[np.ndarray],
        depth: Optional[np.ndarray],
        output_dir: Path,
        frame_idx: int,
        *,
        base_name: str = "",
        normal: Optional[np.ndarray] = None,
    ) -> Dict[str, str]:
        """Override base.save_frame to copy addon-produced files instead of
        re-encoding the in-memory arrays we just decoded.

        The addon already wrote BMP/PNG + EXR to disk; re-encoding them via
        PIL would be a wasted round-trip and lose float depth precision.
        We copy the original files into the requested output_dir under the
        caller's base_name, falling back to base.save_frame() if for some
        reason _last_paths is empty (e.g. arrays were synthesised in tests).
        """
        if not self._last_paths:
            return super().save_frame(
                rgb, depth, output_dir, frame_idx,
                base_name=base_name, normal=normal,
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        if base_name:
            stem_rgb = base_name
            stem_depth = f"{base_name}_d"
            stem_normal = f"{base_name}_n"
        else:
            stem_rgb = f"rgb_{frame_idx:06d}"
            stem_depth = f"depth_{frame_idx:06d}"
            stem_normal = f"normal_{frame_idx:06d}"

        saved: Dict[str, str] = {}
        for kind, stem in (
            ("rgb", stem_rgb), ("depth", stem_depth), ("normal", stem_normal),
        ):
            src = self._last_paths.get(kind)
            if src is None or not src.exists():
                continue
            dst = output_dir / f"{stem}{src.suffix}"
            shutil.copy2(src, dst)
            saved[kind] = dst.name
            logger.debug(
                "[ReShadeGrabber.save_frame] copy %s -> %s", src, dst)
        return saved

    # ── internals ──────────────────────────────────────────────────────

    def _auto_deploy(self) -> None:
        """Ensure dxgi.dll + shaders are present in game_dir; copy from
        the repo build outputs if missing. Idempotent."""
        repo_root   = Path(__file__).resolve().parent.parent
        bin_root    = repo_root / "3rdparty" / "reshade" / "bin"
        # ReShade.sln's $(Platform) is "64-bit" (literal name, not "x64").
        # MSBuild expanded $(SolutionDir)bin\$(Platform)\Release lands the
        # DLL at bin/64-bit/Release/. Try the canonical "x64" first in case
        # someone used a different platform, then fall back. Also accept
        # the .sln-platform "Release" without architecture subdir.
        reshade_dll = None
        for candidate in [
            bin_root / "x64"     / "Release" / "ReShade64.dll",
            bin_root / "64-bit"  / "Release" / "ReShade64.dll",
            bin_root / "x64"     / "Release" / "dxgi.dll",
            bin_root / "Release" / "ReShade64.dll",
        ]:
            if candidate.exists():
                reshade_dll = candidate
                break
        if reshade_dll is None:
            # Last resort: recursive search under bin/
            try:
                hits = list(bin_root.rglob("ReShade64.dll"))
                if hits:
                    reshade_dll = hits[0]
            except OSError:
                pass
        addon_dll   = repo_root / "3rdparty" / "reshade_bridge" / "captureAIshi_bridge.addon"
        shaders_src = repo_root / "3rdparty" / "reshade_bridge" / "shaders"

        dxgi_dst    = self.game_dir / "dxgi.dll"
        addon_dst   = self.game_dir / "captureAIshi_bridge.addon"
        shaders_dst = self.game_dir / "captureAIshi-shaders" / "Shaders"

        # 1. dxgi.dll
        if not dxgi_dst.exists():
            if reshade_dll is None:
                logger.error("[ReShadeGrabber] cannot auto-deploy: ReShade64.dll not "
                             "found under %s. Build it via msbuild 3rdparty\\reshade\\"
                             "ReShade.sln /p:Configuration=Release /p:Platform=\"64-bit\".",
                             bin_root)
            else:
                shutil.copy2(reshade_dll, dxgi_dst)
                logger.info("[ReShadeGrabber] deployed %s -> %s",
                            reshade_dll, dxgi_dst)
        else:
            logger.info("[ReShadeGrabber] %s already present, skipping copy", dxgi_dst)

        # 2. standalone-addon optional copy
        if addon_dll.exists() and not addon_dst.exists():
            shutil.copy2(addon_dll, addon_dst)
            logger.info("[ReShadeGrabber] deployed %s -> %s", addon_dll.name, addon_dst)

        # 3. shaders
        if shaders_src.exists():
            shaders_dst.mkdir(parents=True, exist_ok=True)
            copied = 0
            for fx in shaders_src.glob("*.fx*"):
                dst = shaders_dst / fx.name
                if not dst.exists() or dst.stat().st_size != fx.stat().st_size:
                    shutil.copy2(fx, dst)
                    copied += 1
            if copied:
                logger.info("[ReShadeGrabber] deployed %d shader file(s) -> %s",
                            copied, shaders_dst)

    def _wait_for_bridge(self) -> None:
        deadline = time.monotonic() + self.readiness_timeout_s
        attempts = 0
        while time.monotonic() < deadline:
            attempts += 1
            try:
                with socket.create_connection(
                    (self.bridge_host, self.bridge_port), timeout=1.0,
                ):
                    logger.info(
                        "[ReShadeGrabber] bridge reachable at %s:%d after "
                        "%d attempts", self.bridge_host, self.bridge_port,
                        attempts)
                    return
            except (OSError, socket.timeout):
                time.sleep(self.poll_interval_s * 4)
        logger.warning(
            "[ReShadeGrabber] bridge port %s:%d not reachable within "
            "%.1fs (%d attempts) -- continuing; driver connect may fail",
            self.bridge_host, self.bridge_port,
            self.readiness_timeout_s, attempts)

    def _latest_prefix(self) -> Optional[str]:
        """Return the prefix of the most recent triplet (newest color file).

        Prefix = filename minus the color suffix; depth/normal share it.
        """
        if not self.output_dir.exists():
            return None
        newest_mtime = -1.0
        newest_prefix: Optional[str] = None
        for p in self.output_dir.iterdir():
            if not p.is_file():
                continue
            name = p.name
            for suf in self._COLOR_SUFFIXES:
                if name.endswith(suf):
                    try:
                        mtime = p.stat().st_mtime
                    except OSError:
                        break
                    if mtime > newest_mtime:
                        newest_mtime = mtime
                        newest_prefix = name[: -len(suf)]
                    break
        return newest_prefix

    def _candidate_paths(self, prefix: str) -> Dict[str, Path]:
        """All addon-output files that could exist for this prefix.

        Color is always present; depth/normal are conditional on
        FC_ExportDepth / FC_ExportNormal at the addon side.
        """
        paths: Dict[str, Path] = {}
        for suf in self._COLOR_SUFFIXES:
            p = self.output_dir / f"{prefix}{suf}"
            if p.exists():
                paths["rgb"] = p
                break
        depth = self.output_dir / f"{prefix}{self._DEPTH_SUFFIX}"
        if depth.exists():
            paths["depth"] = depth
        normal = self.output_dir / f"{prefix}{self._NORMAL_SUFFIX}"
        if normal.exists():
            paths["normal"] = normal
        return paths

    def _wait_quiescent(self, paths: Dict[str, Path], deadline: float) -> bool:
        """Block until every path's size is stable for `quiescence_samples`
        consecutive samples, OR `deadline` (monotonic seconds) hits.

        Returns True if all paths quiesced; False on timeout.
        """
        if not paths:
            return True
        prev_sizes: Dict[Path, int] = {}
        stable_count = 0
        while time.monotonic() < deadline:
            try:
                cur_sizes = {p: p.stat().st_size for p in paths.values()}
            except OSError:
                # File could have been re-created mid-sample; reset.
                stable_count = 0
                prev_sizes = {}
                time.sleep(self.poll_interval_s)
                continue
            if cur_sizes == prev_sizes and all(s > 0 for s in cur_sizes.values()):
                stable_count += 1
                if stable_count >= self.quiescence_samples - 1:
                    return True
            else:
                stable_count = 0
                prev_sizes = cur_sizes
            time.sleep(self.poll_interval_s)
        return False

    def _load_triplet(self, prefix: str) -> FrameData:
        paths = self._candidate_paths(prefix)
        self._last_paths = paths
        rgb = self._load_color(paths.get("rgb")) if paths.get("rgb") else None
        depth = self._load_exr(paths.get("depth")) if paths.get("depth") else None
        normal = self._load_exr(paths.get("normal")) if paths.get("normal") else None
        return FrameData(rgb=rgb, depth=depth, normal=normal)

    def _load_color(self, path: Path) -> Optional[np.ndarray]:
        from PIL import Image
        try:
            img = Image.open(path).convert("RGB")
        except OSError as exc:
            logger.warning("[ReShadeGrabber] color load failed (%s): %s", path, exc)
            return None
        return np.asarray(img)

    def _load_exr(self, path: Path) -> Optional[np.ndarray]:
        try:
            import cv2
        except ImportError:
            logger.warning(
                "[ReShadeGrabber] cv2 not installed; cannot load %s", path)
            return None
        # OpenCV needs IMREAD_UNCHANGED to keep float EXR intact.
        arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if arr is None:
            logger.warning("[ReShadeGrabber] cv2 failed to load %s", path)
            return None
        # tinyexr writes BGR -> swap to RGB for normal; depth is single-channel.
        if arr.ndim == 3 and arr.shape[2] >= 3:
            arr = arr[..., ::-1]
        return arr
