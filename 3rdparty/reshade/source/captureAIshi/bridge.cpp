/*
 * captureAIshi_bridge -- Path B "embedded" variant.
 *
 * Same source-of-truth as 3rdparty/reshade_bridge/src/bridge.cpp BUT
 * compiled into ReShade's dxgi.dll itself rather than as a separate
 * captureAIshi_bridge.addon DLL. Mirrors Path A's pattern where
 * renderdoc/renderdoc/core/bridge/console_server.h is compiled into
 * renderdoc.dll.
 *
 * Lifecycle is owned by ReShade's DllMain (source/dll_main.cpp). That TU
 * forward-declares and calls:
 *   bridge_start()  on DLL_PROCESS_ATTACH
 *   bridge_stop()   on DLL_PROCESS_DETACH
 *
 * No reshade::register_addon / NAME / DESCRIPTION exports here -- those
 * are for external addon DLLs. We are reshade itself; addon-event
 * registration for the frame-capture subsystem happens through
 * fc_embed::register_events() (see frame_capture.cpp + embed_api.h).
 *
 * ASCII only in this file (MSVC C4819 compliance).
 */

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include "embed_api.h"   /* fc_embed::trigger_oneshot from frame_capture.cpp */
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <string>
#include <vector>
#include <algorithm>
#include <thread>
#include <atomic>
#include <mutex>
#include <chrono>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "psapi.lib")

/* ── Configuration ─────────────────────────────────────────────────── */

static const int DEFAULT_PORT = 9998;
static const int MAX_CMD_LEN  = 4096;

/* ── Logging ───────────────────────────────────────────────────────── */

static FILE*      g_logfile = nullptr;
static std::mutex g_log_mutex;

void bridge_log(const char* fmt, ...)
{
    std::lock_guard<std::mutex> lock(g_log_mutex);
    if (!g_logfile) return;

    va_list args;
    va_start(args, fmt);

    SYSTEMTIME st;
    GetLocalTime(&st);
    fprintf(g_logfile, "[%02d:%02d:%02d.%03d] ",
            st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);

    vfprintf(g_logfile, fmt, args);
    fprintf(g_logfile, "\n");
    fflush(g_logfile);

    va_end(args);
}

/* ── Include subsystems (order matters: dependencies first) ──────── */

#include "pattern_scan.h"
#include "ue5_engine.h"
#include "camera_path.h"

/* ── Camera Smoothing ──────────────────────────────────────────────── */

/*
 * Exponential moving average for camera input smoothing.
 * Factor controls how many frames of history to blend:
 *   1 = instant (no smoothing)
 *   10 = smooth over ~10 frames
 *   100 = very smooth (for video recording)
 *
 * UUU calls this "movement interpolation factor".
 */

/* Smoothing factor is read by the tick thread every iteration and
 * written by the TCP thread on __smooth.  MSVC /O2 was hoisting the
 * plain-float read out of the tick loop, so TCP writes were never
 * observed.  atomic<float> with relaxed ordering gives us a memory
 * barrier on every read without measurable overhead. */
static std::atomic<float> g_smooth_factor{1.0f};
static Vec3  g_smooth_pos = {0, 0, 0};
static float g_smooth_pitch = 0, g_smooth_yaw = 0, g_smooth_roll = 0;
/* Read by tick thread, written by TCP thread -- atomic avoids torn read. */
static std::atomic<bool> g_smooth_initialized{false};

