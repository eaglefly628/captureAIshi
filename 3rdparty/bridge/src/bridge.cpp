/*
 * captureAIshi_bridge.dll
 *
 * Minimal TCP console server for UE5 shipped games.
 * Replaces UUU's core functionality: receives console commands over TCP
 * and executes them via UEngine::Exec().
 *
 * Architecture:
 *   DllMain -> spawn TCP listener thread on port 9998
 *   TCP thread -> accept connections, read newline-delimited commands
 *   For each command -> find GEngine, call GEngine->Exec(NULL, cmd)
 *
 * Build: cl /LD /EHsc /O2 bridge.cpp ws2_32.lib /Fe:captureAIshi_bridge.dll
 *        (or use CMakeLists.txt)
 *
 * ASCII only in this file (MSVC C4819 compliance).
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <thread>
#include <atomic>
#include <mutex>

#pragma comment(lib, "ws2_32.lib")

/* ── Configuration ─────────────────────────────────────────────────── */

static const int DEFAULT_PORT = 9998;
static const int MAX_CMD_LEN = 4096;

/* ── Logging ───────────────────────────────────────────────────────── */

static FILE* g_logfile = nullptr;
static std::mutex g_log_mutex;

static void bridge_log(const char* fmt, ...)
{
    std::lock_guard<std::mutex> lock(g_log_mutex);
    if (!g_logfile) return;

    va_list args;
    va_start(args, fmt);

    /* Timestamp */
    SYSTEMTIME st;
    GetLocalTime(&st);
    fprintf(g_logfile, "[%02d:%02d:%02d.%03d] ",
            st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);

    vfprintf(g_logfile, fmt, args);
    fprintf(g_logfile, "\n");
    fflush(g_logfile);

    va_end(args);
}

/* ── UE5 Engine Interface ──────────────────────────────────────────── */

/*
 * UEngine::Exec signature (UE4/UE5):
 *   bool UEngine::Exec(UWorld* InWorld, const TCHAR* Cmd,
 *                      FOutputDevice& Ar)
 *
 * We need to find the GEngine global pointer. In shipped UE5 games,
 * GEngine is typically at a fixed offset from the module base.
 *
 * Pattern scan approach:
 *   Search for the byte pattern that references GEngine in the .text
 *   section. This is more robust across game versions than hardcoded
 *   offsets.
 *
 * Common GEngine access pattern in UE5 (x64):
 *   48 8B 05 XX XX XX XX   ; mov rax, [rip + offset]  -> GEngine
 *   48 85 C0               ; test rax, rax
 *
 * The signature for GEngine assignment/check in UEngineLoop::Init:
 *   48 89 05 ?? ?? ?? ??   ; mov [rip+??], rax   (store GEngine)
 *   followed by engine init code
 */

/* Function pointer types matching UE5 internals */
typedef void* UWorld;
typedef void* FOutputDevice;

/* GEngine->Exec virtual function - we call through vtable */
typedef bool (__thiscall *ExecFn)(void* thisptr, UWorld* world,
                                   const wchar_t* cmd, FOutputDevice* ar);

static void* g_engine_ptr = nullptr;
static std::atomic<bool> g_engine_found{false};

/*
 * Pattern scanner: searches a memory region for a byte pattern with
 * wildcard support (0xCC = wildcard).
 *
 * Returns the address of the first match, or nullptr.
 */
static const uint8_t* pattern_scan(
    const uint8_t* start, size_t size,
    const uint8_t* pattern, const char* mask, size_t pattern_len)
{
    for (size_t i = 0; i <= size - pattern_len; i++) {
        bool found = true;
        for (size_t j = 0; j < pattern_len; j++) {
            if (mask[j] == '?' ) continue;
            if (start[i + j] != pattern[j]) {
                found = false;
                break;
            }
        }
        if (found) return &start[i];
    }
    return nullptr;
}

/*
 * Find GEngine by scanning the game's main module for the
 * characteristic mov [rip+offset], rax pattern used when GEngine
 * is first assigned.
 *
 * Alternative approach: scan for "48 8B 05" (mov rax, [rip+X])
 * near known string references like "GEngine" or "EngineLoop".
 */
