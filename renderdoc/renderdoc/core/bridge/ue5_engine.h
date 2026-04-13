/*
 * ue5_engine.h -- UE5 engine interface for captureAIshi bridge
 *
 * WARNING: This header contains static global state. It MUST only be
 * included from a single translation unit (console_server.h -> core.cpp).
 * Including from multiple .cpp files will create independent copies.
 *
 * Locates GEngine and key engine functions via pattern scanning,
 * provides console command execution, timestop, and camera control.
 *
 * ASCII only (MSVC C4819 compliance).
 */

#ifndef CAPTUREAI_UE5_ENGINE_H
#define CAPTUREAI_UE5_ENGINE_H

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
#include <atomic>
#include <cmath>

#include "pattern_scan.h"

/* Forward-declare bridge_log from bridge.cpp */
extern void bridge_log(const char* fmt, ...);

/* -- UE5 type stubs ------------------------------------------------ */

/* We only need opaque pointers; no real UE5 headers needed */
typedef void UEngine;
typedef void UWorld;
typedef void APlayerController;
typedef void FOutputDevice;

/* -- GEngine finder ------------------------------------------------ */

/*
 * GEngine is THE god pointer in UE5. Finding it unlocks:
 *   - Console command execution (Exec)
 *   - World access (GetWorld)
 *   - Player controller access
 *   - Viewport manipulation
 *
 * Strategy (ordered by reliability):
 *
 * 1. String xref method:
 *    - Find string "r.HLOD" or "r.Streaming.PoolSize" in .rdata
 *    - Find LEA instructions referencing that string
 *    - Near those LEAs, find MOV rax,[rip+X] loading GEngine
 *    - This works because CVar registration code always loads
 *      GEngine or GConsoleManager nearby
 *
 * 2. FEngineLoop::PreInit pattern:
 *    - After engine creation, there's always:
 *      48 89 05 ?? ?? ?? ??   mov [rip+offset], rax  (store GEngine)
 *    - Followed by engine init sequence
 *
 * 3. Manual offset via env var or TCP command (fallback)
 */

static UEngine*          g_engine_ptr = nullptr;
static std::atomic<bool> g_engine_found{false};

/* Address of the GEngine global variable itself (not the pointer value) */
static uintptr_t         g_engine_global_addr = 0;

/* UWorld pointer -- captured as direct parameter by FExec hooks */
static void*             g_world_ptr = nullptr;

/* -- Exec function ------------------------------------------------- */

/*
 * UObject::ProcessConsoleExec is the virtual function that handles
 * console command execution in UE4/UE5.  Its vtable index varies
 * per engine version (data from UE4SS PDB-verified vtable dumps):
 *
 *   UE 4.27: 71    UE 5.02-5.04: 80
 *   UE 5.00: 78    UE 5.05:      82
 *   UE 5.01: 79    UE 5.06-5.07: 79
 *
 * ProcessConsoleExec is always at ProcessEvent + 3.
 *
 * Signature (x64 MSVC __fastcall):
 *   rcx = this (GEngine)
 *   rdx = const TCHAR* Cmd
 *   r8  = FOutputDevice& Ar
 *   r9  = UObject* Executor (can be NULL)
 */
/* FExec::Exec -- the universal console command router.
 * UEngine inherits FExec via multiple inheritance, so this is in a
 * SECONDARY vtable at some offset within the GEngine object.
 * Different param order from ProcessConsoleExec! */
typedef bool (__fastcall *FExecExecFn)(
    void* this_fexec,     /* rcx = FExec subobject (GEngine + offset) */
    void* world,          /* rdx = UWorld* (NULL ok for most cmds) */
    const wchar_t* cmd,   /* r8  = command string */
    void* output_device   /* r9  = FOutputDevice& */
);

static FExecExecFn g_fexec_exec = NULL;
static uintptr_t   g_fexec_offset = 0;  /* byte offset in GEngine */

/* -- GUObjectArray globals ----------------------------------------- */

/*
 * GUObjectArray (FUObjectArray) is the master UObject registry.
 *
 * FUObjectArray (UE4.21+, all versions):
 *   +0   ObjFirstGCIndex         (int32)
 *   +4   ObjLastNonGCIndex       (int32)
 *   +8   MaxObjectsNotConsideredByGC (int32)
 *   +12  OpenForDisregardForGC   (bool, 1 byte + 3 pad)
 *   +16  ObjObjects (FChunkedFixedUObjectArray, 0x20 bytes, FIXED since 4.21):
 *     +0x00  Objects** (chunk pointer array)
 *     +0x08  PreAllocatedObjects*
 *     +0x10  MaxElements (int32)
 *     +0x14  NumElements (int32)
 *     +0x18  MaxChunks   (int32)
 *     +0x1C  NumChunks   (int32)
 *
 * FUObjectItem size depends on BUILD CONFIG, NOT engine version:
 *
 *   0x10 (16B) -- UE_PACK_FUOBJECT_ITEM=1
 *                 Object* at +0x00 (low bits hold flags)
 *   0x18 (24B) -- Standard Shipping (default)
 *                 Object* at +0x00, then Flags/ClusterRoot/Serial
 *   0x20 (32B) -- Development/Debug OR WITH_VERSE_VM (UE5.4+)
 *                 +0x00 FlagsAndRefCount (uint64)
 *                 +0x08 RemoteId         (8 bytes)
 *                 +0x10 Object*
 *                 +0x18 extra fields
 *
 * ALWAYS detect stride at runtime (Dumper-7 method) -- do not hardcode.
 * Confirmed for StackOBot (Development, UE5.7): stride=0x20, Object at +0x10.
 *
 * Access pattern (same as UE4SS IndexToObject):
 *   chunk_idx  = index >> 16
 *   within_idx = index & 0xFFFF
 *   item_ptr   = Objects[chunk_idx] + within_idx * stride
 *   object     = *(UObject**)(item_ptr + obj_off)
 */

#define GUOBJARRAY_OBJECTS_OFF    16   /* FUObjectArray+0x10: FChunkedFixedUObjectArray.Objects** */
#define GUOBJARRAY_NUMELEMS_OFF   36   /* FUObjectArray+0x24: FChunkedFixedUObjectArray.NumElements */
                                       /* = FUObjectArray+0x10 + FChunkedFixed+0x14 = 16+20 = 36   */
#define FUOBJECTITEM_STRIDE_DEFAULT    32  /* Development/Debug or WITH_VERSE_VM default */
#define FUOBJECTITEM_OBJECT_OFF_DEFAULT 0x08 /* Object* offset -- confirmed UE5.7 Dev     */
#define FUOBJECTARRAY_CHUNK_SHIFT 16   /* NumElementsPerChunk = 64K = 1<<16 */
#define FUOBJECTARRAY_CHUNK_MASK  0xFFFF

static void*              g_guobjectarray = NULL;
static std::atomic<bool>  g_guobjectarray_found{false};
static int                g_fuobjectitem_stride     = FUOBJECTITEM_STRIDE_DEFAULT;
static int                g_fuobjectitem_object_off = FUOBJECTITEM_OBJECT_OFF_DEFAULT;

/* -- FExec multi-hook table ---------------------------------------- */

/*
 * UE4SS hooks FExec on BOTH GEngine (UGameEngine) AND ULocalPlayer.
 * ULocalPlayer::Exec(UWorld* InWorld, ...) receives UWorld as param.
 * We hook every unique FExec vtable found in GUObjectArray.
 *
 * Default FExec vtable offset in both GEngine and ULocalPlayer: 0x28.
 * (Configurable in UE4SS as FExecVTableOffsetInLocalPlayer, default 0x28.)
 */
struct FExecHookEntry {
    uintptr_t   vtable_base;   /* address of the secondary vtable (key) */
    uintptr_t*  slot;          /* &vtable[1] -- the patched slot */
    FExecExecFn original;      /* saved original vtable[1] */
};

static FExecHookEntry     g_fexec_hook_table[64];
static int                g_fexec_hook_count = 0;

/* -- SEH-safe helpers ---------------------------------------------- */

/*
 * MSVC __try/__except cannot coexist with C++ objects that have
 * destructors in the same function (error C2712). These tiny
 * wrapper functions isolate SEH blocks from C++ code.
 */

