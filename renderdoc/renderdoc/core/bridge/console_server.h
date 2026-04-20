/*
 * console_server.h -- captureAIshi console server for renderdoc
 *
 * Embedded into renderdoc.dll. Uses only Win32 threads (no std::thread)
 * to avoid C++14 compatibility issues with renderdoc's build system.
 *
 * ASCII only (MSVC C4819 compliance).
 */

#ifndef CAPTUREAI_CONSOLE_SERVER_H
#define CAPTUREAI_CONSOLE_SERVER_H

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <atomic>
#include <mutex>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "psapi.lib")

/* Suppress deprecation warnings for getenv/sscanf/inet_addr */
#pragma warning(push)
#pragma warning(disable: 4996)

/* -- Logging ----------------------------------------------------- */

/* Use OutputDebugStringA for logging -- visible in debugger and
 * RenderDoc's own log. Single call to avoid DebugView line splitting. */
static void BRIDGE_LOG(const char* fmt, ...)
{
    char buf[1024];
    const char prefix[] = "[BRIDGE] ";
    const int prefix_len = sizeof(prefix) - 1;
    memcpy(buf, prefix, prefix_len);

    va_list args;
    va_start(args, fmt);
    int avail = (int)(sizeof(buf) - prefix_len - 2);
    int n = vsnprintf(buf + prefix_len, avail, fmt, args);
    va_end(args);

    /* vsnprintf returns "would have written" on truncation, which can
     * exceed avail.  Clamp so buf[total] stays in bounds. */
    int nc = (n < 0) ? 0 : (n >= avail ? avail - 1 : n);
    int total = prefix_len + nc;
    if (total > 0 && buf[total - 1] != '\n') { buf[total] = '\n'; buf[total + 1] = '\0'; }
    OutputDebugStringA(buf);
}

static void bridge_log_adapter(const char* fmt, ...)
{
    char buf[1024];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    BRIDGE_LOG("%s", buf);
}

#define bridge_log bridge_log_adapter

#include "pattern_scan.h"
#include "ue5_engine.h"
#include "camera_path.h"
#include "camera_intercept.h"

#undef bridge_log

/* -- Configuration ----------------------------------------------- */

static const int CONSOLE_DEFAULT_PORT = 9998;
static const int CONSOLE_MAX_CMD_LEN  = 4096;

/* -- Camera Smoothing -------------------------------------------- */

/* atomic<float>: plain float was being hoisted to a register on /O2 so
 * the tick thread never observed __smooth updates.  Relaxed ordering is
 * enough (no data-dependent paired stores). */
static std::atomic<float> cs_smooth_factor{1.0f};
static Vec3  cs_smooth_pos = {0, 0, 0};
static float cs_smooth_pitch = 0, cs_smooth_yaw = 0, cs_smooth_roll = 0;
/* Read by tick thread, written by TCP thread (__smooth command resets it).
 * atomic avoids torn read + gives release/acquire semantics on the flag. */
static std::atomic<bool> cs_smooth_initialized{false};

static InterpolatedCamera cs_apply_smoothing(const InterpolatedCamera& raw)
{
    float smooth = cs_smooth_factor.load(std::memory_order_relaxed);
    if (smooth <= 1.0f || !cs_smooth_initialized.load()) {
        cs_smooth_pos = raw.pos;
        cs_smooth_pitch = raw.pitch;
        cs_smooth_yaw = raw.yaw;
        cs_smooth_roll = raw.roll;
        cs_smooth_initialized.store(true);
        return raw;
    }
    float alpha = 1.0f / smooth;
    cs_smooth_pos.x += (raw.pos.x - cs_smooth_pos.x) * alpha;
    cs_smooth_pos.y += (raw.pos.y - cs_smooth_pos.y) * alpha;
    cs_smooth_pos.z += (raw.pos.z - cs_smooth_pos.z) * alpha;
    cs_smooth_pitch += (raw.pitch - cs_smooth_pitch) * alpha;
    cs_smooth_yaw   += (raw.yaw   - cs_smooth_yaw)   * alpha;
    cs_smooth_roll  += (raw.roll  - cs_smooth_roll)  * alpha;

    InterpolatedCamera out;
    out.pos   = cs_smooth_pos;
    out.pitch = cs_smooth_pitch;
    out.yaw   = cs_smooth_yaw;
    out.roll  = cs_smooth_roll;
    out.fov   = raw.fov;
    return out;
}

/* -- Camera Tick Thread ------------------------------------------ */

static volatile LONG cs_tick_running = 0;
static HANDLE cs_tick_handle = NULL;

static DWORD WINAPI cs_camera_tick(LPVOID)
{
    LARGE_INTEGER freq, last, now;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&last);

    BRIDGE_LOG("Camera tick thread started (1000 Hz)");

    while (InterlockedCompareExchange(&cs_tick_running, 1, 1) == 1) {
        QueryPerformanceCounter(&now);
        float dt = (float)(now.QuadPart - last.QuadPart) / (float)freq.QuadPart;
        last = now;

        /* Serialize every pov_ptr access against __cam_mem_find's scan.
         * If the scan is in progress, skip this tick (scan holds the
         * lock for the full clear+scan+set sequence, so retrying next
         * tick gives the scan a chance to finish). */
        std::unique_lock<std::mutex> pov_lk(g_cam_pov_mutex, std::try_to_lock);
        if (!pov_lk.owns_lock()) {
            Sleep(1);
            continue;
        }

        if (g_camera_path.is_playing()) {
            InterpolatedCamera cam = {};
            bool still = g_camera_path.tick(dt, cam);
            cam = cs_apply_smoothing(cam);
            /* Primary: write directly to FMinimalViewInfo if available.
             * This is what UUU does: background-thread POV override.
             * No race with UpdateCamera because we write AFTER it. */
            if (g_cam_pov_ptr) {
                CameraMemState snap;
                {
                    std::lock_guard<std::mutex> lk(g_cam_override_mutex);
                    g_cam_override_state.x     = cam.pos.x;
                    g_cam_override_state.y     = cam.pos.y;
                    g_cam_override_state.z     = cam.pos.z;
                    g_cam_override_state.pitch = cam.pitch;
                    g_cam_override_state.yaw   = cam.yaw;
                    g_cam_override_state.roll  = cam.roll;
                    if (cam.fov > 0.0f) g_cam_override_state.fov = cam.fov;
                    snap = g_cam_override_state;
                }
                write_camera_mem(snap);
            } else {
                /* Fallback: console commands (requires DebugCamera active) */
                set_camera_location(cam.pos.x, cam.pos.y, cam.pos.z);
                set_camera_rotation(cam.pitch, cam.yaw, cam.roll);
                if (cam.fov > 0.0f && cam.fov != g_camera.fov)
                    set_fov(cam.fov);
            }
            if (!still)
                BRIDGE_LOG("Camera path playback ended");
        }

        /* Direct memory camera override: fight game's per-frame camera
         * update by re-writing FMinimalViewInfo every tick.
         * g_camera_override is set by __cam_mem_write / __cam_mem_on.
         * No game-thread requirement: plain memory write, no FExec. */
        if (g_camera_override.load() && g_cam_pov_ptr) {
            CameraMemState snap;
            {
                std::lock_guard<std::mutex> lk(g_cam_override_mutex);
                snap = g_cam_override_state;
            }
            write_camera_mem(snap);
        }

        pov_lk.unlock();
        Sleep(1);   /* ~1000 Hz -- outpaces UpdateCamera (once per frame ~60 Hz) */
    }
    BRIDGE_LOG("Camera tick thread stopped");
    return 0;
}

/* -- TCP helpers ------------------------------------------------- */