static bool find_gengine()
{
    HMODULE game_module = GetModuleHandleA(NULL);
    if (!game_module) {
        bridge_log("ERROR: GetModuleHandle(NULL) failed");
        return false;
    }

    MODULEINFO mod_info = {};
    /* GetModuleInformation is in psapi.h */
    HMODULE psapi = LoadLibraryA("psapi.dll");
    if (!psapi) {
        bridge_log("ERROR: Failed to load psapi.dll");
        return false;
    }

    typedef BOOL (WINAPI *GetModuleInformationFn)(HANDLE, HMODULE, LPMODULEINFO, DWORD);
    auto pGetModuleInformation = (GetModuleInformationFn)GetProcAddress(
        psapi, "GetModuleInformation");

    if (!pGetModuleInformation) {
        bridge_log("ERROR: GetModuleInformation not found");
        FreeLibrary(psapi);
        return false;
    }

    if (!pGetModuleInformation(
            GetCurrentProcess(), game_module, &mod_info, sizeof(mod_info))) {
        bridge_log("ERROR: GetModuleInformation failed");
        FreeLibrary(psapi);
        return false;
    }
    FreeLibrary(psapi);

    const uint8_t* base = (const uint8_t*)mod_info.lpBaseOfDll;
    size_t mod_size = mod_info.SizeOfImage;
    bridge_log("Game module: base=0x%p, size=%zu MB",
               base, mod_size / (1024 * 1024));

    /*
     * Strategy: Search for the string "GEngine" in the module,
     * then find cross-references to it. Near those xrefs, there
     * will be the actual GEngine global pointer access.
     *
     * Simpler fallback: search for the pattern used in
     * FEngineLoop::PreInit where GEngine is first set:
     *
     *   48 89 05 ?? ?? ?? ??    mov [rip+??], rax
     *   (this stores the newly created engine into GEngine)
     *
     * We look for this pattern near known UE5 strings.
     */

    /* For now, use a simpler approach: scan for a known console
     * variable string "r.Streaming.PoolSize" which is always present
     * in UE5. The CVar system registration code will reference
     * GConsoleManager, and from there we can find GEngine.
     *
     * PLACEHOLDER: In a real implementation, this would use a
     * signature database per-engine-version. For the prototype,
     * we expose a manual offset override via environment variable.
     */

    /* Check for manual GEngine offset (for testing) */
    const char* env_offset = getenv("CAPTUREAI_GENGINE_OFFSET");
    if (env_offset) {
        uintptr_t offset = strtoull(env_offset, NULL, 16);
        g_engine_ptr = *(void**)(base + offset);
        if (g_engine_ptr) {
            bridge_log("GEngine found via env offset 0x%llX -> 0x%p",
                       (unsigned long long)offset, g_engine_ptr);
            g_engine_found = true;
            return true;
        }
        bridge_log("WARNING: Env offset 0x%llX yielded NULL GEngine",
                   (unsigned long long)offset);
    }

    /*
     * Auto-scan: look for "48 8B 0D" (mov rcx, [rip+X]) patterns
     * that load a global pointer, followed by calls to virtual
     * functions. This is a heuristic and may need tuning per game.
     *
     * For the prototype, we skip auto-scan and require either:
     *   1. CAPTUREAI_GENGINE_OFFSET env var, or
     *   2. A separate Cheat Engine script to find and set the offset
     *
     * Full auto-scan implementation is planned for v2.
     */

    bridge_log("WARNING: GEngine auto-scan not yet implemented. "
               "Set CAPTUREAI_GENGINE_OFFSET=<hex> or use CE to find it. "
               "TCP server will start but Exec() calls will be queued.");

    return false;
}

/*
 * Execute a console command via GEngine->Exec().
 *
 * If GEngine is not found yet, the command is logged but not executed.
 * Returns true if the command was sent to the engine.
 */
