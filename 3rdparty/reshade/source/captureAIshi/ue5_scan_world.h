/* ue5_scan_world.h -- UWorld and ULocalPlayer scanner.
 * INCLUDED FROM ue5_engine.h ONLY -- do not include directly. */

/* ---- UWorld cross-validation via GEngine pointer chain --------------- */

/*
 * cross_validate_world(candidate)
 *
 * Verify that a UWorld candidate is reachable from GEngine's member chain.
 * Scans up to 3 levels of indirection, which covers:
 *   Level 1: GEngine+X == candidate  (direct pointer member)
 *   Level 2: GEngine+X -> obj+Y == candidate  (e.g. GameViewport->World)
 *   Level 3: GEngine+X -> obj+Y -> obj2+Z == candidate  (WorldList path:
 *            GEngine->WorldList.Data[i] -> FWorldContext->ThisCurrentWorld)
 *
 * Returns true if the candidate is confirmed reachable from GEngine.
 */
static bool cross_validate_world(void* candidate)
{
    if (!candidate || !g_engine_ptr) return false;

    uint8_t* eng = (uint8_t*)g_engine_ptr;
    uintptr_t target = (uintptr_t)candidate;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;

    /* Level 1: direct member in GEngine */
    for (int off = 48; off < 8192; off += 8) {
        uintptr_t val = seh_read_ptr(eng + off);
        if (val == target) {
            bridge_log("    XVAL: GEngine+0x%X == UWorld 0x%p (direct)", off, candidate);
            return true;
        }
    }

    /* Level 2 + 3: indirect */
    for (int off = 48; off < 8192; off += 8) {
        uintptr_t val = seh_read_ptr(eng + off);
        if (val < 0x10000 || val >= 0x7F0000000000ULL) continue;
        if (val == target) continue;  /* already checked */
        /* Skip module-range pointers (vtable/code, not data) */
        if (val >= mod_start && val < mod_end) continue;

        /* Level 2: scan sub-object (e.g. GameViewport) */
        for (int sub = 0; sub < 1024; sub += 8) {
            uintptr_t sv = seh_read_ptr((void*)(val + sub));
            if (sv == target) {
                bridge_log("    XVAL: GEngine+0x%X -> +0x%X == UWorld 0x%p (2-level)",
                           off, sub, candidate);
                return true;
            }

            /* Level 3: one more hop (covers WorldList indirection) */
            if (sv < 0x10000 || sv >= 0x7F0000000000ULL) continue;
            if (sv >= mod_start && sv < mod_end) continue;
            for (int sub2 = 0; sub2 < 512; sub2 += 8) {
                uintptr_t sv2 = seh_read_ptr((void*)(sv + sub2));
                if (sv2 == target) {
                    bridge_log("    XVAL: GEngine+0x%X -> +0x%X -> +0x%X == "
                               "UWorld 0x%p (3-level/WorldList)",
                               off, sub, sub2, candidate);
                    return true;
                }
            }
        }
    }

    return false;
}

/* ---- UWorld via GUObjectArray + FName -------------------------------- */

/*
 * find_uworld_via_guobjectarray()
 *
 * For each GUObjectArray entry:
 *   1. Read obj->ClassPrivate (UObjectBase+0x10)
 *   2. Read ClassPrivate->NamePrivate lo32 = ComparisonIndex
 *   3. Compare against FName("World")
 *   4. Validate outer chain: obj->OuterPrivate (UObjectBase+0x20) is non-null
 *      (= UPackage), and UPackage->OuterPrivate == null (root object).
 *
 * Requires: g_guobjectarray_found, FNamePool found (find_fnamepool_block0).
 */
