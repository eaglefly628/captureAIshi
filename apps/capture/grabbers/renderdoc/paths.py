"""Executable + capture directory discovery helpers.

Free functions that the RenderDocGrabber orchestrator calls; they don't
need any grabber state beyond explicit arguments.
"""

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def find_pid_by_name(process_name: str) -> Optional[int]:
    """Return PID of first running process matching name, or None."""
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name"]):
            if proc.info["name"].lower() == process_name.lower():
                return proc.info["pid"]
        return None
    except ImportError:
        pass

    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if process_name.lower() in line.lower():
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        return int(parts[1].strip('"'))
                    except ValueError:
                        pass
    return None


def resolve_renderdoccmd(user_path: str) -> str:
    """Find renderdoccmd executable.

    Search order:
      1. User-provided path (if it's a valid file or in PATH)
      2. Vendor tree at <repo>/3rdparty/renderdoc/x64/{Development,Release}/
      3. Common install locations (Windows Program Files)
    """
    exe_name = "renderdoccmd.exe" if sys.platform == "win32" else "renderdoccmd"

    if Path(user_path).is_file():
        logger.debug(f"renderdoccmd: using user path (file): {user_path}")
        return user_path
    resolved = shutil.which(user_path)
    if resolved:
        logger.debug(f"renderdoccmd: found in PATH: {resolved}")
        return resolved

    # apps/capture/grabbers/renderdoc/paths.py -> parents[4] = repo root
    repo_root = Path(__file__).resolve().parents[4]
    relative_candidates = [
        Path("3rdparty/renderdoc/x64/Development") / exe_name,
        Path("3rdparty/renderdoc/x64/Release") / exe_name,
        Path("3rdparty/renderdoc/build/bin") / exe_name,
        Path("3rdparty/renderdoc/bin") / exe_name,
    ]
    for candidate in relative_candidates:
        full = repo_root / candidate
        if full.is_file():
            found = str(full)
            logger.info(f"renderdoccmd: auto-discovered at {found}")
            return found

    if sys.platform == "win32":
        for prog_dir in [Path("C:/Program Files"), Path("C:/Program Files (x86)")]:
            for rdoc_dir in prog_dir.glob("RenderDoc*"):
                candidate = rdoc_dir / exe_name
                if candidate.is_file():
                    found = str(candidate)
                    logger.info(f"renderdoccmd: found in system install: {found}")
                    return found

    raise FileNotFoundError(
        f"renderdoccmd not found. Searched: PATH, {repo_root}/3rdparty/renderdoc/..., "
        f"Program Files. Set full path in UI or add to PATH."
    )


def find_shipping_exe(target_exe: Optional[str]) -> Optional[str]:
    """Search for the real UE5 game exe near the launcher path.

    UE5 packaged games typically have:
      GameRoot/GameName.exe              (launcher - spawns child and exits)
      GameRoot/GameName/Binaries/Win64/GameName-Win64-Shipping.exe  (real)
    or sometimes:
      GameRoot/Engine/Binaries/Win64/GameName-Win64-Shipping.exe
    """
    if not target_exe:
        return None

    exe_path = Path(target_exe)
    game_dir = exe_path.parent
    stem = exe_path.stem

    search_patterns = [
        game_dir / stem / "Binaries" / "Win64" / f"{stem}-Win64-Shipping.exe",
        game_dir / stem / "Binaries" / "Win64" / f"{stem}.exe",
        game_dir / "Engine" / "Binaries" / "Win64" / f"{stem}-Win64-Shipping.exe",
    ]
    for candidate in search_patterns:
        if candidate.is_file() and candidate != exe_path:
            return str(candidate)

    for shipping in game_dir.rglob("*-Win64-Shipping.exe"):
        return str(shipping)
    for shipping in game_dir.rglob("*-Shipping.exe"):
        return str(shipping)
    return None


def find_latest_rdc(capture_dir: Path) -> Optional[Path]:
    """Find the most recently modified .rdc file in ``capture_dir``."""
    rdcs = list(capture_dir.glob("*.rdc"))
    if not rdcs:
        return None
    return max(rdcs, key=lambda p: p.stat().st_mtime)


def find_renderdoc_dirs():
    """Locate renderdoc.pyd (Python bindings) + sibling DLL directory.

    Returns ``(pyd_dir, dll_dir)`` or ``(None, None)`` if not found.
    """
    pyd_name = "renderdoc.pyd" if sys.platform == "win32" else "renderdoc.so"
    repo_root = Path(__file__).resolve().parents[4]
    candidates = [
        Path("3rdparty/renderdoc/x64/Development/pymodules"),
        Path("3rdparty/renderdoc/x64/Release/pymodules"),
        Path("3rdparty/renderdoc/build/lib/pymodules"),
    ]
    for candidate in candidates:
        pyd_dir = repo_root / candidate
        pyd_file = pyd_dir / pyd_name
        if pyd_file.is_file():
            dll_dir = pyd_dir.parent
            logger.debug(f"[RDOC] Found {pyd_name} at {pyd_dir}, DLLs at {dll_dir}")
            return pyd_dir, dll_dir

    logger.error(
        f"[RDOC] renderdoc Python bindings ({pyd_name}) not found. "
        f"Build 'pyrenderdoc_module' in Visual Studio. "
        f"Searched: {repo_root}/3rdparty/renderdoc/..."
    )
    return None, None
