# Reverse Engineering Agent (小逆) — Shared Notes

## Active TODO

### 2026-04-17 (late) session handoff -- xiaoni -- Batman AK E2E 验证 + profile DB + Commit A pointer capture

**Session 成果（10 次 push）**:

1. `8994179` -- 老白 P0/P1/P2 bug sweep (12 of 14)
2. `2accaeb` -- docs/refCode/igcs/ (IGCS 32 款游戏参考源码)
3. `e9f764e` -- `camera_intercept.h` 基础设施 (AOB scan + VirtualProtect 字节 swap)
4. `79b64a5` -- 老白 peer review findings (2 x P1)
5. `e2cd967` -- 老白 sync 3rdparty/bridge/src tree
6. `06b88ca` -- 2 x P1 SEH hardening + C4505 cleanup
7. `c6e622d` -- UI: camera POV + intercept 按钮 + AOB install form
8. `def25e6` -- 游戏 hack profile 系统 (`configs/hacks/*.json` + drivers + Flask + UI dropdown)
9. `1fecdee` -- Hellblade (UE4) + Cyberpunk 2077 profile 加入 dropdown
10. `306395b` -- **Commit A: pointer capture + manual write (Batman 能推姿态)**

**Batman AK 实战验证通过** (用户实测):
- Desktop UI -> Profile dropdown 选 Batman -> Apply -> Lock
- `__cam_intercept_install_aob` 装上 60-byte block
- `__cam_intercept_nop` 切 NOP -> **镜头完全锁死**
- `__cam_intercept_pass` 还原 -> 游戏恢复控制
- 验证 IGCS AOB 直接可用，NOP-only 路径不需要 trampoline

**StackOBot AOB 定位记录** (CE 实测，手工未完成):
- UE5 LWC 用的是 `movups [reg+0],xmm0` + `movups [reg+10],xmm1`，非 IGCS 的 `movsd [reg+disp32]` 形式
- Hot site 在 `+0x75DA888` (count 14474): `rsi` 写 Location.X+Y + `rsi+10` 写 Z+Pitch
- 另外两个 rbx / rcx 写点 (各 7237 次) 未捕获，可能 Rot.Yaw/Roll / photomode / cutscene
- 手工 AOB 装第 2 个 site 对了位置，第 1 个 site AOB 不够独特匹配到 22 MB 外的无关位置
- **结论**: UE5 需要**自动探测**基于 `find_cam_pov` 反推 disp (下个 session)

**游戏数据库架构** (全部推送到 claudeMainBranch):
```
configs/hacks/
  _schema.md           -- JSON 字段文档
  batman_ak.json       -- UE3, 60 bytes, rbx, float coord + ue3_packed_int rot
  hellblade_ue4.json   -- UE4, 43 bytes, rdi, float coord + float rot
  stackobot_ue5.json   -- UE5 LWC, 3+4 bytes (split), rsi, double + double rot
  cyberpunk2077.json   -- REDengine 4, 26 bytes, rbx, float coord + quaternion rot (occurrence=2 TODO)

drivers/game_profile.py  -- load/apply/lock/unlock/uninstall + CLI
web_ui.py /api/hacks/*   -- list / apply / lock / unlock / uninstall
index.html debug panel   -- Profile dropdown + Apply/Lock/Unlock/Clear/Refresh 按钮
```

### 请老白 review 的两个点

1. **`camera_intercept.h` 整体架构评审**
   - AOB + VirtualProtect + SEH 全路径 (pattern_scan -> get_readable_ranges -> 页保护校验 -> SEH memcpy)
   - 16 sites cap / 64 bytes cap 是否合理
   - `cam_seh_memcpy` 隔离 __try 避免 C2712 (C++ 析构冲突) -- 这个手法可以吗
   - 老白之前 review 的 2 个 P1 全修了 (`06b88ca`)

2. **JSON schema 设计**
   - `configs/hacks/_schema.md` 字段清单
   - `intercepts[]` 支持 aob_literal + aob_wildcard + prefer，install 失败自动 fallback
   - `camera_write_profile` (暂时 disabled) 为下个 session 的 manual write 路径预留字段
   - occurrence 字段暂缺 (Cyberpunk 需要第 2 个 match) -- 下个 session 补

### 下个 session 路线图 (三连发)

**Commit A -- Pointer capture + Manual write** ✅ DONE in sha `306395b`

已实现全部内容，待用户实测验证：
- `CamMode` 枚举 + `cam_parse_base_reg` (ModRM 解析) + 29 字节 asm stub
- `g_cap_addr[CAM_INTERCEPT_MAX_SITES]` 稳定槽位
- 新 TCP 命令 `__cam_intercept_capture` / `__cam_intercept_get_capture` / `__cam_mem_poke`
- Python `capture_all` / `get_captured_addr` / `write_camera` / `mem_poke` + CLI `capture` / `get-capture` / `write`
- Flask `/api/hacks/capture` / `/get_capture` / `/write`
- UI "Capture" 行: Capture / Read Addr / 徽章 / Test 按钮
- Batman + Hellblade profile `camera_write_profile.enabled = true`

**已知限制 (留给下个 session)**:
- StackOBot 两个 site 只有 3 / 4 字节，< 14 无法装 CAPTURE。等 UE 自动探测 (Commit D) 合并成一个大 site
- UE3 packed_int 旋转 (16.16 fixed point) 当前直接 cast 浮点为 i32。Batman Test 写 `pitch/yaw/roll=0` 能验证 XYZ 通路，正确换算 `deg * (0x10000/360.0)` 放进轨迹层 (Commit B)
- Cyberpunk 2077 用四元数旋转，`camera_write_profile` 仍 disabled，需加 `quat_f32` 类型

**Commit B -- Trajectory presets + player**:
- `drivers/trajectory_presets.py`: 螺旋 / 绕环 / 直线 / 8 字 (参数化 generator)
- `drivers/trajectory_player.py`: 60Hz 循环插值 -> `write_camera()`
- UI: Trajectory 面板 (preset 下拉 + 参数 + Play/Stop)

**Commit C -- 3D editor integration** (用户强调的可视化):
- 现有 `view3d` canvas + trajectory.json 对接新轨迹系统
- Preset -> 3D 显示 waypoints -> 可拖拽调整 -> "Apply to Game" 开始 Play

**Commit D -- UE 自动探测 (StackOBot 并轨)**:
- 基于 `g_cam_pov_ptr - g_camera_manager_ptr = disp32`
- 扫 `.text` 里 `movups/movsd [reg + disp32], xmm?` 指令
- 识别连续 3-4 条 (x/y/z/w for LWC 或 x/y/z/float) 自动装 multi-site
- StackOBot 端到端就自动化了，无需 CE 手工

### 2026-04-17 汇报给老白 -- xiaoni -- IGCS intercept MVP 进度

