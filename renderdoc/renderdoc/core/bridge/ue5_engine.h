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

/* UWorld pointer -- set by GUObjectArray scan or captured by FExec hooks.
 * g_world_from_gua: true when g_world_ptr was set by the GUA scan
 * (reliable). When true, FExec hooks do NOT overwrite it -- the hook
 * captures many different pointers per second, most of which are wrong. */
static void*             g_world_ptr = nullptr;
static bool              g_world_from_gua = false;

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
#define FUOBJECTARRAY_CHUNK_SHIFT 16   /* NumElementsPerChunk = 64K = 1<<16 */
#define FUOBJECTARRAY_CHUNK_MASK  0xFFFF

/* ============================================================
 * UEVersionLayout -- per-engine-version memory offset table.
 *
 * Add a new entry when a game is confirmed on a different UE version.
 * Set g_ue_layout = &k_layout_XXX at startup (or auto-detect).
 * See docs/ue_memory_layout.md for details and verification status.
 * ============================================================ */
struct UEVersionLayout {
    const char* name;

    /* FUObjectItem */
    int  fuobjectitem_stride;    /* 24=Shipping, 32=Dev/WithVerseVM */
    int  fuobjectitem_obj_off;   /* offset of UObjectBase* inside item */

    /* FField chain (UStruct::ChildProperties walk) */
    int  ffield_next_off;        /* FField::Next pointer */
    int  ffield_name_off;        /* FField::NamePrivate (FName ComparisonIndex) */
    int  fprop_offset_off;       /* FProperty::Offset_Internal */
    int  ustruct_childprops_off; /* UStruct::ChildProperties -- 0x50 all known UE5 */
    int  ustruct_super_off;      /* UStruct::SuperStruct      -- 0x40 all known UE5 */

    /* UPlayer / ULocalPlayer chain */
    int  uplayer_pc_off;         /* UPlayer::PlayerController (APlayerController*) */
    int  ulp_vc_off;             /* ULocalPlayer::ViewportClient (UGameViewportClient*) */

    /* UEngine / UGameViewportClient */
    int  uengine_gvc_off;        /* UEngine::GameViewport */
    int  ugvc_world_off;         /* UGameViewportClient::World */

    /* FMinimalViewInfo inside FCameraCacheEntry */
    bool fmvi_is_lwc;            /* true=double (UE5 LWC), false=float (UE4/non-LWC) */
    int  fcce_pov_off;           /* FCameraCacheEntry::POV offset */
    /* Offsets relative to start of FMinimalViewInfo: */
    int  fmvi_loc_x, fmvi_loc_y, fmvi_loc_z;    /* Location */
    int  fmvi_pitch, fmvi_yaw,   fmvi_roll;      /* Rotation */
    int  fmvi_fov;                               /* FOV (always float) */

    /* FMinimalViewInfo direct offset from APlayerCameraManager base.
     * Non-zero = FField+scan skipped; set directly.
     * 0 = unknown; use FField reflection then scan to discover.
     * Discovered value should be added to the layout for subsequent runs. */
    int  cam_pov_direct_off;

    /* APlayerController -> APlayerCameraManager UUU-style probe */
    int  pc_pcm_start;           /* probe range start */
    int  pc_pcm_end;             /* probe range end */
    int  pc_pcm_step;            /* probe step (always 8) */
};

/* UE5.7 -- CONFIRMED StackOBot UE5.7 Dev (stride=32, LWC doubles)
 * cam_pov_direct_off=0x360: VERIFIED via ToggleDebugCamera -- camera
 * position at manager+0x360 matched in-game view (xyz=9450,-14230,1216 fov=90).
 * CameraCachePrivate at manager+0x358 (POV = CachEntry+0x08 = manager+0x360). */
static const UEVersionLayout k_layout_ue57 = {
    "UE5.7",
    32,   0x08,                          /* FUObjectItem stride=32, obj at +0x08 */
    0x18, 0x20, 0x44, 0x50, 0x40,       /* FField era2 */
    0x30, 0x78,                          /* UPlayer chain */
    0x200, 0x78,                         /* UEngine/GVC */
    true,  0x08,                         /* LWC double, POV at FCCEntry+0x08 */
    0x00,  0x08,  0x10,                  /* Location doubles */
    0x18,  0x20,  0x28,                  /* Rotation doubles */
    0x30,                                /* FOV float */
    0x360,                               /* cam_pov_direct_off: VERIFIED StackOBot */
    0x388, 0x398, 8,                     /* PCM in PC: VERIFIED PC+0x390 (StackOBot, pass2 xval) */
};

/* UE5.3-5.6 -- INFERRED (FField era2, LWC, shipping stride=24)
 * cam_pov_direct_off=0: unknown, will use FField reflection + scan */
static const UEVersionLayout k_layout_ue53 = {
    "UE5.3-5.6",
    24,   0x00,
    0x18, 0x20, 0x44, 0x50, 0x40,
    0x30, 0x78,
    0x200, 0x78,
    true,  0x08,
    0x00,  0x08,  0x10,
    0x18,  0x20,  0x28,
    0x30,
    0,                                   /* cam_pov_direct_off: unknown */
    0x2A0, 0x360, 8,
};

/* UE5.0-5.2 -- INFERRED (FField era1 introduced with LWC)
 * cam_pov_direct_off=0: unknown */
static const UEVersionLayout k_layout_ue50 = {
    "UE5.0-5.2",
    24,   0x00,
    0x20, 0x28, 0x4C, 0x50, 0x40,       /* FField era1 */
    0x30, 0x78,
    0x200, 0x78,
    true,  0x08,
    0x00,  0x08,  0x10,
    0x18,  0x20,  0x28,
    0x30,
    0,                                   /* cam_pov_direct_off: unknown */
    0x2A0, 0x340, 8,
};

/* UE4.27 -- INFERRED (float layout, FField era1)
 * cam_pov_direct_off=0: unknown */
static const UEVersionLayout k_layout_ue427 = {
    "UE4.27",
    24,   0x00,
    0x20, 0x28, 0x4C, 0x50, 0x40,
    0x30, 0x78,
    0x200, 0x78,
    false, 0x10,                         /* float, POV at FCCEntry+0x10 (SIMD) */
    0x00,  0x04,  0x08,                  /* Location floats */
    0x0C,  0x10,  0x14,                  /* Rotation floats */
    0x18,                                /* FOV */
    0,                                   /* cam_pov_direct_off: unknown */
    0x2A0, 0x2C0, 8,
};

/* Active layout -- default UE5.7; override at startup for other games */
static const UEVersionLayout* g_ue_layout = &k_layout_ue57;

/*
 * FUObjectItem size depends on BUILD CONFIG, NOT engine version:
 *   0x18 (24B) -- Standard Shipping: Object*(8)+Flags(4)+ClusterRoot(4)+Serial(4)+Pad(4)
 *   0x20 (32B) -- Development/Debug or WITH_VERSE_VM: +0x08=WeakHandle, +0x08=Object*
 *   0x10 (16B) -- UE_PACK_FUOBJECT_ITEM: Object* in low bits (mask &~7)
 * Detected at runtime via GEngine cross-validation.
 * Confirmed: StackOBot UE5.7 Dev -> stride=32, obj_off=0x08
 */
static int g_fuobjectitem_stride    = 24;   /* default Shipping; detected in detect_fuobjectitem_stride() */
static int g_fuobjectitem_object_off = 0;   /* Object* at start for stride=24; 0x08 for stride=32 */

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

static FExecHookEntry     g_fexec_hook_table[64];
static int                g_fexec_hook_count = 0;

/* (passive g_localplayer_fexec removed: all object lookup via GUA+FName) */

/* -- Debug break support -------------------------------------------
 * When g_debug_break_armed is set (via __bridge_arm_break TCP command),
 * bridge calls __debugbreak() at the next UWorld/LocalPlayer discovery.
 * Attach WinDbg / x64dbg BEFORE arming, then trigger a rescan from the UI.
 * One-shot: auto-disarms after the first break fires.
 */
static std::atomic<bool> g_debug_break_armed{false};

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
static bool find_gengine_via_guobjectarray();  /* forward decl -- used in Method B below */

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
static bool validate_function_ptr(void* fn);         /* forward decl */
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

    uintptr_t item_addr = chunk + (uintptr_t)within_idx * g_fuobjectitem_stride;
    uintptr_t obj = seh_read_ptr((void*)(item_addr + g_fuobjectitem_object_off));
    /* Packed layout: low 3 bits hold flags; mask before returning */
    if (g_fuobjectitem_stride == 16) obj &= ~(uintptr_t)7;
    return (void*)obj;
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
 * detect_fuobjectitem_stride() -- determine FUObjectItem stride at runtime.
 *
 * Cross-validates using GEngine.InternalIndex (at UObjectBase+0x0C).
 * Must be called after both g_guobjectarray and g_engine_ptr are set.
 *
 * Configs tested:
 *   (24, 0x00) -- Standard Shipping (default)
 *   (32, 0x08) -- Development / WITH_VERSE_VM [StackOBot UE5.7 confirmed]
 *   (32, 0x10) -- Alt 32B layout
 *   (16, 0x00) -- UE_PACK_FUOBJECT_ITEM
 */
