# UI Redesign Plan -- PCG Mode for Robotics Scene Foundry

**版本**: 草案 2026-05-13 (老白)
**目标用户**: 机器人训练数据团队 + 内部场景工程师
**对齐**: `docs/robotics_scene_foundry_pitch.md` §9.1.6 最终 scope
**实施 agent**: xiaoyu (UI) + unreal_pcg_robot (PCG backend)

---

## 1. 现状摘要

| 维度 | 当前值 |
|---|---|
| 前端 | `web/templates/index.html` 单文件 ~4200 行（HTML + 内联 JS + CSS variables） |
| 后端 | `web_ui.py` 129 行薄壳 + `web/routes/` 11 个 blueprint（capture / games / hacks / obs / paths / sessions / trajectory / bridge / tools / input_rec） |
| 布局 | 3 栏：Sidebar（参数 cascade lv1→lv2→lv3）/ Center（日志 + Input Rec）/ Right（预览 + 画廊） + Toolbar + Debug Panel + Modals |
| 主流程 | 选游戏 → 配 capture 参数 → 启 `renderdoccmd` → 拍 RGB+Depth+Normal → 出 `trajectory.json` |

## 2. 设计原则

1. **双模式并存**: Toolbar 加 `Capture | PCG` 切换，左栏独立，但共享 CSS variables / 通用组件（日志、预览、画廊、3D 可视化、Debug Panel）
2. **保持一致性**: 跟现 capture 模式同布局（3 栏）、同 cascade（lv1→lv2→lv3）、同 modal 风格、同 dark theme
3. **0 回归**: 现 capture 流程的代码、route、配置文件**全部保留不动**
4. **后端复用最大化**: 公共 `/api/sessions` / `/api/preview` / `/api/log` 不分模式，PCG 新增 routes 只覆盖 PCG 专属动作
5. **本周只规划 + 起脚手架**，实操等 ReShade AOB 跑通信号

## 3. 信息架构

### 3.1 Toolbar Mode Switch

```
┌──────────────────────────────────────────────────────────────────────────┐
│  [☰ Menu]  ◉ Capture   ○ PCG    [Help]  [Settings]  ●Live/○Demo  [Theme]│
└──────────────────────────────────────────────────────────────────────────┘
```

- 切换瞬间换左栏内容 + Toolbar 上下文按钮，中栏 / 右栏 / Debug Panel 不变
- 切换状态写 `localStorage.uiMode` + URL param `?mode=pcg`（深链可分享）

### 3.2 PCG 模式左栏 cascade

**Level 1 (Sidebar root)** — 5 类参数槽位:

```
┌─ PCG Parameters ────────┐
│ ▸ 场景模板              │   (warehouse / 客厅 / 工业一角)
│ ▸ PCG 控制              │   (seed / 密度 / 变体数)
│ ▸ 机器人 URDF           │   (FRANKA Panda / Unitree H1 / UR5 / 多机)
│ ▸ 渲染 + 数据           │   (MRQ 分辨率 / Cosmos Transfer 开关 / 帧数)
│ ▸ 数据导出              │   (LeRobot / RT-X / GR00T / 仅原始)
└─────────────────────────┘
```

**Level 2 (slide-out 二级表单)** — 比如点 `▸ 场景模板`:

```
┌─ 场景模板 ──────────────┐
│ ◉ Warehouse 50×50m     │   ← 三类预设
│ ○ 客厅 5×7m            │
│ ○ 工业一角 8×8m        │
│ ○ Custom (上传 PCG 图) │
│                        │
│ [详细配置 →]            │   → 进 lv3
└─────────────────────────┘
```

**Level 3 (lv3 细节面板)** — 比如 Warehouse 细节:

```
┌─ Warehouse 细节 ────────┐
│ 长 (m):     [50    ]   │
│ 宽 (m):     [50    ]   │
│ 货架行数:   [8     ]   │
│ 通道宽 (m): [3.5   ]   │
│ 货架高 (m): [4     ]   │
│ 资产包:     [Quixel ▼] │   ← Fab / Quixel / 自建
│ [保存为 preset]         │
└─────────────────────────┘
```

