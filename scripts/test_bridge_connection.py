#!/usr/bin/env python3
"""Diagnostic script for testing captureAIshi bridge connection.

Run this AFTER launching a game through renderdoccmd to verify:
  1. TCP connectivity to bridge server
  2. GEngine auto-scan status
  3. Console command execution (ToggleDebugCamera, SetViewLocation, etc.)
  4. Camera path system readiness

Usage:
    python scripts/test_bridge_connection.py [--host 127.0.0.1] [--port 9998]

Exit codes:
    0  All checks passed
    1  Connection failed (bridge not running or wrong port)
    2  GEngine not found (scan failed, need manual offset)
    3  Console commands not working (Exec vtable probe failed)
"""

import argparse
import socket
import sys
import time


class BridgeDiag:
    """Minimal TCP client for bridge diagnostics."""

    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None

    def connect(self) -> bool:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        try:
            self._sock.connect((self.host, self.port))
            return True
        except ConnectionRefusedError:
            return False
        except socket.timeout:
            return False
        except OSError as e:
            print(f"  Socket error: {e}")
            return False

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send_cmd(self, cmd: str, timeout: float = 3.0) -> str:
        """Send a command and return the response line."""
        msg = (cmd + "\n").encode("utf-8")
        self._sock.sendall(msg)
        self._sock.settimeout(timeout)
        try:
            data = self._sock.recv(4096)
            return data.decode("utf-8", errors="replace").strip()
        except socket.timeout:
            return "(timeout)"


def main():
    parser = argparse.ArgumentParser(description="captureAIshi bridge diagnostic")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9998)
    parser.add_argument("--skip-camera", action="store_true",
                        help="Skip camera movement tests (non-destructive only)")
    args = parser.parse_args()

    print(f"=== captureAIshi bridge diagnostic ===")
    print(f"Target: {args.host}:{args.port}")
    print()

    diag = BridgeDiag(args.host, args.port)

    # ── Step 1: TCP Connection ───────────────────────────────────
    print("[1/6] TCP connection...")
    if not diag.connect():
        print(f"  FAIL: Cannot connect to {args.host}:{args.port}")
        print()
        print("Troubleshooting:")
        print("  - Is the game launched via renderdoccmd?")
        print("  - Is renderdoc.dll the custom build with bridge?")
        print("  - Check: netstat -an | findstr 9998")
        print("  - Try setting CAPTUREAI_BRIDGE_PORT env var before launch")
        return 1
    print("  OK: Connected")

    # ── Step 2: Ping ─────────────────────────────────────────────
    print("[2/6] Ping...")
    resp = diag.send_cmd("__bridge_ping")
    if resp == "pong":
        print("  OK: pong received")
    else:
        print(f"  WARN: Expected 'pong', got '{resp}'")
        print("  (May be connecting to a different service on this port)")

    # ── Step 3: Bridge Status ────────────────────────────────────
    print("[3/6] Bridge status...")
    resp = diag.send_cmd("__bridge_status")
    print(f"  Raw: {resp}")

    status = {}
    for pair in resp.split():
        if "=" in pair:
            k, v = pair.split("=", 1)
            status[k] = v

    engine_found = status.get("engine_found", "0") == "1"
    exec_fn = status.get("exec_fn", "0x0")
    embedded = status.get("embedded", "0") == "1"

    print(f"  Engine found: {'YES' if engine_found else 'NO'}")
    print(f"  Exec function: {exec_fn}")
    print(f"  Embedded mode: {'YES' if embedded else 'NO'}")

    if not engine_found:
        print()
        print("  GEngine NOT found. Options:")
        print("    a) Wait longer (game may still be loading)")
        print("    b) Send: __bridge_rescan")
        print("    c) Find offset manually with Cheat Engine, then:")
        print("       __bridge_set_offset <hex>")
        print("    d) Set CAPTUREAI_GENGINE_OFFSET=<hex> before launch")
        print()

        # Try a rescan
        print("  Attempting rescan...")
        resp = diag.send_cmd("__bridge_rescan", timeout=10.0)
        if resp == "ok":
            print("  Rescan succeeded! GEngine found.")
            engine_found = True
        else:
            print(f"  Rescan result: {resp}")
            print("  FAIL: GEngine not found. Cannot proceed with command tests.")
            diag.close()
            return 2

    # ── Step 4: Console Command Test ─────────────────────────────
    print("[4/6] Console command execution (safe test: 'stat none')...")
    # stat none is a no-op that disables stat overlays
    resp = diag.send_cmd("stat none", timeout=5.0)
    # Bridge doesn't reply for passthrough commands, so a timeout is expected
    if resp == "(timeout)":
        print("  OK: Command sent (no reply expected for passthrough commands)")
        # Verify by checking status again - exec_fn should now be cached
        resp2 = diag.send_cmd("__bridge_status")
        for pair in resp2.split():
            if pair.startswith("exec_fn="):
                new_exec = pair.split("=", 1)[1]
                if new_exec != "0x0" and new_exec != "(nil)":
                    print(f"  OK: Exec function cached at {new_exec}")
                else:
                    print("  WARN: Exec function still NULL after command")
                    print("  Console commands may not work. Vtable probe may have failed.")
                    diag.close()
                    return 3
    else:
        print(f"  Response: {resp}")

    # ── Step 5: Camera Test (optional) ───────────────────────────
    if args.skip_camera:
        print("[5/6] Camera test... SKIPPED (--skip-camera)")
    else:
        print("[5/6] Camera test (ToggleDebugCamera)...")
        resp = diag.send_cmd("__cam_toggle")
        if resp == "ok":
            print("  OK: Debug camera toggled")
            time.sleep(0.5)
            # Toggle back
            diag.send_cmd("__cam_toggle")
            print("  OK: Toggled back to normal camera")
        else:
            print(f"  Response: {resp}")
            print("  WARN: ToggleDebugCamera may be disabled in this build")

    # ── Step 6: Camera Path System ───────────────────────────────
    print("[6/6] Camera path system...")
    resp = diag.send_cmd("__path_info")
    print(f"  Path info: {resp}")

    # ── Summary ──────────────────────────────────────────────────
    print()
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"  TCP connection:    OK")
    print(f"  Bridge embedded:   {'YES' if embedded else 'UNKNOWN'}")
    print(f"  GEngine found:     {'YES' if engine_found else 'NO'}")
    print(f"  Exec function:     {exec_fn}")
    print(f"  Ready for capture: {'YES' if engine_found else 'NO'}")
    print()

    if engine_found:
        print("Next steps:")
        print(f"  python main.py --driver ue5 --driver-port {args.port} \\")
        print(f"    --grabber renderdoc --target-exe <game.exe> \\")
        print(f"    --volume-min -10 0 -10 --volume-max 10 5 10")
    else:
        print("Fix GEngine detection before proceeding with capture.")

    diag.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