static void detect_fuobjectitem_stride()
{
    if (!g_guobjectarray || !g_engine_ptr) return;

    uintptr_t chunks_ptr = seh_read_ptr((uint8_t*)g_guobjectarray + GUOBJARRAY_OBJECTS_OFF);
    uintptr_t chunk0 = seh_read_ptr((void*)chunks_ptr);
    if (!chunk0) { bridge_log("  stride detect: chunk0 not readable"); return; }

    int32_t ge_idx = 0;
    __try { ge_idx = *(int32_t*)((uint8_t*)g_engine_ptr + 0x0C); }
    __except(EXCEPTION_EXECUTE_HANDLER) { return; }
    if (ge_idx <= 0 || ge_idx >= 2000000) {
        bridge_log("  stride detect: GEngine.InternalIndex=%d invalid", ge_idx);
        return;
    }

    static const struct { int stride; int obj_off; } cfgs[] = {
        {24, 0x00}, {32, 0x08}, {32, 0x10}, {16, 0x00},
    };
    for (int ci = 0; ci < 4; ci++) {
        int s = cfgs[ci].stride, off = cfgs[ci].obj_off;
        uintptr_t probe = seh_read_ptr(
            (void*)(chunk0 + (uintptr_t)ge_idx * s + off));
        if (s == 16) probe &= ~(uintptr_t)7;
        if (probe == (uintptr_t)g_engine_ptr) {
            g_fuobjectitem_stride    = s;
            g_fuobjectitem_object_off = off;
            bridge_log("  FUObjectItem CONFIRMED: stride=%d obj_off=0x%02X "
                       "(GEngine idx=%d cross-validated)", s, off, ge_idx);
            return;
        }
        bridge_log("  FUObjectItem probe stride=%d off=0x%02X -> 0x%llX (need 0x%llX)",
                   s, off, (unsigned long long)probe, (unsigned long long)(uintptr_t)g_engine_ptr);
    }
    bridge_log("  FUObjectItem detect FAILED -- keeping stride=%d off=0x%02X",
               g_fuobjectitem_stride, g_fuobjectitem_object_off);
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

/* ---- FName Pool Utilities ---------------------------------------- */

/*
 * FNamePool (UE5) block layout:
 *   FNameEntry header (uint16):
 *     UE4: (len << 1) | bIsWide
 *     UE5: (len << 6) | (probeHash << 1) | bIsWide
 *   Followed by char[len] or wchar_t[len].
 *
 * ComparisonIndex encoding:
 *   bits[31:16] = block_idx
 *   bits[15: 0] = word_off   (byte_offset_in_block / 2)
 *
 * FNamePool struct (UE5, MSVC x64, in module .bss):
 *   +0x00  SRWLOCK Lock        (8 bytes)
 *   +0x08  uint32  CurrentBlock
 *   +0x0C  uint32  CurrentByteCursor
 *   +0x10  uint8*  Blocks[8192]   (8192 pointers to 128KB heap blocks)
 *
 * Block size: word_off max = 0xFFFF -> max byte_off = 0x1FFFE = ~128KB.
 */

#define FNAMEPOOL_BLOCKS_OFF  0x10
#define FNAMEPOOL_MAX_BLOCKS  8192
#define FNAMEPOOL_BLOCK_BYTES (128 * 1024)

static int       g_fname_header_shift = 1;  /* 1=UE4, 6=UE5; set on block0 find */
static uintptr_t g_fnamepool_block0   = 0;  /* FNamePool block 0 heap base */
static uintptr_t g_fnamepool_global   = 0;  /* FNamePool struct in module .bss */

/* Extract name length from raw uint16 header */
static inline int fname_entry_len(uint16_t hdr)
{
    return (int)(hdr >> g_fname_header_shift);
}

/* Check if addr is FNamePool block 0 (starts with FNameEntry "None").
 * Detects UE4 vs UE5 header format and sets g_fname_header_shift. */
static bool fname_block0_matches_none(uintptr_t addr)
{
    uint8_t b0, b1, b2, b3, b4, b5;
    __try {
        b0 = *(uint8_t*)(addr + 0); b1 = *(uint8_t*)(addr + 1);
        b2 = *(uint8_t*)(addr + 2); b3 = *(uint8_t*)(addr + 3);
        b4 = *(uint8_t*)(addr + 4); b5 = *(uint8_t*)(addr + 5);
    }
    __except(EXCEPTION_EXECUTE_HANDLER) { return false; }

    if (b2 != 'N' || b3 != 'o' || b4 != 'n' || b5 != 'e') return false;
    if (b0 & 1) return false;  /* bIsWide must be 0 */
    /* UE4: header=0x0008 -> b1==0x00, b0==0x08 */
    if (b1 == 0x00 && b0 == 0x08) { g_fname_header_shift = 1; return true; }
    /* UE5: header=(4<<6)|(hash<<1) -> b1==0x01 (high byte of len field) */
    if (b1 == 0x01) { g_fname_header_shift = 6; return true; }
    return false;
}

/* Return heap pointer for FNamePool block bi. */
static uintptr_t fname_get_block(uint32_t bi)
{
    if (bi == 0 && g_fnamepool_block0) return g_fnamepool_block0;
    if (g_fnamepool_global && bi < FNAMEPOOL_MAX_BLOCKS)
        return seh_read_ptr(
            (void*)(g_fnamepool_global + FNAMEPOOL_BLOCKS_OFF + bi * 8));
    return 0;
}

/* Locate FNamePool struct in module .bss (for multi-block access).
 * Method 1: export symbol "GNamePool". Method 2: backref scan from block0. */
static uintptr_t find_fnamepool_global()
{
    if (g_fnamepool_global) return g_fnamepool_global;

    /* Method 1: export */
    static const char* exports[] = {"GNamePool","?GNamePool@@3VFNamePool@@A"};
    for (int ei = 0; ei < 2; ei++) {
        uintptr_t p = (uintptr_t)GetProcAddress(GetModuleHandleA(NULL), exports[ei]);
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

    /* Method 2: backref scan -- scan PAGE_READWRITE module regions for ptr==block0 */
    if (!g_fnamepool_block0) return 0;
    ModuleRegion rgn;
    if (!get_main_module(rgn)) return 0;
    uintptr_t mod_base = (uintptr_t)rgn.base;
    uintptr_t mod_end  = mod_base + rgn.size;

    uintptr_t cur = mod_base;
    while (cur < mod_end) {
        MEMORY_BASIC_INFORMATION mbi2 = {};
        if (!VirtualQuery((void*)cur, &mbi2, sizeof(mbi2))) { cur += 0x1000; continue; }
        uintptr_t rb = (uintptr_t)mbi2.BaseAddress;
        uintptr_t re = rb + mbi2.RegionSize;
        if (re > mod_end) re = mod_end;
        bool writable = (mbi2.State == MEM_COMMIT) &&
            (mbi2.Protect & (PAGE_READWRITE | PAGE_WRITECOPY |
                              PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY));
        if (writable) {
            for (uintptr_t scan = rb; scan < re - 8; scan += 8) {
                if (seh_read_ptr((void*)scan) != g_fnamepool_block0) continue;
                uintptr_t pool_cand = scan - FNAMEPOOL_BLOCKS_OFF;
                int32_t cur_blk = 0;
                __try { cur_blk = *(int32_t*)(pool_cand + 0x08); }
                __except(EXCEPTION_EXECUTE_HANDLER) { cur_blk = 9999; }
                if (cur_blk < 0 || cur_blk >= 128) continue;
                g_fnamepool_global = pool_cand;
                bridge_log("  FNamePool global=0x%llX (backref, CurrentBlock=%d)",
                           (unsigned long long)pool_cand, cur_blk);
                return pool_cand;
            }
        }
        cur = re;
    }
    bridge_log("  FNamePool global: not found");
    return 0;
}

/* Locate FNamePool block 0.
 * Method 1: export (also sets global). Method 2: VirtualQuery heap scan. */
static uintptr_t find_fnamepool_block0()
{
    if (g_fnamepool_block0) return g_fnamepool_block0;
    if (find_fnamepool_global()) return g_fnamepool_block0;

    MEMORY_BASIC_INFORMATION mbi = {};
    uintptr_t addr = 0x10000;
    int checked = 0;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return 0;
    uintptr_t mod_base = (uintptr_t)rgn.base;
    uintptr_t mod_end  = mod_base + rgn.size;

    while (addr < 0x800000000000ULL) {
        if (!VirtualQuery((void*)addr, &mbi, sizeof(mbi)))
            { addr += 0x10000; continue; }
        uintptr_t base = (uintptr_t)mbi.BaseAddress;
        uintptr_t end  = base + mbi.RegionSize;
        bool skip = (mbi.State != MEM_COMMIT)
            || !(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE
                                | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE))
            || (base < mod_end && end > mod_base)  /* overlaps module */
            || mbi.RegionSize < (64 * 1024);        /* < 64KB */
        if (!skip) {
            checked++;
            if (fname_block0_matches_none(base)) {
                uint16_t next_hdr = 0;
                __try { next_hdr = *(uint16_t*)(base + 6); }
                __except(EXCEPTION_EXECUTE_HANDLER) {}
                int next_len = fname_entry_len(next_hdr);
                if (next_hdr == 0 || (next_len >= 1 && next_len <= 256 && !(next_hdr & 1))) {
                    g_fnamepool_block0 = base;
                    bridge_log("  FNamePool block0=0x%llX fmt=%s (%d regions checked)",
                               (unsigned long long)base,
                               g_fname_header_shift == 6 ? "UE5" : "UE4", checked);
                    find_fnamepool_global();
                    return base;
                }
            }
        }
        addr = end;
    }
    bridge_log("  FNamePool block0: not found (%d regions)", checked);
    return 0;
}

/*
 * get_fname_cmpidx_for(target) -- search all FNamePool blocks for a name.
 * Returns full ComparisonIndex ((block_idx << 16) | word_off), or 0xFFFFFFFF.
 * Block 0 = engine names; block 1+ = game-specific names (need g_fnamepool_global).
 */
static uint32_t get_fname_cmpidx_for(const char* target)
{
    uintptr_t block0 = find_fnamepool_block0();
    if (!block0) return 0xFFFFFFFF;

    int tlen = (int)strlen(target);

    /* How many blocks to search */
    uint32_t max_block = 0;
    if (g_fnamepool_global) {
        int32_t cur_blk = 0;
        __try { cur_blk = *(int32_t*)(g_fnamepool_global + 0x08); }
        __except(EXCEPTION_EXECUTE_HANDLER) { cur_blk = 0; }
        if (cur_blk >= 0 && cur_blk < (int32_t)FNAMEPOOL_MAX_BLOCKS)
            max_block = (uint32_t)cur_blk;
    }

    for (uint32_t bi = 0; bi <= max_block; bi++) {
        uintptr_t block = (bi == 0) ? block0 : fname_get_block(bi);
        if (!block) continue;
        uintptr_t cursor  = block;
        uintptr_t blk_end = block + FNAMEPOOL_BLOCK_BYTES;
        while (cursor < blk_end - 2) {
            uint16_t hdr = 0;
            __try { hdr = *(uint16_t*)cursor; }
            __except(EXCEPTION_EXECUTE_HANDLER) { break; }
            if (hdr == 0) break;
            bool is_wide = (hdr & 1) != 0;
            int  len     = fname_entry_len(hdr);
            if (len < 1 || len > 512) break;
            if (!is_wide && len == tlen) {
                bool match = false;
                __try { match = (memcmp((void*)(cursor + 2), target, tlen) == 0); }
                __except(EXCEPTION_EXECUTE_HANDLER) {}
                if (match)
                    return (bi << 16) | (uint32_t)((cursor - block) >> 1);
            }
            int entry_bytes = 2 + (is_wide ? len * 2 : len);
            cursor += (uintptr_t)((entry_bytes + 1) & ~1);
        }
    }
    return 0xFFFFFFFF;
}

/*
 * resolve_fname(cmp_idx, buf, buf_size)
 *
 * Reverse lookup: ComparisonIndex -> ASCII string.
 * Returns buf (always NUL-terminated). On failure returns "?".
 */
static const char* resolve_fname(uint32_t cmp_idx, char* buf, int buf_size)
{
    if (buf_size < 2) { if (buf_size > 0) buf[0] = '\0'; return buf; }
    buf[0] = '?'; buf[1] = '\0';

    uint32_t block_idx = cmp_idx >> 16;
    uint32_t word_off  = cmp_idx & 0xFFFF;
    uintptr_t block = fname_get_block(block_idx);
    if (!block) return buf;

    uintptr_t entry_addr = block + (uintptr_t)word_off * 2;
    uint16_t hdr = 0;
    __try { hdr = *(uint16_t*)entry_addr; }
    __except(EXCEPTION_EXECUTE_HANDLER) { return buf; }

    if (hdr == 0) return buf;
    bool is_wide = (hdr & 1) != 0;
    int  len     = fname_entry_len(hdr);
    if (len < 1 || len > 512) return buf;

    int copy_len = (len < buf_size - 1) ? len : (buf_size - 1);
    if (!is_wide) {
        __try { memcpy(buf, (void*)(entry_addr + 2), copy_len); }
        __except(EXCEPTION_EXECUTE_HANDLER) { buf[0] = '?'; buf[1] = '\0'; return buf; }
    } else {
        /* Wide -> ASCII lossy conversion */
        __try {
            wchar_t* ws = (wchar_t*)(entry_addr + 2);
            for (int k = 0; k < copy_len; k++)
                buf[k] = (char)(ws[k] & 0x7F);
        }
        __except(EXCEPTION_EXECUTE_HANDLER) { buf[0] = '?'; buf[1] = '\0'; return buf; }
    }
    buf[copy_len] = '\0';
    return buf;
}

/* Helper: read an object's NamePrivate and ClassPrivate->NamePrivate as strings.
 * Writes to name_buf and class_buf. */
static void read_obj_names(void* obj, char* name_buf, int name_sz,
                           char* class_buf, int class_sz)
{
    name_buf[0] = '\0'; class_buf[0] = '\0';

    /* NamePrivate at UObjectBase+0x18, lo32 = ComparisonIndex */
    uint32_t name_idx = 0;
    __try { name_idx = *(uint32_t*)((uint8_t*)obj + 0x18); }
    __except(EXCEPTION_EXECUTE_HANDLER) { name_idx = 0xFFFFFFFF; }
    if (name_idx != 0xFFFFFFFF) resolve_fname(name_idx, name_buf, name_sz);

    /* ClassPrivate at UObjectBase+0x10 */
    uintptr_t class_ptr = seh_read_ptr((uint8_t*)obj + 0x10);
    if (class_ptr >= 0x10000) {
        uint32_t cls_name_idx = 0;
        __try { cls_name_idx = *(uint32_t*)((uint8_t*)class_ptr + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) { cls_name_idx = 0xFFFFFFFF; }
        if (cls_name_idx != 0xFFFFFFFF) resolve_fname(cls_name_idx, class_buf, class_sz);
    }
}

/* ---- UWorld cross-validation via GEngine pointer chain --------------- */

/*
 * cross_validate_world(candidate)
 *
 * Verify that a UWorld candidate is reachable from GEngine's member chain.
 * Scans up to 3 levels of indirection, which covers:
 *   Level 1: GEngine+X == candidate  (direct pointer member)
 *   Level 2: GEngine+X -> obj+Y == candidate  (e.g. GameViewport->World)
 *   Level 3: GEngine+X -> obj+Y -> obj2+Z == candidate  (WorldList path:
 *            GEngine->WorldList.Data[i] -> FWorldContext->ThisCurrentWorld)
 *
 * Returns true if the candidate is confirmed reachable from GEngine.
 */
static bool cross_validate_world(void* candidate)
{
    if (!candidate || !g_engine_ptr) return false;

    uint8_t* eng = (uint8_t*)g_engine_ptr;
    uintptr_t target = (uintptr_t)candidate;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;

    /* Level 1: direct member in GEngine */
    for (int off = 48; off < 8192; off += 8) {
        uintptr_t val = seh_read_ptr(eng + off);
        if (val == target) {
            bridge_log("    XVAL: GEngine+0x%X == UWorld 0x%p (direct)", off, candidate);
            return true;
        }
    }

    /* Level 2 + 3: indirect */
    for (int off = 48; off < 8192; off += 8) {
        uintptr_t val = seh_read_ptr(eng + off);
        if (val < 0x10000 || val >= 0x7F0000000000ULL) continue;
        if (val == target) continue;  /* already checked */
        /* Skip module-range pointers (vtable/code, not data) */
        if (val >= mod_start && val < mod_end) continue;

        /* Level 2: scan sub-object (e.g. GameViewport) */
        for (int sub = 0; sub < 1024; sub += 8) {
            uintptr_t sv = seh_read_ptr((void*)(val + sub));
            if (sv == target) {
                bridge_log("    XVAL: GEngine+0x%X -> +0x%X == UWorld 0x%p (2-level)",
                           off, sub, candidate);
                return true;
            }

            /* Level 3: one more hop (covers WorldList indirection) */
            if (sv < 0x10000 || sv >= 0x7F0000000000ULL) continue;
            if (sv >= mod_start && sv < mod_end) continue;
            for (int sub2 = 0; sub2 < 512; sub2 += 8) {
                uintptr_t sv2 = seh_read_ptr((void*)(sv + sub2));
                if (sv2 == target) {
                    bridge_log("    XVAL: GEngine+0x%X -> +0x%X -> +0x%X == "
                               "UWorld 0x%p (3-level/WorldList)",
                               off, sub, sub2, candidate);
                    return true;
                }
            }
        }
    }

    return false;
}

/* ---- UWorld via GUObjectArray + FName -------------------------------- */

/*
 * find_uworld_via_guobjectarray()
 *
 * For each GUObjectArray entry:
 *   1. Read obj->ClassPrivate (UObjectBase+0x10)
 *   2. Read ClassPrivate->NamePrivate lo32 = ComparisonIndex
 *   3. Compare against FName("World")
 *   4. Validate outer chain: obj->OuterPrivate (UObjectBase+0x20) is non-null
 *      (= UPackage), and UPackage->OuterPrivate == null (root object).
 *
 * Requires: g_guobjectarray_found, FNamePool found (find_fnamepool_block0).
 */
static bool find_uworld_via_guobjectarray()
{
    if (!g_guobjectarray_found || !g_guobjectarray) return false;

    uint32_t world_idx = get_fname_cmpidx_for("World");
    if (world_idx == 0xFFFFFFFF) {
        bridge_log("  find_uworld: FName('World') not found in FNamePool");
        return false;
    }
    int32_t num_elems = guobjectarray_num_elements();
    bridge_log("  find_uworld: FName('World')=0x%X -- scanning %d objects",
               world_idx, num_elems);

    /* Collect non-CDO UWorld candidates.
     * RF_ClassDefaultObject = 0x10 in ObjectFlags (UObjectBase+0x08). */
    struct UWorldCandidate { int32_t index; void* obj; uintptr_t outer; uint32_t flags; };
    UWorldCandidate candidates[16];
    int n_candidates = 0;
    int class_hits = 0;
    int cdo_skipped = 0;

    for (int32_t i = 0; i < num_elems; i++) {
        if (i > 0 && (i % 50000) == 0)
            bridge_log("  find_uworld progress: %d/%d hits=%d", i, num_elems, class_hits);

        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x800000000000ULL) continue;

        /* ClassPrivate at UObjectBase+0x10 */
        uintptr_t class_ptr = seh_read_ptr((uint8_t*)obj + 0x10);
        if (class_ptr < 0x10000) continue;

        /* UClass.NamePrivate lo32 = ComparisonIndex */
        uint32_t cmp_idx = 0;
        __try { cmp_idx = *(uint32_t*)((uint8_t*)class_ptr + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        if (cmp_idx != world_idx) continue;
        class_hits++;

        /* ObjectFlags at UObjectBase+0x08 */
        uint32_t obj_flags = 0;
        __try { obj_flags = *(uint32_t*)((uint8_t*)obj + 0x08); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        /* Read object name + class name for diagnostic logging */
        char obj_name[128], cls_name[128];
        read_obj_names(obj, obj_name, sizeof(obj_name), cls_name, sizeof(cls_name));

        /* Skip CDOs (RF_ClassDefaultObject = 0x10) */
        if (obj_flags & 0x10) {
            bridge_log("  UWorld [%d] 0x%p: CDO name='%s' class='%s' flags=0x%X -- skipped",
                       i, obj, obj_name, cls_name, obj_flags);
            cdo_skipped++;
            continue;
        }

        /* OuterPrivate at UObjectBase+0x20 */
        uintptr_t outer = seh_read_ptr((uint8_t*)obj + 0x20);
        if (outer < 0x10000 || outer >= 0x800000000000ULL) continue;
        /* outer (UPackage) must be a root: its OuterPrivate == null */
        uintptr_t outer_outer = seh_read_ptr((uint8_t*)outer + 0x20);
        if (outer_outer != 0) continue;

        /* Also read outer's name */
        char outer_name[128], outer_cls[128];
        read_obj_names((void*)outer, outer_name, sizeof(outer_name),
                       outer_cls, sizeof(outer_cls));

        bridge_log("  UWorld candidate #%d: [%d] obj=0x%p name='%s' class='%s' "
                   "flags=0x%X outer=0x%llX outer_name='%s'",
                   n_candidates, i, obj, obj_name, cls_name,
                   obj_flags, (unsigned long long)outer, outer_name);

        if (n_candidates < 16) {
            candidates[n_candidates].index = i;
            candidates[n_candidates].obj   = obj;
            candidates[n_candidates].outer = outer;
            candidates[n_candidates].flags = obj_flags;
            n_candidates++;
        } else {
            for (int j = 0; j < 15; j++) candidates[j] = candidates[j + 1];
            candidates[15] = { i, obj, outer, obj_flags };
        }
    }

    bridge_log("  find_uworld: %d non-CDO candidates, %d CDO skipped, "
               "%d total class hits",
               n_candidates, cdo_skipped, class_hits);

    if (n_candidates == 0) {
        bridge_log("  UWorld not found via GUObjectArray (%d objects)", num_elems);
        return false;
    }

    /* --- Selection: cross-validate against GEngine's pointer chain ---
     * The active game UWorld is always reachable from GEngine (via WorldList
     * or GameViewport). CDOs and template worlds are NOT referenced. */
    void* best = nullptr;
    int best_idx = -1;

    if (g_engine_ptr) {
        for (int c = 0; c < n_candidates; c++) {
            if (cross_validate_world(candidates[c].obj)) {
                best = candidates[c].obj;
                best_idx = candidates[c].index;
                bridge_log("  UWorld [%d] 0x%p CONFIRMED by GEngine cross-validation",
                           candidates[c].index, candidates[c].obj);
                /* Don't break -- keep scanning to find the last confirmed
                 * (highest index, most recently created). */
            }
        }
    }

    /* Fallback: if cross-validation didn't confirm any (GEngine not found,
     * or WorldList layout unrecognized), pick the last non-CDO candidate. */
    if (!best) {
        best = candidates[n_candidates - 1].obj;
        best_idx = candidates[n_candidates - 1].index;
        bridge_log("  UWorld [%d] 0x%p selected (fallback: last non-CDO candidate)",
                   best_idx, best);
    }

    g_world_ptr = best;
    g_world_from_gua = true;

    if (g_debug_break_armed.exchange(false)) {
        bridge_log("  DEBUG BREAK: UWorld found -- breaking into debugger");
        __debugbreak();
    }
    return true;
}

/* ---- ULocalPlayer via GUObjectArray + FName ------------------------- */

/* ULocalPlayer object pointer. Set by find_localplayer().
 * Used to route gameplay commands (slomo, ToggleDebugCamera, etc.) via
 * ULocalPlayer::Exec -> APlayerController::Exec -> UCheatManager. */
static void* g_localplayer_ptr = nullptr;

/*
 * find_localplayer() -- scan GUObjectArray for an object whose class
 * FName matches "LocalPlayer" (multi-block search, handles block 5+).
 *
 * ClassPrivate at UObjectBase+0x10, NamePrivate at ClassPrivate+0x18.
 * ComparisonIndex is the full 32-bit value (block<<16 | word_off).
 * After finding the object, verify it has FExec at g_fexec_offset by
 * reading its secondary vtable.
 */
static bool find_localplayer()
{
    if (g_localplayer_ptr) return true;
    if (!g_guobjectarray_found) return false;

    uint32_t lp_idx = get_fname_cmpidx_for("LocalPlayer");
    if (lp_idx == 0xFFFFFFFF) {
        bridge_log("  find_localplayer: FName('LocalPlayer') not found "
                   "(FNamePool has %s)",
                   g_fnamepool_global ? "global" : "block0 only");
        return false;
    }
    bridge_log("  find_localplayer: FName('LocalPlayer')=0x%X (block=%d word=0x%X)",
               lp_idx, lp_idx >> 16, lp_idx & 0xFFFF);

    /* Look up "GameInstance" FName for outer validation.
     * The real LocalPlayer's OuterPrivate is a UGameInstance whose class
     * FName is "GameInstance" (or a subclass). CDO's outer is the UPackage. */
    uint32_t gi_idx = get_fname_cmpidx_for("GameInstance");
    bridge_log("  find_localplayer: FName('GameInstance')=0x%X",
               gi_idx);

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;

    struct LPCandidate {
        int32_t index; void* obj; uintptr_t fexec_vptr;
        uint32_t flags; bool outer_is_gi;
    };
    LPCandidate candidates[8];
    int n_candidates = 0;
    int cdo_skipped = 0;

    int32_t num_elems = guobjectarray_num_elements();
    for (int32_t i = 0; i < num_elems; i++) {
        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x800000000000ULL) continue;

        uintptr_t class_ptr = seh_read_ptr((uint8_t*)obj + 0x10);
        if (class_ptr < 0x10000) continue;

        uint32_t cmp_idx = 0;
        __try { cmp_idx = *(uint32_t*)((uint8_t*)class_ptr + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        if (cmp_idx != lp_idx) continue;

        /* ObjectFlags at UObjectBase+0x08 -- skip CDOs */
        uint32_t obj_flags = 0;
        __try { obj_flags = *(uint32_t*)((uint8_t*)obj + 0x08); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
        /* Read names for diagnostic logging */
        char obj_name[128], cls_name[128];
        read_obj_names(obj, obj_name, sizeof(obj_name), cls_name, sizeof(cls_name));

        if (obj_flags & 0x10) {
            bridge_log("  LocalPlayer [%d] 0x%p: CDO name='%s' class='%s' "
                       "flags=0x%X -- skipped",
                       i, obj, obj_name, cls_name, obj_flags);
            cdo_skipped++;
            continue;
        }

        /* Confirm FExec secondary vtable at g_fexec_offset */
        uintptr_t fexec_off  = g_fexec_offset ? g_fexec_offset : 0x28;
        uintptr_t lp_fexec_v = seh_read_ptr((uint8_t*)obj + fexec_off);
        if (lp_fexec_v < mod_start || lp_fexec_v >= mod_end) continue;

        /* Check if OuterPrivate is a GameInstance.
         * ULocalPlayer.OuterPrivate -> UGameInstance (class FName check). */
        bool outer_is_gi = false;
        char outer_cls_name[128] = {0};
        uintptr_t outer = seh_read_ptr((uint8_t*)obj + 0x20);
        if (outer >= 0x10000 && outer < 0x800000000000ULL) {
            uintptr_t outer_class = seh_read_ptr((void*)(outer + 0x10));
            if (outer_class >= 0x10000) {
                uint32_t outer_class_cmpidx = 0;
                __try { outer_class_cmpidx = *(uint32_t*)((uint8_t*)outer_class + 0x18); }
                __except(EXCEPTION_EXECUTE_HANDLER) { outer_class_cmpidx = 0; }
                resolve_fname(outer_class_cmpidx, outer_cls_name, sizeof(outer_cls_name));
                if (gi_idx != 0xFFFFFFFF)
                    outer_is_gi = (outer_class_cmpidx == gi_idx);
            }
        }

        bridge_log("  LocalPlayer candidate #%d: [%d] obj=0x%p name='%s' "
                   "class='%s' flags=0x%X fexec=0x%llX outer_class='%s' gi=%d",
                   n_candidates, i, obj, obj_name, cls_name,
                   obj_flags, (unsigned long long)lp_fexec_v,
                   outer_cls_name, (int)outer_is_gi);

        if (n_candidates < 8) {
            candidates[n_candidates] = { i, obj, lp_fexec_v,
                                         obj_flags, outer_is_gi };
            n_candidates++;
        } else {
            for (int j = 0; j < 7; j++) candidates[j] = candidates[j + 1];
            candidates[7] = { i, obj, lp_fexec_v, obj_flags, outer_is_gi };
        }
    }

    bridge_log("  find_localplayer: %d non-CDO candidates, %d CDO skipped",
               n_candidates, cdo_skipped);

    if (n_candidates == 0) {
        bridge_log("  find_localplayer: not found in %d objects", num_elems);
        return false;
    }

    /* Selection: prefer candidate whose outer is a GameInstance.
     * Among those, take the last (most recently created). */
    int best_c = -1;
    for (int c = n_candidates - 1; c >= 0; c--) {
        if (candidates[c].outer_is_gi) {
            best_c = c;
            break;
        }
    }
    /* Fallback: last non-CDO candidate. */
    if (best_c < 0) {
        best_c = n_candidates - 1;
        bridge_log("  LocalPlayer: no GameInstance outer found, "
                   "using last non-CDO candidate");
    }

    LPCandidate& best = candidates[best_c];
    g_localplayer_ptr = best.obj;
    bridge_log("  ULocalPlayer SELECTED: [%d] obj=0x%p fexec=0x%llX "
               "outer_gi=%d (%d candidates)",
               best.index, best.obj, (unsigned long long)best.fexec_vptr,
               (int)best.outer_is_gi, n_candidates);

    if (g_debug_break_armed.exchange(false)) {
        bridge_log("  DEBUG BREAK: LocalPlayer found -- breaking into debugger");
        __debugbreak();
    }
    return true;
}

/* ---- APlayerCameraManager via GUObjectArray + FName ---------------- */

/* APlayerCameraManager pointer. Set by find_camera_manager().
 * Used for direct FMinimalViewInfo memory write (camera override). */
static void* g_camera_manager_ptr = nullptr;

/*
 * find_camera_manager() -- scan GUObjectArray for an object whose class
 * FName matches "PlayerCameraManager" or "BP_PlayerCameraManager_C".
 *
 * Layout used:
 *   UObjectBase+0x08: ObjectFlags  (skip CDO if flag 0x10 set)
 *   UObjectBase+0x10: ClassPrivate
 *   ClassPrivate+0x18: ComparisonIndex (class FName)
 *   UObjectBase+0x20: OuterPrivate (owner APlayerController)
 *
 * Selection: prefer candidates whose OuterPrivate's class FName
 * contains "PlayerController".  Fall back to last non-CDO if none.
 */
static bool find_camera_manager()
{
    if (g_camera_manager_ptr) return true;
    if (!g_guobjectarray_found) return false;

    /* Build a list of candidate class FName indices to match against.
     * Stock UE5 class is "PlayerCameraManager".
     * Blueprint subclass is "BP_PlayerCameraManager_C" (common override). */
    const char* class_names[] = {
        "PlayerCameraManager",
        "BP_PlayerCameraManager_C",
        nullptr
    };

    uint32_t pcm_idx[2] = { 0xFFFFFFFF, 0xFFFFFFFF };
    int n_pcm = 0;
    for (int ni = 0; class_names[ni]; ni++) {
        uint32_t idx = get_fname_cmpidx_for(class_names[ni]);
        if (idx != 0xFFFFFFFF) {
            pcm_idx[n_pcm++] = idx;
            bridge_log("  find_camera_manager: FName('%s')=0x%X (block=%d word=0x%X)",
                       class_names[ni], idx, idx >> 16, idx & 0xFFFF);
        } else {
            bridge_log("  find_camera_manager: FName('%s') not in pool",
                       class_names[ni]);
        }
    }

    if (n_pcm == 0) {
        bridge_log("  find_camera_manager: no matching FName found -- "
                   "camera manager cannot be located via GUA scan");
        return false;
    }

    /* Look up "PlayerController" FName for outer validation. */
    uint32_t pc_idx = get_fname_cmpidx_for("PlayerController");
    bridge_log("  find_camera_manager: FName('PlayerController')=0x%X", pc_idx);

    struct PCMCandidate {
        int32_t index; void* obj;
        uint32_t flags; bool outer_is_pc;
        char class_name[64];
    };
    PCMCandidate candidates[8];
    int n_candidates = 0;
    int cdo_skipped = 0;

    int32_t num_elems = guobjectarray_num_elements();
    for (int32_t i = 0; i < num_elems; i++) {
        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x800000000000ULL) continue;

        uintptr_t class_ptr = seh_read_ptr((uint8_t*)obj + 0x10);
        if (class_ptr < 0x10000) continue;

        uint32_t cmp_idx = 0;
        __try { cmp_idx = *(uint32_t*)((uint8_t*)class_ptr + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        /* Match against any of our candidate class FNames */
        bool matched = false;
        for (int ni = 0; ni < n_pcm; ni++) {
            if (cmp_idx == pcm_idx[ni]) { matched = true; break; }
        }
        if (!matched) continue;

        /* ObjectFlags at UObjectBase+0x08 -- skip CDOs */
        uint32_t obj_flags = 0;
        __try { obj_flags = *(uint32_t*)((uint8_t*)obj + 0x08); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        char obj_name[128], cls_name[128];
        read_obj_names(obj, obj_name, sizeof(obj_name), cls_name, sizeof(cls_name));

        if (obj_flags & 0x10) {
            bridge_log("  CameraManager [%d] 0x%p: CDO name='%s' class='%s' "
                       "flags=0x%X -- skipped",
                       i, obj, obj_name, cls_name, obj_flags);
            cdo_skipped++;
            continue;
        }

        /* Check if OuterPrivate is a PlayerController. */
        bool outer_is_pc = false;
        char outer_cls_name[128] = {0};
        uintptr_t outer = seh_read_ptr((uint8_t*)obj + 0x20);
        if (outer >= 0x10000 && outer < 0x800000000000ULL) {
            uintptr_t outer_class = seh_read_ptr((void*)(outer + 0x10));
            if (outer_class >= 0x10000) {
                uint32_t outer_cmp = 0;
                __try { outer_cmp = *(uint32_t*)((uint8_t*)outer_class + 0x18); }
                __except(EXCEPTION_EXECUTE_HANDLER) { outer_cmp = 0; }
                resolve_fname(outer_cmp, outer_cls_name, sizeof(outer_cls_name));
                if (pc_idx != 0xFFFFFFFF)
                    outer_is_pc = (outer_cmp == pc_idx);
            }
        }

        bridge_log("  CameraManager candidate #%d: [%d] obj=0x%p name='%s' "
                   "class='%s' flags=0x%X outer_class='%s' pc=%d",
                   n_candidates, i, obj, obj_name, cls_name,
                   obj_flags, outer_cls_name, (int)outer_is_pc);

        if (n_candidates < 8) {
            PCMCandidate& c = candidates[n_candidates];
            c.index = i; c.obj = obj; c.flags = obj_flags;
            c.outer_is_pc = outer_is_pc;
            strncpy(c.class_name, cls_name, sizeof(c.class_name) - 1);
            n_candidates++;
        } else {
            for (int j = 0; j < 7; j++) candidates[j] = candidates[j + 1];
            PCMCandidate& c = candidates[7];
            c.index = i; c.obj = obj; c.flags = obj_flags;
            c.outer_is_pc = outer_is_pc;
            strncpy(c.class_name, cls_name, sizeof(c.class_name) - 1);
        }
    }

    bridge_log("  find_camera_manager: %d non-CDO candidates, %d CDO skipped",
               n_candidates, cdo_skipped);

    if (n_candidates == 0) {
        bridge_log("  find_camera_manager: not found in %d objects", num_elems);
        return false;
    }

    /* Selection: prefer candidate whose outer is a PlayerController.
     * Among those, take the last (most recently created). */
    int best_c = -1;
    for (int c = n_candidates - 1; c >= 0; c--) {
        if (candidates[c].outer_is_pc) {
            best_c = c;
            break;
        }
    }
    if (best_c < 0) {
        best_c = n_candidates - 1;
        bridge_log("  CameraManager: no PlayerController outer found, "
                   "using last non-CDO candidate");
    }

    PCMCandidate& best = candidates[best_c];
    g_camera_manager_ptr = best.obj;
    bridge_log("  APlayerCameraManager SELECTED: [%d] obj=0x%p class='%s' "
               "outer_pc=%d (%d candidates)",
               best.index, best.obj, best.class_name,
               (int)best.outer_is_pc, n_candidates);

    if (g_debug_break_armed.exchange(false)) {
        bridge_log("  DEBUG BREAK: CameraManager found -- breaking into debugger");
        __debugbreak();
    }
    return true;
}

/* ---- FMinimalViewInfo direct memory access -------------------------
 *
 * APlayerCameraManager stores the active view in CameraCachePrivate
 * (FCameraCacheEntry).  We locate it at runtime via UClass property
 * reflection so the code is version-independent.
 *
 * UStruct layout (UE4SS PDB verified, UE5.00 - UE5.07, all identical):
 *   UObjectBase:        +0x00  (0x28 bytes)
 *   UField::Next:       +0x28  (UField*, 8 bytes -- UField total 0x30)
 *   UStruct::SuperStruct:  +0x40  (UStruct* -- 0x10 gap for UStruct internals)
 *   UStruct::Children:     +0x48  (UField*, legacy)
 *   UStruct::ChildProperties: +0x50 (FField*, UE4.25+ property chain)
 *
 * FField layout (UE4.25+):
 *   ClassPrivate:  +0x00
 *   Owner:         +0x08  (FFieldVariant, 16 bytes)
 *   Next:          +0x18  (FField*)
 *   NamePrivate:   +0x20  (FName -- ComparisonIndex at +0x20)
 *   FlagsPrivate:  +0x28
 *
 * FProperty extends FField:
 *   ArrayDim:      +0x30
 *   ElementSize:   +0x34
 *   PropertyFlags: +0x38  (uint64)
 *   RepIndex:      +0x40
 *   Condition:     +0x42
 *   [pad2]
 *   Offset_Internal: +0x44  (int32) <-- runtime struct offset we need
 *
 * FCameraCacheEntry:
 *   TimeStamp:  +0x00  (float, 4B)
 *   [pad 4 -- to align FMinimalViewInfo at 8-byte boundary for doubles]
 *   POV:        +0x08  (FMinimalViewInfo)
 *
 * FMinimalViewInfo -- UE5 LWC layout (FVector/FRotator = double):
 *   Location:  +0x00  (3 x double = 24B: X, Y, Z)
 *   Rotation:  +0x18  (3 x double = 24B: Pitch, Yaw, Roll)
 *   FOV:       +0x30  (float, 4B)
 *
 * FMinimalViewInfo -- legacy float layout (UE4 / non-LWC UE5):
 *   Location:  +0x00  (3 x float = 12B)
 *   Rotation:  +0x0C  (3 x float = 12B)
 *   FOV:       +0x18  (float)
 *   POV in FCameraCacheEntry: +0x10 (SIMD) or +0x04 (non-SIMD)
 */

/* Pointer to FMinimalViewInfo inside APlayerCameraManager.
 * Set by find_cam_pov().  Written by write_camera_mem() every tick. */
static uint8_t* g_cam_pov_ptr = nullptr;

/* True when the FMinimalViewInfo at g_cam_pov_ptr uses LWC double layout
 * (UE5 with Large World Coordinates: FVector/FRotator are double).
 * False for legacy float layout (UE4 / non-LWC UE5). */
static bool g_cam_pov_is_lwc = false;

/* Camera override state -- written by TCP cam_write command,
 * applied every tick while g_camera_override is true.
 * x/y/z/pitch/yaw/roll are double to match UE5 LWC precision. */
struct CameraMemState {
    double x, y, z;          /* UE5 cm (double for LWC) */
    double pitch, yaw, roll; /* degrees */
    float fov;
};
static CameraMemState g_cam_override_state = {0,0,0, 0,0,0, 90.0f};
/* g_camera_override declared at top of file (line ~294) -- single definition */

/*
 * ffield_find_offset() -- walk UClass::ChildProperties FField chain
 * and return Offset_Internal for the property matching prop_fname_idx.
 * Returns -1 if not found.
 */
/*
 * FField layout changed between UE5.02 and UE5.03 (FFieldVariant shrank).
 * UE4SS PDB verified:
 *
 *   Era        | Next  | NamePrivate | FProperty::Offset_Internal
 *   -----------|-------|-------------|----------------------------
 *   5.00-5.02  | +0x20 | +0x28       | +0x4C
 *   5.03-5.07  | +0x18 | +0x20       | +0x44
 *
 * We detect at runtime by probing: walk the chain with both layouts,
 * check which one produces a readable, non-zero FName index.
 */
static int32_t ffield_find_offset_era(void* child_props_ptr,
                                      uint32_t prop_fname_idx,
                                      int32_t next_off,
                                      int32_t name_off,
                                      int32_t offset_off)
{
    void* field = child_props_ptr;
    int walked = 0;
    for (int limit = 1024; field && limit > 0; limit--) {
        uint32_t fname_idx = 0;
        __try { fname_idx = *(uint32_t*)((uint8_t*)field + name_off); }
        __except(EXCEPTION_EXECUTE_HANDLER) {
            bridge_log("  ffield_era(name+0x%X): AV at field=0x%p after %d props",
                       name_off, field, walked);
            break;
        }

        if (fname_idx == prop_fname_idx) {
            int32_t off = -1;
            __try { off = *(int32_t*)((uint8_t*)field + offset_off); }
            __except(EXCEPTION_EXECUTE_HANDLER) { return -1; }
            return off;
        }

        walked++;
        uintptr_t next = seh_read_ptr((uint8_t*)field + next_off);
        if (!next || next == (uintptr_t)field) {
            bridge_log("  ffield_era(name+0x%X): chain end after %d props (next=%s)",
                       name_off, walked, !next ? "null" : "self-loop");
            break;
        }
        field = (void*)next;
    }
    return -1;
}

static int32_t ffield_find_offset(void* uclass_or_ustruct,
                                  uint32_t prop_fname_idx)
{
    /* UStruct::ChildProperties -- offset from layout (0x50 all known UE5/UE4.27) */
    uintptr_t child_props = seh_read_ptr((uint8_t*)uclass_or_ustruct + g_ue_layout->ustruct_childprops_off);
    if (!child_props || child_props < 0x10000) {
        bridge_log("  ffield: class=0x%p ChildProperties@+0x50=null/invalid",
                   uclass_or_ustruct);
        return -1;
    }

    /* Log first property to diagnose FField era misdetection */
    uint32_t first_fname_5x = 0, first_fname_4x = 0;
    __try { first_fname_5x = *(uint32_t*)((uint8_t*)child_props + 0x20); } /* UE5.03+ name */
    __except(EXCEPTION_EXECUTE_HANDLER) {}
    __try { first_fname_4x = *(uint32_t*)((uint8_t*)child_props + 0x28); } /* UE5.00-5.02 name */
    __except(EXCEPTION_EXECUTE_HANDLER) {}
    char n5[32]={0}, n4[32]={0};
    resolve_fname(first_fname_5x, n5, sizeof(n5));
    resolve_fname(first_fname_4x, n4, sizeof(n4));
    bridge_log("  ffield: class=0x%p children=0x%llX "
               "first_prop_5x='%s'(0x%X) first_prop_4x='%s'(0x%X)",
               uclass_or_ustruct, (unsigned long long)child_props,
               n5, first_fname_5x, n4, first_fname_4x);

    void* fp = (void*)child_props;

    /* Try layout-specified FField era first */
    int32_t off = ffield_find_offset_era(fp, prop_fname_idx,
                                         g_ue_layout->ffield_next_off,
                                         g_ue_layout->ffield_name_off,
                                         g_ue_layout->fprop_offset_off);
    if (off >= 0) {
        bridge_log("  ffield: found at 0x%X via %s era (next=0x%X,name=0x%X,off=0x%X)",
                   off, g_ue_layout->name,
                   g_ue_layout->ffield_next_off,
                   g_ue_layout->ffield_name_off,
                   g_ue_layout->fprop_offset_off);
        return off;
    }

    /* Fall back to the other era (for games that don't match the layout exactly) */
    bool primary_is_era2 = (g_ue_layout->ffield_next_off == 0x18);
    int alt_next = primary_is_era2 ? 0x20 : 0x18;
    int alt_name = primary_is_era2 ? 0x28 : 0x20;
    int alt_off  = primary_is_era2 ? 0x4C : 0x44;
    off = ffield_find_offset_era(fp, prop_fname_idx, alt_next, alt_name, alt_off);
    if (off >= 0) {
        bridge_log("  ffield: found at 0x%X via alt era (next=0x%X,name=0x%X,off=0x%X) "
                   "-- layout mismatch?",
                   off, alt_next, alt_name, alt_off);
    } else {
        bridge_log("  ffield: property 0x%X not found in either FField era", prop_fname_idx);
    }
    return off;
}

/* forward declaration: defined after find_cam_pov() */
static bool find_cam_pov_scan();

/*
 * find_cam_pov() -- locate FMinimalViewInfo inside g_camera_manager_ptr.
 *
 * Priority order:
 * 1. Layout cam_pov_direct_off (non-zero = confirmed offset for this UE version).
 *    Skips FField + scan entirely.  Fastest path.
 * 2. FField reflection: look up FName("CameraCachePrivate"), walk UClass chain.
 *    Correct path when reflection data is complete.
 * 3. Memory scan fallback: find_cam_pov_scan().
 *    Used when FField chain is truncated (e.g. transient properties stripped).
 */
static bool find_cam_pov()
{
    if (g_cam_pov_ptr) return true;
    if (!g_camera_manager_ptr) return false;

    /* Path 1: direct offset from layout (fastest -- no FField, no scan) */
    if (g_ue_layout->cam_pov_direct_off != 0) {
        uint8_t* pov = (uint8_t*)g_camera_manager_ptr + g_ue_layout->cam_pov_direct_off;
        float fov_val = 0.0f;
        __try { fov_val = *(float*)(pov + g_ue_layout->fmvi_fov); }
        __except(EXCEPTION_EXECUTE_HANDLER) {
            bridge_log("  find_cam_pov: AV at direct offset manager+0x%X",
                       g_ue_layout->cam_pov_direct_off);
            goto fallback_ffield;
        }
        if (!isfinite(fov_val) || fov_val < 1.0f || fov_val > 179.0f) {
            bridge_log("  find_cam_pov: direct offset manager+0x%X FOV=%.2f "
                       "invalid -- falling back to FField",
                       g_ue_layout->cam_pov_direct_off, fov_val);
            goto fallback_ffield;
        }
        g_cam_pov_ptr    = pov;
        g_cam_pov_is_lwc = g_ue_layout->fmvi_is_lwc;
        bridge_log("  find_cam_pov: DIRECT at manager+0x%X FOV=%.1f (%s)",
                   g_ue_layout->cam_pov_direct_off, fov_val,
                   g_cam_pov_is_lwc ? "LWC-double" : "float");
        return true;
    }

    fallback_ffield:

    /* Get UClass of the camera manager */
    void* uclass = (void*)seh_read_ptr((uint8_t*)g_camera_manager_ptr + 0x10);
    if (!uclass || (uintptr_t)uclass < 0x10000) {
        bridge_log("  find_cam_pov: invalid UClass pointer at mgr+0x10");
        return false;
    }
    {
        char cls_name[64] = {0};
        uint32_t cls_fname = 0;
        __try { cls_fname = *(uint32_t*)((uint8_t*)uclass + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) {}
        resolve_fname(cls_fname, cls_name, sizeof(cls_name));
        bridge_log("  find_cam_pov: manager=0x%p class=0x%p('%s')",
                   g_camera_manager_ptr, uclass, cls_name);
    }

    /* Resolve FName for the property we're searching */
    uint32_t cc_fname = get_fname_cmpidx_for("CameraCachePrivate");
    if (cc_fname == 0xFFFFFFFF) {
        bridge_log("  find_cam_pov: FName('CameraCachePrivate') not in FNamePool");
        return false;
    }
    bridge_log("  find_cam_pov: FName('CameraCachePrivate')=0x%X", cc_fname);

    /* Walk UClass and its SuperStruct chain */
    int32_t cc_off = -1;
    void* cls = uclass;
    char cls_name[64];
    for (int depth = 0; cls && depth < 16 && cc_off < 0; depth++) {
        resolve_fname(*(uint32_t*)((uint8_t*)cls + 0x18), cls_name, sizeof(cls_name));
        bridge_log("  find_cam_pov: [depth %d] searching class '%s'(0x%p)",
                   depth, cls_name, cls);
        cc_off = ffield_find_offset(cls, cc_fname);
        if (cc_off >= 0) {
            bridge_log("  find_cam_pov: CameraCachePrivate at offset 0x%X "
                       "(found in class '%s', depth=%d)",
                       cc_off, cls_name, depth);
            break;
        }
        cls = (void*)seh_read_ptr((uint8_t*)cls + g_ue_layout->ustruct_super_off); /* SuperStruct */
        if ((uintptr_t)cls < 0x10000) {
            bridge_log("  find_cam_pov: SuperStruct chain ended at depth %d", depth);
            break;
        }
    }

    if (cc_off < 0) {
        bridge_log("  find_cam_pov: CameraCachePrivate property not found "
                   "in UClass chain -- trying memory scan fallback");
        return find_cam_pov_scan();
    }

    /* Try POV-in-cache offsets. Layout provides the primary; two hardcoded
     * fallbacks cover the other known layout variants. */
    struct { int32_t pov_in_cache; int32_t fov_in_pov; bool is_lwc; } trials[] = {
        { g_ue_layout->fcce_pov_off, g_ue_layout->fmvi_fov, g_ue_layout->fmvi_is_lwc },
        { 0x08, 0x30, true  },   /* LWC double fallback */
        { 0x10, 0x18, false },   /* SIMD float fallback */
        { 0x04, 0x18, false },   /* non-SIMD float fallback */
    };
    /* deduplicate: skip trial[0] copy if it matches trial[1] or [2] */
    int num_trials = 4;

    for (int t = 0; t < num_trials; t++) {
        /* skip duplicate of trial[0] in trials[1..3] */
        if (t > 0 && trials[t].pov_in_cache == trials[0].pov_in_cache) continue;
        int32_t pov_off = cc_off + trials[t].pov_in_cache;
        uint8_t* pov_candidate = (uint8_t*)g_camera_manager_ptr + pov_off;
        float fov_val = 0.0f;
        __try { fov_val = *(float*)(pov_candidate + trials[t].fov_in_pov); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        bridge_log("  find_cam_pov: trial[%d] POV at manager+0x%X "
                   "(fov_off=+0x%X) FOV=%.2f",
                   t, pov_off, trials[t].fov_in_pov, fov_val);

        if (fov_val >= 1.0f && fov_val <= 179.0f) {
            g_cam_pov_ptr    = pov_candidate;
            g_cam_pov_is_lwc = trials[t].is_lwc;
            bridge_log("  FMinimalViewInfo confirmed at 0x%p "
                       "(FOV=%.1f deg, layout=%s)",
                       g_cam_pov_ptr, fov_val,
                       g_cam_pov_is_lwc ? "LWC-double" : "float");
            return true;
        }
    }

    bridge_log("  find_cam_pov: FOV out of range [1,179] at all 3 offsets");
    return false;
}

/*
 * find_cam_pov_scan() -- fallback when FField reflection fails.
 *
 * In some UE5 builds CameraCachePrivate is not reflected (no UPROPERTY),
 * so ffield_find_offset returns -1.  Instead, scan the APlayerCameraManager
 * object for a 7-float sequence that looks like FMinimalViewInfo:
 *   +0x00 Location.X  (finite float, any value)
 *   +0x04 Location.Y
 *   +0x08 Location.Z
 *   +0x0C Rotation.Pitch  (in [-90, 90])
 *   +0x10 Rotation.Yaw    (in [-360, 360])
 *   +0x14 Rotation.Roll   (in [-360, 360])
 *   +0x18 FOV             (in [1, 179])
 *
 * Scans manager+0x200 .. manager+0x900 in 4-byte steps.
 * Logs ALL candidates found (for diagnostics).
 * Picks the first valid candidate that also has a finite Location.
 */
/*
 * Scan pass: try a specific FMinimalViewInfo layout.
 * is_lwc=true:  3 doubles (Location) + 3 doubles (Rotation) + float FOV at +0x30
 * is_lwc=false: 3 floats  (Location) + 3 floats  (Rotation) + float FOV at +0x18
 * step: 8 for LWC (double-aligned), 4 for float.
 */
static bool find_cam_pov_scan_pass(bool is_lwc)
{
    uint8_t* mgr = (uint8_t*)g_camera_manager_ptr;
    const int32_t SCAN_START = 0x200;
    const int32_t SCAN_END   = 0x900;
    const int32_t step       = is_lwc ? 8 : 4;

    int found_count = 0;
    uint8_t* best_nz = nullptr;  /* first candidate with real (non-zero) xyz */
    uint8_t* best_z  = nullptr;  /* first candidate with any valid xyz */

    for (int32_t off = SCAN_START; off <= SCAN_END; off += step) {
        uint8_t* pov = mgr + off;
        float fov = 0.0f;
        double px = 0.0, py = 0.0, pz = 0.0;
        double pitch = 0.0, yaw = 0.0, roll = 0.0;

        if (is_lwc) {
            /* LWC: Location and Rotation are doubles, FOV float at +0x30 */
            __try {
                px    = *(double*)(pov + 0x00);
                py    = *(double*)(pov + 0x08);
                pz    = *(double*)(pov + 0x10);
                pitch = *(double*)(pov + 0x18);
                yaw   = *(double*)(pov + 0x20);
                roll  = *(double*)(pov + 0x28);
                fov   = *(float* )(pov + 0x30);
            }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
        } else {
            /* float: Location and Rotation are floats, FOV float at +0x18 */
            float fx, fy, fz, fp, fy2, fr;
            __try {
                fx  = *(float*)(pov + 0x00);
                fy  = *(float*)(pov + 0x04);
                fz  = *(float*)(pov + 0x08);
                fp  = *(float*)(pov + 0x0C);
                fy2 = *(float*)(pov + 0x10);
                fr  = *(float*)(pov + 0x14);
                fov = *(float*)(pov + 0x18);
            }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
            px = fx; py = fy; pz = fz;
            pitch = fp; yaw = fy2; roll = fr;
        }

        /* Strict validation: reject NaN/Inf in all fields */
        if (!isfinite(fov)   || fov < 1.0f || fov > 179.0f) continue;
        if (!isfinite(pitch) || pitch < -91.0 || pitch > 91.0) continue;
        if (!isfinite(yaw)   || yaw  < -360.0 || yaw  > 360.0) continue;
        if (!isfinite(roll)  || roll < -360.0 || roll > 360.0) continue;
        if (!isfinite(px) || !isfinite(py) || !isfinite(pz)) continue;

        /* Prefer candidates with real (non-zero) world position.
         * Zero-xyz candidates are likely uninitialized cache entries or
         * default-constructed structs that accidentally pass float checks. */
        bool has_real_pos = (fabs(px) > 1.0 || fabs(py) > 1.0 || fabs(pz) > 1.0);

        found_count++;
        bridge_log("  cam_scan(%s) #%d at manager+0x%X: "
                   "xyz=(%.1f,%.1f,%.1f) pyr=(%.2f,%.2f,%.2f) fov=%.1f%s",
                   is_lwc ? "LWC" : "float",
                   found_count, off,
                   (float)px, (float)py, (float)pz,
                   (float)pitch, (float)yaw, (float)roll, fov,
                   has_real_pos ? " <-- REAL POS" : "");

        if (has_real_pos && !best_nz) best_nz = pov;   /* first with real position */
        if (!best_z) best_z = pov;                     /* first valid (any position) */
    }

    uint8_t* best = best_nz ? best_nz : best_z;
    if (!best) return false;

    if (best_nz)
        bridge_log("  cam_scan: selected non-zero-pos candidate (manager+0x%X)",
                   (int32_t)(best - (uint8_t*)g_camera_manager_ptr));
    else
        bridge_log("  cam_scan: no real-pos candidate; using first valid (manager+0x%X)",
                   (int32_t)(best - (uint8_t*)g_camera_manager_ptr));

    g_cam_pov_ptr    = best;
    g_cam_pov_is_lwc = is_lwc;
    bridge_log("  FMinimalViewInfo SCAN found at 0x%p (manager+0x%X, %s). "
               "Run __cam_mem_find again after level loads if wrong.",
               g_cam_pov_ptr,
               (int32_t)(g_cam_pov_ptr - mgr),
               is_lwc ? "LWC-double" : "float");
    return true;
}

static bool find_cam_pov_scan()
{
    if (!g_camera_manager_ptr) return false;

    bridge_log("  find_cam_pov_scan: trying LWC-double layout first "
               "[+0x200..+0x900] step=8");
    if (find_cam_pov_scan_pass(true)) return true;

    bridge_log("  find_cam_pov_scan: LWC pass found nothing -- "
               "trying float layout step=4");
    if (find_cam_pov_scan_pass(false)) return true;

    bridge_log("  find_cam_pov_scan: no candidate in either layout -- "
               "game may be in loading screen (FOV/Rotation are 0)");
    return false;
}

/* Read current camera state directly from FMinimalViewInfo */
static bool read_camera_mem(CameraMemState& out)
{
    if (!g_cam_pov_ptr) return false;
    __try {
        if (g_cam_pov_is_lwc) {
            out.x     = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_x);
            out.y     = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_y);
            out.z     = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_z);
            out.pitch = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_pitch);
            out.yaw   = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_yaw);
            out.roll  = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_roll);
            out.fov   = *(float* )(g_cam_pov_ptr + g_ue_layout->fmvi_fov);
        } else {
            out.x     = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_x);
            out.y     = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_y);
            out.z     = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_z);
            out.pitch = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_pitch);
            out.yaw   = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_yaw);
            out.roll  = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_roll);
            out.fov   = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_fov);
        }
        return true;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        bridge_log("  read_camera_mem: AV at 0x%p -- clearing pov ptr",
                   g_cam_pov_ptr);
        g_cam_pov_ptr = nullptr;
        return false;
    }
}