static void cs_reply(SOCKET sock, const char* msg) {
    send(sock, msg, (int)strlen(msg), 0);
}
static void cs_reply(SOCKET sock, const std::string& msg) {
    send(sock, msg.c_str(), (int)msg.size(), 0);
}

/* Locale-independent ASCII float parser.
 *
 * strtof/strtod honor LC_NUMERIC -- under German/Russian/French locale
 * the decimal separator is ',' and "10.5" parses as 10 with '.5' as the
 * unconsumed tail. UE5's own initialization has been observed to flip
 * the CRT locale, so we cannot rely on the process-wide value either.
 *
 * This parser only recognizes `.`, never `,`. Accepts optional sign,
 * integer digits, optional fraction, optional 'e'/'E' exponent.
 * Does NOT accept NaN/Inf tokens -- callers must still run values
 * through cs_sanitize_float() for that.
 *
 * Returns 0.0f and leaves *end == s when no digits are parsed.
 */
static float ascii_strtof(const char* s, const char** end = nullptr)
{
    const char* p = s;
    while (*p == ' ' || *p == '\t') p++;
    bool neg = false;
    if (*p == '+') { p++; }
    else if (*p == '-') { neg = true; p++; }
    double val = 0.0;
    bool any = false;
    while (*p >= '0' && *p <= '9') {
        val = val * 10.0 + (double)(*p - '0');
        p++; any = true;
    }
    if (*p == '.') {
        p++;
        double f = 0.1;
        while (*p >= '0' && *p <= '9') {
            val += (double)(*p - '0') * f;
            f *= 0.1;
            p++; any = true;
        }
    }
    if (!any) {
        if (end) *end = s;
        return 0.0f;
    }
    if (*p == 'e' || *p == 'E') {
        p++;
        bool neg_exp = false;
        if (*p == '+') p++;
        else if (*p == '-') { neg_exp = true; p++; }
        int exp = 0;
        while (*p >= '0' && *p <= '9') {
            exp = exp * 10 + (*p - '0');
            p++;
        }
        double mult = 1.0;
        for (int i = 0; i < exp; i++) mult *= 10.0;
        if (neg_exp) val /= mult;
        else        val *= mult;
    }
    if (neg) val = -val;
    if (end) *end = p;
    return (float)val;
}

/* double variant -- bit-exact for LWC coords up to 1e7 cm. */
static double ascii_strtod(const char* s, const char** end = nullptr)
{
    const char* p = s;
    while (*p == ' ' || *p == '\t') p++;
    bool neg = false;
    if (*p == '+') { p++; }
    else if (*p == '-') { neg = true; p++; }
    double val = 0.0;
    bool any = false;
    while (*p >= '0' && *p <= '9') {
        val = val * 10.0 + (double)(*p - '0');
        p++; any = true;
    }
    if (*p == '.') {
        p++;
        double f = 0.1;
        while (*p >= '0' && *p <= '9') {
            val += (double)(*p - '0') * f;
            f *= 0.1;
            p++; any = true;
        }
    }
    if (!any) {
        if (end) *end = s;
        return 0.0;
    }
    if (*p == 'e' || *p == 'E') {
        p++;
        bool neg_exp = false;
        if (*p == '+') p++;
        else if (*p == '-') { neg_exp = true; p++; }
        int exp = 0;
        while (*p >= '0' && *p <= '9') {
            exp = exp * 10 + (*p - '0');
            p++;
        }
        double mult = 1.0;
        for (int i = 0; i < exp; i++) mult *= 10.0;
        if (neg_exp) val /= mult;
        else        val *= mult;
    }
    if (neg) val = -val;
    if (end) *end = p;
    return val;
}

/* Sanitize a user-supplied float. Rejects NaN, infinities, and values
 * outside [lo, hi]. strtof happily returns INF for "1e40" and NaN for
 * "nan"; feeding those into slomo / path_play / smooth_factor would
 * propagate NaN into camera math (catmull_rom, SLERP) and blank the
 * camera. Returns fallback when input is out of range. */
static float cs_sanitize_float(float v, float lo, float hi, float fallback)
{
    if (!std::isfinite(v)) return fallback;
    if (v < lo || v > hi) return fallback;
    return v;
}

static int cs_parse_floats(const char* str, float* out, int max_count) {
    int count = 0;
    const char* p = str;
    while (count < max_count && *p) {
        while (*p == ' ' || *p == ',') p++;
        if (!*p) break;
        const char* end = NULL;
        float v = ascii_strtof(p, &end);
        if (end == p) break;
        out[count++] = v;
        p = end;
    }
    return count;
}

/* -- Command Router ---------------------------------------------- */

