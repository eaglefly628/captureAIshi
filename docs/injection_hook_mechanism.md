# captureAIshi 注入与 Hook 机制详解

> 面向：逆向/图形同事，想搞清楚 captureAIshi 跑起来之后到底是怎么"控制游戏相机、抓 RGB/Depth/Normal"的。
>
> 覆盖：DLL 注入、GEngine 自动定位、UE5 Exec 虚函数调用、IGCS 风格的 camera_intercept inline patch、AOB pattern 匹配，以及把这些模块串起来的关键函数。

---

## 0. 10 秒速览

捕获一帧流程 = **两条独立通道**同时工作：

```
┌───────────────────────── Control Plane ─────────────────────────┐
│                                                                  │
│  Python (main.py)                                                │
│     │                                                            │
│     │ ① 生成 waypoints / snake path                               │
│     │                                                            │
│     ▼                                                            │
│  drivers/ue5_console.py  ──TCP:9998──▶  captureAIshi_bridge.dll   │
│                                          (注入到游戏进程)         │
│                                          │                       │
│                                          ▼                       │
│                           GEngine->Exec("SetViewLocation ...")   │
│                           或 inline hook (camera_intercept)      │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌───────────────────────── Data Plane ────────────────────────────┐
│                                                                  │
│  grabbers/renderdoc_grabber.py                                   │
│     │                                                            │
│     │ ② renderdoccmd capture / inject 到游戏 → 抓 .rdc             │
│     │ ③ capture_bridge (C++ replay) → 分离 UI / 抽取 RGB+Depth+N  │
│     │                                                            │
│     ▼                                                            │
│     output/<session>/frame_XXXX.{png, exr, npy}                   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

两条通道都依赖**把代码塞进目标游戏进程**，而"塞进去"的方式有三种。

---

## 1. 三种把代码放进游戏进程的方式

| 方式 | 注入者 | 被注入者 | 用途 | 受 anti-cheat 影响 |
|---|---|---|---|---|
| (A) `captureAIshi_bridge.dll` | `3rdparty/bridge/injector.py` 的 `CreateRemoteThread + LoadLibraryW` | 游戏进程 | 控制面: TCP 9998, 执行 UE5 console 命令, 装 AOB hook | 高：经典手法，easy-AC / EAC 基本全拦 |
| (B) `renderdoc.dll` | RenderDoc 自家 launcher (或 `renderdoccmd inject`) | 游戏进程 | 数据面 + **内嵌** `console_server.h` 也监听 TCP 9998 | 中：RenderDoc 自带旁路逻辑 |
| (C) `ExternalMemoryDriver` | **不注入** | — | 从外部用 `ReadProcessMemory` / `WriteProcessMemory` 直接改相机结构体 | 低：不进进程，大多数 user-mode AC 拦不住；kernel-mode AC (Vanguard) 会拦 |

**为什么 bridge DLL 同时存在两个副本**：一个是独立的 `3rdparty/bridge/captureAIshi_bridge.dll`，一个是编进 `renderdoc.dll` 的 `console_server.h`。它们共享 `pattern_scan.h` / `ue5_engine.h` / `camera_path.h` / `camera_intercept.h` 四个头。前者靠 LoadLibraryW 注入；后者借 RenderDoc 的注入路径搭便车，避开单独再起一次 CreateRemoteThread 的 AC 检测。

---

## 2. 注入机制（方式 A）——经典 CreateRemoteThread + LoadLibraryW

代码：`3rdparty/bridge/injector.py`

### 2.1 五步流程

```python
# inject_dll(pid, dll_path)
1. OpenProcess(pid, PROCESS_ALL_INJECT)
2. VirtualAllocEx(h_process, size=len(dll_path_wide), PAGE_READWRITE)
3. WriteProcessMemory(..., dll_path.encode("utf-16-le"))
4. GetProcAddress(kernel32, "LoadLibraryW")  # 本进程里找，地址在目标进程里相同
5. CreateRemoteThread(h_process, start=LoadLibraryW, arg=remote_mem)
   → WaitForSingleObject + GetExitCodeThread  # ExitCode 就是 HMODULE
