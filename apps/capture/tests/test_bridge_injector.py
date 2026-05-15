"""Tests for the bridge injector module.

These tests verify the injector logic is importable and that
Windows-only functions are properly guarded on non-Windows systems.
"""

import sys
import pytest
from pathlib import Path


def test_injector_imports():
    """The injector module should import cleanly on any platform."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "3rdparty" / "bridge"))
    import injector  # noqa: F401


def test_injection_error_class():
    """InjectionError should be a proper exception."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "3rdparty" / "bridge"))
    from injector import InjectionError

    with pytest.raises(InjectionError):
        raise InjectionError("test error")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_find_process_returns_none_for_nonexistent():
    """_find_process_by_name should return None for a process that doesn't exist."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "3rdparty" / "bridge"))
    from injector import _find_process_by_name

    result = _find_process_by_name("definitely_not_a_real_process_12345.exe")
    assert result is None


@pytest.mark.skipif(sys.platform == "win32", reason="Non-Windows only")
def test_inject_dll_raises_on_non_windows():
    """inject_dll should raise OSError on non-Windows platforms."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "3rdparty" / "bridge"))
    from injector import inject_dll

    with pytest.raises(OSError, match="Windows-only"):
        inject_dll(1234, "/fake/path.dll")


def test_auto_inject_skips_gracefully_on_linux(tmp_path):
    """_run_auto_inject should skip gracefully on non-Windows."""
    from unittest.mock import MagicMock
    import main

    args = MagicMock()
    args.auto_inject = True
    args.dry_run = False
    args.bridge_dll = None
    args.target_exe = "game.exe"
    args.inject_process = None

    # On Linux, should log a warning and return without error
    if sys.platform != "win32":
        main._run_auto_inject(args)  # Should not raise