static bool cs_route_command(SOCKET client, const std::string& cmd)
{
    /* Log every command except high-frequency polling */
    if (cmd != "__bridge_ping" && cmd != "__bridge_status")
        BRIDGE_LOG("CMD>> %s", cmd.c_str());

    if (cmd == "__bridge_ping") { cs_reply(client, "pong\n"); return true; }

    if (cmd == "__bridge_status") {
        char buf[896];
        snprintf(buf, sizeof(buf),
            "engine_found=%d engine_ptr=0x%p "
            "fexec_exec=0x%p fexec_offset=%d "
            "fexec_hooks=%d "
            "guobjectarray_found=%d guobjectarray=0x%p "
            "world_ptr=0x%p localplayer_ptr=0x%p "
            "camera_manager_ptr=0x%p cam_pov_ptr=0x%p "
            "uworld_found=%d localplayer_found=%d "
            "camera_manager_found=%d cam_pov_found=%d "
            "cam_override=%d "
            "paused=%d hud=%d "
            "path_keyframes=%zu path_playing=%d "
            "smooth_factor=%.1f embedded=1 "
            "gengine_global=0x%llX "
            "gamethread_dispatch=%d "
            "intercept_sites=%zu intercept_nopped=%d\n",
            (int)g_engine_found.load(), g_engine_ptr,
            (void*)g_fexec_exec, (int)g_fexec_offset,
            (int)g_fexec_hook_count.load(),
            (int)g_guobjectarray_found.load(), g_guobjectarray,
            g_world_ptr, g_localplayer_ptr,
            g_camera_manager_ptr, g_cam_pov_ptr,
            g_world_ptr ? 1 : 0, g_localplayer_ptr ? 1 : 0,
            g_camera_manager_ptr ? 1 : 0, g_cam_pov_ptr ? 1 : 0,
            (int)g_camera_override.load(),
            (int)g_paused.load(),
            (int)g_hud_visible,
            g_camera_path.count(), (int)g_camera_path.is_active(),
            cs_smooth_factor.load(),
            (unsigned long long)g_engine_global_addr,
            (int)g_gamethread_dispatch_ready.load(),
            cam_intercept_count(),
            (int)cam_intercept_any_nopped());
        cs_reply(client, buf);
        return true;
    }

    if (cmd.rfind("__bridge_set_offset ", 0) == 0) {
        uintptr_t offset = strtoull(cmd.c_str() + 20, NULL, 16);
        cs_reply(client, find_gengine_via_offset(offset) ? "ok\n" : "null\n");
        return true;
    }

    if (cmd == "__bridge_rescan") {
        g_engine_found = false; g_engine_ptr = NULL;
        g_fexec_exec = NULL; g_fexec_offset = 0;
        cs_reply(client, find_gengine() ? "ok\n" : "not_found\n");
        return true;
    }

    /* Toggle __debugbreak() arm state.
     * When armed, the next UWorld/LocalPlayer discovery fires INT3.
     * Attach WinDbg/x64dbg to the game process BEFORE arming, then
     * trigger a re-scan from the UI to catch the exact discovery moment.
     * One-shot: auto-disarms after first break. */
    if (cmd == "__bridge_arm_break") {
        bool was = g_debug_break_armed.load();
        g_debug_break_armed = !was;
        bool now = g_debug_break_armed.load();
        BRIDGE_LOG("Debug break: %s", now ? "ARMED (fire on next UWorld/LP find)" : "disarmed");
        cs_reply(client, now ? "armed\n" : "disarmed\n");
        return true;
    }

    /* Re-scan UWorld + ULocalPlayer via GUObjectArray + FName comparison.
     * Call this after map load completes to refresh stale pointers.
     * Clears existing pointers before scanning so stale map references
     * are not kept if the new scan fails. */
    if (cmd == "__bridge_rescan_objects") {
        g_world_ptr = nullptr;
        g_world_from_gua = false;
        g_localplayer_ptr = nullptr;
        g_camera_manager_ptr = nullptr;
        g_cam_pov_ptr = nullptr;
        find_uworld_via_guobjectarray();
        find_localplayer();
        find_camera_manager();   /* Path A: GUObjectArray FName scan */
        cross_validate_camera(); /* Paths B+C: LP chain + render viewport */
        find_cam_pov();
        char rbuf[448];
        snprintf(rbuf, sizeof(rbuf),
                 "uworld_found=%d localplayer_found=%d "
                 "camera_manager_found=%d cam_pov_found=%d "
                 "world_ptr=0x%p localplayer_ptr=0x%p "
                 "camera_manager_ptr=0x%p cam_pov_ptr=0x%p\n",
                 g_world_ptr ? 1 : 0, g_localplayer_ptr ? 1 : 0,
                 g_camera_manager_ptr ? 1 : 0, g_cam_pov_ptr ? 1 : 0,
                 g_world_ptr, g_localplayer_ptr,
                 g_camera_manager_ptr, g_cam_pov_ptr);
        cs_reply(client, rbuf);
        return true;
    }

    /* Commands below require GEngine -- return error if not ready */
    if (!g_engine_found) {
        if (cmd == "__cam_pause" ||
            cmd == "__timestop" || cmd.rfind("__cam_speed ",0)==0 ||
            cmd == "__hud_toggle" || cmd.rfind("__hotsample ",0)==0) {
            cs_reply(client, "error: engine_not_ready\n");
            return false;
        }
    }

    if (cmd == "__bridge_test") {
        BRIDGE_LOG("=== VISUAL TEST ===");
        /* These commands produce obvious visual effects: */
        exec_console_command("slomo 0.1");        /* extreme slow-mo */
        Sleep(3000);                               /* hold 3 seconds */
        exec_console_command("slomo 1");           /* restore */
        exec_console_command("stat fps");          /* show FPS counter */
        cs_reply(client, "test_done\n");
        return true;
    }

    /* ---- Direct camera memory commands (no FExec, no game thread) ---- */

    /* Find FMinimalViewInfo pointer on demand (e.g. after map load) */
    if (cmd == "__cam_mem_find") {
        BRIDGE_LOG("=== __cam_mem_find: starting full camera scan ===");
        BRIDGE_LOG("  LP=0x%p  World=0x%p  GEngine=0x%p",
                   g_localplayer_ptr, g_world_ptr, g_engine_ptr);
        bool ok;
        {
            /* Hold g_cam_pov_mutex for the whole clear+scan+set so no
             * tick iteration can observe a cleared pointer between
             * `g_cam_pov_ptr = nullptr` and `find_cam_pov()`. Tick
             * thread's try_lock lets it skip ticks during the scan. */
            std::lock_guard<std::mutex> lk(g_cam_pov_mutex);
            g_cam_pov_ptr = nullptr;          /* force re-scan */
            g_camera_manager_ptr = nullptr;   /* re-run all paths */
            find_camera_manager();            /* Path A: FName scan */
            cross_validate_camera();          /* Paths B+C+D: LP chain + render + UUU probe */
            ok = find_cam_pov();
        }
        BRIDGE_LOG("=== __cam_mem_find done: mgr=0x%p pov=0x%p ok=%d ===",
                   g_camera_manager_ptr, g_cam_pov_ptr, (int)ok);
        char buf[128];
        if (ok)
            snprintf(buf, sizeof(buf), "ok pov=0x%p\n", g_cam_pov_ptr);
        else
            snprintf(buf, sizeof(buf), "not_found camera_mgr=0x%p\n",
                     g_camera_manager_ptr);
        cs_reply(client, buf);
        return true;
    }

    /* Read current camera state from FMinimalViewInfo */
    if (cmd == "__cam_mem_read") {
        if (!g_cam_pov_ptr && !find_cam_pov()) {
            cs_reply(client, "error: pov_not_found\n");
            return true;
        }
        CameraMemState st;
        if (read_camera_mem(st)) {
            BRIDGE_LOG("  cam_read: xyz=(%.1f,%.1f,%.1f) pyr=(%.2f,%.2f,%.2f) fov=%.1f",
                       st.x, st.y, st.z, st.pitch, st.yaw, st.roll, st.fov);
            char buf[192];
            snprintf(buf, sizeof(buf),
                     "x=%.4f y=%.4f z=%.4f "
                     "pitch=%.4f yaw=%.4f roll=%.4f "
                     "fov=%.4f\n",
                     st.x, st.y, st.z,
                     st.pitch, st.yaw, st.roll, st.fov);
            cs_reply(client, buf);
        } else {
            cs_reply(client, "error: read_failed\n");
        }
        return true;
    }

    /* Write camera state directly to FMinimalViewInfo.
     * Format: __cam_mem_write X Y Z Pitch Yaw Roll FOV
     * Enables override (game writes fought by tick thread at 60 Hz). */
    if (cmd.rfind("__cam_mem_write ", 0) == 0) {
        if (!g_cam_pov_ptr && !find_cam_pov()) {
            cs_reply(client, "error: pov_not_found\n");
            return true;
        }
        float vals[7] = {0,0,0, 0,0,0, 90.0f};
        int n = 0;
        const char* p = cmd.c_str() + 16;
        while (n < 7 && *p) {
            while (*p == ' ' || *p == ',') p++;
            if (!*p) break;
            const char* end = nullptr;
            vals[n++] = ascii_strtof(p, &end);
            if (end == p) break;
            p = end;
        }
        if (n < 6) {
            cs_reply(client, "error: usage __cam_mem_write X Y Z P Y R [FOV]\n");
            return true;
        }
        /* Reject NaN/Inf from strtof before they poison the camera. */
        for (int vi = 0; vi < 3; vi++)
            vals[vi] = cs_sanitize_float(vals[vi], -1e8f, 1e8f, 0.0f);
        for (int vi = 3; vi < 6; vi++)
            vals[vi] = cs_sanitize_float(vals[vi], -360.0f, 360.0f, 0.0f);
        if (n >= 7)
            vals[6] = cs_sanitize_float(vals[6], 1.0f, 179.0f, 90.0f);
        CameraMemState st;
        st.x = vals[0]; st.y = vals[1]; st.z = vals[2];
        st.pitch = vals[3]; st.yaw = vals[4]; st.roll = vals[5];
        {
            std::lock_guard<std::mutex> lk(g_cam_override_mutex);
            st.fov = (n >= 7) ? vals[6] : g_cam_override_state.fov;
            g_cam_override_state = st;
        }
        g_camera_override = true;
        bool ok = write_camera_mem(st);
        BRIDGE_LOG("  cam_write: xyz=(%.1f,%.1f,%.1f) pyr=(%.2f,%.2f,%.2f) fov=%.1f -> %s",
                   st.x, st.y, st.z, st.pitch, st.yaw, st.roll, st.fov,
                   ok ? "ok" : "FAILED");
        cs_reply(client, ok ? "ok\n" : "error: write_failed\n");
        return true;
    }

    /* Enable/disable per-tick camera override */
    if (cmd == "__cam_mem_on") {
        if (!g_cam_pov_ptr && !find_cam_pov()) {
            cs_reply(client, "error: pov_not_found\n");
            return true;
        }
        g_camera_override = true;
        cs_reply(client, "ok override=on\n");
        return true;
    }

    if (cmd == "__cam_mem_off") {
        g_camera_override = false;
        cs_reply(client, "ok override=off\n");
        return true;
    }

    /* ---- IGCS-style code-patch intercept ----
     * Patches the game's own MOV instruction(s) that write POV so that
     * UpdateCamera stops fighting our external writes. Two states per
     * site: "pass" (original bytes) and "nop" (blocked).
     *
     *   __cam_intercept_install_addr <hex_addr> <size> [name]
     *       Install at an absolute address (for testing).
     *   __cam_intercept_install_aob <size> <name> | <AOB>
     *       Install at first AOB match in main module. Name is required
     *       to separate args from the AOB hex (which contains spaces).
     *       The literal '|' separates size/name from the AOB tokens.
     *   __cam_intercept_nop      -- switch all sites to nop (override).
     *   __cam_intercept_pass     -- switch all sites to original.
     *   __cam_intercept_list     -- dump installed sites.
     *   __cam_intercept_uninstall -- restore bytes + clear list.
     */
    if (cmd.rfind("__cam_intercept_install_addr ", 0) == 0) {
        const char* p = cmd.c_str() + 29;
        char* end = NULL;
        uintptr_t addr = strtoull(p, &end, 16);
        if (end == p || addr == 0) {
            cs_reply(client, "error: usage __cam_intercept_install_addr <hex_addr> <size> [name]\n");
            return true;
        }
        p = end;
        while (*p == ' ') p++;
        long size = strtol(p, &end, 10);
        if (end == p || size <= 0 || size > 64) {
            cs_reply(client, "error: size must be 1..64\n");
            return true;
        }
        p = end;
        while (*p == ' ') p++;
        const char* name = *p ? p : "manual";
        bool ok = cam_intercept_install_addr((uint8_t*)addr, (size_t)size, name);
        cs_reply(client, ok ? "ok\n" : "error: install failed\n");
        return true;
    }

    if (cmd.rfind("__cam_intercept_install_aob ", 0) == 0) {
        /* format: __cam_intercept_install_aob <size> <occurrence> <name> | <AOB hex>
         * occurrence >= 1; 1 = first match (default). */
        const char* p = cmd.c_str() + 28;
        char* end = NULL;
        long size = strtol(p, &end, 10);
        if (end == p || size <= 0 || size > 64) {
            cs_reply(client, "error: usage __cam_intercept_install_aob <size> <occurrence> <name> | <AOB>\n");
            return true;
        }
        p = end;
        while (*p == ' ') p++;
        long occurrence = strtol(p, &end, 10);
        if (end == p || occurrence < 1) {
            cs_reply(client, "error: missing occurrence (>= 1) after size\n");
            return true;
        }
        p = end;
        while (*p == ' ') p++;
        const char* name_start = p;
        const char* bar = strchr(p, '|');
        if (!bar) {
            cs_reply(client, "error: missing '|' separator before AOB\n");
            return true;
        }
        std::string name(name_start, bar - name_start);
        while (!name.empty() && name.back() == ' ') name.pop_back();
        const char* aob = bar + 1;
        while (*aob == ' ') aob++;
        /* Parse AOB and try scan before calling install so we can give a
         * specific error (pattern_not_found vs other install failure). */
        {
            uint8_t pat_bytes[128]; char pat_mask[129];
            int pat_len = cam_parse_aob(aob, pat_bytes, pat_mask, 128);
            if (pat_len <= 0) {
                cs_reply(client, "error: malformed_aob\n");
                return true;
            }
            const uint8_t* match = scan_main_module_nth(
                pat_bytes, pat_mask, (size_t)pat_len, (int)occurrence);
            if (!match) {
                char buf[96];
                snprintf(buf, sizeof(buf),
                         "error: pattern_not_found tokens=%d occ=%ld\n",
                         pat_len, occurrence);
                cs_reply(client, buf);
                return true;
            }
        }
        bool ok = cam_intercept_install_aob(aob, (size_t)size,
                                             name.empty() ? "aob" : name.c_str(),
                                             (int)occurrence);
        cs_reply(client, ok ? "ok\n" : "error: install failed (see log)\n");
        return true;
    }

    if (cmd == "__cam_intercept_nop") {
        bool ok = cam_intercept_set_nop_all(true);
        char buf[64];
        snprintf(buf, sizeof(buf), "%s sites=%zu\n",
                 ok ? "ok" : "partial_failure", cam_intercept_count());
        cs_reply(client, buf);
        return true;
    }

    if (cmd == "__cam_intercept_pass") {
        bool ok = cam_intercept_set_nop_all(false);
        char buf[64];
        snprintf(buf, sizeof(buf), "%s sites=%zu\n",
                 ok ? "ok" : "partial_failure", cam_intercept_count());
        cs_reply(client, buf);
        return true;
    }

    if (cmd == "__cam_intercept_list") {
        cs_reply(client, cam_intercept_list());
        return true;
    }

    if (cmd == "__cam_intercept_uninstall") {
        cam_intercept_uninstall_all();
        cs_reply(client, "ok\n");
        return true;
    }

    /* Switch all sites to CAPTURE mode (NOP + snapshot base-register). */
    if (cmd == "__cam_intercept_capture") {
        bool ok = cam_intercept_set_mode_all(CAM_MODE_CAPTURE);
        char buf[128];
        snprintf(buf, sizeof(buf), "%s sites=%zu\n",
                 ok ? "ok" : "partial_failure", cam_intercept_count());
        cs_reply(client, buf);
        return true;
    }

    /* Read captured address at a slot. Returns "addr=0x..." or "null". */
    if (cmd.rfind("__cam_intercept_get_capture ", 0) == 0) {
        char* end = NULL;
        long slot = strtol(cmd.c_str() + 28, &end, 10);
        if (end == cmd.c_str() + 28 || slot < 0 || slot >= 16) {
            cs_reply(client, "error: usage __cam_intercept_get_capture <slot:0-15>\n");
            return true;
        }
        uint64_t cap = cam_intercept_get_captured((int)slot);
        char buf[64];
        if (cap == 0) snprintf(buf, sizeof(buf), "null slot=%ld\n", slot);
        else          snprintf(buf, sizeof(buf), "addr=0x%llX slot=%ld\n",
                               (unsigned long long)cap, slot);
        cs_reply(client, buf);
        return true;
    }

    /* Write a typed value into the camera struct.
     * Format: __cam_mem_poke <addr_hex> <offset_hex_or_dec> <type> <value>
     * Types:  f32, f64, i32, u32
     */
    if (cmd.rfind("__cam_mem_poke ", 0) == 0) {
        const char* p = cmd.c_str() + 15;
        char* end = NULL;
        uint64_t addr = strtoull(p, &end, 16);
        if (end == p || addr == 0) { cs_reply(client, "error: bad addr\n"); return true; }
        p = end;
        while (*p == ' ') p++;
        /* offset: accept 0x prefix or decimal */
        uint64_t off = 0;
        if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
            off = strtoull(p + 2, &end, 16);
        } else {
            off = strtoull(p, &end, 10);
        }
        if (end == p) { cs_reply(client, "error: bad offset\n"); return true; }
        p = end;
        while (*p == ' ') p++;
        /* type token */
        char tbuf[8] = {0};
        int ti = 0;
        while (*p && *p != ' ' && ti < 7) { tbuf[ti++] = *p++; }
        while (*p == ' ') p++;
        int type = -1;
        if (strcmp(tbuf, "f32") == 0) type = 0;
        else if (strcmp(tbuf, "f64") == 0) type = 1;
        else if (strcmp(tbuf, "i32") == 0) type = 2;
        else if (strcmp(tbuf, "u32") == 0) type = 3;
        if (type < 0) { cs_reply(client, "error: type must be f32|f64|i32|u32\n"); return true; }
        /* value */
        uint64_t bits = 0;
        if (type == 0) {
            const char* fe = p;
            float f = ascii_strtof(p, &fe);
            end = (char*)fe;
            uint32_t u = 0; memcpy(&u, &f, 4);
            bits = u;
        } else if (type == 1) {
            const char* de = p;
            double d = ascii_strtod(p, &de);
            end = (char*)de;
            memcpy(&bits, &d, 8);
        } else if (type == 2) {
            long v = strtol(p, &end, 10);
            bits = (uint32_t)(int32_t)v;
        } else {
            unsigned long v = strtoul(p, &end, 10);
            bits = (uint32_t)v;
        }
        if (end == p) { cs_reply(client, "error: bad value\n"); return true; }
        bool ok = cam_mem_poke(addr, off, type, bits);
        cs_reply(client, ok ? "ok\n" : "error: poke faulted\n");
        return true;
    }

    /* Read a typed value from a raw address.
     * Format: __cam_mem_peek <addr_hex> <offset_hex_or_dec> <type>
     * Returns: value=<number>
     */
    if (cmd.rfind("__cam_mem_peek ", 0) == 0) {
        const char* p = cmd.c_str() + 15;
        char* end = NULL;
        uint64_t addr = strtoull(p, &end, 16);
        if (end == p || addr == 0) { cs_reply(client, "error: bad addr\n"); return true; }
        p = end;
        while (*p == ' ') p++;
        uint64_t off = 0;
        if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
            off = strtoull(p + 2, &end, 16);
        } else {
            off = strtoull(p, &end, 10);
        }
        if (end == p) { cs_reply(client, "error: bad offset\n"); return true; }
        p = end;
        while (*p == ' ') p++;
        char tbuf[8] = {0};
        int ti = 0;
        while (*p && *p != ' ' && ti < 7) { tbuf[ti++] = *p++; }
        int type = -1;
        if (strcmp(tbuf, "f32") == 0) type = 0;
        else if (strcmp(tbuf, "f64") == 0) type = 1;
        else if (strcmp(tbuf, "i32") == 0) type = 2;
        else if (strcmp(tbuf, "u32") == 0) type = 3;
        if (type < 0) { cs_reply(client, "error: type must be f32|f64|i32|u32\n"); return true; }
        uint64_t bits = 0;
        if (!cam_mem_peek(addr, off, type, &bits)) {
            cs_reply(client, "error: peek faulted\n");
            return true;
        }
        char buf[64];
        if (type == 0) {
            float f; memcpy(&f, &bits, 4);
            snprintf(buf, sizeof(buf), "value=%.6g\n", (double)f);
        } else if (type == 1) {
            double d; memcpy(&d, &bits, 8);
            snprintf(buf, sizeof(buf), "value=%.6g\n", d);
        } else {
            snprintf(buf, sizeof(buf), "value=%d\n", (int32_t)(uint32_t)bits);
        }
        cs_reply(client, buf);
        return true;
    }

    if (cmd == "__cam_pause" || cmd == "__timestop") {
        toggle_pause();
        char buf[64];
        snprintf(buf, sizeof(buf), "paused=%d speed=%.4f\n", (int)g_paused.load(), g_game_speed);
        cs_reply(client, buf);
        return true;
    }

    if (cmd.rfind("__cam_speed ", 0) == 0) {
        float sp = cs_sanitize_float(ascii_strtof(cmd.c_str() + 12, NULL),
                                     0.0f, 1e6f, 1.0f);
        set_game_speed(sp);
        cs_reply(client, "ok\n");
        return true;
    }

    if (cmd == "__hud_toggle") { toggle_hud(); cs_reply(client, "ok\n"); return true; }

    if (cmd.rfind("__hotsample ", 0) == 0) {
        int w = 0, h = 0;
        sscanf(cmd.c_str() + 12, "%d %d", &w, &h);
        if (w > 0 && h > 0) { hotsample(w, h); cs_reply(client, "ok\n"); }
        else cs_reply(client, "error: usage __hotsample W H\n");
        return true;
    }

    if (cmd.rfind("__smooth ", 0) == 0) {
        float v = cs_sanitize_float(
            ascii_strtof(cmd.c_str() + 9, NULL), 1.0f, 1000.0f, 1.0f);
        cs_smooth_factor.store(v, std::memory_order_relaxed);
        cs_smooth_initialized.store(false);
        char buf[64]; snprintf(buf, sizeof(buf), "smooth_factor=%.1f\n", v);
        cs_reply(client, buf);
        return true;
    }

    /* Camera path commands */
    if (cmd == "__path_add") {
        CameraKeyframe kf;
        kf.pos.x = g_camera.x; kf.pos.y = g_camera.y; kf.pos.z = g_camera.z;
        kf.pitch = g_camera.pitch; kf.yaw = g_camera.yaw; kf.roll = g_camera.roll;
        kf.fov = g_camera.fov; kf.duration = 2.0f;
        g_camera_path.add_keyframe(kf);
        cs_reply(client, "ok\n");
        return true;
    }

    if (cmd.rfind("__path_add ", 0) == 0) {
        float vals[8] = {0,0,0,0,0,0,90.0f,2.0f};
        int n = cs_parse_floats(cmd.c_str() + 11, vals, 8);
        if (n >= 6) {
            CameraKeyframe kf;
            kf.pos.x = vals[0]; kf.pos.y = vals[1]; kf.pos.z = vals[2];
            kf.pitch = vals[3]; kf.yaw = vals[4]; kf.roll = vals[5];
            kf.fov = (n>=7)?vals[6]:90.0f; kf.duration = (n>=8)?vals[7]:2.0f;
            g_camera_path.add_keyframe(kf);
            cs_reply(client, "ok\n");
        } else cs_reply(client, "error: need 6+ values\n");
        return true;
    }

    if (cmd == "__path_clear") { g_camera_path.clear(); cs_reply(client, "ok\n"); return true; }
    if (cmd.rfind("__path_delete ",0)==0) {
        /* strtol + bounds: atoi silently overflows on "2147483648" and
         * returns a negative that cast to size_t becomes astronomical. */
        char* end = NULL;
        long val = strtol(cmd.c_str()+14, &end, 10);
        if (end == cmd.c_str()+14 || val < 0 || val > 10000) {
            cs_reply(client, "error: bad index\n");
            return true;
        }
        cs_reply(client, g_camera_path.delete_keyframe((size_t)val) ? "ok\n":"error\n");
        return true;
    }
    if (cmd == "__path_list") { cs_reply(client, g_camera_path.list_keyframes()); return true; }
    if (cmd == "__path_play" || cmd.rfind("__path_play ",0)==0) {
        float raw = cmd.size()>12 ? ascii_strtof(cmd.c_str()+12,NULL) : 1.0f;
        float spd = cs_sanitize_float(raw, 0.0001f, 1e6f, 1.0f);
        if (spd <= 0) spd = 1.0f;
        g_camera_path.play(spd); cs_reply(client, "ok\n");
        return true;
    }
    if (cmd == "__path_stop") { g_camera_path.stop(); cs_reply(client, "ok\n"); return true; }
    if (cmd == "__path_pause") { g_camera_path.toggle_pause(); cs_reply(client, "ok\n"); return true; }
    if (cmd.rfind("__path_loop ",0)==0) {
        bool l = cmd[12]=='1'; g_camera_path.set_loop(l);
        cs_reply(client, l?"loop=on\n":"loop=off\n"); return true;
    }
    if (cmd == "__path_visualize") {
        std::vector<InterpolatedCamera> pts = g_camera_path.visualize(20);
        std::string r; char buf[128];
        for (size_t i = 0; i < pts.size(); i++) {
            const InterpolatedCamera& p = pts[i];
            snprintf(buf,sizeof(buf),"%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f\n",
                p.pos.x,p.pos.y,p.pos.z,p.pitch,p.yaw,p.roll,p.fov);
            r += buf;
        }
        cs_reply(client, r.empty() ? "(no path)\n" : r); return true;
    }
    if (cmd == "__path_info") {
        char buf[256];
        snprintf(buf,sizeof(buf),"keyframes=%zu total_duration=%.2fs playing=%d\n",
            g_camera_path.count(), g_camera_path.total_duration(),
            (int)g_camera_path.is_active());
        cs_reply(client, buf); return true;
    }

    /* Trigger a RenderDoc frame capture at next frame presentation.
     * The bridge runs inside renderdoc.dll so RenderDoc::Inst() is valid. */
    if (cmd == "__cam_rdc_capture") {
        RenderDoc::Inst().TriggerCapture(1);
        cs_reply(client, "ok\n");
        return true;
    }

    /* Regular UE5 console command (pass-through) */
    if (cmd.rfind("__",0) != 0) {
        if (!g_engine_found) {
            cs_reply(client, "error: engine_not_ready\n");
            return false;
        }
        exec_console_command(cmd.c_str());
        return true;
    }

    BRIDGE_LOG("Unknown command: %s", cmd.c_str());
    cs_reply(client, "error: unknown command\n");
    return false;
}

