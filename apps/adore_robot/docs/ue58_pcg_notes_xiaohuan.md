# UE 5.8 PCG Notes (xiaohuan)

Source: `apps/adore_robot/docs/ue58_preview_capabilities.md` §1, §3, §4, §7.
Audience: xiaohuan 自己 (PCG graph 设计依据) + xiaoxu (custom node / cook 配合)。
Date: 2026-05-15.

本文只挑 PCG 相关结论 + 我们要怎么用。每条都标 `[adopt]` / `[wait]` /
`[reject]`。原始论据看上游 capabilities 文档。

---

## 1. 5.8 PCG 关键变化 (能用)

- **[adopt] DAG 并行 graph evaluation** — 2-2.5x regen 提速，cook-time
  ~50% 时间。三场景循环渲染期间，PCG 占比从 "10 多秒/次" 砍到 "几秒",
  和 MRQ 的 ~15 分钟比可忽略。**iteration loop 不再是瓶颈**。
- **[adopt] 手动编辑 procedural output 不破图** — 在 PCG 生成结果上手动
  挪一个 robot workstation 不会让 graph 断链。**机器人位置由 URDF +
  scene_spec 决定，不进 PCG graph**，PCG 只摆静态家具/工具/货架。
- **[wait] PCG 节点级 5.8 新增列表** `[no data]` — 我按 5.7 节点集合
  (Surface Sampler / Spline Sampler / Density Filter / Self Pruning /
  Static Mesh Spawner) 设计 graph，5.8 装机后再看 PythonStub diff 补。
- **[wait] Biome Core indoor / HGG / Partition Actor 5.8 改动** `[no data]`
  — 我们三场景规模 (warehouse 50x50m = ~2.5K instance) 落在 HISM 区间，
  不需要 Partition Actor。客厅 + 工业一角 instance 数更小 (<200)，单
  PCGComponent 跑完即可。
- **[reject] PCG runtime generation** — 我们走 **cook-time generate +
  MRQ 渲染**，不要 runtime。`Generate on Demand` 编辑器模式触发即可。

---

## 2. Python 驱动 PCG (NL 链路必须)

- **[adopt] 5.7 Python PCG API 已工作** — `unreal.PCGGraph` /
  `unreal.PCGComponent` 暴露足够 (parameter set/get, graph rebuild)。
  forum 帖确认 5.7 起 UEFN/Editor 都能调。
- **[wait] 5.8 PCG Python delta** `[no data]` — capabilities §7 建议 5.8
  装机后 diff `Intermediate/PythonStub/unreal.py`。**我先按 5.7 已知接口
  写 contract，5.8 装机第一件事是 dump `help(unreal.PCGComponent)` 确认
  方法名**。
- **TODO for xiaoxu (boundary)**: PCGComponent override 的实际 Python
  method 名（`SetGraphParameter` / `set_override_param` / 别的），等他
  装 5.8 后填回 `pcg_param_contract.md` §2。

---

## 3. PCG + 其它系统

- **[adopt] Mega Lights production-ready** — warehouse 50-200 个 sodium
  lamp fixture 不用 baked light，real-time Lumen 直接捕。**asset pack
  里的灯具用 Mega Lights actor，不再走 spot/point fallback**。
- **[adopt] Substrate default-on** — 我 PCG 摆的所有 mesh 材质走
  Substrate，不需要适配旧 material domain。
- **[wait] Lumen Medium Quality (beta)** — 2x 快，但 SSIM 损失未知。
  capabilities §4 建议 A/B 测，**Cosmos Transfer 2.5 输入对 GI 质量
  不极端敏感（depth/normal 才是关键 conditioning），值得测**。这是
  xiaoxuan 下游决定的事，本期不动。
- **[constraint] Nanite + translucent 不兼容** (peer review from xiaoxu,
  source: capabilities §4) — 任何 BlendMode=Translucent material 不
  挂 Nanite mesh，否则不可见。详见 `pcg_param_contract.md` §5
  Asset Checklist。

---

## 4. Mesh Terrain (5.8 Experimental, 跨域 note)

- **[reject for 室内]** 三场景全室内，地面是 BSP/Floor mesh 不是
  landscape。Mesh Terrain 不进 v0。
- **[future]** 工业一角的 "outdoor variant" (室外开放工厂) 可以挂
  Mesh Terrain + PCG，但那是 v0.4 之后。

---

## 5. 不打算赌的事 (依赖 + 不依赖明细)

| 项 | 5.8 状态 | 我们的做法 |
|---|---|---|
| PCG 节点级新增 | `[no data]` | 不依赖，按 5.7 节点集设计 graph |
| PCG runtime generation 改动 | `[no data]` | 不依赖，cook-time only |
| Robotics Plugin URDF Beta | `[no data]` | xiaoxu Plan A/B/C 待老白，我 PCG 不放 robot mesh (robot 由 xiaoxu 单独 spawn) |
| LLM / Smart Object 集成 | `[no data]` | NL→PCG 走 Anthropic SDK，不等 Epic |
| Zen incremental cook 稳定 | 5.7 有 regression | 不依赖，每轮 full cook（450 帧不大）|

---

## 6. 我开工时的最小依赖集

要这个 doc 落地，我只需要 (即可以单线推进):

1. **5.7 已知的 PCG 节点表**（`agents/pcg/refs/cheatsheet_pcg_graph.md`
   已有，标的是 5.6/5.7 集合，5.8 兼容）。
2. **5.7 已知的 Python 接口**（forum 帖足够 sketch contract）。
3. **三场景 asset pack 索引**（mesh 类型清单，本 doc §3 + contract §5）。

不依赖的 (不阻塞):

- 5.8 装机
- xiaoxu custom UPCGSettings 实现
- MRQ preset 定稿

依赖的 (等)：

- xiaoxu 装 5.8 后回填 PCGComponent Python method 真名 →
  `pcg_param_contract.md` §2 当前是占位 placeholder。
