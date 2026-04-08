/*
 * pattern_scan.h -- Memory pattern scanner for UE5 games
 *
 * Scans game module memory for byte patterns with wildcard support.
 * Used to locate GEngine, camera structs, and other engine globals
 * without hardcoded offsets.
 *
 * ASCII only (MSVC C4819 compliance).
 */

#ifndef CAPTUREAI_PATTERN_SCAN_H
#define CAPTUREAI_PATTERN_SCAN_H

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <psapi.h>
#include <cstdint>
#include <vector>
#include <string>

#pragma comment(lib, "psapi.lib")

/* -- Module info helper -------------------------------------------- */

struct ModuleRegion {
    const uint8_t* base;
    size_t         size;
};

/*
 * Get the main game module base and size.
 *
 * Primary: GetModuleInformation (PSAPI). May return SizeOfImage=0
 * on some systems or when called very early in process startup.
 *
 * Fallback: Parse the PE header directly to read SizeOfImage from
 * IMAGE_OPTIONAL_HEADER. This always works as long as the module
 * handle is valid, since the PE header is mapped at the base address.
 */
static inline size_t pe_get_image_size(const uint8_t* base)
{
    /* DOS header: e_lfanew at offset 0x3C gives PE header offset */
    if (base[0] != 'M' || base[1] != 'Z') return 0;
    int32_t pe_offset = *(const int32_t*)(base + 0x3C);
    if (pe_offset < 0 || pe_offset > 0x1000) return 0;

    const uint8_t* pe = base + pe_offset;
    /* PE signature: "PE\0\0" */
    if (pe[0] != 'P' || pe[1] != 'E' || pe[2] != 0 || pe[3] != 0)
        return 0;

    /* COFF header is 20 bytes after PE sig, Optional header follows.
     * For PE32+: SizeOfImage is at Optional header offset +0x38 (56). */
    const uint8_t* opt = pe + 4 + 20;  /* skip PE sig + COFF header */
    uint16_t magic = *(const uint16_t*)opt;

    if (magic == 0x20B) {
        /* PE32+ (64-bit) */
        return *(const uint32_t*)(opt + 56);
    } else if (magic == 0x10B) {
        /* PE32 (32-bit) */
        return *(const uint32_t*)(opt + 56);
    }
    return 0;
}

static inline bool get_main_module(ModuleRegion& out)
{
    HMODULE mod = GetModuleHandleA(NULL);
    if (!mod) return false;

    out.base = (const uint8_t*)mod;
    out.size = 0;

    /* Try PSAPI first */
    MODULEINFO info = {};
    if (GetModuleInformation(GetCurrentProcess(), mod, &info, sizeof(info))) {
        out.base = (const uint8_t*)info.lpBaseOfDll;
        out.size = info.SizeOfImage;
    }

    /* Fallback: read PE header if PSAPI returned 0 */
    if (out.size == 0) {
        out.size = pe_get_image_size(out.base);
    }

    return out.size > 0;
}

/* -- Readable region enumeration ----------------------------------- */

/*
 * Build a list of readable byte ranges within [base, base+size).
 * Uses VirtualQuery to skip PAGE_NOACCESS / PAGE_GUARD / uncommitted
 * pages.  A 302 MB module may have holes if sections are sparsely
 * mapped or the game's DRM modified page protections.
 */
struct ReadableRange {
    size_t offset;   /* relative to module base */
    size_t length;
};

static std::vector<ReadableRange> g_cached_ranges;
static const uint8_t* g_cached_base = nullptr;
static size_t         g_cached_size = 0;

/*
 * Get readable ranges for a module. Cached after first call for
 * the same (base, size) to avoid repeated VirtualQuery storms
 * (302 MB module = ~77000 VirtualQuery calls per invocation).
 */