每个 lv2 入口对应一组 lv3 细节面板，结构跟现 capture 模式的 `path` / `cone` / `output` 完全同构 — 复用 `cascadePanel.js`（如果还没抽，这次抽出来）。

### 3.3 中栏 + 右栏（不动）

- **Center**: 复用日志 + 进度条 + Input Rec panel。日志加 PCG 阶段标签前缀 `[PCG]` / `[UE-MRQ]` / `[Cosmos]` / `[Adapter]`
- **Right preview**: 复用画廊 + 3D 可视化器。新增 PCG 专属预览类型：
  - "场景缩略图"（PCG 生成完一份 thumbnail，UE MRQ 出一张 1080p preview）
  - "URDF 姿态预览"（kinematic 静态摆放截图）
  - 训练帧（跟现 RGB/Depth/Normal 三联一样）

### 3.4 Status Bar 加 PCG 字段

```
┌───────────────────────────────────────────────────────────────────────────┐
│ ● Connected | Mode: PCG | Run: warehouse_seed42 | Stage: MRQ 12/30 | ...│
└───────────────────────────────────────────────────────────────────────────┘
```

## 4. 新增后端 routes（`web/routes/pcg.py`）

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/pcg/templates` | 列三类场景模板 + custom |
| POST | `/api/pcg/configure` | 接收 lv3 参数，写 `output/<run>/scene_manifest.json` |
| POST | `/api/pcg/start` | 启动 `UnrealEditor-Cmd.exe -run=PCGGen -manifest=...` headless |
| GET | `/api/pcg/status` | 当前 stage（PCG / MRQ / Cosmos / Adapter）+ 进度 |
| POST | `/api/pcg/stop` | 中止运行 |
| GET | `/api/pcg/urdf` | 列可选机器人 URDF |
| POST | `/api/pcg/export` | 触发 LeRobot / RT-X / GR00T 适配器，参数 `schema=lerobot\|rtx\|gr00t` |
| GET | `/api/pcg/export/status` | 适配器进度 |

## 5. 新增后端 driver（`drivers/unreal_pcg.py`）

跟现 `drivers/ue5_console.py` 同位置，但走完全不同协议:

```python
class UnrealPCGDriver:
    """Launch UnrealEditor-Cmd.exe headless to run a PCG graph."""

    def __init__(self, ue_root: Path, project: Path, manifest: Path):
        ...

    def start(self) -> subprocess.Popen:
        # UE 5.8 + URDF kinematic poser + 我们的 PCG asset
        cmd = [
            self.ue_root / "Engine/Binaries/Win64/UnrealEditor-Cmd.exe",
            str(self.project),
            "-run=PCGGen",
            f"-manifest={self.manifest}",
            "-MRQ=Sequencer/PCG_Render.MoviePipelineConfig",
            "-nullrhi" if self.dry_run else "",
            "-stdout", "-FullStdOutLogOutput",
        ]
        return subprocess.Popen(cmd, ...)

    def parse_progress(self, line: str) -> Optional[dict]:
        # 解析 UE 标准日志 "LogPCG: Render frame 12/30"
        ...
```

启动逻辑跟 `RenderDocGrabber.setup()` 那一套对齐（poll log for ready signal，不 sleep）。

## 6. 资产 / 配置目录

```
configs/
├── hacks/                       # 现有 game profiles (不动)
├── pcg/                         # 新增 PCG 场景预设
│   ├── _schema.md
│   ├── warehouse_50x50.json
│   ├── livingroom_5x7.json
│   ├── industrial_8x8.json
│   └── _default_seed.json
└── robots/                      # 新增 URDF 元数据
    ├── franka_panda.json        # 含 URDF 路径 + 关节限位
    ├── unitree_h1.json
    └── ur5.json

unreal_projects/                 # 新增（gitignore 实际工程, 只 track manifest）
└── RobotFoundry/
    ├── Content/PCG/Graph_Warehouse.uasset
    ├── Content/PCG/Graph_LivingRoom.uasset
    └── ...