static InterpolatedCamera apply_smoothing(const InterpolatedCamera& raw)
{
    float smooth = g_smooth_factor.load(std::memory_order_relaxed);
    if (smooth <= 1.0f || !g_smooth_initialized.load()) {
        g_smooth_pos = raw.pos;
        g_smooth_pitch = raw.pitch;
        g_smooth_yaw = raw.yaw;
        g_smooth_roll = raw.roll;
        g_smooth_initialized.store(true);
        return raw;
    }

    /* EMA: new = old + (raw - old) / factor */
    float alpha = 1.0f / smooth;
    g_smooth_pos.x += (raw.pos.x - g_smooth_pos.x) * alpha;
    g_smooth_pos.y += (raw.pos.y - g_smooth_pos.y) * alpha;
    g_smooth_pos.z += (raw.pos.z - g_smooth_pos.z) * alpha;
    g_smooth_pitch += (raw.pitch - g_smooth_pitch) * alpha;
    g_smooth_yaw   += (raw.yaw   - g_smooth_yaw)   * alpha;
    g_smooth_roll  += (raw.roll  - g_smooth_roll)  * alpha;

    InterpolatedCamera out;
    out.pos   = g_smooth_pos;
    out.pitch = g_smooth_pitch;
    out.yaw   = g_smooth_yaw;
    out.roll  = g_smooth_roll;
    out.fov   = raw.fov;  /* don't smooth FOV */
    return out;
}

/* ── Camera Path Tick Thread ───────────────────────────────────────── */

static std::atomic<bool> g_tick_running{false};
static std::thread       g_tick_thread;

/* Tick rate for camera path playback (Hz) */
static const int TICK_RATE = 60;

static void camera_tick_thread()
{
    using clock = std::chrono::steady_clock;
    auto interval = std::chrono::microseconds(1000000 / TICK_RATE);
    auto last = clock::now();

    bridge_log("[TICK] Camera tick thread started (%d Hz)", TICK_RATE);

    while (g_tick_running) {
        auto now = clock::now();
        float dt = std::chrono::duration<float>(now - last).count();
        last = now;

        /* Update camera path playback */
        if (g_camera_path.is_playing()) {
            InterpolatedCamera cam;
            bool still_playing = g_camera_path.tick(dt, cam);

            /* Apply smoothing */
            cam = apply_smoothing(cam);

            /* Send camera position to game */
            set_camera_location(cam.pos.x, cam.pos.y, cam.pos.z);
            set_camera_rotation(cam.pitch, cam.yaw, cam.roll);
            if (cam.fov > 0.0f && cam.fov != g_camera.fov) {
                set_fov(cam.fov);
            }

            if (!still_playing) {
                bridge_log("[TICK] Camera path playback ended");
            }
        }

        /* Sleep until next tick */
        auto elapsed = clock::now() - now;
        if (elapsed < interval) {
            std::this_thread::sleep_for(interval - elapsed);
        }
    }

    bridge_log("[TICK] Camera tick thread stopped");
}

/* ── TCP Command Router ────────────────────────────────────────────── */

static std::atomic<bool> g_server_running{false};
static SOCKET g_listen_socket = INVALID_SOCKET;

/* Client socket tracking for clean shutdown.
 * shutdown(SD_BOTH) on each socket causes recv() to return with an
 * error, letting the detached client threads observe g_server_running==false
 * and exit instead of blocking forever. */
static std::mutex              g_client_socks_mutex;
static std::vector<SOCKET>     g_client_socks;

/* Helper: send response string to client */
static void reply(SOCKET sock, const char* msg)
{
    send(sock, msg, (int)strlen(msg), 0);
}

static void reply(SOCKET sock, const std::string& msg)
{
    send(sock, msg.c_str(), (int)msg.size(), 0);
}

/* Locale-independent ASCII float parser. strtof honors LC_NUMERIC and
 * UE5 init has been observed to flip the CRT locale, making "10.5" parse
 * as 10 under DE/RU.  This parser only recognizes '.' and ignores the
 * locale entirely. */
static float ascii_strtof(const char* s, const char** end = nullptr)
{
    const char* p = s;
    while (*p == ' ' || *p == '\t') p++;
    bool neg = false;
    if (*p == '+') { p++; }
    else if (*p == '-') { neg = true; p++; }
    double val = 0.0;
    bool any = false;
    while (*p >= '0' && *p <= '9') { val = val*10.0 + (*p-'0'); p++; any=true; }
    if (*p == '.') {
        p++;
        double f = 0.1;
        while (*p >= '0' && *p <= '9') { val += (*p-'0')*f; f*=0.1; p++; any=true; }
    }
    if (!any) { if (end) *end = s; return 0.0f; }
    if (*p == 'e' || *p == 'E') {
        p++;
        bool neg_exp = false;
        if (*p == '+') p++; else if (*p == '-') { neg_exp=true; p++; }
        int exp = 0;
        while (*p >= '0' && *p <= '9') { exp = exp*10 + (*p-'0'); p++; }
        double mult = 1.0;
        for (int i = 0; i < exp; i++) mult *= 10.0;
        if (neg_exp) val /= mult; else val *= mult;
    }
    if (neg) val = -val;
    if (end) *end = p;
    return (float)val;
}