/* Write camera state directly to FMinimalViewInfo.
 * Called from tick thread every frame while g_camera_override is true.
 * This fights the game's per-frame camera update without needing hooks. */
static bool write_camera_mem(const CameraMemState& s)
{
    if (!g_cam_pov_ptr) return false;
    __try {
        if (g_cam_pov_is_lwc) {
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_x) = s.x;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_y) = s.y;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_z) = s.z;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_pitch) = s.pitch;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_yaw)   = s.yaw;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_roll)  = s.roll;
            *(float* )(g_cam_pov_ptr + g_ue_layout->fmvi_fov)   = s.fov;
        } else {
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_x) = (float)s.x;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_y) = (float)s.y;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_z) = (float)s.z;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_pitch) = (float)s.pitch;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_yaw)   = (float)s.yaw;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_roll)  = (float)s.roll;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_fov)   = s.fov;
        }
        return true;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        bridge_log("  write_camera_mem: AV at 0x%p -- clearing pov ptr",
                   g_cam_pov_ptr);
        g_cam_pov_ptr = nullptr;
        return false;
    }
}

/* ---- Camera cross-validation: LP chain + GEngine render path ------- *
 *
 * Strategy (user design):
 *   Path A -- GUObjectArray FName scan:
 *     Scan for class FName "PlayerCameraManager" / "BP_PlayerCameraManager_C".
 *     Problem: BP subclass name varies per game.
 *
 *   Path B -- LocalPlayer -> PlayerController pointer walk:
 *     g_localplayer_ptr + 0x30 -> APlayerController*
 *     FField reflection on PC's UClass -> PlayerCameraManager field offset
 *     Read APlayerCameraManager* from that offset.
 *     Advantage: game-agnostic, works with any PC/PCM subclass name.
 *
 *   Path C -- GEngine render viewport sanity check:
 *     GEngine (UGameEngine) + 0x200 -> UGameViewportClient* (stable UE5)
 *     UGameViewportClient + 0x78 -> UWorld*
 *     Compare with g_world_ptr to confirm GEngine is correct.
 *
 * Cross-validation rule:
 *   Both A and B found, same address -> CONFIRMED, high confidence.
 *   Only B found (LP chain) -> use B; A scan found wrong object (wrong FName).
 *   Only A found -> keep A, log warning.
 *   Neither -> no camera control.
 *
 * UPlayer::PlayerController offset derivation (UE4SS PDB, all UE5):
 *   UObjectBase: 0x28 bytes
 *   FExec secondary vptr: +0x28 (= g_fexec_offset, 8 bytes)
 *   PlayerController (TObjectPtr<APlayerController>): +0x30
 *   CurrentNetSpeed: +0x38  <- first listed field in UE4SS template
 *
 * UEngine::GameViewport (UGameViewportClient*): +0x200 (stable UE5.00-5.07)
 * UGameViewportClient::World (UWorld*): +0x78 (stable UE5.00-5.07)
 */