static bool exec_console_command(const char* cmd)
{
    bridge_log("CMD: %s", cmd);

    if (!g_engine_found || !g_engine_ptr) {
        bridge_log("  (GEngine not available - command logged only)");
        return false;
    }

    /* Convert to wide string for UE5 TCHAR */
    int wlen = MultiByteToWideChar(CP_UTF8, 0, cmd, -1, NULL, 0);
    if (wlen <= 0) {
        bridge_log("  ERROR: UTF-8 to wide conversion failed");
        return false;
    }

    std::vector<wchar_t> wcmd(wlen);
    MultiByteToWideChar(CP_UTF8, 0, cmd, -1, wcmd.data(), wlen);

    /*
     * Call GEngine->Exec(NULL, cmd, *GLog)
     *
     * The Exec function is a virtual method. In UE5, it's typically
     * at vtable index ~100+ (varies by version). For shipped games,
     * we need the exact vtable offset.
     *
     * PROTOTYPE: For now, we use ProcessEvent-style direct call.
     * Full implementation would resolve the vtable offset via
     * pattern scanning the Exec() function body.
     */

    /* TODO: Implement actual Exec() call via vtable
     * For prototype, commands are logged for verification.
     * The actual execution will be implemented once we have
     * the vtable offset scanning working.
     */

    bridge_log("  (Exec call placeholder - vtable resolution pending)");
    return false;
}

/* ── TCP Server ────────────────────────────────────────────────────── */

static std::atomic<bool> g_server_running{false};
static SOCKET g_listen_socket = INVALID_SOCKET;

