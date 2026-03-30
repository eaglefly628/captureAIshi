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

- [ ] **P0: ConsoleServer_Start 用了 Sleep(5000)** (spotted by lead) — 直接违反 CLAUDE.md "no sleep for readiness"。GEngine 初始化时间不固定，应改为轮询 `find_gengine()` 直到成功或超时，不是盲等 5 秒。参考：`console_server.h:410`
- [ ] **P0: detached client threads 没有清理** (spotted by lead) — `cs_handle_client` 线程是 `.detach()` 的，`ConsoleServer_Stop` 不等它们。进程退出时 handler 可能还在执行 `exec_console_command`，写已释放内存。应改为 tracked thread list + join。参考：`console_server.h:393`
- [ ] **P1: static 全局变量在 header 里** (spotted by lead) — `g_engine_ptr`/`g_exec_fn`/`g_camera_path` 等都是 `static`，如果第二个 `.cpp` include 这些 header 会得到独立副本。应改为 `extern` 声明 + 单一定义。
- [ ] **P1: vtable 暴力搜索用用户实际命令** (spotted by lead) — `exec_console_command` 用 110-130 遍历 vtable，拿用户命令试调用。如果错误 index 指向签名兼容但功能不同的函数不会崩但会误操作。应先用无害命令 `stat none` 验证。参考：`ue5_engine.h:423-442`
- [ ] **P1: __path_delete atoi 负数溢出** (spotted by lead) — `atoi` 返回负值转 `size_t` 变巨大正数，越界访问。参考：`console_server.h:280`
- [ ] **P2: toggle_hud ShowFlag.PostProcessing 值错误** (spotted by lead) — 值 `2` 不是 UE5 合法 ShowFlag 值（只有 0/1）。且隐藏 HUD 时关 PostProcessing 会影响 GBuffer 输出。参考：`ue5_engine.h:482`
- [ ] **P2: Quat 旋转顺序与 Python 端不一致** (spotted by lead) — C++ `from_euler` 用 ZYX 顺序，Python `euler_to_quaternion` 用 YXZ。camera path 数据互传时旋转会错。
- [ ] **P2: 缺 Changelog 条目** — CLAUDE.md 规则要求每次 push 写 CL，此次提交没写。

## [v0.1.0] Tested Games
- EagleWalkLJB (UE5 demo): RenderDoc injection OK, console OK, ToggleDebugCamera OK
