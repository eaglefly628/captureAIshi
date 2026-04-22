"""Launch / inject / wait-for-ready helpers.

These functions take the bits of grabber state they need as explicit
arguments instead of reaching into ``self``.
"""

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from grabbers.renderdoc.paths import find_pid_by_name, find_shipping_exe, resolve_renderdoccmd

logger = logging.getLogger(__name__)


# RenderDoc ResultCode mapping for actionable error messages
_RESULT_CODES = {
    0: "Succeeded", 1: "UnknownError", 2: "InternalError",
    3: "FileNotFound", 4: "InjectionFailed", 5: "IncompatibleProcess",
    6: "NetworkIOFailed", 7: "NetworkRemoteBusy",
}


def launch_game_direct(target_exe: str, target_args: list) -> subprocess.Popen:
    """Launch the game exe directly without renderdoccmd (for inject mode).

    Used when the game crashes if launched through RenderDoc (e.g. Cyberpunk
    2.x). We just spawn the exe; the caller then polls for the PID and
    injects renderdoc.dll once the process is up.
    """
    cmd = [target_exe] + target_args
    logger.info(f"Inject mode: launching game directly: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    logger.info(
        f"Game process spawned (PID={proc.pid}). "
        f"Waiting for it to initialize before injecting..."
    )
    return proc


def inject_into_process(
    process_name: str,
    renderdoc_path: str,
    startup_timeout: float,
    inject_delay: float,
    have_direct_launch: bool,
) -> int:
    """Wait for ``process_name`` to appear, then inject renderdoc.dll.

    Used for games like Cyberpunk 2077 2.x where launching via renderdoccmd
    triggers a D3D12 device integrity check and crashes. The game must be
    launched first (either by user or ``launch_game_direct``).

    Returns the injected PID. Raises ``TimeoutError`` / ``RuntimeError`` on
    failure.
    """
    logger.info(
        f"Inject mode: waiting for '{process_name}' (timeout={startup_timeout}s). "
        f"Launch the game manually now."
    )
    poll_interval = 2.0
    elapsed = 0.0
    pid = None
    while elapsed < startup_timeout:
        pid = find_pid_by_name(process_name)
        if pid:
            logger.info(f"Found '{process_name}' (PID={pid})")
            break
        time.sleep(poll_interval)
        elapsed += poll_interval
        if int(elapsed) % 10 == 0:
            logger.info(f"Still waiting for {process_name}... ({elapsed:.0f}s)")

    if not pid:
        raise TimeoutError(
            f"Game process '{process_name}' not found within {startup_timeout}s. "
            f"Start the game manually then retry."
        )

    # For inject mode the process must have initialized D3D12 before we
    # inject -- otherwise the hook fires during device creation and we get
    # the same crash as launch mode. Wait a fixed delay when we started
    # the exe ourselves (no bridge port to probe yet).
    if have_direct_launch and inject_delay > 0:
        logger.info(f"Waiting {inject_delay:.0f}s for D3D12 device initialization before injecting...")
        time.sleep(inject_delay)

    rdoc_cmd = resolve_renderdoccmd(renderdoc_path)
    inject_cmd = [rdoc_cmd, "inject", "--PID", str(pid)]
    logger.info(f"Injecting: {' '.join(inject_cmd)}")
    result = subprocess.run(inject_cmd, capture_output=True, text=True, timeout=30)
    out = (result.stdout or result.stderr or "").strip()
    # renderdoccmd inject returns the injected PID as exit code on success,
    # so any large positive rc is success. Known error codes are 1-7.
    inject_ok = (result.returncode == pid) or (result.returncode > 100) or \
                (result.returncode == 0) or "Launched as ID" in out
    if not inject_ok:
        raise RuntimeError(
            f"renderdoccmd inject failed (rc={result.returncode}): {out}"
        )
    logger.info(f"Bridge injected into '{process_name}' (PID={pid}, rc={result.returncode})")
    return pid


def wait_for_game_ready(
    process: Optional[subprocess.Popen],
    startup_timeout: float,
    wait_for_port: Optional[int],
    target_exe: Optional[str],
) -> None:
    """Poll until game is ready or renderdoccmd exits.

    Checks every second and logs progress every 5s. If ``wait_for_port``
    is set, also probes that TCP port -- once it responds, the game's
    control channel is confirmed up.
    """
    import socket as _socket

    poll_interval = 1.0
    elapsed = 0.0
    port_ready = False

    logger.info(
        f"Waiting for game to start (timeout={startup_timeout}s"
        + (f", port={wait_for_port}" if wait_for_port else "")
        + ")..."
    )

    while elapsed < startup_timeout:
        rc = process.poll() if process is not None else None
        if rc is not None:
            # Give drain threads a moment to flush remaining output
            time.sleep(0.2)
            _report_renderdoccmd_failure(rc, elapsed, target_exe)
            code_name = _RESULT_CODES.get(rc, f"code {rc}")
            raise RuntimeError(
                f"renderdoccmd failed: {code_name} (exit code {rc}). "
                f"Cannot proceed without a running game."
            )

        if wait_for_port and not port_ready:
            try:
                with _socket.create_connection(("127.0.0.1", wait_for_port), timeout=0.3):
                    port_ready = True
                    logger.info(f"Game port {wait_for_port} is open after {elapsed:.0f}s")
                    return
            except (ConnectionRefusedError, OSError):
                pass

        time.sleep(poll_interval)
        elapsed += poll_interval
        if int(elapsed) % 5 == 0:
            logger.info(f"Still waiting for game... ({elapsed:.0f}s elapsed)")

    # Timeout reached
    if process is None or process.poll() is None:
        if wait_for_port and not port_ready:
            logger.warning(
                f"Timeout: game process alive but port {wait_for_port} "
                f"not open after {elapsed:.0f}s. Proceeding anyway."
            )
        else:
            logger.info(f"Game appears to be running after {elapsed:.0f}s")
    else:
        raise RuntimeError(
            "Game process is not running after timeout. "
            "Check renderdoccmd output above for details."
        )


