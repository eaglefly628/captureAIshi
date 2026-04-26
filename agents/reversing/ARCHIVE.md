# Reverse Engineering Agent (小逆) — Archive

已完成 TODO 和详细调研。从 SHARED.md 归档以节省 token。

## Completed TODO

- [x] **P0: ConsoleServer_Start Sleep(5000)** — 改轮询 500ms, 60s timeout。
- [x] **P0: detached client threads 无清理** — tracked vector + join。
- [x] **P1: static 全局变量在 header** — 加注释说明单 TU include。
- [x] **P1: vtable 暴力搜索用用户命令** — 改 `stat none` 探测。
- [x] **P1: __path_delete atoi 负数溢出** — 加 `val < 0` 检查。
- [x] **P1: C++ headers Unicode** (fixed by 主程序员) — U+2500 → ASCII。
- [x] **P2: toggle_hud ShowFlag.PostProcessing** — 移除，只用 ShowHUD。
- [x] **P2: Quat 旋转顺序** — 改 YXZ，与 Python 一致。
- [x] **P2: 缺 CL** — 已补。
- [x] **P3: AOB 数据库调研** — 结论：不需要 per-game DB。

## [v0.1.0] Tested Games
- EagleWalkLJB (UE5 demo): RenderDoc OK, console OK, ToggleDebugCamera OK

## [v0.2.0] AOB Database Research

结论：不需要 per-game 数据库。UUU 用引擎通用 pattern。

可复用资源: patternsleuth (Rust), UEVR (praydog), UE4SS (Lua), IGCS (手工 AOB)

我们的改进: 8 个锚点 (CALIBRATEMOTION, SeamlessTravel FlushLevelStreaming, StaticConstructObject_Internal, r.HLOD + 原 4 个 wide)。

## [v0.2.0] ProcessConsoleExec VTable Research (2026-04-08)

### Root Cause: Wrong Function + Wrong VTable Range

我们一直在调用错误的函数:
- **错误**: 找 `UObject::Exec(UWorld*, TCHAR*, FOutputDevice&)` at vtable[110-130]
- **正确**: 找 `UObject::ProcessConsoleExec(TCHAR*, FOutputDevice&, UObject*)` at vtable[65-90]

参数顺序也完全不同:
- 旧: `fn(this, world, cmd, ar)` -- rdx=UWorld*, r8=cmd, r9=ar
- 新: `fn(this, cmd, ar, executor)` -- rdx=cmd, r8=ar, r9=executor

### UE4SS PDB-Verified VTable Indices

来源: UE4SS `assets/VTableLayoutTemplates/` (PDB 符号导出)
ProcessConsoleExec = ProcessEvent + 3 (永远)

| UE Version | ProcessEvent | ProcessConsoleExec |
|------------|:----------:|:-----------------:|
| 4.10 | 50 | 53 |
| 4.11-4.13 | 53 | 56 |
| 4.14 | 57 | 60 |
| 4.15 | 58 | 61 |
| 4.16 | 62 | 65 |
| 4.17-4.19 | 63 | 66 |
| 4.20 | 65 | 68 |
| 4.21-4.22 | 64 | 67 |
| 4.23-4.25 | 66 | 69 |
| 4.26 | 67 | 70 |
| 4.27 | 68 | 71 |
| 5.00 | 75 | 78 |
| 5.01 | 76 | 79 |
| 5.02-5.04 | 77 | 80 |
| 5.05 | 79 | 82 |
| 5.06-5.07 | 76 | 79 |

### Index 非单调递增原因

- UE 5.01: UObjectBase 加了 `GetFNameForStatID` (+1)
- UE 5.05: UObjectBaseUtility 加了新条目 (+1)
- UE 5.06: UObject 移除了多个虚函数 (PreSaveRoot, PostSaveRoot 等), index 回落

### UEVR 方案参考