/* -- TCP Server -------------------------------------------------- */

static volatile LONG cs_server_running = 0;
static SOCKET cs_listen_socket = INVALID_SOCKET;

/* Client thread tracking. We record the socket alongside the thread
 * handle so shutdown can force recv() to return before WaitForSingleObject;
 * otherwise a client blocked in recv with no pending data holds the
 * thread open past the wait timeout, leaking both handle and socket. */
struct ClientSlot { HANDLE thread; SOCKET sock; };
static ClientSlot cs_client_slots[32];
static int cs_client_count = 0;
static CRITICAL_SECTION cs_client_cs;

struct ClientArg { SOCKET sock; };

static DWORD WINAPI cs_handle_client_thread(LPVOID arg)
{
    ClientArg* ca = (ClientArg*)arg;
    SOCKET client = ca->sock;
    delete ca;

    BRIDGE_LOG("Client connected");
    char buffer[CONSOLE_MAX_CMD_LEN];
    std::string line_buf;
    /* Upper bound on pending line bytes. A single unterminated command
     * spamming us without a newline would otherwise grow the string to OOM
     * and kill the game process. 1 MB is ~256x the largest legitimate
     * command. */
    const size_t LINE_BUF_MAX = 1024 * 1024;

    while (InterlockedCompareExchange(&cs_server_running, 1, 1) == 1) {
        int n = recv(client, buffer, sizeof(buffer)-1, 0);
        if (n == 0) {
            BRIDGE_LOG("Client closed connection");
            break;
        }
        if (n < 0) {
            int err = WSAGetLastError();
            if (err != WSAECONNRESET && err != WSAEINTR)
                BRIDGE_LOG("recv error: %d", err);
            break;
        }
        if (line_buf.size() + (size_t)n > LINE_BUF_MAX) {
            BRIDGE_LOG("Client exceeded %zu-byte line buffer -- disconnecting",
                       LINE_BUF_MAX);
            break;
        }
        line_buf.append(buffer, (size_t)n);

        size_t pos;
        while ((pos = line_buf.find('\n')) != std::string::npos) {
            std::string cmd = line_buf.substr(0, pos);
            line_buf.erase(0, pos+1);
            if (!cmd.empty() && cmd.back()=='\r') cmd.pop_back();
            if (!cmd.empty()) cs_route_command(client, cmd);
        }
    }
    closesocket(client);

    /* Free this thread's slot so a reconnect can reuse it. Without this
     * step the slot stays occupied after every normal disconnect and the
     * next accept eventually hits the 32-slot cap even though no clients
     * are actually attached. */
    EnterCriticalSection(&cs_client_cs);
    for (int i = 0; i < cs_client_count; i++) {
        if (cs_client_slots[i].sock == client) {
            cs_client_slots[i].sock = INVALID_SOCKET;
            if (cs_client_slots[i].thread) {
                CloseHandle(cs_client_slots[i].thread);
                cs_client_slots[i].thread = NULL;
            }
            break;
        }
    }
    /* Compact from the tail: drop trailing INVALID_SOCKET entries so
     * cs_client_count reflects live clients and the accept loop's
     * full-check stays accurate. */
    while (cs_client_count > 0 &&
           cs_client_slots[cs_client_count-1].sock == INVALID_SOCKET) {
        cs_client_count--;
    }
    LeaveCriticalSection(&cs_client_cs);

    BRIDGE_LOG("Client disconnected");
    return 0;
}