def _report_renderdoccmd_failure(rc: int, elapsed: float, target_exe: Optional[str]) -> None:
    """Log actionable diagnostics for known renderdoccmd exit codes."""
    code_name = _RESULT_CODES.get(rc, f"code {rc}")
    logger.error(f"renderdoccmd exited after {elapsed:.0f}s: {code_name} ({rc})")

    if rc == 0 and elapsed < 15:
        # Exit code 0 within 15 seconds strongly suggests a UE5 launcher
        # that spawns a child process and exits.
        shipping_hint = find_shipping_exe(target_exe)
        hint_msg = ""
        if shipping_hint:
            hint_msg = (
                f"\n\n  Auto-detected real game exe:\n"
                f"    {shipping_hint}\n"
                f"  Set this as target_exe instead of the launcher."
            )
        logger.error(
            "renderdoccmd exited immediately with code 0. This usually means "
            "the target is a UE5 launcher that spawns a child process.\n"
            "  The launcher exits, but the real game keeps running.\n"
            "  Solution: point target_exe at the actual game executable\n"
            "  (typically *-Win64-Shipping.exe or *-Cmd.exe in Binaries/Win64/)."
            + hint_msg
        )
    elif rc == 4:
        logger.error(
            "InjectionFailed: RenderDoc could not inject into the process. "
            "Common causes:\n"
            "  - Architecture mismatch (32-bit renderdoccmd vs 64-bit game or vice versa)\n"
            "  - Anti-cheat or process protection blocking injection\n"
            "  - UE5 launcher exited before injection completed "
            "(try launching the actual game exe, not the launcher)"
        )
    elif rc == 3:
        logger.error(
            f"FileNotFound: RenderDoc could not find the executable: {target_exe}"
        )
    elif rc == 5:
        logger.error(
            "IncompatibleProcess: The target process architecture doesn't "
            "match renderdoccmd. Check if both are x64 or both are x86."
        )


def start_renderdoccmd_capture(
    renderdoc_path: str,
    target_exe: str,
    target_args: list,
    capture_dir: Path,
) -> tuple:
    """Launch ``renderdoccmd capture`` against ``target_exe`` with drain threads.

    Returns ``(process, stdout_lines, stderr_lines)``. The drain threads
    pump both pipes into their line lists and into ``logger.info`` so the
    UI sees renderdoccmd output in real time.
    """
    rdoc_cmd = resolve_renderdoccmd(renderdoc_path)
    logger.info(f"Launching {target_exe} via RenderDoc ({rdoc_cmd})...")
    # renderdoccmd syntax: capture [--opts] <exe> [game args]
    # All --opt flags must come BEFORE the executable path.
    cmd = [
        rdoc_cmd, "capture",
        "--opt-hook-children",
        "--capture-file", str(capture_dir / "frame"),
        "--wait-for-exit",
        target_exe,
    ] + target_args
    logger.info(f"renderdoccmd command: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Drain stdout/stderr in background threads to prevent pipe deadlock
    # (renderdoccmd with --wait-for-exit stays alive for the game's lifetime).
    stdout_lines: list = []
    stderr_lines: list = []
    import threading

    def _drain(stream, sink, label):
        for raw_line in stream:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                sink.append(line)
                logger.info(f"[renderdoccmd {label}] {line}")

    threading.Thread(target=_drain, args=(process.stdout, stdout_lines, "out"), daemon=True).start()
    threading.Thread(target=_drain, args=(process.stderr, stderr_lines, "err"), daemon=True).start()
    return process, stdout_lines, stderr_lines


def kill_renderdoccmd_tree(process: subprocess.Popen) -> None:
    """Kill the renderdoccmd process and its entire child tree."""
    try:
        if sys.platform == "win32":
            # terminate() only kills renderdoccmd, not its child game process.
            # Use taskkill /T to kill the whole tree.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True, timeout=10,
            )
        else:
            import os
            import signal
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception as e:
        logger.warning(f"[TEARDOWN] Process tree kill failed, trying terminate: {e}")
        try:
            process.terminate()
        except Exception:
            pass

    try:
        process.wait(timeout=5)
        logger.info("[TEARDOWN] renderdoccmd process exited")
    except Exception:
        logger.warning("[TEARDOWN] renderdoccmd did not exit in 5s, killing")
        try:
            process.kill()
        except Exception:
            pass
