"""Deploy Path B (ReShade) injection vehicle to a game directory.

Copies into <game_dir>:
  dxgi.dll                              ReShade core (proxy DLL the game loads)
  captureAIshi_bridge.addon             our embedded bridge + frame_capture
  captureAIshi-shaders/Shaders/*.fx     DepthToAddon, BackBufferExport, ...

Then writes a fresh fc_output_dir.txt sidecar so the addon writes frames
into a known location.

Usage:
    python scripts/deploy_reshade.py \\
        --game-dir "C:/Games/HellbladeII/Binaries/Win64" \\
        --output-dir "D:/captureAIshi/output/hellblade2/frames"

Pre-reqs: dxgi.dll and captureAIshi_bridge.addon must be built first.
See 3rdparty/reshade_bridge/README.md and 3rdparty/reshade/README.md.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT     = Path(__file__).resolve().parent.parent
DEFAULT_DXGI  = REPO_ROOT / "3rdparty" / "reshade" / "bin" / "x64" / "Release" / "ReShade64.dll"
DEFAULT_ADDON = REPO_ROOT / "3rdparty" / "reshade_bridge" / "captureAIshi_bridge.addon"
SHADERS_DIR   = REPO_ROOT / "3rdparty" / "reshade_bridge" / "shaders"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game-dir", required=True, type=Path,
                    help="Directory containing the game .exe")
    ap.add_argument("--output-dir", required=True, type=Path,
                    help="Where the addon should write captured frames")
    ap.add_argument("--dxgi", type=Path, default=DEFAULT_DXGI,
                    help=f"Path to ReShade core DLL (default: {DEFAULT_DXGI})")
    ap.add_argument("--addon", type=Path, default=DEFAULT_ADDON,
                    help=f"Path to bridge addon (default: {DEFAULT_ADDON})")
    ap.add_argument("--undeploy", action="store_true",
                    help="Remove deployed files instead of installing them")
    args = ap.parse_args()

    if not args.game_dir.is_dir():
        print(f"error: game_dir does not exist: {args.game_dir}", file=sys.stderr)
        return 2

    targets = {
        args.game_dir / "dxgi.dll":                           args.dxgi,
        args.game_dir / "captureAIshi_bridge.addon":          args.addon,
    }
    shaders_target = args.game_dir / "captureAIshi-shaders" / "Shaders"
    sidecar = args.game_dir / "fc_output_dir.txt"

    if args.undeploy:
        for dst in list(targets) + [sidecar]:
            if dst.exists():
                dst.unlink()
                print(f"removed {dst}")
        if shaders_target.exists():
            shutil.rmtree(shaders_target.parent)
            print(f"removed {shaders_target.parent}")
        return 0

    for src in (args.dxgi, args.addon):
        if not src.exists():
            print(f"error: source not found: {src}", file=sys.stderr)
            print("       build it first (see 3rdparty/reshade_bridge/README.md)",
                  file=sys.stderr)
            return 3

    for dst, src in targets.items():
        shutil.copy2(src, dst)
        print(f"deployed {src.name} -> {dst}")

    shaders_target.mkdir(parents=True, exist_ok=True)
    for fx in SHADERS_DIR.glob("*.fx*"):
        shutil.copy2(fx, shaders_target / fx.name)
        print(f"deployed {fx.name} -> {shaders_target}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(str(args.output_dir.resolve()), encoding="utf-8")
    print(f"sidecar  fc_output_dir.txt -> {args.output_dir}")

    print()
    print("Done. Launch the game; ReShade overlay should show 'captureAIshi Bridge'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