/* All chain offsets now come from g_ue_layout (see UEVersionLayout above).
 * Use g_ue_layout->uplayer_pc_off, ->uengine_gvc_off, ->ugvc_world_off,
 * ->ulp_vc_off instead of the old #defines. */

/* Saved GVC pointer (set by validate_engine_viewport_chain, reused by
 * cross_validate_camera LP cross-check). */
static uintptr_t g_gvc_ptr = 0;

/*
 * get_playercontroller() -- read APlayerController* from ULocalPlayer.
 * UPlayer::PlayerController is at +0x30 (stable across all UE5).
 * Returns nullptr if ULocalPlayer not found or pointer invalid.
 */
static void* get_playercontroller()
{
    if (!g_localplayer_ptr) return nullptr;
    uintptr_t pc = seh_read_ptr((uint8_t*)g_localplayer_ptr + g_ue_layout->uplayer_pc_off);
    if (pc < 0x10000 || pc >= 0x800000000000ULL) return nullptr;
    return (void*)pc;
}

/*
 * find_camera_manager_via_lp() -- walk LocalPlayer -> PlayerController
 * -> FField reflection to find PlayerCameraManager.
 *
 * This is game-agnostic: it uses the actual APlayerController* in memory
 * (not FName scan), so it works regardless of subclass name.
 */