static void handle_client(SOCKET client_sock)
{
    bridge_log("Client connected");

    char buffer[MAX_CMD_LEN];
    std::string line_buffer;

    while (g_server_running) {
        int received = recv(client_sock, buffer, sizeof(buffer) - 1, 0);
        if (received <= 0) {
            if (received == 0) {
                bridge_log("Client disconnected gracefully");
            } else {
                int err = WSAGetLastError();
                if (err != WSAECONNRESET && err != WSAEINTR) {
                    bridge_log("recv error: %d", err);
                }
            }
            break;
        }

        buffer[received] = '\0';
        line_buffer.append(buffer);

        /* Process complete lines (newline-delimited, same as UUU protocol) */
        size_t pos;
        while ((pos = line_buffer.find('\n')) != std::string::npos) {
            std::string cmd = line_buffer.substr(0, pos);
            line_buffer.erase(0, pos + 1);

            /* Trim \r if present */
            if (!cmd.empty() && cmd.back() == '\r') {
                cmd.pop_back();
            }

            if (cmd.empty()) continue;

            /* Special bridge commands (prefixed with __bridge_) */
            if (cmd == "__bridge_ping") {
                const char* pong = "pong\n";
                send(client_sock, pong, (int)strlen(pong), 0);
                continue;
            }
            if (cmd == "__bridge_status") {
                char status[256];
                snprintf(status, sizeof(status),
                         "engine_found=%d engine_ptr=0x%p\n",
                         (int)g_engine_found.load(),
                         g_engine_ptr);
                send(client_sock, status, (int)strlen(status), 0);
                continue;
            }
            if (cmd.rfind("__bridge_set_offset ", 0) == 0) {
                /* Runtime GEngine offset override:
                 *   __bridge_set_offset 0x12345678
                 */
                const char* hex = cmd.c_str() + 20;
                uintptr_t offset = strtoull(hex, NULL, 16);
                HMODULE game_mod = GetModuleHandleA(NULL);
                const uint8_t* base = (const uint8_t*)game_mod;
                void* ptr = *(void**)(base + offset);
                if (ptr) {
                    g_engine_ptr = ptr;
                    g_engine_found = true;
                    bridge_log("GEngine set via runtime offset 0x%llX -> 0x%p",
                               (unsigned long long)offset, ptr);
                    const char* ok = "ok\n";
                    send(client_sock, ok, (int)strlen(ok), 0);
                } else {
                    bridge_log("WARNING: Offset 0x%llX yielded NULL",
                               (unsigned long long)offset);
                    const char* fail = "null\n";
                    send(client_sock, fail, (int)strlen(fail), 0);
                }
                continue;
            }

            /* Regular console command */
            exec_console_command(cmd.c_str());
        }
    }

    closesocket(client_sock);
    bridge_log("Client handler exited");
}

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

    /* Allow port reuse (in case of quick restart) */
    int opt = 1;
    setsockopt(g_listen_socket, SOL_SOCKET, SO_REUSEADDR,
               (const char*)&opt, sizeof(opt));

    struct sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");  /* localhost only */
    addr.sin_port = htons((u_short)port);

    if (bind(g_listen_socket, (struct sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) {
        bridge_log("ERROR: bind() failed on port %d: %d", port, WSAGetLastError());
        closesocket(g_listen_socket);
        g_listen_socket = INVALID_SOCKET;
        WSACleanup();
        return;
    }

    if (listen(g_listen_socket, 2) == SOCKET_ERROR) {
        bridge_log("ERROR: listen() failed: %d", WSAGetLastError());
        closesocket(g_listen_socket);
        g_listen_socket = INVALID_SOCKET;
        WSACleanup();
        return;
    }

    g_server_running = true;
    bridge_log("TCP console server listening on 127.0.0.1:%d", port);

    while (g_server_running) {
        /* Accept with timeout so we can check g_server_running */
        fd_set read_fds;
        FD_ZERO(&read_fds);
        FD_SET(g_listen_socket, &read_fds);

        struct timeval tv;
        tv.tv_sec = 1;
        tv.tv_usec = 0;

        int sel = select(0, &read_fds, NULL, NULL, &tv);
        if (sel > 0) {
            SOCKET client = accept(g_listen_socket, NULL, NULL);
            if (client != INVALID_SOCKET) {
                std::thread(handle_client, client).detach();
            }
        }
    }

    closesocket(g_listen_socket);
    g_listen_socket = INVALID_SOCKET;
    WSACleanup();
    bridge_log("TCP server stopped");
}

/* ── DLL Entry Point ───────────────────────────────────────────────── */

static std::thread g_server_thread;

static void startup()
{
    /* Open log file next to the DLL */
    char dll_path[MAX_PATH];
    HMODULE h_self = NULL;
    GetModuleHandleExA(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCSTR)&startup, &h_self);
    GetModuleFileNameA(h_self, dll_path, MAX_PATH);

    std::string log_path(dll_path);
    size_t last_dot = log_path.rfind('.');
    if (last_dot != std::string::npos) {
        log_path = log_path.substr(0, last_dot);
    }
    log_path += ".log";

    g_logfile = fopen(log_path.c_str(), "w");
    bridge_log("captureAIshi bridge v0.1 starting...");
    bridge_log("Log file: %s", log_path.c_str());

    /* Try to find GEngine */
    find_gengine();

    /* Read port from environment (default 9998) */
    int port = DEFAULT_PORT;
    const char* env_port = getenv("CAPTUREAI_BRIDGE_PORT");
    if (env_port) {
        port = atoi(env_port);
        if (port <= 0 || port > 65535) port = DEFAULT_PORT;
    }

    /* Start TCP server */
    g_server_thread = std::thread(tcp_server_thread, port);
}

static void shutdown()
{
    bridge_log("Bridge shutting down...");
    g_server_running = false;

    /* Close listen socket to unblock accept() */
    if (g_listen_socket != INVALID_SOCKET) {
        closesocket(g_listen_socket);
    }

    if (g_server_thread.joinable()) {
        g_server_thread.join();
    }

    if (g_logfile) {
        bridge_log("Bridge shutdown complete");
        fclose(g_logfile);
        g_logfile = nullptr;
    }
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID reserved)
{
    switch (reason) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hModule);
        /* Defer startup to a new thread to avoid DllMain deadlocks */
        std::thread(startup).detach();
        break;
    case DLL_PROCESS_DETACH:
        shutdown();
        break;
    }
    return TRUE;
}
