/* ue5_scan_engine.h -- GEngine/GUObjectArray/FNamePool scanner.
 * INCLUDED FROM ue5_engine.h ONLY -- do not include directly. */

/* -- Implementation ------------------------------------------------ */

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
     * We search for both wide (UTF-16) and ASCII strings.
     * Wide strings are UE5's native TCHAR format (most reliable).
     * ASCII strings cover engine code that uses char* literals
     * (e.g. CALIBRATEMOTION in input processing, present UE4-5.4).
     *
     * Order: most reliable / most unique first.
     */
    struct SearchEntry {
        const wchar_t* wstr;   /* wide string (NULL if ASCII) */
        const char*    astr;   /* ASCII string (NULL if wide) */
        const char*    label;  /* display name for logging */
    };

    const SearchEntry search_entries[] = {
        /* Wide strings (UE5 TCHAR) -- primary */
        {L"ToggleDebugCamera",      NULL, "L\"ToggleDebugCamera\""},
        {L"r.Streaming.PoolSize",   NULL, "L\"r.Streaming.PoolSize\""},
        {L"r.HLOD",                 NULL, "L\"r.HLOD\""},
        {L"GEngine",                NULL, "L\"GEngine\""},
        {L"SetViewLocation",        NULL, "L\"SetViewLocation\""},
        /* ASCII strings (char*) -- UEVR-proven anchors */
        {NULL, "CALIBRATEMOTION",                     "\"CALIBRATEMOTION\""},
        {NULL, "SeamlessTravel FlushLevelStreaming",   "\"SeamlessTravel FlushLevel...\""},
        {NULL, "StaticConstructObject_Internal",       "\"StaticConstructObject_Internal\""},
    };
    const int num_entries = sizeof(search_entries) / sizeof(search_entries[0]);

    int total_strings_found = 0;
    int total_xrefs_found = 0;
    int total_mov_candidates = 0;
    int rejected_out_of_bounds = 0;
    int rejected_null_ptr = 0;
    int rejected_low_addr = 0;
    int rejected_bad_vtable = 0;

    /* Log readable page statistics for diagnostics */
    {
        const auto& ranges = get_readable_ranges(rgn.base, rgn.size);
        size_t total_readable = 0;
        for (const auto& rr : ranges) total_readable += rr.length;
        bridge_log("  Module pages: %zu readable ranges, "
                   "%zu MB readable / %zu MB total",
                   ranges.size(),
                   total_readable / (1024*1024),
                   rgn.size / (1024*1024));
    }

    for (int si = 0; si < num_entries; si++) {
        const SearchEntry& se = search_entries[si];
        const uint8_t* str_addr = NULL;

        /* Yield between entries to avoid starving game threads. */
        if (si > 0) SwitchToThread();

        bridge_log("  [SCAN] Searching %s (%d/%d)...",
                   se.label, si + 1, num_entries);

        if (se.wstr)
            str_addr = find_wstring_in_module(rgn.base, rgn.size, se.wstr);
        else
            str_addr = find_string_in_module(rgn.base, rgn.size, se.astr);

        if (!str_addr) {
            bridge_log("  [SCAN] %s -- not found", se.label);
            continue;
        }

        total_strings_found++;
        bridge_log("  [SCAN] %s at offset +0x%llX",
                   se.label,
                   (unsigned long long)(str_addr - rgn.base));

        /* Find all code references to this string */
        auto xrefs = find_xrefs(rgn.base, rgn.size, (uintptr_t)str_addr);
        total_xrefs_found += (int)xrefs.size();
        bridge_log("  [SCAN]   %zu cross-references found", xrefs.size());

        if (xrefs.empty()) {
            bridge_log("  [SCAN]   No xrefs -- string exists but is "
                       "unreferenced (stripped code?)");
            continue;
        }

        for (const uint8_t* xref : xrefs) {
            bridge_log("  [SCAN]   Xref at +0x%llX, scanning [-256,+512]...",
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

            int local_candidates = 0;
            for (const uint8_t* p = search_start; p < search_end; p++) {
                if (p[0] != 0x48 || p[1] != 0x8B) continue;
                /* ModRM: mod=00, rm=101 means [rip+disp32] */
                if ((p[2] & 0xC7) != 0x05) continue;

                total_mov_candidates++;
                local_candidates++;
                uintptr_t resolved = resolve_rip_relative(p, 3, 7);

                /* Validate: the resolved address should be in the
                 * module's data section (.data or .bss), which is
                 * typically in the upper portion of the image. */
                if (resolved < (uintptr_t)rgn.base ||
                    resolved >= (uintptr_t)(rgn.base + rgn.size)) {
                    rejected_out_of_bounds++;
                    continue;
                }

                /* Read the pointer value at that address.
                 * SEH-safe: module range can contain uncommitted pages
                 * (DRM/AC may rewrite page protection); a raw deref on
                 * such a page would crash the game process mid-scan. */
                uintptr_t cand_raw = seh_read_ptr((void*)resolved);
                if (cand_raw == 0) {
                    rejected_null_ptr++;
                    continue;
                }
                void* candidate = (void*)cand_raw;

                /* Basic validation: the pointer should point to
                 * a valid-looking object (not stack, not too low).
                 * UE5 objects are heap-allocated, typically >0x10000. */
                if ((uintptr_t)candidate < 0x10000) {
                    rejected_low_addr++;
                    continue;
                }

                /* Check if the pointed-to object has a vtable
                 * (first 8 bytes should be a valid pointer too) */
                uintptr_t vtable = seh_read_ptr(candidate);
                if (vtable < 0x10000) {
                    rejected_bad_vtable++;
                    continue;
                }

                /* This looks like a valid engine pointer! */
                g_engine_global_addr = resolved;
                g_engine_ptr = (UEngine*)candidate;
                g_engine_found = true;

                bridge_log("GEngine FOUND via %s xref!",
                           se.label);
                bridge_log("  Global addr: 0x%llX (offset +0x%llX)",
                           (unsigned long long)resolved,
                           (unsigned long long)(resolved - (uintptr_t)rgn.base));
                bridge_log("  Pointer value: 0x%p", candidate);
                bridge_log("  VTable: 0x%llX", (unsigned long long)vtable);
                bridge_log("  Scan stats: %d strings, %d xrefs, "
                           "%d MOV candidates tested",
                           total_strings_found, total_xrefs_found,
                           total_mov_candidates);

                return true;
            }

            if (local_candidates == 0) {
                bridge_log("  [SCAN]   No MOV [rip+X] instructions "
                           "in search window");
            }
        }
    }

    /* All methods exhausted -- dump diagnostic summary */
    bridge_log("GEngine scan FAILED. Diagnostic summary:");
    bridge_log("  Strings found:    %d / %d",
               total_strings_found,
               num_entries);
    bridge_log("  Total xrefs:      %d", total_xrefs_found);
    bridge_log("  MOV candidates:   %d", total_mov_candidates);
    bridge_log("  Rejected reasons:");
    bridge_log("    out-of-bounds:  %d", rejected_out_of_bounds);
    bridge_log("    null pointer:   %d", rejected_null_ptr);
    bridge_log("    low address:    %d", rejected_low_addr);
    bridge_log("    bad vtable:     %d", rejected_bad_vtable);
    if (total_strings_found == 0) {
        bridge_log("  HINT: No search strings found. Game may have "
                   "stripped string data. Try manual offset.");
    } else if (total_xrefs_found == 0) {
        bridge_log("  HINT: Strings exist but no code references them. "
                   "Game may use obfuscated string loading.");
    } else if (total_mov_candidates == 0) {
        bridge_log("  HINT: Xrefs found but no MOV [rip+X] nearby. "
                   "GEngine access may use a different pattern.");
    } else {
        bridge_log("  HINT: Candidates found but none passed validation. "
                   "GEngine may not be initialized yet (try later) "
                   "or pointer layout differs from expected.");
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
    /* SEH-safe: user-supplied offset may point into .pdata or
     * another non-committed region. Raw deref would kill the game. */
    uintptr_t cand_raw = seh_read_ptr((void*)addr);

    if (cand_raw == 0) {
        bridge_log("WARNING: Offset 0x%llX yielded NULL/unreadable pointer",
                   (unsigned long long)offset);
        return false;
    }
    void* candidate = (void*)cand_raw;

    g_engine_global_addr = addr;
    g_engine_ptr = (UEngine*)candidate;
    g_engine_found = true;

    bridge_log("GEngine set via offset 0x%llX -> 0x%p",
               (unsigned long long)offset, candidate);
    return true;
}

/*
 * Master GEngine finder -- dual method with cross-validation.
 *
 * Method 0: env var / TCP override
 * Method 1: PE export "?GEngine@@3PEAVUEngine@@EA" (fastest, many Shipping builds)
 * Method A: string xref (gives g_engine_global_addr)
 * Method B: GUObjectArray structural scan (UE4SS approach, if GUA found)
 *
 * If both A and B succeed and agree  -> confirmed, high confidence.
 * If both succeed but differ         -> prefer A (has global addr).
 * If only one of A/B succeeds        -> use it as-is.
 */
static bool find_gengine_via_guobjectarray();  /* forward decl -- used in Method B below */

static bool find_gengine()
{
    /* Method 0: env var / TCP override (highest priority) */
    const char* env_offset = getenv("CAPTUREAI_GENGINE_OFFSET");
    if (env_offset) {
        uintptr_t offset = strtoull(env_offset, NULL, 16);
        if (find_gengine_via_offset(offset))
            return true;
    }

    /* Method 1: PE export symbol -- fastest, works for many Shipping builds.
     * The export IS the global variable (UEngine**), so dereference once. */
    {
        void** exp_ptr = (void**)GetProcAddress(
            GetModuleHandleA(NULL), "?GEngine@@3PEAVUEngine@@EA");
        if (exp_ptr) {
            void* candidate = seh_read_ptr(exp_ptr) ? *exp_ptr : NULL;
            if (candidate && (uintptr_t)candidate > 0x10000 &&
                (uintptr_t)candidate < 0x7F0000000000ULL)
            {
                uintptr_t vtable = seh_read_ptr(candidate);
                if (vtable > 0x10000) {
                    g_engine_ptr          = (UEngine*)candidate;
                    g_engine_found        = true;
                    g_engine_global_addr  = (uintptr_t)exp_ptr;
                    bridge_log("GEngine via export: 0x%p (global=0x%llX)",
                               candidate, (unsigned long long)exp_ptr);
                    return true;
                }
            }
            bridge_log("GEngine export found but pointer invalid, continue");
        } else {
            bridge_log("GEngine export not found, trying scan methods");
        }
    }

    /* Method A: string xref scan */
    bridge_log("GEngine Method A: string xref scan...");
    bool a_ok = find_gengine_via_string_xref();
    UEngine* a_result = a_ok ? g_engine_ptr : NULL;

    /* Method B: GUObjectArray structural scan (only if GUA already found) */
    bool b_ok = false;
    UEngine* b_result = NULL;
    if (g_guobjectarray_found) {
        bridge_log("GEngine Method B: GUObjectArray structural scan...");
        /* Temporarily clear so find_gengine_via_guobjectarray can write */
        UEngine* saved_a = g_engine_ptr;
        uintptr_t saved_addr = g_engine_global_addr;
        bool saved_found = g_engine_found;
        g_engine_ptr = NULL; g_engine_found = false; g_engine_global_addr = 0;

        b_ok = find_gengine_via_guobjectarray();
        b_result = b_ok ? g_engine_ptr : NULL;

        /* Restore Method A state as base */
        g_engine_ptr   = saved_a;
        g_engine_found = saved_found;
        g_engine_global_addr = saved_addr;
    } else {
        bridge_log("GEngine Method B: skipped (GUObjectArray not yet found)");
    }

    /* Cross-validate */
    if (a_ok && b_ok) {
        if (a_result == b_result) {
            bridge_log("GEngine CONFIRMED by both methods: 0x%p", a_result);
        } else {
            bridge_log("GEngine WARNING: Method A=0x%p vs Method B=0x%p -- "
                       "preferring Method A (has global addr)",
                       a_result, b_result);
        }
        /* Keep Method A result (has g_engine_global_addr) */
        g_engine_ptr = a_result;
        g_engine_found = true;
        return true;
    }

    if (a_ok) {
        bridge_log("GEngine found via Method A only (GUObjectArray unavailable)");
        return true;
    }

    if (b_ok) {
        bridge_log("GEngine found via Method B (GUObjectArray) -- "
                   "string xref failed");
        g_engine_ptr   = b_result;
        g_engine_found = true;
        g_engine_global_addr = 0;  /* not available via GUA scan */
        return true;
    }

    bridge_log("WARNING: GEngine not found by either method. "
               "Use __bridge_set_offset <hex> via TCP, "
               "or set CAPTUREAI_GENGINE_OFFSET env var.");
    return false;
}

/* -- FExec secondary vtable finder --------------------------------- */

/*
 * UEngine inherits from both UObject and FExec (multiple inheritance).
 * The FExec vtable is a SECONDARY vtable at some offset in the object:
 *
 *   GEngine layout (x64):
 *     offset 0:   UObject vptr (primary, 80+ entries)
 *     offset 8+:  UObject members (FName, UClass*, etc.)
 *     offset N:   FExec vptr (secondary, 5 entries: dtor+Exec+3)
 *
 * FExec::Exec is the UNIVERSAL console command router that handles
 * CVars, stat, showflag, ToggleDebugCamera, and all other commands.
 * ProcessConsoleExec (primary vtable) only handles UFUNCTION(Exec).
 *
 * UEngine inherits: public UObject, public FExec  (multiple inheritance).
 * FExec has 5 virtual functions: ~FExec, Exec, Exec_Runtime, Exec_Dev,
 * Exec_Editor.  The FExec subobject vptr sits right after UObject's data.
 *
 * UObjectBase layout (x64, standard FName=8 bytes):
 *   +0   vptr(8) +8 ObjectFlags(4) +12 InternalIndex(4)
 *   +16  ClassPrivate(8) +24 NamePrivate(8) +32 OuterPrivate(8)
 *   sizeof(UObjectBase) = 40
 * UObject adds no data members -> sizeof(UObject) = 40
 * FExec vptr at offset 40 (0x28).
 *
 * WITH_CASE_PRESERVING_NAME (editor builds) makes FName=12 bytes,
 * pushing sizeof(UObject) to 48 -> FExec vptr at 48 (0x30).
 *
 * Strategy: try known offsets 40 and 48 first, then scan.
 */
static bool validate_function_ptr(void* fn);         /* forward decl */
/* Try to find UE version string in the game module.
 * Looks for "++UE5+Release-X.Y" or "+Release-X.Y" ASCII pattern. */
static void detect_ue_version_string()
{
    ModuleRegion rgn;
    if (!get_main_module(rgn)) return;

    const char* pat = "+Release-";
    size_t pat_len = 9;

    /* Use find_string_in_module (VirtualQuery-safe) */
    const uint8_t* hit = find_string_in_module(
        rgn.base, rgn.size, pat);
    if (!hit) {
        bridge_log("  UE Version: not found in module");
        return;
    }
    const char* ver = (const char*)hit + pat_len;
    if (ver[0] >= '4' && ver[0] <= '9' && ver[1] == '.') {
        char buf[64];
        int i = 0;
        while (i < 30 && ver[i] >= ' ' && ver[i] <= 'z')
            buf[i] = ver[i], i++;
        buf[i] = '\0';
        bridge_log("  UE Version detected: %s", buf);
    } else {
        bridge_log("  UE Version: pattern found but no version number");
    }
}

/* Check if offset `off` in the GEngine object holds an FExec vtable.
 * FExec has 5 virtuals: dtor, Exec, Exec_Runtime, Exec_Dev, Exec_Editor.
 * MSVC secondary vtable: all 5 entries are adjustor thunks -> valid fns.
 * We require [0],[1] valid and NOT equal to the primary vtable. */
static bool try_fexec_at_offset(uint8_t* obj, int off,
                                uintptr_t mod_start, uintptr_t mod_end,
                                uintptr_t primary_vptr)
{
    uintptr_t vptr = seh_read_ptr(obj + off);
    if (vptr < mod_start || vptr >= mod_end) return false;
    if (vptr == primary_vptr) return false;   /* skip primary vtable */

    void* fn0 = (void*)seh_read_ptr((void*)vptr);       /* ~FExec */
    void* fn1 = (void*)seh_read_ptr((void*)(vptr + 8)); /* Exec  */
    if (!validate_function_ptr(fn0) || !validate_function_ptr(fn1))
        return false;

    /* Extra validation: FExec has 5 entries, check [2]-[4] too */
    int valid_count = 2;
    for (int i = 2; i < 8; i++) {
        void* fn = (void*)seh_read_ptr((void*)(vptr + i * 8));
        if (validate_function_ptr(fn))
            valid_count++;
        else
            break;
    }

    bridge_log("  obj+%d: vptr=0x%llX, %d valid entries",
               off, (unsigned long long)vptr, valid_count);

    /* FExec should have exactly 5 entries (or 3 in shipping without
     * Exec_Dev/Exec_Editor).  Accept 3-8 entries as FExec candidate.
     * The primary UObject vtable has 80+ entries, so this filters it. */
    if (valid_count > 20) {
        bridge_log("    -> too many entries (%d), likely primary vtable "
                   "duplicate, skip", valid_count);
        return false;
    }

    /* Found FExec vtable */
    g_fexec_offset = (uintptr_t)off;
    g_fexec_exec = (FExecExecFn)fn1;

    bridge_log("  >>> FExec vtable found at obj+%d <<<", off);
    bridge_log("    vptr       = 0x%llX", (unsigned long long)vptr);
    bridge_log("    [0] ~FExec = 0x%p", fn0);
    bridge_log("    [1] Exec   = 0x%p", fn1);
    for (int i = 2; i < valid_count && i < 6; i++) {
        void* fn = (void*)seh_read_ptr((void*)(vptr + i * 8));
        const char* name = (i == 2) ? "Exec_Runtime" :
                           (i == 3) ? "Exec_Dev" :
                           (i == 4) ? "Exec_Editor" : "???";
        bridge_log("    [%d] %-13s= 0x%p", i, name, fn);
    }
    bridge_log("    this_adj   = GEngine+%d (0x%p)",
               off, (void*)(obj + off));
    return true;
}

static bool find_fexec_vtable()
{
    uint8_t* obj = (uint8_t*)g_engine_ptr;
    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;

    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end = mod_start + rgn.size;

    /* Detect UE version for diagnostics */
    detect_ue_version_string();

    bridge_log("=== GEngine FExec Lookup ===");
    bridge_log("  GEngine ptr: 0x%p", g_engine_ptr);
    bridge_log("  Module: 0x%llX - 0x%llX (%zu MB)",
               (unsigned long long)mod_start,
               (unsigned long long)mod_end,
               rgn.size / (1024*1024));

    uintptr_t primary_vptr = seh_read_ptr(obj);
    bridge_log("  Primary vptr (obj+0): 0x%llX",
               (unsigned long long)primary_vptr);

    /*
     * Strategy 1: Try known offsets from UE5 headers.
     *   offset 40 = sizeof(UObject) with FName=8 (standard)
     *   offset 48 = sizeof(UObject) with FName=12 (CASE_PRESERVING)
     */
    bridge_log("  --- Trying known offsets ---");
    static const int known_offsets[] = {40, 48};
    for (int off : known_offsets) {
        bridge_log("  Trying obj+%d...", off);
        if (try_fexec_at_offset(obj, off, mod_start, mod_end,
                                primary_vptr))
            return true;
    }

    /*
     * Strategy 2: Scan all 8-byte-aligned offsets [8..512].
     * Find the first secondary vtable (not primary, 3-20 entries).
     */
    bridge_log("  --- Known offsets failed, scanning [8..512] ---");
    for (int off = 8; off <= 512; off += 8) {
        if (off == 40 || off == 48) continue;  /* already tried */
        if (try_fexec_at_offset(obj, off, mod_start, mod_end,
                                primary_vptr))
            return true;
    }

    bridge_log("ERROR: FExec secondary vtable not found!");
    bridge_log("  This may indicate a non-standard UObject layout.");
    return false;
}

/* -- GUObjectArray finder ------------------------------------------ */
/*
 * UWorld is NOT found by static scan. It is captured as a direct
 * parameter of ULocalPlayer::Exec(UWorld* InWorld, cmd, ar) by the
 * FExec hooks installed below. This is the UE4SS approach.
 */

/*
 * Validate a GUObjectArray candidate.
 * Checks: NumElements in [1000, 5000000], Objects** valid, chunk[0] valid.
 * Mirrors UE4SS's SetupGUObjectArrayAddress() sanity checks.
 */
static bool validate_guobjectarray(void* candidate)
{
    if (!candidate || (uintptr_t)candidate < 0x10000) return false;

    uint8_t* p = (uint8_t*)candidate;

    /* NumElements = p + GUOBJARRAY_NUMELEMS_OFF */
    int32_t num_elems = 0;
    __try { num_elems = *(int32_t*)(p + GUOBJARRAY_NUMELEMS_OFF); }
    __except(EXCEPTION_EXECUTE_HANDLER) { return false; }

    if (num_elems < 1000 || num_elems > 5000000) {
        bridge_log("  GUObjectArray: NumElements=%d out of [1000,5M]",
                   num_elems);
        return false;
    }

    /* Objects** = p + GUOBJARRAY_OBJECTS_OFF */
    uintptr_t chunks_ptr = seh_read_ptr(p + GUOBJARRAY_OBJECTS_OFF);
    if (chunks_ptr < 0x10000 || chunks_ptr >= 0x7F0000000000ULL) {
        bridge_log("  GUObjectArray: Objects** invalid 0x%llX",
                   (unsigned long long)chunks_ptr);
        return false;
    }

    /* Objects*[0] = first chunk must be readable */
    uintptr_t chunk0 = seh_read_ptr((void*)chunks_ptr);
    if (chunk0 < 0x10000 || chunk0 >= 0x7F0000000000ULL) {
        bridge_log("  GUObjectArray: Objects[0] invalid 0x%llX",
                   (unsigned long long)chunk0);
        return false;
    }

    /* First FUObjectItem in chunk0: Object* at +0 must look valid */
    uintptr_t first_obj = seh_read_ptr((void*)chunk0);
    if (first_obj < 0x10000) {
        bridge_log("  GUObjectArray: first object 0x%llX invalid",
                   (unsigned long long)first_obj);
        return false;
    }

    bridge_log("  GUObjectArray valid: %d objects, "
               "Objects**=0x%llX, chunk[0]=0x%llX",
               num_elems, (unsigned long long)chunks_ptr,
               (unsigned long long)chunk0);
    return true;
}

/*
 * Get object at index i. Returns UObjectBase* or NULL.
 * Implements UE4SS IndexToObject() chunk arithmetic.
 */
static void* guobjectarray_get(int32_t index)
{
    if (!g_guobjectarray || index < 0) return NULL;

    uint8_t* arr = (uint8_t*)g_guobjectarray;
    uintptr_t chunks_ptr = seh_read_ptr(arr + GUOBJARRAY_OBJECTS_OFF);
    if (!chunks_ptr) return NULL;

    int32_t chunk_idx   = (uint32_t)index >> FUOBJECTARRAY_CHUNK_SHIFT;
    int32_t within_idx  = (uint32_t)index &  FUOBJECTARRAY_CHUNK_MASK;

    uintptr_t chunk = seh_read_ptr(
        (void*)(chunks_ptr + (uintptr_t)chunk_idx * 8));
    if (!chunk) return NULL;

    uintptr_t item_addr = chunk + (uintptr_t)within_idx * g_fuobjectitem_stride;
    uintptr_t obj = seh_read_ptr((void*)(item_addr + g_fuobjectitem_object_off));
    /* Packed layout: low 3 bits hold flags; mask before returning */
    if (g_fuobjectitem_stride == 16) obj &= ~(uintptr_t)7;
    return (void*)obj;
}

static int32_t guobjectarray_num_elements()
{
    if (!g_guobjectarray) return 0;
    int32_t n = 0;
    __try {
        n = *(int32_t*)((uint8_t*)g_guobjectarray + GUOBJARRAY_NUMELEMS_OFF);
    }
    __except(EXCEPTION_EXECUTE_HANDLER) { n = 0; }
    return n;
}

/*
 * detect_fuobjectitem_stride() -- determine FUObjectItem stride at runtime.
 *
 * Cross-validates using GEngine.InternalIndex (at UObjectBase+0x0C).
 * Must be called after both g_guobjectarray and g_engine_ptr are set.
 *
 * Configs tested:
 *   (24, 0x00) -- Standard Shipping (default)
 *   (32, 0x08) -- Development / WITH_VERSE_VM [StackOBot UE5.7 confirmed]
 *   (32, 0x10) -- Alt 32B layout
 *   (16, 0x00) -- UE_PACK_FUOBJECT_ITEM
 */
static void detect_fuobjectitem_stride()
{
    if (!g_guobjectarray || !g_engine_ptr) return;

    uintptr_t chunks_ptr = seh_read_ptr((uint8_t*)g_guobjectarray + GUOBJARRAY_OBJECTS_OFF);
    uintptr_t chunk0 = seh_read_ptr((void*)chunks_ptr);
    if (!chunk0) { bridge_log("  stride detect: chunk0 not readable"); return; }

    int32_t ge_idx = 0;
    __try { ge_idx = *(int32_t*)((uint8_t*)g_engine_ptr + 0x0C); }
    __except(EXCEPTION_EXECUTE_HANDLER) { return; }
    if (ge_idx <= 0 || ge_idx >= 2000000) {
        bridge_log("  stride detect: GEngine.InternalIndex=%d invalid", ge_idx);
        return;
    }

    static const struct { int stride; int obj_off; } cfgs[] = {
        {24, 0x00}, {32, 0x08}, {32, 0x10}, {16, 0x00},
    };
    for (int ci = 0; ci < 4; ci++) {
        int s = cfgs[ci].stride, off = cfgs[ci].obj_off;
        uintptr_t probe = seh_read_ptr(
            (void*)(chunk0 + (uintptr_t)ge_idx * s + off));
        if (s == 16) probe &= ~(uintptr_t)7;
        if (probe == (uintptr_t)g_engine_ptr) {
            g_fuobjectitem_stride    = s;
            g_fuobjectitem_object_off = off;
            bridge_log("  FUObjectItem CONFIRMED: stride=%d obj_off=0x%02X "
                       "(GEngine idx=%d cross-validated)", s, off, ge_idx);
            return;
        }
        bridge_log("  FUObjectItem probe stride=%d off=0x%02X -> 0x%llX (need 0x%llX)",
                   s, off, (unsigned long long)probe, (unsigned long long)(uintptr_t)g_engine_ptr);
    }
    bridge_log("  FUObjectItem detect FAILED -- keeping stride=%d off=0x%02X",
               g_fuobjectitem_stride, g_fuobjectitem_object_off);
}

/*
 * GEngine finder via GUObjectArray structural scan (UE4SS approach).
 *
 * UGameEngine has the largest primary vtable of any FExec implementor:
 * typically 80-120 entries vs ULocalPlayer ~20-40, others <= 30.
 * We scan the first 1000 objects (GEngine is always created early),
 * find every FExec implementor (secondary vtable at +0x28 with 3-8 entries),
 * and pick the one with the most primary vtable entries.
 *
 * Requires: GUObjectArray already found.
 * Does NOT require FName::ToString -- purely structural.
 */
static bool find_gengine_via_guobjectarray()
{
    if (!g_guobjectarray_found || !g_guobjectarray) return false;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;

    int32_t num_elems  = guobjectarray_num_elements();
    int32_t scan_limit = (num_elems < 1000) ? num_elems : 1000;

    bridge_log("  GUA GEngine scan: first %d objects", scan_limit);

    void*     best_obj    = NULL;
    int       best_vcnt   = 0;
    uintptr_t best_vptr   = 0;

    for (int32_t i = 0; i < scan_limit; i++) {
        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x7F0000000000ULL) continue;

        /* Primary vtable must be in module */
        uintptr_t vptr = seh_read_ptr(obj);
        if (vptr < mod_start || vptr >= mod_end) continue;

        /* Must have FExec secondary vtable at +0x28 */
        uintptr_t fexec_vptr = seh_read_ptr((uint8_t*)obj + 0x28);
        if (fexec_vptr < mod_start || fexec_vptr >= mod_end) continue;
        if (fexec_vptr == vptr) continue;

        /* Validate FExec vtable has 3-8 entries */
        void* fn0 = (void*)seh_read_ptr((void*)fexec_vptr);
        void* fn1 = (void*)seh_read_ptr((void*)(fexec_vptr + 8));
        if (!validate_function_ptr(fn0) || !validate_function_ptr(fn1)) continue;

        int fexec_cnt = 2;
        for (int vi = 2; vi <= 8; vi++) {
            void* fn = (void*)seh_read_ptr((void*)(fexec_vptr + vi * 8));
            if (!validate_function_ptr(fn)) break;
            fexec_cnt++;
        }
        if (fexec_cnt < 3 || fexec_cnt > 8) continue;

        /* Count primary vtable entries -- GEngine wins with 80+ */
        int vcnt = 0;
        for (int vi = 0; vi < 256; vi++) {
            void* fn = (void*)seh_read_ptr((void*)(vptr + vi * 8));
            if (!validate_function_ptr(fn)) break;
            vcnt++;
        }

        if (vcnt > best_vcnt) {
            best_vcnt = vcnt;
            best_obj  = obj;
            best_vptr = vptr;
        }
    }

    /* UGameEngine requires at least 50 primary vtable entries.
     * This filters out ULocalPlayer, UNetDriver, and similar. */
    if (!best_obj || best_vcnt < 50) {
        bridge_log("  GUA GEngine scan: no candidate "
                   "(best=%d vtable entries, need >=50)", best_vcnt);
        return false;
    }

    bridge_log("  GUA GEngine found: 0x%p (vptr=0x%llX, %d vtable entries)",
               best_obj, (unsigned long long)best_vptr, best_vcnt);

    g_engine_ptr   = (UEngine*)best_obj;
    g_engine_found = true;
    /* g_engine_global_addr not available via this method */
    return true;
}

