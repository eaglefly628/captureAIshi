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

### [v0.2.0] Fix vtable probe — xiaoni
- Fix: vtable probe latched onto wrong function (index 113 instead of real Exec)
- Root cause: NULL FOutputDevice crashed real Exec via SEH, probe fell through to wrong fn
- Added dummy FOutputDevice stub (no-op vtable) so Exec never crashes on Ar dereference
- Added two-probe validation: "stat none" must return true AND invalid cmd must return false
- Captures Exec return value via seh_call_exec out_retval parameter

### [v0.2.0] d32d2aa — xiaoni
- TCP 秒启 + GEngine 后台 scan, launcher 秒退检测, 8 锚点, diagnostics, fallback, status

旧版 CL 和已完成 TODO 见 `agents/reversing/ARCHIVE.md`。