/* Safely read a pointer value; returns 0 on access violation. */
#pragma warning(push)
#pragma warning(disable: 4733)  /* inline asm / SEH */
static uintptr_t seh_read_ptr(const void* addr)
{
    __try {
        return *(const uintptr_t*)addr;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

/* Safely validate a function pointer by reading its first byte. */
static bool seh_validate_function(void* fn)
{
    if (!fn || (uintptr_t)fn < 0x10000) return false;
    __try {
        uint8_t b0 = *(uint8_t*)fn;
        /* Common x64 function prologues */
        return (b0 == 0x40 || b0 == 0x48 || b0 == 0x4C ||
                b0 == 0x41 || b0 == 0x55 || b0 == 0x53 ||
                b0 == 0x56 || b0 == 0x57 || b0 == 0xE9 ||
                b0 == 0xCC);
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

/* Safely call FExec::Exec (secondary vtable). */
static bool seh_call_fexec(FExecExecFn fn, void* this_fexec,
                            void* world, const wchar_t* cmd, void* ar,
                            bool* out_retval = NULL)
{
    __try {
        bool ret = fn(this_fexec, world, cmd, ar);
        if (out_retval) *out_retval = ret;
        return true;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        if (out_retval) *out_retval = false;
        return false;
    }
}
#pragma warning(pop)

/* -- Dummy FOutputDevice (safe stub for Exec calls) ---------------- */

/*
 * UE5 Exec() takes an FOutputDevice& for logging output.
 * Passing NULL crashes when commands try to log results,
 * which causes the vtable probe to skip the REAL Exec function
 * and latch onto a wrong (no-op) function instead.
 *
 * Solution: build a minimal stub whose vtable is filled with
 * no-op function pointers.  Any virtual call (Serialize, Flush,
 * TearDown, ...) safely does nothing and returns 0.
 */
static volatile LONG g_dummy_ar_called = 0;

static int dummy_ar_fn(void* self, void* a, void* b, void* c)
{
    (void)self; (void)a; (void)b; (void)c;
    InterlockedExchange(&g_dummy_ar_called, 1);
    return 0;
}

static void*  g_dummy_ar_vtable[64];
static struct  DummyAr { void** vptr; char pad[256]; } g_dummy_ar;
static bool    g_dummy_ar_ready = false;

static void* get_output_device()
{
    if (!g_dummy_ar_ready) {
        for (int i = 0; i < 64; i++)
            g_dummy_ar_vtable[i] = (void*)&dummy_ar_fn;
        g_dummy_ar.vptr = g_dummy_ar_vtable;
        memset(g_dummy_ar.pad, 0, sizeof(g_dummy_ar.pad));
        g_dummy_ar_ready = true;
    }
    return &g_dummy_ar;
}

/* -- Camera struct ------------------------------------------------- */

struct CameraState {
    float x, y, z;           /* position (UE5 units = cm) */
    float pitch, yaw, roll;  /* rotation (degrees) */
    float fov;               /* field of view (degrees) */
};

/* Live camera state - written by camera path playback or TCP commands */
static CameraState g_camera = {0, 0, 0, 0, 0, 0, 90.0f};
static std::atomic<bool> g_camera_override{false};

/* -- Game speed ---------------------------------------------------- */

static float g_game_speed = 1.0f;
static std::atomic<bool> g_paused{false};

/* -- Implementation ------------------------------------------------ */

/*
 * Try to find GEngine via string cross-reference method.
 *
 * UE5 always has CVars like "r.HLOD" registered at startup.
 * The CVar registration code contains a LEA to the string
 * and a nearby reference to GConsoleManager or GEngine.
 *
 * More reliably, we search for the wide string L"GEngine"
 * which appears in UE5's FName table initialization and
 * logging code. Code referencing this string will typically
 * load GEngine via mov rax, [rip+offset] within ~200 bytes.
 */
static bool find_gengine_via_string_xref()
{
    ModuleRegion rgn;
    if (!get_main_module(rgn)) {
        bridge_log("ERROR: Failed to get main module info");
        return false;
    }

    bridge_log("Game module: base=0x%p, size=%zu MB",
               rgn.base, rgn.size / (1024 * 1024));

    /*
     * We search for both wide (UTF-16) and ASCII strings.
     * Wide strings are UE5's native TCHAR format (most reliable).
     * ASCII strings cover engine code that uses char* literals
     * (e.g. CALIBRATEMOTION in input processing, present UE4-5.4).
     *
     * Order: most reliable / most unique first.
     */
    struct SearchEntry {
        const wchar_t* wstr;   /* wide string (NULL if ASCII) */
        const char*    astr;   /* ASCII string (NULL if wide) */
        const char*    label;  /* display name for logging */
    };

    const SearchEntry search_entries[] = {
        /* Wide strings (UE5 TCHAR) -- primary */
        {L"ToggleDebugCamera",      NULL, "L\"ToggleDebugCamera\""},
        {L"r.Streaming.PoolSize",   NULL, "L\"r.Streaming.PoolSize\""},
        {L"r.HLOD",                 NULL, "L\"r.HLOD\""},
        {L"GEngine",                NULL, "L\"GEngine\""},
        {L"SetViewLocation",        NULL, "L\"SetViewLocation\""},
        /* ASCII strings (char*) -- UEVR-proven anchors */
        {NULL, "CALIBRATEMOTION",                     "\"CALIBRATEMOTION\""},
        {NULL, "SeamlessTravel FlushLevelStreaming",   "\"SeamlessTravel FlushLevel...\""},
        {NULL, "StaticConstructObject_Internal",       "\"StaticConstructObject_Internal\""},
    };
    const int num_entries = sizeof(search_entries) / sizeof(search_entries[0]);

    int total_strings_found = 0;
    int total_xrefs_found = 0;
    int total_mov_candidates = 0;
    int rejected_out_of_bounds = 0;
    int rejected_null_ptr = 0;
    int rejected_low_addr = 0;
    int rejected_bad_vtable = 0;

    /* Log readable page statistics for diagnostics */
    {
        const auto& ranges = get_readable_ranges(rgn.base, rgn.size);
        size_t total_readable = 0;
        for (const auto& rr : ranges) total_readable += rr.length;
        bridge_log("  Module pages: %zu readable ranges, "
                   "%zu MB readable / %zu MB total",
                   ranges.size(),
                   total_readable / (1024*1024),
                   rgn.size / (1024*1024));
    }

    for (int si = 0; si < num_entries; si++) {
        const SearchEntry& se = search_entries[si];
        const uint8_t* str_addr = NULL;

        /* Yield between entries to avoid starving game threads.
         * Also helps if game is still loading sections. */
        if (si > 0) Sleep(100);

        bridge_log("  [SCAN] Searching %s (%d/%d)...",
                   se.label, si + 1, num_entries);

        if (se.wstr)
            str_addr = find_wstring_in_module(rgn.base, rgn.size, se.wstr);
        else
            str_addr = find_string_in_module(rgn.base, rgn.size, se.astr);

        if (!str_addr) {
            bridge_log("  [SCAN] %s -- not found", se.label);
            continue;
        }

        total_strings_found++;
        bridge_log("  [SCAN] %s at offset +0x%llX",
                   se.label,
                   (unsigned long long)(str_addr - rgn.base));

        /* Find all code references to this string */
        auto xrefs = find_xrefs(rgn.base, rgn.size, (uintptr_t)str_addr);
        total_xrefs_found += (int)xrefs.size();
        bridge_log("  [SCAN]   %zu cross-references found", xrefs.size());

        if (xrefs.empty()) {
            bridge_log("  [SCAN]   No xrefs -- string exists but is "
                       "unreferenced (stripped code?)");
            continue;
        }

        for (const uint8_t* xref : xrefs) {
            bridge_log("  [SCAN]   Xref at +0x%llX, scanning [-256,+512]...",
                       (unsigned long long)(xref - rgn.base));

            /*
             * Search backward and forward from the xref for a
             * MOV reg, [rip+X] pattern that loads a global pointer.
             * GEngine is typically accessed within 512 bytes of
             * any code that uses these strings.
             *
             * Pattern: 48 8B 05/0D/15/1D/25/2D/35/3D ?? ?? ?? ??
             *          (mov r64, [rip+disp32])
             */
            const uint8_t* search_start = xref - 256;
            if (search_start < rgn.base)
                search_start = rgn.base;
            const uint8_t* search_end = xref + 512;
            if (search_end > rgn.base + rgn.size - 7)
                search_end = rgn.base + rgn.size - 7;

            int local_candidates = 0;
            for (const uint8_t* p = search_start; p < search_end; p++) {
                if (p[0] != 0x48 || p[1] != 0x8B) continue;
                /* ModRM: mod=00, rm=101 means [rip+disp32] */
                if ((p[2] & 0xC7) != 0x05) continue;

                total_mov_candidates++;
                local_candidates++;
                uintptr_t resolved = resolve_rip_relative(p, 3, 7);

                /* Validate: the resolved address should be in the
                 * module's data section (.data or .bss), which is
                 * typically in the upper portion of the image. */
                if (resolved < (uintptr_t)rgn.base ||
                    resolved >= (uintptr_t)(rgn.base + rgn.size)) {
                    rejected_out_of_bounds++;
                    continue;
                }

                /* Read the pointer value at that address */
                void* candidate = *(void**)resolved;
                if (!candidate) {
                    rejected_null_ptr++;
                    continue;
                }

                /* Basic validation: the pointer should point to
                 * a valid-looking object (not stack, not too low).
                 * UE5 objects are heap-allocated, typically >0x10000. */
                if ((uintptr_t)candidate < 0x10000) {
                    rejected_low_addr++;
                    continue;
                }

                /* Check if the pointed-to object has a vtable
                 * (first 8 bytes should be a valid pointer too) */
                uintptr_t vtable = seh_read_ptr(candidate);
                if (vtable < 0x10000) {
                    rejected_bad_vtable++;
                    continue;
                }

                /* This looks like a valid engine pointer! */
                g_engine_global_addr = resolved;
                g_engine_ptr = (UEngine*)candidate;
                g_engine_found = true;

                bridge_log("GEngine FOUND via %s xref!",
                           se.label);
                bridge_log("  Global addr: 0x%llX (offset +0x%llX)",
                           (unsigned long long)resolved,
                           (unsigned long long)(resolved - (uintptr_t)rgn.base));
                bridge_log("  Pointer value: 0x%p", candidate);
                bridge_log("  VTable: 0x%llX", (unsigned long long)vtable);
                bridge_log("  Scan stats: %d strings, %d xrefs, "
                           "%d MOV candidates tested",
                           total_strings_found, total_xrefs_found,
                           total_mov_candidates);

                return true;
            }

            if (local_candidates == 0) {
                bridge_log("  [SCAN]   No MOV [rip+X] instructions "
                           "in search window");
            }
        }
    }

    /* All methods exhausted -- dump diagnostic summary */
    bridge_log("GEngine scan FAILED. Diagnostic summary:");
    bridge_log("  Strings found:    %d / %d",
               total_strings_found,
               num_entries);
    bridge_log("  Total xrefs:      %d", total_xrefs_found);
    bridge_log("  MOV candidates:   %d", total_mov_candidates);
    bridge_log("  Rejected reasons:");
    bridge_log("    out-of-bounds:  %d", rejected_out_of_bounds);
    bridge_log("    null pointer:   %d", rejected_null_ptr);
    bridge_log("    low address:    %d", rejected_low_addr);
    bridge_log("    bad vtable:     %d", rejected_bad_vtable);
    if (total_strings_found == 0) {
        bridge_log("  HINT: No search strings found. Game may have "
                   "stripped string data. Try manual offset.");
    } else if (total_xrefs_found == 0) {
        bridge_log("  HINT: Strings exist but no code references them. "
                   "Game may use obfuscated string loading.");
    } else if (total_mov_candidates == 0) {
        bridge_log("  HINT: Xrefs found but no MOV [rip+X] nearby. "
                   "GEngine access may use a different pattern.");
    } else {
        bridge_log("  HINT: Candidates found but none passed validation. "
                   "GEngine may not be initialized yet (try later) "
                   "or pointer layout differs from expected.");
    }

    return false;
}

/*
 * Try to find GEngine via manual offset (env var or TCP command).
 */
static bool find_gengine_via_offset(uintptr_t offset)
{
    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;

    if (offset >= rgn.size) {
        bridge_log("ERROR: Offset 0x%llX exceeds module size",
                   (unsigned long long)offset);
        return false;
    }

    uintptr_t addr = (uintptr_t)rgn.base + offset;
    void* candidate = *(void**)addr;

    if (!candidate) {
        bridge_log("WARNING: Offset 0x%llX yielded NULL pointer",
                   (unsigned long long)offset);
        return false;
    }

    g_engine_global_addr = addr;
    g_engine_ptr = (UEngine*)candidate;
    g_engine_found = true;

    bridge_log("GEngine set via offset 0x%llX -> 0x%p",
               (unsigned long long)offset, candidate);
    return true;
}

static bool find_gengine_via_guobjectarray();  /* forward decl -- defined after GUA section */

/*
 * Master GEngine finder -- dual method with cross-validation.
 *
 * Method 0: env var / TCP override
 * Method 1: PE export "?GEngine@@3PEAVUEngine@@EA" (fastest, many Shipping builds)
 * Method A: string xref (gives g_engine_global_addr)
 * Method B: GUObjectArray structural scan (UE4SS approach, if GUA found)
 *
 * If both A and B succeed and agree  -> confirmed, high confidence.
 * If both succeed but differ         -> prefer A (has global addr).
 * If only one of A/B succeeds        -> use it as-is.
 */
static bool find_gengine()
{
    /* Method 0: env var / TCP override (highest priority) */
    const char* env_offset = getenv("CAPTUREAI_GENGINE_OFFSET");
    if (env_offset) {
        uintptr_t offset = strtoull(env_offset, NULL, 16);
        if (find_gengine_via_offset(offset))
            return true;
    }

    /* Method 1: PE export symbol -- fastest, works for many Shipping builds.
     * The export IS the global variable (UEngine**), so dereference once. */
    {
        void** exp_ptr = (void**)GetProcAddress(
            GetModuleHandleA(NULL), "?GEngine@@3PEAVUEngine@@EA");
        if (exp_ptr) {
            void* candidate = seh_read_ptr(exp_ptr) ? *exp_ptr : NULL;
            if (candidate && (uintptr_t)candidate > 0x10000 &&
                (uintptr_t)candidate < 0x7F0000000000ULL)
            {
                uintptr_t vtable = seh_read_ptr(candidate);
                if (vtable > 0x10000) {
                    g_engine_ptr          = (UEngine*)candidate;
                    g_engine_found        = true;
                    g_engine_global_addr  = (uintptr_t)exp_ptr;
                    bridge_log("GEngine via export: 0x%p (global=0x%llX)",
                               candidate, (unsigned long long)exp_ptr);
                    return true;
                }
            }
            bridge_log("GEngine export found but pointer invalid, continue");
        } else {
            bridge_log("GEngine export not found, trying scan methods");
        }
    }

    /* Method A: string xref scan */
    bridge_log("GEngine Method A: string xref scan...");
    bool a_ok = find_gengine_via_string_xref();
    UEngine* a_result = a_ok ? g_engine_ptr : NULL;

    /* Method B: GUObjectArray structural scan (only if GUA already found) */
    bool b_ok = false;
    UEngine* b_result = NULL;
    if (g_guobjectarray_found) {
        bridge_log("GEngine Method B: GUObjectArray structural scan...");
        /* Temporarily clear so find_gengine_via_guobjectarray can write */
        UEngine* saved_a = g_engine_ptr;
        uintptr_t saved_addr = g_engine_global_addr;
        bool saved_found = g_engine_found;
        g_engine_ptr = NULL; g_engine_found = false; g_engine_global_addr = 0;

        b_ok = find_gengine_via_guobjectarray();
        b_result = b_ok ? g_engine_ptr : NULL;

        /* Restore Method A state as base */
        g_engine_ptr   = saved_a;
        g_engine_found = saved_found;
        g_engine_global_addr = saved_addr;
    } else {
        bridge_log("GEngine Method B: skipped (GUObjectArray not yet found)");
    }

    /* Cross-validate */
    if (a_ok && b_ok) {
        if (a_result == b_result) {
            bridge_log("GEngine CONFIRMED by both methods: 0x%p", a_result);
        } else {
            bridge_log("GEngine WARNING: Method A=0x%p vs Method B=0x%p -- "
                       "preferring Method A (has global addr)",
                       a_result, b_result);
        }
        /* Keep Method A result (has g_engine_global_addr) */
        g_engine_ptr = a_result;
        g_engine_found = true;
        return true;
    }

    if (a_ok) {
        bridge_log("GEngine found via Method A only (GUObjectArray unavailable)");
        return true;
    }

    if (b_ok) {
        bridge_log("GEngine found via Method B (GUObjectArray) -- "
                   "string xref failed");
        g_engine_ptr   = b_result;
        g_engine_found = true;
        g_engine_global_addr = 0;  /* not available via GUA scan */
        return true;
    }

    bridge_log("WARNING: GEngine not found by either method. "
               "Use __bridge_set_offset <hex> via TCP, "
               "or set CAPTUREAI_GENGINE_OFFSET env var.");
    return false;
}

/* -- FExec secondary vtable finder --------------------------------- */

/*
 * UEngine inherits from both UObject and FExec (multiple inheritance).
 * The FExec vtable is a SECONDARY vtable at some offset in the object:
 *
 *   GEngine layout (x64):
 *     offset 0:   UObject vptr (primary, 80+ entries)
 *     offset 8+:  UObject members (FName, UClass*, etc.)
 *     offset N:   FExec vptr (secondary, 5 entries: dtor+Exec+3)
 *
 * FExec::Exec is the UNIVERSAL console command router that handles
 * CVars, stat, showflag, ToggleDebugCamera, and all other commands.
 * ProcessConsoleExec (primary vtable) only handles UFUNCTION(Exec).
 *
 * UEngine inherits: public UObject, public FExec  (multiple inheritance).
 * FExec has 5 virtual functions: ~FExec, Exec, Exec_Runtime, Exec_Dev,
 * Exec_Editor.  The FExec subobject vptr sits right after UObject's data.
 *
 * UObjectBase layout (x64, standard FName=8 bytes):
 *   +0   vptr(8) +8 ObjectFlags(4) +12 InternalIndex(4)
 *   +16  ClassPrivate(8) +24 NamePrivate(8) +32 OuterPrivate(8)
 *   sizeof(UObjectBase) = 40
 * UObject adds no data members -> sizeof(UObject) = 40
 * FExec vptr at offset 40 (0x28).
 *
 * WITH_CASE_PRESERVING_NAME (editor builds) makes FName=12 bytes,
 * pushing sizeof(UObject) to 48 -> FExec vptr at 48 (0x30).
 *
 * Strategy: try known offsets 40 and 48 first, then scan.
 */
static bool validate_function_ptr(void* fn);  /* forward decl */
/* Try to find UE version string in the game module.
 * Looks for "++UE5+Release-X.Y" or "+Release-X.Y" ASCII pattern. */
static void detect_ue_version_string()
{
    ModuleRegion rgn;
    if (!get_main_module(rgn)) return;

    const char* pat = "+Release-";
    size_t pat_len = 9;

    /* Use find_string_in_module (VirtualQuery-safe) */
    const uint8_t* hit = find_string_in_module(
        rgn.base, rgn.size, pat);
    if (!hit) {
        bridge_log("  UE Version: not found in module");
        return;
    }
    const char* ver = (const char*)hit + pat_len;
    if (ver[0] >= '4' && ver[0] <= '9' && ver[1] == '.') {
        char buf[64];
        int i = 0;
        while (i < 30 && ver[i] >= ' ' && ver[i] <= 'z')
            buf[i] = ver[i], i++;
        buf[i] = '\0';
        bridge_log("  UE Version detected: %s", buf);
    } else {
        bridge_log("  UE Version: pattern found but no version number");
    }
}

/* Check if offset `off` in the GEngine object holds an FExec vtable.
 * FExec has 5 virtuals: dtor, Exec, Exec_Runtime, Exec_Dev, Exec_Editor.
 * MSVC secondary vtable: all 5 entries are adjustor thunks -> valid fns.
 * We require [0],[1] valid and NOT equal to the primary vtable. */
static bool try_fexec_at_offset(uint8_t* obj, int off,
                                uintptr_t mod_start, uintptr_t mod_end,
                                uintptr_t primary_vptr)
{
    uintptr_t vptr = seh_read_ptr(obj + off);
    if (vptr < mod_start || vptr >= mod_end) return false;
    if (vptr == primary_vptr) return false;   /* skip primary vtable */

    void* fn0 = (void*)seh_read_ptr((void*)vptr);       /* ~FExec */
    void* fn1 = (void*)seh_read_ptr((void*)(vptr + 8)); /* Exec  */
    if (!validate_function_ptr(fn0) || !validate_function_ptr(fn1))
        return false;

    /* Extra validation: FExec has 5 entries, check [2]-[4] too */
    int valid_count = 2;
    for (int i = 2; i < 8; i++) {
        void* fn = (void*)seh_read_ptr((void*)(vptr + i * 8));
        if (validate_function_ptr(fn))
            valid_count++;
        else
            break;
    }

    bridge_log("  obj+%d: vptr=0x%llX, %d valid entries",
               off, (unsigned long long)vptr, valid_count);

    /* FExec should have exactly 5 entries (or 3 in shipping without
     * Exec_Dev/Exec_Editor).  Accept 3-8 entries as FExec candidate.
     * The primary UObject vtable has 80+ entries, so this filters it. */
    if (valid_count > 20) {
        bridge_log("    -> too many entries (%d), likely primary vtable "
                   "duplicate, skip", valid_count);
        return false;
    }

    /* Found FExec vtable */
    g_fexec_offset = (uintptr_t)off;
    g_fexec_exec = (FExecExecFn)fn1;

    bridge_log("  >>> FExec vtable found at obj+%d <<<", off);
    bridge_log("    vptr       = 0x%llX", (unsigned long long)vptr);
    bridge_log("    [0] ~FExec = 0x%p", fn0);
    bridge_log("    [1] Exec   = 0x%p", fn1);
    for (int i = 2; i < valid_count && i < 6; i++) {
        void* fn = (void*)seh_read_ptr((void*)(vptr + i * 8));
        const char* name = (i == 2) ? "Exec_Runtime" :
                           (i == 3) ? "Exec_Dev" :
                           (i == 4) ? "Exec_Editor" : "???";
        bridge_log("    [%d] %-13s= 0x%p", i, name, fn);
    }
    bridge_log("    this_adj   = GEngine+%d (0x%p)",
               off, (void*)(obj + off));
    return true;
}

static bool find_fexec_vtable()
{
    uint8_t* obj = (uint8_t*)g_engine_ptr;
    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;

    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end = mod_start + rgn.size;

    /* Detect UE version for diagnostics */
    detect_ue_version_string();

    bridge_log("=== GEngine FExec Lookup ===");
    bridge_log("  GEngine ptr: 0x%p", g_engine_ptr);
    bridge_log("  Module: 0x%llX - 0x%llX (%zu MB)",
               (unsigned long long)mod_start,
               (unsigned long long)mod_end,
               rgn.size / (1024*1024));

    uintptr_t primary_vptr = seh_read_ptr(obj);
    bridge_log("  Primary vptr (obj+0): 0x%llX",
               (unsigned long long)primary_vptr);

    /*
     * Strategy 1: Try known offsets from UE5 headers.
     *   offset 40 = sizeof(UObject) with FName=8 (standard)
     *   offset 48 = sizeof(UObject) with FName=12 (CASE_PRESERVING)
     */
    bridge_log("  --- Trying known offsets ---");
    static const int known_offsets[] = {40, 48};
    for (int off : known_offsets) {
        bridge_log("  Trying obj+%d...", off);
        if (try_fexec_at_offset(obj, off, mod_start, mod_end,
                                primary_vptr))
            return true;
    }

    /*
     * Strategy 2: Scan all 8-byte-aligned offsets [8..512].
     * Find the first secondary vtable (not primary, 3-20 entries).
     */
    bridge_log("  --- Known offsets failed, scanning [8..512] ---");
    for (int off = 8; off <= 512; off += 8) {
        if (off == 40 || off == 48) continue;  /* already tried */
        if (try_fexec_at_offset(obj, off, mod_start, mod_end,
                                primary_vptr))
            return true;
    }

    bridge_log("ERROR: FExec secondary vtable not found!");
    bridge_log("  This may indicate a non-standard UObject layout.");
    return false;
}

/* -- GUObjectArray finder ------------------------------------------ */
/*
 * UWorld is NOT found by static scan. It is captured as a direct
 * parameter of ULocalPlayer::Exec(UWorld* InWorld, cmd, ar) by the
 * FExec hooks installed below. This is the UE4SS approach.
 */

/*
 * validate_guobjectarray() -- verbose structural validation of a candidate.
 *
 * Layout checked (FUObjectArray per user-confirmed UE5 struct):
 *   +0x10: TUObjectArray.Objects**        (GUOBJARRAY_OBJECTS_OFF = 16)
 *   +0x24: TUObjectArray.NumElements      (GUOBJARRAY_NUMELEMS_OFF = 36)
 *          = FUObjectArray+0x10+TUObjectArray.NumElements(+0x14)
 *          = 0x10 + 0x14 = 0x24 = 36 (TUObjectArray has PreAllocatedObjects* at +0x08)
 *
 * First FUObjectItem Object* probed at both +0x10 (UE5.7+) and +0x00 (classic).
 */
static bool validate_guobjectarray(void* candidate)
{
    if (!candidate || (uintptr_t)candidate < 0x10000) return false;

    uint8_t* p = (uint8_t*)candidate;

    /* Dump the first 64 bytes of the candidate for debugging */
    bridge_log("  GUA candidate=0x%p: "
               "[+0x00]=%llX [+0x08]=%llX [+0x10]=%llX [+0x18]=%llX "
               "[+0x20]=%llX [+0x24]=%llX [+0x28]=%llX [+0x2C]=%llX",
               candidate,
               (unsigned long long)seh_read_ptr(p + 0x00),
               (unsigned long long)seh_read_ptr(p + 0x08),
               (unsigned long long)seh_read_ptr(p + 0x10),
               (unsigned long long)seh_read_ptr(p + 0x18),
               (unsigned long long)seh_read_ptr(p + 0x20),
               (unsigned long long)seh_read_ptr(p + 0x24),
               (unsigned long long)seh_read_ptr(p + 0x28),
               (unsigned long long)seh_read_ptr(p + 0x2C));

    /* TUObjectArray.NumElements at FUObjectArray+0x24 */
    int32_t num_elems = 0;
    __try { num_elems = *(int32_t*)(p + GUOBJARRAY_NUMELEMS_OFF); }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        bridge_log("  GUA: NumElements read fault");
        return false;
    }
    bridge_log("  GUA: NumElements@+0x%X=%d, MaxElements@+0x%X=%d, "
               "NumChunks@+0x%X=%d",
               GUOBJARRAY_NUMELEMS_OFF, num_elems,
               GUOBJARRAY_NUMELEMS_OFF - 4,
               (int)seh_read_ptr(p + GUOBJARRAY_NUMELEMS_OFF - 4) & 0xFFFFFFFF,
               GUOBJARRAY_NUMELEMS_OFF + 8,
               (int)seh_read_ptr(p + GUOBJARRAY_NUMELEMS_OFF + 8) & 0xFFFFFFFF);

    if (num_elems < 1000 || num_elems > 5000000) {
        bridge_log("  GUA FAIL: NumElements=%d not in [1000, 5M]", num_elems);
        return false;
    }

    /* TUObjectArray.Objects** at FUObjectArray+0x10 */
    uintptr_t chunks_ptr = seh_read_ptr(p + GUOBJARRAY_OBJECTS_OFF);
    bridge_log("  GUA: Objects**=0x%llX", (unsigned long long)chunks_ptr);
    if (chunks_ptr < 0x10000 || chunks_ptr >= 0x800000000000ULL) {
        bridge_log("  GUA FAIL: Objects** out of valid range");
        return false;
    }

    /* TUObjectArray.PreAllocatedObjects* at FUObjectArray+0x18 (debug only) */
    uintptr_t prealloc = seh_read_ptr(p + 0x18);
    bridge_log("  GUA: PreAllocatedObjects*=0x%llX", (unsigned long long)prealloc);

    /* Objects[0] = pointer to first chunk */
    uintptr_t chunk0 = seh_read_ptr((void*)chunks_ptr);
    bridge_log("  GUA: chunk[0]=0x%llX", (unsigned long long)chunk0);
    if (chunk0 < 0x10000 || chunk0 >= 0x800000000000ULL) {
        bridge_log("  GUA FAIL: chunk[0] invalid");
        return false;
    }

    /* Probe Object* across multiple items and both known offsets.
     * Index 0 is often a null/sentinel entry in UE5 -- do NOT require it valid.
     * For each (stride, obj_off) in known configs, scan items 0..7 and count
     * valid-looking pointers.  Accept if any config scores >= 2 hits. */
    static const struct { int stride; int obj_off; } val_cfgs[] = {
        {32, 0x08},   /* WITH_VERSE_VM Dev: WeakHandle(8)+Object*(8)  */
        {32, 0x10},   /* Alt 32B layout: Object* at higher offset      */
        {24, 0x00},   /* Standard Shipping: Object*(8)+Flags(4)+...    */
        {16, 0x00},   /* Packed (UE_PACK_FUOBJECT_ITEM)                */
    };
    const int N_VAL_ITEMS = 8;
    bool any_ok = false;

    for (int ci = 0; ci < 4; ci++) {
        int s   = val_cfgs[ci].stride;
        int off = val_cfgs[ci].obj_off;
        int hits = 0;
        for (int i = 0; i < N_VAL_ITEMS; i++) {
            uintptr_t ptr = seh_read_ptr(
                (void*)(chunk0 + (uintptr_t)i * s + off));
            if (s == 16) ptr &= ~(uintptr_t)0x7;
            if (ptr >= 0x10000 && ptr < 0x800000000000ULL) hits++;
        }
        bridge_log("  GUA probe: stride=%d off=0x%02X hits=%d/%d",
                   s, off, hits, N_VAL_ITEMS);
        if (hits >= 2) any_ok = true;
    }

    if (!any_ok) {
        bridge_log("  GUA FAIL: no (stride, obj_off) config gives >=2 valid "
                   "Object* in first %d items", N_VAL_ITEMS);
        return false;
    }

    bridge_log("  GUA OK: NumElements=%d Objects**=0x%llX chunk[0]=0x%llX",
               num_elems, (unsigned long long)chunks_ptr,
               (unsigned long long)chunk0);
    return true;
}

/*
 * log_guobjectarray_details() -- verbose dump for cross-checking with game.
 *
 * Prints the FUObjectArray header fields (ObjFirstGCIndex, NumElements, etc.),
 * chunk 0 address, and a sample of object pointers near the tail of the array.
 * Call this immediately after find_guobjectarray() succeeds so the user can
 * compare the bridge's view with the game's own BeginPlay log output.
 */
static void log_guobjectarray_details()
{
    if (!g_guobjectarray) return;
    uint8_t* p = (uint8_t*)g_guobjectarray;

    /* FUObjectArray header fields (UE4.21+ fixed layout) */
    int32_t first_gc_idx    = 0;
    int32_t last_nongc_idx  = 0;
    int32_t max_not_gc      = 0;
    int32_t max_elems       = 0;
    int32_t num_elems       = 0;
    int32_t max_chunks      = 0;
    int32_t num_chunks      = 0;
    uintptr_t chunks_ptr    = 0;
    uintptr_t prealloc_ptr  = 0;

    __try {
        first_gc_idx   = *(int32_t*)(p + 0x00);
        last_nongc_idx = *(int32_t*)(p + 0x04);
        max_not_gc     = *(int32_t*)(p + 0x08);
        /* +0x0C: OpenForDisregardForGC (bool, skip) */
        chunks_ptr     = *(uintptr_t*)(p + 0x10);
        prealloc_ptr   = *(uintptr_t*)(p + 0x18);
        max_elems      = *(int32_t*)(p + 0x20);
        num_elems      = *(int32_t*)(p + 0x24);
        max_chunks     = *(int32_t*)(p + 0x28);
        num_chunks     = *(int32_t*)(p + 0x2C);
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        bridge_log("  GUA details: read fault");
        return;
    }

    bridge_log("  GUA details @ 0x%p:", p);
    bridge_log("    ObjFirstGCIndex=%d ObjLastNonGCIndex=%d MaxNotGC=%d",
               first_gc_idx, last_nongc_idx, max_not_gc);
    bridge_log("    Objects**=0x%llX PreAllocated*=0x%llX",
               (unsigned long long)chunks_ptr, (unsigned long long)prealloc_ptr);
    bridge_log("    MaxElements=%d NumElements=%d MaxChunks=%d NumChunks=%d",
               max_elems, num_elems, max_chunks, num_chunks);

    /* Chunk 0 address */
    uintptr_t chunk0 = seh_read_ptr((void*)chunks_ptr);
    bridge_log("    Chunk[0]=0x%llX", (unsigned long long)chunk0);

    if (!chunk0) return;

    /* Sample objects near the tail (highest density -- recently allocated).
     * Print index, raw item bytes, and the Object* for each of 5 items.
     * Use the current detected stride (may still be default). */
    int s   = g_fuobjectitem_stride;
    int off = g_fuobjectitem_object_off;
    int start_idx = (num_elems > 5) ? num_elems - 5 : 0;
    bridge_log("    Sample objects [%d..%d] stride=%d off=0x%02X:",
               start_idx, start_idx + 4, s, off);

    for (int i = 0; i < 5; i++) {
        int32_t idx = start_idx + i;
        if (idx >= 65536) break;  /* stay within chunk 0 bounds */
        uintptr_t item_addr = chunk0 + (uintptr_t)idx * s;
        uintptr_t obj_ptr   = seh_read_ptr((void*)(item_addr + off));
        uintptr_t raw_w0    = seh_read_ptr((void*)(item_addr + 0));
        bridge_log("      [%d] item=0x%llX raw0=0x%llX obj*=0x%llX",
                   idx,
                   (unsigned long long)item_addr,
                   (unsigned long long)raw_w0,
                   (unsigned long long)obj_ptr);
    }

    /* Also sample a few early permanent objects (idx 1..5) for comparison */
    bridge_log("    Sample objects [1..5] (early permanent):");
    for (int idx = 1; idx <= 5; idx++) {
        uintptr_t item_addr = chunk0 + (uintptr_t)idx * s;
        uintptr_t obj_ptr   = seh_read_ptr((void*)(item_addr + off));
        uintptr_t raw_w0    = seh_read_ptr((void*)(item_addr + 0));
        bridge_log("      [%d] raw0=0x%llX obj*=0x%llX",
                   idx,
                   (unsigned long long)raw_w0,
                   (unsigned long long)obj_ptr);
    }
}

/*
 * Get object at index i. Returns UObjectBase* or NULL.
 * Implements UE4SS IndexToObject() chunk arithmetic.
 */
static void* guobjectarray_get(int32_t index)
{
    if (!g_guobjectarray || index < 0) return NULL;

    uint8_t* arr = (uint8_t*)g_guobjectarray;
    uintptr_t chunks_ptr = seh_read_ptr(arr + GUOBJARRAY_OBJECTS_OFF);
    if (!chunks_ptr) return NULL;

    int32_t chunk_idx   = (uint32_t)index >> FUOBJECTARRAY_CHUNK_SHIFT;
    int32_t within_idx  = (uint32_t)index &  FUOBJECTARRAY_CHUNK_MASK;

    uintptr_t chunk = seh_read_ptr(
        (void*)(chunks_ptr + (uintptr_t)chunk_idx * 8));
    if (!chunk) return NULL;

    /* stride/obj_off detected at runtime by detect_fuobjectitem_stride() */
    uintptr_t item_addr = chunk + (uintptr_t)within_idx * g_fuobjectitem_stride;
    return (void*)seh_read_ptr((void*)(item_addr + g_fuobjectitem_object_off));
}

/*
 * Detect sizeof(FUObjectItem) and Object* offset at runtime (Dumper-7 method).
 *
 * FUObjectItem size is determined by BUILD CONFIG, not engine version:
 *   0x10 (16B) -- UE_PACK_FUOBJECT_ITEM: Object* low bits hold flags
 *   0x18 (24B) -- Standard Shipping: Object* at +0x00
 *   0x20 (32B) -- Development/Debug OR WITH_VERSE_VM: Object* at +0x10
 *
 * Detection: chunk 0 holds 65536 FUObjectItem structs consecutively.
 * For each (stride, obj_off) candidate, scan items[0..N-1].Object and
 * count how many look like valid heap pointers (non-null, readable vtable).
 * The winning combo has the highest score across 30 sampled items.
 * Cross-validate against g_engine_ptr at GEngine.InternalIndex when available.
 *
 * Must be called after g_guobjectarray is set. g_engine_ptr is optional
 * (used for cross-validation only -- gives definitive confirmation).
 */
static void detect_fuobjectitem_stride()
{
    if (!g_guobjectarray) return;

    /* Get chunk 0 base */
    uintptr_t chunks_ptr = seh_read_ptr(
        (uint8_t*)g_guobjectarray + GUOBJARRAY_OBJECTS_OFF);
    uintptr_t chunk0 = seh_read_ptr((void*)chunks_ptr);
    if (!chunk0) {
        bridge_log("  FUObjectItem detect: chunk0 not readable");
        return;
    }

    /*
     * Known (stride, obj_off) configs:
     *   (32, 0x08) -- WITH_VERSE_VM Dev: WeakHandle(8)+Object*(8)+Flags(4)+...
     *                 [StackOBot UE5.7 Dev confirmed: sizeof=32, raw+0x08=Object*]
     *   (32, 0x10) -- Alt 32B layout (Object* shifted further)
     *   (24, 0x00) -- Standard Shipping: Object*(8)+Flags(4)+ClusterRoot(4)+Serial(4)+Pad(4)
     *   (16, 0x00) -- Packed (UE_PACK_FUOBJECT_ITEM): Object* in low bits of first qword
     */
    static const struct { int stride; int obj_off; } configs[] = {
        {32, 0x08},
        {32, 0x10},
        {24, 0x00},
        {16, 0x00},
    };
    const int N_CONFIGS = 4;
    const int N_SAMPLE  = 30;  /* items to sample from chunk 0 */

    /* Optional: GEngine.InternalIndex for cross-validation */
    int32_t ge_idx = 0;
    if (g_engine_ptr) {
        __try { ge_idx = *(int32_t*)((uint8_t*)g_engine_ptr + 0x0C); }
        __except(EXCEPTION_EXECUTE_HANDLER) { ge_idx = 0; }
        if (ge_idx <= 0 || ge_idx >= 2000000) ge_idx = 0;
    }

    int best_score   = -1;
    int best_stride  = g_fuobjectitem_stride;
    int best_obj_off = g_fuobjectitem_object_off;

    /* Choose sample start: items 0..N are mostly null (ObjFirstGCIndex is
     * typically 28000+, but many early slots are still empty).
     * Sample near GEngine (ge_idx) if known, else near array midpoint.
     * Items near num_elems-1 are the densest (recently allocated).
     * Read NumElements directly (guobjectarray_num_elements defined later). */
    int32_t num_elems_now = 0;
    __try {
        num_elems_now = *(int32_t*)(
            (uint8_t*)g_guobjectarray + GUOBJARRAY_NUMELEMS_OFF);
    }
    __except(EXCEPTION_EXECUTE_HANDLER) { num_elems_now = 0; }
    int32_t sample_start = 0;
    if (ge_idx > N_SAMPLE / 2)
        sample_start = ge_idx - N_SAMPLE / 2;
    else if (num_elems_now > N_SAMPLE * 2)
        sample_start = num_elems_now - N_SAMPLE;  /* tail: densest region */

    bridge_log("  FUObjectItem detect: chunk0=0x%p ge_idx=%d "
               "sample_start=%d num=%d",
               (void*)chunk0, ge_idx, sample_start, num_elems_now);

    for (int ci = 0; ci < N_CONFIGS; ci++) {
        int s   = configs[ci].stride;
        int off = configs[ci].obj_off;

        /* Score: count items[sample_start..sample_start+N-1] with valid Object*
         * Only sample within chunk 0 (idx < 65536) to keep arithmetic simple. */
        int score = 0;
        for (int i = 0; i < N_SAMPLE; i++) {
            int32_t idx = sample_start + i;
            if (idx >= 65536) break;  /* stay within chunk 0 */
            uintptr_t ptr = seh_read_ptr(
                (void*)(chunk0 + (uintptr_t)idx * s + off));
            /* packed: mask out low 3 tag bits before checking */
            if (s == 16) ptr &= ~(uintptr_t)0x7;
            if (ptr < 0x10000) continue;
            uintptr_t vtbl = seh_read_ptr((void*)ptr);
            if (vtbl >= 0x10000) score++;
        }

        /* Cross-validate with GEngine at its known InternalIndex */
        bool engine_ok = false;
        if (ge_idx > 0) {
            uintptr_t probe = seh_read_ptr(
                (void*)(chunk0 + (uintptr_t)ge_idx * s + off));
            if (s == 16) probe &= ~(uintptr_t)0x7;
            engine_ok = (probe == (uintptr_t)g_engine_ptr);
        }

        bridge_log("  [stride=%d off=0x%02X] score=%d/%d engine_match=%d",
                   s, off, score, N_SAMPLE, (int)engine_ok);

        /* Definitive: score > half AND engine confirmed */
        if (engine_ok && score > N_SAMPLE / 2) {
            g_fuobjectitem_stride     = s;
            g_fuobjectitem_object_off = off;
            bridge_log("  FUObjectItem CONFIRMED: stride=%d object_off=0x%02X "
                       "(score=%d + engine cross-validated)",
                       s, off, score);
            return;
        }

        if (score > best_score) {
            best_score   = score;
            best_stride  = s;
            best_obj_off = off;
        }
    }

    /* Heuristic fallback: take highest score if decent.
     * Threshold N/5 = 6/30 -- leaves room for sparse ranges while
     * still rejecting noise (wrong config scores ~1-2). */
    if (best_score >= N_SAMPLE / 5) {
        g_fuobjectitem_stride     = best_stride;
        g_fuobjectitem_object_off = best_obj_off;
        bridge_log("  FUObjectItem HEURISTIC: stride=%d object_off=0x%02X "
                   "(score=%d -- no engine cross-validation)",
                   best_stride, best_obj_off, best_score);
    } else {
        bridge_log("  FUObjectItem detect FAILED (best score=%d/%d) "
                   "-- keeping stride=%d off=0x%02X",
                   best_score, N_SAMPLE,
                   g_fuobjectitem_stride, g_fuobjectitem_object_off);
    }
}

static int32_t guobjectarray_num_elements()
{
    if (!g_guobjectarray) return 0;
    int32_t n = 0;
    __try {
        n = *(int32_t*)((uint8_t*)g_guobjectarray + GUOBJARRAY_NUMELEMS_OFF);
    }
    __except(EXCEPTION_EXECUTE_HANDLER) { n = 0; }
    return n;
}

/*
 * GEngine finder via GUObjectArray structural scan (UE4SS approach).
 *
 * UGameEngine has the largest primary vtable of any FExec implementor:
 * typically 80-120 entries vs ULocalPlayer ~20-40, others <= 30.
 * We scan the first 1000 objects (GEngine is always created early),
 * find every FExec implementor (secondary vtable at +0x28 with 3-8 entries),
 * and pick the one with the most primary vtable entries.
 *
 * Requires: GUObjectArray already found.
 * Does NOT require FName::ToString -- purely structural.
 */
static bool find_gengine_via_guobjectarray()
{
    if (!g_guobjectarray_found || !g_guobjectarray) return false;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;

    int32_t num_elems  = guobjectarray_num_elements();
    int32_t scan_limit = (num_elems < 1000) ? num_elems : 1000;

    bridge_log("  GUA GEngine scan: first %d objects", scan_limit);

    void*     best_obj    = NULL;
    int       best_vcnt   = 0;
    uintptr_t best_vptr   = 0;

    for (int32_t i = 0; i < scan_limit; i++) {
        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x7F0000000000ULL) continue;

        /* Primary vtable must be in module */
        uintptr_t vptr = seh_read_ptr(obj);
        if (vptr < mod_start || vptr >= mod_end) continue;

        /* Find FExec secondary vtable. Try both known offsets:
         *   +0x28 = standard UE5 (FName = 8 bytes, sizeof(UObjectBase)=40)
         *   +0x30 = WITH_CASE_PRESERVING_NAME (FName = 12 bytes, sizeof=48)
         * This function runs before find_fexec_vtable(), so g_fexec_offset=0. */
        static const uintptr_t fexec_candidates[] = { 0x28, 0x30 };
        uintptr_t fexec_vptr = 0;
        for (int ci = 0; ci < 2; ci++) {
            uintptr_t candidate = seh_read_ptr((uint8_t*)obj + fexec_candidates[ci]);
            if (candidate >= mod_start && candidate < mod_end && candidate != vptr) {
                void* f0 = (void*)seh_read_ptr((void*)candidate);
                void* f1 = (void*)seh_read_ptr((void*)(candidate + 8));
                if (validate_function_ptr(f0) && validate_function_ptr(f1)) {
                    fexec_vptr = candidate;
                    break;
                }
            }
        }
        if (!fexec_vptr) continue;

        /* Validate FExec vtable has 3-8 entries */
        void* fn0 = (void*)seh_read_ptr((void*)fexec_vptr);
        void* fn1 = (void*)seh_read_ptr((void*)(fexec_vptr + 8));
        if (!validate_function_ptr(fn0) || !validate_function_ptr(fn1)) continue;

        int fexec_cnt = 2;
        for (int vi = 2; vi <= 8; vi++) {
            void* fn = (void*)seh_read_ptr((void*)(fexec_vptr + vi * 8));
            if (!validate_function_ptr(fn)) break;
            fexec_cnt++;
        }
        if (fexec_cnt < 2 || fexec_cnt > 8) continue;

        /* Count primary vtable entries -- GEngine wins with 80+ */
        int vcnt = 0;
        for (int vi = 0; vi < 256; vi++) {
            void* fn = (void*)seh_read_ptr((void*)(vptr + vi * 8));
            if (!validate_function_ptr(fn)) break;
            vcnt++;
        }

        if (vcnt > best_vcnt) {
            best_vcnt = vcnt;
            best_obj  = obj;
            best_vptr = vptr;
        }
    }

    /* UGameEngine requires at least 50 primary vtable entries.
     * This filters out ULocalPlayer, UNetDriver, and similar. */
    if (!best_obj || best_vcnt < 50) {
        bridge_log("  GUA GEngine scan: no candidate "
                   "(best=%d vtable entries, need >=50)", best_vcnt);
        return false;
    }

    bridge_log("  GUA GEngine found: 0x%p (vptr=0x%llX, %d vtable entries)",
               best_obj, (unsigned long long)best_vptr, best_vcnt);

    g_engine_ptr   = (UEngine*)best_obj;
    g_engine_found = true;
    /* g_engine_global_addr not available via this method */
    return true;
}

/* ---- FName Pool Utilities ---------------------------------------- */

/*
 * FNamePool (UE5) block layout:
 *   FNameEntry (2-byte aligned):
 *     uint16 Header = (len << 1) | bIsWide
 *     char/wchar_t Name[len]
 *
 *   Block 0 starts with FNameEntry{"None"} at byte 0.
 *   Engine class/property names are in block 0.
 *   Game-specific names may be in block 1+.
 *
 * ComparisonIndex encoding:
 *   bits[31:16] = block_idx
 *   bits[15: 0] = word_off   (byte_offset_in_block >> 1)
 *
 * Block size: word_off max = 0xFFFF -> max byte_off = 0x1FFFE = ~128KB.
 * Actual allocation is typically 128KB (0x20000) per block.
 * NOTE: previous code required >= 256KB which was WRONG and caused
 * VirtualQuery scan to miss all blocks.
 *
 * FNamePool struct layout (UE5, MSVC x64, in module .bss):
 *   +0x00  SRWLOCK Lock        (8 bytes)
 *   +0x08  uint32  CurrentBlock
 *   +0x0C  uint32  CurrentByteCursor
 *   +0x10  uint8*  Blocks[8192]   (8192 pointers to 128KB heap blocks)
 */

#define FNAMEPOOL_BLOCKS_OFF  0x10   /* Blocks[] starts at FNamePool+0x10 */
#define FNAMEPOOL_MAX_BLOCKS  8192
#define FNAMEPOOL_BLOCK_BYTES (128 * 1024)  /* max usable bytes per block */

/*
 * FNameEntry header format differs between engine versions:
 *
 *   UE4 (UE4.23+):    header = (len << 1) | bIsWide
 *                     "None" header = 0x0008, bytes = {0x08, 0x00}
 *
 *   UE5:              header = (len << 6) | (probeHash << 1) | bIsWide
 *                     "None" header = 0x0100|(hash<<1), bytes = {hash*2, 0x01}
 *                     bIsWide   = bit 0
 *                     probeHash = bits 1-5 (5-bit, hash of lowercase name)
 *                     Len       = bits 6-15 (10-bit)
 *
 * g_fname_header_shift: 1 for UE4, 6 for UE5. Auto-detected on block0 find.
 */
static int       g_fname_header_shift = 1;  /* default UE4; updated on find */
static uintptr_t g_fnamepool_block0   = 0;  /* FNamePool block 0 base (heap) */
static uintptr_t g_fnamepool_global   = 0;  /* FNamePool struct (module .bss) */

/* fname_entry_len(): extract name length from a raw uint16 header */
static inline int fname_entry_len(uint16_t hdr)
{
    return (int)(hdr >> g_fname_header_shift);
}

/* fname_block0_matches_none(): check if addr looks like the start of FNamePool
 * block 0 (first entry = "None") in either UE4 or UE5 header format.
 * Sets g_fname_header_shift to the detected format. */
static bool fname_block0_matches_none(uintptr_t addr)
{
    uint8_t b0, b1, b2, b3, b4, b5;
    __try {
        b0 = *(uint8_t*)(addr + 0);
        b1 = *(uint8_t*)(addr + 1);
        b2 = *(uint8_t*)(addr + 2);
        b3 = *(uint8_t*)(addr + 3);
        b4 = *(uint8_t*)(addr + 4);
        b5 = *(uint8_t*)(addr + 5);
    }
    __except(EXCEPTION_EXECUTE_HANDLER) { return false; }

    if (b2 != 'N' || b3 != 'o' || b4 != 'n' || b5 != 'e') return false;
    if (b0 & 1) return false; /* bIsWide must be 0 */

    /* UE4: header = 0x0008 -- len field in bits 15-1, len=4 => byte1=0x00,byte0=0x08 */
    if (b1 == 0x00 && b0 == 0x08) {
        g_fname_header_shift = 1;
        return true;
    }
    /* UE5: header = 0x0100|(hash<<1) -- len field in bits 15-6, len=4 => byte1=0x01 */
    if (b1 == 0x01) {
        g_fname_header_shift = 6;
        return true;
    }
    return false;
}

/*
 * fname_get_block(bi) -- return heap pointer for block index bi.
 * Uses g_fnamepool_global (full Blocks[] array) when available,
 * falls back to g_fnamepool_block0 for bi==0.
 */
static uintptr_t fname_get_block(uint32_t bi)
{
    if (bi == 0 && g_fnamepool_block0)
        return g_fnamepool_block0;
    if (g_fnamepool_global && bi < FNAMEPOOL_MAX_BLOCKS)
        return seh_read_ptr(
            (void*)(g_fnamepool_global + FNAMEPOOL_BLOCKS_OFF + bi * 8));
    return 0;
}

/*
 * fname_resolve(comp_idx, out, out_len) -- ComparisonIndex -> string.
 * Works for any block (requires g_fnamepool_global for bi > 0).
 * Returns true on success; out is null-terminated UTF-8.
 */
static bool fname_resolve(uint32_t comp_idx, char* out, int out_len)
{
    if (!out || out_len <= 1) return false;
    out[0] = '\0';

    uint32_t bi       = comp_idx >> 16;
    uint32_t word_off = comp_idx & 0xFFFF;
    uint32_t byte_off = word_off * 2;

    uintptr_t block = fname_get_block(bi);
    if (!block) return false;

    uint16_t hdr = 0;
    __try { hdr = *(uint16_t*)(block + byte_off); }
    __except(EXCEPTION_EXECUTE_HANDLER) { return false; }

    bool is_wide = (hdr & 1) != 0;
    int  len     = fname_entry_len(hdr);  /* shift=1 (UE4) or 6 (UE5) */
    if (len <= 0 || len >= 4096) return false;

    int n = (len < out_len - 1) ? len : out_len - 1;
    if (is_wide) {
        int bytes = 0;
        __try {
            bytes = WideCharToMultiByte(CP_UTF8, 0,
                (const wchar_t*)(block + byte_off + 2),
                n, out, out_len - 1, NULL, NULL);
        }
        __except(EXCEPTION_EXECUTE_HANDLER) { return false; }
        out[bytes > 0 ? bytes : 0] = '\0';
    } else {
        __try { memcpy(out, (void*)(block + byte_off + 2), n); }
        __except(EXCEPTION_EXECUTE_HANDLER) { return false; }
        out[n] = '\0';
    }
    return true;
}

/*
 * find_fnamepool_global() -- locate FNamePool struct in module .bss.
 *
 * Method 1: Export symbol "GNamePool" or "?GNamePool@@3VFNamePool@@A".
 *   The export IS the struct; validate by checking Blocks[0] points to
 *   a heap region starting with "None".
 *
 * Method 2: After finding block0 via VirtualQuery, scan module data
 *   for a pointer == block0. That pointer is FNamePool.Blocks[0]
 *   at FNamePool+FNAMEPOOL_BLOCKS_OFF.
 *
 * Sets g_fnamepool_global and g_fnamepool_block0 on success.
 */
static uintptr_t find_fnamepool_global()
{
    if (g_fnamepool_global) return g_fnamepool_global;

    /* Method 1: Export symbol */
    static const char* exports[] = {
        "GNamePool",
        "?GNamePool@@3VFNamePool@@A",
    };
    for (int ei = 0; ei < 2; ei++) {
        uintptr_t p = (uintptr_t)GetProcAddress(
            GetModuleHandleA(NULL), exports[ei]);
        if (!p) continue;

        uintptr_t blk0 = seh_read_ptr((void*)(p + FNAMEPOOL_BLOCKS_OFF));
        if (blk0 < 0x10000) continue;

        if (!fname_block0_matches_none(blk0)) continue;

        g_fnamepool_global = p;
        g_fnamepool_block0 = blk0;
        bridge_log("  FNamePool global=0x%llX (export '%s') block0=0x%llX fmt=%s",
                   (unsigned long long)p, exports[ei],
                   (unsigned long long)blk0,
                   g_fname_header_shift == 6 ? "UE5" : "UE4");
        return p;
    }

    /* Method 2: block0 must already be found -- scan module for backref */
    if (!g_fnamepool_block0) return 0;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return 0;
    uintptr_t mod_base = (uintptr_t)rgn.base;
    uintptr_t mod_end  = mod_base + rgn.size;

    /* Walk module PAGE_READWRITE regions looking for ptr == block0.
     * Skip .text (PAGE_EXECUTE_READ) -- FNamePool is a global in .bss/.data.
     * This avoids scanning 300-600MB of code pages (~75M seh_read_ptr calls). */
    {
        uintptr_t cur = mod_base;
        while (cur < mod_end) {
            MEMORY_BASIC_INFORMATION mbi2 = {};
            if (!VirtualQuery((void*)cur, &mbi2, sizeof(mbi2))) { cur += 0x1000; continue; }
            uintptr_t rgn_base = (uintptr_t)mbi2.BaseAddress;
            uintptr_t rgn_end  = rgn_base + mbi2.RegionSize;
            if (rgn_end > mod_end) rgn_end = mod_end;

            /* Only scan committed, writable (data/bss) pages */
            bool writable = (mbi2.State == MEM_COMMIT) &&
                (mbi2.Protect & (PAGE_READWRITE | PAGE_WRITECOPY |
                                  PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY));
            if (writable) {
                for (uintptr_t scan = rgn_base; scan < rgn_end - 8; scan += 8) {
                    uintptr_t val = seh_read_ptr((void*)scan);
                    if (val != g_fnamepool_block0) continue;

                    /* Validate: pool+0x08 (CurrentBlock) should be small int < 128 */
                    uintptr_t pool_cand = scan - FNAMEPOOL_BLOCKS_OFF;
                    int32_t cur_blk = 0;
                    __try { cur_blk = *(int32_t*)(pool_cand + 0x08); }
                    __except(EXCEPTION_EXECUTE_HANDLER) { cur_blk = 9999; }

                    if (cur_blk < 0 || cur_blk >= 128) continue; /* not a FNamePool */

                    g_fnamepool_global = pool_cand;
                    bridge_log("  FNamePool global=0x%llX (backref scan, "
                               "Blocks[0]@0x%llX, CurrentBlock=%d)",
                               (unsigned long long)pool_cand,
                               (unsigned long long)scan, cur_blk);
                    return pool_cand;
                }
            }
            cur = rgn_end;
        }
    }

    bridge_log("  FNamePool global: backref scan failed");
    return 0;
}

/*
 * find_fnamepool_block0() -- locate FNamePool block 0 in heap.
 *
 * Method 1: Export check via find_fnamepool_global() (also sets global).
 * Method 2: VirtualQuery scan -- find committed readable region >= 64KB
 *   that starts with the "None" FNameEntry.
 *   BUG FIX: old code required >= 256KB but FNamePool blocks are 128KB,
 *   so ALL blocks were filtered out. Now uses 64KB minimum.
 */
static uintptr_t find_fnamepool_block0()
{
    if (g_fnamepool_block0) return g_fnamepool_block0;

    /* Method 1: try export (also finds global for multi-block support) */
    if (find_fnamepool_global()) return g_fnamepool_block0;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return 0;
    uintptr_t mod_base = (uintptr_t)rgn.base;
    uintptr_t mod_end  = mod_base + rgn.size;

    /* Method 2: VirtualQuery heap scan */
    MEMORY_BASIC_INFORMATION mbi = {};
    uintptr_t addr = 0x10000;
    int regions_checked = 0;

    while (addr < 0x800000000000ULL) {
        if (!VirtualQuery((void*)addr, &mbi, sizeof(mbi))) {
            addr += 0x10000;
            continue;
        }
        uintptr_t base = (uintptr_t)mbi.BaseAddress;
        uintptr_t end  = base + mbi.RegionSize;

        /* FNamePool blocks are ~128KB; require >= 64KB to filter noise
         * while still catching blocks smaller than our expectation. */
        bool skip = (mbi.State != MEM_COMMIT)
                 || !(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE
                                    | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE))
                 || (base < mod_end && end > mod_base)   /* overlaps module */
                 || mbi.RegionSize < (64 * 1024);         /* < 64KB, too small */

        if (!skip) {
            regions_checked++;
            if (fname_block0_matches_none(base)) {
                /* Cross-check: next entry after "None" (6 bytes) should be valid */
                uint16_t next_hdr = 0;
                __try { next_hdr = *(uint16_t*)(base + 6); }
                __except(EXCEPTION_EXECUTE_HANDLER) {}

                int next_len = fname_entry_len(next_hdr);
                /* Accept if next entry is zero-terminator or valid short ASCII name */
                if (next_hdr == 0 ||
                    (next_len >= 1 && next_len <= 256 && (next_hdr & 1) == 0)) {
                    g_fnamepool_block0 = base;
                    bridge_log("  FNamePool block0=0x%llX fmt=%s "
                               "(%d regions checked, regionSize=%zuKB)",
                               (unsigned long long)base,
                               g_fname_header_shift == 6 ? "UE5" : "UE4",
                               regions_checked, mbi.RegionSize / 1024);
                    /* Try to find pool global for multi-block support */
                    find_fnamepool_global();
                    return base;
                }
                bridge_log("  FNamePool: 'None' at 0x%llX but next_hdr=0x%04X "
                           "(len=%d) -- rejected",
                           (unsigned long long)base, next_hdr, next_len);
            }
        }
        addr = end;
    }
    bridge_log("  FNamePool block0: not found (%d regions checked)", regions_checked);
    return 0;
}

/*
 * get_fname_cmpidx_for(target) -- walk block 0 to find ComparisonIndex.
 * Returns 0xFFFFFFFF if not found.
 */
static uint32_t get_fname_cmpidx_for(const char* target)
{
    uintptr_t block0 = find_fnamepool_block0();
    if (!block0) return 0xFFFFFFFF;

    int tlen = (int)strlen(target);

    uintptr_t cursor  = block0;
    uintptr_t blk_end = block0 + FNAMEPOOL_BLOCK_BYTES;

    while (cursor < blk_end - 2) {
        uint16_t hdr = 0;
        __try { hdr = *(uint16_t*)cursor; }
        __except(EXCEPTION_EXECUTE_HANDLER) { break; }

        if (hdr == 0) break;
        bool is_wide = (hdr & 1) != 0;
        int  len     = fname_entry_len(hdr);  /* shift=1 (UE4) or 6 (UE5) */
        if (len < 1 || len > 512) break;

        /* In UE5, probe hash occupies bits 1-5 so we can't check exact header.
         * Match on length + content only (bIsWide=0 already checked). */
        if (!is_wide && len == tlen) {
            bool match = false;
            __try { match = (memcmp((void*)(cursor + 2), target, tlen) == 0); }
            __except(EXCEPTION_EXECUTE_HANDLER) {}
            if (match) {
                uint32_t byte_off = (uint32_t)(cursor - block0);
                return byte_off >> 1;   /* block_idx=0, word_off = byte_off/2 */
            }
        }

        int entry_bytes = 2 + (is_wide ? len * 2 : len);
        entry_bytes = (entry_bytes + 1) & ~1;  /* 2-byte aligned */
        cursor += (uintptr_t)entry_bytes;
    }
    return 0xFFFFFFFF;
}

/* ---- UWorld via GUObjectArray + FName class comparison ---------- */

/*
 * find_uworld_via_guobjectarray()
 *
 * Preferred: FName-based class lookup.
 *   For each GUObjectArray item, read ClassPrivate.NamePrivate and compare
 *   ComparisonIndex against FName("World"). ClassPrivate at obj+0x10,
 *   NamePrivate at ClassPrivate+0x18 (FName lo32 = ComparisonIndex).
 *   Apply outer chain check: UWorld->UPackage->null.
 *
 * Fallback: vtable fingerprint (if FNamePool unavailable).
 *   FNetworkNotify secondary vtable (4-10 entries) + primary >= 30 entries.
 *
 * Requires: g_guobjectarray_found && g_engine_found.
 * stride/object_off set by detect_fuobjectitem_stride() before this call.
 */
static bool find_uworld_via_guobjectarray()
{
    if (!g_guobjectarray_found || !g_guobjectarray) return false;
    /* g_engine_ptr is NOT required for the FName path (only for vtable fallback).
     * OuterPrivate is fixed at UObjectBase+0x20 regardless of g_fexec_offset. */

    int32_t num_elems = guobjectarray_num_elements();
    bridge_log("=== UWorld scan via GUObjectArray (%d objects, "
               "stride=%d off=0x%02X) ===",
               num_elems, g_fuobjectitem_stride, g_fuobjectitem_object_off);

    /* OuterPrivate at UObjectBase+0x20 (always -- part of fixed UObjectBase layout) */
    uintptr_t outer_off = 0x20;

    /* --- FName-based search (preferred) --- */
    uint32_t world_idx = get_fname_cmpidx_for("World");
    if (world_idx != 0xFFFFFFFF) {
        /* Cross-validate: resolve the index back to a string.
         * Confirms FNamePool parsing is correct, and gives fname_resolve
         * a call site (suppresses C4505 unused-function warning). */
        char resolved[64];
        if (fname_resolve(world_idx, resolved, sizeof(resolved)))
            bridge_log("  FName('World') idx=0x%X resolved='%s' -- FName class search",
                       world_idx, resolved);
        else
            bridge_log("  FName('World') idx=0x%X (resolve failed) -- FName class search",
                       world_idx);

        int class_matches = 0;

        for (int32_t i = 0; i < num_elems; i++) {
            if (i > 0 && (i % 10000) == 0)
                bridge_log("  FName scan progress: %d/%d, class_matches=%d",
                           i, num_elems, class_matches);

            void* obj = guobjectarray_get(i);
            if (!obj || (uintptr_t)obj < 0x10000) continue;
            if ((uintptr_t)obj >= 0x800000000000ULL) continue;

            /* ClassPrivate at UObjectBase+0x10 */
            uintptr_t class_ptr = seh_read_ptr((uint8_t*)obj + 0x10);
            if (class_ptr < 0x10000) continue;

            /* UClass.NamePrivate lo32 = ComparisonIndex */
            uint64_t name_raw = seh_read_ptr((uint8_t*)class_ptr + 0x18);
            uint32_t cmp_idx  = (uint32_t)(name_raw & 0xFFFFFFFF);
            if (cmp_idx != world_idx) continue;

            class_matches++;
            bridge_log("  FName class match: idx=%d obj=0x%p -- outer chain check",
                       i, obj);

            /* Outer chain: UWorld.OuterPrivate (at outer_off) != null */
            uintptr_t outer = seh_read_ptr((uint8_t*)obj + outer_off);
            bridge_log("    outer_off=0x%llX outer=0x%llX",
                       (unsigned long long)outer_off, (unsigned long long)outer);
            if (outer < 0x10000 || outer >= 0x800000000000ULL) {
                bridge_log("    SKIP: outer invalid");
                continue;
            }

            /* UPackage.OuterPrivate must be null (root object) */
            uintptr_t outer_outer = seh_read_ptr((uint8_t*)outer + outer_off);
            bridge_log("    outer.outer=0x%llX", (unsigned long long)outer_outer);
            if (outer_outer != 0) {
                bridge_log("    SKIP: outer.outer != null (not root UPackage)");
                continue;
            }

            bridge_log("  UWorld found via FName: idx=%d obj=0x%p outer=0x%llX",
                       i, obj, (unsigned long long)outer);
            g_world_ptr = obj;
            return true;
        }

        bridge_log("  UWorld not found via FName (%d objects, %d class matches)",
                   num_elems, class_matches);
        return false;
    }

    /* --- Vtable fingerprint fallback --- */
    bridge_log("  FNamePool N/A -- vtable fingerprint fallback");
    if (!g_engine_ptr) {
        bridge_log("  vtable fallback skipped: g_engine_ptr not found yet");
        return false;
    }

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start   = (uintptr_t)rgn.base;
    uintptr_t mod_end     = mod_start + rgn.size;
    uintptr_t engine_vptr = seh_read_ptr(g_engine_ptr);

    /* UWorld identification: primary vtable >= 30 entries + outer chain.
     * Do NOT use secondary vtable offset -- UWorld's FNetworkNotify is at an
     * unknown offset (not 0x28, which is GEngine's FExec). */
    for (int32_t i = 0; i < num_elems; i++) {
        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x800000000000ULL) continue;

        uintptr_t vptr = seh_read_ptr(obj);
        if (vptr < mod_start || vptr >= mod_end) continue;
        if (vptr == engine_vptr) continue;  /* skip GEngine itself */

        int vcnt = 0;
        for (int vi = 0; vi < 256; vi++) {
            void* fn = (void*)seh_read_ptr((void*)(vptr + vi * 8));
            if (!validate_function_ptr(fn)) break;
            vcnt++;
        }
        if (vcnt < 30) continue;

        uintptr_t outer = seh_read_ptr((uint8_t*)obj + outer_off);
        if (outer < 0x10000 || outer >= 0x800000000000ULL) continue;
        if (seh_read_ptr((uint8_t*)outer + outer_off) != 0) continue;

        bridge_log("  UWorld found via vtable fallback: idx=%d obj=0x%p "
                   "(vcnt=%d outer=0x%llX)", i, obj, vcnt, (unsigned long long)outer);
        g_world_ptr = obj;
        return true;
    }

    bridge_log("  UWorld not found (GUObjectArray vtable scan)");
    return false;
}

