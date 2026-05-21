# RobotDemo_PCG_v0 .umap 建图配方 (用户晚上手搭)

> 你的新办公室机器拉完 UE 5.8 Preview + 打开 IAMRobot.uproject 后, 按本
> 配方建 `/Game/Maps/RobotDemo_PCG_v0.umap`. 配 PG_Warehouse.uasset 上线
> v1 PCG 参数化演示用. ~10 分钟落地。
> Date: 2026-05-20. xiaohuan.

---

## 0. 前置 (已就绪)

- ✅ UE 5.8 Preview 装好
- ✅ IAMRobot.uproject 打开
- ✅ `AIAssistant + ToolsetRegistry + ModelContextProtocol + AllToolsets`
     4 个 plugin 开启 (老机器已验)
- ✅ MCP server 监听 `127.0.0.1:8000/mcp` (Editor 启动后 `ModelContextProtocol.StartServer` 一次)
- ✅ v0 spawn 演示用的 `/Game/Maps/RobotDemo1.umap` + `RobotDemo2.umap` 保留不动
- ⏳ **本文要建**: `/Game/Maps/RobotDemo_PCG_v0.umap` (干净 fresh map)

---

## 1. 建 Map (3 分钟)

1. Editor → `File` → `New Level` → 选 `Empty Level`
2. 立即 `Ctrl+S` 存到 `/Game/Maps/RobotDemo_PCG_v0`
3. 顶部 `Window` → `World Settings`:
   - World Partition: **关掉** (v0 不需要 streaming, 30x30m 单 cell 足够,
     World Partition 会让 PCG 行为复杂)
   - GameMode: 默认 (任意, 演示不跑 PIE)

---

## 2. 地面 + 边界 (2 分钟)

1. 顶部 `Place Actors` panel → `Geometry` → `Box`
2. 拖入 viewport, 设 transform:
   - Location: `(0, 0, 0)`
   - Scale: `(15, 15, 0.1)` → 30x30m floor, 厚度 10cm
3. Material: 任意灰色 (默认 `M_StandardCube` 即可, 演示不需要 polish)
4. 重命名: `Floor`

---

## 3. PCG Volume (核心, 5 分钟)

1. `Place Actors` → 搜 `PCG Volume`
2. 拖入 viewport 居中:
   - Location: `(0, 0, 200)` (z=200cm = 2m 抬高半个 volume, 让 PCG 生成层在 floor 之上)
   - Scale: `(2.5, 2.5, 2)` → 默认 PCG Volume 是 1m³, 这里变 25x25x20m,
     比 room_w=18 / room_l=28 默认值留点余量 (PCG bound > room bound 时
     Surface Sampler 自动 clip)
3. 选中 PCG Volume → `Details` panel:
   - **Graph**: 选 `PG_Warehouse` (你晚上跟 xiaohuan 一起搭完后绑定;
     首建时先 None, 留 placeholder)
   - **Generate On Load**: **取消** (重要! xiaoxu MCP 走外部触发, 不要
     map 加载自动 generate 否则演示节奏被打乱)
   - **Seed**: 0 (默认, 后续由 LLM tool_call 改)
4. 重命名: `PCG_Warehouse` (xiaoxu 的 SceneTools.find_actors 靠 name +
   tag 查它)
5. **打 Tag**: Details → `Actor` 折叠 → `Tags` → 加一个 `PCG_Warehouse`
   (xiaoxu 用这个 tag 做 find_actors filter)

---

## 4. BP_DemoOrigin (1 分钟, 跟 v0 spawn 路线复用)

1. `Place Actors` → 搜 `BP_DemoOrigin`
2. 如果已经在 v0 spawn 路线时建过 (RobotDemo1 / RobotDemo2 有), 直接
   `Content Browser` 找 `BP_DemoOrigin` → 拖入 viewport
3. 如果还没有, 在 `Content/Blueprints/` 新建 BP:
   - Parent class: `Actor`
   - 内容: 一个 `Scene Component` 当 root, 无其他逻辑
   - 命名 `BP_DemoOrigin`, save
4. 摆 viewport 中央: Location `(0, 0, 0)`
5. xiaoxu spawn 出来的 v0 actor 全部相对它 anchor (跟 v0 spawn 路线
   兼容: v1 PCG actor + v0 spawn actor 共存)

---

## 5. 灯光 + 相机 (2 分钟)

### 5.1 灯光 (固定方案, 不接 lighting_preset 参数)

1. `Place Actors` → `Lights` → `Sky Light` → 拖入
2. Details → `Real Time Capture`: **勾上**
3. 再拖一个 `Directional Light`, Rotation: `(0, -45, 30)` (典型仓库逆光)
4. 强度: Sky Light Intensity 1.5, Directional 5.0
5. (可选) `Place Actors` → 搜 `Mega Light` 拖 2-3 个吊顶位置, 颜色 sodium 黄
   (~2200K) - 仅当用户演示要"工业灯氛围", 不强求

### 5.2 默认 viewport 相机

1. `Place Actors` → `Cinematic` → `Cine Camera Actor`
2. Location: `(15, -15, 8)` (斜上方俯视 PCG Volume)
3. Rotation: 让相机看向 `(0, 0, 2)` (PCG Volume 中心稍下)
4. 选中相机 → 顶部菜单 `Camera` → `Pilot 'CameraActor'` (锁定视口跟随)
   或 不 Pilot 让用户操作时视角自由

---