```

- 关键函数：`inject_dll` (`injector.py:120`)、`inject_by_name` (`injector.py:243`)、`wait_and_inject` (`injector.py:266`)
- 走 `kernel32.LoadLibraryW` 而不是自己做 PE loader 是因为它在所有 Windows 上地址固定（同 session），不需要在远端进程里再做重定位。
- DLL 架构必须和目标匹配（x64 游戏配 x64 DLL）。失败时返回的 ExitCode=0 就是没 load 成功，十有八九是架构不对、依赖 DLL 缺失、或 AC 在 `DllMain` 里 kill 了。

### 2.2 为什么单开一个 startup 线程

`DllMain` 里持有 loader lock，任何 I/O / TCP / 创建线程都可能死锁。所以：

```cpp
// bridge.cpp:707
BOOL APIENTRY DllMain(..., DWORD reason, ...) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        std::thread(startup).detach();   // 立即 return，让 loader 继续
    }
    ...
}
```

`startup()` 里才去扫 GEngine、起 TCP server、起 tick 线程。

---

## 3. GEngine 自动定位（方式 A / B 共享）

代码：`3rdparty/bridge/src/ue5_engine.h`

`GEngine` 是 UE5 的万物之源：拿到它就能 Exec console 命令，拿到 Exec 就能 `SetViewLocation` / `slomo` / `ShowHUD` 什么都能干。问题是 shipping build 没有符号，地址每次版本变，不能硬编码。

### 3.1 优先级链

```
find_gengine()              ue5_engine.h:344
  ├── (1) env: CAPTUREAI_GENGINE_OFFSET=<hex>     # 手工覆盖
  ├── (2) find_gengine_via_string_xref()          # 自动扫
  └── (3) 等用户通过 TCP 的 __bridge_set_offset 喂地址
```

### 3.2 String xref 算法（核心）

核心原理：UE 里一定会出现的几个宽字符串（`L"ToggleDebugCamera"`、`L"r.Streaming.PoolSize"` 等）会被某段代码引用；那段代码附近 512 字节内一定会有一条 `mov rax, [rip+disp32]` 把 `GEngine` 全局指针加载到寄存器。

```cpp
// ue5_engine.h:184 find_gengine_via_string_xref()
1. find_wstring_in_module(base, size, L"ToggleDebugCamera")
   → 拿到 .rdata 里的字符串地址
2. find_xrefs(base, size, str_addr)
   扫模块里所有 `48 8D 05 ?? ?? ?? ??` (LEA r64, [rip+disp])
   → 得到引用该字符串的指令地址列表
3. 在每个 xref 周围 [-256, +512] 扫 `48 8B 05 ?? ?? ?? ??`
   (mov r64, [rip+disp]) ← 这一条就是加载 GEngine 的指令
4. resolve_rip_relative(p, 3, 7) → 得到全局变量的绝对地址
5. 验证这个地址指向的指针 != 0 && >= 0x10000 && 第一个 QWORD (vtable) 也 >= 0x10000
   → SEH 包住所有解引用，AC/DRM 可能把页 uncommit 掉
