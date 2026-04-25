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

代码：`3rdparty/bridge/injector.py`（`inject_dll:120`、`inject_by_name:243`、`wait_and_inject:266`）

### 2.1 七步流程（对照源码）

```python
# inject_dll(pid, dll_path)  ─ injector.py:120
1. h_process = OpenProcess(PROCESS_ALL_INJECT, False, pid)         # :148
2. dll_bytes = (dll_abs + "\0").encode("utf-16-le")                 # :158
3. remote_mem = VirtualAllocEx(h_process, None, len, MEM_COMMIT, PAGE_READWRITE)  # :162
4. WriteProcessMemory(h_process, remote_mem, dll_bytes, len, &n)   # :172
5. load_library_addr = GetProcAddress(kernel32, "LoadLibraryW")    # :186
6. h_thread = CreateRemoteThread(h_process, NULL, 1MB,
                                  start=LoadLibraryW, arg=remote_mem)  # :194
7. WaitForSingleObject(h_thread, 10s) + GetExitCodeThread          # :213/222
   → VirtualFreeEx + CloseHandle (finally 块兜底)                    # :237/240
```

`PROCESS_ALL_INJECT` 的位组合（`injector.py:39-46`）：

| 标志 | 值 | 用途 |
|---|---|---|
| `PROCESS_CREATE_THREAD` | `0x0002` | `CreateRemoteThread` |
| `PROCESS_VM_OPERATION`  | `0x0008` | `VirtualAllocEx` / `VirtualFreeEx` |
| `PROCESS_VM_WRITE`      | `0x0020` | `WriteProcessMemory` |
| `PROCESS_VM_READ`       | `0x0010` | 后续读验证 / psapi |
| `PROCESS_QUERY_INFORMATION` | `0x0400` | 查询进程名、模块 |
| `SYNCHRONIZE`           | `0x00100000` | `WaitForSingleObject` |

少任何一位就会在对应步骤 `GetLastError=5 (ACCESS_DENIED)`；最常见是**没管理员权限 / 目标是 Protected Process (anti-cheat)**。

### 2.2 为什么可以"本地拿到 LoadLibraryW 地址给远端用"

x64 Windows 下 `kernel32.dll` 在**所有进程的同一个 session 内加载到相同基址**（ASLR 是 per-session，不是 per-process）。因此注入器进程里 `GetProcAddress(kernel32, "LoadLibraryW")` 返回的地址，在目标进程里指向**同一个函数**。这是整个经典注入技法的地基：

- 不需要在远端进程里解 PE 做重定位
- 不需要 DbgHelp / 符号
- `CreateRemoteThread(start, arg)` 的线程入口点签名 `DWORD WINAPI (LPVOID)` 刚好和 `HMODULE LoadLibraryW(LPCWSTR)` **ABI 兼容**（都是 1 参数、返回值都在 `rax`）

### 2.3 ExitCode → HMODULE 的坑

```python
# injector.py:221
GetExitCodeThread(h_thread, &exit_code)  # exit_code 是 DWORD (32-bit)
if exit_code.value == 0:  # 被 AC 拦 / 架构不对 / 依赖 DLL 缺失
    raise InjectionError(...)
```

`GetExitCodeThread` 返回 32-bit `DWORD`，但真正的 `HMODULE` 是 **64-bit 指针**。如果 DLL 被 load 到地址 > 4GB 的位置，`exit_code` 会被截到低 32 位。幸运的是：非 0 = 成功这一**语义**并不受截断影响（低 32 位是 0 的概率 ≈ 1/2³²）。真正要用 `HMODULE` 的话必须用 `NtQueryInformationThread(ThreadBasicInformation)` 或者改用 `CreateRemoteThreadEx`。captureAIshi 只需要 0/非 0，所以够用。

### 2.4 为什么单开一个 startup 线程

`DllMain` 里持有 **loader lock**（一个进程级 critical section，保证 DLL 初始化串行）。在里面做这些事都会死锁：

