# Reverse Engineering Agent (小逆) — Shared Notes

## Active TODO

- [ ] **P0: 四级 Fallback GEngine/UWorld 检测** (from lead 调研) — 当前只有 Level 2（字符串锚点）。需实现完整 fallback 链，多重交叉验证：
  - **Level 0: PE 导出符号** — 搜修饰名 `?GUObjectArray@@3VFUObjectArray@@A`、`?GEngine@@3PEAVUEngine@@EA` 等。很多 Shipping build 保留了导出符号（UE4SS 的主要策略），最快最准。
  - **Level 1: GUObjectArray AOB → 反射遍历** — GUObjectArray 是 UE 所有版本都有的核心全局变量（比 GEngine 更稳定）。找到后遍历所有 UObject 找 UEngine/UWorld 实例。Dumper-7 和 UE4SS 都验证过，支持 UE4.11-5.x。注意 UE4.21+ 用 Chunked Array，之前用 Fixed Array。有些游戏用加密指针（Dumper-7 有 InitObjectArrayDecryption）。
  - **Level 2: 字符串锚点 xref** — 我们现有的 8 个锚点（已实现）。
  - **Level 3: GSpots 式文件级扫描** — 在 exe .text 段搜 `MOV [rip+xx]` 指令模式 + Lua 自定义签名兜底。
  - 参考: UE4SS (`docs/refCode/RE-UE4SS-main/`), Dumper-7 (github.com/Encryqed/Dumper-7), GSpots (github.com/Do0ks/GSpots), UEVR (github.com/praydog/UEVR)
- [ ] **P0: 真实 UE5 游戏端到端验证** — 跑通一个游戏。
- [ ] **P1: AC 预检脚本** — 检测 EasyAntiCheat.dll / BEService.exe
- [x] **P1: bridge-test 命令注入** (fixed by 主程序员) — 已加白名单。
- [ ] **P2: _detect_bridge 无重试** (spotted by 主程序员)
- [ ] **P2: hardcoded sleep(0.5)** (spotted by 主程序员)
- [ ] **P2: 增强 Pause** — UWorld::IsPaused 内存写入 fallback

## [v0.2.0] Bridge DLL Architecture

Bridge DLL (`3rdparty/bridge/`): TCP 9998, GEngine string-xref scan, Exec() vtable, Camera path (Catmull-Rom + SLERP), timestop, HUD toggle, hotsampling.

Driver: `ue5_console.py` auto-fallback bridge:9998 → UUU:1985, `_detect_bridge()` via `__bridge_ping`.

### Camera Control Methods
- **Bridge DLL** — 注入 + console exec (UE4/UE5, 无反作弊)
- **External Memory** — ReadProcessMemory (绕 user-mode AC)
- **Cheat Engine** — 手动找 offset

### GEngine Scanner
8 个锚点 (5 wide + 3 ASCII, 含 UEVR 验证), 引擎通用 pattern, 无需 per-game 数据库。

## Changelog (latest)

### [v0.2.0] fa65fba -- xiaoni
- `find_uworld_via_guobjectarray()`: 主动扫 GUObjectArray 找 UWorld，结构指纹（无 RTTI/FName）
  - 指纹：主 vtable >= 50 entries + FExec@+0x28 + OuterPrivate != null + Outer.Outer == null
  - 对比 UE4SS：他们靠 hook ULocalPlayer::Exec 参数被动捕获，游戏空闲时失效
  - 我们：hook（被动更新）+ 主动扫描（立即可用），双路保障
- 调用位置：cs_engine_scan_thread 在 install_all_fexec_hooks() 之后立即调用
- 解决 "还是不行啊" -- ToggleDebugCamera/ShowHUD 等游戏命令因 g_world_ptr=NULL 失败

### [v0.2.0] Fix ProcessConsoleExec: wrong function + wrong vtable range — xiaoni
- **Root cause**: calling wrong function (Exec) at wrong vtable range (110-130) with wrong param order
- **Correct function**: `UObject::ProcessConsoleExec(TCHAR*, FOutputDevice&, UObject*)` at vtable[79] (UE5.7)
- Fix: typedef param order `(this, cmd, ar, executor)` not `(this, world, cmd, ar)`
- Fix: scan range 65-90 instead of 110-130
- Built-in version DB (UE4SS PDB-verified): UE 4.27-5.07, 9 entries
- Ar-callback validation: detect if candidate function actually calls FOutputDevice virtual methods
- Dummy FOutputDevice with callback flag replaces NULL Ar
- Research archived to `agents/reversing/ARCHIVE.md` (full vtable index table)

### [v0.2.0] d32d2aa — xiaoni
- TCP 秒启 + GEngine 后台 scan, launcher 秒退检测, 8 锚点, diagnostics, fallback, status

旧版 CL 和已完成 TODO 见 `agents/reversing/ARCHIVE.md`。
