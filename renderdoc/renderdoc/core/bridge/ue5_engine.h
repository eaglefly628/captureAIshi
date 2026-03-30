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

/* ── UE5 type stubs ──────────────────────────────────────────────── */

/* We only need opaque pointers; no real UE5 headers needed */
typedef void UEngine;
typedef void UWorld;
typedef void APlayerController;
typedef void FOutputDevice;

/* ── GEngine finder ──────────────────────────────────────────────── */

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

/* ── Exec function ───────────────────────────────────────────────── */

/*
 * UEngine::Exec is NOT a simple virtual call in shipped games.
 * Instead, we find and call these two alternatives:
 *
 * Option A: GEngine->Exec(UWorld*, const TCHAR*, FOutputDevice&)
 *   - Virtual function, vtable index varies per UE version
 *   - Risky: wrong index = crash
 *
 * Option B: FExec::Exec(UWorld*, const TCHAR*, FOutputDevice&)
 *   - Static/global function, can be found by pattern scan
 *   - Safer: direct call, no vtable lookup needed
 *
 * Option C: UGameplayStatics::ExecuteConsoleCommand() via ProcessEvent
 *   - Uses UE5 reflection system
 *   - Most robust but requires finding UObject::ProcessEvent
 *
 * We use Option A with validation: scan for the Exec function
 * prologue pattern and verify it looks correct before calling.
 *
 * In x64 MSVC, __thiscall uses rcx=this (same as __fastcall).
 */
typedef bool (__fastcall *ExecFn)(
    void* engine,         /* rcx = this (GEngine) */
    void* world,          /* rdx = UWorld* (can be NULL) */
    const wchar_t* cmd,   /* r8  = command string */
    void* output_device   /* r9  = FOutputDevice& */
);

static ExecFn g_exec_fn = nullptr;

/* ── GLog (default output device) ────────────────────────────────── */

/* GLog is UE5's global log output device, needed for Exec() calls.
 * We find it the same way as GEngine: string xref scan.
 * If not found, we pass NULL (most commands still work). */
static void* g_log_ptr = nullptr;

/* ── Camera struct ───────────────────────────────────────────────── */

struct CameraState {
    float x, y, z;           /* position (UE5 units = cm) */
    float pitch, yaw, roll;  /* rotation (degrees) */
    float fov;               /* field of view (degrees) */
};

/* Live camera state - written by camera path playback or TCP commands */
static CameraState g_camera = {0, 0, 0, 0, 0, 0, 90.0f};
static std::atomic<bool> g_camera_override{false};

/* ── Game speed ──────────────────────────────────────────────────── */

static float g_game_speed = 1.0f;
static std::atomic<bool> g_paused{false};

