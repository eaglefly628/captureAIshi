# UE 5.8 Preview -- Engine-side Notes (xiaoxu)

Audience: xiaoxu 自用 + 老白审。Source: `ue58_preview_capabilities.md` (research subagent, 2026-05-15) + xiaoxu 复核。本文只写**对 adore_robot UE 工程化有影响**的子项，按"事实 / 我的判断 / 我要做的事"三段呈现。

`[no data]` 项不假装确定，原文标记保留。

---

## 1. Python Editor Scripting (`unreal.py`)

**事实**:
- 5.7 `unreal.PCGGraph` / `unreal.PCGComponent` 已有 working bindings: 设参数、连节点、rebuild graph。forum 有 working snippet（[Forum: PCG params from python][1]）。
- 5.8 Python 模块新增项: `[no data]`。
- stub 文件路径: `Intermediate/PythonStub/unreal.py`，开 Developer Mode 自动生成。

**判断**:
- NL → PCG 链路上游需要的 API 在 5.7 baseline 就有，不押 5.8 新东西。
- 真正可调用的 PCG override param 方法名 + 签名（`SetGraphParameter` vs `SetOverrideParam` vs 直接 set UPROPERTY）必须靠 stub diff 实证，preview doc 没列出来。

**待办**:
- [ ] **Step 0 实证**: 装 5.8 Preview 后跑 `python -c "import unreal; help(unreal.PCGComponent)"`，把 PCG 相关 method 全 dump 到 `apps/adore_robot/docs/unreal_py_pcg_dump.txt`。这是 NL→PCG 链路写实现前的最后一关。
- [ ] stub diff 5.7 vs 5.8 (`diff Intermediate/PythonStub/unreal.py`)，新增 PCG / MRG 绑定单独列。

[1]: https://forums.unrealengine.com/t/how-to-change-pcg-graph-parameters-from-python/2060532

---

## 2. Movie Render Queue / Movie Render Graph

**事实**:
- 5.8 MRQ/MRG: `[no data]`。MRG 仍是替代 MRQ 的方向。
- 5.7 multi-layer EXR 流程未变: `Movie Render Queue Additional Render Passes` + `EXR (Multilayer)`，一文件出 FinalImage / Object Ids / World Depth / Motion Vectors。
- **已知 5.7 wart**: "render all cameras" + EXR 在 MRQ 里坏，JPG 没事。

**判断**:
- 我的 `cheatsheet_mrq.md` 配置（PIZ + Spatial 8 / Temporal 4 + deterministic CVars）直接照搬，零迁移成本。
- 唯一风险点是 "all cameras + EXR" 这个 wart 在 5.8 是否修。我们的批量场景是**单相机轨迹按 frame 输出**，不是 multi-camera，所以这个 wart 不阻塞，但要在 §9.1.6 sampling spec 上钉死"per-variant 1 camera + N frames"模式，不留 multi-camera 后路。
- MRG 替代 MRQ 不在本期范围。等 5.8 release（非 Preview）再评估。

**待办**:
- [ ] 把 `MRQ_MultiPassEXR.uasset` preset 在 5.8 Preview 重存一遍（asset 版本号差异），git 记一次 commit。
- [ ] 写一个 `tools/verify_exr_channels.py`（已经在 cheatsheet 里有片段，独立化），cook 完跑一遍校验通道齐全 (FinalImage / WorldNormal / SceneDepth / ObjectId / GBufferA)。
- [ ] commandlet 触发 MRQ 的最小命令实证（cheatsheet 里写的命令是 5.6 路径，5.8 改 `UE_5.8` 后 verify）。

---

## 3. Substrate

**事实**: 5.7 Production-ready + default-on，5.8 `[no data]` 改动。

**判断**: 继续用 Substrate 写 material。无迁移工作。

**待办**:
- [ ] 三场景 hero material（warehouse 金属货架、客厅织物、industrial 油漆铁皮）都走 Substrate slab，避免 legacy material 后续返工。小幻先出 PCG，我跟进 material 化时再做。

---

## 4. Lumen / Nanite / VSM / Mega Lights

