# 逆向破解全过程：从"2 个游戏"到"13 个游戏"的 AOB 提取

> **目标**：从 Ghidra 里打开的 IGCS 相机系统 DLL 中，自动提取所有 AOB（Array-of-Bytes）字节模式并关联到它们对应的游戏。
>
> **最终成果**：`aob_patterns_by_game.json` —— 13 个游戏、49 个 per-game key、215 个候选 pattern；以及一个可重跑的提取脚本 `extract_aob_patterns.py`。

---

## 目录

- [0. 环境与约束](#0-环境与约束)
- [1. 第一阶段：侦察期](#1-第一阶段侦察期)
- [2. 第二阶段：手工反编译定位注册惯用模式](#2-第二阶段手工反编译定位注册惯用模式)
- [3. 第三阶段：v1 自动化提取器（只找到 2 个游戏专属）](#3-第三阶段v1-自动化提取器只找到-2-个游戏专属)
- [4. 第四阶段：复盘 —— 为什么只有 2 个游戏](#4-第四阶段复盘--为什么只有-2-个游戏)
- [5. 第五阶段：从进程名字符串重建游戏列表](#5-第五阶段从进程名字符串重建游戏列表)
- [6. 第六阶段：迭代 v2 / v3 —— 游戏上下文与工厂递归](#6-第六阶段迭代-v2--v3--游戏上下文与工厂递归)
- [7. 第七阶段：深挖隐藏游戏](#7-第七阶段深挖隐藏游戏)
- [8. 第八阶段：v4 —— 花括号作用域 + goto-label 感知的解析器](#8-第八阶段v4--花括号作用域--goto-label-感知的解析器)
- [9. 最终产物与结果](#9-最终产物与结果)
- [10. 全流程的 GUI 纯手工等效版本](#10-全流程的-gui-纯手工等效版本)
- [11. 核心经验与坑点清单](#11-核心经验与坑点清单)

<!-- @import "[TOC]" {cmd="toc" depthFrom=1 depthTo=6 orderedList=false} -->

---

## 0. 环境与约束

- **目标程序**：IGCS（InjectableGenericCameraSystem）相机外挂 DLL（64 位 PE）。二进制里链入了 FreeType、Dear ImGui、nlohmann::json 等依赖。
- **Ghidra 状态**：项目已打开并完成自动分析，`GhidraMCP-release-1-4` 插件在 Ghidra 里把分析能力暴露为 HTTP 服务 `http://127.0.0.1:8080/`。
- **MCP 工具状态**：本会话的 `.claude/settings.json` 配置了 Ghidra MCP server（`bridge_mcp_ghidra.py`），但 bridge 在会话里 **未自动连接**，所以 `mcp__ghidra__*` 工具名没有在本会话里加载。
- **旁路策略**：既然底层 HTTP 服务可达，直接用 `curl` / Python `urllib.request` 调用相同的端点，**语义与 MCP 工具完全等价**。

### MCP 工具 ↔ HTTP 端点对照

| MCP 工具（`mcp__ghidra__*`） | HTTP 端点 | 用途 |
|---|---|---|
| `list_methods` | `GET /methods` | 分页列全部函数名 |
| `list_segments` | `GET /segments` | 内存段 |
| `list_strings` | `GET /strings` | 已定义字符串（**有默认截断，必须分页**） |
| `list_namespaces` | `GET /namespaces` | namespace / demangled 类名 |
| `list_classes` | `GET /classes` | 同上（筛出 class） |
| `search_functions_by_name` | `GET /searchFunctions?query=...` | 按名搜索函数（本项目中函数都是 `FUN_<addr>`，用处不大） |
| `get_xrefs_to` | `GET /xrefs_to?address=...` | 反向交叉引用 |
| `decompile_function_by_address` | `GET /decompile_function?address=...` | 按地址反编译 |
| `decompile_function` | `POST /decompile`（body=函数名） | 按名反编译 |

---

## 1. 第一阶段：侦察期

### 1.1 确认 Ghidra HTTP 服务可达

**目的**：决定后续能不能直接脚本化。

```bash
curl -s -m 3 http://127.0.0.1:8080/methods?limit=3
# -> FUN_1800010c0
#    FUN_1800010e0
#    FUN_180001100
```

**MCP 等效**：`list_methods(limit=3)`

**Ghidra GUI 等效**：
1. 打开 Ghidra → 打开 / 导入目标 DLL → `Analyze` 完成初始分析
2. 安装 `GhidraMCP-1-4.zip` 插件（`File → Install Extensions… → 选 .zip`）
3. 重启并打开 CodeBrowser 工具，在 Script Manager 里启动 `GhidraMCP.java`（或在 Tool 里勾选自动启动）
4. 状态栏确认 `GhidraMCP listening on port 8080`

---

### 1.2 内存段布局

```bash
curl -s http://127.0.0.1:8080/segments?limit=50
```

输出：

```
Headers: 180000000 - 1800003ff
.text:   180001000 - 18021dbff
.rdata:  18021e000 - 1802b41ff
.data:   1802b5000 - 1802c7e3f
.pdata:  1802c8000 - 1802ea3ff
.fptable:1802eb000 - 1802eb1ff
.rsrc:   1802ec000 - 1802ec5ff
.reloc:  1802ed000 - 1802ef9ff
tdb:     ff00000000 - ff0000184f
```

**MCP 等效**：`list_segments(limit=50)`

**Ghidra GUI 等效**：`Window → Memory Map`（或工具栏上的 RAM 芯片图标）。

---

### 1.3 粗读字符串识别二进制身份

```bash
curl -s "http://127.0.0.1:8080/strings?limit=3000"   # ⚠️ 最多只返回 ~2000 条；分页才能拉全
```

**MCP 等效**：`list_strings(limit=3000)`

**Ghidra GUI 等效**：
1. `Search → For Strings…` → 默认已选 Memory Blocks → `Search` → 等扫描完
2. 或直接打开 `Window → Defined Strings` 面板

从开头的 `truetype/autofitter/DFGothic-EB` 和尾部的 `ImGuiTableFlags_*, Popups/Modals, Stacked modals` 判定：FreeType + Dear ImGui 链入。典型 IGCS 依赖栈。

---

### 1.4 按关键字过滤 `AOB` / `pattern` / `signature`

```bash
curl -s "http://127.0.0.1:8080/strings?limit=500&filter=AOB"
curl -s "http://127.0.0.1:8080/strings?limit=500&filter=pattern"
curl -s "http://127.0.0.1:8080/strings?limit=500&filter=signature"
```

**MCP 等效**：`list_strings(limit=500, filter="AOB")`

**Ghidra GUI 等效**：`Window → Defined Strings` → 顶部 Filter 输入 `AOB`（支持正则，输 `.*AOB.*`）。

关键线索命中：

- `Pattern '%s' contains an illegal character '%c'` —— 告诉我 pattern 用的是 **空格分隔的两位 hex + `??` 通配符** 格式。
- `Pattern '%s' contains a single char for a 2-char byte.` —— 验证上述推论。
- `.?AVAOBHookAction@Hooking@IGCS@@` —— **IGCS 框架** 的 MSVC 未解码类型名，身份确认。

---

### 1.5 列 namespaces / classes 找游戏类名

```bash
curl -s "http://127.0.0.1:8080/namespaces?limit=200"
curl -s "http://127.0.0.1:8080/classes?limit=200"
```

**MCP 等效**：`list_namespaces(limit=200)` / `list_classes(limit=200)`

**Ghidra GUI 等效**：`Window → Symbol Tree` → 展开 `Classes` / `Namespaces` 节点。

命中四个 `*Feature` 类（**这里是第一次犯错的起点**—— 我把这 4 个当成"所有支持的游戏"）：

- `Borderlands4Feature`
- `Hellblade2Feature`
- `SilentHillfFeature`
- `Tekken8Feature`

---

## 2. 第二阶段：手工反编译定位注册惯用模式

### 2.1 手工挑一个 AOB 名字串查 xref

```bash
curl -s "http://127.0.0.1:8080/xrefs_to?address=0x18027a738&limit=10"
# -> From 180135bbe in FUN_180135b90 [DATA]
#    From 180135691 in FUN_180134b50 [DATA]
#    ...
```

**MCP 等效**：`get_xrefs_to(address="0x18027a738")`

**Ghidra GUI 等效**：
1. 按 `G`（Go To）输入 `18027a738` 回车 → 跳到该地址
2. 右键字符串 → `References → Show References to Address`（或快捷键 `Ctrl+Shift+F`）

---

### 2.2 反编译 `FUN_180134b50` 识别注册惯用模式

```bash
curl -s "http://127.0.0.1:8080/decompile_function?address=0x180134b50" | head -100
```

**MCP 等效**：`decompile_function_by_address(address="0x180134b50")`

**Ghidra GUI 等效**：双击 `FUN_180134b50`（或按 `G` 跳到该地址）→ 下方 `Decompiler` 面板。若面板被关了，`Window → Decompiler`。

发现惯用模式 —— **这是后续自动化的基石**：

```c
puVar2 = FUN_1800171a0(&local_78, "48 8D 15 | ?? ?? ?? ?? EB 16 48 ...");   // 构造 pattern std::string
puVar3 = FUN_1800171a0( local_98, "AOB_NAMESSTORE");                         // 构造 name     std::string
FUN_1801084c0((longlong)param_1, puVar3, puVar2);                             // register(container, name, pattern)
```

- `FUN_1800171a0` = `std::string` 构造/赋值包装
- `|` = 捕获偏移标记
- `??` = 单字节通配
- **反编译文本里字面量出现顺序永远是 `(pattern, name)`**

这三个 `addAOB` 包装器地址（后续会反复用到）：
`FUN_180108570` / `FUN_1801084c0` / `FUN_180108700`

---

## 3. 第三阶段：v1 自动化提取器（只找到 2 个游戏专属）

### 3.1 v1 脚本核心逻辑

```python
import re, urllib.request, urllib.parse
from collections import defaultdict

BASE = "http://127.0.0.1:8080/"

def get(ep, **p):
    url = BASE + ep + ("?" + urllib.parse.urlencode(p) if p else "")
    return urllib.request.urlopen(url, timeout=20).read().decode("utf-8","replace").splitlines()

def post(ep, data):
    body = data.encode("utf-8") if isinstance(data,str) else urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(BASE+ep, data=body, method="POST")
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8","replace")

# 1) 抓全部 AOB_* 名字（⚠️ v1 用的是无过滤的 /strings，只拿到 22 条）
aob_names = {}
for ln in get("strings", limit=5000):
    m = re.match(r'^([0-9a-fA-F]+):\s*"(AOB_[A-Z0-9_]+)"\s*$', ln)
    if m: aob_names[m.group(1)] = m.group(2)

# 2) xref -> caller function
caller_to_names = defaultdict(set)
xref_re = re.compile(r"From\s+([0-9a-fA-F]+)\s+in\s+(FUN_[0-9a-fA-F]+)")
for addr, name in aob_names.items():
    for ln in get("xrefs_to", address="0x"+addr, limit=50):
        m = xref_re.search(ln)
        if m: caller_to_names[m.group(2)].add(name)

# 3) decompile 每个 caller, 抽 (pattern, name) 对
LIT = re.compile(r'"((?:[^"\\]|\\.)*)"')
PAT = re.compile(r"^[0-9A-Fa-f ?|]+$")
for func in caller_to_names:
    src = post("decompile", func)
    last_pat = None
    for lit in LIT.findall(src):
        if re.match(r"^AOB_[A-Z0-9_]+$", lit):
            if last_pat: yield (func, last_pat, lit)
            last_pat = None
        elif PAT.match(lit) and " " in lit and lit.count(" ") >= 3 and len(lit) >= 8:
            last_pat = lit
```

---

### 3.2 v1 暴露的两个 BUG

**BUG 1** —— regex 太严：

```python
# 错误版
elif PAT.match(lit) and ("|" in lit or "?" in lit):
```

要求 pattern 必须包含 `|` 或 `?` —— 把游戏专属的纯硬编码 pattern（如 `48 89 46 10 0F 28 ...`）全漏了。**修复**：删掉通配强制，改为"至少 3 个空格"。

**BUG 2** —— `/strings` 接口隐性截断：

| 调用 | 返回条数 |
|---|---|
| `/strings?limit=3000` | 2999 |
| `/strings?limit=5000` | 2999 |
| `/strings?limit=500&filter=AOB_` | 37 (**真实数**) |
| `/strings?offset=0&limit=2000` + `offset=2000` + … | 6302 (**真正的全量**) |

**表象**：v1 只看到 22 个 AOB_*，跑完 31 个名字有 pattern、7 个没捕获。
**修复**：用 `filter=AOB_`（对此任务够用）；彻底的做法见后面的分页循环。

---

### 3.3 v1 结果

修完两个 BUG 后：

- 38 个 AOB 名、41 个 caller 函数、**214 个候选 pattern**
- 只有 `AOB_BL4_*`（BL4 专属 3 个）和 `AOB_SHF_*`（SHF 专属 1 个）被识别为游戏专属
- 其余 34 个全归到"Shared / UE framework (BL4 + HB2 + SHF + Tekken 8)"
- **游戏数：4（本来以为全是支持的游戏）**

---

## 4. 第四阶段：复盘 —— 为什么只有 2 个游戏

**用户反馈**："应该远远不止 2 个游戏，还有 The Outer Worlds 2、Avowed、Oblivion Remastered、Code Vein II 等等"。

两个怀疑方向：

1. **命名约定错了**：不是所有游戏都用 `AOB_<GAME>_xxx` 格式。BL4/SHF 有游戏前缀只是历史巧合，其他游戏用别的方式标识。
2. **关键字串段被截断**：`/strings` 没分页 → 丢掉了超过一半的字符串。

---

## 5. 第五阶段：从进程名字符串重建游戏列表

### 5.1 正确分页拉全量字符串

```bash
for off in 0 2000 4000 6000 8000; do
  curl -s "http://127.0.0.1:8080/strings?offset=$off&limit=2000" >> /tmp/all_strings.txt
done
# 总条数: 6302 （而不是之前的 2999）
```

**MCP 等效**：循环调用 `list_strings(offset=N, limit=2000)`。

**Ghidra GUI 等效**：`Window → Defined Strings` 自然显示全部，默认不截断，直接向下滚动即可。

### 5.2 寻找 PE 可执行名格式

```bash
grep -oE '"[A-Za-z0-9_]+(-Win64-Shipping|-Shipping|-Win)"' /tmp/all_strings.txt | sort -u
```

结果 —— 12 个进程名字符串（**= 12 个候选游戏**）：

```
"Avowed-Win"                 @ 180270940
"b1-Win64-Shipping"          @ 18026aa78
"Banishers-Win64-Shipping"   @ 180274388
"CodeVein2-Win"              @ 180270a80
"Hellblade2-Win64-Shipping"  @ 1802759e8
"M1-Win64-Shipping"          @ 180274428
"OblivionRemastered-Win"     @ 180270980
"Polaris-Win64-Shipping"     @ 180275a50
"SHf-Win64-Shipping"         @ 180275a08
"Stalker2-Win"               @ 180274538
"TheOuterWorlds2-Win"        @ 180270928
"TQ2-Win64-Shipping"         @ 18027aea0
```

### 5.3 追进程名 xref 定位路由函数

```bash
for addr in 18026aa78 180270928 180270940 ... ; do
  curl -s "http://127.0.0.1:8080/xrefs_to?address=0x$addr&limit=20"
done
```

**MCP 等效**：`get_xrefs_to(address="0x180270928")` × 12

**Ghidra GUI 等效**：对每个地址 `G` → `Ctrl+Shift+F`。

命中 **6 个路由函数**：

```
FUN_1800b3fb0  ->  b1
FUN_1800eb060  ->  TheOuterWorlds2 / Avowed / OblivionRemastered / CodeVein2
FUN_180101210  ->  Avowed / Banishers / M1 / Stalker2
FUN_18010ca10  ->  Hellblade2 / Polaris / SHf
FUN_180134b50  ->  Avowed  (顺带的 strcmp)
FUN_180136330  ->  SHf / TQ2   (纯是 UE struct field 偏移表，不含 AOB pattern)
```

### 5.4 反编译 `FUN_1800eb060` —— 顿悟时刻

```c
if (proc == "TheOuterWorlds2-Win") {
    register(AOB_CUSTOM_WRITEATMOSPHERICS_CALL_LOCATION,
             "E8 ?? ?? ?? ?? 80 BB 50 0A 00 00 00 74 0D ...");   // TOW2 专用字节
}
if (proc == "Avowed-Win") {
    register(AOB_CUSTOM_WRITEATMOSPHERICS_CALL_LOCATION,
             "48 89 6C 24 20 44 8B 4C 24 30 | E8 ?? ?? ...");     // Avowed 专用字节
}
if (proc == "OblivionRemastered-Win") { ... }
if (proc == "CodeVein2-Win") { ... }
```

**根本误解**：v1 把所有 `AOB_CUSTOM_WRITEATMOSPHERICS_CALL_LOCATION` 下的多个 pattern 当作"shared 多候选"，其实是 **同名 key 每个游戏绑一条专属 pattern**。

---

## 6. 第六阶段：迭代 v2 / v3 —— 游戏上下文与工厂递归

### 6.1 v2：进程名驱动的 game-context 切换

核心思想：**按线性出现顺序跟踪"当前活跃的游戏"**。

```python
# v2 核心循环（简化版）
current_game = None
for pos, lit in literals_in_order:
    if PROC_RE.match(lit):             # 进程名 → 切换 game
        current_game = proc_to_game(lit)
        last_pat = None
    elif AOB_NAME_RE.match(lit):       # AOB 名 → 结对
        if last_pat and current_game:
            game_data[current_game][lit].append(last_pat)
        last_pat = None
    elif is_pattern(lit):              # pattern 字面量 → 缓存
        last_pat = lit
```

**问题**：`FUN_180134b50` 开头有几十个 pattern 注册在任何 `if (proc == X)` 之前（真正的 "shared" 注册），但也在 "Avowed-Win" 之前；v2 的 `current_game` 还是 None，这些 pair 被漏掉 —— 或者更糟，被错误归到后面某个游戏。

**v2 结果**：10 个游戏，131 个 variants，但很多 pair 丢失。

### 6.2 v3：加入 callee 递归

发现 `FUN_18010ca10` 的 Hellblade2 分支不含内联 pattern，而是调一个 **游戏专属工厂函数** `FUN_1800febf0`。v3 在扫到 callee 时带着当前 game 标签递归进去。

```python
# v3 递归扫描（伪代码）
def scan_func_for_game(func, game, depth=0):
    src = decompile(func)
    pairs, callees = scan_region(src, 0, len(src))
    for pat, name in pairs:
        record(game, pat, name, func)
    if depth < MAX_DEPTH:
        for callee in callees:
            scan_func_for_game(callee, game, depth+1)
```

**v3 结果**：9 个游戏有 override、47 keys、214 variants。但仍然不见 Hellblade 2、Tekken 8、Banishers、TQ2。

---

## 7. 第七阶段：深挖隐藏游戏

### 7.1 游戏专属工厂函数的注释字面量

```bash
for func in 1800febf0 1800ff070 1800fe240 1800feed0; do
  curl -s "http://127.0.0.1:8080/decompile_function?address=0x$func" | grep -oE '"[^"]*"' | head
done
```

输出：

```
FUN_1800febf0: "Hellblade 2 specific features"
FUN_1800ff070: "Tekken 8 specific features"        ← Polaris = Tekken 8
FUN_1800fe240: "Borderlands 4 specific features"
FUN_1800feed0: "Silent Hill f specific features"
```

**关键发现**：`Polaris` UE 代号就是 Tekken 8。这些工厂自己很小（13-22 行），只设 vftable + 显示名；**真正的 AOB 注册并不在这些工厂里**，而是在被它们实例化的 Feature 对象的虚方法里，通过运行时虚表调度。

### 7.2 扩大搜索：所有 `strcmp` 调用参数

与其只认 `-Win*` 后缀，不如直接看所有传给字符串比较函数（`FUN_1800cd250` / `FUN_1800cd290`）的字面量：

```bash
rm -f /tmp/all_decomp.txt
for f in 1800b2de0 1800b3fb0 1800eb060 1800fe350 1800fec80 1800fef50 \
         1800ff0b0 180101210 180114860 1801155d0 18010ca10 18012da30 \
         180134b50 180136330 180138800; do
  curl -s "http://127.0.0.1:8080/decompile_function?address=0x$f" >> /tmp/all_decomp.txt
done

grep -oE '(FUN_1800cd250|thunk_FUN_1800cd290|FUN_1800cd290)\([^,]+,\s*"[^"]+"' /tmp/all_decomp.txt \
  | grep -oE '"[^"]+"' | sort -u
```

输出（**15 个标签 → 13 个唯一游戏**）：

```
"Avowed-Win"                                          
"b1-Win64-Shipping"                                   
"Banishers-Win64-Shipping"                            
"Borderlands4"                    ← Borderlands 4 短名
"CodeVein2-Win"                                       
"Hellblade2-Win64-Shipping"                           
"M1-Win64-Shipping"                                   
"MafiaTheOldCountry"              ← ⭐ 新游戏：Mafia: The Old Country
"OblivionRemastered-Win"                              
"Polaris-Win64-Shipping"                              
"SHf-Win64-Shipping"                                  
"Stalker2-Win"                                        
"TheOuterWorlds2"                 ← TOW2 短名（没有 -Win）
"TheOuterWorlds2-Win"                                 
"TQ2-Win64-Shipping"                                  
```

Mafia 之所以被 v1-v3 漏掉：它的字面量 `"MafiaTheOldCountry"` 不匹配 `-Win*` 正则 —— 必须看 strcmp 参数，不能只看字符串格式。

### 7.3 发现析取（OR）分支：Mafia || Borderlands4

反编译 `FUN_180134b50` 的 200-215 行：

```c
cVar1 = thunk_FUN_1800cd290(local_58, "MafiaTheOldCountry");
if (cVar1 == '\0') {                                      // 注意：==，不是 !=
    cVar1 = thunk_FUN_1800cd290(local_58, "Borderlands4");
    if (cVar1 == '\0') goto LAB_1801353a3;                // 两者都不匹配才跳过
}
// body: 运行条件 = (Mafia) OR (BL4)
register(AOB_OBJECTSSTORE, "48 8D 0D | ?? ?? ?? ?? E8 ?? ...");
LAB_1801353a3:
// 继续 shared 的 ENGINEVERSION 注册
register(AOB_ENGINEVERSION, ...);
```

v3 的 "按 tag 分段" 会把这块 pattern 只归给最后出现的 tag（BL4），**漏掉了 Mafia**，并且把 `LAB_1801353a3:` 后面的 shared pattern 错误地继续归到 BL4。

---

## 8. 第八阶段：v4 —— 花括号作用域 + goto-label 感知的解析器

### 8.1 设计：事件流 + 游戏上下文栈

把反编译文本 **一次扫出 7 种事件**，按位置排序，然后按顺序"重放"：

| 事件 | 触发条件 |
|---|---|
| `game_tag` | 字符串字面量匹配已知游戏标识集合 |
| `pat` | 字符串字面量看起来是 AOB 字节 pattern |
| `name` | 字符串字面量匹配 `^AOB_[A-Z0-9_]+$` |
| `brace` | `{` 或 `}` |
| `if_ne` | `if (cVar1 != '\0')` |
| `if_eq` | `if (cVar1 == '\0')` |
| `goto` | `goto LAB_xxxx` |
| `label` | `LAB_xxxx:`（行首） |

维护一个 **上下文栈** `stack: list[{games, depth, end_label}]`：

- 见到 `game_tag` → 累积到 `pending_tags`
- 见到 `if_ne` 紧跟 `{` → `pending_tags` 的游戏压栈，`depth = 当前 brace_depth`
- 见到 `if_eq` 紧跟 `{` → 进入 **OR-building** 模式：继续吞后续 `game_tag` 直到见到 `goto LAB`，然后等 `}` 关上这个 OR 块，之后的区域按"多游戏并集"直到匹配的 `LAB:`
- 见到 `}` 且深度等于某个上下文的 depth → 该上下文出栈
- 见到 `label LAB_xxx` → 弹掉所有 `end_label == LAB_xxx` 的上下文
- 见到 `pat` → 缓存
- 见到 `name` → 与缓存 pattern 配对，**归给当前栈里所有游戏**（若栈空则归 shared）

### 8.2 v4 核心代码

```python
def parse_and_attribute(src):
    events = []
    for m in STR_LITERAL.finditer(src):
        lit = m.group(1)
        if lit in tag_literals:           events.append((m.start(), "game_tag", lit))
        elif AOB_NAME_RE.match(lit):      events.append((m.start(), "name", lit))
        elif is_pattern(lit):             events.append((m.start(), "pat", lit))
    for m in re.finditer(r"[{}]", src):   events.append((m.start(), "brace", m.group(0)))
    for m in re.finditer(r"if\s*\(\s*\w+\s*(!=|==)\s*'\\0'\s*\)", src):
        events.append((m.start(), "if_ne" if m.group(1)=="!=" else "if_eq", None))
    for m in re.finditer(r"goto\s+(LAB_[0-9a-fA-F]+)", src):
        events.append((m.start(), "goto", m.group(1)))
    for m in re.finditer(r"^(LAB_[0-9a-fA-F]+):", src, re.MULTILINE):
        events.append((m.start(), "label", m.group(1)))
    events.sort()

    stack, brace_depth, pending_tags, or_building = [], 0, [], None
    last_pat, results = None, []

    for pos, kind, payload in events:
        if kind == "brace" and payload == "{":
            brace_depth += 1
            if pending_tags and or_building is None:
                # 是不是 game_tag ... if_ne 后的那个 {
                if any(e[1]=="if_ne" for e in nearby_events_before(pos)):
                    stack.append({"games": list(pending_tags), "depth": brace_depth})
                    pending_tags = []
                elif any(e[1]=="if_eq" for e in nearby_events_before(pos)):
                    or_building = {"games": list(pending_tags), "goto_label": None,
                                   "outer_depth": brace_depth}
                    pending_tags = []
        elif kind == "brace" and payload == "}":
            while stack and stack[-1]["depth"] == brace_depth and not stack[-1].get("end_label"):
                stack.pop()
            if or_building and brace_depth == or_building["outer_depth"]:
                if or_building["goto_label"]:
                    stack.append({"games": or_building["games"],
                                  "depth": -1, "end_label": or_building["goto_label"]})
                or_building = None
            brace_depth -= 1
        elif kind == "game_tag":
            (or_building["games"] if or_building else pending_tags).append(payload)
        elif kind == "goto" and or_building:
            or_building["goto_label"] = payload
        elif kind == "label":
            stack[:] = [c for c in stack if c.get("end_label") != payload]
        elif kind == "pat":
            last_pat = payload
        elif kind == "name" and last_pat:
            games = [g for ctx in stack for g in ctx["games"]]
            results.append((games, last_pat, payload))
            last_pat = None
    return results
```

（完整版在 `extract_aob_patterns.py`）

### 8.3 GUI 等效说明

严格来讲，Ghidra GUI 里没有直接对应项 —— 这种跨多函数、感知控制流的聚合提取必须脚本化。最接近的人工近似步骤：

1. 对每个注册函数打开 Decompiler 面板（`Ctrl+E` / 双击函数）
2. 用鼠标 **手动跟随 `if (cVar1 != '\0') { ... }` 的花括号配对**（Ghidra Decompiler 支持 Ctrl+M 高亮匹配大括号）
3. 在每个花括号里把 `(pattern, "AOB_...")` 的字面量对抄出来
4. 手动记录当前 `if (strcmp(..., "<game>"))` 的游戏标签
5. 对 `goto LAB:` 跳出标签，再在对应的 `LAB:` 行关闭游戏上下文

对 12 个注册函数 × 平均 200 行反编译 = **约 2400 行肉眼扫**。脚本化后 20 秒搞定。

---

## 9. 最终产物与结果

### 9.1 文件

| 文件 | 内容 |
|---|---|
| `aob_patterns_by_game.json` | 按 game → key → variant_count/patterns/registered_in 组织的结构化结果 |
| `extract_aob_patterns.py` | v4 提取器脚本，可重跑 |
| `REVERSE_ENGINEERING_WALKTHROUGH.md` | 本文档 |

### 9.2 数字

- **13 个游戏检测到**（`GAME_TAGS` 表里 15 个标签合并后）
- **9 个游戏有专属 override**；**4 个游戏只用 shared 多候选池**
- **49 个 per-game key 条目**
- **215 个候选 pattern**

### 9.3 游戏汇总

**有专属 pattern override（9）**：

| 游戏 | Keys | Variants |
|---|---:|---:|
| Borderlands 4 | 5 | 5 |
| Avowed | 3 | 3 |
| The Outer Worlds 2 | 2 | 2 |
| Oblivion Remastered | 2 | 2 |
| Unknown (UE codename M1) | 2 | 2 |
| Code Vein II | 1 | 1 |
| Mafia: The Old Country | 1 | 1 |
| S.T.A.L.K.E.R. 2 | 1 | 1 |
| Silent Hill f | 1 | 1 |

**仅用 shared 池（4）**：Banishers: Ghosts of New Eden、Hellblade II、Tekken 8（Polaris）、Unknown（TQ2）

**共享 UE 框架池**：31 keys × 197 variants

---

## 10. 全流程的 GUI 纯手工等效版本

| 本脚本做的 | Ghidra GUI 手工操作 | 备注 |
|---|---|---|
| 载入并分析 DLL | `File → Import File…` → `Analyze` | 选 PE-x86-64 |
| 看段布局 | `Window → Memory Map` | |
| 拉字符串 | `Window → Defined Strings` | 不分页、直接滚动 |
| 过滤 `AOB_` | Defined Strings 顶部 Filter 框 | 支持正则 |
| 找注册函数 | 对每个 AOB 字符串 `Ctrl+Shift+F` | 38 次 |
| 找路由函数 | 对每个进程名 `-Win*` 字符串 `Ctrl+Shift+F` | 12 次 |
| 读每个注册/路由函数 | 双击函数 → Decompiler 面板 | ~16 个函数 |
| 跟踪花括号作用域 | Decompiler 里 `Ctrl+M` 高亮匹配大括号 | 每个 `if` 块都要跟 |
| 跟踪 goto/label | 肉眼跟踪 `goto LAB_xxx` → 找到对应 `LAB_xxx:` | 最容易出错的一步 |
| 按 tag / 分支归类 pattern | 手抄到表格 / Excel | 200+ 条，易错 |
| 查 vftable 对应类 | Symbol Tree → Classes → 找 `*Feature` | 解 Polaris=Tekken 8 这种代号 |
| 探索隐藏游戏标识 | 在 Decompiler 里搜 `FUN_1800cd250(` / `FUN_1800cd290(` 调用，看第二个字面量参数 | 这一步发现 MafiaTheOldCountry |

一个注意点：Ghidra 的 Decompiler 反编译结果在每次重打开时的行号是稳定的，但若启用了 "去除噪声" 类型显示选项会改变文本，正则匹配脚本要有适应性。

---

## 11. 核心经验与坑点清单

### 11.1 技术层面

1. **`/strings` 端点有隐性截断**：实测 `limit=5000` 也只返回 ~2000 条。**全量必须靠 `offset+limit` 分页**；定向查找用 `filter=<kw>`。
2. **MCP 工具没连上也能跑**：Ghidra 的 HTTP API 是 bridge 的底层，直接 `curl`/`urllib` 是完全合法的旁路，语义一致。
3. **Pattern 字面量未必有通配符**：游戏专属 AOB 常常是纯 hex，正则别要求必须含 `?` / `|`。
4. **别只信 demangled 类名**：本项目中 `*Feature` 类只覆盖 4 个游戏，实际支持 13 个 —— 因为大多数游戏的 per-game 逻辑用**进程名字符串比较**分流，而不是每个游戏都继承一个 C++ 类。
5. **游戏标识不一定是 PE 可执行名**：`MafiaTheOldCountry` 直接是代号字符串，既没有 `-Win` 后缀也没在进程名格式里。扫所有 `strcmp` 调用的参数字面量，才能拿到完整游戏列表。
6. **同名 AOB 在不同游戏有不同 pattern**：`AOB_CUSTOM_WRITEATMOSPHERICS_CALL_LOCATION` 在 4 个游戏里是 4 条完全不同的 pattern —— 要区分"多候选 fallback" vs "per-game override"。二者的关键差别是 **是否处于 `if (proc == "<game>")` 的作用域内**。
7. **反编译文本里的 `goto LAB:`/`LAB:` 不是装饰**：必须识别成控制流边界。不处理就会错把 shared 块粘到某个 game 分支的尾巴上。
8. **OR 析取是 `if (A == 0) { if (B == 0) goto L; } body L:`**：判断条件是相等零（失败），两层才继续。不识别这种惯用法会漏 Mafia。
9. **CPython 在 Windows 默认 GBK 编码**：脚本有 Unicode 字符（比如 `•`）时 `print` 会挂；加 `sys.stdout.reconfigure(encoding='utf-8')` 或设 `PYTHONIOENCODING=utf-8` 环境变量。

### 11.2 方法论层面

1. **别过早相信第一版的抽象**：v1 发现 38 个 AOB 名并成功提 pattern 后，我以为任务完成了。实际上整个命名约定是我自己脑补的 —— 要不是用户反馈，我不会发现更大的结构。
2. **用户反馈是系统性的破坏工具**：当用户说"应该有更多"，那就是信号：**你的假设模型错了**。这时候不应该在当前模型下找更多 —— 要重新审视模型。
3. **每一轮迭代都应该有"可解释的失败"**：v2 比 v1 多发现 6 个游戏，但 Hellblade/Tekken/Banishers/TQ2 还是空。对这些空结果不要放过：深挖后揭出 "工厂函数只是构造器" "某些游戏只用 shared 池" 这两个新事实。
4. **命名约定是脆弱的锚**：凡是基于"命名/前缀"的归类都要交叉验证 —— 用**控制流**（谁在 `if (proc == X)` 里被注册）做复核。

---

## 附：可重跑命令

```bash
# 确认 Ghidra HTTP 服务在线
curl -sf http://127.0.0.1:8080/methods?limit=1 >/dev/null || echo "Ghidra not ready"

# 重新生成报告
python D:/dev/uuuaobcapture/extract_aob_patterns.py

# 查看结果
python - <<'PY'
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
d = json.load(open(r'D:\dev\uuuaobcapture\aob_patterns_by_game.json', encoding='utf-8'))
for game, body in d["games"].items():
    print(f"{game:<55} keys={body['key_count']}")
PY
```
