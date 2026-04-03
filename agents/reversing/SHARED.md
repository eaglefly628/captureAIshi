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

## TODO (from lead review — new session)

- [x] **P1: C++ headers 含 Unicode 字符** (spotted by 主程序员) — Fixed: `ue5_engine.h`, `console_server.h`, `pattern_scan.h`, `camera_path.h` 的注释分隔符用了 U+2500 (`─`) 而非 ASCII `-`。MSVC `/W4 /WX` + codepage 936 会触发 C4819。已全部替换为 ASCII hyphens。
- [ ] **P2: _detect_bridge 无重试** (spotted by 主程序员) — `ue5_console.py` 的 `_detect_bridge()` 在 connect 后立即 ping，如果 bridge 启动慢会误判为 UUU。建议加 2-3 次指数退避重试。
- [ ] **P2: hardcoded sleep(0.5)** (spotted by 主程序员) — `ue5_console.py` line ~279 的 `time.sleep(0.5)` 用于 camera toggle 后等待，违反 no-sleep 规则。改为轮询确认或至少加 TODO 注释说明原因。

## TODO (active)

- [ ] **P0: 真实 UE5 游戏端到端验证** — renderdoccmd launch → bridge 9998 → GEngine scan → Exec → ToggleDebugCamera → SetViewLocation → trigger capture → .rdc export → RGB+Depth PNG。一个游戏跑通就行。
- [ ] **P1: AC 预检脚本** — 启动前检测 EasyAntiCheat.dll / BEService.exe，提示用户禁用或切 driver
- [ ] **P2: 增强 Pause 机制** — 当前只有 slomo 0.0001，加 UWorld::IsPaused 内存写入 fallback
- [ ] **P3: Per-game profile 系统** — JSON 配置：GEngine offset、vtable index、特殊 CVar、已知问题
- [x] **P3: 多游戏 AOB 数据库调研** — 完成。结论：UUU 没有 per-game 数据库，用的是引擎通用 pattern（和我们一样）。已加 UEVR 验证的额外锚点字符串。详见下方调研结果。

## [v0.1.0] Tested Games
- EagleWalkLJB (UE5 demo): RenderDoc injection OK, console OK, ToggleDebugCamera OK

## [v0.2.0] AOB Database Research

**结论：不需要 per-game 数据库。** UUU 用的就是引擎通用 pattern，和我们一样。

### UUU 的真实做法
- AOB pattern **内嵌在 DLL 里**，无外部数据库
- 少量引擎通用 pattern 覆盖 300+ 游戏（因为 UE 引擎代码稳定）
- 当 pattern 不兼容时，内置引擎版本变体

### 可复用的开源资源
| 项目 | 用途 |
|------|------|
| **patternsleuth** (Rust) | UE 通用 scanner，UE4SS v3 在用 |
| **UEVR** (praydog) | 用 ASCII 字符串锚点定位 GEngine，UE4-5.4 验证 |
| **UE4SS** | Lua AOB 框架 + 社区 per-game fallback |
| **IGCS** | 32 个游戏的手工 AOB（不通用，仅参考） |

### 我们的改进
已将 UEVR 验证的锚点加入 bridge scanner：
- `"CALIBRATEMOTION"` (ASCII) — UE4-5.4 全覆盖
- `"SeamlessTravel FlushLevelStreaming"` (ASCII) — GWorld 附近
- `"StaticConstructObject_Internal"` (ASCII) — 引擎核心函数
- `L"r.HLOD"` (wide) — CVar 注册代码附近

加上原有 4 个 wide 字符串，现在共 8 个锚点，大幅提高命中率。

## Changelog

### [v0.2.0] d32d2aa — xiaoni
- TCP server 立即启动，GEngine scan 后台并行（修复 port 9998 等待超时）
- UE5 launcher 秒退检测 + 自动搜索 *-Shipping.exe
- GEngine scanner 扩展到 8 个锚点（5 wide + 3 ASCII，含 UEVR 验证的 CALIBRATEMOTION 等）
- bridge 诊断脚本 `scripts/test_bridge_connection.py`
- UE5 driver 自动 fallback bridge:9998 → UUU:1985
- GEngine scan 失败输出完整统计 + actionable HINTs
- `__bridge_status` 新增 `gengine_global` 地址