/*
 * Find GUObjectArray.
 *
 * Strategy 1: Export symbol lookup.
 *   Many UE5 games export "?GUObjectArray@@3VFUObjectArray@@A".
 *   (Used by Returnal, per UE4SS GUObjectArray.lua.)
 *
 * Strategy 2-4: AOB pattern scan -- three patterns sourced from
 *   UE4SS CustomGameConfigs Lua scripts (validated on real UE5 games):
 *
 *   Pat-A (LN3): LEA reg, [RIP+GUObjectArray] in AllocateUObjectIndex
 *     48 8D ?? ?? ?? ?? ?? 4C 8B C9 48 89 01
 *     Decode: next=addr+7, GUA = next + *(int32*)(addr+3)
 *
 *   Pat-B (FF7 Remake): MOV reg, [RIP+ptr_into_GUA+0x10]
 *     48 8B ?? ?? ?? ?? ?? 4C 8B 04 C8 4D 85 C0 74 07
 *     Decode: next=addr+7, ptr = next+*(int32*)(addr+3), GUA = ptr-0x10
 *
 *   Pat-C (FF7 Rebirth): ADD targeting GUObjectArray+6
 *     03 ?? ?? ?? ?? ?? FF C8 3B D0 0F 8D
 *     Decode: next=addr+6, GUA = next + *(int32*)(addr+2)
 */