## 6. 保存 + 验证 (1 分钟)

1. `Ctrl+S` 保存 map
2. `Content Browser` → 找到 `/Game/Maps/RobotDemo_PCG_v0.umap` 确认存在
3. `File` → `Save All`

### 6.1 MCP 探测验证 (跟 xiaoxu)

```bash
# 在 captureAIshi 仓库根
python apps/adore_robot/tools/probe_mcp.py
```

期望输出 (Step 4 切到这张 map):
```
Step 4: get_current_level() -> /Game/Maps/RobotDemo_PCG_v0
Step 5: find_actors(tag='PCG_Warehouse') -> 1 actor
Step 6: get_properties(actor, ['pCGComponent']) -> nested refPath
```

如果 PCG Volume 的 Graph 字段还没绑 (建图时 placeholder), Step 7 dump
graphInstance 会返回 None - 正常, 等 PG_Warehouse.uasset 搭完绑上去
再 retry。

---

## 7. 跟 PG_Warehouse.uasset 绑定 (你晚上跟 xiaohuan 一起做)

1. 你晚上参 `pg_warehouse_build_cheatsheet.md` + `pg_warehouse_graph_design.md`
   建 `PG_Warehouse.uasset` (路径 `/Game/PCG/Warehouse/PG_Warehouse`)
2. 7 个 Graph Parameter 暴露完 (Expose to Library + Set as Override Param)
3. 回到 RobotDemo_PCG_v0 map → 选 PCG_Warehouse actor → Details → Graph
   field → 选 `PG_Warehouse`
4. PCG Volume 应自动显示 "PCG Component" sub-component, 内部 graphInstance
   已就绪
5. (可选) 点 Details 内 `Generate` 按钮手 trigger 一次 → viewport 看到
   cube 阵列生成

---

## 8. xiaoxu re-enable update_scene 后端到端验

1. xiaoxu 把 `update_scene` tool re-enable 到 `main.py` `/api/chat` tools
   列表 (一行改, 等本步完成)
2. 浏览器开 `http://localhost:5001/`, level chip 切到 `RobotDemo_PCG_v0`
3. chat 输入:
   - `"shelf 密度 0.9"` → 期望: shelf 阵列变密 (更多 cube)
   - `"加 3 台叉车"` → 期望: 3 个黄色 cube 上线
   - `"seed 换成 42"` → 期望: 整图重排 (同密度, 不同位置)
   - `"房间宽 25 米, 长 35 米"` → 期望: PCG Volume bound 不变但 graph
     内 sampler 范围扩大
4. UE Editor 内 viewport 看 cube 阵列实时刷新 - **客户演示链路达成**

---

## 9. 跟 v0 spawn 演示衔接话术

客户演示时按这个顺序:

1. **打开 `/Game/Maps/RobotDemo1.umap`** (v0 spawn 路线)
   - chat: "在中间放一个叉车" → 立刻看到一个 cube 生成
   - chat: "y=10 那排放 5 个货架" → 5 个 cube 一排出来
   - chat: "F1 往左挪 5 米" → 拖动可见
   - 一句一个物件, 直观可控

2. **切到 `/Game/Maps/RobotDemo_PCG_v0.umap`** (v1 PCG 路线, 即本文 map)
   - chat: "shelf 密度 0.9 + 加 3 台叉车 + seed 换一个"
   - 一句话 30+ cube 重生成 + 3 个新叉车 + 整图随机布局变化
   - 一句一图, 震撼

3. (可选) 切回 RobotDemo1 → 在 PCG 生成的基础上手动微调
   - chat: "在 PCG 货架右边再加 2 个箱子" → v0 spawn + v1 PCG 共存
   - `demo_v0_spawned` tag 是隔离边界, PCG 生成的物件不带这个 tag, clear
     操作不会把它们一起删

---

## 10. 常见坑

| 现象 | 解 |
|---|---|
| `Generate On Load` 没关 → map 加载就自动 generate, 演示节奏被抢 | 重要! Details 内取消勾选 |
| `Tag` 没打 → `find_actors(tag='PCG_Warehouse')` 返 0 | 重新加 tag, Save All |
| PCG Volume 太小 → `Bounds < room_w*100 / room_l*100` (UE 用 cm) → Surface Sampler 输出点被 clip | Scale 提到 (2.5, 2.5, 2) 或更大 |
| 切 map 后浏览器 chip 不更新 | 浏览器自动 4s 轮询, 等一下或刷新 |
| PCG Generate 后看不到 cube | Mesh Spawner 的 Mesh field 没配, 全配 `/Engine/BasicShapes/Cube` |
| Substrate material 报错 | v0 演示用 Default `M_StandardCube` 不要 Substrate, 避坑 |

---

## 11. 跟下面文档配套看

- `pg_warehouse_build_cheatsheet.md` — 你建 PG_Warehouse.uasset 1 页速查
- `pg_warehouse_graph_design.md` — 完整 graph 节点拓扑 (含 v0.4 精简说明)
- `pcg_param_contract.md` §1.0 + §1.1 — 7 参数语义 / range / 校验
- `demo_v0_simplified_contract.md` — v0 spawn 路线 (RobotDemo1/2 用)
- `ue58_mcp_capability_report.md` — MCP 整体能力评估
- `ue58_mcp_validation_log.md` (xiaoxu) — Plan B `/api/mcp/probe_graph` 验过 graphInstance.parametersOverrides.parameters 路径
