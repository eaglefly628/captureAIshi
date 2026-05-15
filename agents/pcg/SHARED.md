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

### [v0.3.2] 等 xiaoxu 装 5.8 后回填 (单点依赖)

- [ ] **PCGComponent Python method 真名** -- 等 `help(unreal.PCGComponent)` dump，回填 `pcg_param_contract.md` §2 placeholder (当前两个 hypothesis: `set_graph_parameter` / `override_param`)。回填前 contract 的 key 名 + value 类型 + range 仍然有效，不阻塞 xiaoxu batch UI 表单 + tool input_schema 派生

## Boundary & Handoff

- **依赖 xiaoxu**: `UAdoreRobotPCGParams` UCLASS in `AdoreRobotPCG` plugin，UPROPERTY EditAnywhere 对应 contract §1 公开参数；PCG graph 引用此 class 作为 OverrideParams
- **依赖 xiaoxu**: MRQ preset 触发时 PCG `Generate on Demand` 跑完再开 render（cook-time，不上 runtime generation）
- **下游 xiaoxuan**: multi-layer EXR 终交付，PCG 只管 scene 准备好；Substrate + Mega Lights + Nanite+translucent 约束（contract §5）影响 normal/depth pass 一致性，已落 contract

## Reference 速查

详见 `agents/pcg/refs/`:
- `cheatsheet_pcg_graph.md` -- PCG 核心节点 + 数据流模板（5.6/5.7 节点集，5.8 兼容）
- `scene_specs.md` -- 三场景 spec 草稿（本轮已 review + 定稿到 `apps/adore_robot/configs/scenes/`）

## Changelog

### [v0.3.2] <commit-sha> -- xiaohuan
- apps/adore_robot/docs/ue58_pcg_notes_xiaohuan.md: 5.8 PCG 调研 (Step 1) -- DAG eval / Python API / Mega Lights / Nanite+translucent
- apps/adore_robot/docs/pcg_param_contract.md: PCG 参数契约 (Step 2/3) -- 三场景参数表 + override key 约定 + 5 few-shot + 资产 pack 索引 + Asset Checklist
- apps/adore_robot/configs/scenes/warehouse_v0.json: warehouse spec + thumbnail_camera + pcg_params 默认值
- apps/adore_robot/configs/scenes/living_room_v0.json: living_room spec + thumbnail_camera + pcg_params 默认值
- apps/adore_robot/configs/scenes/industrial_corner_v0.json: industrial_corner spec + thumbnail_camera + pcg_params 默认值
- 覆盖 P1 from xiaoxu 全部 6 项 (公开参数表 / override key / few-shot / asset pack / thumbnail viewpoint / Nanite+translucent)
- 单点依赖 xiaoxu 装 5.8 后回填 PCGComponent Python method 真名 (contract §2 placeholder)