6. 找到 → 存 g_engine_ptr, g_engine_global_addr, g_engine_found=true
```

相关工具函数：

- `pattern_scan` (`pattern_scan.h:51`) — mask 式字节扫描，`x` 精确匹配、`?` wildcard
- `find_xrefs` (`pattern_scan.h:143`) — 枚举所有 `REX + 8B/8D + ModRM(00,*,101)` 的 RIP-relative 引用
- `resolve_rip_relative` (`pattern_scan.h:126`) — `rip = instr + len + disp32`
- `seh_probe_readable` / `seh_read_u64` (`ue5_engine.h:135-156`) — 用 `__try/__except` 包住解引用，避免 AC 把游戏弄崩

### 3.3 Exec 虚函数的 vtable 探针

`UEngine::Exec` 是虚函数，不同 UE 版本 vtable index 不一样 (5.0-5.1: ~114, 5.4+: ~120)。策略：

```cpp
// ue5_engine.h:414 exec_console_command()
for (int idx = 110; idx <= 130; idx++) {
    ExecFn try_exec = (ExecFn)vtable[idx];
    if (!validate_function_ptr(try_exec)) continue;  // 检查函数序言字节

    // 先发安全命令 L"stat none" 探针
    if (!seh_call_exec(try_exec, g_engine_ptr, L"stat none", g_log_ptr))
        continue;

    // 活下来了 = 找到 Exec，缓存 g_exec_fn 以后直接用
    g_exec_fn = try_exec;
    // 然后才发用户真正的命令
    seh_call_exec(g_exec_fn, g_engine_ptr, wcmd.data(), g_log_ptr);
    return true;
}
```

关键点：**不是盲调**。每一次调用都在 SEH 保护里，先用 `stat none`（副作用为 0 的命令）探针，失败就跳过，找到之后才发真命令。这是为什么即使 Exec 偏移漂了半个指令，游戏也不会崩。

函数签名（x64 MSVC `__fastcall`）：

```cpp
typedef bool (__fastcall *ExecFn)(
    void* engine,         // rcx = this
    void* world,          // rdx = UWorld* (NULL = 全局)
    const wchar_t* cmd,   // r8
    void* output_device   // r9 = GLog or NULL
);
```

---

## 4. IGCS 风格 Inline Hook —— `camera_intercept.h`

`Exec("SetViewLocation ...")` 只在 UE 里管用，UE3/UE4 的老游戏、或者 engine 每帧自己覆盖相机的场景（比如 Batman Arkham Knight），就必须**把游戏每帧写相机结构体的那几条 `mov` 指令直接拿掉**。这就是 "camera_intercept"。

代码：`renderdoc/renderdoc/core/bridge/camera_intercept.h`

### 4.1 三种 mode

| mode | 现场指令 | 效果 |
|---|---|---|
| `CAM_MODE_PASS` | 原字节 | 游戏自己写相机，外部写会被下一帧冲掉 |
| `CAM_MODE_NOP` | `0x90` 填满 | 游戏的写变成空操作；外部通过 memory write 设的相机**能留住** |
| `CAM_MODE_CAPTURE` | 14 字节 `jmp [rip+0]; dq stub` + `NOP` 补齐 | 跳到动态生成的 asm stub，把相机结构体基址（`rbx`/`rdi`/...）记下来再跳回去 |

### 4.2 install 流程

```
cam_intercept_install_aob(aob_hex, size, name, occurrence)
  │
  │ ① cam_parse_aob()          — 把 "89 83 ?? 05 00 00 ..." 解析成 bytes + mask
  │ ② scan_main_module_nth()    — 在游戏主模块里找第 N 次出现
  │ ③ cam_parse_base_reg()     — 读第一条指令的 ModRM 字节，拿到基址寄存器编号
  │                              (0..15, 0=rax, 3=rbx, 7=rdi, 8..15 配 REX.B)
  │ ④ VirtualQuery + 边界检查    — 拒绝跨页、拒绝不可读、拒绝已经有 site 的地址
  │ ⑤ 保存原字节 to site.orig, 准备 NOP 填充 to site.nops
  │ ⑥ push_back 到 g_cam_sites
  │
  └── 初始 mode = PASS（不动游戏字节）
```

### 4.3 切到 CAPTURE mode 时动态生成 29 字节 stub

`cam_build_capture_stub` (`camera_intercept.h:269`):

```
  push rax                                          ; 50
  mov  rax, <base_reg>        ; 48/4C 89 C0|..      ; REX + 89 + ModRM
  mov  [abs64], rax           ; 48 A3 <8 bytes>     ; 写 g_cap_addr[slot]
  pop  rax                                          ; 58
  jmp  qword ptr [rip+0]      ; FF 25 00 00 00 00
  dq   <continue_addr>        ; <8 bytes, 指向原 block 之后>