static void* find_camera_manager_via_lp()
{
    void* pc = get_playercontroller();
    if (!pc) {
        bridge_log("  cam_via_lp: PlayerController not found (LP+0x30 null)");
        return nullptr;
    }

    char pc_name[128] = {0}, pc_cls[128] = {0};
    read_obj_names(pc, pc_name, sizeof(pc_name), pc_cls, sizeof(pc_cls));
    bridge_log("  cam_via_lp: PlayerController=0x%p name='%s' class='%s'",
               pc, pc_name, pc_cls);

    /* Resolve FName for PlayerCameraManager property */
    uint32_t pcm_fname = get_fname_cmpidx_for("PlayerCameraManager");
    if (pcm_fname == 0xFFFFFFFF) {
        bridge_log("  cam_via_lp: FName('PlayerCameraManager') not in pool");
        return nullptr;
    }

    /* FField reflection: walk APlayerController UClass + SuperStruct chain */
    uintptr_t pc_class = seh_read_ptr((uint8_t*)pc + 0x10);
    if (pc_class < 0x10000) {
        bridge_log("  cam_via_lp: invalid PC UClass");
        return nullptr;
    }

    int32_t pcm_off = -1;
    void* cls = (void*)pc_class;
    char cls_name[64] = {0};
    for (int depth = 0; cls && depth < 20 && pcm_off < 0; depth++) {
        pcm_off = ffield_find_offset(cls, pcm_fname);
        if (pcm_off >= 0) {
            resolve_fname(*(uint32_t*)((uint8_t*)cls + 0x18), cls_name, sizeof(cls_name));
            bridge_log("  cam_via_lp: PlayerCameraManager at PC+0x%X "
                       "(found in class '%s', depth=%d)",
                       pcm_off, cls_name, depth);
            break;
        }
        cls = (void*)seh_read_ptr((uint8_t*)cls + g_ue_layout->ustruct_super_off); /* SuperStruct */
        if ((uintptr_t)cls < 0x10000) break;
    }

    if (pcm_off < 0) {
        bridge_log("  cam_via_lp: PlayerCameraManager property not found "
                   "in APlayerController UClass chain");
        return nullptr;
    }

    uintptr_t pcm = seh_read_ptr((uint8_t*)pc + pcm_off);
    if (pcm < 0x10000 || pcm >= 0x800000000000ULL) {
        bridge_log("  cam_via_lp: PCM pointer null/invalid at PC+0x%X", pcm_off);
        return nullptr;
    }

    char pcm_name[128] = {0}, pcm_cls[128] = {0};
    read_obj_names((void*)pcm, pcm_name, sizeof(pcm_name),
                   pcm_cls, sizeof(pcm_cls));
    bridge_log("  cam_via_lp: APlayerCameraManager=0x%p name='%s' class='%s'",
               (void*)pcm, pcm_name, pcm_cls);
    return (void*)pcm;
}