/*
 * find_uworld_via_worldlist()
 *
 * Locate UWorld by scanning GEngine for its WorldList field.
 * Does NOT require GUObjectArray -- works even when GUObjectArray
 * pattern matching fails (e.g. stripped/LTCG builds).
 *
 * UEngine::WorldList is TIndirectArray<FWorldContext>.
 * TIndirectArray<T> is TArray<T*> internally:
 *   +0x00  FWorldContext** Data   (pointer to array of FWorldContext*)
 *   +0x08  int32           Num    (element count)
 *   +0x0C  int32           Max    (capacity)
 *
 * In a standalone game, WorldList always has exactly Num=1.
 * FWorldContext[+0x00] = TEnumAsByte<EWorldType> = uint8 = 1 (Game).
 *
 * Confirmed for UE5.7 standalone:
 *   WorldList at GEngine+0x1250, Num=1, Max=4.
 *   FWorldContext::ThisCurrentWorld holds UWorld* at the end of struct.
 *
 * Strategy:
 *   1. Scan GEngine+0..+0x6000 step 8 for TIndirectArray pattern.
 *   2. Validate FWorldContext: Data[0] valid heap ptr, WorldType==1.
 *   3. Scan FWorldContext for UWorld: FNetworkNotify secondary vtable
 *      (4-10 entries), primary vtable >= 30, outer chain World->Pkg->null.
 */
