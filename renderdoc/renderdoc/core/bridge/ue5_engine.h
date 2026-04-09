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
 * Layout (UE5, x64 -- from UE source and UE4SS/UEPseudo):
 *
 * FUObjectArray:
 *   +0   ObjFirstGCIndex         (int32)
 *   +4   ObjLastNonGCIndex       (int32)
 *   +8   MaxObjectsNotConsideredByGC (int32)
 *   +12  OpenForDisregardForGC   (bool, 1 byte + 3 pad)
 *   +16  ObjObjects (FChunkedFixedUObjectArray):
 *     +16  Objects** (chunk array pointer)
 *     +24  PreAllocatedObjects* (may be NULL)
 *     +32  MaxElements (int32)
 *     +36  NumElements (int32)
 *     +40  MaxChunks (int32)
 *     +44  NumChunks (int32)
 *
 * FUObjectItem (24 bytes):
 *   +0   Object (UObjectBase*)
 *   +8   Flags (int32)
 *   +12  ClusterRootIndex (int32)
 *   +16  SerialNumber (int32)
 *   +20  padding (int32)
 *
 * Access pattern (same as UE4SS IndexToObject):
 *   chunk_idx      = index >> 16   (= index / 65536)
 *   within_idx     = index & 0xFFFF
 *   item           = Objects[chunk_idx][within_idx]  -- 24-byte stride
 *   object         = item.Object  (at item+0)
 */

#define GUOBJARRAY_OBJECTS_OFF    16   /* &GUObjectArray.ObjObjects.Objects */
#define GUOBJARRAY_NUMELEMS_OFF   36   /* &GUObjectArray.ObjObjects.NumElements */
#define FUOBJECTITEM_STRIDE       24   /* sizeof(FUObjectItem) */
#define FUOBJECTARRAY_CHUNK_SHIFT 16   /* NumElementsPerChunk = 64K = 1<<16 */
#define FUOBJECTARRAY_CHUNK_MASK  0xFFFF

static void*              g_guobjectarray = NULL;
static std::atomic<bool>  g_guobjectarray_found{false};

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

static FExecHookEntry     g_fexec_hook_table[16];
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
 * Validate a GUObjectArray candidate.
 * Checks: NumElements in [1000, 5000000], Objects** valid, chunk[0] valid.
 * Mirrors UE4SS's SetupGUObjectArrayAddress() sanity checks.
 */