```

总共 29 字节，`VirtualAlloc` 一整个 4KB 页（`PAGE_EXECUTE_READWRITE`），用 `0xCC` 填满（乱跳进来会触发 INT3）。

现场 patch 是 14 字节的 `jmp qword ptr [rip+0]; dq stub`（`cam_build_capture_patch`, `camera_intercept.h:318`），剩余字节补 `0x90`。因此 **AOB 匹配的 `size` 必须 >= 14**，否则 capture 模式装不上。

### 4.4 为什么需要 ModRM 解析

一条 `mov [rbx+0x574], eax` 和 `mov [rdi+0x04], eax`，字节不一样。stub 要知道基址寄存器是 `rbx` 还是 `rdi` 才知道把哪个寄存器的值写到 `g_cap_addr[slot]`。

`cam_parse_base_reg` (`camera_intercept.h:222`):

```
skip SSE/size 前缀 (F2/F3/66)
可选 REX (0x40..0x4F) — 记下来，REX.B 给 base 寄存器 +8
读 opcode，只接受：
    0x89            mov r/m, r          (UE3 Batman: mov [rbx+0x574], eax)
    0x0F 0x11       movups/movaps       (UE4/5: movups [rdi+0x60], xmm0)
读 ModRM:
    mod==3 → 寄存器-寄存器（不碰内存）→ 返回 -1
    rm==4  → SIB 编码（不支持）       → 返回 -1
    mod==0 && rm==5 → RIP-relative      → 返回 -1
    else → base = rm | (REX.B << 3)
```

### 4.5 写内存的并发保护

```cpp
// cam_patch_write  camera_intercept.h:135
1. cam_suspend_others()              // SuspendThread 本进程所有其他线程
2. VirtualProtect(PAGE_EXECUTE_READWRITE)
3. cam_seh_memcpy(addr, data, n)     // __try/__except 保护
4. VirtualProtect(old_prot)
5. FlushInstructionCache
6. cam_resume_others()
7. （resume 之后才 log，防止 DBWIN mutex 死锁）
```

**不是** CAS / 不是 thread-safe 写：x64 多字节指令不是原子的，游戏线程可能正在执行我们要改的那条指令 → 必须 suspend 所有其他线程再改。suspend/resume 之间任何日志调用都不能做，否则 CSRSS 互斥量死锁整个进程。

### 4.6 TCP 命令集

```
__cam_intercept_install_addr <hex_addr> <size> [name]
__cam_intercept_install_aob <size> <occurrence> <name> | <AOB hex>
__cam_intercept_pass                         — 全部切回原字节
__cam_intercept_nop                          — 全部切 NOP
__cam_intercept_capture                      — 全部切 capture stub
__cam_intercept_list
__cam_intercept_uninstall                    — 还原并释放 stub 页
__cam_intercept_get_capture <slot>           — 读 g_cap_addr[slot]，拿到相机基址
```

---

## 5. AOB Pattern 怎么用

### 5.1 两层 AOB

| 层级 | 位置 | 作用 |
|---|---|---|
| **引擎级 AOB** | `pattern_scan.h` + `ue5_engine.h` 的 string-xref 算法 | 定位 `GEngine`、`GLog`、间接定位 `Exec` |
| **游戏级 AOB** | `configs/hacks/<game>.json` 的 `intercepts[]` | 定位特定游戏每帧写相机的 `mov` 指令块，装 inline hook |

### 5.2 Pattern 文本格式

```
"89 83 ?? 05 00 00 8B 47 04 89 83 ?? 05 00 00 ..."
```

- 两位 hex = 精确字节
- `??` = 通配符（1 字节）
- 空格/逗号随意，解析器 skip
- 解析入口：`cam_parse_aob` (`camera_intercept.h:176`)

解析结果放两个数组：`uint8_t bytes[128]` + `char mask[128]`，`mask[i]` 是 `'x'` 或 `'?'`。然后交给：

```cpp
pattern_scan(base, size, bytes, mask, pat_len)   // pattern_scan.h:51
```

这是个朴素的逐字节 O(N*M) 扫描；主模块一般 ~300 MB，pat_len ~50 B，冷启动 ~200 ms，够用没上 Boyer-Moore。

### 5.3 Per-game 配置示例（Batman: Arkham Knight）

```jsonc
// configs/hacks/batman_ak.json
{
  "id": "batman_ak",
  "engine": "UE3",
  "process_names": ["BatmanAK.exe"],
  "intercepts": [{
    "name": "camera_write",
    "size": 60,
    // 7 个 'mov [rbx+0x57X], eax'，把 Location+Rotation+FOV 打包写进去
    "aob_literal":  "89 83 74 05 00 00 8B 47 04 89 83 78 05 ...",
    "aob_wildcard": "89 83 ?? 05 00 00 8B 47 04 89 83 ?? 05 ...",
    "prefer": "literal",
    "default_mode": "pass"
  }],
  "camera_write_profile": {
    "struct_base_reg": "rbx",
    "capture_from_intercept": "camera_write",
    "location": { "x": "0x574", "y": "0x578", "z": "0x57C", "type": "float32" },
    "rotation": { "pitch": "0x580", "yaw": "0x584", "roll": "0x588",
                  "type": "ue3_packed_int" },  // UE3 rotator: 16.16 fp, 0x10000 = 360 deg
    "fov": { "off": "0x58C", "type": "float32" }
  }
}
```

读取 + 下发流程（`drivers/game_profile.py`）：

```
load_profile("batman_ak")
  └── Profile.from_json
