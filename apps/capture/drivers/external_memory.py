"""External memory driver for anti-cheat protected games.

Controls the camera by directly reading/writing game process memory
from OUTSIDE the process using ReadProcessMemory/WriteProcessMemory.

NO DLL injection needed. NO hooks. NO code modification.
This bypasses most user-mode anti-cheat systems because we never
enter the game process — we just read and write floats from outside.

Requirements:
  - Windows only (uses kernel32 process memory APIs)
  - Requires camera struct memory addresses (found via Cheat Engine)
  - Game process must be accessible (not kernel-protected)

Configuration via JSON offset file:
  {
    "process_name": "MyGame-Win64-Shipping.exe",
    "base_module": "MyGame-Win64-Shipping.exe",
    "camera": {
      "x": "0x04F3A120",
      "y": "+0x4",
      "z": "+0x8",
      "pitch": "0x04F3A130",
      "yaw": "+0x4",
      "roll": "+0x8",
      "fov": "0x04F3A140"
    },
    "game_speed": "0x04F3B000",
    "coord_system": "ue5"
  }

  Absolute offsets: "0x04F3A120" (from module base)
  Relative offsets: "+0x4" (from previous address)

Usage:
  python main.py --driver memory --memory-offsets offsets.json
"""

import ctypes
import ctypes.wintypes as wintypes
import json
import logging
import struct
import sys
import time
from pathlib import Path
from typing import Optional

from drivers.base import CameraDriver
from core.waypoint import CameraPose

logger = logging.getLogger(__name__)


class MemoryDriverError(Exception):
    """Raised when memory operations fail."""


