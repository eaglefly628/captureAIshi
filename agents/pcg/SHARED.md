# PCG Agent (小幻) — Shared Notes

## Active TODO

### [v0.3.2] P0 batch scene gen 调研 + 架构 (from 老白, 2026-05-15)

**xiaoxu 同步在做引擎侧调研 + 批量 UI + NL 驱动 PCG 的架构 sketch (见 `agents/unreal/SHARED.md`)。你这边平行做 PCG 侧的调研 + 参数契约设计。本轮也只做调研 + 设计，不写 production PCG graph。**

#### Step 1: 摸 UE5.8 Preview 的 PCG 改动
- [ ] 先读 `apps/adore_robot/docs/ue58_preview_capabilities.md`（老白这边 research subagent 拉的，未到时自己用 WebSearch 补）
- [ ] 重点关注以下子项，整理成 `apps/adore_robot/docs/ue58_pcg_notes_xiaohuan.md`:
  - 5.8 新增 PCG 节点（哪些用得上）
  - PCG Biome Core indoor 模板更新
  - Hierarchical Generation Grid / Partition Actor 性能改动
  - PCG runtime generation 状态（5.8 是否可用，决定后续是否 cook 时跑还是 runtime 生）
  - PCG + Geometry Script interop 改动
  - PCG Python API 进度（决定 NL → PCG 是否可行）

#### Step 2: PCG graph 参数暴露契约（核心）

xiaoxu 那边做的 NL → PCG 链路需要 PCG graph 暴露**可被外部 set 的参数**。你定义"哪些参数暴露、什么类型、合理范围"。
- [ ] 产出文档 `apps/adore_robot/docs/pcg_param_contract.md`，每个场景一节，每节包含：
  - **公开参数表** (示例 warehouse)：
    | 参数名 | 类型 | 范围 | 默认 | 影响 |
    |---|---|---|---|---|
    | `shelf_density` | float | 0.2 - 1.0 | 0.7 | 货架在 BSP 切分后的填充率 |
    | `alley_width_m` | float | 1.5 - 4.0 | 2.4 | 叉车通道宽度 |
    | `forklift_count` | int | 0 - 5 | 1 | 叉车摆放数量 |
    | `prop_variety` | int | 1 - 5 | 3 | 货物种类数（pallets/boxes/drums...）|
    | `lighting_preset` | enum | warehouse_sodium / cool_white / mixed | warehouse_sodium | 灯光氛围 |
    | `seed` | int | any | 0 | 随机种子 |
  - **实现方式**：PCG graph 用 `Get Param Data` 节点读 PCG Component 的 `OverrideParams`，每个 param 对应一个 UPROPERTY EditAnywhere
  - **校验规则**：哪些组合不合法（比如 alley_width > size_m[0] / 4）
  - **隐式参数**：你内部用但不暴露给 LLM 的（节点连接、噪声 octave 等）

#### Step 3: NL prompt 模板（给 xiaoxu 参考）

LLM 收到用户文本后要输出严格 JSON delta，你这边以 PCG 专家身份起草 prompt template：
- [ ] 在 `pcg_param_contract.md` 续写 §4 "NL Prompt Template"，包含：
  - **System prompt 草稿**：给 LLM 解释每个参数物理含义、合理组合、典型 use case
  - **Few-shot 示例**：用户说"warehouse 货架密一点" → LLM 应该输出 `{"shelf_density": 0.9, "prop_variety": 4}`
  - **失败处理**：用户要求做不到时（"加 100 台叉车"超 forklift_count 上限）LLM 该怎么 graceful degrade
  - **资产 pack 索引**：如果 LLM 提到 "汽车" 但 warehouse asset pack 没汽车 mesh，LLM 该怎么响应

#### Step 4: 三场景 spec 定稿
- [ ] 把 `agents/pcg/refs/scene_specs.md` 的三场景草稿 review + 改成最终版，落到 `apps/adore_robot/configs/scenes/` 下 3 个 JSON 文件（warehouse_v0.json / living_room_v0.json / industrial_corner_v0.json）
- [ ] 跟 xiaoxu 对齐 schema（他要据此设计 batch UI 表单）

#### Verification
- [ ] 两份 doc + 三份 scene spec JSON 在 PR 里
- [ ] CL 条目 ≤ 10 行，遵守 `.claude/rules/versioning.md`
- [ ] 不动 `Source/` / `Plugins/` / `Config/`（那是 xiaoxu 的）

## Boundary & Handoff

- **依赖 xiaoxu**: custom UPCGSettings 节点实现、PCG Component param override 怎么从外部 Python set
- **依赖 xiaoxu**: MRQ preset，渲染时 PCG 必须 Generate-on-Demand 跑完再开 MRQ
- **下游 xiaoxuan**: multi-layer EXR 是最终交付物，PCG 这边只管 scene 准备好

## Reference 速查

详见 `agents/pcg/refs/`:
- `cheatsheet_pcg_graph.md` -- PCG 核心节点 + 数据流模板
- `scene_specs.md` -- warehouse / 客厅 / 工业一角 spec 模板（本轮要 review + 定稿）

## Changelog

_暂无，等首批 PR_