static bool find_uworld_via_worldlist()
{
    if (!g_engine_ptr) return false;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;

    /* OuterPrivate is at UObjectBase+0x20 (fixed in all UE versions).
     * Do not derive from g_fexec_offset -- that's GEngine's FExec offset, not UWorld's. */
    const uintptr_t outer_off = 0x20;

    uintptr_t eng = (uintptr_t)g_engine_ptr;
    bridge_log("=== UWorld scan via GEngine WorldList ===");

    for (int off = 0; off <= 0x6000; off += 8) {
        uintptr_t slot = eng + off;

        /* --- Step 1: Check TIndirectArray layout at GEngine+off ---
         * Read Data* at +0 (must be heap), then Num/Max packed in next 8B. */
        uintptr_t data_ptr = seh_read_ptr((void*)slot);
        if (data_ptr < 0x10000 || data_ptr >= 0x800000000000ULL) continue;
        /* Data* must not point inside GEngine itself */
        if (data_ptr >= eng && data_ptr < eng + 0x10000) continue;
        /* Data* must not be in the module image (vtable or code section) */
        if (data_ptr >= mod_start && data_ptr < mod_end) continue;

        /* Num(lo32) and Max(hi32) are packed in bytes +8..+15 */
        uintptr_t num_max = seh_read_ptr((void*)(slot + 8));
        int32_t num = (int32_t)(num_max & 0xFFFFFFFFULL);
        int32_t max = (int32_t)(num_max >> 32);

        if (num != 1) continue;          /* standalone always has exactly 1 */
        if (max < 1 || max > 16) continue;

        /* --- Step 2: Validate FWorldContext pointer ---
         * Data[0] is FWorldContext* (TIndirectArray stores pointers-to-elements). */
        uintptr_t fwc = seh_read_ptr((void*)data_ptr);
        if (fwc < 0x10000 || fwc >= 0x800000000000ULL) continue;
        if (fwc >= mod_start && fwc < mod_end) continue;
        if (fwc >= eng && fwc < eng + 0x10000) continue;

        /* FWorldContext[+0x00] = TEnumAsByte<EWorldType> = uint8.
         * EWorldType::Game == 1.  Read as low byte of the first 8-byte word. */
        uintptr_t first8 = seh_read_ptr((void*)fwc);
        uint8_t world_type = (uint8_t)(first8 & 0xFF);
        if (world_type != 1) continue;   /* not a Game world context */

        bridge_log("  WorldList candidate GEngine+0x%X: Data=0x%llX "
                   "Num=%d Max=%d FWC=0x%llX",
                   off, (unsigned long long)data_ptr,
                   num, max, (unsigned long long)fwc);

        /* --- Step 3: Scan FWorldContext for UWorld pointer ---
         * Walk every 8-byte-aligned slot of FWorldContext (up to 0x2000 bytes).
         * UWorld is identified by: primary vtable in module (>= 30 entries) +
         * outer chain: UWorld.OuterPrivate -> valid heap, outer.OuterPrivate == null. */
        int fwc_heap_ptrs = 0;   /* count of non-null heap ptrs seen (for diagnostics) */
        int fwc_vtable_ok = 0;   /* heap ptrs that also have module vtable */
        for (int woff = 0; woff <= 0x2000; woff += 8) {
            uintptr_t candidate = seh_read_ptr((void*)(fwc + woff));
            if (candidate < 0x10000 || candidate >= 0x800000000000ULL) continue;
            if (candidate >= mod_start && candidate < mod_end) continue;
            if (candidate == (uintptr_t)g_engine_ptr) continue;
            if (candidate == fwc) continue;
            fwc_heap_ptrs++;

            /* Primary vtable must be in module image */
            uintptr_t vptr = seh_read_ptr((void*)candidate);
            if (vptr < mod_start || vptr >= mod_end) continue;
            fwc_vtable_ok++;

            /* Primary vtable >= 30 entries (UWorld is a large class). */
            int vcnt = 0;
            for (int vi = 0; vi < 256; vi++) {
                void* fn = (void*)seh_read_ptr((void*)(vptr + vi * 8));
                if (!validate_function_ptr(fn)) break;
                vcnt++;
            }

            /* OuterPrivate at outer_off */
            uintptr_t outer = seh_read_ptr((void*)(candidate + outer_off));
            uintptr_t outer_outer = (outer >= 0x10000 && outer < 0x800000000000ULL)
                ? seh_read_ptr((void*)(outer + outer_off)) : 0xDEAD;

            bridge_log("  FWC+0x%03X: cand=0x%llX vptr=0x%llX vcnt=%d "
                       "outer=0x%llX oo=0x%llX",
                       woff, (unsigned long long)candidate,
                       (unsigned long long)vptr, vcnt,
                       (unsigned long long)outer,
                       (unsigned long long)outer_outer);

            /* vcnt >= 1: we only require the vtable is readable.
             * validate_function_ptr is strict about prologue bytes and
             * may score optimized UWorld as vcnt=1. The outer chain
             * (outer valid + outer.outer==null) is the real discriminator. */
            if (vcnt < 1) continue;
            if (outer < 0x10000 || outer >= 0x800000000000ULL) continue;
            if (outer_outer != 0) continue;

            bridge_log("  UWorld found via WorldList: FWC+0x%X=0x%llX "
                       "(vcnt=%d outer=0x%llX)",
                       woff, (unsigned long long)candidate,
                       vcnt, (unsigned long long)outer);
            g_world_ptr = (void*)candidate;
            return true;
        }

        bridge_log("  FWC at 0x%llX (GEngine+0x%X) scan done: "
                   "heap_ptrs=%d vtable_ok=%d -- UWorld not found",
                   (unsigned long long)fwc, off, fwc_heap_ptrs, fwc_vtable_ok);
    }

    bridge_log("  UWorld not found via WorldList scan");
    return false;
}