```

## 7. 数据导出（`adapters/`）

```
adapters/
├── __init__.py
├── base.py                # ExporterBase ABC
├── lerobot.py             # parquet + videos schema (HuggingFace v2)
├── rt_x.py                # TFDS schema (Google Robotics)
└── gr00t.py               # NVIDIA Isaac GR00T schema
```

`Export As ...` 按钮 -> `POST /api/pcg/export {schema, run_id}` -> 跑 `adapters/<schema>.export(run_dir, target_dir)`，后台进度推到 `/api/pcg/export/status`。

## 8. 实施路线（4 phase，~3.5 周）

### Phase 0 — 视觉重构 + 提亮配色（~3 天）

**前提**：当前 capture UI 配色极暗（`--bg-base: #0a0a0a`），文字对比度偏低，长时间使用眼累。先把现有风格抬亮一档再叠 PCG 模式，避免新旧风格不一致。

**配色方案 (拟定，xiaoyu 可微调)**

```css
:root {
  /* 背景：从近黑提到深石墨色，3 级层次更清晰 */
  --bg-base:     #16181d;   /* 原 #0a0a0a */
  --bg-surface:  #1c1f26;   /* 原 #111111 */
  --bg-elevated: #242832;   /* 原 #1a1a1a */
  --bg-overlay:  #2d3340;   /* 原 #222222 */
  --bg-hover:    rgba(255,255,255,0.06);   /* 原 0.04 */
  --bg-selected: rgba(91,138,240,0.14);    /* 用 accent 染色, 不再是中性白 */

  /* 边框：稍亮一档 */
  --border-subtle:  rgba(255,255,255,0.10);
  --border-default: rgba(255,255,255,0.16);
  --border-strong:  rgba(255,255,255,0.26);

  /* 文字：拉对比度 (WCAG AA on bg-base ≥ 4.5:1) */
  --text-primary:     #f4f4f5;   /* 原 #ededed, 微调 */
  --text-secondary:   #b4b8c0;   /* 原 #a0a0a0, 提亮 */
  --text-tertiary:    #7a8088;   /* 原 #5a5a5a, 提亮 */
  --text-placeholder: #4a4f57;   /* 原 #3a3a3a */

  /* Accent：保留蓝, 同时引入暖橙做次强调避免全冷色 */
  --accent:       #6ea1ff;       /* 原 #5b8af0, 微亮 */
  --accent-hover: #8db4ff;
  --accent-dim:   rgba(110,161,255,0.18);
  --success:      #4ade80;       /* 原 #3ecf8e, 提亮 */
  --warning:      #fbbf24;       /* 原 #f5a623, 提亮 */
  --danger:       #f87171;       /* 原 #f03e3e, 不刺眼 */
  --info:         #60a5fa;
  --orange:       #fb923c;       /* PCG 模式专用次强调色 */

  /* 圆角：统一抬到 6px / 8px, 视觉更柔 */
  --radius:    6px;             /* 原 4px */
  --radius-md: 8px;
  --radius-lg: 12px;            /* 新增: 大卡片用 */

  /* 字体不动 */
}
```

**视觉规范升级**

| 项 | 现状 | 目标 |
|---|---|---|
| 主背景对比 | 3 级 #0a/#11/#1a 区分微弱 | 4 级 #16/#1c/#24/#2d 阶梯清晰 |
| 文字对比度 | secondary #a0a0a0 on #0a0a0a ≈ 6.4:1 | 提到 #b4b8c0 on #16181d ≈ 8.2:1 |
| selected state | 中性白 6% 不明显 | 用 accent 蓝色 14% 染色，态明确 |
| 圆角 | 4px 偏方 | 6/8/12px 三档，跟现代 SaaS 一致 |
| 阴影 | 几乎没有 | 加 elevation tokens（lv1/lv2/lv3 三档 box-shadow） |
| spacing rhythm | 散乱（5/7/11px 都有） | 强制 4px 网格（4/8/12/16/24/32） |