apply_profile(profile)
  └── for each intercept:
        socket.send("__cam_intercept_install_aob 60 1 camera_write | 89 83 74 05 ...")
        socket.send("__cam_intercept_nop")     # 让游戏停止写
  # 之后外部驱动（cheat_engine / external_memory）用 camera_write_profile
  # 里的偏移量，直接 WriteProcessMemory 到 rbx + 0x574 就能改相机
```

### 5.4 Pattern 是哪来的 —— uuuaobcapture

`uuuaobcapture/` 是一条独立的离线流水线，把 UUU (Universal UE Unlocker) 的 DLL 在 Ghidra 里拆开，把每个 AOB 字面量关联到具体游戏：

```
Ghidra (加载 UUU DLL)
   ↓  GhidraMCP HTTP server (127.0.0.1:8080)
extract_aob_patterns_*.py
   ├── /strings          — 列出所有 "AOB_*" 字符串
   ├── /xrefs_to         — 找引用它们的 registrar 函数
   ├── /decompile        — 拿反编译文本
   └── 花括号+goto 作用域解析器
        ── 跟踪 strcmp(s, "Hogwarts-Win64-Shipping") 决定的上下文
        ── 把当前作用域里出现的 pattern+AOB_NAME 挂到该游戏名下
   ↓