Session focus this round:
  1. **DONE** 老白 bug fix sweep (12 of 14 review items) -- sha `8994179`.
  2. **DONE** Copy IGCS source to `docs/refCode/igcs/` -- sha `2accaeb`.
     Reference for the inline MOV-patch technique.
  3. **IN PROGRESS** Implement IGCS-style camera intercept -- current CL.
     Infrastructure done: `camera_intercept.h` + TCP commands +
     shutdown cleanup + `__bridge_status` reporting.

Decision recorded (per 老白 direction):
  - Keep current FName/GUObjectArray discovery. Actors / UWorld /
    LocalPlayer / CameraManager still found the same way.
  - Per-game AOB signatures acceptable (target-game list is small).
  - Starting with simple byte-swap (NOP game writes) instead of a
    full IGCS conditional-asm trampoline. Trampoline is a follow-up
    if NOPs corrupt anything.

Want feedback before next step on:
  - **(auto-discovery)** After `find_cam_pov` succeeds we know
    `camera_manager_ptr + cc_off + pov_x_off`. Scanning `.text` for
    `movsd [reg + <that disp32>], xmm0` should land us on the write
    site automatically. Worth doing next or wait for field data from
    StackOBot?
  - **(trampoline)** If NOPs break audio/animation (they shouldn't,
    but UE may read these fields after writing), do we go IGCS-full
    with a conditional asm stub, or just live with write-then-restore?
  - **(Slack bot practice target)** User plans to test this on a Slack
    Bot-exercised game today. Need a minimal driver-side recipe so
    the bot can: (a) install AOB, (b) flip nop/pass, (c) verify via
    `__bridge_status`.

### 主程序员 peer review: e9f764e (IGCS intercept infrastructure)

Overall: 架构合理，代码整洁。Opus 4.7 深度 review 共发现 13 个新问题：

- [x] **P1: camera_intercept.h:171 memcpy(site.orig, addr, size) 无 SEH** (spotted by 主程序员) —
  fixed in `06b88ca`: added CAM_READABLE_MASK protect check + cam_seh_memcpy SEH wrapper。

- [x] **P1: cam_patch_write() memcpy 无 SEH** (spotted by 主程序员) —
  fixed in `06b88ca`: write goes through cam_seh_memcpy。

**P0 — 崩溃 / 数据污染（Opus 4.7 deep review，2026-04-17）：**

- [ ] **P0: ue5_exec_hook.h cmd_queue 多生产者竞争** (spotted by 主程序员 Opus) —
  两个 TCP 客户端并发 `exec_console_command()` 时读到同一 `head`，写同一槽，各自 `InterlockedIncrement`。
  结果：命令丢失 + 槽内容混杂。修法：push 前加 CRITICAL_SECTION。

- [ ] **P0: cam_patch_write() patch 时未暂停游戏线程** (spotted by 主程序员 Opus) —
  `memcpy(addr, data, n)` 最多 64 字节写入时游戏线程可能正在执行该代码，x64 不保证多字节写原子性。
  修法：`SuspendThread` 所有游戏线程 → patch → `FlushInstructionCache` → `ResumeThread`。

**P1 — 功能/正确性（Opus 4.7 deep review）：**

- [ ] **P1: camera_intercept.h:166 VirtualQuery 未检查 size 跨页** (spotted by 主程序员 Opus) —
  若 `size` 跨页边界进入 PAGE_NOACCESS 页，`memcpy(site.orig, addr, size)` AV。
  修法：检查 `(uint8_t*)addr + size <= (uint8_t*)mbi.BaseAddress + mbi.RegionSize`。

- [ ] **P1: console_server.h InterpolatedCamera cam 未初始化** (spotted by 主程序员 Opus) —
  `cam` 是未初始化 POD；`tick()` keyframes<2 时 `return false` 不写 `out`，随后用 garbage 写入游戏内存。
  修法：`InterpolatedCamera cam = {};`。

- [ ] **P1: camera_path.h play()/stop() 未持有 m_mutex** (spotted by 主程序员 Opus) —
  `play()` 无锁读 `m_keyframes.size()`（UB vector race）；`stop()` 无锁写 `m_play_time`（data race with tick）。
  修法：加 lock_guard；`clear()` 内部调 stop 需加 `stop_unlocked()` 变体。

- [ ] **P1: __cam_mem_write 未做 NaN/Inf 过滤** (spotted by 主程序员 Opus) —
  `cs_parse_floats` 直接用 strtof，NaN/Inf 进 FMinimalViewInfo 导致相机矩阵崩溃。
  修法：对 vals[0..6] 跑 `cs_sanitize_float`（坐标 ±1e8，角度 ±360，FOV 1..179）。

- [ ] **P1: g_cam_pov_ptr 无同步** (spotted by 主程序员 Opus) —
  TCP 线程 `__cam_mem_find` 清空指针再重扫，tick 线程可能在 if/write_camera_mem 之间读到被清零的指针。
  修法：`std::atomic<uint8_t*>` 或 rescan 前停 tick 线程。

- [ ] **P1: ConsoleServer_Stop WSACleanup 时序** (spotted by 主程序员 Opus) —
  WaitForSingleObject 1s 超时后 CloseHandle 但线程仍活，WSACleanup 清零引用计数，
  存活线程再调 closesocket → WSANOTINITIALISED UB。
  修法：等所有客户端线程退出后再 WSACleanup。

**P2 — 次要/代码质量（Opus 4.7 deep review）：**

- [ ] **P2: BRIDGE_LOG vsnprintf truncation 数学错误** (spotted by 主程序员 Opus) —
  vsnprintf 截断返回"本应写入数"而非实际写入数，`buf[total]='\n'` 可能越界。
  修法：clamp n: `int nc = (n<0||n>=(int)(sizeof(buf)-prefix_len-2)) ? (int)(sizeof(buf)-prefix_len-3) : n;`

- [ ] **P2: g_fexec_hook_count 非原子递增** (spotted by 主程序员 Opus) —
  plain `int++` 竞争游戏线程 hook 分发。修法：填满 entry 后再 `InterlockedIncrement`。

- [ ] **P2: 第 33 个客户端 socket 泄漏** (spotted by 主程序员 Opus) —
  slots 满时 `CloseHandle(h)` 但未 `closesocket(c)`，线程持有 socket 永不释放。

- [ ] **P2: ue5_scan_engine.h Sleep(100) 违反 no-sleep.md** (spotted by 主程序员 Opus) —
  用于协作让步但违反项目规则。修法：换成 `SwitchToThread()`。

两个 P1 修复后 camera_intercept.h 可用于生产。
回答小逆的问题:
  - **auto-discovery**: 值得做，但先用 StackOBot 验证手动 AOB 流程，确认 nop 不 crash 再做。
  - **trampoline**: 先试 NOP 路线；UE5 POV 字段只在 UpdateCamera 写，不会被读，NOP 应安全。
  - **driver-side recipe**: 见 drivers/ue5_console.py — 加 `cam_intercept_install_aob()` / `cam_intercept_nop()` 包装方法即可，与现有 `_send_cmd()` 机制一致。