/*
 * Find GUObjectArray.
 *
 * Strategy 1: Export symbol lookup.
 *   Many UE5 games export "?GUObjectArray@@3VFUObjectArray@@A".
 *   (Used by Returnal, per UE4SS GUObjectArray.lua.)
 *
 * Strategy 2-4: AOB pattern scan -- three patterns sourced from
 *   UE4SS CustomGameConfigs Lua scripts (validated on real UE5 games):
 *
 *   Pat-A (LN3): LEA reg, [RIP+GUObjectArray] in AllocateUObjectIndex
 *     48 8D ?? ?? ?? ?? ?? 4C 8B C9 48 89 01
 *     Decode: next=addr+7, GUA = next + *(int32*)(addr+3)
 *
 *   Pat-B (FF7 Remake): MOV reg, [RIP+ptr_into_GUA+0x10]
 *     48 8B ?? ?? ?? ?? ?? 4C 8B 04 C8 4D 85 C0 74 07
 *     Decode: next=addr+7, ptr = next+*(int32*)(addr+3), GUA = ptr-0x10
 *
 *   Pat-C (FF7 Rebirth): ADD targeting GUObjectArray+6
 *     03 ?? ?? ?? ?? ?? FF C8 3B D0 0F 8D
 *     Decode: next=addr+6, GUA = next + *(int32*)(addr+2)
 */