static bool find_guobjectarray()
{
    bridge_log("=== GUObjectArray Search ===");

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;

    /* --- Strategy 1: Export symbol --- */
    HMODULE exe = GetModuleHandleA(NULL);
    void* exp_addr = (void*)GetProcAddress(
        exe, "?GUObjectArray@@3VFUObjectArray@@A");
    if (exp_addr) {
        bridge_log("  Strategy 1: export found at 0x%p", exp_addr);
        if (validate_guobjectarray(exp_addr)) {
            g_guobjectarray = exp_addr;
            g_guobjectarray_found = true;
            bridge_log("  GUObjectArray via export: 0x%p", exp_addr);
            return true;
        }
    } else {
        bridge_log("  Strategy 1: export not found");
    }

    /* --- Strategy 2-5: AOB patterns --- */
    /* mod_start/mod_end only needed for AOB candidate validation */
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;

    /* Pat-A: 48 8D ?? ?? ?? ?? ?? 4C 8B C9 48 89 01
     * LEA reg,[rip+GUA] in AllocateUObjectIndex (LN3 demo) */
    static const uint8_t patA[] = {
        0x48,0x8D, 0,0,0,0,0,  0x4C,0x8B,0xC9, 0x48,0x89,0x01
    };
    static const char maskA[] = "xx?????xxxxxx";

    /* Pat-B: 48 8B ?? ?? ?? ?? ?? 4C 8B 04 C8 4D 85 C0 74 07
     * MOV reg,[rip+GUA+0x10] (FF7 Remake) */
    static const uint8_t patB[] = {
        0x48,0x8B, 0,0,0,0,0,  0x4C,0x8B,0x04,0xC8, 0x4D,0x85,0xC0,0x74,0x07
    };
    static const char maskB[] = "xx?????xxxxxxxxx";

    /* Pat-C: 03 ?? ?? ?? ?? ?? FF C8 3B D0 0F 8D
     * ADD targeting GUObjectArray+6 (FF7 Rebirth) */
    static const uint8_t patC[] = {
        0x03, 0,0,0,0,0,  0xFF,0xC8, 0x3B,0xD0, 0x0F,0x8D
    };
    static const char maskC[] = "x?????xxxxxx";

    /* Pat-D: 48 8D 0D ?? ?? ?? ?? E8 ?? ?? ?? ?? E8 ?? ?? ?? ?? E8 ?? ?? ?? ?? C6 05 ?? ?? ?? ?? 01
     * LEA RCX,[rip+GUA+0x10] in engine init sequence (Split Fiction)
     * Same -0x10 adjustment as Pat-B. */
    static const uint8_t patD[] = {
        0x48,0x8D,0x0D, 0,0,0,0,
        0xE8, 0,0,0,0,
        0xE8, 0,0,0,0,
        0xE8, 0,0,0,0,
        0xC6,0x05, 0,0,0,0, 0x01
    };
    static const char maskD[] = "xxx????x????x????x????xx????x";

    struct PatEntry {
        const uint8_t* bytes;
        const char*    mask;
        size_t         len;
        int            disp_off;   /* offset to int32 displacement */
        int            instr_len;  /* total instruction bytes */
        int            adjustment; /* subtract from resolved addr */
        const char*    name;
    };

    PatEntry pats[] = {
        {patA, maskA, 13, 3, 7,    0, "Pat-A (LN3/AllocateUObjectIndex)"},
        {patB, maskB, 16, 3, 7, 0x10, "Pat-B (FF7R/GUObjectArray+0x10)"},
        {patC, maskC, 12, 2, 6,    0, "Pat-C (FF7Rebirth/ADD-pattern)"},
        {patD, maskD, 29, 3, 7, 0x10, "Pat-D (SplitFiction/LEA-RCX)"},
    };
    const int NUM_PATS = 4;

    for (int pi = 0; pi < NUM_PATS; pi++) {
        const PatEntry& pe = pats[pi];
        const uint8_t* hit = pattern_scan(
            rgn.base, rgn.size, pe.bytes, pe.mask, pe.len);

        if (!hit) {
            bridge_log("  Strategy %d: %s -- no match", pi + 2, pe.name);
            continue;
        }

        bridge_log("  Strategy %d: %s matched at +0x%llX",
                   pi + 2, pe.name,
                   (unsigned long long)(hit - rgn.base));

        uintptr_t resolved = resolve_rip_relative(
            hit, pe.disp_off, pe.instr_len);
        void* candidate = (void*)(resolved - (uintptr_t)pe.adjustment);

        bridge_log("    resolved=0x%llX, candidate=0x%p",
                   (unsigned long long)resolved, candidate);

        if ((uintptr_t)candidate < mod_start ||
            (uintptr_t)candidate >= mod_end) {
            bridge_log("    candidate outside module, skip");
            continue;
        }

        if (!validate_guobjectarray(candidate)) continue;

        g_guobjectarray = candidate;
        g_guobjectarray_found = true;
        bridge_log("  GUObjectArray FOUND via %s: 0x%p", pe.name, candidate);
        return true;
    }

    bridge_log("  GUObjectArray: all strategies failed");
    return false;
}

