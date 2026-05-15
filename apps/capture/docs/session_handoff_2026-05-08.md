# Session Handoff — 2026-05-08

## 本次 Session 完成内容

### OBS 录制修复 (xiaoyu)

| 问题 | 修复 |
|------|------|
| OBS 录制在 UE readiness gate 之后才启动（gate 最多等 600s） | 把 recorder start 提前到 driver.connect() 之后、gate 之前 |
| driver_port=4455 连到 OBS 而非 bridge，gate 永远不通过 | 加警告日志（driver_port == obs_port 时提示） |
| OBS settings（host 等）localStorage 失效（每次随机端口） | 改为 POST/GET `/api/obs/config` 写读 `configs/obs.json` |
| grabber=obs 不拉起游戏 | 若 target_exe 存在，用 `launch_game_direct` + `wait_for_game_ready` |
| Connection 字段刷新丢失 | localStorage 持久化 target_exe / driver_host / driver_port / output_dir |
| OBS scene mismatch 报错不友好 | 失败时打印 OBS 当前可用 scene 列表 |
| desktop_app.py 随机端口导致 localStorage 全部失效 | 固定用 5173 端口（被占才随机） |

### Input Recording (xiaoyu)

| 功能 | 说明 |
|------|------|
| `utils/input_recorder.py` | pynput 系统级鼠标键盘录制，无 pynput 时 stub 静默 |
| `web/routes/input_rec.py` | `/api/input/start|stop|status|files|load` |
| UI：⏺ Input Rec tab | 录制控制 + 文件列表 |
| 自动录制 | Start capture → 自动 start input rec；Stop / session 结束 → 自动 stop 并保存 |
| WASD 轨迹可视化 | 等角透视 canvas：WASD 死算位置（含鼠标 yaw 转向）+ 移动平均平滑 + 二次贝塞尔路径 + 胶囊体角色 |

---

## 当前整体状态

### 已验证工作 (end-to-end OK)
- Batman: Arkham Knight — bridge 注入 + renderdoc 采帧 ✓
- OBS 视频录制连接 + 场景切换（OBS 在 198.18.0.1:4455）

### 待解决

| 优先级 | 问题 | 状态 |
|--------|------|------|
| P0 | **Hellblade II 注入失败** — LoadLibraryW 返回 NULL（ec=0）。排除：ProcessSignaturePolicy、LdrLoadDll hook、ProcessImageLoadPolicy 均正常。怀疑 SetDefaultDllDirectories 限制依赖搜索路径，需把 Development/ DLLs 复制到游戏目录测试 | 调查中 |
| P0 | **unicap dxgi.dll proxy 整合** — 新注入方案，无 CreateRemoteThread，不触发 AC。`3rdparty/unicap` 已 clone (424113d)。待实现 `grabbers/unicap_grabber.py` | 新增 |
| P0 | UpdateCamera vtable hook（ULocalPlayer::GetViewPoint）| 设计完成，待实现 |
| P0 | StackOBot 端到端验证 | 进行中 |
| P0 | Path D 逆向补全 | 进行中 |
| P0 | UUU 功能复刻（per-node FOV, play duration, loop, pause/resume, camera_get）| 待实现 |
| P1 | AC 预检脚本（检测 EAC/BE）| 待实现 |

---

## unicap 技术说明（新注入方案）

**仓库**：`3rdparty/unicap/`（https://github.com/raptoravis/unicap）

**注入方式**：
- DX12 / DXGI：`dxgi.dll` proxy 放入游戏目录，替换系统 DXGI 层
- Vulkan：环境变量 `VK_IMPLICIT_LAYER_PATH` / `VK_INSTANCE_LAYERS`
- **不使用 CreateRemoteThread / LoadLibraryW** → 不触发 anti-cheat

**采帧方式**：
- ReShade addon hook `on_begin_render_pass` / `on_bind_rts_dsv`，捕获 pre-UI 渲染目标
- 输出：Color BMP + Depth/Normal EXR，synchronized timestamps
- 附带：键盘鼠标/手柄输入录制（与我们新做的 Input Recording 功能互补）

**整合优先级**：P0，作为 Hellblade II 等 AC 游戏的 fallback grabber

**核心参考文件**：
- `reshade-addons/99-frame_capture/frame_capture.cpp` — ReShade 采帧 addon (~1100 LOC)
- `tools/capture/survey.py` — pre-UI RT skip count 自动探测
- `shaders/DepthToAddon.fx` — depth/normal 导出 shader
- `main.py` — CLI 编排（launch/video/pack 子命令）

---

## 新 Session 首要任务

1. **unicap 整合**（P0）：
   - 分析 `frame_capture.cpp`，理解 DX12 hook 点
   - 实现 `grabbers/unicap_grabber.py`：setup() 把 dxgi.dll 复制到游戏目录，teardown() 移除
   - 在 `create_grabber()` 加 `"unicap"` 选项
   - 测试：Hellblade II（DX12, UE5）

2. **Hellblade II DLL 注入继续排查**（若 unicap 整合前需要）：
   - 把 renderdoc Development/ DLL 复制到游戏目录，测试依赖加载是否修复
   - 备用：直接换 unicap 方案跳过此问题

3. **pynput 安装**（用于 Input Recording 真实事件）：
   ```
   c:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe -m pip install pynput
   ```