- `LoadLibrary` / `FreeLibrary` 嵌套
- `WSAStartup`（内部加载 mswsock.dll）
- `std::thread` 构造里如果用 ucrt 的延迟初始化
- 任何 COM / RPC 调用

所以 DLL 入口只做最小动作：

```cpp
// bridge.cpp:707
BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID reserved) {
    switch (reason) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hModule);        // 后续 DLL_THREAD_ATTACH 不再回调
        std::thread(startup).detach();             // 立刻返回，loader lock 释放
        break;
    case DLL_PROCESS_DETACH:
        shutdown();                                 // 只在游戏正常退出时跑
        break;
    }
    return TRUE;
}
```

`startup()`（`bridge.cpp:637`）在新线程里做 "真正的初始化"：打开 log 文件 → `find_gengine()` → `camera_tick_thread` → `tcp_server_thread`。此时 loader lock 已释放，任何 API 都能用。

### 2.5 `wait_and_inject` 的用法

```python
# injector.py:266
wait_and_inject("BatmanAK.exe", dll_path, timeout=60.0, poll_interval=1.0)
```

- 轮询 `_find_process_by_name`（内部 `EnumProcesses + GetModuleBaseNameW`）
- 发现进程后 `time.sleep(0.5)` 让它把主模块 map 完，再注入（否则 `GetModuleHandle(NULL)` 的 size 会偏小，AOB 扫不全）
- 这 0.5s 是这套代码里**唯一**一个违反 `no-sleep.md` 的地方；正确做法是轮询 main module 的 `SizeOfImage` 稳定后再注入。现在没触发过问题，所以先留着。

### 2.6 失败对照表

| 症状 | `GetLastError` | 最可能原因 |
|---|---|---|
| `OpenProcess` 返回 0 | `5 (ACCESS_DENIED)` | 无管理员 / Protected Process Light (anti-cheat) |
| `OpenProcess` 返回 0 | `87 (INVALID_PARAMETER)` | PID 已退出 |
| `VirtualAllocEx` = NULL | `8 (NOT_ENOUGH_MEMORY)` | 目标进程地址空间受限 (32-bit 游戏) |
| `CreateRemoteThread` = NULL | `5` 或 `8` | EAC/BE 的 `ObjectPreCallback` 拦 `THREAD_CREATE` |
| `WaitForSingleObject` = `WAIT_TIMEOUT` | — | `DllMain` 死锁了（见 2.4） |
| `ExitCode == 0` | — | 架构不对 / 依赖 DLL 不在 `PATH` / `DllMain` 里 `return FALSE` |

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

#### 3.2.1 一条指令怎么解出来 —— REX / ModRM 字节级解读

`48 8B 05 XX XX XX XX` 这 7 字节，每一位都讲得清：

```
 48        8B        05        XX XX XX XX
 |         |         |         |
 REX.W     opcode    ModRM     disp32 (小端, 有符号 32-bit)
 │         │         │
 │         │         └─ mod=00  reg=000(rax)  rm=101
 │         │            mod=00 + rm=101 的特殊编码 = [rip + disp32]
 │         │            (x64 独有；x86 下 mod=00/rm=101 是 [disp32] 绝对地址)
 │         └─ MOV r64, r/m64  (方向：把内存 → 寄存器)
 │
 └─ REX prefix, 二进制 0100 WRXB
    W=1 操作数是 64-bit
    R=0 reg 扩展位 (给 reg 字段 +8)
    X=0 SIB index 扩展位
    B=0 rm 扩展位   (给 rm 字段 +8)
```

所以 `find_xrefs` 里的魔数 `(b2 & 0xC7) == 0x05` 是在说："ModRM 的 mod=00 且 rm=101，忽略中间的 reg 字段（哪个目标寄存器无所谓）"。`0xC7 = 11000111` 只保留 mod+rm 两组比特。

把 `disp32` 加回去得绝对地址：

```cpp
// pattern_scan.h:126
resolved = instr_addr + instr_len + (int32_t)disp32
//                     │            │
//                     │            └─ 7 bytes 后是下一条指令 (rip)
//                     └─ rip-relative 基准点就是 "下一条指令的地址"
```

