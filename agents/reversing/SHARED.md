# Reverse Engineering Agent (小逆) — Shared Notes

## Active TODO

- [ ] **P0: 真实 UE5 游戏端到端验证** — StackOBot test in progress. Bridge finds GEngine/UWorld/LP/CameraManager. Next: rebuild DLL, run __cam_mem_find, confirm scan fallback finds POV.
- [ ] **P1: AC 预检脚本** — 检测 EasyAntiCheat.dll / BEService.exe
- [ ] **P2: _detect_bridge 无重试** (spotted by 主程序员) — 加 2-3 次指数退避重试。
- [ ] **P2: hardcoded sleep(0.5)** (spotted by 主程序员) — camera toggle 后改轮询。
- [ ] **P2: 增强 Pause** — 加 UWorld::IsPaused 内存写入 fallback
- [ ] **P2: g_gvc_ptr binary-address bug** — GEngine+0x200 for StackOBot returns 0x7FF4... (binary/DLL range, not heap). LP+0x78 gives correct heap GVC. Need to use LP GVC as authoritative, or TObjectPtr decode for GVC field.

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
