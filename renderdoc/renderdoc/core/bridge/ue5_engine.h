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

/* UWorld pointer -- needed for game commands (ToggleDebugCamera etc.) */
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
        auto ranges = get_readable_ranges(rgn.base, rgn.size);
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

/*
 * Master GEngine finder: tries all methods in order.
 */
static bool find_gengine()
{
    /* Method 1: env var override */
    const char* env_offset = getenv("CAPTUREAI_GENGINE_OFFSET");
    if (env_offset) {
        uintptr_t offset = strtoull(env_offset, NULL, 16);
        if (find_gengine_via_offset(offset))
            return true;
    }

    /* Method 2: automatic string xref scan */
    bridge_log("Starting GEngine auto-scan...");
    if (find_gengine_via_string_xref())
        return true;

    bridge_log("WARNING: GEngine not found automatically. "
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

    /* Dump first 64 bytes for diagnostics */
    bridge_log("  --- Object layout ---");
    for (int off = 0; off <= 64; off += 8) {
        uintptr_t val = seh_read_ptr(obj + off);
        bridge_log("  obj+%2d: 0x%016llX",
                   off, (unsigned long long)val);
    }

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

/* -- UWorld finder ------------------------------------------------- */

/*
 * UE5's FExec::Exec(UWorld*, cmd, ar) needs a valid UWorld* to route
 * game commands (ToggleDebugCamera, etc.) through PlayerController.
 * CVars and ShowFlag work with NULL, but game commands return false.
 *
 * Strategy: find GWorld via the same string xref technique.
 * GWorld is a TObjectPtr<UWorld> global, always present in UE5.
 */
/*
 * Strategy A: Scan .data/.bss near GEngine's global address.
 * In UE5, global pointers (GEngine, GWorld, GIsEditor, etc.) are
 * all stored in the same data section, typically within +-8KB.
 */
/*
 * Helper: check if a pointer looks like a valid UObject on the heap.
 * Requires vtable in module, ClassPrivate at offset +16 also looks valid.
 * Returns the vtable address or 0 if not a UObject.
 */
static uintptr_t check_uobject_ptr(void* ptr,
                                    uintptr_t mod_start, uintptr_t mod_end)
{
    if (!ptr || (uintptr_t)ptr < 0x10000) return 0;
    uintptr_t vtable = seh_read_ptr(ptr);
    if (vtable < mod_start || vtable >= mod_end) return 0;

    /* Check first vtable entry is a valid function */
    void* fn0 = (void*)seh_read_ptr((void*)vtable);
    if (!validate_function_ptr(fn0)) return 0;

    /* Check ClassPrivate at offset 16 -- should be a valid pointer */
    uintptr_t class_ptr = seh_read_ptr((uint8_t*)ptr + 16);
    if (class_ptr < 0x10000) return 0;

    /* ClassPrivate should itself have a vtable in module (it's a UClass) */
    uintptr_t class_vt = seh_read_ptr((void*)class_ptr);
    if (class_vt < mod_start || class_vt >= mod_end) return 0;

    return vtable;
}

/*
 * Strategy A: Scan GEngine OBJECT members for UWorld-like pointers.
 *
 * GEngine has hundreds of members. Some are UObject* pointing to
 * UFont, UGameViewportClient, etc. UWorld is referenced through
 * WorldList (TIndirectArray<FWorldContext>) and GameViewport.
 *
 * We scan the GEngine heap object for any UObject* whose:
 *   - vtable is in module (not NULL, not external DLL)
 *   - ClassPrivate is valid (UObject header at +16)
 *   - vtable differs from GEngine's (different class)
 *   - UClass differs from common types (UFont, etc.)
 *
 * We collect unique (vtable, ClassPrivate) pairs and pick the
 * most likely UWorld candidate.
 */
struct WorldCandidate {
    void*     ptr;
    uintptr_t vtable;
    uintptr_t class_ptr;
    int       offset_in_engine;   /* where in GEngine we found it */
};

static bool find_world_in_engine_object()
{
    if (!g_engine_ptr) return false;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end = mod_start + rgn.size;

    uint8_t* obj = (uint8_t*)g_engine_ptr;
    uintptr_t engine_vt = seh_read_ptr(obj);
    uintptr_t engine_class = seh_read_ptr(obj + 16);

    bridge_log("  Scanning GEngine object members for UWorld...");
    bridge_log("    GEngine vtable=0x%llX class=0x%llX",
               (unsigned long long)engine_vt,
               (unsigned long long)engine_class);

    /* Track unique classes we've seen (to filter duplicates like UFont) */
    const int MAX_CLASSES = 64;
    uintptr_t seen_classes[MAX_CLASSES];
    int       seen_class_count[MAX_CLASSES];
    int       num_classes = 0;

    WorldCandidate best = {0};

    /* Scan object at offsets 48 (after FExec vptr) to 8192 */
    for (int off = 48; off < 8192; off += 8) {
        void* member = (void*)seh_read_ptr(obj + off);
        uintptr_t vt = check_uobject_ptr(member, mod_start, mod_end);
        if (!vt) continue;
        if (member == (void*)g_engine_ptr) continue;
        if (vt == engine_vt) continue;  /* same class as GEngine */

        uintptr_t cls = seh_read_ptr((uint8_t*)member + 16);
        if (cls == engine_class) continue;

        /* Track class frequency */
        int ci = -1;
        for (int i = 0; i < num_classes; i++) {
            if (seen_classes[i] == cls) { ci = i; break; }
        }
        if (ci >= 0) {
            seen_class_count[ci]++;
        } else if (num_classes < MAX_CLASSES) {
            ci = num_classes++;
            seen_classes[ci] = cls;
            seen_class_count[ci] = 1;
        }

        /* UWorld typically appears only once or twice in GEngine.
         * UFont appears 6+ times. Skip classes with many instances. */
        if (ci >= 0 && seen_class_count[ci] > 3) continue;

        /* Check OuterPrivate at offset 32. UWorld's outer is typically
         * a UPackage (which itself has a different class). This helps
         * distinguish UWorld from small helper objects. */
        uintptr_t outer = seh_read_ptr((uint8_t*)member + 32);
        bool has_outer = (outer > 0x10000);

        /* UWorld should have a valid OuterPrivate (UPackage) */
        if (!has_outer) continue;

        /* Best candidate: first unique-class UObject with outer */
        if (!best.ptr) {
            best.ptr = member;
            best.vtable = vt;
            best.class_ptr = cls;
            best.offset_in_engine = off;
        }

        bridge_log("    obj+%d: UObject ptr=0x%p vt=0x%llX "
                   "class=0x%llX outer=%s",
                   off, member, (unsigned long long)vt,
                   (unsigned long long)cls,
                   has_outer ? "yes" : "no");
    }

    bridge_log("    %d unique classes found in GEngine members",
               num_classes);

    if (!best.ptr) {
        bridge_log("  UWorld not found in GEngine object members");
        return false;
    }

    /* For now, use the first candidate. If wrong, the user will see
     * ret=0 for ToggleDebugCamera and we can refine. */
    g_world_ptr = best.ptr;
    bridge_log("  UWorld candidate from GEngine+%d: 0x%p",
               best.offset_in_engine, best.ptr);
    return true;
}

/*
 * Strategy B: Scan the PE .data section for GWorld global.
 * GWorld is a UWorld* global in the writable data section.
 * We scan all writable pages for non-null UObject pointers with
 * a different class from GEngine.
 */
static bool find_gworld_in_data_section()
{
    if (!g_engine_ptr) return false;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end = mod_start + rgn.size;
    uintptr_t engine_vt = seh_read_ptr(g_engine_ptr);
    uintptr_t engine_class = seh_read_ptr((uint8_t*)g_engine_ptr + 16);

    bridge_log("  Scanning .data section for GWorld...");

    /* Use VirtualQuery to find writable pages (likely .data/.bss) */
    const uint8_t* addr = rgn.base;
    const uint8_t* end = rgn.base + rgn.size;
    int pages_scanned = 0;
    int ptrs_checked = 0;
    int candidates = 0;

    while (addr < end) {
        MEMORY_BASIC_INFORMATION mbi = {};
        if (VirtualQuery(addr, &mbi, sizeof(mbi)) == 0) break;

        const uint8_t* region_base = (const uint8_t*)mbi.BaseAddress;
        size_t region_size = mbi.RegionSize;

        /* Only scan writable pages (.data, .bss) */
        bool writable = (mbi.State == MEM_COMMIT) &&
            (mbi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE |
                            PAGE_WRITECOPY | PAGE_EXECUTE_WRITECOPY)) &&
            !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD));

        if (writable) {
            pages_scanned++;
            const uint8_t* r_start = (region_base < rgn.base) ?
                                      rgn.base : region_base;
            const uint8_t* r_end = region_base + region_size;
            if (r_end > end) r_end = end;

            /* Align to 8 bytes */
            uintptr_t s = ((uintptr_t)r_start + 7) & ~(uintptr_t)7;
            uintptr_t e = (uintptr_t)r_end - 8;

            for (uintptr_t a = s; a <= e; a += 8) {
                void* ptr = *(void**)a;
                ptrs_checked++;
                uintptr_t vt = check_uobject_ptr(ptr, mod_start, mod_end);
                if (!vt) continue;
                if (ptr == (void*)g_engine_ptr) continue;
                if (vt == engine_vt) continue;

                uintptr_t cls = seh_read_ptr((uint8_t*)ptr + 16);
                if (cls == engine_class) continue;

                /* Check OuterPrivate */
                uintptr_t outer = seh_read_ptr((uint8_t*)ptr + 32);
                if (outer < 0x10000) continue;

                candidates++;
                bridge_log("    .data+0x%llX: ptr=0x%p vt=0x%llX "
                           "class=0x%llX",
                           (unsigned long long)(a - mod_start),
                           ptr, (unsigned long long)vt,
                           (unsigned long long)cls);

                /* First match = GWorld (most common UObject global) */
                g_world_ptr = ptr;
                bridge_log("  GWorld FOUND in .data: 0x%p "
                           "(%d pages, %d ptrs checked)",
                           ptr, pages_scanned, ptrs_checked);
                return true;
            }
        }

        addr = region_base + region_size;
        if (addr <= region_base) break;
    }

    bridge_log("  GWorld not found in .data "
               "(%d pages, %d ptrs, %d candidates)",
               pages_scanned, ptrs_checked, candidates);
    return false;
}

