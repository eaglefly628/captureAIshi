"""DLL injector for captureAIshi bridge.

Injects captureAIshi_bridge.dll into a target game process using the
classic CreateRemoteThread + LoadLibraryW technique. This is the same
approach used by RenderDoc (see renderdoc/os/win32/win32_process.cpp).

Usage:
    from injector import inject_dll

    # Inject by PID
    inject_dll(pid=12345, dll_path="path/to/captureAIshi_bridge.dll")

    # Find game process by name and inject
    inject_by_name("MyGame-Win64-Shipping.exe", "path/to/captureAIshi_bridge.dll")

This module is Windows-only (requires kernel32, psapi).
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Only define Windows-specific constants and types on Windows
if sys.platform == "win32":
    # Process access rights
    PROCESS_CREATE_THREAD = 0x0002
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_OPERATION = 0x0008
    PROCESS_VM_WRITE = 0x0020
    PROCESS_VM_READ = 0x0010
    SYNCHRONIZE = 0x00100000

    PROCESS_ALL_INJECT = (
        PROCESS_CREATE_THREAD
        | PROCESS_QUERY_INFORMATION
        | PROCESS_VM_OPERATION
        | PROCESS_VM_WRITE
        | PROCESS_VM_READ
        | SYNCHRONIZE
    )

    # Memory allocation
    MEM_COMMIT = 0x1000
    MEM_RELEASE = 0x8000
    PAGE_READWRITE = 0x04

    INFINITE = 0xFFFFFFFF

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi


class InjectionError(Exception):
    """Raised when DLL injection fails."""


def _find_process_by_name(name: str) -> Optional[int]:
    """Find a process PID by executable name (Windows only).

    Enumerates all processes and matches against the given name
    (case-insensitive). Returns the first match or None.
    """
    if sys.platform != "win32":
        raise OSError("Process enumeration is Windows-only")

    # Get list of all PIDs
    arr = (wintypes.DWORD * 1024)()
    bytes_returned = wintypes.DWORD()
    psapi.EnumProcesses(
        ctypes.byref(arr),
        ctypes.sizeof(arr),
        ctypes.byref(bytes_returned),
    )

    count = bytes_returned.value // ctypes.sizeof(wintypes.DWORD)
    target = name.lower()

    for i in range(count):
        pid = arr[i]
        if pid == 0:
            continue

        # Try to open the process to read its name
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
        )
        if not handle:
            continue

        try:
            # Get module base name
            mod_name = ctypes.create_unicode_buffer(260)
            h_mod = wintypes.HMODULE()
            cb_needed = wintypes.DWORD()

            if psapi.EnumProcessModules(
                handle,
                ctypes.byref(h_mod),
                ctypes.sizeof(h_mod),
                ctypes.byref(cb_needed),
            ):
                psapi.GetModuleBaseNameW(
                    handle, h_mod, mod_name, ctypes.sizeof(mod_name)
                )
                if mod_name.value.lower() == target:
                    logger.info(f"Found process '{name}' with PID {pid}")
                    return pid
        finally:
            kernel32.CloseHandle(handle)

    return None


def inject_dll(pid: int, dll_path: str) -> None:
    """Inject a DLL into a running process.

    Steps (same as RenderDoc's InjectDLL):
      1. OpenProcess with required access rights
      2. VirtualAllocEx — allocate memory in target for DLL path string
      3. WriteProcessMemory — write the DLL path
      4. CreateRemoteThread — call LoadLibraryW in the target process
      5. Wait for thread, cleanup

    Args:
        pid: Target process ID.
        dll_path: Absolute path to the DLL to inject.

    Raises:
        InjectionError: If any step fails.
        OSError: If not running on Windows.
    """
    if sys.platform != "win32":
        raise OSError("DLL injection is Windows-only")

    dll_abs = str(Path(dll_path).resolve())
    if not Path(dll_abs).is_file():
        raise InjectionError(f"DLL not found: {dll_abs}")

    logger.info(f"Injecting {Path(dll_abs).name} into PID {pid}...")

    # 1. Open target process
    h_process = kernel32.OpenProcess(PROCESS_ALL_INJECT, False, pid)
    if not h_process:
        err = ctypes.get_last_error()
        raise InjectionError(
            f"OpenProcess failed for PID {pid} (error {err}). "
            f"Try running as Administrator."
        )

    try:
        # 2. Encode DLL path as wide string (UTF-16LE + null terminator)
        dll_bytes = (dll_abs + "\0").encode("utf-16-le")
        alloc_size = len(dll_bytes)

        # 3. Allocate memory in target process
        remote_mem = kernel32.VirtualAllocEx(
            h_process, None, alloc_size, MEM_COMMIT, PAGE_READWRITE
        )
        if not remote_mem:
            err = ctypes.get_last_error()
            raise InjectionError(f"VirtualAllocEx failed (error {err})")

        try:
            # 4. Write DLL path to allocated memory
            written = ctypes.c_size_t(0)
            ok = kernel32.WriteProcessMemory(
                h_process, remote_mem, dll_bytes, alloc_size, ctypes.byref(written)
            )
            if not ok:
                err = ctypes.get_last_error()
                raise InjectionError(f"WriteProcessMemory failed (error {err})")

            logger.debug(f"Wrote {written.value} bytes to remote process memory")

            # 5. Get LoadLibraryW address from kernel32
            h_kernel32 = kernel32.GetModuleHandleW("kernel32.dll")
            if not h_kernel32:
                raise InjectionError("Failed to get kernel32.dll handle")

            load_library_addr = kernel32.GetProcAddress(
                h_kernel32, b"LoadLibraryW"
            )
            if not load_library_addr:
                raise InjectionError("Failed to get LoadLibraryW address")

            # 6. Create remote thread to call LoadLibraryW(dll_path)
            thread_id = wintypes.DWORD()
            h_thread = kernel32.CreateRemoteThread(
                h_process,
                None,           # security attributes
                1024 * 1024,    # stack size (1MB, same as RenderDoc)
                load_library_addr,
                remote_mem,     # argument = pointer to DLL path
                0,              # creation flags
                ctypes.byref(thread_id),
            )
            if not h_thread:
                err = ctypes.get_last_error()
                raise InjectionError(
                    f"CreateRemoteThread failed (error {err}). "
                    f"Anti-cheat may be blocking injection."
                )

            logger.debug(f"Remote thread created (tid={thread_id.value}), waiting...")

            # 7. Wait for LoadLibraryW to complete
            wait_result = kernel32.WaitForSingleObject(h_thread, 10000)  # 10s timeout
            if wait_result != 0:  # 0 = WAIT_OBJECT_0
                raise InjectionError(
                    f"Remote thread did not complete (wait={wait_result}). "
                    f"DLL may have failed to load."
                )

            # Check thread exit code (LoadLibraryW return value = module handle)
            exit_code = wintypes.DWORD()
            kernel32.GetExitCodeThread(h_thread, ctypes.byref(exit_code))
            if exit_code.value == 0:
                raise InjectionError(
                    "LoadLibraryW returned NULL — DLL failed to load in target. "
                    "Check that the DLL architecture matches the game (x64 vs x86) "
                    "and that all DLL dependencies are available."
                )

            kernel32.CloseHandle(h_thread)
            logger.info(
                f"DLL injected successfully! Module handle=0x{exit_code.value:X}"
            )

        finally:
            # Free remote memory
            kernel32.VirtualFreeEx(h_process, remote_mem, 0, MEM_RELEASE)

    finally:
        kernel32.CloseHandle(h_process)


def inject_by_name(process_name: str, dll_path: str) -> int:
    """Find a process by name and inject a DLL into it.

    Args:
        process_name: Executable name (e.g. "MyGame-Win64-Shipping.exe").
        dll_path: Path to DLL to inject.

    Returns:
        The PID of the injected process.

    Raises:
        InjectionError: If process not found or injection fails.
    """
    pid = _find_process_by_name(process_name)
    if pid is None:
        raise InjectionError(
            f"Process '{process_name}' not found. "
            f"Is the game running?"
        )
    inject_dll(pid, dll_path)
    return pid


def wait_and_inject(
    process_name: str,
    dll_path: str,
    timeout: float = 60.0,
    poll_interval: float = 1.0,
) -> int:
    """Wait for a process to appear, then inject.

    Used when the game is being launched (e.g. by renderdoccmd) and
    we need to wait for the actual renderer process to start.

    Args:
        process_name: Executable name to watch for.
        dll_path: Path to DLL to inject.
        timeout: Max seconds to wait.
        poll_interval: Seconds between checks.

    Returns:
        The PID of the injected process.
    """
    import time

    logger.info(f"Waiting for '{process_name}' to start (timeout={timeout}s)...")
    elapsed = 0.0

    while elapsed < timeout:
        pid = _find_process_by_name(process_name)
        if pid is not None:
            # Brief delay to let the process finish initialization
            time.sleep(0.5)
            inject_dll(pid, dll_path)
            return pid

        time.sleep(poll_interval)
        elapsed += poll_interval

        if int(elapsed) % 5 == 0 and elapsed > 0:
            logger.info(f"Still waiting for '{process_name}'... ({elapsed:.0f}s)")

    raise InjectionError(
        f"Process '{process_name}' did not start within {timeout}s"
    )