- UEVR 用私有子模块 UESDK (不公开) 解析 vtable
- UE4SS 用 PDB 符号表 + INI 模板 (最可靠)
- UE4SS 的 UVTD (Unreal VTable Dumper) 从 PDB 自动导出 vtable 布局

### 验证方法: Ar-callback detection

真正的 ProcessConsoleExec 会调用 `Ar.Serialize()` (FOutputDevice 虚函数)。
用 dummy FOutputDevice + callback flag 检测: 如果 Ar 被调用 = 找到 Exec。

## [v0.1.0] Camera Control Details

### Unity
- BepInEx plugin (IL2CPP + Mono)
- UnityExplorer runtime inspector

---
## Archived 2026-04-18 (精简 SHARED.md)

### Closed TODO items (全部已完成)

- [x] P0: 3rdparty/bridge/src/ 与 renderdoc/ 双树分叉 → e2cd967 同步
- [x] P0: line_buf 无大小上限 → 1MB cap + disconnect
- [x] P0: ue5_engine.h 文件拆分 → c088120 (5 子文件)
- [x] P0: cmd_queue CAS 引入消费者读半写槽 → 2c0ea17 per-slot ready flag
- [x] P0: cam_patch_write() patch 时未暂停游戏线程 → SuspendThread
- [x] P0: ue5_scan_engine.h 裸指针解引用无 SEH (×2) → seh_read_ptr
- [x] P0: ue5_scan_camera.h FField 裸解引用 (×2) → seh_read_u32_ok
- [x] P0: g_cam_override_state 多线程撕裂读写 → g_cam_override_mutex
- [x] P0: strtof locale 陷阱 → ascii_strtof / ascii_strtod (both trees)
- [x] P1: recv() 错误和关闭未区分 → n==0/n<0 split
- [x] P1: __path_delete atoi 整数溢出 → strtol + bounds
- [x] P1: camera_path.h count/tick/list 无 mutex → mutable + lock_guard
- [x] P1: ClientArg CreateThread 失败泄漏 → delete arg + closesocket
- [x] P1: camera_intercept.h memcpy 无 SEH (×2) → cam_seh_memcpy
- [x] P1: VirtualQuery 未检查 size 跨页 → cross-boundary check
- [x] P1: InterpolatedCamera cam 未初始化 → zero-init
- [x] P1: camera_path.h play/stop 未持锁 → stop_unlocked()
- [x] P1: __cam_mem_write 未做 NaN/Inf 过滤 → cs_sanitize_float
- [x] P1: g_cam_pov_ptr 无同步 → g_cam_pov_mutex + try_lock
- [x] P1: ConsoleServer_Stop WSACleanup 时序 → 移到 Stop()
- [x] P1: console_server.h Sleep(5000) → module-size-stability poll
- [x] P1: console_server.h 无 WSAStartup → cs_server_main 内初始化
- [x] P1: EnumWindows 重复代码 → find_game_window()
- [x] P1: cmd_queue 生产者无溢出保护 → drop with log
- [x] P1: 33rd client socket-reuse UAF → slot-full check before CreateThread
- [x] P1: cam_patch_write SuspendThread 下 bridge_log 死锁 → 改错误缓冲
- [x] P1: __cam_mem_find 暂停 override 竞争窗口 → g_cam_pov_mutex
- [x] P1: handle_client 退出不从 g_client_socks 移除 → slot cleanup
- [x] P1: g_smooth_factor 裸读写数据竞争 → std::atomic<float>
- [x] P1: UObject GC lifecycle 校验缺失 → cam_manager_alive() flags check
- [x] P1: WSACleanup ordering + scan 线程超时 (caveat noted)
- [x] P2: cs_smooth_initialized 数据竞争 → std::atomic<bool>
- [x] P2: BRIDGE_LOG vsnprintf truncation → clamp n to avail-1
- [x] P2: g_fexec_hook_count volatile → std::atomic<LONG>
- [x] P2: 第 33 个客户端 socket 泄漏 → shutdown + closesocket
- [x] P2: Sleep(100) → SwitchToThread()
- [x] P2: client thread shutdown → ClientSlot + shutdown(SD_BOTH)
- [x] P2: console_server.h strtof INF/NaN → cs_sanitize_float
- [x] P2: hardcoded sleep(0.5) → cam_read() FOV poll
- [x] P2: g_gvc_ptr binary-address bug → LP+0x78 authoritative
- [x] Gemini 第二轮外审 3 条驳回 (Nagle/accept 阻塞/LWC 严重性) — 经 Opus 4.7 验证均为 false alarm 或定性夸张

