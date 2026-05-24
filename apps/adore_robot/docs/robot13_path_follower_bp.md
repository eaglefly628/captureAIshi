# Robot13_Blueprint — Path Follower 改造步骤

让 worker (Robot13) 沿一组 waypoint 平滑巡逻。改造后 ADORE Python 端
一次写 waypoints 数组进 BP，BP 自己 Event Tick 走完整路径，no flicker。

---

## 1. 新增 Variables (Class Defaults → Variables → +)

| 名字 | 类型 | 默认值 | Access | 说明 |
|---|---|---|---|---|
| `Waypoints`         | `Vector` Array | `[]` | Public, Read/Write   | 路径点列表（**world coords cm**，跟 actor location 同坐标系）|
| `WalkSpeed`         | `float`        | `200.0` | Public, Read/Write | cm/s，2 m/s |
| `CurrentIndex`      | `int`          | `0`   | Private              | 当前指向哪个 waypoint |
| `IsWalking`         | `bool`         | `false` | Public, Read/Write | 主开关；ADORE 写 true 即开始走 |
| `LoopPath`          | `bool`         | `true`  | Public, Read/Write | 走完循环 / 停在终点 |
| `RotateToFace`      | `bool`         | `true`  | Public, Read/Write | 朝向移动方向 |
| `ArriveTolerance`   | `float`        | `10.0`  | Public, Read/Write | 到达判定 cm |

⚠ **Waypoints 必须勾 "Instance Editable" + "Expose On Spawn"** 才能让
ObjectTools.set_properties 通过反射写入。

---

## 2. Event Graph (Event Tick)

```
[Event Tick] ─DeltaSeconds──┐
                            ▼
              [Branch] IsWalking ?
              │
              │ True
              ▼
              [Branch] Waypoints.Length > 0 ?
              │
              │ True
              ▼
              [Get] Waypoints[CurrentIndex] ──→ target_world (Vector)
              [Self → GetActorLocation]        ──→ current
              [delta = target_world − current]
              [distance = VectorLength(delta)]
              │
              ▼
              [Branch] distance < ArriveTolerance ?
              │                            │
              │ True                       │ False
              ▼                            ▼
   ┌─────────────────────────┐   [step = Normalize(delta) × WalkSpeed × DeltaSeconds]
   │ CurrentIndex = (i+1) %  │   [SetActorLocation(current + step,
   │   Waypoints.Length      │                     bSweep=false, bTeleport=false)]
   │                         │   │
   │ Branch:                 │   ▼ (if RotateToFace)
   │   if not LoopPath AND   │   [LookAtRotation(current, target_world)]
   │   CurrentIndex == 0:    │   [SetActorRotation(yaw_only, false)]
   │     IsWalking = false   │
   └─────────────────────────┘
```

### 节点连法（按蓝图实操）

1. **Event Tick** 拖出 → **Branch** (Condition = `IsWalking`)
2. True 引脚 → **Branch** (Condition = `Length of Waypoints > 0`，需要先 `Array Length` 节点)
3. True 引脚 → **Get** `Waypoints` → **Array Get** by `CurrentIndex` → 拿到 target_world
4. **GetActorLocation** (Self) → 拿到 current
5. **Vector − Vector** (target_world − current) → delta；**VectorLength** → distance
6. **Branch** distance < ArriveTolerance
7. **False 分支（继续走）**：
   - **Normalize** delta → dir
   - dir × WalkSpeed → speed_vec
   - speed_vec × DeltaSeconds → step
   - current + step → new_loc
   - **SetActorLocation**(new_loc, Sweep = false)
   - 可选：**FindLookAtRotation**(current, target_world) → 拆 Yaw 重组 Rotator (Pitch=0, Roll=0) → **SetActorRotation**
8. **True 分支（到达，下一个点）**：
   - (CurrentIndex + 1) → next_idx
   - next_idx % Array Length → wrapped_idx
   - Set CurrentIndex = wrapped_idx
   - Branch: NOT LoopPath AND wrapped_idx == 0 → Set IsWalking = false（停车）

---

## 3. 测试 BP 是否就绪

在 UE Editor 里：
1. Play (PIE) → Robot13 actor 在 level 里
2. Outliner 选中 Robot13 → Details 面板找 Default → Robot13 → Waypoints
3. 手动加 3 个 Vector 进去，例如 (0,0,0) / (200,0,0) / (200,200,0)
4. 勾 IsWalking = true
5. Robot13 应该开始走三角形

走通后再接 ADORE python 端。

---

## 4. ADORE Python 端写 waypoints

ADORE 提供 `mcp.set_worker_path(handle, waypoints_world_cm, walk_speed_mps=2.0,
loop=True)`：

- 调 `ObjectTools.set_properties` 一次写入：
  ```json
  {
    "Waypoints":   [{"x":..,"y":..,"z":..}, ...],   // world cm vectors
    "WalkSpeed":   200.0,    // cm/s
    "LoopPath":    true,
    "IsWalking":   true,     // 最后才设，避免还没写 waypoints 就 tick
    "CurrentIndex": 0
  }
  ```
- Waypoints 由 caller 算好——通常是 volume-local 米 + 加 anchor_cm × 100 转成
  world cm。endpoint `/api/demo/set_worker_path` 会帮你算。

---

## 5. ADORE 端用法

```
POST /api/demo/set_worker_path
{
  "actor_handle": "worker_1",
  "waypoints_local_m": [[-3,-3], [3,-3], [3,3], [-3,3]],
  "walk_speed_mps": 2.0,
  "loop": true
}
```

服务端会：
1. 拿当前 volume world_cm 当 anchor
2. 把 waypoints_local_m × 100 + anchor → world cm
3. set_properties 写进 Robot13 BP
4. Robot13 Event Tick 启动，走起来

---

## 已知限制

- `SetActorLocation` 的 Sweep=false 不做碰撞检测，会穿模。要求碰撞检测就
  Sweep=true，但 worker 卡墙时会停。
- UE 后台 throttle 也影响 Event Tick；要让 worker 在后台也走，记得开
  Editor Preferences → "Use Less CPU when in Background" 取消勾选。
- ADORE 写 IsWalking=false 可以暂停，再写 true 续走（CurrentIndex 保留）。
