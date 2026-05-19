# PCG Agent (小幻) — Shared Notes

## Active TODO

### [v0.3.3] P0 from xiaoxu via 用户 (2026-05-17): PG_Warehouse 真 PCG graph 落地

xiaoxu 这一边 MCP wiring 完毕 (ObjectTools.set_properties 闭环验通, 见
`apps/adore_robot/docs/ue58_mcp_validation_log.md`), 现在差的是**实际能 spawn 物件
的 PCG graph asset**. 用户原话: "让这个 pcg volume 和 app 一起 spawn 仓库布局里
的机器, 机器人等物件吧". 这是 xiaohuan 域 (Content/PCG/Warehouse/) 的产物.

需要交付的:
- [ ] `apps/adore_robot/unreal_projects/AdoreRobot/Content/PCG/Warehouse/PG_Warehouse.uasset`:
      PCG Graph asset, 暴露 contract §1 的 7 个 warehouse 参数 (`shelf_density`,
      `alley_width_m`, `forklift_count`, `prop_variety`, `pallet_load_factor`,
      `lighting_preset`, `seed`) + common 4 (`room_w_m`, `room_l_m`, `ceiling_h_m`,
      `worker_count`) 作 Graph Parameter. 节点链路建议:
        Input -> Surface Sampler (用 alley_width_m+room_w_m 切 grid)
               -> Density Filter (按 shelf_density)
               -> Static Mesh Spawner (shelf SKU, multi-mesh weighted)
               -> 并行支路: Point Filter (n=forklift_count) -> Forklift SM Spawner
               -> 并行支路: Point Filter (n=machine_count, if any) -> Machine SM Spawner
               -> 并行支路: Point Filter (n=worker_count) -> Worker placeholder SM
               -> Output
- [ ] Mesh 资产挑选 (按 contract §3.1 asset pack `Quixel_Industrial`):
      - shelf 5 SKU
      - forklift 3 款
      - pallet (loaded by pallet_load_factor)
      - box / drum (prop_variety 控制多样性)
      - sodium_lamp / cool_lamp (PointLight 或 SM with emissive, 按 lighting_preset)
      - worker placeholder (简单 mannequin / capsule, 反正是 v0)
- [ ] 客厅 / 工业一角同样 graph 各一份 (`PG_LivingRoom`, `PG_IndustrialCorner`).
      参 contract §1.2 / §1.3 公开参数 + §3.2 / §3.3 asset pack 索引.
- [ ] 三个 graph 各搭一个**示例 level** (`Maps/Warehouse_v0.umap` /
      `Maps/LivingRoom_v0.umap` / `Maps/IndustrialCorner_v0.umap`), 内放一个 PCG
      Volume 绑好对应 graph, **`GenerateOnLoad`** 关掉 (xiaoxu MCP 走外部触发),
      场景就绪可被 chat 流远程驱动.

xiaoxu 那边已就绪:
- `apps/adore_robot/mcp_client.py` `apply_pcg_delta(params)` 一次调用 = auto_load +
  find_pcg_component_refpath + set_actor_properties. 21 + 4 = 25 公开参数任意 key
  set 立即生效, **graph 设了 OverrideParams 的就走 graphInstance 嵌套路径**, 探
  graphInstance 用 `/api/mcp/probe_graph` 一键 dump.
- 用户 chat "货架密一点" -> DeepSeek update_scene tool_call -> /api/chat 自动转
  MCP set_properties.
- 即将加的 `trigger_generate` MCP wrap 让 set 完调一次 Generate(), graph 重 sim,
  shelf 真的变密 (今晚 push, see agents/unreal/SHARED.md CL).

依赖关系 / 验收路径:
1. xiaohuan ship PG_Warehouse + Maps/Warehouse_v0.umap
2. xiaoxu pull, 打开 Maps/Warehouse_v0 -> 选 PCG Volume -> 在浏览器
   `localhost:5001/` chat 输 "货架密一点, 加 2 台叉车" -> 应看到 UE Editor 内
   shelf SM 重新 spawn 变密 + 2 个 forklift mesh 出现
3. 录视频 / 截图 -> 客户演示资产, 老白终审

(xiaohuan 知识库 `agents/pcg/refs/cheatsheet_pcg_graph.md` 里有 5.6/5.7 节点
模板, 5.8 兼容. 三场景 spec `apps/adore_robot/configs/scenes/*_v0.json` 是
ground truth, 不要漂移.)

#### xiaohuan 回复 (2026-05-19, 5b62b77)

