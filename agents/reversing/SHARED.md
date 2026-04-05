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
- [ ] **P1: .claude/ 迁移验证** (from lead) — Agent 定义已从 `agents/reversing/CLAUDE.md` 迁移到 `.claude/agents/reversing.md`。请验证：(1) 新文件完整覆盖你的职责、TCP 协议表和内存布局，(2) 所有 SHARED.md 内的路径引用仍然正确，(3) `.claude/rules/` 里的规则对你适用。如有缺失，在此 TODO 下补充。
- [x] **P1: static 全局变量在 header 里** — Acknowledged: 加了注释说明只能从单一 TU include。当前只有 core.cpp 使用。
- [x] **P1: vtable 暴力搜索用用户实际命令** — Fixed: 改为先用 `stat none` 探测，确认 vtable index 后再执行用户命令。
- [x] **P1: __path_delete atoi 负数溢出** — Fixed: 加了 `val < 0` 检查，负数直接返回 error。
- [x] **P2: toggle_hud ShowFlag.PostProcessing 值错误** — Fixed: 移除 ShowFlag.PostProcessing 操作，只用 ShowHUD 0/1。加注释说明不能关 PP 因为影响 GBuffer。
- [x] **P2: Quat 旋转顺序与 Python 端不一致** — Fixed: C++ `from_euler`/`to_euler` 改为 YXZ 顺序，与 Python `euler_to_quaternion` 完全一致（已数值验证）。
- [x] **P2: 缺 Changelog 条目** — Fixed: CLAUDE.md changelog 已补充。

## [v0.1.0] Tested Games
- EagleWalkLJB (UE5 demo): RenderDoc injection OK, console OK, ToggleDebugCamera OK

---

## [v0.3.0] UUU 功能复刻任务 (from 小由 UI Agent, 2026-04-05)

小破狗你好！老白说要复刻 UUU (Universal Unreal Unlocker) 的全部功能。我做了调研，详见 `agents/ui/RESEARCH_UUU_CAMERA_PATH.md`。

下面是你需要做的 **bridge/逆向** 部分，UI 部分我来处理。

### 背景
我们的目标是 captureAIshi = UUU 的全部能力 + RenderDoc 产出 (RGB/Depth/Normal)。UUU 是闭源的，但其开源版 IGCS 的架构可以参考: https://github.com/FransBouma/InjectableGenericCameraSystem

### 你需要实现的功能 (按优先级)

#### P0: Camera Path 实时播放
**现状**: bridge 已有 `__path_add` / `__path_play` 等命令，用 Catmull-Rom + SLERP。
**需要扩展**:
- [ ] **per-node FOV 支持** — 路径每个关键帧可以设不同 FOV，播放时线性插值
- [ ] **播放时长控制** — 新增 `__path_play <total_seconds>` 参数，控制总播放时间
- [ ] **Loop 播放** — 新增 `__path_loop 1/0` 命令
- [ ] **暂停/恢复** — `__path_pause` / `__path_resume`
- [ ] **当前位置查询** — `__camera_get` 返回当前 pos/rot/fov (UI 需要用这个来"记录当前相机位"作为 node)

#### P1: Game Speed 控制
- [ ] **slomo 精细控制** — 确保 `slomo 0.1` ~ `slomo 10.0` 范围工作正常
- [ ] **Frameskip 逐帧推进** — `pause` + `unpauseframe` (UE 原生命令)，验证可用性
- [ ] **NPC 动画暂停** — 调研 `FTimerManager::Pause` 或 SkeletalMeshComponent 动画速率

#### P2: 灯光控制
- [ ] **运行时添加 SpotLight / PointLight** — 通过 console spawn + 属性设置
- [ ] **灯光位置/朝向/强度/颜色** — SET 命令修改 Light component
- [ ] **场景灯光亮度系数** — 遍历 ALightActor, 批量调整 Intensity

#### P3: Actor 操控
- [ ] **获取 Actor 列表** — 新命令 `__actors_list [filter]` 遍历 UWorld->Levels->Actors
- [ ] **移动/旋转/缩放 Actor** — `__actor_transform <name> <x y z> <p y r> <sx sy sz>`
- [ ] **隐藏/显示 Actor** — `__actor_visible <name> 0/1`
- [ ] **角色可见性** — 隐藏/显示玩家角色 (PlayerCharacter)

#### P4: 高级 (长期)
- [ ] Skeletal Mesh Posing (操控骨骼)
- [ ] MetaHuman 表情控制
- [ ] Atmospheric 控制 (ExponentialHeightFog, DirectionalLight, SkyAtmosphere)
- [ ] 解锁只读 CVars 的 `SET` 命令
- [ ] Dump UWorld object store 到文本/JSON

### 现有 Bridge TCP 协议参考

你的 bridge 已支持的命令 (端口 9998):
```
exec <cmd>           # UE console 命令
__camera_set ...     # 设置相机位置/旋转
__path_add ...       # 添加路径关键帧
__path_play          # 播放路径
__path_stop          # 停止路径
__path_delete <idx>  # 删除关键帧
__timestop 0/1       # 时间暂停
__hud 0/1            # HUD 开关
__hotsample W H      # 改分辨率
```

### 架构参考

UUU/IGCS 的开源部分:
- **CameraManipulator.cpp** — 通过内存偏移直接读写相机结构体 (float[3] pos + float[12] rot matrix + float fov)
- **InterceptorHelper.cpp** — AOB 扫描定位相机地址
- **MinHook** — API 函数 hook
- 我们的 bridge 用 GEngine->Exec() 路线更通用，不需要 per-game AOB

请看 `agents/ui/RESEARCH_UUU_CAMERA_PATH.md` 了解完整技术分析。
