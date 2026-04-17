/*
 * camera_intercept.h -- IGCS-style inline code patch for camera writes.
 *
 * INCLUDED FROM console_server.h ONLY. Depends on pattern_scan.h and
 * ue5_engine.h being included earlier in the same translation unit.
 *
 * Problem:
 *   UE5 APlayerCameraManager::UpdateCamera() writes the player-follow
 *   position into FMinimalViewInfo every game frame. Our 1000 Hz tick
 *   races against it and usually loses.
 *
 * Solution (Otis_Inf / IGCS approach for UE4/UE5 games):
 *   Patch the game's own MOV instructions that write to the POV struct.
 *   Keep the FName / GUObjectArray discovery pipeline intact -- we still
 *   find CameraManager / UWorld / Actors through that. This module only
 *   replaces the "override" mechanism.
 *
 * Two states per installed site:
 *   - "pass"  : original bytes in place; game updates camera normally.
 *   - "nop"   : patched with 0x90s; game write becomes a no-op. Our
 *               __cam_mem_write / path playback keeps the values alive.
 *
 * Scope:
 *   This is the infrastructure layer. AOB patterns are supplied per
 *   game (via TCP command or config). Auto-discovery of the write
 *   instruction from known cam_pov offsets is a follow-up.
 *
 * ASCII only (MSVC C4819 compliance).
 */

#ifndef CAPTUREAI_CAMERA_INTERCEPT_H
#define CAPTUREAI_CAMERA_INTERCEPT_H

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <vector>
#include <mutex>

/* Forward-declare; defined in bridge_log_adapter in console_server.h */
extern void bridge_log(const char* fmt, ...);

/* -- Configuration ---------------------------------------------------- */

/* Maximum bytes a single intercept can cover. A typical UE5 LWC camera
 * write block (movsd x / movsd y / movsd z + a few mov eax) fits in
 * well under 64 bytes. */
static const size_t CAM_INTERCEPT_MAX_SIZE = 64;

/* Hard cap on installed sites. Prevents runaway memory if someone spams
 * __cam_intercept_install_aob. */
static const size_t CAM_INTERCEPT_MAX_SITES = 16;

/* -- State ------------------------------------------------------------ */

struct CamInterceptSite {
    uint8_t*  addr;                                 /* patched location  */
    size_t    size;                                 /* byte count        */
    uint8_t   orig[CAM_INTERCEPT_MAX_SIZE];         /* saved bytes       */
    uint8_t   nops[CAM_INTERCEPT_MAX_SIZE];         /* 0x90 padding      */
    bool      nopped;                               /* current state     */
    char      name[64];                             /* label for logs    */
};

static std::vector<CamInterceptSite> g_cam_sites;
static std::mutex                     g_cam_sites_mutex;

/* -- Low-level: page protection + code write ------------------------- */

static bool cam_patch_write(uint8_t* addr, const uint8_t* data, size_t n)
{
    DWORD old_prot = 0;
    if (!VirtualProtect(addr, n, PAGE_EXECUTE_READWRITE, &old_prot)) {
        bridge_log("[intercept] VirtualProtect(0x%p, %zu) failed: %lu",
                   addr, n, GetLastError());
        return false;
    }
    memcpy(addr, data, n);
    DWORD tmp = 0;
    VirtualProtect(addr, n, old_prot, &tmp);
    FlushInstructionCache(GetCurrentProcess(), addr, n);
    return true;
}

/* -- AOB parsing ------------------------------------------------------ */

/*
 * Parse "F2 0F 11 ?? 80 04 00 00" into bytes[] + mask[] (mask: 'x'/'?').
 * Returns token count on success, -1 on malformed input.
 * Tokens are space-separated; each is 2 hex chars or "??".
 */
static int cam_parse_aob(const char* hex, uint8_t* bytes, char* mask,
                         int max_len)
{
    int count = 0;
    const char* p = hex;
    while (*p && count < max_len) {
        /* skip whitespace and commas */
        while (*p == ' ' || *p == '\t' || *p == ',') p++;
        if (!*p) break;
        if (p[0] == '?' && p[1] == '?') {
            bytes[count] = 0x00;
            mask[count] = '?';
            p += 2;
        } else {
            /* Expect 2 hex chars */
            auto hex_digit = [](char c) -> int {
                if (c >= '0' && c <= '9') return c - '0';
                if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
                if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
                return -1;
            };
            int hi = hex_digit(p[0]);
            int lo = hex_digit(p[1]);
            if (hi < 0 || lo < 0) return -1;
            bytes[count] = (uint8_t)((hi << 4) | lo);
            mask[count] = 'x';
            p += 2;
        }
        count++;
    }
    mask[count] = '\0';
    return count;
}

/* -- Install / set mode ---------------------------------------------- */