**新增 elevation tokens**

```css
:root {
  --elev-1: 0 1px 2px rgba(0,0,0,0.30);
  --elev-2: 0 2px 6px rgba(0,0,0,0.36);
  --elev-3: 0 8px 20px rgba(0,0,0,0.45);
}
```

`.panel` / `.modal` / `.lightbox` / `.dropdown` 全部按层级套对应 elevation。

**Phase 0 任务清单**

- [ ] `web/templates/index.html` 顶部 `:root` 块整体替换为新 CSS variables
- [ ] 全局 audit：所有写死的 `#xxx` 颜色（grep `#[0-9a-fA-F]{3,6}` 应只剩 0 处）替换为变量
- [ ] spacing audit：所有 `padding` / `margin` 不在 4px 网格上的统一到最近网格
- [ ] 加 `--elev-*` tokens 并应用到 panel/modal/lightbox/dropdown
- [ ] selected state 全替换为 accent 染色（list item / dropdown option / cascade lv2 active）
- [ ] dark mode 自检：长时间看不刺眼 + 文字 WCAG AA + selected 一眼可辨
- [ ] **可选**：加一个 `data-theme="light"` 备用 light theme（白底）作为后期开关，但本周不实装切换 UI
- [ ] **验证**：现有 capture 流程跑一遍截图，对比前/后视觉

**Phase 0 完成标志**：xiaoyu 在 SHARED.md 贴一组 before/after 截图（Toolbar + Sidebar + Center + Modal 各 1 张）。老白看图过审才进 Phase A。

### Phase A — 脚手架 + 双模式切换（~1 周）

- [ ] `web/templates/index.html`: Toolbar 加 mode switch + PCG sidebar shell（lv1 + 5 空槽 lv2 + 占位 lv3）
- [ ] `web/routes/pcg.py`: 8 个 stub routes 全 return mocked JSON
- [ ] `web/templates/pcg/*.html`: 拆 PCG 左栏为 partial，capture 不动
- [ ] `cascadePanel.js`: 抽离公用 cascade 行为
- [ ] **验证**: mode 切换平滑，左栏切换无闪烁，capture 模式 0 回归（跑一次 capture 端到端）

### Phase B — 后端打通（~1 周）

- [ ] `drivers/unreal_pcg.py`: `UnrealPCGDriver.start/stop/parse_progress`
- [ ] `configs/pcg/warehouse_50x50.json`: 第一个真实模板（先 mock 参数，后接 PCG asset）
- [ ] `unreal_projects/RobotFoundry/`: 起个空 UE 5.8 工程 + 1 个 PCG graph stub
- [ ] `unreal_projects/RobotFoundry/Content/Python/run_pcg_headless.py`: UE 内 Python 入口
- [ ] **验证**: UI 点 Generate → UE-Cmd 启 headless → 出空 `.uasset` + 假 thumbnail，UI 进度条到 100%

### Phase C — 适配器 + 端到端（~1 周）

- [ ] `adapters/lerobot.py`: 跟 LeRobot v2 dataset spec 对齐（parquet + mp4 + meta）
- [ ] `adapters/rt_x.py`: RT-X TFDS skeleton
- [ ] `adapters/gr00t.py`: GR00T schema skeleton
- [ ] UI Export 下拉 + 进度面板
- [ ] **验证**: warehouse 50x50 一份场景跑完整 pipeline，导出 LeRobot 格式 ≤ 1 分钟，HF datasets `load_dataset` 能正常读

## 9. 兼容性 / 风险