### 当前 session (from 主程序员 + 老白)

- [ ] **P0: UpdateCamera 覆写 -- 正确解法: 渲染线程边界 hook**
  - UpdateCamera() 每帧写回玩家摄像机位置，无法从外部争抢
  - 正确解: hook `ULocalPlayer::GetViewPoint` (virtual, hookable via vtable)
  - GetViewPoint 在渲染线程 FSceneView 构建前被调用，是数据流进渲染器的最后门
  - UE4SS 方案: `RegisterHook("Function /Script/Engine.LocalPlayer.GetViewPoint", ...)`
  - 我们方案: 找 LP vtable 中 GetViewPoint 的 slot，VirtualProtect + 写钩子函数
  - 钩子直接返回 g_cam_override_state，完全跳过 UpdateCamera 写的 POV
  - 注意: vtable index 因 UE 版本而异，需从 UE4SS PDB 数据或运行时扫描确定

- [ ] **P0: ue5_engine.h 文件拆分** (from 老白) -- DONE in current commit
  - [x] 拆成 ue5_scan_engine.h / ue5_scan_world.h / ue5_scan_camera.h / ue5_exec_hook.h / ue5_actions.h
  - 主文件 430 行 (原 3839 行), 最大子文件 ~1237 行

- [ ] **P0: 真实 UE5 游戏端到端验证** — StackOBot test in progress. Bridge finds GEngine/UWorld/LP/CameraManager. Next: rebuild DLL, run __cam_mem_find, confirm scan fallback finds POV.

### 代码 bug（from 主程序员 review，基于 claudeMainBranch）

- [x] **P0: 3rdparty/bridge/src/ 与 renderdoc/renderdoc/core/bridge/ 双树分叉** (spotted by 主程序员) — 老白 的 bug sweep (commit 8994179) 全部修在 renderdoc 树，但实际 CMake 构建目标是 3rdparty/bridge/src/bridge.cpp，该文件无任何修复。主程序员已同步全部 P0/P1/P2 修复到 3rdparty 树（直接修 ue5_engine.h + camera_path.h + bridge.cpp），见下方 CL。两树仍独立存在，建议小逆在后续 PR 中删除其中一棵或通过 target_include_directories 统一来源。

- [x] **P0: line_buf 无大小上限** (spotted by 主程序员) — fixed in pending CL: 1 MB cap + explicit disconnect + split recv close/error.

- [x] **P1: recv() 错误和关闭未区分** (spotted by 主程序员) — fixed in pending CL: n==0 logs close, n<0 logs WSAGetLastError() (skips WSAECONNRESET/WSAEINTR).

- [x] **P1: `__path_delete` atoi 整数溢出** (spotted by 主程序员) — fixed in pending CL: strtol + bounds [0, 10000].

- [x] **P1: camera_path.h count()/list_keyframes()/tick() 无 mutex** (spotted by 主程序员) — fixed in pending CL: m_mutex -> mutable, lock_guard on count/list/visualize/tick/total_duration; added total_duration_unlocked() helper.

- [x] **P1: ClientArg CreateThread 失败泄漏** (spotted by 主程序员) — fixed in pending CL: delete arg + closesocket on CreateThread failure.

- [x] **P2: cs_smooth_initialized 数据竞争** (spotted by 主程序员) — fixed in pending CL: std::atomic<bool>.

### Opus 4.7 深度 review (2026-04-17, by 主程序员)

**P0 新发现：**

- [x] **P0: ue5_scan_engine.h:154 裸指针解引用无 SEH** (spotted by 主程序员 4.7 review) — fixed in pending CL: seh_read_ptr on string-xref candidate.

- [x] **P0: ue5_scan_engine.h:248 同样裸解引用** (spotted by 主程序员 4.7 review) — fixed in pending CL: seh_read_ptr on manual-offset deref.

- [x] **P0: ue5_scan_camera.h:445 + :799 FField 链裸解引用** (spotted by 主程序员 4.7 review) — fixed in pending CL: added seh_read_u32_ok helper; wrapped cls+0x18 reads in find_cam_pov and find_camera_manager_via_lp.

- [x] **P0: g_cam_override_state 多线程撕裂读写** (spotted by 主程序员 4.7 review) — fixed in pending CL: g_cam_override_mutex guards every read/write; tick snapshots under lock then writes to FMinimalViewInfo outside it.

**P1 新发现：**

- [x] **P1: console_server.h:652 Sleep(5000) 违反 no-sleep.md** (spotted by 主程序员 4.7 review) — fixed in pending CL: module-size-stability poll (3 stable samples @ 500 ms, 30 s cap).

- [x] **P1: console_server.h 无 WSAStartup** (spotted by 主程序员 4.7 review) — fixed in pending CL: WSAStartup at entry of cs_server_main, WSACleanup at exit (ref-counted, safe).

- [ ] **P1: ue5_actions.h:85 + ue5_exec_hook.h:294 重复 EnumWindows 代码** (spotted by 主程序员 4.7 review) — not done; cosmetic refactor, kept on TODO.

- [x] **P1: ue5_exec_hook.h:346 cmd_queue 生产者无溢出保护** (spotted by 主程序员 4.7 review) — fixed in pending CL: check (head - tail) >= CMD_QUEUE_MAX and drop with log.

**P2 新发现：**

- [x] **P2: console_server.h:429/445/487 strtof 返回 INF/NaN 未拦截** (spotted by 主程序员 4.7 review) — fixed in pending CL: cs_sanitize_float applied to __cam_speed / __smooth / __path_play.

- [x] **P2: console_server.h:892 client thread shutdown 不彻底** (spotted by 主程序员 4.7 review) — fixed in pending CL: ClientSlot tracks SOCKET+HANDLE; shutdown(SD_BOTH) before WaitForSingleObject.

- [ ] **P2: CL 条目缺失** (spotted by 主程序员 4.7 review) — `c088120 "Remove ToggleDebugCamera; split ue5_engine.h; bump tick to 1000Hz"` 在 SHARED.md 里仍是 `(pending push)`，已 push 应填实际 sha。`43ac097 "Add ref/ to .gitignore"` 完全无 CL 条目。按 versioning.md 规则补上。

### UUU 功能复刻 (from 小由 2026-04-05, 老白 confirmed)

- [ ] **P0: per-node FOV 支持** — 路径每个关键帧可以设不同 FOV，播放时线性插值
- [ ] **P0: 播放时长控制** — `__path_play <total_seconds>` 参数控制总播放时间
- [ ] **P0: Loop 播放** — `__path_loop 1/0` 命令
- [ ] **P0: 暂停/恢复** — `__path_pause` / `__path_resume`
- [ ] **P0: 当前位置查询** — `__camera_get` 返回当前 pos/rot/fov