#### 3.2.2 `find_xrefs` 的匹配范围

```cpp
// pattern_scan.h:143
if ((b0 == 0x48 || b0 == 0x4C) && (b1 == 0x8B || b1 == 0x8D)) {
    if ((b2 & 0xC7) == 0x05) { ... }
}
```

覆盖这 4 种组合：

| REX | opcode | 语义 |
|---|---|---|
| `48` | `8B` | `MOV r64, [rip+disp]` （**加载全局变量**） |
| `48` | `8D` | `LEA r64, [rip+disp]` （**取地址**，例如指向字符串） |
| `4C` | `8B` | 同上，目标寄存器是 `r8..r15` |
| `4C` | `8D` | 同上 |

不覆盖 `48 89 05 ?? ...`（`MOV [rip+disp], r64`，写全局）——因为找字符串 xref 只关心**读**，不关心写。find_xrefs 的结果是"所有加载这个地址的指令"，对字符串来说就是"用了这个字符串的代码点"。

#### 3.2.3 为什么要 SEH 保护每一次解引用

游戏主模块声明的 `.text` / `.rdata` 大小 (`SizeOfImage`) 是**映射时的理论值**；实际页面可能：

- 被 DRM (Denuvo) 在运行期**解密后再重新加密**，窗口期内该页读出来是垃圾
- 被 AC 的用户态 hook 标成 `PAGE_NOACCESS` 作为反调试陷阱
- 反射型模块加载后留下的"幽灵"段，映射标志位对但内容是 0

```cpp
// ue5_engine.h:264
if (!seh_probe_readable((const void*)resolved)) continue;   // 解指针值
...
if (!seh_read_u64((uintptr_t)candidate, &vtable)) continue; // 解 vtable
```

两次 SEH 意味着**允许扫描过程中撞到任何坏页面**，`__except(EXCEPTION_EXECUTE_HANDLER)` 静默跳过继续下一个候选。注意 MSVC 的 C2712：**含 C++ 对象（有析构函数）的函数不能直接用 `__try`**，所以 `seh_*` 三兄弟都被 `__declspec(noinline)` + 独立函数签名包裹，给调用方一个干净的布尔返回。

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

`cam_build_capture_stub` (`camera_intercept.h:269`) 逐字节产出：

```
  偏移  字节                            反汇编                       含义
  ----  ------------------------------  ---------------------------  -----------------------
  0x00  50                              push rax                     保存 rax (我们要借用)
  0x01  48 89 C0                        mov rax, rax                 base_reg=0 时占位
        48 89 C3                        mov rax, rbx                 base_reg=3 (rbx)
        48 89 C7                        mov rax, rdi                 base_reg=7 (rdi)
        4C 89 C0                        mov rax, r8                  base_reg=8 (REX.R=1)
        4C 89 C7                        mov rax, r15                 base_reg=15
  0x04  48 A3 <8 bytes>                 mov [abs64], rax             写到 g_cap_addr[slot]
  0x0E  58                              pop rax                      还原
  0x0F  FF 25 00 00 00 00               jmp qword ptr [rip+0]        跳回
  0x15  <8 bytes>                       (dq continue_addr)           原 block 之后的地址
  0x1D  (结束, 总 29 字节)
```

几个关键点：

1. **`push rax / pop rax` 必须成对**。我们借用 `rax` 做中转，如果不保存/还原，游戏线程返回后会用错 `rax` 立刻崩。整条 stub 只污染 rflags 里的结果标志（`mov` 不改 flags），对 UE 的相机更新代码无影响。
2. **编码表 `base_reg → REX / ModRM`**：
   ```
   REX  = (base_reg >= 8) ? 0x4C : 0x48        // REX.W=1 总是要；REX.R 给源寄存器加 8
   opcd = 0x89                                 // MOV r/m64, r64  (direction=0, reg field 是源)
   ModRM = 0xC0 | ((base_reg & 7) << 3)        // mod=11 寄存器到寄存器, reg=base_reg, rm=000(rax)
   ```
   举例 `base_reg=3 (rbx)`：`REX=0x48`, `ModRM=0xC0 | (3<<3) = 0xD8`。组合字节 `48 89 D8` = `mov rax, rbx`。
