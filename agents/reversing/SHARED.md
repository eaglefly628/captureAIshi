# Reverse Engineering Agent (小逆) — Shared Notes

## Active TODO

- [ ] **P0: 真实 UE5 游戏端到端验证** — renderdoccmd → bridge 9998 → GEngine → Exec → camera → capture → export。跑通一个游戏。
- [ ] **P1: AC 预检脚本** — 检测 EasyAntiCheat.dll / BEService.exe
- [ ] **P2: _detect_bridge 无重试** (spotted by 主程序员) — 加 2-3 次指数退避重试。
- [ ] **P2: hardcoded sleep(0.5)** (spotted by 主程序员) — camera toggle 后改轮询。
- [ ] **P2: 增强 Pause** — 加 UWorld::IsPaused 内存写入 fallback

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
