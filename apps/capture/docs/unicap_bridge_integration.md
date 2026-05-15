# unicap × bridge 整合技术方案

**Date**: 2026-05-09  •  **Author**: 主程序员  •  **Status**: Draft / awaiting approval

## 1. 目标

新增一条**完全独立**的注入路径，与现有 bridge DLL 注入并存：

| 路径 | 注入方式 | AC 兼容 | 适用 |
|------|----------|---------|------|
| **A. bridge DLL**（现有） | CreateRemoteThread + LoadLibraryW | ✗ | 无 AC 或弱 AC |
| **B. unicap addon**（新增） | dxgi.dll proxy（合法 DXGI 加载链） | ✓ | EAC / BattlEye / Hellblade II |

两路在 UI 上提供菜单二选一。后端各自独立模块，互不依赖。C++ 层面通过共享 `bridge_core/` 头文件复用核心逻辑（GEngine 扫描、命令路由、相机 tick、TCP 服务器），仅入口点 (`DllMain` vs ReShade addon entry) 不同。

## 2. 架构总览

```
                 ┌─────────────────────── Python (captureAIshi) ───────────────────────┐
                 │                                                                       │
                 │  web_ui.py  ──[选择 injection_mode: "bridge" | "unicap"]──             │
                 │                          │                                             │
                 │             ┌────────────┴────────────┐                                │
                 │             ▼                          ▼                                │
                 │    grabbers/renderdoc_grabber    grabbers/unicap_grabber                │
                 │      + 3rdparty/bridge/injector    + dxgi.dll proxy deploy              │
                 │             │                          │                                │
                 └─────────────┼──────────────────────────┼───────────────────────────────┘
                               ▼                          ▼
                  ┌───────  Game Process  ─────────────────────────┐
                  │                                                 │
                  │   Path A:  captureAIshi_bridge.dll  ◄──────┐    │
                  │   Path B:  dxgi.dll → ReShade core         │    │
                  │              ├─ 98-bridge_console.addon ◄──┤    │  TCP 9998
                  │              └─ 99-frame_capture.addon     │    │  (drivers/ue5_console.py)
                  │                                            │    │
                  │   Both expose **identical TCP 9998 protocol** ─┘ │
                  └─────────────────────────────────────────────────┘
```

`drivers/ue5_console.py` 不区分 A/B —— 它只看 TCP 端口对面是不是 bridge 协议（`__bridge_ping`）。

## 3. C++ 代码组织（共享设计）

### 3.1 当前结构

```
3rdparty/bridge/src/
├── bridge.cpp        ← 包含 DllMain + 全部业务逻辑（710 LOC）
├── ue5_engine.h      ← 纯 header，GEngine pattern-scan + ExecFn
├── camera_path.h     ← 纯 header，相机路径 / Catmull-Rom
├── pattern_scan.h    ← 纯 header，内存扫描工具
└── CMakeLists.txt    ← 出 captureAIshi_bridge.dll
```

### 3.2 重构后结构

```
3rdparty/bridge/src/
├── bridge_core/                  ★ 新：共享核心
│   ├── bridge_core.cpp           ← 业务逻辑（从 bridge.cpp 拆出，不含 DllMain）
│   ├── bridge_core.h             ← 暴露 startup(port) / shutdown() / route_command()
│   ├── ue5_engine.h              ← (移入)
│   ├── camera_path.h             ← (移入)
│   └── pattern_scan.h            ← (移入)
├── bridge_dll/
│   ├── dllmain.cpp               ← 只剩 DllMain → spawn thread → bridge_core::startup()
│   └── CMakeLists.txt            ← 出 captureAIshi_bridge.dll（路径 A）
└── CMakeLists.txt                ← 顶层，include 两个子目录

3rdparty/unicap/reshade-addons/
├── 99-frame_capture/             ← unicap 现有
└── 98-bridge_console/            ★ 新：ReShade addon
    ├── addon_entry.cpp           ← ReShade addon 注册 + 调 bridge_core::startup()
    ├── CMakeLists.txt            ← include 3rdparty/bridge/src/bridge_core
    └── README.md
```

### 3.3 `bridge_core.h` 接口（最小公共面）

```cpp
namespace bridge_core {
    /* 启动：开 TCP server + 60Hz tick + GEngine scan thread。非阻塞。 */
    void startup(int port = 9998);

    /* 停止：join 所有线程，关 socket。在 DLL detach 或 addon uninit 调。 */
    void shutdown();

    /* （可选）允许宿主自定义 log sink。默认写 captureAIshi_bridge.log。 */
    void set_log_sink(void (*sink)(const char* line));
}
```

`bridge_core.cpp` ≈ 当前 `bridge.cpp` 去掉 `DllMain` + `tcp_server_thread`/`camera_tick_thread`/`startup`/`shutdown` 改为命名空间内导出函数。

