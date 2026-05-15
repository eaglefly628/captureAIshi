# adore_robot — UE5 PCG 室内场景管线

## 目标 (§9.1.6)

为机器人训练场景批量生成三类室内场景，每类 30 frame x 5 variant = 150 帧，共 450 帧。
输出 multi-layer EXR (FinalImage + WorldNormal + SceneDepth + ObjectId + GBufferA) → Cosmos Transfer 2.5。

| 场景 | 规模 | 算法 | 资产 |
|---|---|---|---|
| Warehouse | 50x50m | BSP + grid | Quixel Industrial |
| 客厅 | 5x7m | Graph + WFC | Fab MetaSofa + Megascans |
| 工业一角 | 8x8m | Grammar + cluster | Fab Industrial + 自建 |

## Agent 分工

| 角色 | 工作 | 看 |
|---|---|---|
| 小幻 (xiaohuan) | PCG graph 设计、procgen 算法、scene config metadata、URDF kinematic pose | `agents/pcg/SHARED.md`, `agents/pcg/refs/` |
| 小虚 (xiaoxu) | UE5 .uproject + Source/ + Plugins/ + MRQ preset + cook/package + custom UPCGSettings 实现 | `agents/unreal/SHARED.md`, `agents/unreal/refs/` |
| 小萱 (xiaoxuan, downstream) | 拿 MRQ 输出的 EXR 跑 Cosmos Transfer 2.5 | `agents/rendering/SHARED.md` |

跨 agent 改动先在对方 SHARED.md 写请求，不要直接动别人的目录。

## 目录约定

```
apps/adore_robot/
├── unreal_projects/
│   └── AdoreRobot/                      ← 小虚 owned (UE5 .uproject)
│       ├── AdoreRobot.uproject
│       ├── Source/AdoreRobot/           ← C++ gameplay (小虚)
│       ├── Plugins/AdoreRobotPCG/       ← Custom PCG nodes (小虚 实现, 小幻 用)
│       ├── Content/PCG/                 ← 小幻 owned (PCG graph .uasset)
│       │   ├── Warehouse/
│       │   ├── LivingRoom/
│       │   └── IndustrialCorner/
│       ├── Content/Sequences/           ← 小虚 owned (LevelSequence per scene/variant)
│       ├── Config/                      ← 小虚 owned
│       │   └── MovieRender/MRQ_MultiPassEXR.uasset
│       └── Saved/MovieRenders/<scene>/<variant>/frame_NNNN.exr  ← cook output
├── configs/
│   └── scenes/                          ← 小幻 owned (scene spec JSON)
│       ├── warehouse_v0.json
│       ├── living_room_v0.json
│       └── industrial_corner_v0.json
├── docs/                                ← 项目级文档 (PCG strategy, robotics pitch)
├── main.py                              ← Flask stub (port 5001, launcher 起的)
├── web/templates/index.html             ← preview UI (现状: stub)
└── CLAUDE.md                            ← this file
```

## 状态 (v0.3.1 时间点)

- ✅ `apps/adore_robot/` 脚手架已建（launcher subprocess port 5001）
- ✅ `docs/`: robotics_scene_foundry_pitch.md + ui_pcg_redesign_plan.md 已迁
- ❌ `unreal_projects/AdoreRobot/`: 还没建（小虚 P0）
- ❌ `Plugins/AdoreRobotPCG/`: 还没建（小虚 P2 模板）
- ❌ `Content/PCG/<scene>/`: 还没建（小幻 P0）
- ❌ `configs/scenes/*.json`: 还没建（小幻 P0 + xiaoxu 配合）

## 启动

主要靠 UE Editor。Flask stub `main.py` 当前只是 launcher 拉子进程占位，端口 5001 显示一个 placeholder 页面。后续可以挂 EXR preview / scene config 编辑器。

## 规矩

- ASCII only in `Source/**/*.{h,cpp}`、shader、`*.Build.cs`、`*.Target.cs`
- PCG graph 不强制 ASCII（.uasset 是二进制）但路径、metadata JSON 用 ASCII
- 任何 plugin 启用改动都在 `AdoreRobot.uproject` 里走 Plugins[] 数组，不要单独动 ini
