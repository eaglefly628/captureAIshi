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

### [v0.3.3] P1 from xiaoxu via 老白 (方向 B 拍板, 2026-05-16): contract -> AICallable 映射

> **2026-05-17 老白补**: 完整映射表 (三场景 21 参数 + 6 orchestration + 5 UENUM literal) 已落到 `apps/adore_robot/docs/batch_scene_gen_architecture_v2.md` §2.2-§2.4. 你 §8 直接写**两行 + 一个链接**即可: "AICallable Method 映射的 single source of truth 在 v2 doc §2.2-§2.4; 本 contract §1 是参数语义/range/校验源头, v2 §2 是 UFUNCTION/tool name 派生表; 两边不一致以 contract 为准." 不要复制粘贴, 防双源漂移. 另外 §4 加 Example 6 (MCP tool call 序列) 内容参 v2 §3.5.

老白拍板**方向 B = 全面拥抱 UE5.8 MCP**，ref `apps/adore_robot/docs/refs/ue58_ai_mcp_overview.md`。xiaoxu 会写 `UPCGAdoreToolset : UToolsetDefinition`，把你 contract §1 的每个公开参数包成 `UFUNCTION(meta=(AICallable))`。**你的 contract 内容不变，只需新增一节映射表**：

- [ ] `pcg_param_contract.md` 加 §8 "AICallable Method 映射" -- 给每个公开参数列出 (param key / 类型 / 期望的 C++ 方法名 / 期望的 JSON Schema 字段名)。例:
  | param key | type | UFUNCTION name | AI tool schema name |
  |---|---|---|---|
  | `shelf_density` | float | `SetShelfDensity(float Value)` | `set_shelf_density` |
  | `forklift_count` | int | `SetForkliftCount(int32 Value)` | `set_forklift_count` |
  | `lighting_preset` | enum | `SetLightingPreset(EAdoreLighting Preset)` | `set_lighting_preset` |
  - 三场景全列。
  - enum 参数顺便给出对应的 `UENUM` 字面值清单（让 xiaoxu 知道枚举类怎么定义）。
  - 标注每个参数 set 后是否需要 implicit re-generate，还是要 LLM 显式调 `trigger_generate()`（建议显式，agent loop 控制力更强）。
- [ ] §4 NL prompt few-shot 顺手补一条 MCP 风格示例：用户文本 -> 多个 MCP tool call 序列（不再是单个 delta JSON），让 LLM 学会"先 set 几个参数再调 generate"的模式。
- [ ] 其他 contract 内容 (§1-§7) 不变，三场景 JSON spec 不变。

## Boundary & Handoff

- **依赖 xiaoxu**: `UAdoreRobotPCGParams` UCLASS in `AdoreRobotPCG` plugin，UPROPERTY EditAnywhere 对应 contract §1 公开参数；PCG graph 引用此 class 作为 OverrideParams
- **依赖 xiaoxu**: MRQ preset 触发时 PCG `Generate on Demand` 跑完再开 render（cook-time，不上 runtime generation）
- **下游 xiaoxuan**: multi-layer EXR 终交付，PCG 只管 scene 准备好；Substrate + Mega Lights + Nanite+translucent 约束（contract §5）影响 normal/depth pass 一致性，已落 contract

## Reference 速查

详见 `agents/pcg/refs/`:
- `cheatsheet_pcg_graph.md` -- PCG 核心节点 + 数据流模板（5.6/5.7 节点集，5.8 兼容）
- `scene_specs.md` -- 三场景 spec 草稿（本轮已 review + 定稿到 `apps/adore_robot/configs/scenes/`）

## Changelog

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
