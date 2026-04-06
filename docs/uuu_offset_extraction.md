# UUU Offset Extraction -- 从 UUU 提取 GEngine 偏移的方法

## 背景

UUU 用 AOB 扫描定位 GEngine，我们可以"搭便车"：让 UUU 先找到地址，然后我们提取出来用。

---

## 方法 1: x64dbg 断点拦截 (最精确)

### 原理
UUU 的 DLL 注入后，会调用 Windows API 来读写游戏内存。在关键 API 上下断点，就能看到它访问了哪些地址。

### 步骤
1. 启动游戏，等主菜单加载完
2. 用 x64dbg 附加到游戏进程
3. 在以下 API 上设条件断点:
   ```
   bp WriteProcessMemory
   bp VirtualProtect
   bp VirtualProtectEx
   ```
4. 启动 UUU，让它注入
5. 断点触发时，查看参数:
   - 第2个参数 = 目标地址 (lpBaseAddress)
   - 第4个参数 = 写入的数据
6. UUU 找到 GEngine 后会 hook 相机更新函数，写入的地址就是相机结构体
7. 记录: `目标地址 - 模块基址 = 偏移`

### 输出
```
GEngine offset:         exe_base + 0x04A8B230
CameraManager offset:   GEngine + 0x0C48 -> 0x0038 -> 0x02A8
ViewTarget.Location:    CameraManager + 0x0440
ViewTarget.Rotation:    CameraManager + 0x044C
FOV:                    CameraManager + 0x0458
```

---

## 方法 2: 我们自己的 Sniffer DLL (自动化)

### 原理
写一个小 DLL，在 UUU 注入后也注入到游戏，扫描 UUU 的 DLL 内存找到它存储的全局变量。

### 实现思路
```cpp
// 1. 找到 UUU 的 DLL 模块
HMODULE uuu = GetModuleHandle(L"UniversalUE4Unlocker.dll");
if (!uuu) return; // UUU 还没注入

// 2. 扫描 UUU 的 .data section 找指针
// UUU 把 GEngine 地址存在全局变量里
// 特征: 指向游戏 .exe 范围内的地址，且解引用后是有效的 UObject vtable
MODULEINFO exe_info;
GetModuleInformation(GetCurrentProcess(), GetModuleHandle(NULL), &exe_info, sizeof(exe_info));

uintptr_t uuu_base = (uintptr_t)uuu;
IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(uuu_base + ((IMAGE_DOS_HEADER*)uuu)->e_lfanew);
IMAGE_SECTION_HEADER* section = IMAGE_FIRST_SECTION(nt);

for (int i = 0; i < nt->FileHeader.NumberOfSections; i++) {
    if (strcmp((char*)section[i].Name, ".data") == 0) {
        uintptr_t start = uuu_base + section[i].VirtualAddress;
        uintptr_t end = start + section[i].Misc.VirtualSize;
        
        // 扫描每个 8 字节对齐的值
        for (uintptr_t addr = start; addr < end - 8; addr += 8) {
            uintptr_t val = *(uintptr_t*)addr;
            // 检查是否指向游戏 exe 范围内
            if (val >= (uintptr_t)exe_info.lpBaseOfDll && 
                val < (uintptr_t)exe_info.lpBaseOfDll + exe_info.SizeOfImage) {
                // 可能是 GEngine 指针
                printf("Candidate GEngine: 0x%llX (offset: +0x%llX)\n", 
                       val, val - (uintptr_t)exe_info.lpBaseOfDll);
            }
        }
    }
}
```

### 自动化流程
```
1. 启动游戏
2. 等 UUU 注入 + 找到 GEngine (看 UUU 控制台显示 "Camera enabled")
3. 注入我们的 sniffer DLL
4. Sniffer 扫描 UUU 的全局变量，提取 GEngine 指针
5. 计算 offset = GEngine - exe_base
6. 写入 configs/games/<game>.json
7. 下次直接用 offset，不需要 UUU
```

---

