# GUObjectArray 数据结构全版本对照（UE 4.20 - 5.07）

> 数据来源: UE4SS `assets/MemberVarLayoutTemplates/` (PDB 符号导出)
> 日期: 2026-04-12

## 核心结论

1. **TUObjectArray (FChunkedFixedUObjectArray) 从 4.20 到 5.07 布局完全不变** — 0x20 字节，ChunkSize=65536
2. **FUObjectItem 在 4.20-5.06 都是 0x18** — 但 **5.07 破坏性变更**：Object 和 Flags 互换位置
3. **FUObjectArray 外壳在三个时期大小不同** — 但内部 ObjObjects 偏移始终是 0x10

---

## FUObjectItem 历代对比

### UE 4.20 - 5.06（全部相同，0x18）
```cpp
struct FUObjectItem {           // Total: 0x18 (24 bytes)
    UObjectBase*  Object;       // 0x00
    int32         Flags;        // 0x08
    int32         ClusterRootIndex; // 0x0C
    int32         SerialNumber; // 0x10
    // pad 4 bytes to 0x18
};
```

### UE 5.07（破坏性变更！Object 和 Flags 互换）
```cpp
struct FUObjectItem {           // Total: 0x18 (24 bytes)
    int64  FlagsAndRefCount;    // 0x00  ← 原来是 Object!
    // uint8 RemoteId @ 0x00 (重叠 union)
    UObjectBase*  Object;       // 0x08  ← 原来是 Flags!
    // uint32 ObjectPtrLow @ 0x08 (重叠 union)
    int32  SerialNumber;        // 0x10
    int32  ClusterRootIndex;    // 0x14  ← 从 0x0C 移到 0x14
};
```

**影响**: 遍历 GUObjectArray 时读 Object 指针的偏移从 0x0 变成了 0x8。必须运行时探测或版本检测。

---

## TUObjectArray / FChunkedFixedUObjectArray（4.20-5.07 全部相同）

```cpp
struct TUObjectArray {          // Total: 0x20 (32 bytes) — 所有版本一致
    FUObjectItem** Objects;     // 0x00  二级指针 [ChunkIdx][InChunkIdx]
    FUObjectItem*  PreAllocatedObjects; // 0x08
    int32  MaxElements;         // 0x10
    int32  NumElements;         // 0x14
    int32  MaxChunks;           // 0x18
    int32  NumChunks;           // 0x1C
};
// ChunkSize = 65536 (0x10000)，所有版本相同
// ChunkIdx = Index / 65536, InChunkIdx = Index % 65536
```

---

## FUObjectArray 外壳（三个时期）

| UE 版本 | Total Size | ObjObjects 偏移 | 变化原因 |
|---------|-----------|----------------|---------|
| 4.20-4.21 | **0x1B0** | 0x10 | 含 CriticalSection 锁 (~0x100) |
| 4.22-4.26 | **0x130** | 0x10 | 移除部分锁，缩小 |
| 4.27-5.06 | **0xB8** | 0x10 | 重构 GC 相关字段 |
| 5.07 | **0xC0** | 0x10 | 加 ObjAvailableListEstimateCount |

**关键不变量**: `ObjObjects` 偏移始终是 **0x10**。

### UE 4.27 详细布局（最常见的目标版本）
```
0x00  ObjFirstGCIndex              (int32)
0x04  ObjLastNonGCIndex            (int32)
0x08  MaxObjectsNotConsideredByGC  (int32)
0x0C  OpenForDisregardForGC        (bool + 3 pad)
0x10  ObjObjects                   (TUObjectArray, 0x20)  ← 入口
0x30  [internal padding]           (0x28)
0x58  ObjAvailableList             (TArray<int32>)
0x68  UObjectCreateListeners       (TArray)
0x78  UObjectDeleteListeners       (TArray)
0xB0  MasterSerialNumber           (int32)
0xB8  total
```

---

## UE4SS 如何找 GUObjectArray

### 1. Lua AOB 脚本扫描
文件: `UE4SS_Signatures/GUObjectArray.lua`

```lua
function Register()
    -- 返回 AOB 字节序列
    return "8 B/5 1/0 4/8 5/D 2/7 4/5 A/4 8/6 3/0 1/..."
end

function OnMatchFound(matchAddress)
    local movInstr = matchAddress + 0x1A
    local nextInstr = movInstr + 0x7
    local offset = movInstr + 0x3
    -- 解析 RIP-relative MOV 指令获取全局变量地址
    local dataMoved = nextInstr + DerefToInt32(offset) - 0x10
    return dataMoved
end
```

### 2. 启动流程
```
UE4SSProgram::init()
  → Signatures::setup_lua_scan_overrides()     // 加载 Lua AOB 脚本
  → UnrealInitializer::SetupUnrealModules()    // 执行扫描
  → UObjectArray::SetupGUObjectArrayAddress()  // 注册找到的地址
  → ForEachUObject(callback)                   // 遍历所有对象
```

### 3. FUObjectItem 大小探测
```cpp
// UE4SSProgram.cpp line 209-214
if (settings_manager.EngineVersionOverride.DebugBuild) {
    if (Unreal::Version::IsAtLeast(4, 25)) {
        Unreal::FUObjectItem::UEP_TotalSize() += sizeof(void*);
        // Debug build: 0x18 + 0x8 = 0x20
    }
}
```

---

## 运行时探测 FUObjectItem 大小（推荐方案）

不依赖版本号，直接量：

```cpp
// 读第一个 chunk 的前两个 item
FUObjectItem* chunk0 = Objects[0];
// 假设 item_size，尝试 0x18 和 0x20
for (int try_size : {0x18, 0x20, 0x10}) {
    void* obj0 = *(void**)((char*)chunk0 + 0);        // offset 0x0
    void* obj1 = *(void**)((char*)chunk0 + try_size);  // 下一个 item
    void* obj0_alt = *(void**)((char*)chunk0 + 0x8);   // 5.07: Object@0x8

    // 验证: 有效 UObject 指针应该在堆范围 [0x10000, 0x7F0000000000]
    // 且 vtable 指向 .text 段
    if (is_valid_uobject(obj0) && is_valid_uobject(obj1)) {
        item_size = try_size;
        object_offset = 0x0;
        break;
    }
    if (is_valid_uobject(obj0_alt)) {
        object_offset = 0x8;  // UE 5.07 layout
    }
}
```

---

## 给小逆的实现建议

1. **ObjObjects 偏移 0x10 是硬编码安全的** — 16 个版本都是 0x10
2. **TUObjectArray 布局是硬编码安全的** — 0x20，所有版本一致
3. **FUObjectItem 必须运行时探测** — 5.07 打破了 Object@0x0 的假设
4. **FUObjectArray 外壳大小不需要知道** — 只需要 ObjObjects@0x10 就够了
