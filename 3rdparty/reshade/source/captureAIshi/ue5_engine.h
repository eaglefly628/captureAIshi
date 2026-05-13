/*
 * ue5_engine.h -- UE5 engine interface for captureAIshi bridge
 *
 * Orchestrator header: defines the engine-wide globals, type stubs, and SEH
 * helpers used by the implementation files included at the bottom, then
 * provides high-level helpers (exec_console_command, HUD toggle, timestop,
 * free-camera commands, hotsampling) layered on top.
 *
 * WARNING: This header contains static global state. It MUST only be
 * included from a single translation unit (bridge.cpp). Including from
 * multiple .cpp files will create independent copies.
 *
 * Build requirement: TU including this header MUST be compiled with /EHa
 * (Async exception handling) so __try blocks can coexist with C++ stack
 * objects that have destructors. ReShade.vcxproj sets /EHa explicitly for
 * bridge.cpp via per-file AdditionalOptions.
 *
 * ASCII only (MSVC C4819 compliance).
 */

#ifndef CAPTUREAI_UE5_ENGINE_H
#define CAPTUREAI_UE5_ENGINE_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
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

/* -- GEngine globals ----------------------------------------------- */

static UEngine*          g_engine_ptr = nullptr;
static std::atomic<bool> g_engine_found{false};

/* Address of the GEngine global variable itself (not the pointer value) */
static uintptr_t         g_engine_global_addr = 0;

/* -- UWorld globals (used by ue5_scan_world.h / ue5_scan_camera.h) - */

/* g_world_from_gua: true when g_world_ptr was set by the GUA scan
 * (reliable). When true, future FExec hooks would not overwrite it. */
static void*             g_world_ptr = nullptr;
static bool              g_world_from_gua = false;

/* -- FExec typedef + globals (referenced by ue5_scan_engine.h) ----- */

/* FExec::Exec signature (secondary-vtable entry on UEngine multi-inherit). */
typedef bool (__fastcall *FExecExecFn)(
    void* this_fexec,     /* rcx = FExec subobject (GEngine + offset) */
    void* world,          /* rdx = UWorld* (NULL ok for most cmds) */
    const wchar_t* cmd,   /* r8  = command string */
    void* output_device   /* r9  = FOutputDevice& */
);

static FExecExecFn g_fexec_exec   = nullptr;
static uintptr_t   g_fexec_offset = 0;   /* byte offset in GEngine */

/* -- GUObjectArray constants --------------------------------------- */

/*
 * GUObjectArray (FUObjectArray) is the master UObject registry.
 * Layout (UE5, x64): see ue5_scan_engine.h header comment for details.
 */
#define GUOBJARRAY_OBJECTS_OFF    16
#define GUOBJARRAY_NUMELEMS_OFF   36
#define FUOBJECTARRAY_CHUNK_SHIFT 16
#define FUOBJECTARRAY_CHUNK_MASK  0xFFFF

/* -- UEVersionLayout (per-version memory offset table) ------------- */

struct UEVersionLayout {
    const char* name;

    /* FUObjectItem */
    int  fuobjectitem_stride;    /* 24=Shipping, 32=Dev/WithVerseVM */
    int  fuobjectitem_obj_off;   /* offset of UObjectBase* inside item */

    /* UObjectBase::ObjectFlags (32-bit EObjectFlags, 0x08 for UE4/5) */
    int  ue_obj_flags_off;

    /* FField chain (UStruct::ChildProperties walk) */
    int  ffield_next_off;
    int  ffield_name_off;
    int  fprop_offset_off;
    int  ustruct_childprops_off;
    int  ustruct_super_off;

    /* UPlayer / ULocalPlayer chain */
    int  uplayer_pc_off;
    int  ulp_vc_off;

    /* UEngine / UGameViewportClient */
    int  uengine_gvc_off;
    int  ugvc_world_off;

    /* FMinimalViewInfo inside FCameraCacheEntry */
    bool fmvi_is_lwc;
    int  fcce_pov_off;
    int  fmvi_loc_x, fmvi_loc_y, fmvi_loc_z;
    int  fmvi_pitch, fmvi_yaw,   fmvi_roll;
    int  fmvi_fov;

    /* FMinimalViewInfo direct offset from APlayerCameraManager base */
    int  cam_pov_direct_off;

    /* APlayerController -> APlayerCameraManager UUU-style probe */
    int  pc_pcm_start;
    int  pc_pcm_end;
    int  pc_pcm_step;
};

/* UE5.7 -- VERIFIED StackOBot UE5.7 Dev */
static const UEVersionLayout k_layout_ue57 = {
    "UE5.7",
    32,   0x08,
    0x08,
    0x18, 0x20, 0x44, 0x50, 0x40,
    0x30, 0x78,
    0x200, 0x78,
    true,  0x08,
    0x00,  0x08,  0x10,
    0x18,  0x20,  0x28,
    0x30,
    0x360,
    0x388, 0x398, 8,
};

