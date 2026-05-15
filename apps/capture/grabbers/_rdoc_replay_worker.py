#!/usr/bin/env python3
"""Standalone RenderDoc replay worker.

This script runs as a separate process to avoid module name conflicts
(the project has a 'renderdoc/' source directory that shadows the
renderdoc Python module). It loads a .rdc capture file, extracts the
backbuffer (RGB) and depth buffer, and saves them as numpy .npy files.

Usage:
    python _rdoc_replay_worker.py <rdc_file> <output_dir> [--dll-dir <path>]

Output files (in output_dir):
    rgb.npy   — uint8 array (H, W, 3)
    depth.npy — float32 array (H, W)
"""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="RenderDoc replay worker")
    parser.add_argument("rdc_file", help="Path to .rdc capture file")
    parser.add_argument("output_dir", help="Directory to save rgb.npy and depth.npy")
    parser.add_argument("--dll-dir", help="Directory containing renderdoc.dll")
    parser.add_argument("--pyd-dir", help="Directory containing renderdoc.pyd")
    args = parser.parse_args()

    # Set up DLL search path BEFORE importing renderdoc
    if args.dll_dir:
        os.add_dll_directory(args.dll_dir)
        os.environ["PATH"] = args.dll_dir + ";" + os.environ.get("PATH", "")

    if args.pyd_dir and args.pyd_dir not in sys.path:
        sys.path.insert(0, args.pyd_dir)

    try:
        import renderdoc as rd
    except ImportError as e:
        print(f"ERROR: Failed to import renderdoc: {e}", file=sys.stderr)
        sys.exit(1)

    if not hasattr(rd, 'OpenCaptureFile'):
        print("ERROR: renderdoc module is not the replay API (missing OpenCaptureFile)", file=sys.stderr)
        sys.exit(1)

    import numpy as np

    rdc_file = args.rdc_file
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize replay (required for standalone use)
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])

    try:
        cap = rd.OpenCaptureFile()
        result = cap.OpenFile(rdc_file, '', None)
        if result != rd.ResultCode.Succeeded:
            print(f"ERROR: Failed to open capture file: {result}", file=sys.stderr)
            sys.exit(2)

        if not cap.LocalReplaySupport():
            print("ERROR: Capture cannot be replayed locally", file=sys.stderr)
            cap.Shutdown()
            sys.exit(2)

        result, controller = cap.OpenCapture(rd.ReplayOptions(), None)
        if result != rd.ResultCode.Succeeded:
            print(f"ERROR: Failed to open replay: {result}", file=sys.stderr)
            cap.Shutdown()
            sys.exit(2)

        try:
            rgb = _extract_backbuffer(controller, rd)
            depth = _extract_depth(controller, rd)

            if rgb is not None:
                np.save(str(output_dir / "rgb.npy"), rgb)
                print(f"OK: rgb {rgb.shape[1]}x{rgb.shape[0]}")
            else:
                print("WARN: No backbuffer found")

            if depth is not None:
                np.save(str(output_dir / "depth.npy"), depth)
                print(f"OK: depth {depth.shape[1]}x{depth.shape[0]}")
            else:
                print("WARN: No depth buffer found")

        finally:
            controller.Shutdown()
            cap.Shutdown()

    finally:
        rd.ShutdownReplay()


def _extract_backbuffer(controller, rd):
    """Extract the RGB backbuffer from a replay."""
    import numpy as np
    textures = controller.GetTextures()
    for tex in textures:
        if tex.creationFlags & rd.TextureCategory.SwapBuffer:
            # Use SaveTexture to a temp file — more reliable than GetTextureData
            # for cross-API compatibility
            data = controller.GetTextureData(tex.resourceId, rd.Subresource())
            if data is not None:
                w, h = tex.width, tex.height
                arr = np.frombuffer(data, dtype=np.uint8)
                if len(arr) >= w * h * 4:
                    rgba = arr[:w * h * 4].reshape(h, w, 4)
                    return rgba[:, :, :3]  # Drop alpha
    return None


def _extract_depth(controller, rd):
    """Extract the depth buffer from a replay."""
    import numpy as np
    textures = controller.GetTextures()
    for tex in textures:
        if tex.creationFlags & rd.TextureCategory.DepthTarget:
            data = controller.GetTextureData(tex.resourceId, rd.Subresource())
            if data is not None:
                w, h = tex.width, tex.height
                arr = np.frombuffer(data, dtype=np.float32)
                if len(arr) >= w * h:
                    depth = arr[:w * h].reshape(h, w)
                    return depth
    return None


if __name__ == "__main__":
    main()