static bool find_guobjectarray()
{
    bridge_log("=== GUObjectArray Search ===");

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;

    /* --- Strategy 1: Export symbol --- */
    HMODULE exe = GetModuleHandleA(NULL);
    void* exp_addr = (void*)GetProcAddress(
        exe, "?GUObjectArray@@3VFUObjectArray@@A");
    if (exp_addr) {
        bridge_log("  Strategy 1: export found at 0x%p", exp_addr);
        if (validate_guobjectarray(exp_addr)) {
            g_guobjectarray = exp_addr;
            g_guobjectarray_found = true;
            bridge_log("  GUObjectArray via export: 0x%p", exp_addr);
            return true;
        }
    } else {
        bridge_log("  Strategy 1: export not found");
    }

    /* --- Strategy 2-5: AOB patterns --- */
    /* mod_start/mod_end only needed for AOB candidate validation */
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;

    /* Pat-A: 48 8D ?? ?? ?? ?? ?? 4C 8B C9 48 89 01
     * LEA reg,[rip+GUA] in AllocateUObjectIndex (LN3 demo) */
    static const uint8_t patA[] = {
        0x48,0x8D, 0,0,0,0,0,  0x4C,0x8B,0xC9, 0x48,0x89,0x01
    };
    static const char maskA[] = "xx?????xxxxxx";

    /* Pat-B: 48 8B ?? ?? ?? ?? ?? 4C 8B 04 C8 4D 85 C0 74 07
     * MOV reg,[rip+GUA+0x10] (FF7 Remake) */
    static const uint8_t patB[] = {
        0x48,0x8B, 0,0,0,0,0,  0x4C,0x8B,0x04,0xC8, 0x4D,0x85,0xC0,0x74,0x07
    };
    static const char maskB[] = "xx?????xxxxxxxxx";

    /* Pat-C: 03 ?? ?? ?? ?? ?? FF C8 3B D0 0F 8D
     * ADD targeting GUObjectArray+6 (FF7 Rebirth) */
    static const uint8_t patC[] = {
        0x03, 0,0,0,0,0,  0xFF,0xC8, 0x3B,0xD0, 0x0F,0x8D
    };
    static const char maskC[] = "x?????xxxxxx";

    /* Pat-D: 48 8D 0D ?? ?? ?? ?? E8 ?? ?? ?? ?? E8 ?? ?? ?? ?? E8 ?? ?? ?? ?? C6 05 ?? ?? ?? ?? 01
     * LEA RCX,[rip+GUA+0x10] in engine init sequence (Split Fiction)
     * Same -0x10 adjustment as Pat-B. */
    static const uint8_t patD[] = {
        0x48,0x8D,0x0D, 0,0,0,0,
        0xE8, 0,0,0,0,
        0xE8, 0,0,0,0,
        0xE8, 0,0,0,0,
        0xC6,0x05, 0,0,0,0, 0x01
    };
    static const char maskD[] = "xxx????x????x????x????xx????x";

    struct PatEntry {
        const uint8_t* bytes;
        const char*    mask;
        size_t         len;
        int            disp_off;   /* offset to int32 displacement */
        int            instr_len;  /* total instruction bytes */
        int            adjustment; /* subtract from resolved addr */
        const char*    name;
    };

    PatEntry pats[] = {
        {patA, maskA, 13, 3, 7,    0, "Pat-A (LN3/AllocateUObjectIndex)"},
        {patB, maskB, 16, 3, 7, 0x10, "Pat-B (FF7R/GUObjectArray+0x10)"},
        {patC, maskC, 12, 2, 6,    0, "Pat-C (FF7Rebirth/ADD-pattern)"},
        {patD, maskD, 29, 3, 7, 0x10, "Pat-D (SplitFiction/LEA-RCX)"},
    };
    const int NUM_PATS = 4;

    for (int pi = 0; pi < NUM_PATS; pi++) {
        const PatEntry& pe = pats[pi];
        const uint8_t* hit = pattern_scan(
            rgn.base, rgn.size, pe.bytes, pe.mask, pe.len);

        if (!hit) {
            bridge_log("  Strategy %d: %s -- no match", pi + 2, pe.name);
            continue;
        }

        bridge_log("  Strategy %d: %s matched at +0x%llX",
                   pi + 2, pe.name,
                   (unsigned long long)(hit - rgn.base));

        uintptr_t resolved = resolve_rip_relative(
            hit, pe.disp_off, pe.instr_len);
        void* candidate = (void*)(resolved - (uintptr_t)pe.adjustment);

        bridge_log("    resolved=0x%llX, candidate=0x%p",
                   (unsigned long long)resolved, candidate);

        if ((uintptr_t)candidate < mod_start ||
            (uintptr_t)candidate >= mod_end) {
            bridge_log("    candidate outside module, skip");
            continue;
        }

        if (!validate_guobjectarray(candidate)) continue;

        g_guobjectarray = candidate;
        g_guobjectarray_found = true;
        bridge_log("  GUObjectArray FOUND via %s: 0x%p", pe.name, candidate);
        return true;
    }

    bridge_log("  GUObjectArray: all strategies failed");
    return false;
}

