#!/usr/bin/env python3
"""Build script for captureAIshi desktop application.

Handles dependency checking, PyInstaller invocation, and packaging
for Windows, macOS, and Linux.

Usage:
    python build_desktop.py            # Default one-dir build
    python build_desktop.py --onefile  # Single .exe (slower startup)
    python build_desktop.py --clean    # Clean previous builds first
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

REQUIRED_PACKAGES = [
    "pyinstaller",
    "pywebview",
    "flask",
    "numpy",
    "pillow",
    "mss",
]


def check_dependencies() -> list:
    """Return list of missing packages."""
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg.replace("-", "_").lower())
        except ImportError:
            # Handle package name → import name differences
            alt_names = {
                "pyinstaller": "PyInstaller",
                "pywebview": "webview",
                "pillow": "PIL",
            }
            alt = alt_names.get(pkg)
            if alt:
                try:
                    __import__(alt)
                    continue
                except ImportError:
                    pass
            missing.append(pkg)
    return missing


def install_dependencies(packages: list) -> None:
    """Install missing packages via pip."""
    print(f"Installing: {', '.join(packages)}")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install"] + packages,
        stdout=subprocess.DEVNULL,
    )


def clean_build() -> None:
    """Remove previous build artifacts."""
    for d in ["build", "dist"]:
        p = ROOT / d
        if p.exists():
            print(f"Removing {p}")
            shutil.rmtree(p)


def build(onefile: bool = False) -> None:
    """Run PyInstaller build."""
    if onefile:
        # One-file mode: produces a single .exe
        # Slower startup but easier to distribute
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--noconsole",
            "--name", "captureAIshi",
            "--add-data", f"web/templates{_sep()}web/templates",
            "--add-data", f"web/static{_sep()}web/static",
            "--hidden-import", "flask",
            "--hidden-import", "webview",
            "--hidden-import", "numpy",
            "--hidden-import", "PIL",
            "--hidden-import", "mss",
            "--hidden-import", "drivers.ue5_console",
            "--hidden-import", "drivers.unity_socket",
            "--hidden-import", "drivers.cheat_engine",
            "--hidden-import", "drivers.manual",
            "--hidden-import", "grabbers.renderdoc_grabber",
            "--hidden-import", "grabbers.screenshot_grabber",
            "--hidden-import", "ui_hiders.chain",
            "--hidden-import", "core.snake_path",
            "--hidden-import", "core.cone_rotation",
            "--hidden-import", "core.tangent_smoothing",
            "--hidden-import", "utils.coords",
            "desktop_app.py",
        ]
    else:
        # Use .spec file for one-dir mode (recommended)
        cmd = [
            sys.executable, "-m", "PyInstaller",
            str(ROOT / "desktop_app.spec"),
        ]

    print(f"Building {'one-file' if onefile else 'one-dir'} executable...")
    subprocess.check_call(cmd, cwd=str(ROOT))


def _sep() -> str:
    """Return the PyInstaller --add-data separator for current OS."""
    return ";" if sys.platform == "win32" else ":"


def main():
    parser = argparse.ArgumentParser(description="Build captureAIshi desktop app")
    parser.add_argument("--onefile", action="store_true", help="Build single .exe")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts first")
    parser.add_argument("--skip-deps", action="store_true", help="Skip dependency check")
    args = parser.parse_args()

    if args.clean:
        clean_build()

    if not args.skip_deps:
        missing = check_dependencies()
        if missing:
            print(f"Missing dependencies: {', '.join(missing)}")
            install_dependencies(missing)

    build(onefile=args.onefile)

    # Report result
    if args.onefile:
        exe = ROOT / "dist" / ("captureAIshi.exe" if sys.platform == "win32" else "captureAIshi")
    else:
        exe = ROOT / "dist" / "captureAIshi" / ("captureAIshi.exe" if sys.platform == "win32" else "captureAIshi")

    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"\nBuild successful!")
        print(f"  Output: {exe}")
        print(f"  Size:   {size_mb:.1f} MB")
    else:
        print(f"\nBuild completed. Check dist/ for output.")


if __name__ == "__main__":
    main()