### Archived CL entries (older than 14 days)

#### [v0.2.0] 46cb892 -- xiaoni -- Commit C: trajectory 3D preview
Hooks /api/trajectory/preview into view3d canvas. Preview 3D / Clear 3D
buttons; cyan path + start/end dots + yaw/pitch arrows + red playhead bisect.
UE Z-up -> canvas Y-up swap done in draw pass. 32 tests passed.

#### [v0.2.0] 2c0ea17 -- xiaoni -- Opus 4.7 round-2 review (5 items)
P0 cmd_queue per-slot ready flag. P1: 33rd-client pre-CreateThread check;
cam_patch_write error buffer after resume; g_cam_pov_mutex in tick+find.
P2 g_fexec_hook_count -> std::atomic<LONG>.

#### [v0.2.0] 1a10b3d -- xiaoni -- Opus 4.7 review sweep (13 items)
2 P0 (cmd_queue CAS, SuspendThread patch), 7 P1 (VirtualQuery cross-page,
zero-init, play/stop mutex, sanitize_float, pov sync, WSACleanup, EnumWindows),
4 P2 (BRIDGE_LOG, g_fexec_hook, 33rd socket, SwitchToThread).

#### [v0.2.0] 76cbd5a -- xiaoni -- Commit B: trajectory presets + 60 Hz player
orbit/helix/line/figure8 generators. TrajectoryPlayer 60Hz writer thread,
persistent _PokeSession, pause/resume/loop. 7 Flask routes. 26 tests.

#### [v0.2.0] (pending) -- xiaoni -- IGCS-style camera intercept (MVP)
camera_intercept.h: AOB scan + VirtualProtect byte-swap + cam_suspend_others.
TCP: __cam_intercept_install_aob/nop/pass/list/uninstall.

#### [v0.2.0] 8994179 -- xiaoni -- 老白 bug fix sweep
Batch 12-of-14: SEH on bare ptrs, g_cam_override_mutex, line_buf 1MB cap,
strtol path_delete, camera_path mutex, WSA lifecycle, overflow bound check,
sanitize_float, ClientSlot shutdown, SwitchToThread.

#### [v0.2.0] e2cd967 -- 主程序员 -- 3rdparty build tree sync
Applied equivalent P0/P1/P2 fixes to compiled tree (3rdparty/bridge/src/).
Both trees remain independent (CMake consolidation TBD).

#### [v0.2.0] Earlier CLs (c088120, d82c2b4, a403a51, 738ea13, 152fc53,
d37d007+5a050ec, 6879265, (prev pending), a0fe8c3, 373cf2b, 711d8eb,
aea22c7, 951ee30, stride-fix, PCE-fix, d32d2aa)
See git log for full details. All shipped to claudeMainBranch.

---
## Archived 2026-04-25 (超过 3 条 CL 限制)

### [v0.2.0] f82f461 -- xiaoni -- Fix capture marker orientation in 3D preview
- `web/templates/index.html` `draw3d()`: kept all vector math in game space; added `projGame(gx,gy,gz)` wrapper; rewrite capture-marker loop. Fixed fy/fz axis swap bug.