/* -- FExec multi-hook: scan GUObjectArray for FExec objects -------- */

/*
 * Install a hook on vtable[1] of a secondary FExec vtable.
 * Returns true if newly installed, false if already hooked.
 *
 * Reuses hooked_fexec_exec (defined later) which:
 *   1. Captures UWorld from the `world` parameter.
 *   2. Looks up the correct original in g_fexec_hook_table.
 *   3. Forwards to the original.
 */
static bool __fastcall hooked_fexec_exec(  /* forward decl */
    void* this_fexec, void* world, const wchar_t* cmd, void* ar);

static bool install_fexec_hook_on(uintptr_t fexec_vtable,
                                   uintptr_t primary_vptr,
                                   uintptr_t mod_start, uintptr_t mod_end)
{
    if (g_fexec_hook_count >= 64) {
        return false;  /* table full -- caller should stop scanning */
    }

    /* Reject primary vtable */
    if (fexec_vtable == primary_vptr) return false;

    /* Check if already hooked */
    for (int i = 0; i < g_fexec_hook_count; i++) {
        if (g_fexec_hook_table[i].vtable_base == fexec_vtable)
            return false;  /* already done */
    }

    /* vtable[1] = Exec (the function we want to intercept) */
    uintptr_t* slot = (uintptr_t*)(fexec_vtable + 8);
    FExecExecFn orig = (FExecExecFn)seh_read_ptr((void*)slot);
    if (!orig || orig == (FExecExecFn)hooked_fexec_exec) return false;
    if (!validate_function_ptr((void*)orig)) return false;

    /* Make vtable page writable */
    DWORD old_prot = 0;
    if (!VirtualProtect(slot, 8, PAGE_READWRITE, &old_prot)) {
        bridge_log("  FExec hook: VirtualProtect failed (%d)",
                   GetLastError());
        return false;
    }
    *slot = (uintptr_t)hooked_fexec_exec;
    VirtualProtect(slot, 8, old_prot, &old_prot);

    FExecHookEntry& e = g_fexec_hook_table[g_fexec_hook_count++];
    e.vtable_base = fexec_vtable;
    e.slot        = slot;
    e.original    = orig;

    bridge_log("  FExec hook installed: vtable=0x%llX "
               "original=0x%p slot=%d",
               (unsigned long long)fexec_vtable, (void*)orig,
               g_fexec_hook_count - 1);
    return true;
}

/*
 * Scan GUObjectArray for all UObjects that have a secondary FExec vtable
 * at offset 0x28 (= sizeof(UObject) = UE4SS default FExecVTableOffsetInLocalPlayer).
 *
 * This finds UGameEngine (already hooked), ULocalPlayer, and any other
 * FExec implementors. We hook all unique vtables.
 *
 * Caps at 200,000 objects to avoid blocking the game thread too long.
 * ULocalPlayer is created early and typically has index < 10,000.
 */
static void scan_guobjectarray_for_fexec_hooks()
{
    if (!g_guobjectarray_found || !g_guobjectarray) return;
    if (!g_engine_ptr) return;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;
    uintptr_t primary_vptr = seh_read_ptr(g_engine_ptr);  /* GEngine vtable */

    int32_t num_elems = guobjectarray_num_elements();
    int32_t scan_limit = (num_elems < 200000) ? num_elems : 200000;

    bridge_log("=== GUObjectArray FExec scan (%d objects, limit %d) ===",
               num_elems, scan_limit);

    int checked = 0;
    int hooked_new = 0;

    for (int32_t i = 0; i < scan_limit; i++) {
        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x7F0000000000ULL) continue;

        checked++;

        /* Use g_fexec_offset detected by find_fexec_vtable() on GEngine.
         * This handles both standard layout (+0x28) and WITH_CASE_PRESERVING_NAME
         * layout (+0x30) transparently. */
        uintptr_t fexec_off = g_fexec_offset ? g_fexec_offset : 0x28;
        uintptr_t fexec_vptr = seh_read_ptr((uint8_t*)obj + fexec_off);
        if (fexec_vptr < mod_start || fexec_vptr >= mod_end) continue;
        if (fexec_vptr == primary_vptr) continue;  /* skip primary */

        /* Validate: vtable[0] and vtable[1] must be valid functions
         * in module; 3-8 total entries (FExec signature). */
        void* fn0 = (void*)seh_read_ptr((void*)fexec_vptr);
        void* fn1 = (void*)seh_read_ptr((void*)(fexec_vptr + 8));
        if (!validate_function_ptr(fn0) || !validate_function_ptr(fn1))
            continue;

        int vcnt = 2;
        for (int vi = 2; vi < 9; vi++) {
            void* fn = (void*)seh_read_ptr((void*)(fexec_vptr + vi * 8));
            if (!validate_function_ptr(fn)) break;
            vcnt++;
        }
        if (vcnt < 2 || vcnt > 8) continue;

        /* This object has a valid FExec vtable -- hook it */
        if (install_fexec_hook_on(fexec_vptr, primary_vptr,
                                   mod_start, mod_end))
            hooked_new++;
        else if (g_fexec_hook_count >= 64)
            break;  /* table full, no point scanning further */
    }

    bridge_log("  GUObjectArray scan done: checked=%d, new_hooks=%d "
               "total_hooks=%d", checked, hooked_new, g_fexec_hook_count);
}


/* -- FExec multi-hook: actual hook function and management --------- */

/*
 * THE hook function installed on all FExec vtable[1] slots.
 *
 * This implements UE4SS's ULocalPlayerExecPreCallback pattern:
 *   ULocalPlayer::Exec(UWorld* InWorld, cmd, ar) -- UWorld is param 2.
 *   GEngine::Exec  (UWorld* InWorld, cmd, ar)    -- same calling convention.
 *
 * When the game calls any registered FExec::Exec (GEngine or ULocalPlayer),
 * InWorld (rdx) is the live UWorld pointer.  We capture it here.
 *
 * Lookup: find the correct original by matching this_fexec's vtable
 * against g_fexec_hook_table[].vtable_base.
 */
static bool __fastcall hooked_fexec_exec(
    void* this_fexec, void* world, const wchar_t* cmd, void* ar)
{
    /* Capture UWorld -- only accept valid heap pointers */
    if (world && (uintptr_t)world > 0x10000 &&
        (uintptr_t)world < 0x7F0000000000ULL)
    {
        if (g_world_ptr != world) {
            g_world_ptr = world;
            bridge_log("HOOK: UWorld captured 0x%p (this_fexec=0x%p)",
                       world, this_fexec);
        }
    }

    /* Dispatch to correct original via vtable lookup.
     * this_fexec points to the FExec subobject; its first qword is
     * the secondary vtable pointer (same key we stored at install). */
    uintptr_t vtable = seh_read_ptr(this_fexec);
    for (int i = 0; i < g_fexec_hook_count; i++) {
        if (g_fexec_hook_table[i].vtable_base == vtable)
            return g_fexec_hook_table[i].original(
                this_fexec, world, cmd, ar);
    }

    /* Fallback: vtable not in table (should not happen).
     * Return false rather than crashing. */
    bridge_log("HOOK: vtable 0x%llX not in hook table -- no-op",
               (unsigned long long)vtable);
    return false;
}

/*
 * Install FExec hook on GEngine (called after find_fexec_vtable()).
 * Also installs via GUObjectArray scan if available.
 * This replaces the old install_exec_hook().
 */
static bool install_all_fexec_hooks()
{
    if (!g_engine_ptr || !g_fexec_offset) return false;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;
    uintptr_t primary_vptr = seh_read_ptr(g_engine_ptr);

    bridge_log("=== Installing FExec hooks ===");

    /* Always hook GEngine's FExec (already found by find_fexec_vtable) */
    uint8_t* eng = (uint8_t*)g_engine_ptr;
    uintptr_t engine_fexec_vtable = seh_read_ptr(eng + g_fexec_offset);
    int n = g_fexec_hook_count;
    install_fexec_hook_on(engine_fexec_vtable, primary_vptr,
                          mod_start, mod_end);
    if (g_fexec_hook_count > n)
        bridge_log("  GEngine FExec hooked (vtable=0x%llX)",
                   (unsigned long long)engine_fexec_vtable);

    /* Scan GUObjectArray for additional FExec objects (ULocalPlayer etc.) */
    if (g_guobjectarray_found)
        scan_guobjectarray_for_fexec_hooks();

    bridge_log("  Total FExec hooks: %d", g_fexec_hook_count);
    return g_fexec_hook_count > 0;
}