/*
 * Refresh g_world_ptr.  Called periodically (not on every command).
 * Only uses safe memory-scan approaches, never calls vtable functions.
 */
/*
 * Find UWorld using all available strategies.
 * Called at startup and can be retriggered via TCP command.
 */
static bool find_uworld()
{
    if (g_world_ptr) return true;

    bridge_log("=== UWorld Search ===");

    /* Strategy A: scan GEngine object members */
    if (find_world_in_engine_object())
        return true;

    /* Strategy B: scan entire .data section */
    if (find_gworld_in_data_section())
        return true;

    bridge_log("  All UWorld strategies failed");
    return false;
}
    if (!find_gworld_near_gengine())
        find_world_via_getworld();
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
static int g_exec_crash_count = 0;

static bool exec_console_command_internal(const char* cmd)
{
    bridge_log("  exec: %s (world=%p)", cmd,
               g_world_ptr);

    if (!g_fexec_exec) {
        bridge_log("  [SKIP] FExec::Exec not available");
        return false;
    }

    if (g_exec_crash_count >= 3) {
        bridge_log("  [SKIP] FExec disabled after %d crashes", g_exec_crash_count);
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

    bool cmd_ret = false;
    if (seh_call_fexec(g_fexec_exec, this_fexec,
                        g_world_ptr, wcmd.data(), ar, &cmd_ret)) {
        bridge_log("  OK ret=%d", (int)cmd_ret);
        g_exec_crash_count = 0;  /* reset on success */
        return cmd_ret;
    }

    g_exec_crash_count++;
    bridge_log("  ERROR: FExec::Exec crashed (count=%d/3)",
               g_exec_crash_count);
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