### [v0.2.0] a804214 -- xiaoni -- Unified 60Hz streaming for rdc-step + restore on any exit + decode fallback
- `trajectory_player.py`: unified rdc-step + preview into single 60Hz `interp_linear` loop; moved restore_pose to unified finally block.
- `web/routes/trajectory.py`: decode fallback globs `%TEMP%\RenderDoc\**\*.rdc`.

### [v0.2.0] 54cf28f -- xiaoni -- Uniform FOV marker size in 3D preview
- `draw3d()`: replaced per-point `fovLen*tan(fov/2)` with fixed `FOV_HALF_W/H` constants.

### [v0.2.0] 5e7e1aa -- xiaoni -- Fine path streaming + sparse captures + FOV/arrow 3D markers
- `trajectory_presets.py`: new `generate_smooth()` returning (fine_path, capture_indices) with FINE_PATH_SAMPLES=256.
- `web/routes/trajectory.py`: preview/play return capture_indices; 3D renderer shows amber dot + FOV frustum per capture.

### [v0.2.0] 9495fd1 -- xiaoni -- Speed-driven trajectories + Preview/Play/Stop row
- `trajectory_presets.py`: new `_path_length()` + speed->duration conversion; PRESET_SCHEMA uses speed.
- UI: rebuilt control row Preview|Play|Stop|Decode|Preview3D|ClearD; dropped Pause/Resume.

### [v0.2.0] c41089a -- xiaoni -- Manual Decode button + /api/trajectory/decode
- New `POST /api/trajectory/decode` endpoint; UI Decode button.

### [v0.2.0] 40acc76 -- xiaoni -- Post-loop auto-decode + restore start pose
- `web/state.py`: set/get_active_grabber(). Post-loop decode callback fires export_batch on background thread.
- `TrajectoryPlayer.play()`: snapshots + restores pose on any exit.

### [v0.2.0] 8ed197d -- xiaoni -- RDC-step capture_interval (16->16 captures land)
- `TrajectoryPlayer.play()`: new `capture_interval=1.5` param; loop poke->settle->capture->dwell.
- UI: `#capture_interval` input persisted in localStorage.

### [v0.2.0] 8554e66 -- xiaoni -- run_capture: launch-and-wait session mode
- `main.run_capture`: now launch+connect+block on stop_event only; all capture driven from UI.

### [v0.2.0] d03a98c -- xiaoni -- Configurable focus delay for Capture + Play
- UI: `#focus_delay` input + `_afterFocusDelay(fn)` helper; trajPlay() passes focus_delay to backend.

### [v0.2.0] f6c58ad -- xiaoni -- Remove legacy volume/snake/cone capture pipeline
- `main.py`: early-raise on run_capture; dropped volume/spacing/cone argparse + UI panels.

### [v0.2.0] afc35b5 -- xiaoni -- Batman ue3_packed_int deg conversion
- `game_profile.py`: `_deg_to_ue3_packed`/`_ue3_packed_to_deg`; write_camera + read_camera_pose use them.
- `trajectory_player.py`: `_PokeField.raw_type` for per-tick conversion.
- 4 new tests in `test_trajectory.py`.

### [v0.2.0] c656837 -- xiaoni -- Gemini review sweep + UI Phase 1 bug fixes
- Bridge: ascii_strtof/ascii_strtod; slot cleanup on client exit; g_smooth_factor atomic; cam_manager_alive() GC check.
- UI: fixed toggleAdvancedAob() scope; removed Lv2 menu Capture Area/Path/Cone items.

### [v0.2.0] 2325ee6 -- xiaoni -- UI Phase 1: debug refactor + custom trajectory + save/load + auto-preview
- Bridge Debug panel trimmed; Advanced section collapsed; Trajectory panel gets Save/Del/auto-preview.
- Backend: custom preset; /api/trajectory/save + saved/<name> GET/DELETE; 46 tests green.

### [v0.2.0] ee9a5db -- xiaoni -- Game library trim to 6 active titles
- `game_library.json`: 332->6 active titles; stub profiles for unreal_physics + black_myth_wukong.
