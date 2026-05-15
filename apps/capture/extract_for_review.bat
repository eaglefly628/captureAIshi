@echo off
setlocal
set OUT=gemini_review.txt

echo. > %OUT%

:: ============================================================
:: captureAIshi -- Core Function Logic Extract
:: Purpose: Feed to external AI reviewer (Gemini) for audit
:: Generated: %DATE% %TIME%
:: ============================================================

call :header "PROJECT OVERVIEW" "captureAIshi v0.2.0 -- UE5/Unity game camera capture pipeline"
echo. >> %OUT%
echo Architecture: >> %OUT%
echo   DLL injection via renderdoc + bridge.dll (TCP 9998) >> %OUT%
echo   GEngine/UWorld auto-scan, camera struct intercept, Catmull-Rom path playback >> %OUT%
echo   Python drivers connect to bridge TCP server to send camera poses >> %OUT%
echo   Two build trees: 3rdparty/bridge/src/ (CMake, compiled) vs renderdoc/ (reference) >> %OUT%
echo. >> %OUT%

:: ---- COMPILED DLL: 3rdparty/bridge/src/ ----

call :section "3rdparty/bridge/src/bridge.cpp" "TCP server (port 9998), command dispatch, client socket management, g_smooth/path state. THIS IS THE COMPILED DLL."
type 3rdparty\bridge\src\bridge.cpp >> %OUT%
echo. >> %OUT%

call :section "3rdparty/bridge/src/ue5_engine.h" "GEngine/GWorld pointer scan, FName resolution, UObject iteration. SEH-guarded bare pointer reads."
type 3rdparty\bridge\src\ue5_engine.h >> %OUT%
echo. >> %OUT%

call :section "3rdparty/bridge/src/camera_path.h" "CameraPath: Catmull-Rom keyframe interpolation + mutex guards. Compiled into bridge.dll."
type 3rdparty\bridge\src\camera_path.h >> %OUT%
echo. >> %OUT%

call :section "3rdparty/bridge/src/pattern_scan.h" "AOB pattern scanner: Boyer-Moore-Horspool over mapped PE sections."
type 3rdparty\bridge\src\pattern_scan.h >> %OUT%
echo. >> %OUT%

:: ---- REFERENCE TREE: 3rdparty/renderdoc/renderdoc/core/bridge/ (NOT compiled by CMake) ----

call :header "REFERENCE TREE (renderdoc/renderdoc/core/bridge/)" "Rewritten by xiaoni -- not yet integrated into CMake. Reviewed for bugs below."

call :section "3rdparty/renderdoc/renderdoc/core/bridge/camera_intercept.h" "IGCS-style AOB patch: VirtualProtect+memcpy NOP, SuspendThread/ResumeThread, SEH memcpy, 16-site cap."
type ..\..\3rdparty\renderdoc\renderdoc\core\bridge\camera_intercept.h >> %OUT%
echo. >> %OUT%

call :section "3rdparty/renderdoc/renderdoc/core/bridge/console_server.h" "Reference TCP server: ClientSlot struct, cmd_queue ring buffer, CAS slot claim, camera override mutex, WSA lifecycle."
type ..\..\3rdparty\renderdoc\renderdoc\core\bridge\console_server.h >> %OUT%
echo. >> %OUT%

call :section "3rdparty/renderdoc/renderdoc/core/bridge/camera_path.h" "Reference CameraPath with mutable mutex, stop_unlocked() helper, play/stop/toggle_pause lock."
type ..\..\3rdparty\renderdoc\renderdoc\core\bridge\camera_path.h >> %OUT%
echo. >> %OUT%

call :section "3rdparty/renderdoc/renderdoc/core/bridge/ue5_exec_hook.h" "UE5 exec hook: cmd_queue SPSC ring buffer, CAS slot-claim fix (has producer-ordering bug -- see known issues)."
type ..\..\3rdparty\renderdoc\renderdoc\core\bridge\ue5_exec_hook.h >> %OUT%
echo. >> %OUT%

call :section "3rdparty/renderdoc/renderdoc/core/bridge/ue5_scan_engine.h" "GEngine scan: string-xref walk, SEH-guarded reads, seh_read_ptr helper."
type ..\..\3rdparty\renderdoc\renderdoc\core\bridge\ue5_scan_engine.h >> %OUT%
echo. >> %OUT%

call :section "3rdparty/renderdoc/renderdoc/core/bridge/ue5_scan_camera.h" "Camera struct scan: FField chain walk, seh_read_u32_ok, offset discovery."
type ..\..\3rdparty\renderdoc\renderdoc\core\bridge\ue5_scan_camera.h >> %OUT%
echo. >> %OUT%