**重构差异（精确）**：
- `bridge.cpp:711-738` 整段 `DllMain` 移到 `bridge_dll/dllmain.cpp`。
- `bridge.cpp:637-707` `startup()` / `shutdown()` 改名 `bridge_core::startup()` / `bridge_core::shutdown()`，签名加 `int port` 参数。
- 全文 `static` 全局（`g_*`）保持 `static`，但移入匿名命名空间避免跨 TU 冲突。
- `bridge_log()` 提取为可注入 sink，addon 路径下转发到 ReShade log。

## 4. Path B 详细：ReShade addon

### 4.1 `addon_entry.cpp` 骨架

```cpp
#include <reshade.hpp>
#include "bridge_core/bridge_core.h"

extern "C" __declspec(dllexport) const char *NAME    = "Bridge Console";
extern "C" __declspec(dllexport) const char *DESCRIPTION =
    "captureAIshi: TCP camera/timestop/HUD bridge (port 9998)";

static void on_reshade_log(const char* line) {
    reshade::log_message(reshade::log_level::info, line);
}

extern "C" __declspec(dllexport) bool AddonInit(HMODULE addon_module, HMODULE reshade_module) {
    if (!reshade::register_addon(addon_module, reshade_module)) return false;
    bridge_core::set_log_sink(on_reshade_log);
    bridge_core::startup(9998);  // 与 Path A 同端口
    return true;
}

extern "C" __declspec(dllexport) void AddonUninit(HMODULE addon_module, HMODULE reshade_module) {
    bridge_core::shutdown();
    reshade::unregister_addon(addon_module);
}
```

不 hook `on_reshade_present` —— bridge 不需要渲染线程时机，纯独立线程跑。

### 4.2 ReShade addon CMake

```cmake
# 3rdparty/unicap/reshade-addons/98-bridge_console/CMakeLists.txt
add_library(98_bridge_console SHARED addon_entry.cpp)
set_target_properties(98_bridge_console PROPERTIES
    SUFFIX ".addon"        # ReShade 期望的扩展名
    PREFIX "")
target_include_directories(98_bridge_console PRIVATE
    ${RESHADE_SDK_DIR}/include
    ${CMAKE_SOURCE_DIR}/../../../bridge/src)            # 跨仓引 bridge_core
target_link_libraries(98_bridge_console PRIVATE
    bridge_core ws2_32 psapi)
```

**bridge_core 必须出成 `OBJECT` 或 `STATIC` 库**，让 DLL 和 addon 各自独立链接，避免运行时依赖第三个 .dll。

### 4.3 配套部署文件

每个走 unicap 的游戏目录需要：
```
<game>/
├── dxgi.dll                       ← unicap ReShade core（带 addon support）
├── ReShade.ini                    ← [GENERAL] EffectSearchPaths / TextureSearchPaths
│                                    [ADDON]   AddonPath = .\addons\
│                                    [APP]     PreventFullscreenChange = 1
├── addons/
│   ├── 98-bridge_console.addon
│   └── 99-frame_capture.addon
├── unicap.ini                     ← FC_PreUICapture / FC_PreUISkipCount / FC_OutputDir
└── DepthToAddon.fx                ← unicap 现成，frame_capture 依赖
```

**文件清单由 `grabbers/unicap_grabber.py setup()` 在每次启动时部署**（symlink 优先，跨盘 fallback copy）。teardown 可选清除 —— 默认保留以便 ReShade 的 effect cache 命中。

## 5. Python 侧改动

### 5.1 `grabbers/unicap_grabber.py`（新文件，~250 LOC 估）

实现 `BaseGrabber` 接口（参考 `grabbers/base.py`）：

```python
class UnicapGrabber(BaseGrabber):
    def __init__(self, target_exe: Path, output_dir: Path, *,
                 unicap_root: Path = Path("3rdparty/unicap/dist"),
                 addons: list[str] = ("98-bridge_console", "99-frame_capture"),
                 fc_pre_ui_skip: int = 0,
                 keep_dxgi_on_teardown: bool = True):
        ...

    def setup(self) -> None:
        # 1. 校验 unicap_root 下 dist/ 产物齐全
        # 2. 部署到 target_exe.parent: dxgi.dll, ReShade.ini, addons/*.addon, unicap.ini
        # 3. 启动游戏: subprocess.Popen([target_exe], cwd=...)
        # 4. _wait_for_game_ready: 轮询 TCP 9998 的 __bridge_status
        #    超时 60s（首次加载 ReShade 慢；shader compile 可能更久）

    def capture_frame(self, pose: Pose, frame_idx: int) -> FrameOutputs:
        # 写 fc_state.txt = "capturing"
        # 等 fc_pass_total.txt 计数 +1
        # 读 output/<session>/frame_NNNN_color.bmp + depth.exr + normal.exr

    def teardown(self) -> None:
        # 关游戏 / 关 TCP / （可选）清理 dxgi.dll
```

**与 RenderDocGrabber 的差异**：
- 不调 `renderdoccmd inject` —— 游戏自己加载 dxgi.dll
- `_wait_for_game_ready()` 改轮询 bridge TCP 而非 renderdoc 端口
- `capture_frame()` 走文件 IPC（unicap 现有 sidecar 协议），不走 renderdoc replay