static bool find_uworld_via_guobjectarray()
{
    if (!g_guobjectarray_found || !g_guobjectarray) return false;

    uint32_t world_idx = get_fname_cmpidx_for("World");
    if (world_idx == 0xFFFFFFFF) {
        bridge_log("  find_uworld: FName('World') not found in FNamePool");
        return false;
    }
    int32_t num_elems = guobjectarray_num_elements();
    bridge_log("  find_uworld: FName('World')=0x%X -- scanning %d objects",
               world_idx, num_elems);

    /* Collect non-CDO UWorld candidates.
     * RF_ClassDefaultObject = 0x10 in ObjectFlags (UObjectBase+0x08). */
    struct UWorldCandidate { int32_t index; void* obj; uintptr_t outer; uint32_t flags; };
    UWorldCandidate candidates[16];
    int n_candidates = 0;
    int class_hits = 0;
    int cdo_skipped = 0;

    for (int32_t i = 0; i < num_elems; i++) {
        if (i > 0 && (i % 50000) == 0)
            bridge_log("  find_uworld progress: %d/%d hits=%d", i, num_elems, class_hits);

        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x800000000000ULL) continue;

        /* ClassPrivate at UObjectBase+0x10 */
        uintptr_t class_ptr = seh_read_ptr((uint8_t*)obj + 0x10);
        if (class_ptr < 0x10000) continue;

        /* UClass.NamePrivate lo32 = ComparisonIndex */
        uint32_t cmp_idx = 0;
        __try { cmp_idx = *(uint32_t*)((uint8_t*)class_ptr + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        if (cmp_idx != world_idx) continue;
        class_hits++;

        /* ObjectFlags at UObjectBase+0x08 */
        uint32_t obj_flags = 0;
        __try { obj_flags = *(uint32_t*)((uint8_t*)obj + 0x08); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        /* Read object name + class name for diagnostic logging */
        char obj_name[128], cls_name[128];
        read_obj_names(obj, obj_name, sizeof(obj_name), cls_name, sizeof(cls_name));

        /* Skip CDOs (RF_ClassDefaultObject = 0x10) */
        if (obj_flags & 0x10) {
            bridge_log("  UWorld [%d] 0x%p: CDO name='%s' class='%s' flags=0x%X -- skipped",
                       i, obj, obj_name, cls_name, obj_flags);
            cdo_skipped++;
            continue;
        }

        /* OuterPrivate at UObjectBase+0x20 */
        uintptr_t outer = seh_read_ptr((uint8_t*)obj + 0x20);
        if (outer < 0x10000 || outer >= 0x800000000000ULL) continue;
        /* outer (UPackage) must be a root: its OuterPrivate == null */
        uintptr_t outer_outer = seh_read_ptr((uint8_t*)outer + 0x20);
        if (outer_outer != 0) continue;

        /* Also read outer's name */
        char outer_name[128], outer_cls[128];
        read_obj_names((void*)outer, outer_name, sizeof(outer_name),
                       outer_cls, sizeof(outer_cls));

        bridge_log("  UWorld candidate #%d: [%d] obj=0x%p name='%s' class='%s' "
                   "flags=0x%X outer=0x%llX outer_name='%s'",
                   n_candidates, i, obj, obj_name, cls_name,
                   obj_flags, (unsigned long long)outer, outer_name);

        if (n_candidates < 16) {
            candidates[n_candidates].index = i;
            candidates[n_candidates].obj   = obj;
            candidates[n_candidates].outer = outer;
            candidates[n_candidates].flags = obj_flags;
            n_candidates++;
        } else {
            for (int j = 0; j < 15; j++) candidates[j] = candidates[j + 1];
            candidates[15] = { i, obj, outer, obj_flags };
        }
    }

    bridge_log("  find_uworld: %d non-CDO candidates, %d CDO skipped, "
               "%d total class hits",
               n_candidates, cdo_skipped, class_hits);

    if (n_candidates == 0) {
        bridge_log("  UWorld not found via GUObjectArray (%d objects)", num_elems);
        return false;
    }

    /* --- Selection: cross-validate against GEngine's pointer chain ---
     * The active game UWorld is always reachable from GEngine (via WorldList
     * or GameViewport). CDOs and template worlds are NOT referenced. */
    void* best = nullptr;
    int best_idx = -1;

    if (g_engine_ptr) {
        for (int c = 0; c < n_candidates; c++) {
            if (cross_validate_world(candidates[c].obj)) {
                best = candidates[c].obj;
                best_idx = candidates[c].index;
                bridge_log("  UWorld [%d] 0x%p CONFIRMED by GEngine cross-validation",
                           candidates[c].index, candidates[c].obj);
                /* Don't break -- keep scanning to find the last confirmed
                 * (highest index, most recently created). */
            }
        }
    }

    /* Fallback: if cross-validation didn't confirm any (GEngine not found,
     * or WorldList layout unrecognized), pick the last non-CDO candidate. */
    if (!best) {
        best = candidates[n_candidates - 1].obj;
        best_idx = candidates[n_candidates - 1].index;
        bridge_log("  UWorld [%d] 0x%p selected (fallback: last non-CDO candidate)",
                   best_idx, best);
    }

    g_world_ptr = best;
    g_world_from_gua = true;

    if (g_debug_break_armed.exchange(false)) {
        bridge_log("  DEBUG BREAK: UWorld found -- breaking into debugger");
        __debugbreak();
    }
    return true;
}

/* ---- ULocalPlayer via GUObjectArray + FName ------------------------- */

/* ULocalPlayer object pointer. Set by find_localplayer().
 * Used to route gameplay commands (slomo, ToggleDebugCamera, etc.) via
 * ULocalPlayer::Exec -> APlayerController::Exec -> UCheatManager. */
static void* g_localplayer_ptr = nullptr;

/*
 * find_localplayer() -- scan GUObjectArray for an object whose class
 * FName matches "LocalPlayer" (multi-block search, handles block 5+).
 *
 * ClassPrivate at UObjectBase+0x10, NamePrivate at ClassPrivate+0x18.
 * ComparisonIndex is the full 32-bit value (block<<16 | word_off).
 * After finding the object, verify it has FExec at g_fexec_offset by
 * reading its secondary vtable.
 */
static bool find_localplayer()
{
    if (g_localplayer_ptr) return true;
    if (!g_guobjectarray_found) return false;

    uint32_t lp_idx = get_fname_cmpidx_for("LocalPlayer");
    if (lp_idx == 0xFFFFFFFF) {
        bridge_log("  find_localplayer: FName('LocalPlayer') not found "
                   "(FNamePool has %s)",
                   g_fnamepool_global ? "global" : "block0 only");
        return false;
    }
    bridge_log("  find_localplayer: FName('LocalPlayer')=0x%X (block=%d word=0x%X)",
               lp_idx, lp_idx >> 16, lp_idx & 0xFFFF);

    /* Look up "GameInstance" FName for outer validation.
     * The real LocalPlayer's OuterPrivate is a UGameInstance whose class
     * FName is "GameInstance" (or a subclass). CDO's outer is the UPackage. */
    uint32_t gi_idx = get_fname_cmpidx_for("GameInstance");
    bridge_log("  find_localplayer: FName('GameInstance')=0x%X",
               gi_idx);

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;

    struct LPCandidate {
        int32_t index; void* obj; uintptr_t fexec_vptr;
        uint32_t flags; bool outer_is_gi;
    };
    LPCandidate candidates[8];
    int n_candidates = 0;
    int cdo_skipped = 0;

    int32_t num_elems = guobjectarray_num_elements();
    for (int32_t i = 0; i < num_elems; i++) {
        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x800000000000ULL) continue;

        uintptr_t class_ptr = seh_read_ptr((uint8_t*)obj + 0x10);
        if (class_ptr < 0x10000) continue;

        uint32_t cmp_idx = 0;
        __try { cmp_idx = *(uint32_t*)((uint8_t*)class_ptr + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        if (cmp_idx != lp_idx) continue;

        /* ObjectFlags at UObjectBase+0x08 -- skip CDOs */
        uint32_t obj_flags = 0;
        __try { obj_flags = *(uint32_t*)((uint8_t*)obj + 0x08); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
        /* Read names for diagnostic logging */
        char obj_name[128], cls_name[128];
        read_obj_names(obj, obj_name, sizeof(obj_name), cls_name, sizeof(cls_name));

        if (obj_flags & 0x10) {
            bridge_log("  LocalPlayer [%d] 0x%p: CDO name='%s' class='%s' "
                       "flags=0x%X -- skipped",
                       i, obj, obj_name, cls_name, obj_flags);
            cdo_skipped++;
            continue;
        }

        /* Confirm FExec secondary vtable at g_fexec_offset */
        uintptr_t fexec_off  = g_fexec_offset ? g_fexec_offset : 0x28;
        uintptr_t lp_fexec_v = seh_read_ptr((uint8_t*)obj + fexec_off);
        if (lp_fexec_v < mod_start || lp_fexec_v >= mod_end) continue;

        /* Check if OuterPrivate is a GameInstance.
         * ULocalPlayer.OuterPrivate -> UGameInstance (class FName check). */
        bool outer_is_gi = false;
        char outer_cls_name[128] = {0};
        uintptr_t outer = seh_read_ptr((uint8_t*)obj + 0x20);
        if (outer >= 0x10000 && outer < 0x800000000000ULL) {
            uintptr_t outer_class = seh_read_ptr((void*)(outer + 0x10));
            if (outer_class >= 0x10000) {
                uint32_t outer_class_cmpidx = 0;
                __try { outer_class_cmpidx = *(uint32_t*)((uint8_t*)outer_class + 0x18); }
                __except(EXCEPTION_EXECUTE_HANDLER) { outer_class_cmpidx = 0; }
                resolve_fname(outer_class_cmpidx, outer_cls_name, sizeof(outer_cls_name));
                if (gi_idx != 0xFFFFFFFF)
                    outer_is_gi = (outer_class_cmpidx == gi_idx);
            }
        }

        bridge_log("  LocalPlayer candidate #%d: [%d] obj=0x%p name='%s' "
                   "class='%s' flags=0x%X fexec=0x%llX outer_class='%s' gi=%d",
                   n_candidates, i, obj, obj_name, cls_name,
                   obj_flags, (unsigned long long)lp_fexec_v,
                   outer_cls_name, (int)outer_is_gi);

        if (n_candidates < 8) {
            candidates[n_candidates] = { i, obj, lp_fexec_v,
                                         obj_flags, outer_is_gi };
            n_candidates++;
        } else {
            for (int j = 0; j < 7; j++) candidates[j] = candidates[j + 1];
            candidates[7] = { i, obj, lp_fexec_v, obj_flags, outer_is_gi };
        }
    }

    bridge_log("  find_localplayer: %d non-CDO candidates, %d CDO skipped",
               n_candidates, cdo_skipped);

    if (n_candidates == 0) {
        bridge_log("  find_localplayer: not found in %d objects", num_elems);
        return false;
    }

    /* Selection: prefer candidate whose outer is a GameInstance.
     * Among those, take the last (most recently created). */
    int best_c = -1;
    for (int c = n_candidates - 1; c >= 0; c--) {
        if (candidates[c].outer_is_gi) {
            best_c = c;
            break;
        }
    }
    /* Fallback: last non-CDO candidate. */
    if (best_c < 0) {
        best_c = n_candidates - 1;
        bridge_log("  LocalPlayer: no GameInstance outer found, "
                   "using last non-CDO candidate");
    }

    LPCandidate& best = candidates[best_c];
    g_localplayer_ptr = best.obj;
    bridge_log("  ULocalPlayer SELECTED: [%d] obj=0x%p fexec=0x%llX "
               "outer_gi=%d (%d candidates)",
               best.index, best.obj, (unsigned long long)best.fexec_vptr,
               (int)best.outer_is_gi, n_candidates);

    if (g_debug_break_armed.exchange(false)) {
        bridge_log("  DEBUG BREAK: LocalPlayer found -- breaking into debugger");
        __debugbreak();
    }
    return true;
}

