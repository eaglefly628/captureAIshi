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
- [x] **P1: find_fnamepool_global() backref 扫全模块太慢** (fixed ce573b4) —
  Now uses VirtualQuery to iterate only PAGE_READWRITE regions (skips .text).
- [x] **P1: find_fnamepool_global() backref 无交叉验证** (fixed ce573b4) —
  Now validates CurrentBlock (+0x08) is small int (< 128) before accepting candidate.
- [x] **P2: fname_resolve 宽字符 null 终止位置错误** (fixed ce573b4) —
  Now uses WideCharToMultiByte return value: `out[bytes > 0 ? bytes : 0] = '\0';`
- [ ] **P2: log_guobjectarray_details 使用默认 stride 采样** (spotted by xiaoni review) —
  在 detect_fuobjectitem_stride() 之前调用，此时 stride=32 off=0x10 是默认值，若实际 stride=24 则打印的 obj* 地址错误（有"may still be default"注释，但没有明显警告）。
  Fix: 检测完 stride 后再调用，或在日志中加 "WARNING: stride not yet detected" 标注。
- [ ] **P2: _detect_bridge 无重试** (spotted by 主程序员)
- [x] **detect_fuobjectitem_stride 采样 items 0..29** (fixed d7b038c) -- now samples tail
- [x] **WorldList vcnt>=30 拒绝 UWorld** (fixed d7b038c) -- now vcnt>=1
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

## FUObjectItem Stride -- Key Facts (do not guess, always detect)

FUObjectItem size is determined by BUILD CONFIG, not engine version:

| Config                         | stride | Object* off |
|-------------------------------|--------|-------------|
| UE_PACK_FUOBJECT_ITEM          | 0x10   | 0x00 (low bits = flags, mask &~7) |
| Standard Shipping              | 0x18   | 0x00        |
| Development/Debug or WITH_VERSE_VM | 0x20 | 0x10    |

FChunkedFixedUObjectArray layout is FIXED since UE4.21 (all versions):
  +0x00 Objects** (chunk pointer array)
  +0x08 PreAllocatedObjects*
  +0x10 MaxElements (int32)
  +0x14 NumElements (int32)  <- at FUObjectArray+0x24 = GUOBJARRAY_NUMELEMS_OFF=36
  +0x18 MaxChunks (int32)
  +0x1C NumChunks (int32)
PreAllocatedObjects is also a contiguous FUObjectItem array (2nd data source for stride detection).

Detection method (Dumper-7):
- chunk 0 has 65536 entries, always full in any shipped game
- Try each (stride, obj_off) candidate against first 30 items in chunk 0
- Count how many item.Object values are valid heap pointers (non-null + readable vtable)
- Cross-validate with g_engine_ptr at GEngine.InternalIndex for definitive result
- Implemented in detect_fuobjectitem_stride() -- called early, before GUObjectArray walk

Confirmed for StackOBot (Development, UE5.7): stride=0x20, Object at +0x10.

## FName Resolution -- Current Status

**Have:**
- `get_fname_cmpidx_for(str)` -- string -> ComparisonIndex (block 0 only)
- `fname_cmpidx_matches(idx, str)` -- index vs known string (block 0 only)
- `find_objects_by_class_name(name, out, max)` -- batch class search
- `find_first_object_by_class_name(name)` -- single result

**Also have (f135597):**
- `fname_resolve(uint32_t comp_idx, char* out, int len)` -- any ComparisonIndex to string
  Requires g_fnamepool_global (for block 1+); block 0 works standalone.
- `find_fnamepool_global()` -- locates FNamePool struct in module .bss
- `fname_get_block(bi)` -- get block heap pointer for any block index

**Missing:**
- FNamePool block 1+ reliably found -- need g_fnamepool_global via export or backref.
  Game-specific class names (block_idx > 0) still unresolvable without the global.

**Coverage:** All standard engine class names are in FNamePool block 0:
  PlayerController, PlayerCameraManager, DirectionalLight, PostProcessVolume,
  SkeletalMeshComponent, FoliageInstancedStaticMesh, World, etc.
  Game-specific classes may be in block 1+ (need multi-block support).

## Changelog (latest)

### [v0.2.0] 7de8e46 -- xiaoni
- `find_localplayer()`: scans GUObjectArray for object with class FName 'LocalPlayer'.
  UWorld does NOT inherit FExec (inherits FNetworkNotify), so UWorld fallback was wrong.
  ULocalPlayer::Exec routes to PlayerController->CheatManager for all gameplay commands.