aob_patterns_by_game.json    # 26 游戏, 397 pattern
```

这个流水线不在 runtime 跑；它是离线生成 `configs/hacks/*.json` 所需 AOB 的**原料**，产出的是 JSON 里填的那些 `"89 83 ?? 05 00 00 ..."`。

---

## 6. RenderDoc 数据面（方式 B）

代码：`grabbers/renderdoc_grabber.py`、`renderdoc_ext/capture_bridge.cpp`

跟 hook 无关但讲完整性：

1. `renderdoccmd.exe inject --PID <game> --capture-file <template>` — RenderDoc 官方 loader 把 `renderdoc.dll` 注入游戏。
2. 注入时 `console_server.h` 的 `DllMain` 被拉起，与 (A) 共享**同一套** `pattern_scan / ue5_engine / camera_intercept` 头文件，也监听 TCP 9998。于是 bridge 能力不需要再单独走一次 LoadLibrary。
3. RenderDoc 的 IPC 让 Python 触发 capture → 落盘 `.rdc`。
4. `capture_bridge.cpp`（通过 pybind 暴露）加载 `.rdc` replay，用启发式分离 UI / scene：
   - `classify_ui_events(tail_fraction=0.2, extra_keywords=[...])` — 尾部 N% 的 draw / 特定关键字 / orthographic 投影 → 标成 UI
   - `extract_frame(target_event, excluded_events)` — 重放到指定 event，跳过 UI → 干净 RGB
   - `extract_depth` — 读深度纹理，自动判 reverseZ/linearZ/D24/D16
5. 结果写 `output/<session>/frame_XXXX.png / .exr / normal.npy`。

---

## 7. 串起来：Batman Arkham Knight 从启动到落盘

```
main.py
  create_driver(args)
    → UE5ConsoleDriver(host=127.0.0.1, port=9998)

  create_grabber(args)
    → RenderDocGrabber(target_exe="BatmanAK.exe", ...)

  grabber.setup()
    └── 清理旧 .rdc, mkdir capture_dir

  # ─────────── 游戏启动 + 注入 ───────────
  renderdoccmd capture --capture-file <tpl> BatmanAK.exe
    ↓
  BatmanAK.exe 被 renderdoc.dll 注入
    ↓
  console_server.h DllMain → 启 9998 TCP server
                          → find_gengine() 扫 L"ToggleDebugCamera"
                          → (UE3 游戏扫不到 GEngine，继续往下)

  # ─────────── hook 安装 ───────────
  Python: game_profile.apply_profile("batman_ak")
    → TCP 9998: "__cam_intercept_install_aob 60 1 camera_write | 89 83 74 05 ..."
    → bridge: scan_main_module_nth → 地址 A
             cam_parse_base_reg → rbx (3)
             保存原 60 字节到 site.orig
             mode = PASS
    → TCP 9998: "__cam_intercept_nop"
    → bridge: cam_suspend_others()
             memcpy(A, 60个0x90)
             cam_resume_others()
    → 从此 Batman 每帧写相机的 7 条 mov 变成 NOP，相机"冻住"

  # ─────────── 相机驱动 ───────────
  driver.connect()  → socket 9998
  for pose in snake_path:
    driver.set_pose(pose)
      → 外部 WriteProcessMemory 到 [rbx + 0x574 .. 0x58C]
        (rbx 从 __cam_intercept_get_capture slot 拿到)
      → 相机立刻生效，因为游戏自己的写已经被 NOP

    grabber.capture()
      → RenderDoc IPC: "capture next frame"
      → 落 frame_NNNN.rdc
      → capture_bridge.replay(rdc) → UI 过滤 → RGB + Depth + Normal
      → PNG / EXR / NPY 写到 output/
```

---

## 8. 关键函数一览（按层）

| 层 | 文件 | 函数 | 作用 |
|---|---|---|---|
| 注入 | `3rdparty/bridge/injector.py:120` | `inject_dll` | CreateRemoteThread + LoadLibraryW |
| 注入 | `3rdparty/bridge/injector.py:266` | `wait_and_inject` | 轮询进程名出现后再注入 |
| DLL 启动 | `3rdparty/bridge/src/bridge.cpp:637` | `startup` | find_gengine + 起 TCP + 起 tick |
| DLL 启动 | `3rdparty/bridge/src/bridge.cpp:707` | `DllMain` | 裸启一个线程跑 startup，避开 loader lock |
| 模式扫描 | `3rdparty/bridge/src/pattern_scan.h:51` | `pattern_scan` | mask 字节扫描 |
| 模式扫描 | `3rdparty/bridge/src/pattern_scan.h:126` | `resolve_rip_relative` | `rip = instr + len + disp32` |
| 模式扫描 | `3rdparty/bridge/src/pattern_scan.h:143` | `find_xrefs` | 扫所有 RIP-relative LEA/MOV 指令 |
| GEngine | `3rdparty/bridge/src/ue5_engine.h:184` | `find_gengine_via_string_xref` | 主算法：宽字符串 xref |
| GEngine | `3rdparty/bridge/src/ue5_engine.h:344` | `find_gengine` | 优先级链（env → xref） |
| Exec | `3rdparty/bridge/src/ue5_engine.h:414` | `exec_console_command` | vtable[110..130] 探针 + SEH |
| Exec | `3rdparty/bridge/src/ue5_engine.h:135-156` | `seh_*` helpers | __try/__except 包住任何裸解引用 |
| TCP 路由 | `3rdparty/bridge/src/bridge.cpp:268` | `route_command` | `__bridge_*` / `__cam_*` / `__path_*` 分发 |
| Inline hook | `renderdoc/renderdoc/core/bridge/camera_intercept.h:176` | `cam_parse_aob` | 把 "89 83 ?? ..." 解析成 bytes+mask |
| Inline hook | `camera_intercept.h:222` | `cam_parse_base_reg` | 从 ModRM 字节读基址寄存器 |
| Inline hook | `camera_intercept.h:269` | `cam_build_capture_stub` | 动态拼 29 字节 asm stub |
| Inline hook | `camera_intercept.h:135` | `cam_patch_write` | suspend threads → VirtualProtect → memcpy |
| Inline hook | `camera_intercept.h:405` | `cam_intercept_install_aob` | scan + 装 site |
| Inline hook | `camera_intercept.h:480` | `cam_set_mode_one` | PASS / NOP / CAPTURE 切换 |
| 游戏档案 | `drivers/game_profile.py:40-65` | `Intercept`, `Profile` | JSON schema 数据类 |
| 相机驱动 | `drivers/ue5_console.py:90` | `UE5ConsoleDriver.connect` | 9998 → 1985 fallback |
| 外部内存 | `drivers/external_memory.py:101` | `ExternalMemoryDriver.connect` | 不注入，只 RPM/WPM |
| 抓帧 | `grabbers/renderdoc_grabber.py:93` | `RenderDocGrabber.setup` | 起 renderdoccmd / 等端口 |
| 抓帧 | `renderdoc_ext/capture_bridge.h:143-161` | `ReplaySession::extract_*` | UI 过滤后抽 RGB/Depth |

---

## 9. 易踩坑提醒

1. **Pattern size 必须 >= 14**。否则 `CAPTURE` 模式的 14 字节 `jmp [rip+0]` 塞不下，只能 PASS/NOP。Batman 的 60 字节裕度很大。
2. **NOP 模式前要先确认游戏不在那段代码里**。`cam_patch_write` 已经 suspend 了所有别的线程，但要记住别在 suspend 区间打 log，会死锁。
3. **UE3 扫不到 `L"ToggleDebugCamera"`**。老游戏 fallback 只能靠 `camera_intercept` + per-game AOB，不能走 `Exec()`。
4. **`__cam_intercept_get_capture` 返回 0** 表示 stub 还没被触发过；要先让游戏跑几帧（不能上来就 NOP）。流程应该是 install → CAPTURE → 读 slot → NOP → 外部写。
5. **ExternalMemoryDriver 不能发 console 命令**。只有读写相机字段，没法 `ShowHUD 0`、没法 `r.SetRes`。Anti-cheat 场景下这是唯一选项。
6. **AOB 一定要在游戏加载完之后再扫**。太早 `.text` 里有 loader 写的 thunk，模块还没完全映射好。bridge 在 DLL 启动线程里直接扫是 OK 的，因为 DllMain 返回时主模块已经完整。
7. **Ghidra 提取的 wildcard 版 pattern 不要太激进**。把偏移量都挖 `??` 会匹配到别的 struct 写；保持 `prefer: "literal"`，wildcard 只作同版本小 patch 的兜底。

---

## 10. 想改/加东西时的切入点

| 诉求 | 改哪里 |
|---|---|
| 加新 UE 游戏的 Exec 路径 | `configs/hacks/<id>.json` 新建档案；如果 UE5 够新，通常不需要 intercept，`UE5ConsoleDriver` 直通 |
| 加 UE3/UE4 老游戏 | 用 uuuaobcapture 挖 AOB → 写 `configs/hacks/<id>.json` + `camera_write_profile` 偏移量 |
| 加新引擎（Unity/Bethesda） | 加新 driver (`drivers/<engine>.py`) + 对应的 companion DLL / mod |
| 支持新 anti-cheat | 优先 `ExternalMemoryDriver` 路径；AOB 不变，只是去掉注入 |
| RGB/Depth/Normal 抽取不准 | `renderdoc_ext/capture_bridge.cpp` 的 `classify_ui_events` / `detect_depth_format` |
| 相机平滑/路径插值 | `3rdparty/bridge/src/camera_path.h`（Catmull-Rom + SLERP）、`bridge.cpp:108` 的 `apply_smoothing`（EMA） |

---

文档版本：v0.2.0 对齐。若 bridge / intercept 头加新命令或换 pattern 算法，记得同步更新本文件和 `configs/hacks/_schema.md`。