class ExternalMemoryDriver(CameraDriver):
    """Control camera via external process memory read/write.

    This driver never enters the game process. It uses Windows
    ReadProcessMemory/WriteProcessMemory APIs from outside,
    which bypasses most anti-cheat DLL injection detection.

    Limitations:
      - Kernel-mode anti-cheat (e.g., Vanguard) may block
        ReadProcessMemory too
      - Requires pre-scanned memory offsets per game
      - Cannot execute console commands (no GEngine access)
      - Camera control only (position, rotation, FOV, game speed)
    """

    def __init__(
        self,
        offsets_file: str = "",
        process_name: str = "",
        settle_time: float = 0.05,
    ):
        self.offsets_file = Path(offsets_file) if offsets_file else None
        self.process_name = process_name
        self.settle_time = settle_time

        self._h_process = None
        self._pid = 0
        self._module_base = 0

        # Resolved absolute addresses
        self._addr_x = 0
        self._addr_y = 0
        self._addr_z = 0
        self._addr_pitch = 0
        self._addr_yaw = 0
        self._addr_roll = 0
        self._addr_fov = 0
        self._addr_speed = 0

        self._coord_system = "pipeline"
        self._offsets_config = {}

    def connect(self) -> None:
        if sys.platform != "win32":
            raise MemoryDriverError("ExternalMemoryDriver is Windows-only")

        # Load offsets
        if self.offsets_file and self.offsets_file.is_file():
            self._offsets_config = json.loads(self.offsets_file.read_text())
            if not self.process_name:
                self.process_name = self._offsets_config.get("process_name", "")
            self._coord_system = self._offsets_config.get("coord_system", "pipeline")
        elif not self.process_name:
            raise MemoryDriverError(
                "No offsets file or process name specified. "
                "Use --memory-offsets <file.json>"
            )

        if not self.process_name:
            raise MemoryDriverError("process_name not set in offsets file")

        # Find process
        self._pid = self._find_process(self.process_name)
        if not self._pid:
            raise MemoryDriverError(
                f"Process '{self.process_name}' not found. Is the game running?"
            )

        # Open process handle
        PROCESS_VM_READ = 0x0010
        PROCESS_VM_WRITE = 0x0020
        PROCESS_VM_OPERATION = 0x0008
        PROCESS_QUERY_INFORMATION = 0x0400

        kernel32 = ctypes.windll.kernel32
        self._h_process = kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
            | PROCESS_QUERY_INFORMATION,
            False, self._pid,
        )
        if not self._h_process:
            err = ctypes.get_last_error()
            raise MemoryDriverError(
                f"OpenProcess failed for PID {self._pid} (error {err}). "
                f"Run as Administrator."
            )

        # Find module base
        base_module = self._offsets_config.get("base_module", self.process_name)
        self._module_base = self._get_module_base(self._pid, base_module)
        if not self._module_base:
            raise MemoryDriverError(
                f"Module '{base_module}' not found in process {self._pid}"
            )

        logger.info(
            f"[MEMORY] Attached to {self.process_name} (PID {self._pid}), "
            f"module base=0x{self._module_base:X}"
        )

        # Resolve camera addresses
        self._resolve_addresses()
        logger.info("[MEMORY] Camera addresses resolved, ready for control")

    def disconnect(self) -> None:
        if self._h_process:
            ctypes.windll.kernel32.CloseHandle(self._h_process)
            self._h_process = None
            logger.info("[MEMORY] Disconnected from game process")

    def set_pose(self, pose: CameraPose) -> None:
        pos = pose.position.copy()
        rot = pose.rotation.copy()

        if self._coord_system == "ue5":
            from utils.coords import pipeline_to_ue5_position, pipeline_to_ue5_rotation
            pos = pipeline_to_ue5_position(pos)
            rot = pipeline_to_ue5_rotation(rot)
        elif self._coord_system == "unity":
            from utils.coords import pipeline_to_unity_position, pipeline_to_unity_rotation
            pos = pipeline_to_unity_position(pos)
            rot = pipeline_to_unity_rotation(rot)

        # Write position
        if self._addr_x:
            self._write_float(self._addr_x, pos[0])
            self._write_float(self._addr_y, pos[1])
            self._write_float(self._addr_z, pos[2])

        # Write rotation
        if self._addr_pitch:
            self._write_float(self._addr_pitch, rot[0])
            self._write_float(self._addr_yaw, rot[1])
            self._write_float(self._addr_roll, rot[2])

        # Write FOV
        if self._addr_fov and pose.fov != 90.0:
            self._write_float(self._addr_fov, pose.fov)

        time.sleep(self.settle_time)

    def read_camera(self) -> dict:
        """Read current camera state from game memory.

        Returns dict with x, y, z, pitch, yaw, roll, fov.
        Useful for recording keyframes.
        """
        result = {}
        if self._addr_x:
            result["x"] = self._read_float(self._addr_x)
            result["y"] = self._read_float(self._addr_y)
            result["z"] = self._read_float(self._addr_z)
        if self._addr_pitch:
            result["pitch"] = self._read_float(self._addr_pitch)
            result["yaw"] = self._read_float(self._addr_yaw)
            result["roll"] = self._read_float(self._addr_roll)
        if self._addr_fov:
            result["fov"] = self._read_float(self._addr_fov)
        return result

    def set_game_speed(self, speed: float) -> None:
        """Set game speed (requires game_speed offset in config)."""
        if self._addr_speed:
            self._write_float(self._addr_speed, speed)
            logger.debug(f"[MEMORY] Game speed set to {speed}")
        else:
            logger.warning("[MEMORY] game_speed offset not configured")

    def pause(self) -> None:
        """Pause the game."""
        self.set_game_speed(0.0001)

    def unpause(self) -> None:
        """Unpause the game."""
        self.set_game_speed(1.0)

    # ── Internal helpers ──

    def _read_float(self, addr: int) -> float:
        """Read a 32-bit float from game memory."""
        buf = ctypes.create_string_buffer(4)
        read = ctypes.c_size_t(0)
        ok = ctypes.windll.kernel32.ReadProcessMemory(
            self._h_process, ctypes.c_void_p(addr),
            buf, 4, ctypes.byref(read),
        )
        if not ok or read.value != 4:
            return 0.0
        return struct.unpack("<f", buf.raw)[0]

    def _write_float(self, addr: int, value: float) -> bool:
        """Write a 32-bit float to game memory."""
        data = struct.pack("<f", value)
        written = ctypes.c_size_t(0)
        ok = ctypes.windll.kernel32.WriteProcessMemory(
            self._h_process, ctypes.c_void_p(addr),
            data, 4, ctypes.byref(written),
        )
        if not ok or written.value != 4:
            logger.warning(
                f"[MEMORY] WriteProcessMemory failed at 0x{addr:X}"
            )
            return False
        return True

    def _find_process(self, name: str) -> int:
        """Find process PID by name."""
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32

        arr = (wintypes.DWORD * 2048)()
        cb = wintypes.DWORD()
        psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(cb))

        count = cb.value // ctypes.sizeof(wintypes.DWORD)
        target = name.lower()

        for i in range(count):
            pid = arr[i]
            if pid == 0:
                continue
            h = kernel32.OpenProcess(0x0410, False, pid)  # QUERY_INFO | VM_READ
            if not h:
                continue
            try:
                mod_name = ctypes.create_unicode_buffer(260)
                h_mod = wintypes.HMODULE()
                cb_needed = wintypes.DWORD()
                if psapi.EnumProcessModules(
                    h, ctypes.byref(h_mod), ctypes.sizeof(h_mod),
                    ctypes.byref(cb_needed),
                ):
                    psapi.GetModuleBaseNameW(h, h_mod, mod_name, 260)
                    if mod_name.value.lower() == target:
                        return pid
            finally:
                kernel32.CloseHandle(h)
        return 0

    def _get_module_base(self, pid: int, module_name: str) -> int:
        """Get the base address of a module in the target process."""
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32

        h = self._h_process
        h_mods = (wintypes.HMODULE * 1024)()
        cb_needed = wintypes.DWORD()

        if not psapi.EnumProcessModulesEx(
            h, ctypes.byref(h_mods), ctypes.sizeof(h_mods),
            ctypes.byref(cb_needed), 0x03,  # LIST_MODULES_ALL
        ):
            return 0

        count = cb_needed.value // ctypes.sizeof(wintypes.HMODULE)
        target = module_name.lower()

        for i in range(count):
            name_buf = ctypes.create_unicode_buffer(260)
            psapi.GetModuleBaseNameW(h, h_mods[i], name_buf, 260)
            if name_buf.value.lower() == target:
                mod_info_size = 24  # MODULEINFO struct size
                mod_info = (ctypes.c_byte * mod_info_size)()
                psapi.GetModuleInformation(
                    h, h_mods[i], mod_info, mod_info_size
                )
                return ctypes.cast(
                    ctypes.pointer(h_mods[i]),
                    ctypes.POINTER(ctypes.c_void_p)
                ).contents.value or int(h_mods[i])
        return 0

    def _resolve_addresses(self) -> None:
        """Resolve camera field addresses from offset config."""
        cam = self._offsets_config.get("camera", {})

        def resolve(field_offsets: dict, field_names: list) -> list:
            """Resolve a group of offsets (absolute or relative)."""
            addrs = []
            prev_addr = 0
            for name in field_names:
                raw = field_offsets.get(name, "")
                if not raw:
                    addrs.append(0)
                    continue
                if raw.startswith("+"):
                    # Relative to previous address
                    offset = int(raw, 16)
                    addr = prev_addr + offset
                else:
                    # Absolute offset from module base
                    offset = int(raw, 16)
                    addr = self._module_base + offset
                addrs.append(addr)
                prev_addr = addr
                logger.debug(
                    f"[MEMORY] {name} -> 0x{addr:X} (offset {raw})"
                )
            return addrs

        pos_addrs = resolve(cam, ["x", "y", "z"])
        self._addr_x = pos_addrs[0]
        self._addr_y = pos_addrs[1]
        self._addr_z = pos_addrs[2]

        rot_addrs = resolve(cam, ["pitch", "yaw", "roll"])
        self._addr_pitch = rot_addrs[0]
        self._addr_yaw = rot_addrs[1]
        self._addr_roll = rot_addrs[2]

        fov_addrs = resolve(cam, ["fov"])
        self._addr_fov = fov_addrs[0] if fov_addrs else 0

        # Game speed address
        speed_raw = self._offsets_config.get("game_speed", "")
        if speed_raw:
            self._addr_speed = self._module_base + int(speed_raw, 16)