/* Helper: parse floats from a command string after a prefix */
static int parse_floats(const char* str, float* out, int max_count)
{
    int count = 0;
    const char* p = str;
    while (count < max_count && *p) {
        while (*p == ' ' || *p == ',') p++;
        if (!*p) break;
        const char* end = nullptr;
        float v = ascii_strtof(p, &end);
        if (end == p) break;
        out[count++] = v;
        p = end;
    }
    return count;
}

/*
 * Route a single command line to the appropriate handler.
 * Returns true if the command was recognized (even if execution failed).
 */
static bool route_command(SOCKET client, const std::string& cmd)
{
    /* ── Bridge internal commands ── */

    if (cmd == "__bridge_ping") {
        reply(client, "pong\n");
        return true;
    }

    /* One-shot frame capture (parity with RenderDoc's __cam_rdc_capture).
     * Bypasses FC_EnableCapture + FPS gate -- writes exactly one BMP/PNG
     * (+ DepthBuffer.exr / NormalBuffer.exr if enabled) on next present.
     * Use from Bridge Debug "Capture" button or trajectory Play loop. */
    if (cmd == "__fc_capture") {
        fc_embed::trigger_oneshot();
        reply(client, "OK\n");
        return true;
    }

    if (cmd == "__bridge_status") {
        char buf[512];
        snprintf(buf, sizeof(buf),
                 "engine_found=%d engine_ptr=0x%p exec_fn=0x%p "
                 "camera_active=%d paused=%d hud=%d "
                 "path_keyframes=%zu path_playing=%d "
                 "smooth_factor=%.1f\n",
                 (int)g_engine_found.load(), g_engine_ptr, (void*)g_exec_fn,
                 (int)g_debug_camera_active, (int)g_paused.load(),
                 (int)g_hud_visible,
                 g_camera_path.count(), (int)g_camera_path.is_active(),
                 g_smooth_factor.load());
        reply(client, buf);
        return true;
    }

    if (cmd.rfind("__bridge_set_offset ", 0) == 0) {
        uintptr_t offset = strtoull(cmd.c_str() + 20, NULL, 16);
        if (find_gengine_via_offset(offset))
            reply(client, "ok\n");
        else
            reply(client, "null\n");
        return true;
    }

    if (cmd == "__bridge_rescan") {
        g_engine_found = false;
        g_engine_ptr = nullptr;
        g_exec_fn = nullptr;
        if (find_gengine())
            reply(client, "ok\n");
        else
            reply(client, "not_found\n");
        return true;
    }

    /* ── Camera control shortcuts ── */

    if (cmd == "__cam_toggle") {
        toggle_debug_camera();
        reply(client, "ok\n");
        return true;
    }

    if (cmd == "__cam_pause" || cmd == "__timestop") {
        toggle_pause();
        char buf[64];
        snprintf(buf, sizeof(buf), "paused=%d speed=%.4f\n",
                 (int)g_paused.load(), g_game_speed);
        reply(client, buf);
        return true;
    }

    if (cmd.rfind("__cam_speed ", 0) == 0) {
        float speed = ascii_strtof(cmd.c_str() + 12, NULL);
        if (!std::isfinite(speed) || speed < 0.0f || speed > 1e6f) speed = 1.0f;
        set_game_speed(speed);
        reply(client, "ok\n");
        return true;
    }

    if (cmd == "__hud_toggle") {
        toggle_hud();
        reply(client, "ok\n");
        return true;
    }

    if (cmd.rfind("__hotsample ", 0) == 0) {
        int w = 0, h = 0;
        sscanf(cmd.c_str() + 12, "%d %d", &w, &h);
        if (w > 0 && h > 0) {
            hotsample(w, h);
            reply(client, "ok\n");
        } else {
            reply(client, "error: usage __hotsample WIDTH HEIGHT\n");
        }
        return true;
    }

    if (cmd.rfind("__smooth ", 0) == 0) {
        float v = ascii_strtof(cmd.c_str() + 9, NULL);
        if (!std::isfinite(v) || v < 1.0f || v > 1000.0f) v = 1.0f;
        g_smooth_factor.store(v, std::memory_order_relaxed);
        g_smooth_initialized.store(false);
        char buf[64];
        snprintf(buf, sizeof(buf), "smooth_factor=%.1f\n", v);
        reply(client, buf);
        return true;
    }

    /* ── Camera path commands ── */

    if (cmd == "__path_add") {
        /* Add current camera state as keyframe */
        CameraKeyframe kf;
        kf.pos = { g_camera.x, g_camera.y, g_camera.z };
        kf.pitch = g_camera.pitch;
        kf.yaw = g_camera.yaw;
        kf.roll = g_camera.roll;
        kf.fov = g_camera.fov;
        kf.duration = 2.0f;  /* default 2 seconds per segment */
        g_camera_path.add_keyframe(kf);
        reply(client, "ok\n");
        return true;
    }

    if (cmd.rfind("__path_add ", 0) == 0) {
        /* __path_add X Y Z Pitch Yaw Roll FOV [Duration] */
        float vals[8] = {0, 0, 0, 0, 0, 0, 90.0f, 2.0f};
        int n = parse_floats(cmd.c_str() + 11, vals, 8);
        if (n >= 6) {
            CameraKeyframe kf;
            kf.pos = { vals[0], vals[1], vals[2] };
            kf.pitch = vals[3];
            kf.yaw = vals[4];
            kf.roll = vals[5];
            kf.fov = (n >= 7) ? vals[6] : 90.0f;
            kf.duration = (n >= 8) ? vals[7] : 2.0f;
            g_camera_path.add_keyframe(kf);
            reply(client, "ok\n");
        } else {
            reply(client, "error: need at least 6 values (X Y Z P Y R)\n");
        }
        return true;
    }

    if (cmd == "__path_clear") {
        g_camera_path.clear();
        reply(client, "ok\n");
        return true;
    }

    if (cmd.rfind("__path_delete ", 0) == 0) {
        char* end = NULL;
        long val = strtol(cmd.c_str() + 14, &end, 10);
        if (end == cmd.c_str() + 14 || val < 0 || val > 10000) {
            reply(client, "error: bad index\n");
            return true;
        }
        if (g_camera_path.delete_keyframe((size_t)val))
            reply(client, "ok\n");
        else
            reply(client, "error: invalid index\n");
        return true;
    }

    if (cmd == "__path_list") {
        reply(client, g_camera_path.list_keyframes());
        return true;
    }

    if (cmd == "__path_play" || cmd.rfind("__path_play ", 0) == 0) {
        float speed = 1.0f;
        if (cmd.size() > 12) {
            float v = ascii_strtof(cmd.c_str() + 12, NULL);
            if (std::isfinite(v) && v > 0.0f && v <= 1e6f) speed = v;
        }
        g_camera_path.play(speed);
        reply(client, "ok\n");
        return true;
    }

    if (cmd == "__path_stop") {
        g_camera_path.stop();
        reply(client, "ok\n");
        return true;
    }

    if (cmd == "__path_pause") {
        g_camera_path.toggle_pause();
        reply(client, "ok\n");
        return true;
    }

    if (cmd.rfind("__path_loop ", 0) == 0) {
        bool loop = (cmd[12] == '1');
        g_camera_path.set_loop(loop);
        reply(client, loop ? "loop=on\n" : "loop=off\n");
        return true;
    }

    if (cmd == "__path_loop") {
        g_camera_path.set_loop(!g_camera_path.is_active());
        reply(client, "ok\n");
        return true;
    }

    if (cmd == "__path_visualize") {
        auto points = g_camera_path.visualize(20);
        std::string result;
        char buf[128];
        for (size_t i = 0; i < points.size(); i++) {
            const auto& p = points[i];
            snprintf(buf, sizeof(buf),
                     "%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f\n",
                     p.pos.x, p.pos.y, p.pos.z,
                     p.pitch, p.yaw, p.roll, p.fov);
            result += buf;
        }
        if (result.empty()) result = "(no path)\n";
        reply(client, result);
        return true;
    }

    if (cmd == "__path_info") {
        char buf[256];
        snprintf(buf, sizeof(buf),
                 "keyframes=%zu total_duration=%.2fs playing=%d "
                 "loop=%d\n",
                 g_camera_path.count(),
                 g_camera_path.total_duration(),
                 (int)g_camera_path.is_active(),
                 0 /* TODO: expose loop state */);
        reply(client, buf);
        return true;
    }

    /* ── Regular UE5 console commands (pass-through to Exec) ── */

    /* Any command not starting with __ is a regular console command */
    if (cmd.rfind("__", 0) != 0) {
        exec_console_command(cmd.c_str());
        return true;
    }

    /* Unknown __ command */
    bridge_log("Unknown bridge command: %s", cmd.c_str());
    reply(client, "error: unknown command\n");
    return false;
}

