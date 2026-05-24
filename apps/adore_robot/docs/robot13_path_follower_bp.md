# Robot13 Path Follower -- C++ 方案（不动 BP 节点）

让 worker 沿一组 waypoint 平滑巡逻。**用 C++ ActorComponent 实现**，不
需要在 BP 编辑器里接任何节点；BP 上只需要 `+ Component` 添加这个
Component 一次即可。

代码在 `docs/cpp/`：
- `PathFollowerComponent.h`
- `PathFollowerComponent.cpp`

---

## 1. 集成到 UE 工程（xiaoxu）

### 1.1 拷贝文件

```
docs/cpp/PathFollowerComponent.h
  -> apps/adore_robot/unreal_projects/AdoreRobot/Source/AdoreRobot/Public/

docs/cpp/PathFollowerComponent.cpp
  -> apps/adore_robot/unreal_projects/AdoreRobot/Source/AdoreRobot/Private/
```

### 1.2 检查 .Build.cs 依赖

`Source/AdoreRobot/AdoreRobot.Build.cs` 的 `PublicDependencyModuleNames`
需要至少包含：

```csharp
PublicDependencyModuleNames.AddRange(new string[] {
    "Core", "CoreUObject", "Engine", "InputCore",
});
```

`UKismetMathLibrary::FindLookAtRotation` 来自 Engine，已经在里面，不
需要新增。

### 1.3 检查 module API 宏

`PathFollowerComponent.h` 顶部用了 `ADOREROBOT_API`。这必须跟 module
名一致。打开 `Source/AdoreRobot/AdoreRobot.h`（或 .Build.cs）看
module name；如果不叫 `AdoreRobot`，把 .h 里的 `ADOREROBOT_API` 改
成实际的 `<MODULENAME>_API`。

### 1.4 编译

UE Editor 关掉 → VS / Rider 编译 AdoreRobot module → 重开 UE Editor。
或者 UE Editor 顶栏 "Live Coding" (Ctrl+Alt+F11) 热重载。

编译完 Editor Content Browser 不需要操作；Component 是 C++ 类，自动
注册到 ClassGroup `Adore` 里。

---

## 2. 挂到 Robot13_Blueprint（30 秒，不接节点）

1. Content Browser 双击打开 `Robot13_Blueprint`
2. 左侧 **Components** 面板 → **+ Add**
3. 搜索框输 `Path Follower` → 选 **Path Follower (ADORE)** 添加
4. 编译 + 保存
5. 完事

不需要写任何节点。Component 自带 Tick，挂上就能跑。

---

## 3. ADORE Python 端用法

调 `POST /api/demo/set_worker_path`：

```json
{
  "actor_handle": "worker_1",
  "waypoints_local_m": [[-3, -3], [3, -3], [3, 3], [-3, 3]],
  "walk_speed_mps": 2.0,
  "loop": true
}
```

后端会：
1. 用当前 PCGVolume 的 `world_cm` 当 anchor，把 local 米转成 world cm
2. `ObjectTools.set_properties` 写入 Robot13 actor 上 PathFollower
   Component 的属性：
   - `Waypoints` -> 转好的 world cm 列表
   - `WalkSpeed` -> cm/s
   - `LoopPath` -> bool
   - `CurrentIndex` -> 0
   - `bIsWalking` -> true（最后翻，避免 tick 撞上半写状态）
3. Component 下一帧 Tick 开始走路

属性名跟 C++ UPROPERTY 名一致（`bIsWalking` / `bLoopPath` —— UE5.8 MCP
反射用 UPROPERTY 真名，跟 BrushComponent / RelativeLocation 同惯例）。

---

## 4. 测试顺序

### 4.1 BP 自测（不依赖 ADORE）

1. PIE 跑起来 → 选中 Robot13 actor → Details 面板找
   **Path Follower** → 展开
2. 手动加 3 个 Waypoints（注意是 world cm，例如基于当前 Robot13
   location 加几百 cm）
3. 勾 `Is Walking` = true
4. Robot13 应该开始平滑走

### 4.2 ADORE 端联调

1. spawn 一个 worker（chat 输 `加 1 个 worker 在 0,0`）
2. curl 或浏览器 POST `/api/demo/set_worker_path`（body 见 §3）
3. worker 应该沿矩形巡逻一圈

### 4.3 暂停 / 续走 / 改路径

- 暂停：发空 body `{actor_handle: ..., waypoints_local_m: []}` 会清空
  waypoints + 写 `bIsWalking=false`。或者单独 POST 一个只设
  `{"bIsWalking": false}` 的 set_properties RPC
- 续走：再 POST 完整 body，CurrentIndex 回 0 重新开始
- 中途换路径：直接 POST 新的 waypoints_local_m，Component 立刻按新
  路径走（旧路径丢弃）

---

## 5. 已知限制

- `SetActorLocation(Sweep=false)` 不做碰撞检测，会穿模。要碰撞就
  把 `bSweep` 改 true，但 worker 卡墙会停在原地（适合机器人，不适
  合鬼）。
- UE Editor 后台 throttle 会拉低 Tick 频率 -> 后台时 worker 走得慢。
  解法：Editor Preferences → General → Performance → 取消 "Use Less
  CPU when in Background"。
- ADORE 写 `Waypoints` 数组超过几十个点 UE5.8 MCP set_properties 的
  JSON payload 会变大，但 BP 反射没有显式上限。实测百级 waypoints
  OK。

---

## 6. 对比方案 B（demo_move 轮询）

| 维度 | C++ Path Follower (本方案) | demo_move 轮询 (start_patrol 假版) |
|---|---|---|
| 平滑度 | 真插值，60 FPS 走 | delete+respawn，每 2s 闪一下 |
| Python 通信 | 一次 set_properties | 每 2s 一次 demo_move RPC |
| 碰撞 | 可选 Sweep | 无 |
| 性能 | UE 端 Tick 几乎无开销 | 每步 2-3 RPC + actor 销毁 / 生成 |
| 演示效果 | 像真机器人 | 像 PPT 翻页 |

C++ 方案正式上线后，`/api/demo/start_patrol`（假版）可以下线。