**Sandbox 硬性限制**: 当前会话跑在 Linux 容器 (`/home/user/captureAIshi`)，
**没有 UE5.8 Editor**、**没有 Quixel/Fab 资产订阅**、**没有 .uasset 序列化器**。
`.uasset` 是 UE 专有 binary, 不能用文本工具构造、不能 hex 手搓 (PCG schema
跨次要版本变更, 5.8 Preview 与 release 不保证二进制兼容)。**我无法在本
sandbox 直出 `PG_Warehouse.uasset` / `Warehouse_v0.umap`。**

**已交付的替代**: `apps/adore_robot/docs/pg_warehouse_graph_design.md`
(commit 5b62b77) —— 节点级 spec, 11 参数 -> 8 Stage 拓扑, xiaoxu 在 UE
Editor 里 1-2 小时手搭即可。Mesh 资产挑选 (Quixel_Industrial 5+3+...
SKU) 必须在他装机的环境里挑, 不能在我这边定。

**建议两条路 (xiaoxu / 老白 选)**:

- **路径 A (推荐, 不阻塞客户演示)**: xiaoxu 照 design doc 在 UE Editor 内
  手搭 `PG_Warehouse.uasset` + `Warehouse_v0.umap` (~1-2h)。资产挑选他选,
  我审 (peer review on next sync)。验收路径同上。
- **路径 B (MCP 自动化, 演示后做)**: 我把 design doc 改写成
  `apps/adore_robot/scripts/build_pg_warehouse.py` — 一个能被
  `ProgrammaticToolset.execute_tool_script` 消费的 unreal-python 脚本,
  调 `unreal.AssetToolsHelpers.get_asset_tools().create_asset(
  asset_name="PG_Warehouse", package_path="/Game/PCG/Warehouse/",
  asset_class=unreal.PCGGraph, factory=unreal.PCGGraphFactory())` 等
  反射 API 建 PCGGraph + 拉节点 + 配 OverrideParams。xiaoxu MCP 端
  `execute_tool_script` 跑一次, asset 落地, 跑通后改 mesh 引用为他选的
  SKU。**这条路把建图从"手活"变成"配置驱动"**, 客户后续要换布局只改
  Python 不动 .uasset。

**等 xiaoxu / 老白 回 A 还是 B。** 如果 A 优先 (今天演示)，我下轮帮 xiaoxu
review 他搭出来的 graph (用 `/api/mcp/probe_graph` dump 对照 contract §1
+ design doc §1 表); 如果 B 优先 (演示后), 我下轮写 `build_pg_warehouse.py`。

LivingRoom + IndustrialCorner design 在 PG_Warehouse 走通后写 (`pg_warehouse_graph_design.md` §12 已说明)。


### [v0.3.2] P1 from xiaoxu -- NL→PCG 链路 contract 产出 (2026-05-15)

xiaoxu 在 `apps/adore_robot/docs/batch_scene_gen_architecture.md` §3/§4
列了六件 NL→PCG 链路阻塞项，全部由本轮 `pcg_param_contract.md` 覆盖：

- [x] **公开参数表** -- `pcg_param_contract.md` §1 三场景表完整 (name/type/range/default/物理含义 + 校验 + 隐式参数)
- [x] **OverrideParams key 命名约定** -- §2 定: ASCII snake_case = 参数表 name 列字面值，无前缀/无 GUID/无命名空间。Python method 真名等 xiaoxu 装 5.8 后回填
- [x] **Few-shot prompt 内容** -- §4.2 五个示例 (单参数 / 多参数 / 超 range clamp / asset 不在 pack / 隐式参数 refuse)
- [x] **资产 pack 索引** -- §3 三场景 mesh 类别清单，"没有"项明列
- [x] **Thumbnail viewpoint** -- 三场景 `<scene>_v0.json` 已加 `thumbnail_camera` (pos / look_at / fov_v_deg / near_far_m)
- [x] **(spotted by xiaoxu)** Nanite + translucent 不兼容 -- contract §5 PCG Asset Checklist 收编

### [v0.3.2] P0 batch scene gen 调研 + 架构 (from 老白, 2026-05-15)

#### Step 1: 摸 UE5.8 Preview 的 PCG 改动 -- DONE
- [x] 读 `apps/adore_robot/docs/ue58_preview_capabilities.md` (subagent 已产出，无需 WebSearch)
- [x] 整理 `apps/adore_robot/docs/ue58_pcg_notes_xiaohuan.md` (6 节: DAG / Python API / Mega Lights+Substrate / Mesh Terrain / 不赌项 / 最小依赖)

#### Step 2: PCG graph 参数暴露契约 -- DONE
- [x] `apps/adore_robot/docs/pcg_param_contract.md` 写完 (§1 三场景参数表 / §2 override key 约定 / §3 资产 pack 索引 / §4 NL prompt template / §5 Asset Checklist / §6 thumbnail / §7 接口契约小结)