static bool cam_intercept_install_addr_locked(uint8_t* addr, size_t size,
                                               const char* name)
{
    if (!addr) {
        bridge_log("[intercept] install: null address");
        return false;
    }
    if (size == 0 || size > CAM_INTERCEPT_MAX_SIZE) {
        bridge_log("[intercept] install: bad size %zu (max %zu)",
                   size, CAM_INTERCEPT_MAX_SIZE);
        return false;
    }
    if (g_cam_sites.size() >= CAM_INTERCEPT_MAX_SITES) {
        bridge_log("[intercept] install: site cap %zu reached",
                   CAM_INTERCEPT_MAX_SITES);
        return false;
    }
    /* Refuse to re-install the same address */
    for (const auto& s : g_cam_sites) {
        if (s.addr == addr) {
            bridge_log("[intercept] install: 0x%p already has a site", addr);
            return false;
        }
    }

    CamInterceptSite site = {};
    site.addr = addr;
    site.size = size;
    site.nopped = false;
    if (name && *name)
        snprintf(site.name, sizeof(site.name), "%s", name);
    else
        snprintf(site.name, sizeof(site.name), "site#%zu", g_cam_sites.size());

    /* Save original bytes (readable code section; no SEH expected but
     * we still validate the address is in a committed page). */
    MEMORY_BASIC_INFORMATION mbi = {};
    if (!VirtualQuery(addr, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT) {
        bridge_log("[intercept] install: 0x%p not committed", addr);
        return false;
    }
    memcpy(site.orig, addr, size);
    memset(site.nops, 0x90, size);

    g_cam_sites.push_back(site);
    bridge_log("[intercept] installed '%s' at 0x%p (%zu bytes, mode=pass)",
               site.name, addr, size);
    return true;
}

static bool cam_intercept_install_addr(uint8_t* addr, size_t size,
                                        const char* name)
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    return cam_intercept_install_addr_locked(addr, size, name);
}

/* AOB scan in main module; install at first match. */
static bool cam_intercept_install_aob(const char* aob_hex, size_t size,
                                       const char* name)
{
    uint8_t bytes[128];
    char    mask[129];
    int pat_len = cam_parse_aob(aob_hex, bytes, mask, 128);
    if (pat_len <= 0) {
        bridge_log("[intercept] install_aob: malformed pattern");
        return false;
    }
    const uint8_t* match = scan_main_module(bytes, mask, (size_t)pat_len);
    if (!match) {
        bridge_log("[intercept] install_aob: pattern not found (%d tokens)",
                   pat_len);
        return false;
    }
    bridge_log("[intercept] install_aob: match at 0x%p (pattern %d tokens)",
               (void*)match, pat_len);
    return cam_intercept_install_addr((uint8_t*)match, size, name);
}

/* Switch all sites to nop (true) or pass-through (false). */
static bool cam_intercept_set_nop_all(bool nop)
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    int ok_count = 0, fail_count = 0;
    for (auto& s : g_cam_sites) {
        if (s.nopped == nop) continue;
        const uint8_t* data = nop ? s.nops : s.orig;
        if (cam_patch_write(s.addr, data, s.size)) {
            s.nopped = nop;
            ok_count++;
            bridge_log("[intercept] '%s' -> %s", s.name, nop ? "nop" : "pass");
        } else {
            fail_count++;
        }
    }
    bridge_log("[intercept] set_nop_all(%d): %d ok, %d failed, total sites %zu",
               (int)nop, ok_count, fail_count, g_cam_sites.size());
    return fail_count == 0;
}

/* Restore original bytes everywhere and clear the list. */
static void cam_intercept_uninstall_all()
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    for (auto& s : g_cam_sites) {
        if (s.nopped)
            cam_patch_write(s.addr, s.orig, s.size);
    }
    bridge_log("[intercept] uninstalled %zu sites", g_cam_sites.size());
    g_cam_sites.clear();
}

/* -- Query ----------------------------------------------------------- */

static size_t cam_intercept_count()
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    return g_cam_sites.size();
}

/* Format current sites for TCP response. */
static std::string cam_intercept_list()
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    std::string out;
    char buf[256];
    for (size_t i = 0; i < g_cam_sites.size(); i++) {
        const auto& s = g_cam_sites[i];
        snprintf(buf, sizeof(buf),
                 "[%zu] %s addr=0x%p size=%zu mode=%s\n",
                 i, s.name, s.addr, s.size, s.nopped ? "nop" : "pass");
        out += buf;
    }
    if (out.empty()) out = "(no sites)\n";
    return out;
}

/* True if at least one site is installed and currently in nop mode. */
static bool cam_intercept_any_nopped()
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    for (const auto& s : g_cam_sites)
        if (s.nopped) return true;
    return false;
}

#endif /* CAPTUREAI_CAMERA_INTERCEPT_H */
