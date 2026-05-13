/*
 * camera_intercept.h -- IGCS-style inline code patch for camera writes.
 *
 * INCLUDED FROM bridge.cpp. Depends on pattern_scan.h being included
 * earlier in the same translation unit (bridge.cpp already does this).
 *
 * Three modes per site:
 *   - PASS    : original bytes in place; game updates camera normally.
 *   - NOP     : 0x90 fill. Game's write is a no-op; external writes persist.
 *   - CAPTURE : 14-byte `jmp qword ptr [rip+0]` to a VirtualAlloc'd asm stub
 *               that snapshots the base-register (rbx/rsi/rdi/r8..r15) to
 *               g_cap_addr[slot] and then jumps past the original block.
 *               Requires site.size >= 14.
 *
 * The stub is assembled at runtime from the ModRM byte of the first
 * instruction in the AOB. That byte tells us which register holds the
 * camera struct pointer (rm field + REX.B).
 *
 * ASCII only (MSVC C4819 compliance).
 */

#ifndef CAPTUREAI_CAMERA_INTERCEPT_H
#define CAPTUREAI_CAMERA_INTERCEPT_H

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <vector>
#include <mutex>

extern void bridge_log(const char* fmt, ...);

/* -- Configuration ---------------------------------------------------- */

static const size_t CAM_INTERCEPT_MAX_SIZE  = 64;
static const size_t CAM_INTERCEPT_MAX_SITES = 16;
static const size_t CAM_STUB_MAX_SIZE       = 64;   /* our stub is ~29 bytes */

/* -- Mode ------------------------------------------------------------- */

enum CamMode {
    CAM_MODE_PASS    = 0,
    CAM_MODE_NOP     = 1,
    CAM_MODE_CAPTURE = 2,
};

static const char* cam_mode_str(int m) {
    switch (m) {
        case CAM_MODE_PASS:    return "pass";
        case CAM_MODE_NOP:     return "nop";
        case CAM_MODE_CAPTURE: return "capture";
        default:               return "?";
    }
}

/* -- State ------------------------------------------------------------ */

struct CamInterceptSite {
    uint8_t*  addr;                                  /* patched location   */
    size_t    size;                                  /* byte count         */
    uint8_t   orig[CAM_INTERCEPT_MAX_SIZE];          /* saved original     */
    uint8_t   nops[CAM_INTERCEPT_MAX_SIZE];          /* 0x90 fill          */
    uint8_t   patch[CAM_INTERCEPT_MAX_SIZE];         /* jmp-to-stub + NOPs */
    int       mode;                                  /* CAM_MODE_*         */
    int       base_reg;                              /* 0..15 or -1        */
    void*     stub;                                  /* VirtualAlloc'd code*/
    int       slot;                                  /* cap-addr index     */
    char      name[64];
};

static std::vector<CamInterceptSite> g_cam_sites;
static std::mutex                     g_cam_sites_mutex;

/* Stubs write captured base-register values here. 8-byte aligned.
 * Indexed by site.slot (0..CAM_INTERCEPT_MAX_SITES-1). */
static uint64_t g_cap_addr[CAM_INTERCEPT_MAX_SITES] = {0};

/* -- Low-level: page protection + code write ------------------------- */

static const DWORD CAM_READABLE_MASK =
    PAGE_READONLY | PAGE_READWRITE |
    PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
    PAGE_EXECUTE_WRITECOPY | PAGE_WRITECOPY;