/* ---- FName Pool Utilities ---------------------------------------- */

/*
 * FNamePool (UE5) block layout:
 *   FNameEntry header (uint16):
 *     UE4: (len << 1) | bIsWide
 *     UE5: (len << 6) | (probeHash << 1) | bIsWide
 *   Followed by char[len] or wchar_t[len].
 *
 * ComparisonIndex encoding:
 *   bits[31:16] = block_idx
 *   bits[15: 0] = word_off   (byte_offset_in_block / 2)
 *
 * FNamePool struct (UE5, MSVC x64, in module .bss):
 *   +0x00  SRWLOCK Lock        (8 bytes)
 *   +0x08  uint32  CurrentBlock
 *   +0x0C  uint32  CurrentByteCursor
 *   +0x10  uint8*  Blocks[8192]   (8192 pointers to 128KB heap blocks)
 *
 * Block size: word_off max = 0xFFFF -> max byte_off = 0x1FFFE = ~128KB.
 */

#define FNAMEPOOL_BLOCKS_OFF  0x10
#define FNAMEPOOL_MAX_BLOCKS  8192
#define FNAMEPOOL_BLOCK_BYTES (128 * 1024)

static int       g_fname_header_shift = 1;  /* 1=UE4, 6=UE5; set on block0 find */
static uintptr_t g_fnamepool_block0   = 0;  /* FNamePool block 0 heap base */
static uintptr_t g_fnamepool_global   = 0;  /* FNamePool struct in module .bss */

