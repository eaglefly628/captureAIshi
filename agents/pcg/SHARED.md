# PCG Agent (小幻) — Shared Notes

## Active TODO

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