static void uninstall_all_fexec_hooks()
{
    bridge_log("=== Uninstalling FExec hooks (%d) ===", g_fexec_hook_count);
    for (int i = 0; i < g_fexec_hook_count; i++) {
        FExecHookEntry& e = g_fexec_hook_table[i];
        DWORD old_prot = 0;
        VirtualProtect(e.slot, 8, PAGE_READWRITE, &old_prot);
        *e.slot = (uintptr_t)e.original;
        VirtualProtect(e.slot, 8, old_prot, &old_prot);
        bridge_log("  Restored vtable=0x%llX",
                   (unsigned long long)e.vtable_base);
    }
    g_fexec_hook_count = 0;
}

/* -- Console command execution ------------------------------------- */

/*
 * ProcessConsoleExec = ProcessEvent + 3 (always).
 */

static bool validate_function_ptr(void* fn)
{
    return seh_validate_function(fn);
}

/* -- Game-thread command dispatch ----------------------------------- */

/*
 * UE5 requires most console commands to run on the game thread.
 * Calling Exec() from our TCP handler thread causes assertion failures
 * (IsInGameThread check in AsyncLoading2.cpp etc.).
 *
 * Solution: subclass the game window's WndProc. The game thread runs
 * the Windows message pump, so PostMessage + custom WM delivers
 * execution to the game thread. TCP thread pushes commands to a
 * queue and posts a message; WndProc hook drains the queue and
 * calls exec_console_command_internal().
 */

static const int CMD_QUEUE_MAX = 256;
static char     g_cmd_queue[CMD_QUEUE_MAX][512];
static volatile LONG g_cmd_queue_head = 0;   /* write index (TCP thread) */
static volatile LONG g_cmd_queue_tail = 0;   /* read index (game thread) */

static HWND    g_game_hwnd = NULL;
static WNDPROC g_original_wndproc = NULL;
static UINT    g_wm_bridge_exec = 0;
static std::atomic<bool> g_gamethread_dispatch_ready{false};

/* The actual Exec call -- only called from game thread via WndProc */
static bool exec_console_command_internal(const char* cmd);

static void gamethread_drain_queue()
{
    while (g_cmd_queue_tail != g_cmd_queue_head) {
        LONG idx = g_cmd_queue_tail % CMD_QUEUE_MAX;
        exec_console_command_internal(g_cmd_queue[idx]);
        InterlockedIncrement(&g_cmd_queue_tail);
    }
}

static LRESULT CALLBACK bridge_wndproc(HWND hwnd, UINT msg,
                                        WPARAM wp, LPARAM lp)
{
    if (msg == g_wm_bridge_exec) {
        gamethread_drain_queue();
        return 0;
    }
    return CallWindowProcA(g_original_wndproc, hwnd, msg, wp, lp);
}

static bool setup_gamethread_dispatch()
{
    /* Register a unique window message */
    g_wm_bridge_exec = RegisterWindowMessageA("captureAIshi_bridge_exec");
    if (!g_wm_bridge_exec) {
        bridge_log("ERROR: RegisterWindowMessage failed");
        return false;
    }

    /* Find the game window (same logic as hotsample) */
    struct FindCtx { DWORD pid; HWND result; };
    FindCtx ctx = { GetCurrentProcessId(), NULL };

    EnumWindows([](HWND hwnd, LPARAM lp) -> BOOL {
        FindCtx* c = (FindCtx*)lp;
        DWORD wnd_pid = 0;
        GetWindowThreadProcessId(hwnd, &wnd_pid);
        if (wnd_pid == c->pid && IsWindowVisible(hwnd)) {
            char title[256];
            GetWindowTextA(hwnd, title, sizeof(title));
            if (strlen(title) > 0) {
                c->result = hwnd;
                return FALSE;
            }
        }
        return TRUE;
    }, (LPARAM)&ctx);

    g_game_hwnd = ctx.result;
    if (!g_game_hwnd) {
        bridge_log("WARNING: Game window not found for dispatch hook. "
                   "Commands will run on TCP thread (may crash).");
        return false;
    }

    /* Subclass the window */
    g_original_wndproc = (WNDPROC)SetWindowLongPtrA(
        g_game_hwnd, GWLP_WNDPROC, (LONG_PTR)bridge_wndproc);

    if (!g_original_wndproc) {
        bridge_log("WARNING: SetWindowLongPtr failed (%d). "
                   "Commands will run on TCP thread.", GetLastError());
        g_game_hwnd = NULL;
        return false;
    }

    g_gamethread_dispatch_ready = true;
    bridge_log("Game-thread dispatch ready (hwnd=0x%p, WM=0x%X)",
               g_game_hwnd, g_wm_bridge_exec);
    return true;
}

/*
 * Public API: queue a command for game-thread execution.
 * If dispatch is not ready, falls back to direct call (risky).
 */
static bool exec_console_command(const char* cmd)
{
    if (g_gamethread_dispatch_ready && g_game_hwnd) {
        /* Push to queue */
        LONG idx = g_cmd_queue_head % CMD_QUEUE_MAX;
        strncpy(g_cmd_queue[idx], cmd, 511);
        g_cmd_queue[idx][511] = '\0';
        InterlockedIncrement(&g_cmd_queue_head);

        /* Wake the game thread */
        PostMessageA(g_game_hwnd, g_wm_bridge_exec, 0, 0);

        bridge_log("CMD: %s (queued for game thread)", cmd);
        return true;
    }

    /* Fallback: direct call (may crash on some commands) */
    bridge_log("CMD: %s (direct call -- no dispatch hook)", cmd);
    return exec_console_command_internal(cmd);
}

/*
 * Internal: call FExec::Exec() on GEngine. Must be on game thread.
 *
 * FExec::Exec is the universal command router.  It handles CVars,
 * stat, showflag, and routes to world/player controllers for game
 * commands like ToggleDebugCamera.
 *
 * The this pointer must be adjusted to the FExec subobject:
 *   this_fexec = (uint8_t*)g_engine_ptr + g_fexec_offset
 * The vtable thunk then adjusts it back to UEngine base.
 */
static bool exec_console_command_internal(const char* cmd)
{
    if (!g_fexec_exec) {
        bridge_log("  [SKIP] FExec::Exec not available");
        return false;
    }

    /* Convert UTF-8 to wide string */
    int wlen = MultiByteToWideChar(CP_UTF8, 0, cmd, -1, NULL, 0);
    if (wlen <= 0) {
        bridge_log("  ERROR: UTF-8 to wide conversion failed");
        return false;
    }
    std::vector<wchar_t> wcmd(wlen);
    MultiByteToWideChar(CP_UTF8, 0, cmd, -1, wcmd.data(), wlen);

    void* ar = get_output_device();
    void* this_fexec = (uint8_t*)g_engine_ptr + g_fexec_offset;

    /* Lazy UWorld scan: startup scan runs before map load so UWorld may not
     * exist yet.  Re-scan here on first command after map load.
     * Priority: WorldList scan (no GUObjectArray needed) -> GUObjectArray fallback.
     * FExec hook parameters also update g_world_ptr when the game calls Exec. */
    if (!g_world_ptr) {
        if (!find_uworld_via_worldlist() && g_guobjectarray_found.load())
            find_uworld_via_guobjectarray();
    }
    void* world = g_world_ptr;

    /* Use GEngine's original Exec to avoid recursion.
     * GEngine hook is always the first entry in g_fexec_hook_table. */
    FExecExecFn exec_fn = g_fexec_exec;
    if (g_fexec_hook_count > 0)
        exec_fn = g_fexec_hook_table[0].original;

    bool cmd_ret = false;
    bool call_ok = seh_call_fexec(exec_fn, this_fexec,
                                   world, wcmd.data(), ar, &cmd_ret);
    if (!call_ok) {
        bridge_log("  ERROR: GEngine FExec::Exec crashed");
        return false;
    }

    if (cmd_ret) {
        bridge_log("  OK ret=1 (GEngine)");
        return true;
    }

    /* GEngine returned false -- gameplay commands (ToggleDebugCamera, slomo,
     * Teleport, SetViewLocation, etc.) are NOT routed by UEngine::Exec to
     * the world in UE5.7; they need UWorld::Exec directly.
     * UWorld also inherits FExec; its secondary vtable is at the same offset
     * as GEngine's (g_fexec_offset = sizeof(UObject) = 40 or 48). */
    if (world) {
        void* world_fexec_subobj = (uint8_t*)world + g_fexec_offset;
        uintptr_t world_fexec_vptr = seh_read_ptr(world_fexec_subobj);

        ModuleRegion rgn;
        if (get_main_module(rgn)) {
            uintptr_t mod_start = (uintptr_t)rgn.base;
            uintptr_t mod_end   = mod_start + rgn.size;

            if (world_fexec_vptr >= mod_start && world_fexec_vptr < mod_end) {
                /* vtable[1] = Exec -- same layout as GEngine's FExec vtable */
                FExecExecFn world_exec_fn = (FExecExecFn)seh_read_ptr(
                    (void*)(world_fexec_vptr + 8));

                if (world_exec_fn && validate_function_ptr((void*)world_exec_fn)) {
                    bool world_ret = false;
                    bool world_ok  = seh_call_fexec(world_exec_fn,
                                                     world_fexec_subobj,
                                                     world, wcmd.data(), ar,
                                                     &world_ret);
                    if (world_ok) {
                        bridge_log("  OK ret=%d (UWorld fallback)", (int)world_ret);
                        return world_ret;
                    }
                    bridge_log("  ERROR: UWorld FExec::Exec crashed");
                    return false;
                }
            }
        }
    }

    bridge_log("  OK ret=0 (GEngine only, no UWorld fallback)");
    return false;
}

/* -- Timestop / Game Speed ----------------------------------------- */

static bool set_game_speed(float speed)
{
    g_game_speed = speed;
    g_paused = (speed == 0.0f);

    char cmd[64];
    snprintf(cmd, sizeof(cmd), "slomo %.4f", speed);
    return exec_console_command(cmd);
}

static bool toggle_pause()
{
    if (g_paused) {
        return set_game_speed(1.0f);
    } else {
        return set_game_speed(0.0001f);  /* near-zero, not true 0 */
    }
}

/* -- HUD Toggle ---------------------------------------------------- */

static bool g_hud_visible = true;

static bool toggle_hud()
{
    g_hud_visible = !g_hud_visible;
    if (g_hud_visible) {
        exec_console_command("ShowHUD 1");
        exec_console_command("stat none");
    } else {
        exec_console_command("ShowHUD 0");
        exec_console_command("stat none");
        /* Do NOT disable PostProcessing -- it affects GBuffer output
         * (depth, normals) which we need for capture. ShowHUD 0 alone
         * is sufficient to hide the game HUD. */
    }
    bridge_log("HUD %s", g_hud_visible ? "shown" : "hidden");
    return true;
}

/* -- Free Camera --------------------------------------------------- */

static bool g_debug_camera_active = false;

static bool toggle_debug_camera()
{
    g_debug_camera_active = !g_debug_camera_active;
    exec_console_command("ToggleDebugCamera");
    bridge_log("Debug camera %s",
               g_debug_camera_active ? "enabled" : "disabled");
    return true;
}

static bool set_camera_location(float x, float y, float z)
{
    g_camera.x = x;
    g_camera.y = y;
    g_camera.z = z;

    char cmd[128];
    snprintf(cmd, sizeof(cmd), "SetViewLocation %.2f %.2f %.2f", x, y, z);
    return exec_console_command(cmd);
}

static bool set_camera_rotation(float pitch, float yaw, float roll)
{
    g_camera.pitch = pitch;
    g_camera.yaw = yaw;
    g_camera.roll = roll;

    char cmd[128];
    snprintf(cmd, sizeof(cmd), "SetViewRotation %.2f %.2f %.2f",
             pitch, yaw, roll);
    return exec_console_command(cmd);
}

static bool set_fov(float fov)
{
    g_camera.fov = fov;

    char cmd[64];
    snprintf(cmd, sizeof(cmd), "FOV %.1f", fov);
    return exec_console_command(cmd);
}

/* -- Hotsampling (Window Resize) ----------------------------------- */

static bool hotsample(int width, int height)
{
    /* Find the game window */
    HWND game_wnd = NULL;

    /* Walk all top-level windows, find one belonging to our process */
    struct FindCtx { DWORD pid; HWND result; };
    FindCtx ctx = { GetCurrentProcessId(), NULL };

    EnumWindows([](HWND hwnd, LPARAM lp) -> BOOL {
        FindCtx* c = (FindCtx*)lp;
        DWORD wnd_pid = 0;
        GetWindowThreadProcessId(hwnd, &wnd_pid);
        if (wnd_pid == c->pid && IsWindowVisible(hwnd)) {
            char title[256];
            GetWindowTextA(hwnd, title, sizeof(title));
            if (strlen(title) > 0) {
                c->result = hwnd;
                return FALSE;  /* stop */
            }
        }
        return TRUE;
    }, (LPARAM)&ctx);

    game_wnd = ctx.result;
    if (!game_wnd) {
        bridge_log("ERROR: Could not find game window for hotsampling");
        return false;
    }

    /* Remove window borders for exact pixel dimensions */
    LONG style = GetWindowLongA(game_wnd, GWL_STYLE);
    SetWindowLongA(game_wnd, GWL_STYLE, style & ~(WS_CAPTION | WS_THICKFRAME));

    /* Resize */
    SetWindowPos(game_wnd, HWND_TOP, 0, 0, width, height,
                 SWP_NOMOVE | SWP_FRAMECHANGED);

    /* Tell UE5 to update its rendering resolution */
    char cmd[128];
    snprintf(cmd, sizeof(cmd), "r.SetRes %dx%d", width, height);
    exec_console_command(cmd);

    bridge_log("Hotsampled to %dx%d", width, height);
    return true;
}

#endif /* CAPTUREAI_UE5_ENGINE_H */
