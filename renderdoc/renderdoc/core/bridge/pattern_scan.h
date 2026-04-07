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

/* -- Pattern scan (mask-based) ------------------------------------- */

/*
 * Scan a memory region for a byte pattern.
 * mask: 'x' = must match, '?' = wildcard
 * Returns address of first match, or nullptr.
 */
static inline const uint8_t* pattern_scan(
    const uint8_t* start, size_t size,
    const uint8_t* pattern, const char* mask, size_t pat_len)
{
    for (size_t i = 0; i <= size - pat_len; i++) {
        bool ok = true;
        for (size_t j = 0; j < pat_len; j++) {
            if (mask[j] == '?') continue;
            if (start[i + j] != pattern[j]) { ok = false; break; }
        }
        if (ok) return &start[i];
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

/* -- String search ------------------------------------------------- */

/*
 * Find a UTF-8 string in the module's memory (typically .rdata section).
 * Returns the address of the string, or nullptr.
 */
static inline const uint8_t* find_string_in_module(
    const uint8_t* base, size_t size, const char* str)
{
    size_t len = strlen(str);
    if (len == 0 || len > size) return nullptr;

    for (size_t i = 0; i <= size - len; i++) {
        if (memcmp(base + i, str, len) == 0)
            return base + i;
    }
    return nullptr;
}

/*
 * Find a wide string (UTF-16LE) in module memory.
 * UE5 uses wchar_t strings extensively.
 */
static inline const uint8_t* find_wstring_in_module(
    const uint8_t* base, size_t size, const wchar_t* str)
{
    size_t byte_len = wcslen(str) * sizeof(wchar_t);
    if (byte_len == 0 || byte_len > size) return nullptr;

    for (size_t i = 0; i <= size - byte_len; i++) {
        if (memcmp(base + i, str, byte_len) == 0)
            return base + i;
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
     */
    for (size_t i = 0; i + 7 <= size; i++) {
        uint8_t b0 = base[i];
        uint8_t b1 = base[i + 1];
        uint8_t b2 = base[i + 2];

        /* Check REX prefix (48 or 4C) + opcode (8B or 8D) */
        if ((b0 == 0x48 || b0 == 0x4C) && (b1 == 0x8B || b1 == 0x8D)) {
            /* ModRM byte: mod=00, reg=any, rm=101 (RIP-relative) */
            if ((b2 & 0xC7) == 0x05) {
                uintptr_t resolved = resolve_rip_relative(base + i, 3, 7);
                if (resolved == target) {
                    results.push_back(base + i);
                }
            }
        }
    }
    return results;
}

#endif /* CAPTUREAI_PATTERN_SCAN_H */