/* Extract name length from raw uint16 header */
static inline int fname_entry_len(uint16_t hdr)
{
    return (int)(hdr >> g_fname_header_shift);
}

/* Check if addr is FNamePool block 0 (starts with FNameEntry "None").
 * Detects UE4 vs UE5 header format and sets g_fname_header_shift. */
static bool fname_block0_matches_none(uintptr_t addr)
{
    uint8_t b0, b1, b2, b3, b4, b5;
    __try {
        b0 = *(uint8_t*)(addr + 0); b1 = *(uint8_t*)(addr + 1);
        b2 = *(uint8_t*)(addr + 2); b3 = *(uint8_t*)(addr + 3);
        b4 = *(uint8_t*)(addr + 4); b5 = *(uint8_t*)(addr + 5);
    }
    __except(EXCEPTION_EXECUTE_HANDLER) { return false; }

    if (b2 != 'N' || b3 != 'o' || b4 != 'n' || b5 != 'e') return false;
    if (b0 & 1) return false;  /* bIsWide must be 0 */
    /* UE4: header=0x0008 -> b1==0x00, b0==0x08 */
    if (b1 == 0x00 && b0 == 0x08) { g_fname_header_shift = 1; return true; }
    /* UE5: header=(4<<6)|(hash<<1) -> b1==0x01 (high byte of len field) */
    if (b1 == 0x01) { g_fname_header_shift = 6; return true; }
    return false;
}

