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