### 其他

- [ ] **P0: Path D 逆向补全** — pass 2 now scans PC+[0x100..0x800] for exact manager ptr. On next run, log "PC+0xXXX == Path-A manager [XVAL OK]" -- update k_layout_ue57.pc_pcm_start/end to that discovered offset.
- [ ] **P1: AC 预检脚本** — 检测 EasyAntiCheat.dll / BEService.exe
- [ ] **P2: _detect_bridge 无重试** (spotted by 主程序员) — 加 2-3 次指数退避重试。
- [x] **P2: hardcoded sleep(0.5)** (spotted by 主程序员) — fixed: replaced with cam_read() FOV poll.
- [ ] **P2: 增强 Pause** — 加 UWorld::IsPaused 内存写入 fallback
- [x] **P2: g_gvc_ptr binary-address bug** — fixed in d82c2b4: always compare GEngine+0x200 with LP+0x78; if they differ, LP wins (raw ptr, authoritative).

## [v0.2.0] UUU / UE4SS Camera Research

**UUU (Universal Unreal Engine Unlocker) approach:**
- AOB scan for GEngine (not GUObjectArray) -- narrower but works
- PlayerController via GEngine->GameViewport->LocalPlayer->PlayerController chain
- APlayerCameraManager via PlayerController at a fixed offset (~0x2A8 UE5.x)
- Free camera: background thread writes Location/Rotation/FOV to CameraCachePrivate.POV at ~60Hz
- `UpdateCamera(float)` on APlayerCameraManager is NOT a C++ virtual -- CANNOT vtable-hook it
- UUU's approach is identical to ours (background write). Our GUObjectArray+FName scan is more robust.

**UE4SS community approach:**
- Lua `RegisterHook("Function /Script/Engine.Actor.CalcCamera", ...)` hooks UFUNCTION (slow, Lua overhead)
- `RegisterHook` on PlayerTick to set actor location per-tick (BP-level, not as direct as POV write)
- `PlayerController.PlayerCameraManager` via FField reflection (same as our ffield_find_offset)
- `ULocalPlayer::GetViewPoint(FMinimalViewInfo&)` IS virtual (UE4SS template line 1226-1227)
  and is called by renderer before FSceneView construction -- possible hook point (no race condition)
  but vtable index calculation requires counting full AActor+UPlayer+ULocalPlayer chain (~100+ entries)

**Conclusion: current 60Hz write approach is correct and industry-standard.**
Race condition fix = use timestop (g_paused) before capture sequence. With game paused,
UpdateCamera stops running, our write wins trivially. No vtable hook needed for offline capture.

**Compile fix:** duplicate `static std::atomic<bool> g_camera_override` at ue5_engine.h:294 and 2120
-- removed second declaration (would cause C++ redefinition error).

## [v0.2.0] Bridge DLL Architecture

Bridge DLL (`3rdparty/bridge/`): TCP 9998, GEngine string-xref scan, Exec() vtable, Camera path (Catmull-Rom + SLERP), timestop, HUD toggle, hotsampling.

Driver: `ue5_console.py` auto-fallback bridge:9998 → UUU:1985, `_detect_bridge()` via `__bridge_ping`.

### Camera Control Methods
- **Bridge DLL** — 注入 + console exec (UE4/UE5, 无反作弊)
- **External Memory** — ReadProcessMemory (绕 user-mode AC)
- **Cheat Engine** — 手动找 offset

### GEngine Scanner
8 个锚点 (5 wide + 3 ASCII, 含 UEVR 验证), 引擎通用 pattern, 无需 per-game 数据库。

## Changelog (latest)

### [v0.2.0] (pending push) -- xiaoni -- Commit B: trajectory presets + 60 Hz player

Builds on Commit A (`306395b`, IGCS-style pointer capture). Streams
parametric camera trajectories to the captured camera struct at 60 Hz.

**New files**:
- `drivers/trajectory_presets.py` -- `orbit / helix / line / figure8`
  generators. Returns `list[PosePoint]` in game-space (UE convention:
  Z up). Each preset is parameterized (center, radius, height, turns,
  duration, samples, fov) and has an auto-look-at-center option that
  solves yaw/pitch from camera position. Shared helpers: `generate()`
  dispatcher used by the Flask API, `interp_linear()` with bisection
  lookup + shortest-path yaw wrapping, `total_duration()`.

- `drivers/trajectory_player.py` -- `TrajectoryPlayer` class owns one
  background writer thread that ticks at configurable rate (default
  60 Hz). Per-tick: interpolate the current `t` -> pose, poke each
  field of the camera struct over a **persistent** TCP session
  (`_PokeSession`, reuses one socket for the full playback to avoid
  420 connect/close/s). Profile offsets + types are baked once at
  `play()` time into a `_PokeField` plan. Supports pause / resume /
  loop, aborts after 8 consecutive poke failures, exposes live
  `status()` (state, t, ticks, writes_ok/fail, last_pose). Module
  singleton `get_default_player()` backs the Flask routes.

- `tests/test_trajectory.py` -- 26 tests: preset geometry
  (circle-on-radius, helix monotonic rise, line endpoints, figure-8
  passes through center), interpolation (midpoint, clamping, yaw
  shortest-path at 350->10 seam, bisect on dense orbit),
  `_PokeSession` wire format verified against a local echo server.

**Modified**:
- `web_ui.py`: seven new routes under `/api/trajectory/*`:
  `presets` (+ schemas for UI form rendering), `preview` (no-play
  generation for 3D viz), `play`, `stop`, `pause`, `resume`, `status`.
  Validates `profile_id` slug for path-traversal, maps ValueError ->
  400, RuntimeError (already running) -> 409, FileNotFoundError -> 404,
  ConnectionError -> 503.

- `web/templates/index.html`: new "Trajectory" row in the Debug panel
  with preset dropdown, per-preset dynamic form rendered from
  `PRESET_SCHEMA` (vec3 / num / int / bool / choice), rate + loop
  inputs, Play/Pause/Resume/Stop buttons, live status banner polled
  every 500 ms while not idle. Reuses the existing game-profile
  dropdown to pick which game to stream to.

**Known limitations (carried to Commit C/D)**:
- No 3D visualization of the generated path yet -- `/api/trajectory/preview`
  returns all sampled points ready for the `view3d` canvas overlay
  (Commit C wires it up).
- UE3 packed-int rotation (Batman) still casts pitch/yaw/roll floats
  verbatim to i32 at the bridge layer. Correct `deg * (0x10000/360)`
  conversion not yet in the player; pass rotations 0 for first test.
- Cyberpunk 2077 (quaternion rotation) `camera_write_profile` remains
  disabled -- player rejects profiles with `enabled: false`.
- StackOBot multi-site captures (3/4 byte sites < 14 threshold) wait
  for Commit D UE auto-discovery.