/* Return heap pointer for FNamePool block bi. */
static uintptr_t fname_get_block(uint32_t bi)
{
    if (bi == 0 && g_fnamepool_block0) return g_fnamepool_block0;
    if (g_fnamepool_global && bi < FNAMEPOOL_MAX_BLOCKS)
        return seh_read_ptr(
            (void*)(g_fnamepool_global + FNAMEPOOL_BLOCKS_OFF + bi * 8));
    return 0;
}

/* Locate FNamePool struct in module .bss (for multi-block access).
 * Method 1: export symbol "GNamePool". Method 2: backref scan from block0. */
static uintptr_t find_fnamepool_global()
{
    if (g_fnamepool_global) return g_fnamepool_global;

    /* Method 1: export */
    static const char* exports[] = {"GNamePool","?GNamePool@@3VFNamePool@@A"};
    for (int ei = 0; ei < 2; ei++) {
        uintptr_t p = (uintptr_t)GetProcAddress(GetModuleHandleA(NULL), exports[ei]);
        if (!p) continue;
        uintptr_t blk0 = seh_read_ptr((void*)(p + FNAMEPOOL_BLOCKS_OFF));
        if (blk0 < 0x10000) continue;
        if (!fname_block0_matches_none(blk0)) continue;
        g_fnamepool_global = p;
        g_fnamepool_block0 = blk0;
        bridge_log("  FNamePool global=0x%llX (export '%s') block0=0x%llX fmt=%s",
                   (unsigned long long)p, exports[ei],
                   (unsigned long long)blk0,
                   g_fname_header_shift == 6 ? "UE5" : "UE4");
        return p;
    }

    /* Method 2: backref scan -- scan PAGE_READWRITE module regions for ptr==block0 */
    if (!g_fnamepool_block0) return 0;
    ModuleRegion rgn;
    if (!get_main_module(rgn)) return 0;
    uintptr_t mod_base = (uintptr_t)rgn.base;
    uintptr_t mod_end  = mod_base + rgn.size;

    uintptr_t cur = mod_base;
    while (cur < mod_end) {
        MEMORY_BASIC_INFORMATION mbi2 = {};
        if (!VirtualQuery((void*)cur, &mbi2, sizeof(mbi2))) { cur += 0x1000; continue; }
        uintptr_t rb = (uintptr_t)mbi2.BaseAddress;
        uintptr_t re = rb + mbi2.RegionSize;
        if (re > mod_end) re = mod_end;
        bool writable = (mbi2.State == MEM_COMMIT) &&
            (mbi2.Protect & (PAGE_READWRITE | PAGE_WRITECOPY |
                              PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY));
        if (writable) {
            for (uintptr_t scan = rb; scan < re - 8; scan += 8) {
                if (seh_read_ptr((void*)scan) != g_fnamepool_block0) continue;
                uintptr_t pool_cand = scan - FNAMEPOOL_BLOCKS_OFF;
                int32_t cur_blk = 0;
                __try { cur_blk = *(int32_t*)(pool_cand + 0x08); }
                __except(EXCEPTION_EXECUTE_HANDLER) { cur_blk = 9999; }
                if (cur_blk < 0 || cur_blk >= 128) continue;
                g_fnamepool_global = pool_cand;
                bridge_log("  FNamePool global=0x%llX (backref, CurrentBlock=%d)",
                           (unsigned long long)pool_cand, cur_blk);
                return pool_cand;
            }
        }
        cur = re;
    }
    bridge_log("  FNamePool global: not found");
    return 0;
}