#### Step 3: NL prompt 模板 -- DONE
- [x] 并入 contract §4 (System prompt 三段 + 5 个 few-shot + 失败处理表 + server validate)

#### Step 4: 三场景 spec 定稿 -- DONE
- [x] `apps/adore_robot/configs/scenes/warehouse_v0.json`
- [x] `apps/adore_robot/configs/scenes/living_room_v0.json`
- [x] `apps/adore_robot/configs/scenes/industrial_corner_v0.json`
- [ ] **跟 xiaoxu 对齐 schema** -- 他装 5.8 dry-run 之后再校对，本期 unblock

#### Verification
- [x] 两份 doc + 三份 scene spec JSON 在 commit 里
- [x] CL 条目 ≤ 10 行
- [x] 未动 `Source/` / `Plugins/` / `Config/`（xiaoxu 的）

### [v0.3.2] Robotics Backend 字段补丁 (老白 2026-05-15 P0 反向影响) -- DONE

老白 commit `5f1cfa2c` 把 xiaoxu Plan C only 改为 A/B/C 三方案接口支持，scene_spec JSON 需新增 `robotics_backend` 字段。本轮直接补：

- [x] 三场景 `<scene>_v0.json` 加 `robotics_backend: "minimal"` + `robotics_backend_compatible: ["minimal","urlab","urobosim"]`
- [x] `pcg_param_contract.md` 加 §7 Robotics Backend 字段 (5 节: schema / LLM 是否能切 / UI 要求 / server validate / 与 OverrideParams 关系)
- [x] 旧 §7 "与 xiaoxu 的接口契约（小结）" 重编号到 §8，加 item 7 引用 §7 + §7.3
- [x] **写 P1 到 `agents/unreal/SHARED.md`** -- "batch UI 必须清晰表达多 backend 支持" 7 条 (selector / status badge / `/api/scenes` 字段 / 默认 minimal / NL 不暴露 / scene JSON 已就位 / 表单区块位置)，承接老白原话 "UI 界面能清晰表达出我们的多个接口支持样子"

### [v0.3.2] 等 xiaoxu 装 5.8 后回填 (单点依赖)

- [ ] **PCGComponent Python method 真名** -- 等 `help(unreal.PCGComponent)` dump，回填 `pcg_param_contract.md` §2 placeholder (当前两个 hypothesis: `set_graph_parameter` / `override_param`)。回填前 contract 的 key 名 + value 类型 + range 仍然有效，不阻塞 xiaoxu batch UI 表单 + tool input_schema 派生

### [v0.3.3] P1 from xiaoxu via 老白 (方向 B 拍板, 2026-05-16): contract -> AICallable 映射 -- DONE

> **2026-05-17 老白补**: 完整映射表已落到 `batch_scene_gen_architecture_v2.md` §2.2-§2.4. 我 §9 写**两行 + 链接 + 边界规则**，不复制粘贴防双源漂移. §4 加 Example 6 (MCP tool call 序列).

- [x] `pcg_param_contract.md` 加 §9 "AICallable Method 映射 (pointer)" -- 两行 + v2 doc §2.2-§2.4 链接 + 边界规则 (contract = 语义源头 / v2 = UFUNCTION 派生表 / 不一致以 contract 为准)
- [x] §4.2 加 Example 6 -- MCP tool call 序列 (user 输入 -> 4 个 tool call: set_shelf_density / set_forklift_count / trigger_generate / trigger_mrq_render)，附 v1/v2 共存说明
- [x] 其他 contract 内容 (§1-§7) 不变，三场景 JSON spec 不变

### [v0.3.3] PG_Warehouse_v0 graph design (xiaoxu 接力交付物 - sandbox 无 UE Editor 出不了 .uasset) -- DONE

老白原文 "让 21-param 全跑通"。sandbox 无 UE 无法直接产 `.uasset` 二进制，交付节点级设计文档让 xiaoxu 机械翻译。

- [x] `apps/adore_robot/docs/pg_warehouse_graph_design.md` -- 11 个参数 (7 warehouse + 4 common) 到 8 个 Stage 的节点接入点 + 拓扑 + edge case + Nanite/HISM/ISM 选型 + xiaoxu UE Editor 落地 checklist (7 步)
- [x] **drift 收编**: `pcg_param_contract.md` 新增 §1.0 "Common to ALL scenes" -- room_w_m (8-40) / room_l_m (8-60) / ceiling_h_m (3-9) / worker_count (0-8). 消掉 demo/prompts.py 与 contract 的 single-source 不一致 (commit d45a3af3 引入 drift)
- [ ] **PG_LivingRoom_v0 + PG_IndustrialCorner_v0 design doc** -- 等 PG_Warehouse 在 UE Editor 跑通后再写 (pattern generalize)，**下轮接力**

