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
    int n = vsnprintf(buf + prefix_len, sizeof(buf) - prefix_len - 2, fmt, args);
    va_end(args);

    int total = prefix_len + (n > 0 ? n : 0);
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

#undef bridge_log

/* -- Configuration ----------------------------------------------- */

static const int CONSOLE_DEFAULT_PORT = 9998;
static const int CONSOLE_MAX_CMD_LEN  = 4096;

/* -- Camera Smoothing -------------------------------------------- */

static float cs_smooth_factor = 1.0f;
static Vec3  cs_smooth_pos = {0, 0, 0};
static float cs_smooth_pitch = 0, cs_smooth_yaw = 0, cs_smooth_roll = 0;
static bool  cs_smooth_initialized = false;

static InterpolatedCamera cs_apply_smoothing(const InterpolatedCamera& raw)
{
    if (cs_smooth_factor <= 1.0f || !cs_smooth_initialized) {
        cs_smooth_pos = raw.pos;
        cs_smooth_pitch = raw.pitch;
        cs_smooth_yaw = raw.yaw;
        cs_smooth_roll = raw.roll;
        cs_smooth_initialized = true;
        return raw;
    }
    float alpha = 1.0f / cs_smooth_factor;
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

    BRIDGE_LOG("Camera tick thread started (60 Hz)");

    while (InterlockedCompareExchange(&cs_tick_running, 1, 1) == 1) {
        QueryPerformanceCounter(&now);
        float dt = (float)(now.QuadPart - last.QuadPart) / (float)freq.QuadPart;
        last = now;

        if (g_camera_path.is_playing()) {
            InterpolatedCamera cam;
            bool still = g_camera_path.tick(dt, cam);
            cam = cs_apply_smoothing(cam);
            set_camera_location(cam.pos.x, cam.pos.y, cam.pos.z);
            set_camera_rotation(cam.pitch, cam.yaw, cam.roll);
            if (cam.fov > 0.0f && cam.fov != g_camera.fov)
                set_fov(cam.fov);
            if (!still)
                BRIDGE_LOG("Camera path playback ended");
        }

        Sleep(16);  /* ~60 Hz */
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

static int cs_parse_floats(const char* str, float* out, int max_count) {
    int count = 0;
    const char* p = str;
    while (count < max_count && *p) {
        while (*p == ' ' || *p == ',') p++;
        if (!*p) break;
        char* end = NULL;
        float v = strtof(p, &end);
        if (end == p) break;
        out[count++] = v;
        p = end;
    }
    return count;
}

/* -- Command Router ---------------------------------------------- */

static bool cs_route_command(SOCKET client, const std::string& cmd)
{
    if (cmd == "__bridge_ping") { cs_reply(client, "pong\n"); return true; }

    if (cmd == "__bridge_status") {
        char buf[768];
        snprintf(buf, sizeof(buf),
            "engine_found=%d engine_ptr=0x%p "
            "fexec_exec=0x%p fexec_offset=%d "
            "fexec_hooks=%d "
            "guobjectarray_found=%d guobjectarray=0x%p "
            "world_ptr=0x%p "
            "camera_active=%d paused=%d hud=%d "
            "path_keyframes=%zu path_playing=%d "
            "smooth_factor=%.1f embedded=1 "
            "gengine_global=0x%llX "
            "gamethread_dispatch=%d\n",
            (int)g_engine_found.load(), g_engine_ptr,
            (void*)g_fexec_exec, (int)g_fexec_offset,
            g_fexec_hook_count,
            (int)g_guobjectarray_found.load(), g_guobjectarray,
            g_world_ptr,
            (int)g_debug_camera_active, (int)g_paused.load(),
            (int)g_hud_visible,
            g_camera_path.count(), (int)g_camera_path.is_active(),
            cs_smooth_factor,
            (unsigned long long)g_engine_global_addr,
            (int)g_gamethread_dispatch_ready.load());
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

    /* Commands below require GEngine -- return error if not ready */
    if (!g_engine_found) {
        if (cmd == "__cam_toggle" || cmd == "__cam_pause" ||
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

    if (cmd == "__cam_toggle") { toggle_debug_camera(); cs_reply(client, "ok\n"); return true; }

    if (cmd == "__cam_pause" || cmd == "__timestop") {
        toggle_pause();
        char buf[64];
        snprintf(buf, sizeof(buf), "paused=%d speed=%.4f\n", (int)g_paused.load(), g_game_speed);
        cs_reply(client, buf);
        return true;
    }

    if (cmd.rfind("__cam_speed ", 0) == 0) {
        set_game_speed(strtof(cmd.c_str() + 12, NULL));
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
        cs_smooth_factor = strtof(cmd.c_str() + 9, NULL);
        if (cs_smooth_factor < 1.0f) cs_smooth_factor = 1.0f;
        cs_smooth_initialized = false;
        char buf[64]; snprintf(buf, sizeof(buf), "smooth_factor=%.1f\n", cs_smooth_factor);
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
        int val = atoi(cmd.c_str()+14);
        if (val < 0) { cs_reply(client, "error: negative index\n"); return true; }
        cs_reply(client, g_camera_path.delete_keyframe((size_t)val) ? "ok\n":"error\n");
        return true;
    }
    if (cmd == "__path_list") { cs_reply(client, g_camera_path.list_keyframes()); return true; }
    if (cmd == "__path_play" || cmd.rfind("__path_play ",0)==0) {
        float spd = cmd.size()>12 ? strtof(cmd.c_str()+12,NULL) : 1.0f;
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

/* Client thread tracking */
static HANDLE cs_client_handles[32];
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

    while (InterlockedCompareExchange(&cs_server_running, 1, 1) == 1) {
        int n = recv(client, buffer, sizeof(buffer)-1, 0);
        if (n <= 0) break;
        buffer[n] = '\0';
        line_buf.append(buffer);

        size_t pos;
        while ((pos = line_buf.find('\n')) != std::string::npos) {
            std::string cmd = line_buf.substr(0, pos);
            line_buf.erase(0, pos+1);
            if (!cmd.empty() && cmd.back()=='\r') cmd.pop_back();
            if (!cmd.empty()) cs_route_command(client, cmd);
        }
    }
    closesocket(client);
    BRIDGE_LOG("Client disconnected");
    return 0;
}

static void cs_server_main(int port)
{
    cs_listen_socket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (cs_listen_socket == INVALID_SOCKET) {
        BRIDGE_LOG("socket() failed: %d", WSAGetLastError());
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
        return;
    }

    if (listen(cs_listen_socket, 4) == SOCKET_ERROR) {
        BRIDGE_LOG("listen() failed: %d", WSAGetLastError());
        closesocket(cs_listen_socket);
        cs_listen_socket = INVALID_SOCKET;
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
                ClientArg* arg = new ClientArg;
                arg->sock = c;
                HANDLE h = CreateThread(NULL, 0, cs_handle_client_thread, arg, 0, NULL);
                if (h) {
                    EnterCriticalSection(&cs_client_cs);
                    if (cs_client_count < 32)
                        cs_client_handles[cs_client_count++] = h;
                    else
                        CloseHandle(h);
                    LeaveCriticalSection(&cs_client_cs);
                }
            }
        }
    }

    closesocket(cs_listen_socket);
    cs_listen_socket = INVALID_SOCKET;
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
    BRIDGE_LOG("GEngine scan thread started");

    /* Wait for game to finish initial loading before scanning.
     * Scanning too early (while DRM unpacks or sections load)
     * causes intermittent crashes at entry 3 of string search. */
    BRIDGE_LOG("Waiting 5s for game to stabilize...");
    Sleep(5000);

    /* Find GUObjectArray FIRST so GEngine finder can use it as fallback.
     * GUObjectArray is present from very early in game startup. */
    if (find_guobjectarray()) {
        BRIDGE_LOG("GUObjectArray found: 0x%p (%d objects)",
                   g_guobjectarray, guobjectarray_num_elements());
        log_guobjectarray_details();
    } else {
        BRIDGE_LOG("NOTE: GUObjectArray not found -- "
                   "GEngine Method B unavailable, string xref only");
    }

    /* Try FNamePool early -- it is stable from game startup and required
     * for FName-based UWorld search (find_uworld_via_guobjectarray). */
    {
        uintptr_t blk0 = find_fnamepool_block0();
        if (blk0) {
            BRIDGE_LOG("FNamePool block0=0x%llX global=0x%llX",
                       (unsigned long long)blk0,
                       (unsigned long long)g_fnamepool_global);
            /* Quick sanity: resolve "World" class name index */
            uint32_t world_idx = get_fname_cmpidx_for("World");
            BRIDGE_LOG("  FName('World') ComparisonIndex=0x%X%s",
                       world_idx,
                       world_idx == 0xFFFFFFFF ? " (NOT FOUND in block0)" : " OK");
            if (world_idx != 0xFFFFFFFF) {
                uint32_t engine_idx = get_fname_cmpidx_for("GameEngine");
                uint32_t pkg_idx    = get_fname_cmpidx_for("Package");
                BRIDGE_LOG("  FName('GameEngine')=0x%X FName('Package')=0x%X",
                           engine_idx, pkg_idx);
            }
        } else {
            BRIDGE_LOG("FNamePool block0: not found (will retry via GUObjectArray path)");
        }
    }

    const int poll_interval_ms = 2000;
    const int timeout_ms = 120000;
    int elapsed = 0;
    while (!find_gengine() && elapsed < timeout_ms) {
        Sleep(poll_interval_ms);
        elapsed += poll_interval_ms;
        if (elapsed % 10000 == 0)
            BRIDGE_LOG("Waiting for GEngine... (%ds)", elapsed / 1000);
    }
    if (g_engine_found) {
        BRIDGE_LOG("GEngine found after %ds", elapsed / 1000);

        /* Find FExec secondary vtable for console command execution */
        if (!find_fexec_vtable())
            BRIDGE_LOG("WARNING: FExec not found, commands will fail");

        /* Auto-detect FUObjectItem element stride.
         * GEngine.InternalIndex (+0x0C) lets us verify guobjectarray_get().
         * Default 24 bytes is wrong for some UE5 builds (may be 16). */
        detect_fuobjectitem_stride();

        /* Install FExec hooks on GEngine AND all FExec objects in
         * GUObjectArray (including ULocalPlayer).  When any FExec::Exec
         * fires with a non-NULL UWorld, we capture it automatically. */
        if (install_all_fexec_hooks())
            BRIDGE_LOG("FExec hooks active (%d total) -- "
                       "UWorld will be captured from game calls",
                       g_fexec_hook_count);
        else
            BRIDGE_LOG("WARNING: No FExec hooks installed");

        /* Proactively find UWorld.
         * Priority 1: WorldList scan -- does not need GUObjectArray,
         *   scans GEngine object for TIndirectArray<FWorldContext> then
         *   walks FWorldContext for UWorld by FNetworkNotify fingerprint.
         * Priority 2: GUObjectArray scan -- fallback for games where
         *   WorldList scan finds no FWorldContext (edge cases). */
        if (find_uworld_via_worldlist())
            BRIDGE_LOG("UWorld found via WorldList: 0x%p", g_world_ptr);
        else if (find_uworld_via_guobjectarray())
            BRIDGE_LOG("UWorld found via GUObjectArray: 0x%p", g_world_ptr);
        else
            BRIDGE_LOG("NOTE: UWorld not found yet -- will be captured "
                       "from FExec hook parameters when game calls Exec.");

        /* Find ULocalPlayer for gameplay command routing.
         * ULocalPlayer::Exec -> PlayerController -> CheatManager.
         * Lazy fallback also runs inside exec_console_command_internal. */
        if (find_localplayer())
            BRIDGE_LOG("ULocalPlayer found: 0x%p", g_localplayer_ptr);
        else
            BRIDGE_LOG("NOTE: ULocalPlayer not found -- "
                       "gameplay commands may not route correctly.");

        /* Wait a bit for the game window to be created, then install
         * the WndProc hook for game-thread command dispatch. */
        for (int retry = 0; retry < 20; retry++) {
            Sleep(500);
            if (setup_gamethread_dispatch())
                break;
            if (retry % 4 == 3)
                BRIDGE_LOG("Waiting for game window... (%ds)",
                           (retry + 1) / 2);
        }
    } else {
        BRIDGE_LOG("WARNING: GEngine not found after %ds", timeout_ms / 1000);
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

    /* Wait for client threads */
    EnterCriticalSection(&cs_client_cs);
    for (int i = 0; i < cs_client_count; i++) {
        WaitForSingleObject(cs_client_handles[i], 1000);
        CloseHandle(cs_client_handles[i]);
    }
    cs_client_count = 0;
    LeaveCriticalSection(&cs_client_cs);
    DeleteCriticalSection(&cs_client_cs);

    /* Remove all FExec hooks before shutdown */
    uninstall_all_fexec_hooks();

    BRIDGE_LOG("Console server shutdown complete");
}

#pragma warning(pop)  /* restore 4996 */

#else  /* non-Windows */

static inline void ConsoleServer_Start() {}
static inline void ConsoleServer_Stop() {}

#endif /* _WIN32 */

#endif /* CAPTUREAI_CONSOLE_SERVER_H */
