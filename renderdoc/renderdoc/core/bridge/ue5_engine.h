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
#include <mutex>

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

/* Safely read a uint32_t; returns 0 on access violation.
 * 0 is a valid FName ComparisonIndex ("None") so callers that need
 * to distinguish AV from legitimate zero must use seh_read_u32_ok. */
static uint32_t seh_read_u32(const void* addr)
{
    __try {
        return *(const uint32_t*)addr;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
}

/* Safely read a uint32_t with success flag; returns false on AV. */
static bool seh_read_u32_ok(const void* addr, uint32_t* out)
{
    __try {
        *out = *(const uint32_t*)addr;
        return true;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        return false;
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


/* -- Implementation (split for readability) -------------------------
 * Each file is ONLY ever included from here -- never standalone.
 * Include order is critical: each file depends on globals and
 * forward declarations defined in files included before it. */
#include "ue5_scan_engine.h"   /* GEngine, GUObjectArray, FNamePool */
#include "ue5_scan_world.h"    /* UWorld, ULocalPlayer              */
#include "ue5_scan_camera.h"   /* PCM, cam_pov, cross-validation    */
#include "ue5_exec_hook.h"     /* FExec hook, console exec, gthr    */
#include "ue5_actions.h"       /* timestop, HUD, camera, hotsample  */

#endif /* CAPTUREAI_UE5_ENGINE_H */