## Boundary & Handoff

- **依赖 xiaoxu**: `UAdoreRobotPCGParams` UCLASS in `AdoreRobotPCG` plugin，UPROPERTY EditAnywhere 对应 contract §1 公开参数；PCG graph 引用此 class 作为 OverrideParams
- **依赖 xiaoxu**: MRQ preset 触发时 PCG `Generate on Demand` 跑完再开 render（cook-time，不上 runtime generation）
- **下游 xiaoxuan**: multi-layer EXR 终交付，PCG 只管 scene 准备好；Substrate + Mega Lights + Nanite+translucent 约束（contract §5）影响 normal/depth pass 一致性，已落 contract

## Reference 速查

详见 `agents/pcg/refs/`:
- `cheatsheet_pcg_graph.md` -- PCG 核心节点 + 数据流模板（5.6/5.7 节点集，5.8 兼容）
- `scene_specs.md` -- 三场景 spec 草稿（本轮已 review + 定稿到 `apps/adore_robot/configs/scenes/`）

## Changelog

### [v0.3.3] 5b62b77 -- xiaohuan (PG_Warehouse design + AICallable pointer + drift fix)
- apps/adore_robot/docs/pg_warehouse_graph_design.md: 11 参数 (7 warehouse + 4 common) -> 8 Stage 节点拓扑 + edge case + Nanite/HISM 选型 + xiaoxu UE Editor 7 步 checklist
- apps/adore_robot/docs/pcg_param_contract.md §9: AICallable Method 映射 pointer (两行 + v2 doc §2.2-§2.4 链接 + 边界规则, 不复制粘贴防漂移)
- apps/adore_robot/docs/pcg_param_contract.md §1.0: 新增 Common to ALL scenes (room_w_m / room_l_m / ceiling_h_m / worker_count) 收编 commit d45a3af3 drift
- apps/adore_robot/docs/pcg_param_contract.md §4.2 Example 6: MCP tool call 序列 (4 tool call demo: set + generate + render) + v1/v2 共存说明
- xiaoxu 接 21-param 全跑通: design doc 是机械翻译指南 + plugin UCLASS UPROPERTY 名字直接对齐 §1.0+§1.1, .uasset 仍需 UE Editor 落地
- PG_LivingRoom / PG_IndustrialCorner design 下轮 (pattern generalize 自 PG_Warehouse 跑通后)

### [v0.3.2] 9a77993 -- xiaohuan (robotics_backend 补丁)
- apps/adore_robot/configs/scenes/{warehouse,living_room,industrial_corner}_v0.json: 加 `robotics_backend: "minimal"` + `robotics_backend_compatible` 数组
- apps/adore_robot/docs/pcg_param_contract.md §7: 新增 Robotics Backend 字段定义 (schema / LLM 不暴露 / UI 要求 / server validate / 与 PCG OverrideParams 关系)
- apps/adore_robot/docs/pcg_param_contract.md §8: 旧 §7 接口契约小结重编号 + 加 item 7 引用 §7.3
- agents/unreal/SHARED.md: 写 P1 to xiaoxu -- batch UI 多 backend 显式表达 7 条要求 (承接老白 "UI 界面能清晰表达出多接口支持样子")
- 老白 commit 5f1cfa2c 反向影响落地完毕，xiaoxu 接 P0 时 schema 已对齐

### [v0.3.2] e484db1 -- xiaohuan
- apps/adore_robot/docs/ue58_pcg_notes_xiaohuan.md: 5.8 PCG 调研 (Step 1) -- DAG eval / Python API / Mega Lights / Nanite+translucent
- apps/adore_robot/docs/pcg_param_contract.md: PCG 参数契约 (Step 2/3) -- 三场景参数表 + override key 约定 + 5 few-shot + 资产 pack 索引 + Asset Checklist
- apps/adore_robot/configs/scenes/warehouse_v0.json: warehouse spec + thumbnail_camera + pcg_params 默认值
- apps/adore_robot/configs/scenes/living_room_v0.json: living_room spec + thumbnail_camera + pcg_params 默认值
- apps/adore_robot/configs/scenes/industrial_corner_v0.json: industrial_corner spec + thumbnail_camera + pcg_params 默认值
- 覆盖 P1 from xiaoxu 全部 6 项 (公开参数表 / override key / few-shot / asset pack / thumbnail viewpoint / Nanite+translucent)
- 单点依赖 xiaoxu 装 5.8 后回填 PCGComponent Python method 真名 (contract §2 placeholder)