| 风险 | 缓解 |
|---|---|
| `index.html` 单文件已 4200 行，再加 PCG 撑到 6000+ 不可维护 | Phase A 把 PCG 部分独立成 `web/templates/pcg_partial.html`，用 Jinja `{% include %}` |
| Toolbar mode 切换可能误伤 capture 用户肌肉记忆 | 默认进站记 `localStorage.uiMode = 'capture'`，老用户 0 感知 |
| UE 5.8 URDF poser 未到位 (Epic 无官方 Robotics Plugin, 参 ue58_engine_notes §5) | `drivers/unreal_pcg.py` 启动失败时退回 `pcg --dry-run` 模式，UI 用假帧推流，离线开发可继续 |
| 三套 schema 实施差异大，工作量爆 | Phase C 先打通 LeRobot 一套（最热门），RT-X / GR00T 占位即可 |
| PCG 模式跟 capture 模式 state 互相污染 | `_capture_state` / `_pcg_state` 物理隔离，session id 加前缀 `cap-` / `pcg-` |

## 10. 不做（明确划线）

- ✗ React / Vue 重写（坚持 vanilla JS + Jinja，跟现仓库 style 一致）
- ✗ 真实物理仿真接入（Isaac Sim 等，已在 §9.1.6 划线不做）
- ✗ 训练侧任何代码（policy / RL / imitation）
- ✗ Cosmos Transfer 2.5 接入到 UI（Phase C 之后再说，本规划只占位）
- ✗ 多用户 / 权限 / 团队管理（desktop tool，单机用）

## 11. 工作分配建议

| Agent | Phase A | Phase B | Phase C |
|---|---|---|---|
| **xiaoyu (UI)** | 主力（Toolbar / Sidebar / cascade 抽离 / Jinja 拆分） | 接 PCG status polling + 进度组件 | Export 下拉 + 适配器进度面板 |
| **unreal_pcg_robot** | 起 UE 工程 + 1 个 dummy PCG graph + run_pcg_headless.py | 主力（PCG asset / MRQ config / 三类场景 graph） | URDF kinematic posing |
| **xiaoxuan (rendering)** | 顾问 | 接 MRQ 多层 EXR 输出（Cryptomatte 等） | 适配器读 EXR -> 转 LeRobot 视频 |
| **xiaoni (reversing)** | hold | hold | hold |
| **老白** | 这份规划 + 复审 Phase A 第一份 commit | Adapter schema 选型决策（LeRobot 优先级） | 验收 + bump v0.4.0 |

## 12. 启动时机

ReShade AOB camera control 跑通后（参考 `agents/rendering/SHARED.md` P0），下周一开 Phase A kickoff。

跑通信号到达前：
- 这份规划 freeze 在 docs/，xiaoyu 可以先读熟 + 在自己 SHARED.md 提 review 问题
- unreal_pcg_robot 没有 SHARED.md 工作板（暂搁），但可以先看 `.claude/agents/unreal_pcg_robot.md` 知识库准备

---

**Open Questions（让用户拍）**

1. ❓ UE 工程要不要进 git？我倾向 `unreal_projects/` 写进 `.gitignore`，只 track `Content/PCG/*.json` manifest 和 `Content/Python/*.py` 脚本（`.uasset` 二进制走 Git LFS 或独立 Perforce）
2. ❓ Cosmos Transfer 2.5 接入是 Phase C 还是 Phase D（独立 phase）？Cosmos GPU 配额没批之前，UI 这边能做的只是占位按钮 + 显示 "wait Inception approval"
3. ❓ 数据导出阶段，是否需要 **数据集预览**（导出后在 UI 里展示前 N 帧 + meta 校验）？我倾向加，~半天工时

---

**附：现有 UI 关键文件清单（不动的部分）**

```
web_ui.py                        129 行（薄壳）
web/__init__.py / state.py / helpers.py
web/routes/capture.py            主 capture API
web/routes/games.py              23 款 game profile 列表
web/routes/hacks.py              AOB intercept / mem_poke
web/routes/obs.py                OBS WebSocket
web/routes/paths.py              waypoint / cone rotation
web/routes/sessions.py           会话管理 + 画廊
web/routes/trajectory.py         trajectory.json 输出
web/routes/bridge.py             bridge dll TCP 9998
web/routes/tools.py              renderdoccmd 工具入口
web/routes/input_rec.py          键鼠录制
web/templates/index.html         4247 行单文件 SPA
```

PCG 新增**只增不改**，0 回归。