/*
 * validate_engine_viewport_chain() -- sanity check via render path.
 *
 * Reads GEngine -> GameViewport -> World and compares with g_world_ptr.
 * If they match, GEngine pointer is confirmed correct.
 * If they differ, log a warning (GEngine may point to wrong object or
 * g_world_ptr may be stale after a map change).
 */
static void validate_engine_viewport_chain()
{
    if (!g_engine_ptr) return;

    uintptr_t gvc = seh_read_ptr((uint8_t*)g_engine_ptr + g_ue_layout->uengine_gvc_off);
    if (gvc < 0x10000) {
        bridge_log("  GVC chain: GameViewport null at GEngine+0x%X",
                   g_ue_layout->uengine_gvc_off);
        return;
    }

    /* Detect TObjectPtr encoding: if GVC is inside the game binary it is an
     * encoded handle (UE5.4+ TObjectPtr dynamic resolution), not a real heap ptr.
     * Fall back to LP->ViewportClient (+0x78) which always stores a raw pointer. */
    ModuleRegion rgn;
    bool in_binary = false;
    if (get_main_module(rgn)) {
        uintptr_t mod_lo = (uintptr_t)rgn.base;
        uintptr_t mod_hi = mod_lo + rgn.size;
        in_binary = (gvc >= mod_lo && gvc < mod_hi);
    }
    if (in_binary) {
        bridge_log("  GVC chain: GEngine+0x%X=0x%p is in binary range "
                   "(TObjectPtr-encoded), trying LP+0x78 fallback",
                   g_ue_layout->uengine_gvc_off, (void*)gvc);
        if (!g_localplayer_ptr) {
            bridge_log("  GVC chain: no LP available for GVC fallback");
            return;
        }
        uintptr_t lp_gvc = seh_read_ptr((uint8_t*)g_localplayer_ptr +
                                         g_ue_layout->ulp_vc_off);
        bool lp_valid = (lp_gvc >= 0x10000 && lp_gvc < 0x800000000000ULL);
        bool lp_in_bin = lp_valid &&
                         (lp_gvc >= (uintptr_t)rgn.base &&
                          lp_gvc < (uintptr_t)rgn.base + rgn.size);
        if (!lp_valid || lp_in_bin) {
            bridge_log("  GVC chain: LP+0x78=0x%p invalid or also in binary, "
                       "cannot resolve GVC", (void*)lp_gvc);
            return;
        }
        bridge_log("  GVC chain: LP+0x78=0x%p (heap, authoritative -- overrides GEngine field)",
                   (void*)lp_gvc);
        gvc = lp_gvc;
    }

    g_gvc_ptr = gvc;  /* save for LP cross-check in cross_validate_camera */

    uintptr_t gvc_world = seh_read_ptr((void*)(gvc + g_ue_layout->ugvc_world_off));
    bridge_log("  GVC chain: GameViewport=0x%p  GVC->World=0x%p  "
               "g_world_ptr=0x%p",
               (void*)gvc, (void*)gvc_world, g_world_ptr);

    if (!g_world_ptr) {
        /* GVC chain found a world we didn't -- use it and lock it */
        if (gvc_world >= 0x10000 && gvc_world < 0x800000000000ULL) {
            bridge_log("  GVC chain: adopting world 0x%p from render path (locked)",
                       (void*)gvc_world);
            g_world_ptr = (void*)gvc_world;
            g_world_from_gua = true;  /* lock: prevent FExec hook spam */
        }
        return;
    }

    if (gvc_world == (uintptr_t)g_world_ptr) {
        bridge_log("  GVC chain: World CONFIRMED (render path == g_world_ptr)");
        g_world_from_gua = true;  /* re-lock each time we confirm */
    } else {
        bridge_log("  GVC chain: World MISMATCH -- render=0x%p stored=0x%p "
                   "(map change? stale pointer?)",
                   (void*)gvc_world, g_world_ptr);
        /* Prefer the render-path world: it's what's actually being drawn.
         * Set g_world_from_gua=true to prevent FExec sublevel spam. */
        if (gvc_world >= 0x10000 && gvc_world < 0x800000000000ULL) {
            bridge_log("  GVC chain: updating g_world_ptr -> 0x%p (locked)", (void*)gvc_world);
            g_world_ptr = (void*)gvc_world;
            g_world_from_gua = true;
        }
    }
}