### 5.2 `grabbers/__init__.py` 工厂

```python
def create_grabber(name: str, **kwargs):
    if name == "renderdoc": return RenderDocGrabber(**kwargs)
    if name == "screenshot": return ScreenshotGrabber(**kwargs)
    if name == "obs":        return ObsGrabber(**kwargs)
    if name == "unicap":     return UnicapGrabber(**kwargs)        # ★ 新
    raise ValueError(...)
```

### 5.3 UI 菜单（`web/templates/index.html` + `web_ui.py`）

Capture 面板 Connection 区加 `<select name="injection_mode">`：

| 选项 | 含义 |
|------|------|
| **bridge (DLL inject)** | grabber=renderdoc + bridge DLL 走 injector.py |
| **unicap (DXGI proxy)** | grabber=unicap，bridge 由 ReShade addon 提供 |
| ~~bridge + obs~~        | 现有保留 |

存到 `configs/<game>.json` 的 `injection_mode` 字段，启动时读 → 选 grabber。

### 5.4 driver 不动

`drivers/ue5_console.py` 完全不改 —— 它认 TCP `__bridge_ping`，A/B 路径协议同。

## 6. 构建流程

```
# Path A（现状不变）
cd 3rdparty/bridge && build.bat
# → 3rdparty/bridge/captureAIshi_bridge.dll

# Path B（新增）
cd 3rdparty/unicap && cmake -B build -DUNICAP_WITH_BRIDGE_ADDON=ON
cmake --build build --config Release
# → 3rdparty/unicap/dist/dxgi.dll
# → 3rdparty/unicap/dist/addons/98-bridge_console.addon
# → 3rdparty/unicap/dist/addons/99-frame_capture.addon
```

unicap 的 CMake 加 option `UNICAP_WITH_BRIDGE_ADDON`（默认 ON），关掉则只出 frame_capture。

## 7. Phase 计划

| Phase | 内容 | 工时 | 验收 |
|-------|------|------|------|
| **0. 重构** | bridge.cpp 拆 `bridge_core/` + `bridge_dll/`，原 DLL 跑通端到端（不引入新功能） | 1 天 | Batman 测试用例不回归 |
| **1. spike** | 在 unicap CMake 里建空 addon `98-bridge_console`，仅打印 "loaded"，部署到测试游戏验证 ReShade 真的加载它 | 0.5 天 | 游戏启动后 ReShade.log 出现 addon name |
| **2. 接 bridge_core** | addon_entry.cpp 调 `bridge_core::startup(9998)`，从 Python 端 TCP `__bridge_ping` 通 | 1 天 | TCP 9998 响应 `pong` |
| **3. unicap_grabber.py** | 实现 setup/capture/teardown，与 frame_capture addon 走 sidecar IPC | 2 天 | 一帧 RGB+Depth+Normal 落盘 |
| **4. UI 菜单** | injection_mode 下拉、配置持久化、grabber 工厂分支 | 0.5 天 | UI 切换两路都能开拍 |
| **5. Hellblade II 实测** | 走 Path B 跑通端到端 | 0.5 天 | 拍 10 帧成功 |
| **6. 回归** | Batman / StackOBot 走 Path A 不回归 | 0.5 天 | 现有测试通过 |

合计 ~6 天。Phase 0 是不可跳的前提（共享代码必须先拆好）。

## 8. 风险与决策

| 风险 | 缓解 |
|------|------|
| ReShade 自身被 AC flag | 用官方 "addon-enabled" build；必要时 fork 改签名 |
| GEngine pattern 重编游戏失效 | 已有 `CAPTUREAI_GENGINE_OFFSET` env var 兜底 |
| ReShade addon ABI 跨版本变 | unicap submodule pin 到 SHA `424113d`，CI smoke test |
| 两 addon 加载顺序敏感 | 命名前缀 `98-` < `99-`；frame_capture 在 `on_reshade_present` 末端 hook |
| 游戏自带 dxgi.dll（ENB / mod loader） | unicap proxy 已实现 export forwarding；冲突时日志告警，不静默 |
| bridge_core 重构破坏 Path A | Phase 0 完整跑一次 Batman 端到端，diff log 验证行为无变化 |

## 9. Open Questions

- ReShade core 是否需要我们自己打包，还是 unicap submodule 自带 prebuilt `dxgi.dll`？— 待 spike 阶段确认。
- 是否给 addon 加运行时配置（env var `CAPTUREAI_BRIDGE_PORT`），方便多开？— Phase 2 后视需求加，默认 9998 够用。
- frame_capture 的 `fc_pass_total.txt` 文件 IPC 是否够低延迟做 per-pose 触发？1080p 一帧 16ms 是底线 —— 实测 Phase 3 给出数据。

## 10. 接下来

Phase 0 重构是任何后续工作的前提。提交本文档后等待批准，批准后第一步开 Phase 0。