**事实**:
- Mega Lights production-ready in 5.8（noise 降低，console + handheld 提速）。
- Lumen Medium Quality (Beta): ~2x faster than Lumen High GI。
- Nanite Skinning (5.7): trees-as-skeletal-mesh 可 Nanite。5.8 Procedural Vegetation Editor 升级。
- Nanite translucent: 仍不支持（不可见 = 用 opacity-masked 替代）。

**判断**:
- **Mega Lights 是最大利好**: warehouse 50-200 fixture 现在 real-time 可用，不用 bake light，cook 时间砍掉 light bake 阶段。
- **Lumen Medium 必须 A/B 测**: 如果 SSIM vs Lumen High 损失可接受，dataset 吞吐翻倍。
- Nanite translucent 限制对我们影响小（客厅玻璃窗用 opacity-masked），但要在 PCG asset checklist 里钉死"不要 translucent material on Nanite mesh"。

**待办**:
- [ ] cheatsheet_mrq.md 的 CVars 段增加 `r.MegaLights.Enable=1` 备选。
- [ ] A/B test plan: warehouse_v0 + variant_0 跑两遍，一遍 Lumen High 一遍 Lumen Medium，比 SSIM + 看 final image。结果写 `docs/lumen_medium_ab.md`（下个 session）。
- [ ] PCG asset spec 里加 "no translucent on Nanite mesh" 约束，给 xiaohuan 写到他的 P1 里。

---

## 5. Robotics Plugin -- **RED FLAG, 必须重新决策**

**事实**:
- preview doc 明确写: `[no data]` -- Epic 在 5.8 Preview 文档里**没有官方 Robotics plugin**。
- 我的 `xiaoxu.md` "UE5.6 Robotics Plugin Beta" 说法**无公开源**，需视为**假设错误**。
- 第三方现状: URLab (5.7+，MuJoCo-in-UE，活跃)、URoboSim (IAI 维护)、ad-hoc URDF-to-BP converters。

**判断**:
项目地基级风险。三个备案：