/*
 * verify_lp_via_gvc() -- cross-check g_localplayer_ptr using saved GVC.
 *
 * ULocalPlayer::ViewportClient = +0x78 (UE4SS MemberVarLayout_5_07).
 * If LP->ViewportClient == g_gvc_ptr, the LP pointer is independently
 * confirmed via the GEngine render chain.
 */
static bool verify_lp_via_gvc()
{
    if (!g_localplayer_ptr || !g_gvc_ptr) return false;

    uintptr_t lp_gvc = seh_read_ptr((uint8_t*)g_localplayer_ptr + g_ue_layout->ulp_vc_off);
    if (lp_gvc == g_gvc_ptr) {
        bridge_log("  LP cross-check: LP+0x78->GVC=0x%p == g_gvc_ptr CONFIRMED",
                   (void*)lp_gvc);
        return true;
    }
    bridge_log("  LP cross-check: LP+0x78->GVC=0x%p != g_gvc_ptr=0x%p MISMATCH "
               "(stale LP or GVC?)",
               (void*)lp_gvc, (void*)g_gvc_ptr);
    return false;
}

/*
 * find_camera_manager_uuu_style() -- UUU-style fixed-offset probe.
 *
 * UUU uses chain: GEngine->GameViewport->LocalPlayer->PlayerController,
 * then reads PlayerCameraManager at a game-specific fixed offset from PC.
 * The commonly cited value is PC+0x2A8 for UE5 games, but the actual
 * offset shifts upward with each UE5 minor version as new members are added
 * to APlayerController before PlayerCameraManager.
 *
 * Known observed offsets (UE4SS PDB / community reports):
 *   UE4.27:   ~0x2A0
 *   UE5.00-5.03: ~0x2A8
 *   UE5.04-5.05: ~0x2E0-0x300
 *   UE5.06-5.07: ~0x300-0x360
 *
 * We probe 8 candidates in 8-byte steps covering the full range.
 * Used ONLY for cross-validation; Path B (FField reflection) is authoritative.
 *
 * Returns the first valid-looking CameraManager pointer, or nullptr.
 * Logs all candidates found.
 */
