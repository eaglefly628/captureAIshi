# PCG Graph Cheatsheet

> Quick reference for assembling PCG graphs. Reach for `.claude/agents/xiaohuan.md` for full theory.

## 最小 graph 模板

```
[Get Actor Data]  →  [Bounds]  →  [Surface Sampler]  →  [Density Filter]  →  [Self Pruning]  →  [Static Mesh Spawner]
                                       │                       │
                                  (Looseness=0.6)         (Threshold=0.4)
```

- Surface Sampler: `Looseness` 控制点紧密度，`Use Bounds 2D` 平面采样
- Density Filter: 配 `Noise` (Perlin/Worley) 做空间变化
- Self Pruning: `Min Distance` >= 资产 footprint 半径

## 三场景常用 pattern

### Warehouse (BSP + Grid)
```
[Bounds] → [Subdivide N-times] → [Transform Points (grid)] → [Static Mesh Spawner (shelf)]
                                          │
                                          ├─ alley walkway (Difference 减去走道带)
                                          └─ pallet on ground (再叠一层 Density Filter)
```

### 客厅 (Graph + WFC)
- 不用 PCG 内建 graph 节点，**外部 Python 跑 WFC 生 room layout** → 写成 JSON → PCG `Get Param Data` 读 JSON → `Spawn Actor` 摆 module
- Module 粒度：沙发组 / 茶几组 / 电视墙 / 装饰 / 地毯，每个 module 是一个 BP_Actor 含子 PCG component

### 工业一角 (Grammar + Cluster)
```
[Anchor Points (3 个: 机床/工具架/控制台)] → [Cluster (radius=0.8m)] → [Spawn Actor (prefab per cluster)]
```

## 性能 cheat

| Instance count | 用 |
|---|---|
| < 5K | HISM (Static Mesh Spawner 默认) |
| 5K - 50K | Mass Entity (Spawn Mass Entity 节点) |
| > 50K | Hierarchical Generation Grid + Partition Actor |

## 调试节点

- `Print` (Param Data) -- 在 output log 看属性值
- `Visualize` toggle -- viewport 显示中间结果点云
- `PCG Profiling` console -- `pcg.GraphExecutor.LogTaskTimings 1`

## 常见坑

1. **Generate on Demand 不刷新**：Actor outliner 右键 -> "Force Regenerate"，或代码 `PCGComponent::Generate(true)`
2. **HISM 没 Nanite**：HISM 跟 Nanite 互斥，要 Nanite 走 ISM + nanite static mesh
3. **Partition Actor 不生效**：World Setting 里 World Partition 必须勾上，否则 Hierarchical Generation Grid 退化为普通 grid

## 外部 reference (按需 WebFetch)

- UE5 PCG Docs: https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine
- PCG Sample (Epic 官方): https://www.fab.com/listings/4a4f47b1-b8c8-4b21-9614-b8c33feb1adc
- Electric Dreams technical breakdown: https://dev.epicgames.com/community/learning/talks-and-demos/9YRD/unreal-engine-electric-dreams