static bool validate_guobjectarray(void* candidate)
{
    if (!candidate || (uintptr_t)candidate < 0x10000) return false;

    uint8_t* p = (uint8_t*)candidate;

    /* NumElements = p + GUOBJARRAY_NUMELEMS_OFF */
    int32_t num_elems = 0;
    __try { num_elems = *(int32_t*)(p + GUOBJARRAY_NUMELEMS_OFF); }
    __except(EXCEPTION_EXECUTE_HANDLER) { return false; }

    if (num_elems < 1000 || num_elems > 5000000) {
        bridge_log("  GUObjectArray: NumElements=%d out of [1000,5M]",
                   num_elems);
        return false;
    }

    /* Objects** = p + GUOBJARRAY_OBJECTS_OFF */
    uintptr_t chunks_ptr = seh_read_ptr(p + GUOBJARRAY_OBJECTS_OFF);
    if (chunks_ptr < 0x10000 || chunks_ptr >= 0x7F0000000000ULL) {
        bridge_log("  GUObjectArray: Objects** invalid 0x%llX",
                   (unsigned long long)chunks_ptr);
        return false;
    }

    /* Objects*[0] = first chunk must be readable */
    uintptr_t chunk0 = seh_read_ptr((void*)chunks_ptr);
    if (chunk0 < 0x10000 || chunk0 >= 0x7F0000000000ULL) {
        bridge_log("  GUObjectArray: Objects[0] invalid 0x%llX",
                   (unsigned long long)chunk0);
        return false;
    }

    /* First FUObjectItem in chunk0: Object* at +0 must look valid */
    uintptr_t first_obj = seh_read_ptr((void*)chunk0);
    if (first_obj < 0x10000) {
        bridge_log("  GUObjectArray: first object 0x%llX invalid",
                   (unsigned long long)first_obj);
        return false;
    }

    bridge_log("  GUObjectArray valid: %d objects, "
               "Objects**=0x%llX, chunk[0]=0x%llX",
               num_elems, (unsigned long long)chunks_ptr,
               (unsigned long long)chunk0);
    return true;
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

    /* FUObjectItem::Object at offset 0 within the item */
    uintptr_t item_addr = chunk + (uintptr_t)within_idx * FUOBJECTITEM_STRIDE;
    return (void*)seh_read_ptr((void*)item_addr);
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

        /* Must have FExec secondary vtable at +0x28 */
        uintptr_t fexec_vptr = seh_read_ptr((uint8_t*)obj + 0x28);
        if (fexec_vptr < mod_start || fexec_vptr >= mod_end) continue;
        if (fexec_vptr == vptr) continue;

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
        if (fexec_cnt < 3 || fexec_cnt > 8) continue;

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

/*
 * Find UWorld via GUObjectArray structural scan.
 *
 * UE4SS captures UWorld as an InWorld parameter of ULocalPlayer::Exec().
 * When the game is idle (no player input triggers FExec), that hook never
 * fires.  This function actively scans GUObjectArray using structural
 * fingerprints -- no FName::ToString or RTTI required.
 *
 * UWorld fingerprint (UE5 x64 MSVC layout):
 *   1. Primary vtable at +0x00 is inside the game module.
 *   2. Primary vtable differs from GEngine's vtable.
 *   3. Primary vtable has >= 50 entries (UWorld is large, like GEngine).
 *   4. FExec secondary vtable at +0x28 with 3-8 entries (UWorld : FExec).
 *   5. OuterPrivate at +0x20 is non-null (UWorld's outer = level UPackage).
 *   6. Outer's OuterPrivate at outer+0x20 is null (root UPackage has no parent).
 *
 * Requires: g_guobjectarray_found && g_engine_found.
 */
static bool find_uworld_via_guobjectarray()
{
    if (!g_guobjectarray_found || !g_guobjectarray) return false;
    if (!g_engine_ptr) return false;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start  = (uintptr_t)rgn.base;
    uintptr_t mod_end    = mod_start + rgn.size;
    uintptr_t engine_vptr = seh_read_ptr(g_engine_ptr); /* exclude GEngine */

    int32_t num_elems = guobjectarray_num_elements();
    bridge_log("=== UWorld scan via GUObjectArray (%d objects) ===",
               num_elems);

    for (int32_t i = 0; i < num_elems; i++) {
        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x7F0000000000ULL) continue;

        /* 1+2. Primary vtable in module, not GEngine */
        uintptr_t vptr = seh_read_ptr(obj);
        if (vptr < mod_start || vptr >= mod_end) continue;
        if (vptr == engine_vptr) continue;

        /* 4. FExec secondary vtable at +0x28 */
        uintptr_t fexec_vptr = seh_read_ptr((uint8_t*)obj + 0x28);
        if (fexec_vptr < mod_start || fexec_vptr >= mod_end) continue;
        if (fexec_vptr == vptr) continue;

        /* Validate FExec vtable: exactly 3-8 valid entries */
        void* fn0 = (void*)seh_read_ptr((void*)fexec_vptr);
        void* fn1 = (void*)seh_read_ptr((void*)(fexec_vptr + 8));
        if (!validate_function_ptr(fn0) || !validate_function_ptr(fn1)) continue;
        int fexec_cnt = 2;
        for (int vi = 2; vi <= 8; vi++) {
            void* fn = (void*)seh_read_ptr((void*)(fexec_vptr + vi * 8));
            if (!validate_function_ptr(fn)) break;
            fexec_cnt++;
        }
        if (fexec_cnt < 3 || fexec_cnt > 8) continue;

        /* 3. Primary vtable has >= 50 entries (UWorld is large) */
        int vcnt = 0;
        for (int vi = 0; vi < 256; vi++) {
            void* fn = (void*)seh_read_ptr((void*)(vptr + vi * 8));
            if (!validate_function_ptr(fn)) break;
            vcnt++;
        }
        if (vcnt < 50) continue;

        /* 5. OuterPrivate at +0x20 must be a valid heap pointer */
        uintptr_t outer = seh_read_ptr((uint8_t*)obj + 0x20);
        if (outer < 0x10000 || outer >= 0x7F0000000000ULL) continue;

        /* 6. Outer's OuterPrivate must be null (root UPackage) */
        uintptr_t outer_outer = seh_read_ptr((void*)(outer + 0x20));
        if (outer_outer != 0) continue;

        /* UWorld found */
        bridge_log("  UWorld found: 0x%p "
                   "(vptr=0x%llX vcnt=%d outer=0x%llX)",
                   obj, (unsigned long long)vptr, vcnt,
                   (unsigned long long)outer);
        g_world_ptr = obj;
        return true;
    }

    bridge_log("  UWorld not found in GUObjectArray scan");
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
    if (g_fexec_hook_count >= 16) {
        bridge_log("  FExec hook table full");
        return false;
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

        /* Check for FExec vtable at UE4SS default offset 0x28 (= 40) */
        uintptr_t fexec_off = 0x28;
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
        if (vcnt < 3 || vcnt > 8) continue;

        /* This object has a valid FExec vtable -- hook it */
        if (install_fexec_hook_on(fexec_vptr, primary_vptr,
                                   mod_start, mod_end))
            hooked_new++;
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

    /* UWorld captured by FExec hooks from ULocalPlayer::Exec.
     * NULL is accepted -- CVars and showflag work without it. */
    void* world = g_world_ptr;

    /* Use GEngine's original Exec to avoid recursion.
     * GEngine hook is always the first entry in g_fexec_hook_table. */
    FExecExecFn exec_fn = g_fexec_exec;
    if (g_fexec_hook_count > 0)
        exec_fn = g_fexec_hook_table[0].original;

    bool cmd_ret = false;
    if (seh_call_fexec(exec_fn, this_fexec,
                        world, wcmd.data(), ar, &cmd_ret)) {
        bridge_log("  OK ret=%d", (int)cmd_ret);
        return cmd_ret;
    }

    bridge_log("  ERROR: FExec::Exec crashed");
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
