# UUU/IGCS 功能复刻调研报告

**作者**: 小由 (UI Agent)
**日期**: 2026-04-05
**版本**: v0.3.0
**目的**: 为 captureAIshi 复刻 UUU/IGCS 核心功能提供技术方案，供下一个 session 实施。

---

## 1. UUU/IGCS 架构分析

### 1.1 技术栈

| 组件 | 技术 | 开源? | 我们的对应 |
|------|------|-------|-----------|
| DLL 注入 | IGCSInjector (WriteProcessMemory + CreateRemoteThread) | 开源 | renderdoc 注入 / bridge DLL |
| 函数 Hook | [MinHook](https://github.com/TsudaKageyu/minhook) (x86/x64 API Hooking) | MIT | bridge 中的 hook |
| 内存扫描 | AOB (Array of Bytes) pattern scan | 开源 | Cheat Engine driver |
| GUI Overlay | [Dear ImGui](https://github.com/ocornut/imgui) (hooked into DirectX/Vulkan) | MIT | Web UI (外置) |
| 3D 数学 | DirectXMath.h (Windows SDK) | MS | numpy + core/ |
| 相机插值 | Catmull-Rom spline (自研) | 闭源(UUU) / 开源(IGCS) | core/tangent_smoothing.py |
| ReShade 集成 | [IgcsConnector](https://github.com/FransBouma/IgcsConnector) | 开源 | 无 |
| 构建 | MSVC 2019+, C++17 | - | CMake + MSVC |

### 1.2 IGCS 核心架构 (开源部分)

```
IGCS per-game DLL
├── InterceptorHelper.cpp    # AOB 扫描定位相机结构体地址
│   └── AOBBlock patterns    # 字节模式 → 找到游戏内相机写入代码
├── CameraManipulator.cpp    # 读写相机数据
│   ├── g_cameraStructAddress + OFFSET → float[3] 坐标
│   ├── g_cameraStructAddress + OFFSET → float[12] 旋转矩阵(3x3)
│   ├── g_fovStructAddress + OFFSET → float FOV
│   └── hostImageAddress + OFFSET → byte timestop (0/1)
├── Camera.cpp               # 相机状态管理 (quaternion → matrix)
├── System.cpp               # 键位绑定, 主循环
├── Globals.cpp              # 全局状态
└── OverlayControl.cpp       # ImGui overlay 渲染
```

**关键设计**: 每个游戏独立一份代码副本，不共享基类。因为每个游戏的内存布局完全不同。

### 1.3 UUU 特有部分 (闭源)

UUU 比 IGCS 多了：
- **通用 UE4/UE5 引擎扫描** — 不需要 per-game AOB，自动找 GEngine/UWorld
- **UE Console 重建** — 重新激活被禁用的控制台
- **Camera Path 系统** — Catmull-Rom 插值 + 关键帧属性
- **灯光/Actor 操控** — 遍历 UWorld Actor 列表
- **Skeletal Mesh Posing** — 操控骨骼变换矩阵
- **Hotsampling** — Hook DX/Vulkan Present 改分辨率

---

## 2. Camera Path 功能详解

### 2.1 数据模型

```
CameraPath
├── name: string
├── nodes: CameraPathNode[]
│   ├── position: {x, y, z}
│   ├── orientation: {pitch, yaw, roll} 或 quaternion
│   ├── fov: float
│   └── custom_props: dict    # 游戏特有: TimeOfDay, GameSpeed 等
├── total_play_time: float (seconds)
├── loop: bool
└── interpolation: "catmull-rom"
```

### 2.2 Node 操作

| 操作 | 快捷键 | 说明 |
|------|--------|------|
| Add Node | ^ 按钮 | 在当前 node 后插入，记录当前相机状态 |
| Delete Node | X 按钮 | 删除选中 node (不可撤销) |
| Go to Node | 点击 | 相机跳转到该 node 的位置预览 |
| 重排序 | 拖拽 | 上下移动 node 顺序 |

### 2.3 播放逻辑

```python
# 伪代码: Camera Path 播放
def play_path(path, total_time):
    nodes = path.nodes
    t = 0
    dt = 1.0 / fps
    while t <= 1.0:
        # Catmull-Rom 插值: 找到 t 对应的 segment
        segment_idx = int(t * (len(nodes) - 1))
        local_t = (t * (len(nodes) - 1)) - segment_idx
        
        # 取 4 个控制点 (p0, p1, p2, p3)
        p0 = nodes[max(0, segment_idx - 1)]
        p1 = nodes[segment_idx]
        p2 = nodes[min(len(nodes)-1, segment_idx + 1)]
        p3 = nodes[min(len(nodes)-1, segment_idx + 2)]
        
        pos = catmull_rom(p0.pos, p1.pos, p2.pos, p3.pos, local_t)
        rot = slerp(p1.orientation, p2.orientation, local_t)
        fov = lerp(p1.fov, p2.fov, local_t)
        
        driver.set_pose(pos, rot)
        driver.set_fov(fov)
        
        t += dt / total_time
        if path.loop and t > 1.0:
            t -= 1.0
```

### 2.4 与 captureAIshi 现有代码的映射

| UUU 概念 | captureAIshi 现有 | 差距 |
|----------|------------------|------|
| CameraPathNode | `core/waypoint.py::CameraPose` | 需加 per-node FOV |
| Catmull-Rom 插值 | `core/tangent_smoothing.py` | **已实现** |
| 路径保存/加载 | `trajectory.json` | 需扩展格式 |
| 播放逻辑 | `main.py::capture_loop` | 需分离为独立模块 |
| 3D 预览 | `index.html` 3D Viewer | 需加交互编辑 |

---

## 3. 完整功能复刻方案

### Phase 1: Camera Path Editor (优先级最高)

**目标**: Web UI 中交互式创建/编辑/播放相机路径

#### 3.1.1 后端 API 新增

```python
# web_ui.py 新增路由
POST   /api/path                    # 创建新路径
GET    /api/path/<id>               # 获取路径数据
PUT    /api/path/<id>               # 更新路径
DELETE /api/path/<id>               # 删除路径
GET    /api/paths                   # 列出所有路径
POST   /api/path/<id>/play          # 开始播放
POST   /api/path/<id>/stop          # 停止播放
POST   /api/path/<id>/node          # 添加 node
DELETE /api/path/<id>/node/<idx>    # 删除 node
PUT    /api/path/<id>/node/<idx>    # 编辑 node
GET    /api/camera/current          # 获取当前相机位置 (从 driver)
```

#### 3.1.2 数据格式 (camera_paths.json)

```json
{
  "paths": [
    {
      "id": "path_001",
      "name": "Flyover",
      "created": "2026-04-05T10:00:00",
      "total_time": 10.0,
      "loop": false,
      "nodes": [
        {
          "position": [1.0, 2.0, 3.0],
          "rotation": [0.0, 0.0, 0.0, 1.0],
          "fov": 90.0,
          "custom": {}
        }
      ]
    }
  ]
}
```

#### 3.1.3 前端 UI 设计

```
┌─────────────────────────────────────────────┐
│  3D VIEW (Canvas)                           │
│  [路径可视化 + 可点击/拖拽 node]             │
│  左键点击空白处 = 添加 node                  │
│  左键拖拽 node = 移动位置                    │
│  右键 node = 编辑属性 / 删除                 │
├─────────────────────────────────────────────┤
│  PATH CONTROLS                               │
│  ┌──────────────────────────────────────────┐│
│  │ Path: [Flyover ▾] [+ New] [Delete]      ││
│  │ Nodes: [1] [2] [3] [4] [+Add Current]  ││
│  │ Time: [10.0]s  [□ Loop]                 ││
│  │ [▶ Play] [⏸ Pause] [⏹ Stop]            ││
│  │ Selected Node #2:                        ││
│  │   Pos: [1.0] [2.0] [3.0]               ││
│  │   Rot: [0] [45] [0]                     ││
│  │   FOV: [90]                              ││
│  └──────────────────────────────────────────┘│
└─────────────────────────────────────────────┘
```

#### 3.1.4 播放引擎 (core/path_player.py 新文件)

```python
"""Camera path playback engine.

Reads a path definition, interpolates between nodes using
Catmull-Rom splines, and pushes poses to the driver in real-time.
"""
class PathPlayer:
    def __init__(self, driver, path_data):
        self.driver = driver
        self.nodes = path_data["nodes"]
        self.total_time = path_data["total_time"]
        self.loop = path_data["loop"]
    
    def play(self, stop_event):
        """Play the path, pushing interpolated poses to driver."""
        # 使用 core/tangent_smoothing.py 的 catmull_rom_chain()
        # 按 total_time 等分时间步
        # 每步: 插值 pos/rot/fov → driver.set_pose()
        pass
```

### Phase 2: 实时相机控制

**目标**: 键盘/手柄实时操控游戏内相机

| 功能 | 实现方式 |
|------|---------|
| WASD 移动 | WebSocket 推送 → driver.set_pose() |
| 鼠标旋转 | WebSocket 推送 → driver.set_rotation() |
| 滚轮 FOV | WebSocket 推送 → driver.set_fov() |
| "记录当前位置" 按钮 | GET /api/camera/current → 添加为 node |

需要 WebSocket 替代 HTTP 轮询，延迟要 < 16ms (60fps)。

### Phase 3: Timestop & Game Speed

| 功能 | 实现方式 |
|------|---------|
| Timestop | bridge 已有: `slomo 0` / `UWorld::IsPaused` |
| Game Speed | bridge: `slomo 0.5` / `slomo 2.0` |
| Frameskip | bridge: `pause` + `unpauseframe` 逐帧推进 |

### Phase 4: 灯光控制

| 功能 | 实现方式 |
|------|---------|
| 添加 Spotlight | UE console: `summon SpotLight` + 设置位置/朝向 |
| 添加 Pointlight | UE console: `summon PointLight` + 设置属性 |
| 调节亮度 | `SET` 命令修改 Light component 属性 |
| 场景灯调暗 | 遍历 LightActor, 乘以系数 |

### Phase 5: Actor 操控 (高级)

需要深入 UE5 反射系统，通过 bridge 遍历 UWorld → Level → Actors。

---

## 4. 关键开源资源

| 资源 | URL | 用途 |
|------|-----|------|
| IGCS (开源相机系统) | https://github.com/FransBouma/InjectableGenericCameraSystem | 参考架构、CameraManipulator 实现 |
| MinHook | https://github.com/TsudaKageyu/minhook | API Hooking (我们 bridge 已用类似技术) |
| IgcsConnector | https://github.com/FransBouma/IgcsConnector | ReShade ↔ IGCS 数据交换协议 |
| FModel Game-Compatibility | https://github.com/FModel/Game-Compatibility | UE4/UE5 游戏列表 (199 款) |
| framedsc Sitesource | https://github.com/framedsc/Sitesource | UUU v3 游戏列表 markdown (332 款) |
| Dear ImGui | https://github.com/ocornut/imgui | GUI 参考 (我们用 Web UI 替代) |

---

## 5. captureAIshi 已有基础 (不需要重写)

| 模块 | 文件 | 可复用于 |
|------|------|---------|
| Catmull-Rom 样条 | `core/tangent_smoothing.py` | Camera Path 插值 |
| CameraPose (位置+旋转) | `core/waypoint.py` | Path Node 数据模型 |
| 路径生成 | `core/snake_path.py` | 自动路径模式 |
| UE5 Console 通信 | `drivers/ue5_console.py` | 实时控制 |
| Bridge DLL | `3rdparty/bridge/` | 引擎内 hook (GEngine/timestop/HUD/hotsampling) |
| CE 内存驱动 | `drivers/cheat_engine.py` | 内存直接读写 |
| 3D Viewer | `web/templates/index.html` | 路径编辑器 canvas |
| trajectory.json | 输出格式 | 路径保存/加载 |

---

## 6. 下一个 Session 实施建议

### 优先级排序

1. **Camera Path Editor UI** — 在 3D Viewer 中添加交互式 node 编辑
2. **Path Player 引擎** — `core/path_player.py` 实时播放
3. **Path API** — `web_ui.py` CRUD + 播放控制路由
4. **实时相机控制** — WebSocket 推送 (需要 flask-socketio)
5. **Game Speed / Frameskip** — bridge 扩展

### 预估工作量

| Phase | 涉及文件 | 复杂度 |
|-------|---------|--------|
| Phase 1 (Path Editor) | index.html, web_ui.py, core/path_player.py | 大 (新功能) |
| Phase 2 (实时控制) | index.html, web_ui.py (WebSocket) | 中 |
| Phase 3 (Timestop/Speed) | web_ui.py, drivers/ | 小 (bridge 已有) |
| Phase 4 (灯光) | web_ui.py, bridge 扩展 | 大 (逆向) |
| Phase 5 (Actor) | bridge 扩展 | 很大 (深度逆向) |

---

## 7. 网络访问备注

以下 URL 被当前网络代理 403 拦截，需要本地访问或加白名单:
- `opm.fransbouma.com/*` — UUU v4/v5 完整游戏列表、功能文档
- `framedsc.com/*` — 社区教程
- `web.archive.org` — 缓存页面
- `patreon.com` — 最新兼容游戏帖子

可访问的替代源:
- GitHub raw 文件: `raw.githubusercontent.com` ✅
- GitHub API: `api.github.com` ✅
- Google Translate 代理: 偶尔可用