3. **为什么用 64-bit 绝对寻址 `48 A3`**：`g_cap_addr` 在 DLL 的 `.bss` 里，stub 在 `VirtualAlloc` 出来的独立页里，两者距离可能超过 2GB。RIP-relative (`48 89 05 disp32`) 放不下，只能走 `MOV moffs64` (opcode `A3`)——它是 x64 里**极少数**直接带 64-bit 绝对地址的指令之一。
4. **为什么现场 patch 用 14 字节 `FF 25 00 00 00 00 <qword>` 而不是 `E9 <disp32>`**：`E9` 是 rip-relative ±2GB 跳转；stub 的 `VirtualAlloc` 不保证落在游戏模块附近 2GB 内。`FF 25` + 绝对 64-bit 目标是唯一保险的"短跳远"编码。
5. **4KB 整页 + 0xCC 填充**：`cam_alloc_stub_page` 一次分配 4096 字节，即使 stub 只占 29 字节也不省。填 `0xCC` (INT3) 的意义：如果某条游戏线程被 suspend 时 rip 正好在 patch 区间中部、resume 后误跳进 stub 页的尾巴，会立刻 `EXCEPTION_BREAKPOINT` 而不是跑一串垃圾指令污染全局状态。

现场 patch 是 14 字节的 `jmp qword ptr [rip+0]; dq stub`（`cam_build_capture_patch`, `camera_intercept.h:318`），剩余字节补 `0x90`。因此 **AOB 匹配的 `size` 必须 >= 14**，否则 capture 模式装不上（`cam_ensure_stub` 会直接失败，见 `camera_intercept.h:450`）。

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

- 两位 hex = 精确字节（`0-9 a-f A-F` 都接受）
- `??` = 通配符（**恰好 1 字节**，不是 1 个 nibble）
- 空格 / 制表符 / 逗号随意，解析器 skip
- 单个 `?` 无效；必须是两个
- 单 nibble (`"8"` 而不是 `"08"`) 返回 -1 解析失败

解析入口：`cam_parse_aob` (`camera_intercept.h:176`)，产出两个并行数组：

```cpp
uint8_t bytes[128];   // 精确字节值；通配位置填 0x00 (忽略)
char    mask[129];    // 每位 'x' 或 '?'；以 '\0' 结尾便于 log
int     pat_len;      // 实际 token 数，上限 128
```

然后交给 `pattern_scan`:

```cpp
// pattern_scan.h:51  - 朴素 O(N*M) 逐字节扫描
for (size_t i = 0; i <= size - pat_len; i++) {
    bool ok = true;
    for (size_t j = 0; j < pat_len; j++) {
        if (mask[j] == '?') continue;               // 通配跳过
        if (start[i + j] != pattern[j]) { ok=false; break; }
    }
    if (ok) return &start[i];
}
```

主模块一般 ~300 MB，pat_len ~30-60 B，冷启动单次扫描 ~100-300 ms。够用，没上 Boyer-Moore。

### 5.3 `scan_main_module_nth` 和 `occurrence` 参数

同一条 pattern 在模块里可能**多次出现**（例如 Batman 里 7 个 `mov [rbx+0x57X], eax` 中的前 6 个可以被同样的前缀匹配）。`scan_main_module_nth` (`pattern_scan.h:196`) 是在 `pattern_scan` 基础上加了个"跳过前 N-1 次"：

```cpp
while (remaining >= pat_len) {
    const uint8_t* m = pattern_scan(base, remaining, pattern, mask, pat_len);
    if (!m) return nullptr;
    if (++found == occurrence) return m;
    base = m + 1; remaining = rgn.size - (m+1 - rgn.base);
}
```