/* ── Implementation ──────────────────────────────────────────────── */

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
     * Strategy 1: Find L"ToggleDebugCamera" wide string.
     * This string is always present in shipped UE5 games and is
     * processed by code that accesses GEngine->GameViewport or
     * the player controller. Nearby code loads GEngine.
     */
    const wchar_t* search_strings[] = {
        L"ToggleDebugCamera",
        L"r.Streaming.PoolSize",
        L"GEngine",
        L"SetViewLocation",
    };

    for (const wchar_t* search_str : search_strings) {
        const uint8_t* str_addr = find_wstring_in_module(
            rgn.base, rgn.size, search_str);

        if (!str_addr) {
            bridge_log("String L\"%ls\" not found, trying next...",
                       search_str);
            continue;
        }

        bridge_log("Found L\"%ls\" at offset 0x%llX",
                   search_str,
                   (unsigned long long)(str_addr - rgn.base));

        /* Find all code references to this string */
        auto xrefs = find_xrefs(rgn.base, rgn.size, (uintptr_t)str_addr);
        bridge_log("  Found %zu cross-references", xrefs.size());

        for (const uint8_t* xref : xrefs) {
            bridge_log("  Xref at offset 0x%llX",
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

            for (const uint8_t* p = search_start; p < search_end; p++) {
                if (p[0] != 0x48 || p[1] != 0x8B) continue;
                /* ModRM: mod=00, rm=101 means [rip+disp32] */
                if ((p[2] & 0xC7) != 0x05) continue;

                uintptr_t resolved = resolve_rip_relative(p, 3, 7);

                /* Validate: the resolved address should be in the
                 * module's data section (.data or .bss), which is
                 * typically in the upper portion of the image. */
                if (resolved < (uintptr_t)rgn.base ||
                    resolved >= (uintptr_t)(rgn.base + rgn.size))
                    continue;

                /* Read the pointer value at that address */
                void* candidate = *(void**)resolved;
                if (!candidate) continue;

                /* Basic validation: the pointer should point to
                 * a valid-looking object (not stack, not too low).
                 * UE5 objects are heap-allocated, typically >0x10000. */
                if ((uintptr_t)candidate < 0x10000) continue;

                /* Check if the pointed-to object has a vtable
                 * (first 8 bytes should be a valid pointer too) */
                __try {
                    uintptr_t vtable = *(uintptr_t*)candidate;
                    if (vtable < 0x10000) continue;

                    /* This looks like a valid engine pointer!
                     * Store it and verify by trying a benign read. */
                    g_engine_global_addr = resolved;
                    g_engine_ptr = (UEngine*)candidate;
                    g_engine_found = true;

                    bridge_log("GEngine FOUND via '%ls' xref!",
                               search_str);
                    bridge_log("  Global addr: 0x%llX (offset 0x%llX)",
                               (unsigned long long)resolved,
                               (unsigned long long)(resolved - (uintptr_t)rgn.base));
                    bridge_log("  Pointer value: 0x%p", candidate);
                    bridge_log("  VTable: 0x%llX", (unsigned long long)vtable);

                    return true;
                }
                __except(EXCEPTION_EXECUTE_HANDLER) {
                    /* Access violation - not a valid pointer */
                    continue;
                }
            }
        }
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

/* ── Console command execution ───────────────────────────────────── */

/*
 * Execute a UE5 console command via GEngine->Exec().
 *
 * When g_exec_fn is found (via pattern scan), we call it directly.
 * Otherwise, we fall back to the virtual function call through
 * the vtable at a known index.
 *
 * UE5 Exec is at different vtable indices per version:
 *   UE 5.0-5.1: ~index 114-118
 *   UE 5.2-5.3: ~index 116-120
 *   UE 5.4+:    ~index 118-122
 *
 * We validate by checking that the function at the index
 * starts with a valid prologue (push rbp / sub rsp / mov).
 */

/* Validate a function pointer looks like a real function */
static bool validate_function_ptr(void* fn)
{
    if (!fn || (uintptr_t)fn < 0x10000) return false;

    __try {
        uint8_t* bytes = (uint8_t*)fn;
        /* Check for common x64 function prologues:
         * 40 55        push rbp
         * 48 89 5C     mov [rsp+...], rbx
         * 48 83 EC     sub rsp, N
         * 48 8B C1     mov rax, rcx
         * 4C 89 44     mov [rsp+...], r8
         * 41 56        push r14
         * 55           push rbp
         * 53           push rbx
         */
        uint8_t b0 = bytes[0];
        if (b0 == 0x40 || b0 == 0x48 || b0 == 0x4C ||
            b0 == 0x41 || b0 == 0x55 || b0 == 0x53 ||
            b0 == 0x56 || b0 == 0x57 || b0 == 0xE9 ||
            b0 == 0xCC) {
            return true;
        }
        return false;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

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

    /*
     * Call through vtable. UEngine::Exec is a virtual function.
     *
     * vtable layout (simplified):
     *   vptr -> [0]: destructor
     *           [1]: ...
     *           [N]: Exec(UWorld*, TCHAR*, FOutputDevice&)
     *
     * We try indices 110-130 and validate each looks like Exec
     * by checking the function prologue and attempting a safe call.
     *
     * The Exec function signature in x64 MSVC __fastcall:
     *   rcx = this (UEngine*)
     *   rdx = UWorld* (NULL for global commands)
     *   r8  = const TCHAR* (command)
     *   r9  = FOutputDevice& (GLog or NULL)
     */

    uintptr_t* vtable = *(uintptr_t**)g_engine_ptr;
    if (!vtable || (uintptr_t)vtable < 0x10000) {
        bridge_log("  ERROR: Invalid vtable pointer");
        return false;
    }

    /* If we already found the Exec function, call it directly */
    if (g_exec_fn) {
        __try {
            g_exec_fn(g_engine_ptr, NULL, wcmd.data(), g_log_ptr);
            bridge_log("  OK (direct call)");
            return true;
        }
        __except(EXCEPTION_EXECUTE_HANDLER) {
            bridge_log("  ERROR: Exec call crashed, clearing cached fn");
            g_exec_fn = nullptr;
            return false;
        }
    }

    /* Probe vtable to find Exec using a safe no-op command first.
     * "stat none" is benign: disables all stat overlays, no side effects.
     * Only after we confirm the correct vtable index do we run the
     * user's actual command. */
    bridge_log("  Probing vtable for Exec with safe command...");

    const wchar_t* probe_cmd = L"stat none";

    for (int idx = 110; idx <= 130; idx++) {
        __try {
            void* fn = (void*)vtable[idx];
            if (!validate_function_ptr(fn)) continue;

            ExecFn try_exec = (ExecFn)fn;

            /* Probe with safe command first */
            try_exec(g_engine_ptr, NULL, probe_cmd, g_log_ptr);

            /* If we get here, this index works. Cache it. */
            g_exec_fn = try_exec;
            bridge_log("  Found Exec at vtable[%d] = 0x%p", idx, fn);

            /* Now run the actual user command */
            g_exec_fn(g_engine_ptr, NULL, wcmd.data(), g_log_ptr);
            bridge_log("  OK");
            return true;
        }
        __except(EXCEPTION_EXECUTE_HANDLER) {
            continue;
        }
    }

    bridge_log("  FAILED: Could not find Exec in vtable[110..130]");
    return false;
}

/* ── Timestop / Game Speed ───────────────────────────────────────── */

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

/* ── HUD Toggle ──────────────────────────────────────────────────── */

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

/* ── Free Camera ─────────────────────────────────────────────────── */

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

/* ── Hotsampling (Window Resize) ─────────────────────────────────── */

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