/* UE5.3-5.6 -- INFERRED */
static const UEVersionLayout k_layout_ue53 = {
    "UE5.3-5.6",
    24,   0x00,
    0x08,
    0x18, 0x20, 0x44, 0x50, 0x40,
    0x30, 0x78,
    0x200, 0x78,
    true,  0x08,
    0x00,  0x08,  0x10,
    0x18,  0x20,  0x28,
    0x30,
    0,
    0x2A0, 0x360, 8,
};

/* UE5.0-5.2 -- INFERRED */
static const UEVersionLayout k_layout_ue50 = {
    "UE5.0-5.2",
    24,   0x00,
    0x08,
    0x20, 0x28, 0x4C, 0x50, 0x40,
    0x30, 0x78,
    0x200, 0x78,
    true,  0x08,
    0x00,  0x08,  0x10,
    0x18,  0x20,  0x28,
    0x30,
    0,
    0x2A0, 0x340, 8,
};

/* UE4.27 -- INFERRED */
static const UEVersionLayout k_layout_ue427 = {
    "UE4.27",
    24,   0x00,
    0x08,
    0x20, 0x28, 0x4C, 0x50, 0x40,
    0x30, 0x78,
    0x200, 0x78,
    false, 0x10,
    0x00,  0x04,  0x08,
    0x0C,  0x10,  0x14,
    0x18,
    0,
    0x2A0, 0x2C0, 8,
};

/* Active layout -- default UE5.7; override at startup for other games */
static const UEVersionLayout* g_ue_layout = &k_layout_ue57;

/* FUObjectItem layout -- detected at runtime via GEngine cross-validation. */
static int g_fuobjectitem_stride    = 24;
static int g_fuobjectitem_object_off = 0;

static void*              g_guobjectarray = nullptr;
static std::atomic<bool>  g_guobjectarray_found{false};

/* -- Debug break support ------------------------------------------- */

/* When armed (via TCP command), bridge calls __debugbreak() at the next
 * UWorld/LocalPlayer discovery for attach-from-debugger workflows.
 * One-shot: auto-disarms after the first break fires. */
static std::atomic<bool> g_debug_break_armed{false};

/* -- Exec function (slim UEngine::Exec vtable path) ---------------- */

/*
 * UEngine::Exec via primary vtable.  Different from FExec::Exec above:
 * this is the per-engine virtual call at vtable[~110-130], not the
 * secondary-vtable FExec subobject entry.  Used by exec_console_command
 * below when bridge_log/etc forward simple console commands.
 */
typedef bool (__fastcall *ExecFn)(
    void* engine,         /* rcx = this (GEngine) */
    void* world,          /* rdx = UWorld* (can be NULL) */
    const wchar_t* cmd,   /* r8  = command string */
    void* output_device   /* r9  = FOutputDevice& */
);

static ExecFn g_exec_fn = nullptr;

/* GLog is UE5's global log output device.  Currently unused (passed as
 * NULL is safe for most commands); kept for future wiring. */
static void* g_log_ptr = nullptr;

/* -- SEH-safe helpers ----------------------------------------------
 *
 * Two flavors live here:
 *
 * 1. The original slim helpers (`*_ok` variants writing to out-params)
 *    used by exec_console_command and other slim code paths.  These
 *    isolate SEH into pure-C wrappers in case the host TU lacks /EHa.
 *
 * 2. The RDC-style helpers (`seh_read_ptr` returning uintptr_t, etc.)
 *    used by ue5_scan_engine.h, ue5_scan_world.h, ue5_scan_camera.h.
 *    These rely on /EHa being on for bridge.cpp (set in ReShade.vcxproj).
 */

#pragma warning(push)
#pragma warning(disable: 4733)  /* SEH installed via try/except */

/* -- Slim *_ok helpers (used by exec_console_command) -- */