**Tests**: `pytest tests/test_trajectory.py -v` -> 26 passed.

### [v0.2.0] (pending push) -- xiaoni -- IGCS-style camera intercept (MVP)

**New file**: `renderdoc/renderdoc/core/bridge/camera_intercept.h`

Motivation: `APlayerCameraManager::UpdateCamera()` writes player-follow
position into `FMinimalViewInfo` every frame, racing with our 1000 Hz
tick. Instead of racing, patch the game's own MOV instruction(s): swap
to NOPs when we want to block the game's writes, swap back when we
want it to drive.

Key decision (confirmed by 老白): **keep the entire existing discovery
pipeline**. GEngine / UWorld / ULocalPlayer / APlayerCameraManager are
still located via string-xref + GUObjectArray + FName. We still plan to
walk actors with the same infrastructure. The intercept module replaces
only the 1000 Hz override mechanism.

Design mirrors IGCS Hellblade (UE4) reference at
`docs/refCode/igcs/Cameras/Hellblade/InjectableGenericCameraSystem/`:
 - AOB-scan the game's write instruction in `.text`.
 - `VirtualProtect(PAGE_EXECUTE_READWRITE)` + `memcpy` + restore +
   `FlushInstructionCache`. Per-site original bytes saved so toggles
   between `pass` / `nop` are reversible.
 - Not using MinHook / Detours / inline trampoline generation yet --
   simpler byte-swap first. Conditional asm trampoline is a follow-up
   if per-game NOP turns out to corrupt game state.

TCP commands (new):
  - `__cam_intercept_install_addr <hex_addr> <size> [name]`
  - `__cam_intercept_install_aob <size> <name> | <AOB hex>`
  - `__cam_intercept_nop`       (override ON -- block game writes)
  - `__cam_intercept_pass`      (override OFF -- restore originals)
  - `__cam_intercept_list`
  - `__cam_intercept_uninstall` (restore + clear list; also runs on DLL shutdown)

`__bridge_status` now reports `intercept_sites=N intercept_nopped=0/1`.

Not yet implemented (intentional scope):
  - Auto-discovery of the write instruction from known
    `g_camera_manager_ptr + cc_off + pov_x_off`. Currently per-game AOB
    must be supplied from UI / config.
  - Conditional asm trampoline (IGCS's `cameraStructInterceptor` PROC
    with `g_cam_override_state` writes inside the asm). Byte-swap first.
  - Integration with path playback: tick-thread path writes still go
    through `write_camera_mem` unchanged. Once an intercept site is in
    nop mode, the game doesn't fight those writes any more.

Expected usage from UI side (xiaoyu to wire up):
  1. Call `__cam_mem_find` as today -- confirms camera POV pointer.
  2. For target game, pass the AOB (found offline in CE/x64dbg) +
     byte-count via `__cam_intercept_install_aob`.
  3. Before path playback: `__cam_intercept_nop` + `__cam_mem_on`.
  4. After playback: `__cam_intercept_pass` (hand control back to game).
  5. DLL unload or `__cam_intercept_uninstall` cleans up.

### [v0.2.0] 8994179 -- xiaoni -- 老白 bug fix sweep

Batch fix of 主程序员 review (base + Opus 4.7 deep review). All listed
P0 / P1 / P2 items marked completed in the TODO section above.

P0 crashes & races:
- `ue5_scan_engine.h`: wrap `*(void**)resolved` (string-xref) and
  `*(void**)addr` (manual-offset) with `seh_read_ptr`. Uncommitted pages
  in DRM/AC-modified modules no longer take the whole process down.
- `ue5_scan_camera.h`: add `seh_read_u32_ok` helper in `ue5_engine.h`;
  replace bare `*(uint32_t*)(cls+0x18)` FName loads in `find_cam_pov`
  and `find_camera_manager_via_lp` so a torn class-chain step logs
  `<av>` instead of faulting.
- `console_server.h`: add `g_cam_override_mutex` (declared next to
  `g_cam_override_state` in `ue5_scan_camera.h`). Tick thread snapshots
  the struct under lock before pushing to FMinimalViewInfo; TCP
  `__cam_mem_write` updates it under the same lock. No more mid-struct
  torn writes feeding NaN into the camera.
- `console_server.h` client handler: cap `line_buf` at 1 MB (was
  unbounded), split `recv <= 0` into explicit close (`n == 0`) vs
  error (`n < 0` with `WSAGetLastError`).

P1:
- `__path_delete`: switch `atoi` -> `strtol` with explicit bounds
  `[0, 10000]`; rejects `INT_MAX+1` etc.
- `camera_path.h`: make `m_mutex` mutable, add `lock_guard` to
  `count()`, `list_keyframes()`, `visualize()`, `tick()`, and the
  public `total_duration()`. Introduced `total_duration_unlocked()`
  for callers that already hold the lock.
- `console_server.h`: clean up `ClientArg` + `closesocket(c)` on
  `CreateThread` failure.
- `console_server.h`: replace `Sleep(5000)` engine-scan preamble with
  a module-size-stability poll (3 consecutive stable samples,
  500 ms cadence, 30 s cap). Per `.claude/rules/no-sleep.md`.
- `console_server.h`: call `WSAStartup`/`WSACleanup` inside
  `cs_server_main` instead of relying on RenderDoc's `Network::Init()`
  ordering.
- `ue5_exec_hook.h`: bound-check `cmd_queue` before push
  (`head - tail >= CMD_QUEUE_MAX` => drop with log). Prevents silent
  overwrite when game thread is paused on a loading screen.

P2:
- `cs_smooth_initialized` -> `std::atomic<bool>`.
- `__cam_speed` / `__smooth` / `__path_play` run incoming floats
  through `cs_sanitize_float` (rejects NaN/INF and out-of-range).
- Client-thread shutdown now records the SOCKET alongside the HANDLE
  and calls `shutdown(SD_BOTH)` on each before `WaitForSingleObject`,
  so a recv-blocked client does not leak its handle past the timeout.

Notes / deferred:
- P1 EnumWindows dedup in `ue5_actions.h` + `ue5_exec_hook.h`: not
  done (cosmetic; separate refactor).
- CL 条目缺失 for `c088120` / `43ac097`: still pending.

### [v0.2.0] (pending push) -- 主程序员 peer review: 3rdparty build tree sync

Review of commit 8994179 (老白 P0/P1/P2 bug sweep) found that ALL
fixes were applied to `renderdoc/renderdoc/core/bridge/` only.
The actual CMake build target (`3rdparty/bridge/src/bridge.cpp`) includes
`ue5_engine.h`, `camera_path.h`, `pattern_scan.h` from `3rdparty/bridge/src/`
-- none of the renderdoc fixes were in the built DLL.

Applied equivalent fixes to the 3rdparty build tree:

**3rdparty/bridge/src/ue5_engine.h (P0 SEH)**
- Line 218: bare `*(void**)resolved` in string-xref scan -- wrapped in
  `__try/__except` block (inline, same pattern as seh_read_ptr).
- Line 274: bare `*(void**)addr` in `find_gengine_via_offset` -- wrapped
  in `__try/__except`; AV now logs and returns false instead of crashing.

**3rdparty/bridge/src/camera_path.h (P1 mutex)**
- `m_mutex` -> `mutable std::mutex`
- `count()`: add lock_guard
- `tick()`: add lock_guard + call total_duration_unlocked()
- `total_duration()`: add lock_guard + call total_duration_unlocked()
- `list_keyframes()`: add lock_guard
- `visualize()`: add lock_guard
- Added private `total_duration_unlocked()` helper

**3rdparty/bridge/src/bridge.cpp (P1/P2)**
- `g_smooth_initialized`: bool -> `std::atomic<bool>` (P2)
- `__smooth` float: add NaN/INF/range check before storing (P2)
- `__cam_speed` float: add NaN/INF/range check (P2)
- `__path_play` float: add NaN/INF/range check (P2)
- `__path_delete`: atoi -> strtol + bounds [0, 10000] (P1)
- `line_buffer`: cap at 1 MB before append; disconnect on overflow (P1)
- Client socket tracking: `g_client_socks` vector + mutex; registered
  on connect, erased on disconnect. `shutdown()` calls `shutdown(SD_BOTH)`
  on all before joining server thread (P1 recv-blocked thread leak)
- Added `#include <algorithm>` and `#include <cmath>`

Remaining open items:
- Two trees still independent (CMake build-system decision TBD by 小逆)
- EnumWindows dedup in renderdoc tree (cosmetic, deferred)
- cmd_queue overflow comparison: `(LONG)(head - tail)` should be `(ULONG)` to
  avoid UB when head/tail wrap past INT_MAX (P2, theoretical, ~2B ops)

### [v0.2.0] (pending push, earlier) -- xiaoni
- **Remove ToggleDebugCamera logic**: all `g_debug_camera_active` code removed from
  `ue5_engine.h`, `console_server.h`, `ue5_console.py`, `test_camera_path.py`.
  Shipping games have no ToggleDebugCamera; debug PCM approach is dev-build-only.
  Removed `__cam_toggle`, `__cam_debug_on`, `__cam_debug_off` bridge commands.
- **Tick thread bumped to 1000 Hz** (`Sleep(1)` was `Sleep(16)`): writes 16x per
  game frame vs UpdateCamera's 1x. Temporary mitigation until GetViewPoint hook.
  UpdateCamera root cause documented: correct fix is ULocalPlayer::GetViewPoint vtable
  hook (virtual, called at game-to-render boundary, bypasses UpdateCamera entirely).
- **ue5_engine.h split** (3839 -> 430 lines): implementation extracted into 5
  sub-headers included in order from ue5_engine.h:
  - `ue5_scan_engine.h` (1218 lines): GEngine, GUObjectArray, FNamePool, FExec vtable
  - `ue5_scan_world.h` (379 lines): UWorld, ULocalPlayer
  - `ue5_scan_camera.h` (1237 lines): PCM, cam_pov, R/W, cross-validation
  - `ue5_exec_hook.h` (472 lines): FExec multi-hook, console exec, gamethread dispatch
  - `ue5_actions.h` (129 lines): timestop, HUD, free camera, hotsampling

### [v0.2.0] 1089807 -- xiaoni
- **Fix camera not moving (without slomo)**: correct approach is debug PCM.
  `slomo` is unreliable in cracked/modified games (TimeDilation may be disabled).
  UUU-style fix: ToggleDebugCamera creates a debug PCM with no `UpdateCamera()`
  position lock; writing to IT persists across frames. Original PCM is locked to
  player position every frame.
- `find_camera_manager()`: when `g_debug_camera_active && n_candidates > 1`,
  select **NEWEST** (highest GUA index) candidate = debug PCM. Was always selecting
  oldest (original position-locked PCM).
- `cross_validate_camera()`: when `g_debug_camera_active && A != D`, **keep A**
  (debug PCM). D scans LP+0x30 which may still point to original PC in UE5.7
  (LP not updated by ToggleDebugCamera); D returns original PCM = wrong.
- **New bridge commands**: `__cam_debug_on` / `__cam_debug_off` (idempotent).
  Only toggles if state differs; replies `camera_active=0/1`. Caller runs
  `__cam_mem_find` after enable so PCM re-selection takes effect.
- **Driver**: `cam_debug_on()` / `cam_debug_off()` methods.
  `enable_debug_camera()` now uses `cam_debug_on()` (idempotent) for bridge.
- **test_camera_path.py**: removed slomo. Calls `cam_debug_on()` + `cam_find()`
  before building path. Path starts from debug PCM position.

### [v0.2.0] d82c2b4 -- xiaoni
- **Fix camera not moving: slomo before path play** (`tools/test_camera_path.py`):
  Root cause: `APlayerCameraManager::UpdateCamera()` runs every game frame and
  writes the player-follow position back to CameraCachePrivate.POV -- the same
  address our 60 Hz tick writes to. Game wins the race; camera stays at player pos.
  Fix: issue `slomo 0.0001` before `path_play()`. At 1/10000 speed UpdateCamera
  runs ~once per 167s; our 60 Hz tick dominates every rendered frame.
  Speed restored to 1.0 after path ends or Ctrl+C.
  Added `--no-slomo` flag for debug-camera-active scenarios (debug PCM has no
  position lock, so no competition).
- **Fix: GVC TObjectPtr detection extended to DLL range** (`ue5_engine.h`):
  Previous check only caught GVC values in main EXE range. In StackOBot,
  `GEngine+0x200 = 0x7FF457799DF8` is in a DLL range below the EXE base --
  old check missed it, `g_gvc_ptr` got the fake value, LP cross-check logged
  spurious MISMATCH, GVC-world update used wrong world causing GEngine FExec
  crash on every subsequent command.
  Fix: always read `LP+0x78` (raw ptr, UE4SS verified). If LP GVC != GEngine GVC,
  adopt LP's value. `g_gvc_ptr` now equals `LP+0x78` so `verify_lp_via_gvc()` confirms.

### [v0.2.0] a403a51 -- xiaoni
- **Fix crash: Path D "CameraManager" filter** (was "Camera"):
  After `ToggleDebugCamera`, `LP+0x30` -> `DebugCameraController`.
  Path D was finding `DebugCameraHUD` (class contains "Camera") at
  `DebugCameraController+0x388`. cross_validate switched to DebugCameraHUD.
  Camera tick thread then wrote LWC doubles into DebugCameraHUD memory at
  +0x360 (valid heap, no AV), corrupting internal HUD data -> fatal crash.
  Fix: both pass 1 and pass 2 of `find_camera_manager_uuu_style()` now
  require "CameraManager" substring. APlayerCameraManager and all BP subclasses
  match; HUDs, components, controllers do not.