/* Locate FNamePool block 0.
 * Method 1: export (also sets global). Method 2: VirtualQuery heap scan. */
static uintptr_t find_fnamepool_block0()
{
    if (g_fnamepool_block0) return g_fnamepool_block0;
    if (find_fnamepool_global()) return g_fnamepool_block0;

    MEMORY_BASIC_INFORMATION mbi = {};
    uintptr_t addr = 0x10000;
    int checked = 0;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return 0;
    uintptr_t mod_base = (uintptr_t)rgn.base;
    uintptr_t mod_end  = mod_base + rgn.size;

    while (addr < 0x800000000000ULL) {
        if (!VirtualQuery((void*)addr, &mbi, sizeof(mbi)))
            { addr += 0x10000; continue; }
        uintptr_t base = (uintptr_t)mbi.BaseAddress;
        uintptr_t end  = base + mbi.RegionSize;
        bool skip = (mbi.State != MEM_COMMIT)
            || !(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE
                                | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE))
            || (base < mod_end && end > mod_base)  /* overlaps module */
            || mbi.RegionSize < (64 * 1024);        /* < 64KB */
        if (!skip) {
            checked++;
            if (fname_block0_matches_none(base)) {
                uint16_t next_hdr = 0;
                __try { next_hdr = *(uint16_t*)(base + 6); }
                __except(EXCEPTION_EXECUTE_HANDLER) {}
                int next_len = fname_entry_len(next_hdr);
                if (next_hdr == 0 || (next_len >= 1 && next_len <= 256 && !(next_hdr & 1))) {
                    g_fnamepool_block0 = base;
                    bridge_log("  FNamePool block0=0x%llX fmt=%s (%d regions checked)",
                               (unsigned long long)base,
                               g_fname_header_shift == 6 ? "UE5" : "UE4", checked);
                    find_fnamepool_global();
                    return base;
                }
            }
        }
        addr = end;
    }
    bridge_log("  FNamePool block0: not found (%d regions)", checked);
    return 0;
}