- `occurrence <= 1`：首次匹配（最常见）
- `occurrence = 2, 3, ...`：第 N 次命中
- 每次往后只推进 1 字节（不是 `pat_len` 字节）——这允许**重叠匹配**，但代价是最坏情况 O(N·M·occ)

TCP 命令里的字段：

```
__cam_intercept_install_aob <size> <occurrence> <name> | <AOB hex>
                                  ▲
                                  └─ 第几次命中；Batman 配置固定写 1
```

### 5.4 `prefer: "literal"` vs `"wildcard"` 的分工

per-game JSON 同一条 intercept 里常常同时写两版：

```json
"aob_literal":  "89 83 74 05 00 00 8B 47 04 89 83 78 05 ...",   // 一个 build
"aob_wildcard": "89 83 ?? 05 00 00 8B 47 04 89 83 ?? 05 ...",   // 跨小版本
"prefer": "literal"
```

`drivers/game_profile.py` 的 `apply_profile` 先按 `prefer` 发一次 `__cam_intercept_install_aob`；如果 bridge 回 `error: install_failed`，再用另一条兜底。目的：

- **literal**：扫得快、不会误匹配相似的 `mov`，但游戏一次微更新（偏移从 `0x574` 改到 `0x580`）就失效
- **wildcard**：跨小版本稳，但如果挖 `??` 太多会命中别的无关 `mov`

所以平时 `literal` 先行，wildcard 只作为当版本 patch 的兜底。

### 5.5 Per-game 配置示例（Batman: Arkham Knight）

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