- **Fix: FOV validation before A->D switch** in `cross_validate_camera()`:
  Before switching from A (FName-found) to D (PC-direct), read D's direct-offset
  FOV and validate it is in [1,179] and finite. If invalid, keep A.
  Defense-in-depth against future false positives from Path D.
- Root cause of fatal error confirmed: writing to wrong UObject (DebugCameraHUD)
  at camera POV offsets = silent memory corruption + crash seconds later.

### [v0.2.0] 738ea13 -- xiaoni
- **Fix: GVC TObjectPtr encoding** (g_gvc_ptr binary-address P2 bug):
  `GEngine+0x200` on StackOBot UE5.7 returns `0x7FF3E2BA9DF8` (inside game binary),
  which is a TObjectPtr-encoded handle, not a heap object pointer.
  Fix: `validate_engine_viewport_chain()` now checks if GVC is in `[module_base,
  module_base+size)`. If yes, falls back to `LP+ulp_vc_off` (always raw pointer,
  confirmed UE4SS layout). LP cross-check will now pass.
- **k_layout_ue57 pc_pcm range**: updated to 0x388-0x398 (VERIFIED: PC+0x390 from
  Path D pass-2 run, A==D [XVAL OK]).

### [v0.2.0] 152fc53 -- xiaoni
- **Path D: direct ptr scan fallback for UUU cross-validation**:
  `find_camera_manager_uuu_style()` now has two passes:
  - Pass 1: FName class check in layout-defined range [pc_pcm_start..pc_pcm_end]
  - Pass 2: scan PC+[0x100..0x800] step=8 for exact `g_camera_manager_ptr` value.
    When found: logs "PC+0xXXX == Path-A manager [XVAL OK]" -- use that offset to
    tighten future pc_pcm range in layout struct.
  User requirement: "UUU cross-validation must succeed, not 'known limitation'".
  Fix: pass 2 is definitively correct regardless of FName range or TObjectPtr encoding.
- `cross_validate_camera()`: logs "A==D [XVAL OK]" when pass-2 confirms Path A.
- k_layout_ue57: pc_pcm_end extended 0x380 -> 0x500 (wider pass-1 coverage).
- Design confirmed: per-game UEVersionLayout is correct approach (hardcode offsets
  from reversing); scan fallback only when no game-specific config available.

### [v0.2.0] d37d007 + 5a050ec -- xiaoni
- **CRITICAL FIX: FMinimalViewInfo double layout (UE5 LWC)**:
  UE5 FVector/FRotator are double (8B each), not float. All camera read/write was
  using wrong offsets and types. Fixed:
  - CameraMemState: x/y/z/pitch/yaw/roll now double
  - g_cam_pov_is_lwc flag: set when POV found, used in read/write/scan
  - find_cam_pov(): tries 3 POV-in-cache offsets (+0x08 LWC, +0x10 SIMD-float, +0x04)
    with matching FOV offsets (+0x30 LWC, +0x18 float)
  - find_cam_pov_scan(): split into find_cam_pov_scan_pass(is_lwc).
    LWC pass (step=8, doubles) tried first; float pass (step=4) as fallback.
  - read/write_camera_mem(): branch on g_cam_pov_is_lwc
- **docs/ue_memory_layout.md**: New reference document covering all memory offsets
  used by bridge DLL across UE4/UE5, with verification status per game.

### [v0.2.0] 6879265 -- xiaoni
- **find_cam_pov_scan()**: FField reflection fallback. When CameraCachePrivate is not reflected
  (StackOBot: FField chain ends after 1 prop "PCOwner"), scans manager+0x200..+0x900 in 4-byte
  steps for valid 7-float FMinimalViewInfo pattern (FOV[1,179], Pitch[-91,91], all finite).
  Logs all candidates; picks first valid. Added forward declaration.
- **GVC world locking**: set g_world_from_gua=true in all three paths (adopt/confirm/mismatch)
  inside validate_engine_viewport_chain(). Prevents FExec sublevel-world spam after GVC confirms.
- **ffield_find_offset_era() verbose logging**: walked counter, AV log, chain-end log.

### [v0.2.0] (previously pending) -- xiaoni
- **UUU/UE4SS camera research**: confirmed background 60Hz POV write is industry standard (same as UUU).
  `UpdateCamera` is NOT virtual, vtable hook not applicable. Race condition fix = use timestop.
- **Fix: duplicate `g_camera_override` declaration** (ue5_engine.h:2120) -- second `static std::atomic<bool>
  g_camera_override{false}` removed; would cause C++ redefinition error at compile time.
- **Path + mem integration**: camera path tick now writes directly to `g_cam_override_state` +
  `write_camera_mem()` when `g_cam_pov_ptr` is available, falling back to console commands otherwise.
  Camera path no longer requires DebugCamera when direct memory path is active.
- **Path D (UUU-style fixed-offset probe)**: `find_camera_manager_uuu_style()` -- probes PC at 16
  offsets (0x2A0-0x380, 8-byte steps) and checks class FName for "Camera" substring. Covers full
  UE5.00-5.07 range (offset drifts upward each minor version). Used for cross-validation only;
  Path B (FField) is authoritative.
- **LP -> GVC cross-check**: `verify_lp_via_gvc()` -- confirms `g_localplayer_ptr` by reading
  `LP+0x78` (ULocalPlayer::ViewportClient) and comparing with `g_gvc_ptr` saved from GVC chain.
  Stable UE5 offset: UE4SS MemberVarLayout_5_07 confirmed ViewportClient=0x78.
- `g_gvc_ptr` global saves GVC from `validate_engine_viewport_chain()` for reuse.
- `cross_validate_camera()` now runs ALL four paths (A/B/C/D) and logs agreement/disagreement.
  Priority B > A > D. Logs B==D or B!=D to confirm/deny UUU's claimed PCM offset for this game.

### [v0.2.0] a0fe8c3 -- xiaoni
- **Direct FMinimalViewInfo camera override** (complete implementation):
  - `find_cam_pov()`: walks `UClass::ChildProperties` (FField linked list) at runtime
    to find `CameraCachePrivate` offset; no PDB, no hardcoded per-game offsets.
  - Handles two UE5 FField eras (UE4SS PDB verified):
    UE5.00-5.02 (Next=+0x20, Name=+0x28, Offset_Internal=+0x4C);
    UE5.03-5.07 (Next=+0x18, Name=+0x20, Offset_Internal=+0x44).
    Key fix: `UStruct::ChildProperties` = **+0x50** (not +0x40 which is SuperStruct).
  - FCameraCacheEntry::POV at +0x10 (float TimeStamp + 12-byte SIMD pad),
    with +0x04 fallback for non-SIMD builds; validated by reading FOV in [1,179].
  - FMinimalViewInfo: Location+0x00, Rotation+0x0C, FOV+0x18 (stable across UE5).
  - Tick thread (60 Hz) writes `g_cam_override_state` to fight game's per-frame update.
