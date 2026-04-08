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

## [v0.1.0] Camera Control Details

### Unity
- BepInEx plugin (IL2CPP + Mono)
- UnityExplorer runtime inspector