static bool seh_probe_read(const void* addr)
{
    __try {
        volatile uintptr_t t = *(const uintptr_t*)addr;
        (void)t;
        return true;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

static bool seh_read_ptr_ok(const void* addr, uintptr_t* out)
{
    __try {
        *out = *(const uintptr_t*)addr;
        return true;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

static bool seh_read_u8_ok(const void* addr, uint8_t* out)
{
    __try {
        *out = *(const uint8_t*)addr;
        return true;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

typedef void* SehExec4Args[4];
static bool seh_call_exec4(void* fn, void* p1, void* p2, void* p3, void* p4)
{
    typedef int (__fastcall *Exec4Fn)(void*, void*, void*, void*);
    Exec4Fn f = (Exec4Fn)fn;
    __try {
        (void)f(p1, p2, p3, p4);
        return true;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

/* -- RDC-style helpers (used by ue5_scan_*.h) -- */

/* Safely read a pointer value; returns 0 on access violation. */
static uintptr_t seh_read_ptr(const void* addr)
{
    __try {
        return *(const uintptr_t*)addr;
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

#pragma warning(pop)

/* -- validate_function_ptr (forward-declared in ue5_scan_engine.h) - */

/*
 * Check that fn looks like a real x64 function entry point: low-address
 * filter + first-byte prologue sniff.  Single body shared between the
 * slim exec_console_command path and the scan_*.h files.
 */
static bool validate_function_ptr(void* fn)
{
    if (!fn || (uintptr_t)fn < 0x10000) return false;
    uint8_t b0 = 0;
    if (!seh_read_u8_ok(fn, &b0)) return false;
    return (b0 == 0x40 || b0 == 0x48 || b0 == 0x4C ||
            b0 == 0x41 || b0 == 0x55 || b0 == 0x53 ||
            b0 == 0x56 || b0 == 0x57 || b0 == 0xE9 ||
            b0 == 0xCC);
}

/* -- Camera struct ------------------------------------------------- */

struct CameraState {
    float x, y, z;           /* position (UE5 units = cm) */
    float pitch, yaw, roll;  /* rotation (degrees) */
    float fov;               /* field of view (degrees) */
};

/* Live camera state -- written by camera path playback or TCP commands. */
static CameraState g_camera = {0, 0, 0, 0, 0, 0, 90.0f};
static std::atomic<bool> g_camera_override{false};

/* -- Game speed ---------------------------------------------------- */

static float g_game_speed = 1.0f;
static std::atomic<bool> g_paused{false};

/* -- Implementation files included here ----------------------------
 *
 * Each file is ONLY ever included from here -- never standalone.  Include
 * order is critical: each file depends on globals and forward decls
 * defined above. */
#include "ue5_scan_engine.h"   /* GEngine, GUObjectArray, FNamePool */
#include "ue5_scan_world.h"    /* UWorld, ULocalPlayer              */
#include "ue5_scan_camera.h"   /* PCM, cam_pov, cross-validation    */

/* -- High-level helpers (slim path) --------------------------------
 *
 * exec_console_command and friends use the primary UEngine::Exec vtable
 * (slim approach), independent of the FExec hook machinery that the RDC
 * path uses.  No FExec hooks are installed on the ReShade side.
 */

static bool exec_console_command(const char* cmd)
{
    bridge_log("CMD: %s", cmd);

    if (!g_engine_found || !g_engine_ptr) {
        bridge_log("  [SKIP] GEngine not available");
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

    uintptr_t* vtable = *(uintptr_t**)g_engine_ptr;
    if (!vtable || (uintptr_t)vtable < 0x10000) {
        bridge_log("  ERROR: Invalid vtable pointer");
        return false;
    }

    /* If we already found the Exec function, call it directly. */
    if (g_exec_fn) {
        void* cmd_ptr = (void*)wcmd.data();
        if (seh_call_exec4((void*)g_exec_fn, g_engine_ptr, NULL, cmd_ptr, g_log_ptr)) {
            bridge_log("  OK (direct call)");
            return true;
        }
        bridge_log("  ERROR: Exec call crashed, clearing cached fn");
        g_exec_fn = nullptr;
        return false;
    }

    /* Probe vtable to find Exec using a safe no-op command first. */
    bridge_log("  Probing vtable for Exec with safe command...");

    const wchar_t* probe_cmd = L"stat none";

    for (int idx = 110; idx <= 130; idx++) {
        uintptr_t fn_addr = 0;
        if (!seh_read_ptr_ok(&vtable[idx], &fn_addr)) continue;
        void* fn = (void*)fn_addr;
        if (!validate_function_ptr(fn)) continue;

        ExecFn try_exec = (ExecFn)fn;

        if (!seh_call_exec4((void*)try_exec, g_engine_ptr, NULL, (void*)probe_cmd, g_log_ptr))
            continue;

        g_exec_fn = try_exec;
        bridge_log("  Found Exec at vtable[%d] = 0x%p", idx, fn);

        void* cmd_ptr = (void*)wcmd.data();
        if (!seh_call_exec4((void*)g_exec_fn, g_engine_ptr, NULL, cmd_ptr, g_log_ptr)) {
            bridge_log("  ERROR: Cached Exec crashed on user command");
            g_exec_fn = nullptr;
            return false;
        }
        bridge_log("  OK");
        return true;
    }

    bridge_log("  FAILED: Could not find Exec in vtable[110..130]");
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
        return set_game_speed(0.0001f);
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
    HWND game_wnd = NULL;

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

    game_wnd = ctx.result;
    if (!game_wnd) {
        bridge_log("ERROR: Could not find game window for hotsampling");
        return false;
    }

    LONG style = GetWindowLongA(game_wnd, GWL_STYLE);
    SetWindowLongA(game_wnd, GWL_STYLE, style & ~(WS_CAPTION | WS_THICKFRAME));

    SetWindowPos(game_wnd, HWND_TOP, 0, 0, width, height,
                 SWP_NOMOVE | SWP_FRAMECHANGED);

    char cmd[128];
    snprintf(cmd, sizeof(cmd), "r.SetRes %dx%d", width, height);
    exec_console_command(cmd);

    bridge_log("Hotsampled to %dx%d", width, height);
    return true;
}

#endif /* CAPTUREAI_UE5_ENGINE_H */