static void cs_server_main(int port)
{
    /* RenderDoc normally calls WSAStartup via Network::Init() before we
     * get here, but there is no happens-before guarantee. WSAStartup is
     * ref-counted and safe to call redundantly; pair with WSACleanup on
     * exit to balance the ref. */
    WSADATA wsa_data;
    bool wsa_started = (WSAStartup(MAKEWORD(2, 2), &wsa_data) == 0);
    if (!wsa_started) {
        BRIDGE_LOG("WSAStartup failed: %d", WSAGetLastError());
        return;
    }

    cs_listen_socket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (cs_listen_socket == INVALID_SOCKET) {
        BRIDGE_LOG("socket() failed: %d", WSAGetLastError());
        WSACleanup();
        return;
    }

    int opt = 1;
    setsockopt(cs_listen_socket, SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    addr.sin_port = htons((u_short)port);

    if (bind(cs_listen_socket, (struct sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) {
        BRIDGE_LOG("bind() port %d failed: %d", port, WSAGetLastError());
        closesocket(cs_listen_socket);
        cs_listen_socket = INVALID_SOCKET;
        WSACleanup();
        return;
    }

    if (listen(cs_listen_socket, 4) == SOCKET_ERROR) {
        BRIDGE_LOG("listen() failed: %d", WSAGetLastError());
        closesocket(cs_listen_socket);
        cs_listen_socket = INVALID_SOCKET;
        WSACleanup();
        return;
    }

    InterlockedExchange(&cs_server_running, 1);
    BRIDGE_LOG("Console server on 127.0.0.1:%d", port);

    while (InterlockedCompareExchange(&cs_server_running, 1, 1) == 1) {
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(cs_listen_socket, &fds);
        struct timeval tv;
        tv.tv_sec = 1;
        tv.tv_usec = 0;

        if (select(0, &fds, NULL, NULL, &tv) > 0) {
            SOCKET c = accept(cs_listen_socket, NULL, NULL);
            if (c != INVALID_SOCKET) {
                /* Reject BEFORE CreateThread when slots are full. Spawning a
                 * thread that is never tracked leads to a socket-value-reuse
                 * UAF: main thread closesocket(c) -> kernel reclaims value ->
                 * next accept() hands the same value to a new connection ->
                 * the rejected thread's closesocket() then kills a live one. */
                EnterCriticalSection(&cs_client_cs);
                bool full = (cs_client_count >= 32);
                LeaveCriticalSection(&cs_client_cs);
                if (full) {
                    BRIDGE_LOG("Client rejected: 32 slots full");
                    shutdown(c, SD_BOTH);
                    closesocket(c);
                    continue;
                }

                ClientArg* arg = new ClientArg;
                arg->sock = c;
                HANDLE h = CreateThread(NULL, 0, cs_handle_client_thread, arg, 0, NULL);
                if (h) {
                    /* Single-accept-thread model: cs_client_count is only
                     * mutated by this loop + ConsoleServer_Stop (after exit),
                     * so the full-check above stays valid here. */
                    EnterCriticalSection(&cs_client_cs);
                    cs_client_slots[cs_client_count].thread = h;
                    cs_client_slots[cs_client_count].sock = c;
                    cs_client_count++;
                    LeaveCriticalSection(&cs_client_cs);
                } else {
                    /* CreateThread failed -- thread never ran, so it can't
                     * free arg or close the socket. Clean up here. */
                    BRIDGE_LOG("CreateThread(client) failed: %lu", GetLastError());
                    delete arg;
                    shutdown(c, SD_BOTH);
                    closesocket(c);
                }
            }
        }
    }

    closesocket(cs_listen_socket);
    cs_listen_socket = INVALID_SOCKET;
    /* WSACleanup deferred to ConsoleServer_Stop() so that client
     * threads can still call closesocket() during their shutdown. */
    BRIDGE_LOG("Console server stopped");
}

/* -- Startup Thread ---------------------------------------------- */

static HANDLE cs_main_thread = NULL;
static HANDLE cs_engine_scan_handle = NULL;

/*
 * GEngine scan runs in its own thread so the TCP server can start
 * immediately. Commands that need GEngine will report "not available"
 * until the scan succeeds, but __bridge_ping / __bridge_status work
 * right away -- critical for the Python side's readiness detection.
 */
static DWORD WINAPI cs_engine_scan_thread(LPVOID)
{
    /* Poll module size until it stabilizes instead of a blind Sleep(5000).
     * Game module may still be loading sections when we start; scanning
     * partial code yields false negatives. We consider the module stable
     * when its reported size has not grown for 3 consecutive polls. */
    BRIDGE_LOG("Engine scan thread started, waiting for module to stabilize...");
    {
        size_t last_size = 0;
        int stable_count = 0;
        const int stable_target = 3;
        const int poll_ms = 500;
        const int max_wait_ms = 30000;
        int elapsed = 0;
        while (stable_count < stable_target && elapsed < max_wait_ms) {
            ModuleRegion mr;
            size_t cur = get_main_module(mr) ? mr.size : 0;
            if (cur > 0 && cur == last_size) stable_count++;
            else { stable_count = 0; last_size = cur; }
            Sleep(poll_ms);
            elapsed += poll_ms;
        }
        BRIDGE_LOG("Module stable at %zu bytes after %dms", last_size, elapsed);
    }

    /* === Gate 1: GUObjectArray (mandatory) ===
     * All object discovery goes through GUObjectArray.  No GUObjectArray = no
     * UWorld, no LocalPlayer, no commands.  Poll until found or timeout. */
    {
        const int poll_ms = 2000, gate_timeout_ms = 120000;
        int elapsed = 0;
        while (!find_guobjectarray() && elapsed < gate_timeout_ms) {
            Sleep(poll_ms);
            elapsed += poll_ms;
            if (elapsed % 10000 == 0)
                BRIDGE_LOG("Waiting for GUObjectArray... (%ds)", elapsed / 1000);
        }
        if (!g_guobjectarray_found) {
            BRIDGE_LOG("FATAL: GUObjectArray not found after %ds -- bridge disabled",
                       gate_timeout_ms / 1000);
            return 0;
        }
        BRIDGE_LOG("[1/7] GUObjectArray: 0x%p (%d objects)",
                   g_guobjectarray, guobjectarray_num_elements());
    }

    /* === Gate 2: FNamePool (mandatory) ===
     * All class/object identification uses FName ComparisonIndex comparison.
     * No FNamePool = can't identify UWorld, LocalPlayer, or any actor.
     * Must be found before proceeding to object scans. */
    {
        const int poll_ms = 1000, gate_timeout_ms = 60000;
        int elapsed = 0;
        while (!find_fnamepool_block0() && elapsed < gate_timeout_ms) {
            Sleep(poll_ms);
            elapsed += poll_ms;
            if (elapsed % 5000 == 0)
                BRIDGE_LOG("Waiting for FNamePool... (%ds)", elapsed / 1000);
        }
        if (!g_fnamepool_block0) {
            BRIDGE_LOG("FATAL: FNamePool not found after %ds -- bridge disabled",
                       gate_timeout_ms / 1000);
            return 0;
        }
        /* Read CurrentBlock for diagnostics */
        int32_t cur_blk = 0;
        if (g_fnamepool_global)
            __try { cur_blk = *(int32_t*)(g_fnamepool_global + 0x08); }
            __except(EXCEPTION_EXECUTE_HANDLER) { cur_blk = -1; }
        BRIDGE_LOG("[2/7] FNamePool: block0=0x%llX fmt=%s blocks=%d global=0x%llX",
                   (unsigned long long)g_fnamepool_block0,
                   g_fname_header_shift == 6 ? "UE5" : "UE4",
                   cur_blk,
                   (unsigned long long)g_fnamepool_global);
    }

    /* === Gate 3: GEngine (string xref, poll) ===
     * GEngine is the exception to the FNamePool rule -- it's located via
     * string cross-reference, NOT FNamePool.  All other objects use GUA+FName. */
    {
        const int poll_ms = 2000, gate_timeout_ms = 120000;
        int elapsed = 0;
        while (!find_gengine() && elapsed < gate_timeout_ms) {
            Sleep(poll_ms);
            elapsed += poll_ms;
            if (elapsed % 10000 == 0)
                BRIDGE_LOG("Waiting for GEngine... (%ds)", elapsed / 1000);
        }
        if (!g_engine_found) {
            BRIDGE_LOG("FATAL: GEngine not found after %ds -- bridge disabled",
                       gate_timeout_ms / 1000);
            return 0;
        }
        BRIDGE_LOG("[3/7] GEngine: 0x%p", g_engine_ptr);
    }

    /* === Step 4: FUObjectItem stride (GEngine cross-validation) === */
    detect_fuobjectitem_stride();

    /* === Step 5: FExec vtable === */
    if (!find_fexec_vtable()) {
        BRIDGE_LOG("FATAL: FExec vtable not found -- commands disabled");
        return 0;
    }
    BRIDGE_LOG("[4/7] FExec vtable at GEngine+0x%llX", (unsigned long long)g_fexec_offset);

    /* === Step 6: FExec hooks (GEngine + GUObjectArray scan) === */
    install_all_fexec_hooks();
    BRIDGE_LOG("[5/7] FExec hooks: %d installed",
               (int)g_fexec_hook_count.load());

    /* === Step 7: UWorld via GUObjectArray + FName("World") ===
     * Active scan -- works at cold start without waiting for game to call FExec. */
    if (find_uworld_via_guobjectarray())
        BRIDGE_LOG("[6/7] UWorld: 0x%p", g_world_ptr);
    else
        BRIDGE_LOG("[6/7] UWorld: not found yet (FExec hook will capture on first game call)");

    /* === Step 8: ULocalPlayer via GUObjectArray + FName("LocalPlayer") ===
     * 'LocalPlayer' is in FNamePool block 5+ (not block 0).
     * Multi-block search using g_fnamepool_global handles this correctly. */
    if (find_localplayer())
        BRIDGE_LOG("[7/7] ULocalPlayer: 0x%p", g_localplayer_ptr);
    else
        BRIDGE_LOG("[7/7] ULocalPlayer: not found -- gameplay cmds (slomo, camera) will fail");

    /* === Step 9: APlayerCameraManager (two paths + cross-validation) ===
     *
     * Path A: GUObjectArray FName scan for "PlayerCameraManager" /
     *         "BP_PlayerCameraManager_C" (may miss game-specific subclasses).
     * Path B: ULocalPlayer+0x30 -> APlayerController -> FField reflection
     *         for "PlayerCameraManager" property (game-agnostic).
     * Path C: GEngine+0x200 -> GameViewport -> World (render path sanity).
     *
     * cross_validate_camera() runs all three and picks the best result. */
    BRIDGE_LOG("--- Step 8: APlayerCameraManager (4-path cross-validation) ---");
    find_camera_manager(); /* Path A: GUObjectArray FName scan */
    cross_validate_camera(); /* Paths B+C+D: LP chain + GVC render + UUU-probe */
    if (g_camera_manager_ptr)
        BRIDGE_LOG("[8/9] APlayerCameraManager: 0x%p (cross-validated A/B/C/D)",
                   g_camera_manager_ptr);
    else
        BRIDGE_LOG("[8/9] APlayerCameraManager: not found -- "
                   "direct camera override unavailable (try __cam_mem_find after level load)");

    /* === Step 10: FMinimalViewInfo pointer via UClass property reflection ===
     * find_cam_pov() walks UClass::ChildProperties to get CameraCachePrivate
     * offset, then validates by reading FOV. */
    if (find_cam_pov())
        BRIDGE_LOG("[9/9] FMinimalViewInfo: 0x%p", g_cam_pov_ptr);
    else
        BRIDGE_LOG("[9/9] FMinimalViewInfo: not resolved yet "
                   "(run __cam_mem_find after game loads)");

    /* === Game-thread dispatch ===
     * UE5 requires console commands on the game thread.
     * WndProc subclass delivers commands via PostMessage. */
    for (int retry = 0; retry < 20; retry++) {
        Sleep(500);
        if (setup_gamethread_dispatch())
            break;
        if (retry % 4 == 3)
            BRIDGE_LOG("Waiting for game window... (%ds)", (retry + 1) / 2);
    }

    return 0;
}

/*
 * Minimum module size to start the bridge (10 MB).
 *
 * When --opt-hook-children is used, renderdoc.dll gets injected into
 * BOTH the launcher EXE and the real game process. The launcher is
 * typically tiny (< 1 MB) and has no UE5 engine code. If we start
 * the bridge in the launcher, it grabs port 9998 and blocks the real
 * game process from binding. Skip bridge startup for small modules.
 */
static const size_t BRIDGE_MIN_MODULE_SIZE = 10 * 1024 * 1024;

static DWORD WINAPI cs_startup_thread(LPVOID)
{
    /* Check if this is a real game process or just a tiny launcher */
    ModuleRegion check_rgn;
    size_t mod_size = 0;
    if (get_main_module(check_rgn))
        mod_size = check_rgn.size;

    if (mod_size < BRIDGE_MIN_MODULE_SIZE) {
        BRIDGE_LOG("Module size=%zu bytes (< %zu MB threshold). "
                   "Skipping bridge in launcher process.",
                   mod_size, BRIDGE_MIN_MODULE_SIZE / (1024*1024));
        return 0;
    }

    BRIDGE_LOG("=== captureAIshi console server (embedded in RenderDoc) ===");
    BRIDGE_LOG("Module size: %zu MB -- starting bridge", mod_size / (1024*1024));

    int port = CONSOLE_DEFAULT_PORT;
    const char* env_port = getenv("CAPTUREAI_BRIDGE_PORT");
    if (env_port) {
        port = atoi(env_port);
        if (port <= 0 || port > 65535) port = CONSOLE_DEFAULT_PORT;
    }

    /* Start camera tick thread */
    InterlockedExchange(&cs_tick_running, 1);
    cs_tick_handle = CreateThread(NULL, 0, cs_camera_tick, NULL, 0, NULL);

    /* Start GEngine scan in background -- don't block TCP server */
    cs_engine_scan_handle = CreateThread(NULL, 0, cs_engine_scan_thread, NULL, 0, NULL);

    /* Run TCP server immediately (blocks until shutdown).
     * __bridge_ping works right away; GEngine-dependent commands
     * return "GEngine not available" until scan completes. */
    cs_server_main(port);
    return 0;
}

/* -- Public API -------------------------------------------------- */

static inline void ConsoleServer_Start()
{
    InitializeCriticalSection(&cs_client_cs);
    cs_main_thread = CreateThread(NULL, 0, cs_startup_thread, NULL, 0, NULL);
}

static inline void ConsoleServer_Stop()
{
    InterlockedExchange(&cs_server_running, 0);
    InterlockedExchange(&cs_tick_running, 0);

    /* Restore original WndProc before shutdown */
    if (g_game_hwnd && g_original_wndproc) {
        SetWindowLongPtrA(g_game_hwnd, GWLP_WNDPROC, (LONG_PTR)g_original_wndproc);
        g_original_wndproc = NULL;
        g_game_hwnd = NULL;
        g_gamethread_dispatch_ready = false;
    }

    if (cs_listen_socket != INVALID_SOCKET)
        closesocket(cs_listen_socket);

    /* Wait for main server thread */
    if (cs_main_thread) {
        WaitForSingleObject(cs_main_thread, 3000);
        CloseHandle(cs_main_thread);
        cs_main_thread = NULL;
    }

    /* Wait for tick thread */
    if (cs_tick_handle) {
        WaitForSingleObject(cs_tick_handle, 1000);
        CloseHandle(cs_tick_handle);
        cs_tick_handle = NULL;
    }

    /* Wait for engine scan thread */
    if (cs_engine_scan_handle) {
        WaitForSingleObject(cs_engine_scan_handle, 2000);
        CloseHandle(cs_engine_scan_handle);
        cs_engine_scan_handle = NULL;
    }

    /* Wait for client threads. Force each socket to error-out of recv()
     * first so the thread can observe cs_server_running==0 promptly. */
    EnterCriticalSection(&cs_client_cs);
    for (int i = 0; i < cs_client_count; i++) {
        if (cs_client_slots[i].sock != INVALID_SOCKET)
            shutdown(cs_client_slots[i].sock, SD_BOTH);
    }
    for (int i = 0; i < cs_client_count; i++) {
        WaitForSingleObject(cs_client_slots[i].thread, 1000);
        CloseHandle(cs_client_slots[i].thread);
    }
    cs_client_count = 0;
    LeaveCriticalSection(&cs_client_cs);
    DeleteCriticalSection(&cs_client_cs);

    /* Remove all FExec hooks before shutdown */
    uninstall_all_fexec_hooks();

    /* Restore any code-patched camera-write sites */
    cam_intercept_uninstall_all();

    /* All threads are joined; safe to clean up Winsock now. */
    WSACleanup();

    BRIDGE_LOG("Console server shutdown complete");
}

#pragma warning(pop)  /* restore 4996 */

#else  /* non-Windows */

static inline void ConsoleServer_Start() {}
static inline void ConsoleServer_Stop() {}

#endif /* _WIN32 */

#endif /* CAPTUREAI_CONSOLE_SERVER_H */