static void* find_camera_manager_uuu_style()
{
    void* pc = get_playercontroller();
    if (!pc) {
        bridge_log("  cam_uuu_probe: no PlayerController");
        return nullptr;
    }

    /* Pass 1: layout-defined range, FName class check (UUU-style) */
    bridge_log("  cam_uuu_probe: PC=0x%p range [0x%X..0x%X] step=%d (%s)",
               pc, g_ue_layout->pc_pcm_start, g_ue_layout->pc_pcm_end,
               g_ue_layout->pc_pcm_step, g_ue_layout->name);

    void* best = nullptr;
    for (int32_t probe = g_ue_layout->pc_pcm_start;
         probe <= g_ue_layout->pc_pcm_end;
         probe += g_ue_layout->pc_pcm_step) {
        uintptr_t candidate = 0;
        __try { candidate = *(uintptr_t*)((uint8_t*)pc + probe); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        if (candidate < 0x10000 || candidate >= 0x800000000000ULL) continue;

        /* Must have a valid vtable */
        uintptr_t vt = 0;
        __try { vt = *(uintptr_t*)candidate; }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
        if (vt < 0x10000) continue;

        /* Must have a valid UClass pointer at +0x10 */
        uintptr_t cls = 0;
        __try { cls = *(uintptr_t*)(candidate + 0x10); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
        if (cls < 0x10000) continue;

        /* Check class FName for "Camera" substring */
        uint32_t cls_fname = 0;
        __try { cls_fname = *(uint32_t*)(cls + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        char cls_name[64] = {0};
        resolve_fname(cls_fname, cls_name, sizeof(cls_name));

        bool looks_like_cam = (strstr(cls_name, "Camera") != nullptr ||
                               strstr(cls_name, "camera") != nullptr);
        bridge_log("  cam_uuu_probe: PC+0x%X=0x%p class='%s'%s",
                   probe, (void*)candidate, cls_name,
                   looks_like_cam ? " <-- CAMERA" : "");

        if (looks_like_cam && !best) {
            best = (void*)candidate;
        }
    }

    if (best) return best;

    bridge_log("  cam_uuu_probe: FName probe found nothing in [0x%X..0x%X]",
               g_ue_layout->pc_pcm_start, g_ue_layout->pc_pcm_end);

    /*
     * Pass 2: direct pointer scan.
     *
     * If Path A already found g_camera_manager_ptr, scan the entire PC object
     * (offsets 0x100..0x800, step 8) for that exact address.  This cross-
     * validates Path A and discovers the actual PC::PlayerCameraManager field
     * offset even when the FName probe failed (wrong range, TObjectPtr, etc.).
     *
     * This scan also catches any valid-looking camera manager pointer even
     * when Path A has not run yet, by applying the same class-FName check
     * over the full 0x100..0x800 sweep.
     */
    bridge_log("  cam_uuu_probe: pass 2 -- full sweep PC+[0x100..0x800] step=8");

    uintptr_t known_mgr = (uintptr_t)g_camera_manager_ptr;

    for (int32_t probe = 0x100; probe <= 0x800; probe += 8) {
        uintptr_t candidate = 0;
        __try { candidate = *(uintptr_t*)((uint8_t*)pc + probe); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        if (candidate < 0x10000 || candidate >= 0x800000000000ULL) continue;

        /* If we have a known manager from Path A, direct match is definitive */
        if (known_mgr && candidate == known_mgr) {
            bridge_log("  cam_uuu_probe: XVAL -- PC+0x%X == Path-A manager 0x%p "
                       "(exact ptr match, cross-validation SUCCESS)",
                       probe, (void*)candidate);
            /* Update layout pc_pcm_start/end so future FName probes hit this offset.
             * Not strictly needed since we return the pointer, but useful for logs. */
            return (void*)candidate;
        }

        /* No known manager yet: apply class FName check over full range */
        if (!known_mgr) {
            uintptr_t vt = 0;
            __try { vt = *(uintptr_t*)candidate; }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
            if (vt < 0x10000) continue;

            uintptr_t cls = 0;
            __try { cls = *(uintptr_t*)(candidate + 0x10); }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
            if (cls < 0x10000) continue;

            uint32_t cls_fname = 0;
            __try { cls_fname = *(uint32_t*)(cls + 0x18); }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

            char cls_name[64] = {0};
            resolve_fname(cls_fname, cls_name, sizeof(cls_name));

            if (strstr(cls_name, "Camera") || strstr(cls_name, "camera")) {
                bridge_log("  cam_uuu_probe: pass2 PC+0x%X=0x%p class='%s' <-- CAMERA",
                           probe, (void*)candidate, cls_name);
                if (!best) best = (void*)candidate;
            }
        }
    }

    if (!best && !known_mgr)
        bridge_log("  cam_uuu_probe: full sweep found no camera-class pointer");
    if (!best && known_mgr)
        bridge_log("  cam_uuu_probe: XVAL FAIL -- Path-A manager 0x%p "
                   "not found anywhere in PC+[0x100..0x800]",
                   (void*)known_mgr);
    return best;
}

/*
 * cross_validate_camera() -- run all four paths and pick best result.
 *
 * Called after find_camera_manager() (Path A, GUObjectArray FName scan)
 * and find_localplayer() are complete.
 *
 * Path A: GUObjectArray FName scan (g_camera_manager_ptr)
 * Path B: LP -> PC -> FField property reflection (find_camera_manager_via_lp)
 * Path C: GEngine -> GVC -> World sanity (validate_engine_viewport_chain)
 *         + LP -> GVC cross-check (verify_lp_via_gvc)
 * Path D: LP -> PC -> fixed-offset probe scan (find_camera_manager_uuu_style)
 *         mirrors UUU's approach; used for comparison only.
 *
 * Priority: B > A > D (FField runtime reflection is most reliable).
 */
static void cross_validate_camera()
{
    /* Path C: render viewport world sanity + save g_gvc_ptr */
    validate_engine_viewport_chain();

    /* Path C cont: LP -> GVC cross-check (verifies g_localplayer_ptr) */
    verify_lp_via_gvc();

    /* Path B: LP -> PC -> FField reflection for PlayerCameraManager offset */
    void* cam_b = find_camera_manager_via_lp();

    /* Path D: LP -> PC -> fixed-offset probe (UUU-style) */
    void* cam_d = find_camera_manager_uuu_style();

    /* Summarize all four paths */
    bridge_log("  camera cross-val summary: "
               "A(FName)=0x%p  B(FField)=0x%p  D(UUU-probe)=0x%p",
               g_camera_manager_ptr, cam_b, cam_d);

    /* Agreement checks */
    if (cam_d && g_camera_manager_ptr && cam_d == g_camera_manager_ptr) {
        bridge_log("  camera cross-val: A==D -- FName result confirmed by "
                   "PC direct-ref scan 0x%p  [XVAL OK]", cam_d);
    } else if (cam_d && g_camera_manager_ptr && cam_d != g_camera_manager_ptr) {
        bridge_log("  camera cross-val: A!=D WARNING -- "
                   "FName picked 0x%p but PC+0x%X refs 0x%p  "
                   "(multiple PCM instances; D is authoritative)",
                   g_camera_manager_ptr,
                   g_ue_layout->pc_pcm_start,   /* printed as hint only */
                   cam_d);
    }
    if (cam_d && cam_b && cam_d != cam_b) {
        bridge_log("  camera cross-val: B!=D -- FField and UUU-probe disagree "
                   "(FField wins; UUU offset may be wrong for this UE version)");
    } else if (cam_d && cam_b && cam_d == cam_b) {
        bridge_log("  camera cross-val: B==D -- FField and UUU-probe AGREE 0x%p",
                   cam_b);
    }

    /*
     * Priority for g_camera_manager_ptr: B > D > A
     *
     * Path D (PC direct-ref) is preferred over Path A (last-non-CDO heuristic)
     * when they disagree.  PC+offset is authoritative: it is the manager the
     * PlayerController actually calls UpdateCamera() on.  Path A's "last non-CDO"
     * heuristic fails when multiple PCM instances exist (e.g. after seamless
     * travel: old PCM lingers, new PCM at higher GUA index gets selected).
     */
    if (!cam_b && !g_camera_manager_ptr) {
        if (cam_d) {
            bridge_log("  camera cross-val: A+B failed, using D(PC-ref)=0x%p", cam_d);
            g_camera_manager_ptr = cam_d;
        } else {
            bridge_log("  camera cross-val: ALL paths failed -- no camera control");
        }
        return;
    }

    if (!g_camera_manager_ptr && cam_b) {
        bridge_log("  camera cross-val: A(FName) missed, using B(FField)=0x%p "
                   "(BP subclass?)", cam_b);
        g_camera_manager_ptr = cam_b;
        return;
    }

    if (cam_b) {
        /* B is authoritative when available */
        if (cam_b != g_camera_manager_ptr) {
            bridge_log("  camera cross-val: A!=B -- using B(FField)=0x%p "
                       "(overrides FName heuristic)", cam_b);
            g_camera_manager_ptr = cam_b;
            g_cam_pov_ptr = nullptr;
        } else {
            bridge_log("  camera cross-val: CONFIRMED -- A==B==0x%p%s",
                       g_camera_manager_ptr,
                       (cam_d == cam_b) ? " (D also agrees)" : "");
        }
        return;
    }

    /* B failed; A found something. Prefer D over A when they disagree. */
    if (cam_d && cam_d != g_camera_manager_ptr) {
        bridge_log("  camera cross-val: A!=D (no B) -- "
                   "switching to D(PC-ref)=0x%p (was A=%0xp)",
                   cam_d, g_camera_manager_ptr);
        g_camera_manager_ptr = cam_d;
        g_cam_pov_ptr = nullptr; /* invalidate: manager changed */
        return;
    }

    bridge_log("  camera cross-val: B failed, keeping A(FName)=0x%p%s",
               g_camera_manager_ptr,
               (!cam_d) ? " (D also failed)" : " (A==D)");
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
        /* Silent: table full, stop scanning */
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
    /* Capture UWorld from Exec parameter -- only as a FALLBACK when the
     * GUObjectArray scan has not found it yet.  The GUA scan is reliable
     * (validates class FName + outer chain); the hook sees many different
     * pointers per frame, most of which are NOT the real game UWorld. */
    if (!g_world_from_gua &&
        world && (uintptr_t)world > 0x10000 &&
        (uintptr_t)world < 0x7F0000000000ULL)
    {
        if (g_world_ptr != world) {
            g_world_ptr = world;
            bridge_log("HOOK: UWorld captured 0x%p (this_fexec=0x%p) [fallback]",
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
    bridge_log("EXEC: '%s'  (engine=0x%p world=0x%p lp=0x%p)",
               cmd, g_engine_ptr, g_world_ptr, g_localplayer_ptr);
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

    void* world = g_world_ptr;

    /* Use GEngine's original Exec to avoid recursion.
     * GEngine hook is always the first entry in g_fexec_hook_table. */
    FExecExecFn exec_fn = g_fexec_exec;
    if (g_fexec_hook_count > 0)
        exec_fn = g_fexec_hook_table[0].original;

    bool cmd_ret = false;
    bool call_ok = seh_call_fexec(exec_fn, this_fexec,
                                   world, wcmd.data(), ar, &cmd_ret);

    /* If crash with a world pointer, the pointer may be stale (map reload).
     * Clear it and retry with NULL -- CVars/stat work without world. */
    if (!call_ok && world) {
        bridge_log("  RETRY: GEngine crashed (world=0x%p stale?), retrying null", world);
        g_world_ptr = nullptr;
        /* Keep g_world_from_gua=true: do NOT unlock the FExec hook here.
         * Unlocking causes sublevel worlds to flood g_world_ptr.
         * GVC chain re-check on next __bridge_rescan will re-acquire. */
        world = nullptr;
        call_ok = seh_call_fexec(exec_fn, this_fexec,
                                  nullptr, wcmd.data(), ar, &cmd_ret);
    }
    if (!call_ok) {
        bridge_log("  ERROR: GEngine FExec::Exec crashed");
        return false;
    }

    if (cmd_ret) {
        bridge_log("  OK ret=1 (GEngine)");
        return true;
    }

    /* GEngine returned false -- gameplay commands route via ULocalPlayer::Exec.
     * ULocalPlayer is found actively via GUObjectArray + FName scan.
     * Helper lambda: call LP Exec via its FExec subobject. */
    auto try_lp_exec = [&](void* lp_fexec_subobj) -> bool {
        if (!lp_fexec_subobj) return false;
        uintptr_t lp_vtable = seh_read_ptr(lp_fexec_subobj);
        if (!lp_vtable) return false;

        FExecExecFn lp_fn = nullptr;

        /* Look up in hook table first (use original if hooked) */
        for (int i = 0; i < g_fexec_hook_count; i++) {
            if (g_fexec_hook_table[i].vtable_base == lp_vtable) {
                lp_fn = g_fexec_hook_table[i].original;
                break;
            }
        }

        /* Fallback: vtable not hooked (FExec has only 2 entries, scan
         * requires >= 3), so vtable[1] is still the original Exec. */
        if (!lp_fn)
            lp_fn = (FExecExecFn)seh_read_ptr((void*)(lp_vtable + 8));

        if (!lp_fn || !validate_function_ptr((void*)lp_fn)) return false;
        bool lp_ret = false;
        bool lp_ok  = seh_call_fexec(lp_fn, lp_fexec_subobj,
                                      world, wcmd.data(), ar, &lp_ret);
        if (lp_ok) {
            bridge_log("  OK ret=%d (ULocalPlayer)", (int)lp_ret);
            return true;
        }
        bridge_log("  ERROR: ULocalPlayer FExec crashed");
        return false;
    };

    if (!g_localplayer_ptr) find_localplayer();
    if (g_localplayer_ptr) {
        uintptr_t fexec_off = g_fexec_offset ? g_fexec_offset : 0x28;
        void* lp_fexec = (uint8_t*)g_localplayer_ptr + fexec_off;
        if (try_lp_exec(lp_fexec)) return true;
    }

    bridge_log("  OK ret=0 (GEngine rejected, LocalPlayer not found)");
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