| Plan | 方案 | 优点 | 缺点 |
|---|---|---|---|
| A | [URLab](https://github.com/URLab-Sim/UnrealRoboticsLab) | 活跃维护，MuJoCo 集成（更准物理） | 5.8 兼容性 `[no data]`，需 fork 维护 |
| B | [URoboSim](https://github.com/urobosim/URoboSim) | 老牌，IAI 维护 | 偏 ROS 生态，kinematic-only 适合度待验 |
| C | 自撸 minimal URDF parser + kinematic posing BP | 完全可控，不依赖第三方 | 工作量大（urdfpy 类 parser + bone driver），但只做 kinematic 不接物理时可控范围 |

**我倾向 C**: 我们只要 kinematic posing（joint angle → mesh transform），不需要 MuJoCo 的物理；URLab/URoboSim 的物理引擎是我们用不上的负担。但工作量评估前不下结论。

**待办**:
- [ ] **第一件事**: 装完 UE5.8 Preview 打开 Plugin Manager 搜 "Robot" / "URDF" / "Articulation" / "Inverse Kinematics"，确认是否真没官方。结果落到本文 §5 加 `[verified <date>]` 标记。
- [ ] 若确认无官方: 写 `docs/robotics_plugin_decision.md`，对比 Plan A/B/C 的 (兼容性 / 维护成本 / 真值精度 / 接入工时)，给老白做选择题。
- [ ] **不在本期写代码**。本期产出限于决策 doc。

---

## 6. USD

**事实**: 5.7 baseline (USD Stage Editor, Live Actor / Stage Importer Beta) 不变。5.8 PCG → USD export `[no data]`。

**判断**: 跨 DCC 工具链（Houdini/Blender 互通）保留 5.7 能力。如果老白选 Houdini Engine 路线，USD 是接口；否则不优先。

**待办**:
- [ ] 老白决定是否上 Houdini Engine 后，单独评估 USD 链路。本期挂起。

---

## 7. PCG (小幻主域，我只看交接面)

**事实** (xiaoxu 视角，详细看 `ue58_pcg_notes_xiaohuan.md` 出来后):
- DAG eval ~2-2.5x faster (5.7→5.8)，warehouse 2km² 全 regen 提速；单节点 edit 从十秒级降到个位数。
- "edit procedural output without breaking graph" 新工作流。
- Mesh Terrain (5.8 Experimental) 原生接 PCG。
- Python: 5.7 baseline 工作，5.8 PCG-specific binding 改动 `[no data]`。

**判断 (xiaoxu 侧)**:
- DAG 提速直接利好 NL→PCG agent loop: 每个 LLM delta 提交后等的时间从十几秒缩到几秒，loop 可用性提一个等级。
- "edit procedural output preserved" 让"NL 调一个参数 + 手工微调一台叉车" 不冲突。
- Mesh Terrain 暂不用（三场景都是室内 / 8x8 小室外）。
- xiaohuan 那边出参数清单后，我才能确定 Python override 是 `SetGraphParameter` 还是别的接口（见 §1 待办）。

**待办**:
- [ ] 跟 xiaohuan 对 `OverrideParams` USTRUCT key 命名约定: 字符串名 vs PCG-internal GUID。这条挂在他的 P1（见 `agents/pcg/SHARED.md`）。

---

## 8. World Partition / OFPA / Build / Cook

**事实**: 5.8 World Partition / OFPA / Zen Loader / Incremental Cook 改动 `[no data]`。5.7 baseline 继续。Incremental Cook 5.7 有"几乎和 clean cook 一样慢"的 known issue，5.8 需验证。

**判断**:
- 三场景规模都小（warehouse 50x50m / 客厅 5x7m / industrial 8x8m），World Partition 单 cell 装得下，cell streaming 不是热点。
- Zen Loader 开（`s.ZenLoaderEnabled=True` + `s.AsyncLoadingThreadEnabled=True`）能提编辑器迭代速度，5.8 也保留这个 knob。

**待办**:
- [ ] `Config/DefaultEngine.ini` 加 Zen Loader 启用（小工程不一定值得，等批量 cook 慢的时候再开）。
- [ ] Incremental Cook 第一次跑 + 改一个 actor 再 cook，对比时间，定是否启用。
- [ ] World Partition 单 cell 即可，不分 sublevel。

---

## 9. LLM / AI 集成 (Epic 侧)

**事实**: 5.8 `[no data]` -- Epic 无官方 LLM / Verse-AI / Smart Object semantic。第三方: UnrealGenAISupport, Convai, Flopperam, Personica AI, Local LLM (Fab)。

**判断**:
- 不等 Epic。NL → PCG agent loop 由我们自己起（Anthropic SDK，见 `batch_scene_gen_architecture.md` §3）。
- 第三方插件不评估，直接 Python 进程 + HTTP 调 Claude API，UE 端只负责 PCG generate + MRQ render。Engine 不嵌 LLM。

**待办**: 无（决策 = 不在 engine 侧引入 LLM 插件）。

---

## 10. 其他值得标记

- **Mesh Terrain (Experimental, 5.8 new)**: 室内三场景不用；如果未来加 outdoor industrial 变种再启用。
- **Procedural Vegetation Editor**: 室内场景不用；客厅可能有盆栽 placeholder 走传统 static mesh。
- **MetaHuman Crowd**: 当前无 human co-worker；如果机器人 + 人协作场景加上来再启用。
- **Direct Mesh Controls (Experimental)**: 跟 Robotics §5 决策耦合，若 Plan C 自撸，DMC 是 articulation 后备方案。本期忽略。

---

## 11. 5.8 采纳前置操作 (我的版本)

按优先级：

1. **5.8 Preview 装机** (1 台 Windows workstation，独立于生产)。
2. **Plugin Manager 实证 Robotics** -> 更新本文 §5 verified 标记 -> 触发 Plan A/B/C 评估 doc。
3. **`unreal.py` stub diff (5.7 vs 5.8)** + 单独 dump PCG / MRG bindings (§1 待办)。
4. **MRQ_MultiPassEXR 在 5.8 重存** + 跑 cheatsheet 里的 CLI 最小命令实证。
5. **PCG DAG 提速 benchmark**: warehouse_v0 第一份 graph 出来后跑 5.7 vs 5.8，验证 ~2-2.5x。
6. **Mega Lights + Lumen Medium A/B**: warehouse_v0 + variant_0 两遍 render，比 SSIM。
7. **生产工程冻结 5.7** 直到 5.8.0 (非 Preview) 发布。Preview 只在调研机上跑。
