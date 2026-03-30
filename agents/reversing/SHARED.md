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

## [v0.1.0] Tested Games
- EagleWalkLJB (UE5 demo): RenderDoc injection OK, console OK, ToggleDebugCamera OK