/* ── TCP Client Handler ────────────────────────────────────────────── */

static void handle_client(SOCKET client_sock)
{
    {
        std::lock_guard<std::mutex> lk(g_client_socks_mutex);
        g_client_socks.push_back(client_sock);
    }
    bridge_log("Client connected");

    char buffer[MAX_CMD_LEN];
    std::string line_buffer;

    while (g_server_running) {
        int received = recv(client_sock, buffer, sizeof(buffer) - 1, 0);
        if (received <= 0) {
            if (received == 0)
                bridge_log("Client disconnected gracefully");
            else {
                int err = WSAGetLastError();
                if (err != WSAECONNRESET && err != WSAEINTR)
                    bridge_log("recv error: %d", err);
            }
            break;
        }

        /* Cap line buffer to prevent OOM on malicious/runaway clients. */
        if (line_buffer.size() + (size_t)received > 1024 * 1024) {
            bridge_log("Client line buffer overflow -- disconnecting");
            break;
        }
        line_buffer.append(buffer, (size_t)received);

        /* Process complete lines (newline-delimited) */
        size_t pos;
        while ((pos = line_buffer.find('\n')) != std::string::npos) {
            std::string cmd = line_buffer.substr(0, pos);
            line_buffer.erase(0, pos + 1);

            /* Trim \r */
            if (!cmd.empty() && cmd.back() == '\r')
                cmd.pop_back();

            if (cmd.empty()) continue;

            route_command(client_sock, cmd);
        }
    }

    {
        std::lock_guard<std::mutex> lk(g_client_socks_mutex);
        auto it = std::find(g_client_socks.begin(), g_client_socks.end(), client_sock);
        if (it != g_client_socks.end()) g_client_socks.erase(it);
    }
    closesocket(client_sock);
    bridge_log("Client handler exited");
}

