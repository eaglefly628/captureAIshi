# Reverse Engineering Agent — Shared Notes

This file is used for inter-agent communication. The RE agent writes game compatibility findings, injection methods, and camera control research here.

## [v0.1.0] Camera Control Methods

### UE5 Released Games
1. **captureAIshi Bridge DLL** — Self-hosted console server injected into game process
   - `ToggleDebugCamera` → free camera mode
   - `SetViewLocation X Y Z` / `SetViewRotation P Y R`
   - Works on most single-player UE4/UE5 games without anti-cheat
   - Includes camera path (Catmull-Rom + SLERP), timestop, HUD toggle, hotsampling
2. **Cheat Engine** — Direct memory write to camera transform
   - Requires finding ViewMatrix offset per game
   - More universal but needs per-game setup
3. **External Memory Driver** — ReadProcessMemory/WriteProcessMemory from outside
   - No DLL injection needed, bypasses most user-mode anti-cheat
   - Requires per-game memory offsets (found via CE)

### Unity Released Games
1. **BepInEx** — Plugin framework for Unity games
   - Custom plugin receives TCP commands for camera control
   - Works on most Unity games (IL2CPP and Mono)
2. **UnityExplorer** — Runtime inspector, can modify camera

## [v0.2.0] Bridge DLL Architecture

Bridge DLL (`3rdparty/bridge/`) replaces external UUU dependency:
- **Injection**: `injector.py` — CreateRemoteThread + LoadLibraryW (same as RenderDoc)
- **GEngine scan**: String xref method (finds `ToggleDebugCamera`/`r.Streaming.PoolSize` in memory, traces xrefs to locate GEngine global)
- **Console exec**: GEngine->Exec() via vtable call with validation
- **Camera path**: Keyframe system with Catmull-Rom position + SLERP rotation, 60Hz tick thread
- **TCP protocol**: Newline-delimited commands on port 9998, compatible with `ue5_console.py`

Anti-cheat research: see `docs/anti_cheat_research.md`

## TODO (from lead review of 7f06986)

- [x] **P0: ConsoleServer_Start 用了 Sleep(5000)** — Fixed: 改为轮询 `find_gengine()` 每 500ms 一次，最长 60 秒超时。
- [x] **P0: detached client threads 没有清理** — Fixed: 改为 tracked `cs_client_threads` vector + `ConsoleServer_Stop()` 中 join 所有线程。
- [x] **P1: static 全局变量在 header 里** — Acknowledged: 加了注释说明只能从单一 TU include。当前只有 core.cpp 使用。
- [x] **P1: vtable 暴力搜索用用户实际命令** — Fixed: 改为先用 `stat none` 探测，确认 vtable index 后再执行用户命令。
- [x] **P1: __path_delete atoi 负数溢出** — Fixed: 加了 `val < 0` 检查，负数直接返回 error。
- [x] **P2: toggle_hud ShowFlag.PostProcessing 值错误** — Fixed: 移除 ShowFlag.PostProcessing 操作，只用 ShowHUD 0/1。加注释说明不能关 PP 因为影响 GBuffer。
- [x] **P2: Quat 旋转顺序与 Python 端不一致** — Fixed: C++ `from_euler`/`to_euler` 改为 YXZ 顺序，与 Python `euler_to_quaternion` 完全一致（已数值验证）。
- [x] **P2: 缺 Changelog 条目** — Fixed: CLAUDE.md changelog 已补充。

## TODO (active)

- [ ] **P0: 真实 UE5 游戏端到端验证** — renderdoccmd launch → bridge 9998 → GEngine scan → Exec → ToggleDebugCamera → SetViewLocation → trigger capture → .rdc export → RGB+Depth PNG。一个游戏跑通就行。
- [ ] **P1: AC 预检脚本** — 启动前检测 EasyAntiCheat.dll / BEService.exe，提示用户禁用或切 driver
- [ ] **P2: 增强 Pause 机制** — 当前只有 slomo 0.0001，加 UWorld::IsPaused 内存写入 fallback
- [ ] **P3: Per-game profile 系统** — JSON 配置：GEngine offset、vtable index、特殊 CVar、已知问题
- [ ] **P3: 多游戏 AOB 数据库调研** — 研究 UUU/IGCS 的 offset 来源，评估自建 vs 复用可行性

## [v0.1.0] Tested Games
- EagleWalkLJB (UE5 demo): RenderDoc injection OK, console OK, ToggleDebugCamera OK

## Changelog

### [v0.2.0] 1dde07f — xiaoni
- `scripts/test_bridge_connection.py`: standalone 6-step diagnostic (TCP → ping → status → GEngine → Exec → camera path), exit codes for CI
- `drivers/ue5_console.py`: auto-fallback bridge:9998 → UUU:1985, `_detect_bridge()` via `__bridge_ping`, `_is_bridge` flag
- `renderdoc/renderdoc/core/bridge/ue5_engine.h`: GEngine scan failure now dumps full stats (strings/xrefs/MOV candidates/rejection counts) + actionable HINTs
- `renderdoc/renderdoc/core/bridge/console_server.h`: `__bridge_status` now includes `gengine_global` address