- `exec_console_command_internal`: after GEngine returns false, try ULocalPlayer::Exec.
  Lazy re-scan in case LocalPlayer wasn't ready at init time.
- Called from cs_engine_scan_thread after UWorld scan.
- `main.py --wait-attach`: pause before teardown for debugger attach.
- `temp/BotDebugGameMode.cpp`: added exec chain test via 3 paths (PC->ConsoleCommand,
  GEngine->Exec(World), GEngine->Exec(nullptr)) with return value logging.

### [v0.2.0] ce573b4 -- xiaoni
- `FUObjectItem stride (32, 0x08)`: game log confirmed sizeof=32 and Object* at +0x08 (not +0x10).
  Layout: WeakHandle(8) + Object*(8) + Flags(4) + ClusterRoot(4) + Serial(4) + Pad(4).
  Added (32, 0x08) as first candidate in detect_fuobjectitem_stride() and validate_guobjectarray().
  Updated FUOBJECTITEM_OBJECT_OFF_DEFAULT from 0x10 to 0x08. N_CONFIGS: 3->4.
- `FNamePool UE5 header format` (root cause of "not found" in 9824 regions):
  UE4 header: len<<1 -- "None" pattern {0x08,0x00,'N','o','n','e'}
  UE5 header: (len<<6)|(probeHash<<1)|bIsWide -- "None" pattern {hash*2,0x01,'N','o','n','e'}
  Old code only searched UE4 pattern, so all UE5 blocks were skipped.
  Replaced kFNameNone+memcmp with fname_block0_matches_none() that checks byte[1]==0x00 (UE4)
  or byte[1]==0x01 (UE5, len=4 always gives high byte=1). Sets g_fname_header_shift (1 or 6).
- `fname_entry_len(hdr)`: new helper replaces inline (hdr>>1) in get_fname_cmpidx_for and fname_resolve.
  Uses g_fname_header_shift. Also removed probe-hash-dependent exact-header match in search.
- `fname_resolve`: fixed wide-char null-term (use WideCharToMultiByte return value).
- `find_fnamepool_global() backref`: now scans only PAGE_READWRITE regions via VirtualQuery.
  Adds CurrentBlock sanity check (< 128) to reject false positives.

### [v0.2.0] f135597 -- xiaoni
- `find_fnamepool_block0()`: root cause found -- 256KB size filter is WRONG.
  FNamePool blocks are 128KB (word_off max=0xFFFF, byte_off max=0x1FFFE). All
  blocks were filtered by `mbi.RegionSize < 256KB`. Fixed to 64KB.
- `find_fnamepool_global()`: new -- finds FNamePool struct in module .bss
  via export symbol (GNamePool) or backref scan from block0. Enables block 1+.
- `fname_resolve(comp_idx, out, out_len)`: new -- any ComparisonIndex -> string.
  Uses g_fnamepool_global for block 1+, g_fnamepool_block0 for block 0.
- Early FNamePool log in cs_engine_scan_thread: now logs block0/global addr and
  FName("World"), FName("GameEngine") indices before GEngine search begins.

### [v0.2.0] d7b038c -- xiaoni
- `detect_fuobjectitem_stride`: fixed sampling range -- was items 0..29 (score=7/30 fails),
  now samples tail (num_elems-30..num_elems-1) when ge_idx unavailable. Heuristic threshold
  N/3->N/5 so score=7 passes. Root cause: ObjFirstGCIndex=28286 means early slots are empty.
- `find_uworld_via_worldlist`: vcnt>=30 -> vcnt>=1. validate_function_ptr strict on optimized
  prologues gives UWorld vcnt=1. FWC+0x2C0 confirmed as UWorld by game log -- outer chain
  is the real discriminator.
- `log_guobjectarray_details()`: new -- logs ObjFirstGCIndex, NumElements, chunk[0] addr,
  sample objects at [tail-5..tail] and [1..5]. Called after find_guobjectarray() for cross-
  checking bridge view vs game BeginPlay output.

### [v0.2.0] ed8ba05 -- xiaoni
- `find_objects_by_class_name()` + `find_first_object_by_class_name()` added
  Foundation for direct-memory camera control (find APlayerCameraManager -> write transforms)
- Review: fixed two UWorld search bugs -- secondary vtable offset was using GEngine's FExec
  offset (0x28) for UWorld's FNetworkNotify (wrong). Now: primary vtable>=30 + outer chain only.
- `g_engine_ptr` guard removed from FName path in `find_uworld_via_guobjectarray()`

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