static bool cam_seh_memcpy(void* dst, const void* src, size_t n)
{
    __try {
        memcpy(dst, src, n);
        return true;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

/* Suspend all threads in this process except our own.
 * Returns their handles so cam_resume_others() can wake them. */
static std::vector<HANDLE> cam_suspend_others()
{
    std::vector<HANDLE> out;
    DWORD me = GetCurrentThreadId();
    DWORD pid = GetCurrentProcessId();
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snap == INVALID_HANDLE_VALUE) return out;
    THREADENTRY32 te = {};
    te.dwSize = sizeof(te);
    if (Thread32First(snap, &te)) {
        do {
            if (te.th32OwnerProcessID == pid && te.th32ThreadID != me) {
                HANDLE h = OpenThread(THREAD_SUSPEND_RESUME, FALSE,
                                      te.th32ThreadID);
                if (h) {
                    SuspendThread(h);
                    out.push_back(h);
                }
            }
        } while (Thread32Next(snap, &te));
    }
    CloseHandle(snap);
    return out;
}

static void cam_resume_others(std::vector<HANDLE>& handles)
{
    for (HANDLE h : handles) {
        ResumeThread(h);
        CloseHandle(h);
    }
    handles.clear();
}

static bool cam_patch_write(uint8_t* addr, const uint8_t* data, size_t n)
{
    /* Suspend game threads while patching executable code.
     * x64 does not guarantee atomicity of multi-byte writes, and the
     * game thread may be executing the instruction we are replacing. */
    auto suspended = cam_suspend_others();

    /* CRITICAL: No bridge_log / OutputDebugStringA between suspend and
     * resume -- DBWIN / CSRSS mutex may be held by one of the suspended
     * threads, which would deadlock the entire process. Stash any error
     * into a stack buffer and emit it after resume. */
    char err[256];
    err[0] = '\0';
    bool ok = true;

    DWORD old_prot = 0;
    if (!VirtualProtect(addr, n, PAGE_EXECUTE_READWRITE, &old_prot)) {
        snprintf(err, sizeof(err),
                 "[intercept] VirtualProtect(0x%p, %zu) failed: %lu",
                 addr, n, (unsigned long)GetLastError());
        ok = false;
    } else {
        if (!cam_seh_memcpy(addr, data, n)) {
            snprintf(err, sizeof(err),
                     "[intercept] memcpy faulted writing %zu bytes at 0x%p "
                     "(AC may have blocked VirtualProtect)", n, addr);
            ok = false;
        }
        DWORD tmp = 0;
        VirtualProtect(addr, n, old_prot, &tmp);
        FlushInstructionCache(GetCurrentProcess(), addr, n);
    }

    cam_resume_others(suspended);

    if (err[0]) bridge_log("%s", err);
    return ok;
}

/* -- AOB parsing ------------------------------------------------------ */

static int cam_parse_aob(const char* hex, uint8_t* bytes, char* mask,
                         int max_len)
{
    int count = 0;
    const char* p = hex;
    while (*p && count < max_len) {
        while (*p == ' ' || *p == '\t' || *p == ',') p++;
        if (!*p) break;
        if (p[0] == '?' && p[1] == '?') {
            bytes[count] = 0x00;
            mask[count] = '?';
            p += 2;
        } else {
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

/* -- ModRM -> base register ------------------------------------------- */

/*
 * Walk the first instruction in an AOB: skip SSE/size prefix, optional
 * REX, opcode, read ModRM. Return the base register (rm + REX.B<<3).
 * Returns -1 if we don't recognize the opcode or ModRM is wildcarded or
 * addressing doesn't use [reg + disp] (i.e. mod==11 or rm==4 SIB).
 *
 * Supported opcodes:
 *   0F 11 /r          movups/movaps store
 *   F2 0F 11 /r       movsd  store
 *   F3 0F 11 /r       movss  store
 *   89 /r             mov r/m16/32/64, r (used by UE3 Batman)
 */
static int cam_parse_base_reg(const uint8_t* bytes, const char* mask,
                               int pat_len)
{
    int i = 0;
    uint8_t rex = 0;

    if (i >= pat_len || mask[i] != 'x') return -1;
    if (bytes[i] == 0xF2 || bytes[i] == 0xF3 || bytes[i] == 0x66) i++;

    if (i < pat_len && mask[i] == 'x' &&
        (bytes[i] & 0xF0) == 0x40) {
        rex = bytes[i];
        i++;
    }

    if (i >= pat_len || mask[i] != 'x') return -1;
    uint8_t op1 = bytes[i++];

    if (op1 == 0x0F) {
        if (i >= pat_len || mask[i] != 'x') return -1;
        uint8_t op2 = bytes[i++];
        if (op2 != 0x11 && op2 != 0x29) return -1; /* movups/movaps store */
    } else if (op1 != 0x89) {
        return -1;
    }

    if (i >= pat_len || mask[i] != 'x') return -1;
    uint8_t modrm = bytes[i];
    uint8_t mod = (modrm >> 6) & 0x3;
    uint8_t rm  = modrm & 0x7;

    if (mod == 0x3) return -1; /* register-register, no memory */
    if (rm  == 0x4) return -1; /* SIB -- unsupported */
    if (mod == 0x0 && rm == 0x5) return -1; /* RIP-relative, no base */

    int base = rm | ((rex & 0x1) << 3);
    return base;
}

/* -- Capture stub assembly ------------------------------------------- */

/*
 * Assemble a 29-byte capture stub into `out`.
 * Stub: push rax / mov rax,<base> / mov [g_cap_addr+slot*8],rax / pop rax
 *       / jmp qword ptr [rip+0]; dq continue
 * Returns bytes written, or 0 on failure.
 */
static size_t cam_build_capture_stub(uint8_t* out, size_t out_cap,
                                      int base_reg,
                                      uint64_t cap_target_addr,
                                      uint64_t continue_addr)
{
    if (out_cap < 29) return 0;
    if (base_reg < 0 || base_reg > 15) return 0;

    size_t n = 0;
    out[n++] = 0x50;                                 /* push rax */

    /* mov rax, <base_reg>  (REX.W | REX.R? | 89 | ModRM) */
    out[n++] = (base_reg >= 8) ? 0x4C : 0x48;
    out[n++] = 0x89;
    out[n++] = (uint8_t)(0xC0 | ((base_reg & 7) << 3));

    /* mov [abs64], rax   (48 A3 <8 bytes>) */
    out[n++] = 0x48;
    out[n++] = 0xA3;
    memcpy(out + n, &cap_target_addr, 8); n += 8;

    out[n++] = 0x58;                                 /* pop rax */

    /* jmp qword ptr [rip+0] */
    out[n++] = 0xFF;
    out[n++] = 0x25;
    out[n++] = 0x00; out[n++] = 0x00;
    out[n++] = 0x00; out[n++] = 0x00;
    memcpy(out + n, &continue_addr, 8); n += 8;

    return n;
}

static void* cam_alloc_stub_page(size_t n_bytes)
{
    void* p = VirtualAlloc(NULL, 4096, MEM_COMMIT | MEM_RESERVE,
                           PAGE_EXECUTE_READWRITE);
    if (!p) {
        bridge_log("[intercept] VirtualAlloc(stub) failed: %lu",
                   GetLastError());
        return NULL;
    }
    /* Fill with INT3s so stray jumps die loudly. */
    memset(p, 0xCC, 4096);
    (void)n_bytes;
    return p;
}

/* Build the 14-byte `jmp qword ptr [rip+0]; dq stub` patch, pad rest w/ NOP. */
static void cam_build_capture_patch(uint8_t* out, size_t size, uint64_t stub)
{
    out[0] = 0xFF; out[1] = 0x25;
    out[2] = 0x00; out[3] = 0x00; out[4] = 0x00; out[5] = 0x00;
    memcpy(out + 6, &stub, 8);
    if (size > 14) memset(out + 14, 0x90, size - 14);
}

/* -- Install ---------------------------------------------------------- */

static bool cam_intercept_install_addr_locked(uint8_t* addr, size_t size,
                                               const char* name)
{
    if (!addr) {
        bridge_log("[intercept] install: null address"); return false;
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
    for (const auto& s : g_cam_sites) {
        if (s.addr == addr) {
            bridge_log("[intercept] install: 0x%p already has a site", addr);
            return false;
        }
    }

    CamInterceptSite site = {};
    site.addr = addr;
    site.size = size;
    site.mode = CAM_MODE_PASS;
    site.base_reg = -1;
    site.stub = NULL;
    site.slot = (int)g_cam_sites.size();
    if (name && *name)
        snprintf(site.name, sizeof(site.name), "%s", name);
    else
        snprintf(site.name, sizeof(site.name), "site#%zu", g_cam_sites.size());

    MEMORY_BASIC_INFORMATION mbi = {};
    if (!VirtualQuery(addr, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT) {
        bridge_log("[intercept] install: 0x%p not committed", addr);
        return false;
    }
    if (!(mbi.Protect & CAM_READABLE_MASK)) {
        bridge_log("[intercept] install: 0x%p protect=0x%lx not readable",
                   addr, (unsigned long)mbi.Protect);
        return false;
    }
    /* Reject if addr+size crosses into another page region. */
    if ((uint8_t*)addr + size >
        (uint8_t*)mbi.BaseAddress + mbi.RegionSize) {
        bridge_log("[intercept] install: 0x%p + %zu crosses page boundary "
                   "(region ends at 0x%p)", addr, size,
                   (uint8_t*)mbi.BaseAddress + mbi.RegionSize);
        return false;
    }
    if (!cam_seh_memcpy(site.orig, addr, size)) {
        bridge_log("[intercept] install: AV reading %zu bytes at 0x%p",
                   size, addr);
        return false;
    }
    memset(site.nops, 0x90, size);
    memset(site.patch, 0x90, size);  /* will be overwritten if CAPTURE used */

    g_cap_addr[site.slot] = 0;
    g_cam_sites.push_back(site);
    bridge_log("[intercept] installed '%s' at 0x%p (%zu bytes, slot=%d, mode=pass)",
               site.name, addr, size, site.slot);
    return true;
}

static bool cam_intercept_install_addr(uint8_t* addr, size_t size,
                                        const char* name)
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    return cam_intercept_install_addr_locked(addr, size, name);
}

/* AOB scan in main module; install at Nth match. Also parses ModRM
 * for future capture mode. */
static bool cam_intercept_install_aob(const char* aob_hex, size_t size,
                                       const char* name, int occurrence = 1)
{
    uint8_t bytes[128];
    char    mask[129];
    int pat_len = cam_parse_aob(aob_hex, bytes, mask, 128);
    if (pat_len <= 0) {
        bridge_log("[intercept] install_aob: malformed pattern");
        return false;
    }
    const uint8_t* match = scan_main_module_nth(bytes, mask, (size_t)pat_len,
                                                occurrence);
    if (!match) {
        bridge_log("[intercept] install_aob: pattern not found (tokens=%d occ=%d)",
                   pat_len, occurrence);
        return false;
    }
    int base_reg = cam_parse_base_reg(bytes, mask, pat_len);
    bridge_log("[intercept] install_aob: match 0x%p (pat=%d bytes, base_reg=%d, occ=%d)",
               (void*)match, pat_len, base_reg, occurrence);

    bool ok = cam_intercept_install_addr((uint8_t*)match, size, name);
    if (!ok) return false;

    /* Patch base_reg into the last installed site (we just pushed_back). */
    {
        std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
        if (!g_cam_sites.empty()) {
            g_cam_sites.back().base_reg = base_reg;
        }
    }
    return true;
}

/* -- Mode switching --------------------------------------------------- */

/* Ensure site has a valid stub (allocating + building if needed). */
static bool cam_ensure_stub(CamInterceptSite& s)
{
    if (s.stub) return true;
    if (s.base_reg < 0) {
        bridge_log("[intercept] '%s' base_reg unknown; capture mode unavailable",
                   s.name);
        return false;
    }
    if (s.size < 14) {
        bridge_log("[intercept] '%s' size=%zu < 14; capture mode needs 14 bytes "
                   "for absolute jmp", s.name, s.size);
        return false;
    }
    void* page = cam_alloc_stub_page(29);
    if (!page) return false;

    uint8_t stub[64] = {};
    uint64_t cap_target = (uint64_t)(uintptr_t)&g_cap_addr[s.slot];
    uint64_t cont       = (uint64_t)(uintptr_t)(s.addr + s.size);
    size_t stub_n = cam_build_capture_stub(stub, sizeof(stub),
                                           s.base_reg, cap_target, cont);
    if (stub_n == 0) {
        VirtualFree(page, 0, MEM_RELEASE);
        return false;
    }
    memcpy(page, stub, stub_n);
    FlushInstructionCache(GetCurrentProcess(), page, stub_n);

    s.stub = page;
    cam_build_capture_patch(s.patch, s.size, (uint64_t)(uintptr_t)page);
    bridge_log("[intercept] '%s' stub built at 0x%p (%zu bytes, base_reg=%d, "
               "cap_target=0x%llX, continue=0x%llX)",
               s.name, page, stub_n, s.base_reg,
               (unsigned long long)cap_target,
               (unsigned long long)cont);
    return true;
}

static bool cam_set_mode_one(CamInterceptSite& s, int new_mode)
{
    if (s.mode == new_mode) return true;

    const uint8_t* src = s.orig;
    if (new_mode == CAM_MODE_NOP) {
        src = s.nops;
    } else if (new_mode == CAM_MODE_CAPTURE) {
        if (!cam_ensure_stub(s)) {
            bridge_log("[intercept] '%s' capture setup failed", s.name);
            return false;
        }
        src = s.patch;
    }

    if (!cam_patch_write(s.addr, src, s.size)) return false;
    bridge_log("[intercept] '%s' %s -> %s",
               s.name, cam_mode_str(s.mode), cam_mode_str(new_mode));
    s.mode = new_mode;
    return true;
}

static bool cam_intercept_set_mode_all(int new_mode)
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    int ok = 0, fail = 0;
    for (auto& s : g_cam_sites) {
        if (cam_set_mode_one(s, new_mode)) ok++;
        else fail++;
    }
    bridge_log("[intercept] set_mode_all(%s): %d ok, %d failed",
               cam_mode_str(new_mode), ok, fail);
    return fail == 0;
}

/* Legacy API kept for existing TCP commands (__cam_intercept_nop/pass). */
static bool cam_intercept_set_nop_all(bool nop)
{
    return cam_intercept_set_mode_all(nop ? CAM_MODE_NOP : CAM_MODE_PASS);
}

/* -- Uninstall -------------------------------------------------------- */

static void cam_intercept_uninstall_all()
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    for (auto& s : g_cam_sites) {
        if (s.mode != CAM_MODE_PASS)
            cam_patch_write(s.addr, s.orig, s.size);
        if (s.stub) {
            VirtualFree(s.stub, 0, MEM_RELEASE);
            s.stub = NULL;
        }
        if (s.slot >= 0 && s.slot < (int)CAM_INTERCEPT_MAX_SITES)
            g_cap_addr[s.slot] = 0;
    }
    bridge_log("[intercept] uninstalled %zu sites", g_cam_sites.size());
    g_cam_sites.clear();
}

/* -- Query ------------------------------------------------------------ */

static size_t cam_intercept_count()
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    return g_cam_sites.size();
}

static std::string cam_intercept_list()
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    std::string out;
    char buf[320];
    for (size_t i = 0; i < g_cam_sites.size(); i++) {
        const auto& s = g_cam_sites[i];
        snprintf(buf, sizeof(buf),
                 "[%zu] %s addr=0x%p size=%zu mode=%s base_reg=%d "
                 "slot=%d captured=0x%llX\n",
                 i, s.name, s.addr, s.size, cam_mode_str(s.mode),
                 s.base_reg, s.slot,
                 (unsigned long long)g_cap_addr[s.slot]);
        out += buf;
    }
    if (out.empty()) out = "(no sites)\n";
    return out;
}

static bool cam_intercept_any_nopped()
{
    std::lock_guard<std::mutex> lk(g_cam_sites_mutex);
    for (const auto& s : g_cam_sites)
        if (s.mode == CAM_MODE_NOP || s.mode == CAM_MODE_CAPTURE) return true;
    return false;
}

/* Retrieve captured base register value for a given slot.
 * Returns 0 if slot out of range or nothing captured yet. */
static uint64_t cam_intercept_get_captured(int slot)
{
    if (slot < 0 || slot >= (int)CAM_INTERCEPT_MAX_SITES) return 0;
    return g_cap_addr[slot];
}

/* -- Manual memory write --------------------------------------------- *
 *
 * cam_mem_poke(addr, offset, type, value):
 *   Write a value into the camera struct at the given offset. Wraps in
 *   SEH so a bogus addr/offset doesn't take the DLL down.
 *
 *   type: 0=f32, 1=f64, 2=i32, 3=u32
 */
static bool cam_mem_poke(uint64_t addr, uint64_t offset, int type,
                         uint64_t value_bits)
{
    if (addr == 0) return false;
    uint8_t* target = (uint8_t*)(uintptr_t)addr + offset;
    __try {
        switch (type) {
            case 0: { /* f32 */
                uint32_t v = (uint32_t)(value_bits & 0xFFFFFFFFu);
                *(uint32_t*)target = v;
                return true;
            }
            case 1: /* f64 */
                *(uint64_t*)target = value_bits;
                return true;
            case 2: /* i32 */
            case 3: /* u32 */
                *(uint32_t*)target = (uint32_t)(value_bits & 0xFFFFFFFFu);
                return true;
            default:
                return false;
        }
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

/* Read a typed value from addr+offset. Returns true and fills value_bits on
 * success. Wraps in SEH so a bogus address doesn't crash the DLL. */
static bool cam_mem_peek(uint64_t addr, uint64_t offset, int type,
                         uint64_t* value_bits)
{
    if (addr == 0 || !value_bits) return false;
    const uint8_t* src = (const uint8_t*)(uintptr_t)addr + offset;
    __try {
        switch (type) {
            case 0: { /* f32 */
                uint32_t v = *(const uint32_t*)src;
                *value_bits = v;
                return true;
            }
            case 1: /* f64 */
                *value_bits = *(const uint64_t*)src;
                return true;
            case 2: /* i32 */
            case 3: /* u32 */
                *value_bits = *(const uint32_t*)src;
                return true;
            default:
                return false;
        }
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

#endif /* CAPTUREAI_CAMERA_INTERCEPT_H */