### 5.6 Pattern 是哪来的 —— uuuaobcapture

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
| 注入 | `3rdparty/bridge/injector.py:63` | `_find_process_by_name` | `EnumProcesses + GetModuleBaseNameW` |
| 注入 | `3rdparty/bridge/injector.py:120` | `inject_dll` | CreateRemoteThread + LoadLibraryW |
| 注入 | `3rdparty/bridge/injector.py:243` | `inject_by_name` | 找进程 + 注入一条龙 |
| 注入 | `3rdparty/bridge/injector.py:266` | `wait_and_inject` | 轮询进程名出现后再注入 |
| DLL 启动 | `3rdparty/bridge/src/bridge.cpp:637` | `startup` | find_gengine + 起 TCP + 起 tick |
| DLL 启动 | `3rdparty/bridge/src/bridge.cpp:707` | `DllMain` | 裸启一个线程跑 startup，避开 loader lock |
| 模式扫描 | `3rdparty/bridge/src/pattern_scan.h:30` | `get_main_module` | `GetModuleHandleA(NULL) + GetModuleInformation` |
| 模式扫描 | `3rdparty/bridge/src/pattern_scan.h:51` | `pattern_scan` | mask 字节扫描 |
| 模式扫描 | `renderdoc/.../pattern_scan.h:196` | `scan_main_module_nth` | 扫第 N 次命中 |
| 模式扫描 | `3rdparty/bridge/src/pattern_scan.h:98` | `find_wstring_in_module` | UTF-16LE 字串搜索 |
| 模式扫描 | `3rdparty/bridge/src/pattern_scan.h:126` | `resolve_rip_relative` | `rip = instr + len + disp32` |
| 模式扫描 | `3rdparty/bridge/src/pattern_scan.h:143` | `find_xrefs` | 扫所有 RIP-relative LEA/MOV 指令 |
| GEngine | `3rdparty/bridge/src/ue5_engine.h:184` | `find_gengine_via_string_xref` | 主算法：宽字符串 xref |
| GEngine | `3rdparty/bridge/src/ue5_engine.h:304` | `find_gengine_via_offset` | 手工偏移 + SEH 验证 |
| GEngine | `3rdparty/bridge/src/ue5_engine.h:344` | `find_gengine` | 优先级链（env → xref） |
| Exec | `3rdparty/bridge/src/ue5_engine.h:384` | `validate_function_ptr` | 函数序言字节合法性检查 |
| Exec | `3rdparty/bridge/src/ue5_engine.h:414` | `exec_console_command` | vtable[110..130] 探针 + SEH |
| Exec | `3rdparty/bridge/src/ue5_engine.h:135-156` | `seh_*` helpers | __try/__except 包住任何裸解引用 |
| TCP 路由 | `3rdparty/bridge/src/bridge.cpp:268` | `route_command` | `__bridge_*` / `__cam_*` / `__path_*` 分发 |
| Inline hook | `renderdoc/.../camera_intercept.h:101` | `cam_suspend_others` | `Toolhelp32Snapshot` 枚举本进程线程并暂停 |
| Inline hook | `renderdoc/.../camera_intercept.h:135` | `cam_patch_write` | suspend threads → VirtualProtect → memcpy |
| Inline hook | `renderdoc/.../camera_intercept.h:176` | `cam_parse_aob` | 把 "89 83 ?? ..." 解析成 bytes+mask |
| Inline hook | `renderdoc/.../camera_intercept.h:222` | `cam_parse_base_reg` | 从 ModRM 字节读基址寄存器 |
| Inline hook | `renderdoc/.../camera_intercept.h:269` | `cam_build_capture_stub` | 动态拼 29 字节 asm stub |
| Inline hook | `renderdoc/.../camera_intercept.h:318` | `cam_build_capture_patch` | 14 字节 `FF 25 / dq stub` 现场 patch |
| Inline hook | `renderdoc/.../camera_intercept.h:405` | `cam_intercept_install_aob` | scan + 装 site |
| Inline hook | `renderdoc/.../camera_intercept.h:442` | `cam_ensure_stub` | 惰性分配 stub 页，切 CAPTURE 时才执行 |
| Inline hook | `renderdoc/.../camera_intercept.h:480` | `cam_set_mode_one` | PASS / NOP / CAPTURE 切换 |
| Inline hook | `renderdoc/.../camera_intercept.h:591` | `cam_mem_poke` / `cam_mem_peek` | SEH 包装的相机字段读写 |
| 游戏档案 | `drivers/game_profile.py:40-65` | `Intercept`, `Profile` | JSON schema 数据类 |
| 相机驱动 | `drivers/ue5_console.py:90` | `UE5ConsoleDriver.connect` | 9998 → 1985 fallback |
| 外部内存 | `drivers/external_memory.py:101` | `ExternalMemoryDriver.connect` | 不注入，只 RPM/WPM |
| 抓帧 | `grabbers/renderdoc_grabber.py:93` | `RenderDocGrabber.setup` | 起 renderdoccmd / 等端口 |
| 抓帧 | `renderdoc_ext/capture_bridge.h:143-161` | `ReplaySession::extract_*` | UI 过滤后抽 RGB/Depth |

### 8.1 关键函数原理小抄（速查）

按"我想干这件事 → 调这个函数 → 背后做了什么"组织，方便对着代码读：

**注入一个 DLL 到运行中的游戏**

```
inject_dll(pid, dll_path)
├─ OpenProcess(PROCESS_ALL_INJECT)      权限位见 §2.1 表格
├─ VirtualAllocEx(PAGE_READWRITE)       在目标地址空间里开一块 RW 页
├─ WriteProcessMemory                   把 UTF-16 的 DLL 路径灌进去
├─ GetProcAddress(kernel32,"LoadLibraryW")   利用 kernel32 基址跨进程一致
└─ CreateRemoteThread(start=LoadLibraryW, arg=remote_mem)
   │                                    目标线程 EIP=LoadLibraryW, RCX=路径
   └─ WaitForSingleObject + GetExitCodeThread   ExitCode!=0 表示 load 成功
```

**在游戏模块里找一个字节 pattern**

```
scan_main_module(pattern, mask, len)     // 最常见情况
├─ GetModuleHandleA(NULL)                 拿主模块句柄（注入 DLL 跑时 = 游戏 exe）
├─ GetModuleInformation -> {base, size}
└─ pattern_scan(base, size, ...)          O(N*M) 扫，'x'=匹配 '?'=忽略

scan_main_module_nth(..., occurrence)    // 需要跳到第 N 次命中
└─ 同上 + 外层循环把 base 推进 1 字节再扫
```