## 方法 3: 逆向 UUU 的 AOB Patterns (一劳永逸)

### 原理
UUU 的 DLL 里硬编码了 AOB pattern。反编译 DLL 就能提取出来。

### 工具
- **IDA Pro** 或 **Ghidra** (免费) 打开 `UniversalUE4Unlocker.dll`
- 搜索 `FindPattern` / `SigScan` / `PatternScan` 函数
- 提取所有 AOB byte pattern

### 示例
```
// 在 IDA 里看到的伪代码可能长这样:
pattern_gengine = "48 8B 05 ?? ?? ?? ?? 48 8B 88 ?? ?? ?? ?? 48 85 C9 74"
result = FindPattern(exe_base, exe_size, pattern_gengine);
GEngine = result + 3 + *(int*)(result + 3); // RIP-relative addressing
```

### 输出
把这些 pattern 直接加到我们的 bridge scanner:
```cpp
// ue5_engine.h - add UUU's patterns as fallback
const char* uuu_patterns[] = {
    "48 8B 05 ?? ?? ?? ?? 48 8B 88 ?? ?? ?? ?? 48 85 C9 74",  // GEngine (UE5.1-5.4)
    "48 89 05 ?? ?? ?? ?? 48 8B ?? 48 85 C9 74 ?? 48 8B 49",  // GEngine (UE4.25-4.27)
    // ... more patterns
};
```

### 法律风险
- UUU 是闭源商业软件 (Patreon $6.50/月)
- 反编译提取 pattern **可能侵犯版权**
- 但 AOB pattern 本质是描述公开的 UE 引擎代码特征，不是 UUU 的创意作品
- **建议**: 参考开源的 UEVR/UE4SS 的 pattern，不要直接从 UUU 提取

---

## 方法 4: 运行时 Hook (最优雅)

### 原理
不碰 UUU 的代码，而是 hook 游戏自己的函数。UUU 找到 GEngine 后会调用
`GEngine->Exec()` 来执行命令。我们 hook `Exec` 函数，就能拿到 GEngine 指针。

### 实现
```cpp
// Hook UE 的 ProcessEvent 或 Exec
// 当 UUU 调用 ToggleDebugCamera 时，我们拦截到 GEngine
typedef void (*ExecFn)(void* GEngine, void* world, const wchar_t* cmd, void* output);
ExecFn original_exec = nullptr;

void hooked_exec(void* GEngine, void* world, const wchar_t* cmd, void* output) {
    // 记录 GEngine 地址
    static bool captured = false;
    if (!captured) {
        uintptr_t exe_base = (uintptr_t)GetModuleHandle(NULL);
        printf("GEngine captured: 0x%p (offset: +0x%llX)\n", 
               GEngine, (uintptr_t)GEngine - exe_base);
        captured = true;
        // 保存到文件
        save_offset_to_json(GEngine, exe_base);
    }
    original_exec(GEngine, world, cmd, output);
}
```

---

## 推荐方案

| 方法 | 难度 | 自动化 | 法律风险 | 推荐度 |
|------|------|--------|---------|--------|
| x64dbg 手动 | 低 | 不能 | 无 | 学习用 |
| Sniffer DLL | 中 | 半自动 | 无 | **推荐** |
| 逆向 AOB | 高 | 一次性 | 有 | 不推荐 |
| 运行时 Hook | 中 | 全自动 | 无 | **最佳** |

**最佳路径**: 方法 4 (运行时 Hook) — 不依赖 UUU，不碰 UUU 代码，一旦 GEngine
被任何工具（UUU/我们自己/CE）定位到，我们都能自动捕获并缓存。

实际上**我们的 bridge DLL 已经在做类似的事**（字符串 xref 扫描）。
真正的价值是: 用 UUU 作为**验证工具** -- 如果 UUU 能在某游戏上工作，
说明该游戏的 GEngine 结构是标准的，我们的 scanner 也应该能找到。
如果我们找不到而 UUU 找到了，就用 x64dbg 比较两者的差异来改进我们的 scanner。