/*
 * get_fname_cmpidx_for(target) -- search all FNamePool blocks for a name.
 * Returns full ComparisonIndex ((block_idx << 16) | word_off), or 0xFFFFFFFF.
 * Block 0 = engine names; block 1+ = game-specific names (need g_fnamepool_global).
 */
static uint32_t get_fname_cmpidx_for(const char* target)
{
    uintptr_t block0 = find_fnamepool_block0();
    if (!block0) return 0xFFFFFFFF;

    int tlen = (int)strlen(target);

    /* How many blocks to search */
    uint32_t max_block = 0;
    if (g_fnamepool_global) {
        int32_t cur_blk = 0;
        __try { cur_blk = *(int32_t*)(g_fnamepool_global + 0x08); }
        __except(EXCEPTION_EXECUTE_HANDLER) { cur_blk = 0; }
        if (cur_blk >= 0 && cur_blk < (int32_t)FNAMEPOOL_MAX_BLOCKS)
            max_block = (uint32_t)cur_blk;
    }

    for (uint32_t bi = 0; bi <= max_block; bi++) {
        uintptr_t block = (bi == 0) ? block0 : fname_get_block(bi);
        if (!block) continue;
        uintptr_t cursor  = block;
        uintptr_t blk_end = block + FNAMEPOOL_BLOCK_BYTES;
        while (cursor < blk_end - 2) {
            uint16_t hdr = 0;
            __try { hdr = *(uint16_t*)cursor; }
            __except(EXCEPTION_EXECUTE_HANDLER) { break; }
            if (hdr == 0) break;
            bool is_wide = (hdr & 1) != 0;
            int  len     = fname_entry_len(hdr);
            if (len < 1 || len > 512) break;
            if (!is_wide && len == tlen) {
                bool match = false;
                __try { match = (memcmp((void*)(cursor + 2), target, tlen) == 0); }
                __except(EXCEPTION_EXECUTE_HANDLER) {}
                if (match)
                    return (bi << 16) | (uint32_t)((cursor - block) >> 1);
            }
            int entry_bytes = 2 + (is_wide ? len * 2 : len);
            cursor += (uintptr_t)((entry_bytes + 1) & ~1);
        }
    }
    return 0xFFFFFFFF;
}

/*
 * resolve_fname(cmp_idx, buf, buf_size)
 *
 * Reverse lookup: ComparisonIndex -> ASCII string.
 * Returns buf (always NUL-terminated). On failure returns "?".
 */
static const char* resolve_fname(uint32_t cmp_idx, char* buf, int buf_size)
{
    if (buf_size < 2) { if (buf_size > 0) buf[0] = '\0'; return buf; }
    buf[0] = '?'; buf[1] = '\0';

    uint32_t block_idx = cmp_idx >> 16;
    uint32_t word_off  = cmp_idx & 0xFFFF;
    uintptr_t block = fname_get_block(block_idx);
    if (!block) return buf;

    uintptr_t entry_addr = block + (uintptr_t)word_off * 2;
    uint16_t hdr = 0;
    __try { hdr = *(uint16_t*)entry_addr; }
    __except(EXCEPTION_EXECUTE_HANDLER) { return buf; }

    if (hdr == 0) return buf;
    bool is_wide = (hdr & 1) != 0;
    int  len     = fname_entry_len(hdr);
    if (len < 1 || len > 512) return buf;

    int copy_len = (len < buf_size - 1) ? len : (buf_size - 1);
    if (!is_wide) {
        __try { memcpy(buf, (void*)(entry_addr + 2), copy_len); }
        __except(EXCEPTION_EXECUTE_HANDLER) { buf[0] = '?'; buf[1] = '\0'; return buf; }
    } else {
        /* Wide -> ASCII lossy conversion */
        __try {
            wchar_t* ws = (wchar_t*)(entry_addr + 2);
            for (int k = 0; k < copy_len; k++)
                buf[k] = (char)(ws[k] & 0x7F);
        }
        __except(EXCEPTION_EXECUTE_HANDLER) { buf[0] = '?'; buf[1] = '\0'; return buf; }
    }
    buf[copy_len] = '\0';
    return buf;
}

/* Helper: read an object's NamePrivate and ClassPrivate->NamePrivate as strings.
 * Writes to name_buf and class_buf. */
static void read_obj_names(void* obj, char* name_buf, int name_sz,
                           char* class_buf, int class_sz)
{
    name_buf[0] = '\0'; class_buf[0] = '\0';

    /* NamePrivate at UObjectBase+0x18, lo32 = ComparisonIndex */
    uint32_t name_idx = 0;
    __try { name_idx = *(uint32_t*)((uint8_t*)obj + 0x18); }
    __except(EXCEPTION_EXECUTE_HANDLER) { name_idx = 0xFFFFFFFF; }
    if (name_idx != 0xFFFFFFFF) resolve_fname(name_idx, name_buf, name_sz);

    /* ClassPrivate at UObjectBase+0x10 */
    uintptr_t class_ptr = seh_read_ptr((uint8_t*)obj + 0x10);
    if (class_ptr >= 0x10000) {
        uint32_t cls_name_idx = 0;
        __try { cls_name_idx = *(uint32_t*)((uint8_t*)class_ptr + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) { cls_name_idx = 0xFFFFFFFF; }
        if (cls_name_idx != 0xFFFFFFFF) resolve_fname(cls_name_idx, class_buf, class_sz);
    }
}