- **New TCP commands**: `__cam_mem_find`, `__cam_mem_read`,
  `__cam_mem_write X Y Z P Y R [FOV]`, `__cam_mem_on`, `__cam_mem_off`.
- **find_camera_manager()**: scans GUObjectArray for class FName
  "PlayerCameraManager" or "BP_PlayerCameraManager_C"; skips CDOs; prefers
  candidate whose OuterPrivate class is "PlayerController".
- **__bridge_status** extended: `camera_manager_ptr`, `cam_pov_ptr`,
  `camera_manager_found`, `cam_pov_found`, `cam_override`.
- **__bridge_rescan_objects** now resets and re-finds camera_manager + cam_pov.
- **Startup sequence** extended to 10 steps: step 9=CameraManager, step 10=POV.
- **Python/UI**: `scan_status()`, `rescan_objects()` return `camera_manager_found/ptr`;
  Web UI debug panel shows "CameraMgr:" badge alongside UWorld/LP.

### [v0.2.0] 373cf2b -- xiaoni
- **Toolbar '重新扫描 UE' button**: visible at all times, colored dot (gray/green/orange/red),
  opens debug panel + triggers rescan in one click. No longer buried in debug panel.
- **Arm Break mechanism**: g_debug_break_armed atomic toggle via __bridge_arm_break command.
  find_uworld + find_localplayer each fire __debugbreak() (one-shot) when armed.
  Workflow: attach WinDbg -> Arm Break -> Re-scan UE -> debugger catches at discovery.
- **Debug panel 'Arm Break' button**: turns red when armed, shows attach-debugger instructions.

### [v0.2.0] 711d8eb -- xiaoni
- `__bridge_rescan_objects` TCP command: clears g_world_ptr/g_localplayer_ptr,
  re-runs find_uworld + find_localplayer, returns `uworld_found= localplayer_found=`
- `__bridge_status` extended with `uworld_found= localplayer_found= localplayer_ptr=`
- `drivers/ue5_console.py`: scan_status(), rescan_objects(), is_objects_ready(),
  wait_for_objects_ready() (polls 2s interval, up to 10 min)
- `web_ui.py`: /api/bridge/scan_status GET, /api/bridge/rescan POST
- `web/templates/index.html`: Debug panel scan status row (UWorld/LP indicators)
  + "Re-scan UE" button; auto-refreshes on panel open
- `main.py`: pre-capture gate: polls is_objects_ready() until ready or stop

### [v0.2.0] aea22c7 -- xiaoni
- **Ordered gated init**: console_server.h startup rewritten as 7-step sequential
  init. Gate 1=GUObjectArray (poll 120s), Gate 2=FNamePool (poll 60s), Gate 3=GEngine
  (poll 120s). All are mandatory -- bridge aborts (FATAL log) if any gate times out.
  Steps labeled [1/7]..[7/7] for clean log readability.
- **Removed per-hook log noise**: install_fexec_hook_on no longer logs per hook.
  64 individual log lines -> 1 summary "[5/7] FExec hooks: N installed".
- **Removed lazy world scan**: exec_console_command_internal no longer calls
  find_uworld_via_guobjectarray() lazily on each command. UWorld must be found
  at startup (step [6/7]) or captured by FExec hook.
- **Removed passive LocalPlayer fallback**: g_localplayer_fexec global and hook
  capture removed entirely. ULocalPlayer is found ONLY via GUA+FName("LocalPlayer")
  active scan. Single exec path: GEngine first, ULocalPlayer (FName) second.

### [v0.2.0] 951ee30 -- xiaoni
- `find_localplayer()`: multi-block FName scan. 'LocalPlayer' confirmed in block 5+
  (not block 0). Old code returned 0xFFFFFFFF silently. Now searches blocks 0..CurrentBlock.
- `g_localplayer_ptr`: new global set by find_localplayer(). exec fallback uses it
  as primary path; g_localplayer_fexec (passive hook) is secondary.
- console_server.h: find_localplayer() called eagerly after find_uworld_via_guobjectarray.
- Log confirmed root cause: FNamePool CurrentBlock=30, LocalPlayer not in block 0.

### [v0.2.0] Fix stride detection + hook table + ULocalPlayer fallback -- xiaoni
- **Root cause A: FUOBJECTITEM_STRIDE hardcoded 24** -- current branch rewrite removed runtime
  stride detection. StackOBot UE5.7 Dev uses stride=32, obj_off=0x08, so guobjectarray_get()
  was returning garbage pointers, causing GUObjectArray FExec scan to find zero ULocalPlayer hooks.
  Fix: restored `g_fuobjectitem_stride`/`g_fuobjectitem_object_off` globals + `detect_fuobjectitem_stride()`
  using GEngine.InternalIndex cross-validation. Called from console_server.h after GEngine found.
- **Root cause B: hook table size 16 (regression)** -- rewrite reverted table to 16.
  Fix: restored to 64; silent return when full (no spam).
- **ULocalPlayer fallback in exec_console_command_internal** -- GEngine::Exec returns false for
  gameplay commands (slomo, ToggleDebugCamera, etc.) in UE5. Added `g_localplayer_fexec` global
  captured by hooked_fexec_exec on first non-GEngine FExec call with valid world. exec fallback
  looks up vtable in hook table -> calls ULocalPlayer original. Lazy capture (passive, no FName scan).
- **Crash retry on stale world** -- if GEngine::Exec AV-crashes (stale map-reload world pointer),
  clear g_world_ptr and retry with nullptr. CVars/stat work without world.

### [v0.2.0] Fix ProcessConsoleExec: wrong function + wrong vtable range — xiaoni
- **Root cause**: calling wrong function (Exec) at wrong vtable range (110-130) with wrong param order
- **Correct function**: `UObject::ProcessConsoleExec(TCHAR*, FOutputDevice&, UObject*)` at vtable[79] (UE5.7)
- Fix: typedef param order `(this, cmd, ar, executor)` not `(this, world, cmd, ar)`
- Fix: scan range 65-90 instead of 110-130
- Built-in version DB (UE4SS PDB-verified): UE 4.27-5.07, 9 entries
- Ar-callback validation: detect if candidate function actually calls FOutputDevice virtual methods
- Dummy FOutputDevice with callback flag replaces NULL Ar
- Research archived to `agents/reversing/ARCHIVE.md` (full vtable index table)

### [v0.2.0] d32d2aa — xiaoni
- TCP 秒启 + GEngine 后台 scan, launcher 秒退检测, 8 锚点, diagnostics, fallback, status

旧版 CL 和已完成 TODO 见 `agents/reversing/ARCHIVE.md`。