call :section "3rdparty/renderdoc/renderdoc/core/bridge/ue5_engine.h" "Reference UE5 engine structs and type definitions."
type ..\..\3rdparty\renderdoc\renderdoc\core\bridge\ue5_engine.h >> %OUT%
echo. >> %OUT%

call :section "3rdparty/renderdoc/renderdoc/core/bridge/pattern_scan.h" "Reference pattern scanner."
type ..\..\3rdparty\renderdoc\renderdoc\core\bridge\pattern_scan.h >> %OUT%
echo. >> %OUT%

:: ---- PYTHON DRIVERS ----

call :header "PYTHON DRIVERS" "Camera control adapters connecting Python pipeline to the DLL"

call :section "drivers/base.py" "CameraDriver ABC: CameraPose dataclass, connect/set_pose/disconnect interface."
type drivers\base.py >> %OUT%
echo. >> %OUT%

call :section "drivers/bridge_path.py" "BridgePathDriver: TCP client to bridge.dll port 9998, sends __path_add / __path_play."
type drivers\bridge_path.py >> %OUT%
echo. >> %OUT%

call :section "drivers/external_memory.py" "ExternalMemoryDriver: Cheat Engine style direct memory write via ReadProcessMemory/WriteProcessMemory."
type drivers\external_memory.py >> %OUT%
echo. >> %OUT%

call :section "drivers/trajectory_player.py" "TrajectoryPlayer: reads trajectory.json, replays at 60Hz via driver.set_pose()."
type drivers\trajectory_player.py >> %OUT%
echo. >> %OUT%

call :section "drivers/game_profile.py" "GameProfile: per-game config (AOB patterns, struct offsets, coordinate transform, rotation format)."
type drivers\game_profile.py >> %OUT%
echo. >> %OUT%

:: ---- KNOWN BUGS SUMMARY (for reviewer context) ----

call :header "KNOWN BUGS -- Reviewer Context" "Issues already identified internally, confirm/expand"
echo. >> %OUT%
echo BUG-1 [P0] cmd_queue producer-ordering hole (console_server.h / ue5_exec_hook.h): >> %OUT%
echo   CAS claims slot N atomically, but two producers A(slot N) and B(slot N+1) >> %OUT%
echo   can complete out-of-order. Consumer advances head after both slots filled, >> %OUT%
echo   but producer A may not have written yet when head passes N. >> %OUT%
echo   Fix options: (a) write-before-CAS publish pattern, (b) per-slot ready flag. >> %OUT%
echo. >> %OUT%
echo BUG-2 [P1] 33rd client socket UAF (bridge.cpp / console_server.h): >> %OUT%
echo   When MAX_CLIENTS=32 reached, closesocket(client) in accept loop while >> %OUT%
echo   spawned thread may hold same fd. Kernel recycles fd; thread's later >> %OUT%
echo   closesocket() can destroy a different live connection. >> %OUT%
echo   Fix: reject before CreateThread when slots full. >> %OUT%
echo. >> %OUT%
echo BUG-3 [P1] SuspendThread + bridge_log deadlock (camera_intercept.h): >> %OUT%
echo   cam_patch_write() calls bridge_log() on failure paths INSIDE the >> %OUT%
echo   SuspendThread window. bridge_log -> OutputDebugStringA -> CSRSS/DBWIN mutex. >> %OUT%
echo   If suspended thread held that mutex: deadlock. >> %OUT%
echo   Fix: move all bridge_log calls after cam_resume_others(). >> %OUT%
echo. >> %OUT%
echo BUG-4 [P1] __cam_mem_find global lock missing (console_server.h): >> %OUT%
echo   pause + clear + scan + resume sequence has no global CRITICAL_SECTION. >> %OUT%
echo   A second concurrent __cam_mem_find can double-suspend or scan during active playback. >> %OUT%
echo. >> %OUT%
echo QUESTION FOR REVIEWER: >> %OUT%
echo   Are there additional thread-safety issues in the CameraPath tick() path? >> %OUT%
echo   Is the Catmull-Rom clamping at keyframe boundaries correct? >> %OUT%
echo   Is seh_read_ptr sufficient for DRM page protection, or is VirtualQuery needed first? >> %OUT%

echo.
echo Done. Output: %OUT%
echo Lines written:
find /c /v "" %OUT%
goto :eof

:section
echo. >> %OUT%
echo ================================================================ >> %OUT%
echo FILE: %~1 >> %OUT%
echo DESC: %~2 >> %OUT%
echo ================================================================ >> %OUT%
echo. >> %OUT%
goto :eof

:header
echo. >> %OUT%
echo. >> %OUT%
echo ################################################################ >> %OUT%
echo ## %~1 >> %OUT%
echo ## %~2 >> %OUT%
echo ################################################################ >> %OUT%
echo. >> %OUT%
goto :eof