**从一条 `mov [reg+disp], reg` 的 AOB 解出基址寄存器**

```
cam_parse_base_reg(bytes, mask, pat_len)
├─ skip 可选前缀 (F2/F3/66)
├─ 读 REX (0x40..0x4F) 记 REX.B
├─ 匹配 opcode: 89 (mov) / 0F 11 / 0F 29 (movups/movaps)
├─ 读 ModRM:
│   mod==11 → 寄存器-寄存器, 返回 -1
│   rm==100 → SIB 编码, 返回 -1（不支持）
│   mod==00 && rm==101 → RIP-relative, 返回 -1（没基址寄存器）
└─ return rm | (REX.B << 3)   // 得到 0..15
```

**把 X 字节代码原子地换成另 X 字节**

```
cam_patch_write(addr, new_bytes, n)
├─ cam_suspend_others()                   暂停本进程所有其他线程
│   └─ Toolhelp32Snapshot + Thread32First/Next
│      + OpenThread(SUSPEND_RESUME) + SuspendThread
├─ VirtualProtect(PAGE_EXECUTE_READWRITE) 拿写权限
├─ cam_seh_memcpy(addr, new_bytes, n)     __try 包住 memcpy
├─ VirtualProtect(原保护位)               还原
├─ FlushInstructionCache                  强刷 L1i，保证其他 CPU 也见到新字节
└─ cam_resume_others()                    resume + CloseHandle
⚠ suspend/resume 之间禁止 OutputDebugString / bridge_log: CSRSS 锁死锁风险
```

**在 UE5 里执行一条 console 命令**

```
exec_console_command("SetViewLocation 100 200 300")
├─ MultiByteToWideChar (UTF-8 → UTF-16)
├─ vtable = *(uintptr_t**)g_engine_ptr   // 读 GEngine 的 vptr
├─ if g_exec_fn 已缓存: seh_call_exec(g_exec_fn, ...) 直接调
└─ 否则 for idx in 110..130:
      if !validate_function_ptr(vtable[idx]): continue
      if !seh_call_exec(vtable[idx], ..., L"stat none", ...): continue  // 探针
      g_exec_fn = vtable[idx]           // 探针活下来 = 是 Exec
      seh_call_exec(g_exec_fn, ..., 真命令, ...)
```

`stat none` 选作探针因为它无副作用（即使走进了非 Exec 的虚函数，期望的行为是"参数无效被忽略"）；即便这个行为不成立，`seh_call_exec` 也会兜住异常。

**安装一个 IGCS 风格的相机 hook**

```
cam_intercept_install_aob(aob_hex, size, name, occurrence=1)
├─ cam_parse_aob             → bytes[], mask[], pat_len
├─ scan_main_module_nth      → 找到第 N 次命中地址 A
├─ cam_parse_base_reg        → 从 AOB 第一条指令取基址寄存器号
└─ cam_intercept_install_addr(A, size, name)
    ├─ VirtualQuery          → 确认页已 commit 且可读
    ├─ 确认 A+size 不跨页
    ├─ cam_seh_memcpy(orig, A, size)   备份原字节
    ├─ memset(nops, 0x90, size)        准备 NOP 填充
    └─ push_back 到 g_cam_sites, mode=PASS

之后 __cam_intercept_nop  → 对每个 site 调 cam_set_mode_one(NOP)
                          → cam_patch_write(addr, nops, size)
之后 __cam_intercept_capture → cam_ensure_stub() 分配 4KB 页 + 组 29 字节 stub
                              → cam_patch_write(addr, patch, size)  // 14 字节 FF 25 跳走
```

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

文档版本：v0.2.0 对齐（更新 2026-04-24：加深注入 / xref / stub / AOB 细节和关键函数原理小抄）。若 bridge / intercept 头加新命令或换 pattern 算法，记得同步更新本文件和 `configs/hacks/_schema.md`。