static inline const std::vector<ReadableRange>& get_readable_ranges(
    const uint8_t* base, size_t size)
{
    if (base == g_cached_base && size == g_cached_size &&
        !g_cached_ranges.empty())
        return g_cached_ranges;

    g_cached_ranges.clear();
    g_cached_base = base;
    g_cached_size = size;

    const uint8_t* end = base + size;
    const uint8_t* addr = base;

    while (addr < end) {
        MEMORY_BASIC_INFORMATION mbi = {};
        if (VirtualQuery(addr, &mbi, sizeof(mbi)) == 0)
            break;

        const uint8_t* region_base = (const uint8_t*)mbi.BaseAddress;
        size_t region_size = mbi.RegionSize;

        const uint8_t* r_start = (region_base < base) ? base : region_base;
        const uint8_t* r_end = region_base + region_size;
        if (r_end > end) r_end = end;

        if (mbi.State == MEM_COMMIT &&
            (mbi.Protect & (PAGE_READONLY | PAGE_READWRITE |
                            PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                            PAGE_EXECUTE_WRITECOPY | PAGE_WRITECOPY)) &&
            !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        {
            if (r_start < r_end) {
                ReadableRange rr;
                rr.offset = (size_t)(r_start - base);
                rr.length = (size_t)(r_end - r_start);
                g_cached_ranges.push_back(rr);
            }
        }

        addr = region_base + region_size;
        if (addr <= region_base) break;
    }
    return g_cached_ranges;
}

/* -- Pattern scan (mask-based) ------------------------------------- */

/*
 * Scan a memory region for a byte pattern.
 * mask: 'x' = must match, '?' = wildcard
 * Returns address of first match, or nullptr.
 */
static inline const uint8_t* pattern_scan(
    const uint8_t* base, size_t size,
    const uint8_t* pattern, const char* mask, size_t pat_len)
{
    const auto& ranges = get_readable_ranges(base, size);
    for (const auto& rr : ranges) {
        if (rr.length < pat_len) continue;
        const uint8_t* start = base + rr.offset;
        size_t scan_len = rr.length - pat_len;
        for (size_t i = 0; i <= scan_len; i++) {
            bool ok = true;
            for (size_t j = 0; j < pat_len; j++) {
                if (mask[j] == '?') continue;
                if (start[i + j] != pattern[j]) { ok = false; break; }
            }
            if (ok) return &start[i];
        }
    }
    return nullptr;
}

/* Convenience: scan main module */
static inline const uint8_t* scan_main_module(
    const uint8_t* pattern, const char* mask, size_t pat_len)
{
    ModuleRegion rgn;
    if (!get_main_module(rgn)) return nullptr;
    return pattern_scan(rgn.base, rgn.size, pattern, mask, pat_len);
}

/* -- String search (safe) ------------------------------------------ */

/*
 * Find a UTF-8 string in the module's memory (typically .rdata section).
 * Only reads committed, readable pages.
 */
static inline const uint8_t* find_string_in_module(
    const uint8_t* base, size_t size, const char* str)
{
    size_t len = strlen(str);
    if (len == 0 || len > size) return nullptr;

    const auto& ranges = get_readable_ranges(base, size);
    for (const auto& rr : ranges) {
        if (rr.length < len) continue;
        const uint8_t* start = base + rr.offset;
        size_t scan_len = rr.length - len;
        for (size_t i = 0; i <= scan_len; i++) {
            if (memcmp(start + i, str, len) == 0)
                return start + i;
        }
    }
    return nullptr;
}

/*
 * Find a wide string (UTF-16LE) in module memory.
 * Only reads committed, readable pages.
 */
static inline const uint8_t* find_wstring_in_module(
    const uint8_t* base, size_t size, const wchar_t* str)
{
    size_t byte_len = wcslen(str) * sizeof(wchar_t);
    if (byte_len == 0 || byte_len > size) return nullptr;

    const auto& ranges = get_readable_ranges(base, size);
    for (const auto& rr : ranges) {
        if (rr.length < byte_len) continue;
        const uint8_t* start = base + rr.offset;
        size_t scan_len = rr.length - byte_len;
        for (size_t i = 0; i <= scan_len; i++) {
            if (memcmp(start + i, str, byte_len) == 0)
                return start + i;
        }
    }
    return nullptr;
}

/* -- RIP-relative address resolution ------------------------------- */

/*
 * Resolve a RIP-relative address from an instruction like:
 *   48 8B 05 XX XX XX XX   ; mov rax, [rip + disp32]
 *   48 89 05 XX XX XX XX   ; mov [rip + disp32], rax
 *   48 8D 0D XX XX XX XX   ; lea rcx, [rip + disp32]
 *
 * instr_addr: address of the instruction start (the 48 byte)
 * disp_offset: offset from instr_addr to the 4-byte displacement
 *              (typically 3 for the patterns above)
 * instr_len: total instruction length (typically 7)
 *
 * Returns the resolved absolute address.
 */
static inline uintptr_t resolve_rip_relative(
    const uint8_t* instr_addr, int disp_offset, int instr_len)
{
    int32_t disp = *(const int32_t*)(instr_addr + disp_offset);
    return (uintptr_t)(instr_addr + instr_len + disp);
}

/* -- Cross-reference scanner --------------------------------------- */

/*
 * Find instructions that reference a known address via RIP-relative
 * addressing. Searches for LEA/MOV patterns that load/store a
 * specific target address.
 *
 * target: the address being referenced (e.g., a string address)
 * Returns: vector of instruction addresses that reference target
 */
static inline std::vector<const uint8_t*> find_xrefs(
    const uint8_t* base, size_t size, uintptr_t target)
{
    std::vector<const uint8_t*> results;

    /* LEA reg, [rip+disp32] patterns:
     *   48 8D 05/0D/15/1D/25/2D/35/3D XX XX XX XX
     *   4C 8D 05/0D/15/1D/25/2D/35/3D XX XX XX XX
     * MOV reg, [rip+disp32]:
     *   48 8B 05/0D/15/1D/25/2D/35/3D XX XX XX XX
     *
     * Only scan readable pages to avoid access violations on
     * uncommitted or guard pages within the module's VA range.
     */
    const auto& ranges = get_readable_ranges(base, size);
    for (const auto& rr : ranges) {
        if (rr.length < 7) continue;
        const uint8_t* start = base + rr.offset;
        size_t scan_end = rr.length - 7;

        for (size_t i = 0; i <= scan_end; i++) {
            uint8_t b0 = start[i];
            uint8_t b1 = start[i + 1];
            uint8_t b2 = start[i + 2];

            if ((b0 == 0x48 || b0 == 0x4C) &&
                (b1 == 0x8B || b1 == 0x8D)) {
                if ((b2 & 0xC7) == 0x05) {
                    uintptr_t resolved = resolve_rip_relative(
                        start + i, 3, 7);
                    if (resolved == target) {
                        results.push_back(start + i);
                    }
                }
            }
        }
    }
    return results;
}

#endif /* CAPTUREAI_PATTERN_SCAN_H */
