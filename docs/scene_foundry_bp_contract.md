# SceneFoundry — UE5 Blueprint contract

captureAIshi 的 AI Scene 流水线靠 UE5 端的 3 个自定义 BP 函数对接。把它们做在
**Level Blueprint** 或一个常驻 Manager Actor 上即可——只要场景里能被 `ke *`
触发到。

## 1. 文件落点

- captureAIshi 启动目录为根；约定写入 `<cwd>/output/scene_volume.json`。
- 路径可在 UE5 端用 `FPaths::ProjectDir() / TEXT("../../output/scene_volume.json")`
  之类拼接，或直接用绝对路径。

## 2. 必须实现的函数

### 2.1 `SceneFoundry_QueryVolume <VolumeName>`

被 `ke * SceneFoundry_QueryVolume PCGBuilderVolume` 触发。

行为：
1. 用 Tag / Label / Class 查找名为 `VolumeName` 的 Actor。
2. 取 `GetActorBounds(false, Origin, BoxExtent)`（或更精准：访问
   `UPrimitiveComponent::Bounds`）。
3. 把结果写到 `output/scene_volume.json`：

```json
{
  "name": "PCGBuilderVolume",
  "actor_path": "/Game/Maps/Warehouse.Warehouse:PersistentLevel.PCGBuilderVolume_1",
  "bounds_min": [-1500.0, -1000.0, 0.0],
  "bounds_max": [ 1500.0,  1000.0, 300.0],
  "origin":     [0.0, 0.0, 150.0],
  "extent":     [1500.0, 1000.0, 150.0],
  "ts":         1716385780.0
}
```

`bounds_min` / `bounds_max` 是必填字段；Python 端只用这两个。

### 2.2 `SceneFoundry_Spawn <Class> <X> <Y> <Z> <Yaw> <Scale>`

被 `ke * SceneFoundry_Spawn SM_Crate_Large 100.0 200.0 0.0 90.0 1.0` 触发，
每个 actor 一次。

行为：
1. 用 `<Class>` 做 key 查 Blueprint 资产表（你在 BP 里维护一个
   `Map<FString, TSubclassOf<AActor>>`，对应 `scene_gen.layout_gen.WAREHOUSE_CATALOG`
   的 11 个名字）。
2. `SpawnActor` 在 `(X, Y, Z)`，yaw = `<Yaw>`，uniform scale = `<Scale>`。
3. **不要**调用 `RedrawAllViewports`——交给 `SceneFoundry_RefreshViewport`
   批量刷新，避免每次 spawn 都做整 viewport 重绘。

### 2.3 `SceneFoundry_RefreshViewport`

被 `ke * SceneFoundry_RefreshViewport` 触发，每 N 个 spawn 一次（N 在 UI
"Auto-invalidate after spawn" 控制；默认 1，可调高到 5/10 减负）。

行为：
- **Editor 模式**：调 `EditorLevelLibrary.editor_invalidate_viewports()` 或
  Python `unreal.EditorLevelLibrary.editor_invalidate_viewports()`，强制全部
  level viewport 重画一帧。这正是 "不点 viewport 看不到新 actor" 的根治
  方案。
- **PIE / Standalone**：no-op（运行时 viewport 本来就实时 tick）。

替代/兜底：用户在 viewport 工具栏点 ⚡ 启用 **Realtime** 模式（或 Ctrl+R），
之后 viewport 始终 tick，不需要 nudge。

## 3. 资产命名表（与 catalog 对应）

| BP key            | 建议路径                              | half-XY (cm) |
|-------------------|---------------------------------------|--------------|
| SM_Shelf_Large    | /Game/Warehouse/SM/SM_Shelf_Large     | 90 x 30      |
| SM_Shelf_Small    | /Game/Warehouse/SM/SM_Shelf_Small     | 60 x 25      |
| SM_Pallet_Wood    | /Game/Warehouse/SM/SM_Pallet_Wood     | 60 x 60      |
| SM_Pallet_Metal   | /Game/Warehouse/SM/SM_Pallet_Metal    | 60 x 60      |
| SM_Crate_Large    | /Game/Warehouse/SM/SM_Crate_Large     | 50 x 50      |
| SM_Crate_Small    | /Game/Warehouse/SM/SM_Crate_Small     | 30 x 30      |
| SM_Barrel         | /Game/Warehouse/SM/SM_Barrel          | 25 x 25      |
| SM_Box_Large      | /Game/Warehouse/SM/SM_Box_Large       | 40 x 40      |
| SM_Box_Small      | /Game/Warehouse/SM/SM_Box_Small       | 25 x 25      |
| SM_ConveyorBelt   | /Game/Warehouse/SM/SM_ConveyorBelt    | 150 x 40     |
| SM_Forklift       | /Game/Warehouse/SM/SM_Forklift        | 100 x 80     |

half-XY 与 `scene_gen/layout_gen.py::WAREHOUSE_CATALOG` 同步，2D 预览也用这套。

## 4. Smoke test

1. 把上面 3 个函数挂上，启动 Editor，把 PCGBuilderVolume 拖进 level。
2. captureAIshi UI → AI Scene → 输 `PCGBuilderVolume` → 点 Fetch。
   - 期望：4–5 秒内 status 变绿，显示 `Wm x Lm`。
3. 点 Generate（Spawn = on, Refresh = on, count = 推荐值）。
   - 期望：每条 spawn 后 viewport 立即出现新 actor，无需鼠标点击。
4. 关闭 Refresh，重复 step 3。
   - 期望：viewport 不刷新（除非启用 Realtime），客户端进度条仍逐条刷。