/* ── TCP Server Thread ─────────────────────────────────────────────── */

static void tcp_server_thread(int port)
{
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        bridge_log("ERROR: WSAStartup failed: %d", WSAGetLastError());
        return;
    }

    g_listen_socket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (g_listen_socket == INVALID_SOCKET) {
        bridge_log("ERROR: socket() failed: %d", WSAGetLastError());
        WSACleanup();
        return;
    }

    int opt = 1;
    setsockopt(g_listen_socket, SOL_SOCKET, SO_REUSEADDR,
               (const char*)&opt, sizeof(opt));

    struct sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    addr.sin_port = htons((u_short)port);

    if (bind(g_listen_socket, (struct sockaddr*)&addr, sizeof(addr))
            == SOCKET_ERROR) {
        bridge_log("ERROR: bind() on port %d failed: %d",
                   port, WSAGetLastError());
        closesocket(g_listen_socket);
        g_listen_socket = INVALID_SOCKET;
        WSACleanup();
        return;
    }

    if (listen(g_listen_socket, 4) == SOCKET_ERROR) {
        bridge_log("ERROR: listen() failed: %d", WSAGetLastError());
        closesocket(g_listen_socket);
        g_listen_socket = INVALID_SOCKET;
        WSACleanup();
        return;
    }

    g_server_running = true;
    bridge_log("TCP console server on 127.0.0.1:%d", port);

    while (g_server_running) {
        fd_set read_fds;
        FD_ZERO(&read_fds);
        FD_SET(g_listen_socket, &read_fds);

        struct timeval tv = { 1, 0 };
        int sel = select(0, &read_fds, NULL, NULL, &tv);
        if (sel > 0) {
            SOCKET client = accept(g_listen_socket, NULL, NULL);
            if (client != INVALID_SOCKET)
                std::thread(handle_client, client).detach();
        }
    }

    closesocket(g_listen_socket);
    g_listen_socket = INVALID_SOCKET;
    WSACleanup();
    bridge_log("TCP server stopped");
}

/* ── DLL Startup / Shutdown ────────────────────────────────────────── */

static std::thread g_server_thread;

static void startup()
{
    /* Open log file next to DLL */
    char dll_path[MAX_PATH];
    HMODULE h_self = NULL;
    GetModuleHandleExA(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS
        | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCSTR)&startup, &h_self);
    GetModuleFileNameA(h_self, dll_path, MAX_PATH);

    std::string log_path(dll_path);
    size_t last_dot = log_path.rfind('.');
    if (last_dot != std::string::npos)
        log_path = log_path.substr(0, last_dot);
    log_path += ".log";

    g_logfile = fopen(log_path.c_str(), "w");
    bridge_log("=== captureAIshi bridge v0.2 ===");
    bridge_log("DLL: %s", dll_path);
    bridge_log("Log: %s", log_path.c_str());

    /* Find GEngine (tries env var first, then auto-scan) */
    find_gengine();

    /* Read port from env (default 9998) */
    int port = DEFAULT_PORT;
    const char* env_port = getenv("CAPTUREAI_BRIDGE_PORT");
    if (env_port) {
        port = atoi(env_port);
        if (port <= 0 || port > 65535) port = DEFAULT_PORT;
    }

    /* Start camera tick thread */
    g_tick_running = true;
    g_tick_thread = std::thread(camera_tick_thread);

    /* Start TCP server */
    g_server_thread = std::thread(tcp_server_thread, port);
}

static void shutdown()
{
    bridge_log("Bridge shutting down...");

    /* Stop tick thread */
    g_tick_running = false;
    if (g_tick_thread.joinable())
        g_tick_thread.join();

    /* Stop TCP server: first force all recv()-blocked client threads
     * to return an error so they can see g_server_running==false. */
    g_server_running = false;
    {
        std::lock_guard<std::mutex> lk(g_client_socks_mutex);
        for (SOCKET s : g_client_socks)
            shutdown(s, SD_BOTH);
    }
    if (g_listen_socket != INVALID_SOCKET)
        closesocket(g_listen_socket);
    if (g_server_thread.joinable())
        g_server_thread.join();

    if (g_logfile) {
        bridge_log("Bridge shutdown complete");
        fclose(g_logfile);
        g_logfile = nullptr;
    }
}

/* ── Public entry points (called from ReShade's source/dll_main.cpp) ─── */

/* These are the only externally visible symbols. ReShade's DllMain owns
 * the DLL lifecycle; we just expose start/stop hooks it can call. The
 * frame-capture subsystem is wired separately via fc_embed::* (see
 * embed_api.h). */

extern "C" void bridge_start()
{
    /* startup() is the original Path B init -- opens log file, starts the
     * camera tick thread + TCP server thread. It detaches both so this
     * call returns quickly; no loader-lock concerns since we are called
     * from a deferred context (ReShade init is past DllMain by the time
     * its addon hooks run, but to be safe we still defer like the
     * standalone addon did). */
    std::thread(startup).detach();
}

extern "C" void bridge_stop()
{
    /* Symmetrical to startup(): close listener + tick thread, flush log. */
    shutdown();
}
