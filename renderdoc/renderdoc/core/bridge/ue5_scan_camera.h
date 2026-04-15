/* ue5_scan_camera.h -- APlayerCameraManager, FMinimalViewInfo, cross-validation.
 * INCLUDED FROM ue5_engine.h ONLY -- do not include directly. */

/* ---- APlayerCameraManager via GUObjectArray + FName ---------------- */

/* APlayerCameraManager pointer. Set by find_camera_manager().
 * Used for direct FMinimalViewInfo memory write (camera override). */
static void* g_camera_manager_ptr = nullptr;

/*
 * find_camera_manager() -- scan GUObjectArray for an object whose class
 * FName matches "PlayerCameraManager" or "BP_PlayerCameraManager_C".
 *
 * Layout used:
 *   UObjectBase+0x08: ObjectFlags  (skip CDO if flag 0x10 set)
 *   UObjectBase+0x10: ClassPrivate
 *   ClassPrivate+0x18: ComparisonIndex (class FName)
 *   UObjectBase+0x20: OuterPrivate (owner APlayerController)
 *
 * Selection: prefer candidates whose OuterPrivate's class FName
 * contains "PlayerController".  Fall back to last non-CDO if none.
 */
static bool find_camera_manager()
{
    if (g_camera_manager_ptr) return true;
    if (!g_guobjectarray_found) return false;

    /* Build a list of candidate class FName indices to match against.
     * Stock UE5 class is "PlayerCameraManager".
     * Blueprint subclass is "BP_PlayerCameraManager_C" (common override). */
    const char* class_names[] = {
        "PlayerCameraManager",
        "BP_PlayerCameraManager_C",
        nullptr
    };

    uint32_t pcm_idx[2] = { 0xFFFFFFFF, 0xFFFFFFFF };
    int n_pcm = 0;
    for (int ni = 0; class_names[ni]; ni++) {
        uint32_t idx = get_fname_cmpidx_for(class_names[ni]);
        if (idx != 0xFFFFFFFF) {
            pcm_idx[n_pcm++] = idx;
            bridge_log("  find_camera_manager: FName('%s')=0x%X (block=%d word=0x%X)",
                       class_names[ni], idx, idx >> 16, idx & 0xFFFF);
        } else {
            bridge_log("  find_camera_manager: FName('%s') not in pool",
                       class_names[ni]);
        }
    }

    if (n_pcm == 0) {
        bridge_log("  find_camera_manager: no matching FName found -- "
                   "camera manager cannot be located via GUA scan");
        return false;
    }

    /* Look up "PlayerController" FName for outer validation. */
    uint32_t pc_idx = get_fname_cmpidx_for("PlayerController");
    bridge_log("  find_camera_manager: FName('PlayerController')=0x%X", pc_idx);

    struct PCMCandidate {
        int32_t index; void* obj;
        uint32_t flags; bool outer_is_pc;
        char class_name[64];
    };
    PCMCandidate candidates[8];
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

        /* Match against any of our candidate class FNames */
        bool matched = false;
        for (int ni = 0; ni < n_pcm; ni++) {
            if (cmp_idx == pcm_idx[ni]) { matched = true; break; }
        }
        if (!matched) continue;

        /* ObjectFlags at UObjectBase+0x08 -- skip CDOs */
        uint32_t obj_flags = 0;
        __try { obj_flags = *(uint32_t*)((uint8_t*)obj + 0x08); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        char obj_name[128], cls_name[128];
        read_obj_names(obj, obj_name, sizeof(obj_name), cls_name, sizeof(cls_name));

        if (obj_flags & 0x10) {
            bridge_log("  CameraManager [%d] 0x%p: CDO name='%s' class='%s' "
                       "flags=0x%X -- skipped",
                       i, obj, obj_name, cls_name, obj_flags);
            cdo_skipped++;
            continue;
        }

        /* Check if OuterPrivate is a PlayerController. */
        bool outer_is_pc = false;
        char outer_cls_name[128] = {0};
        uintptr_t outer = seh_read_ptr((uint8_t*)obj + 0x20);
        if (outer >= 0x10000 && outer < 0x800000000000ULL) {
            uintptr_t outer_class = seh_read_ptr((void*)(outer + 0x10));
            if (outer_class >= 0x10000) {
                uint32_t outer_cmp = 0;
                __try { outer_cmp = *(uint32_t*)((uint8_t*)outer_class + 0x18); }
                __except(EXCEPTION_EXECUTE_HANDLER) { outer_cmp = 0; }
                resolve_fname(outer_cmp, outer_cls_name, sizeof(outer_cls_name));
                if (pc_idx != 0xFFFFFFFF)
                    outer_is_pc = (outer_cmp == pc_idx);
            }
        }

        bridge_log("  CameraManager candidate #%d: [%d] obj=0x%p name='%s' "
                   "class='%s' flags=0x%X outer_class='%s' pc=%d",
                   n_candidates, i, obj, obj_name, cls_name,
                   obj_flags, outer_cls_name, (int)outer_is_pc);

        if (n_candidates < 8) {
            PCMCandidate& c = candidates[n_candidates];
            c.index = i; c.obj = obj; c.flags = obj_flags;
            c.outer_is_pc = outer_is_pc;
            strncpy(c.class_name, cls_name, sizeof(c.class_name) - 1);
            n_candidates++;
        } else {
            for (int j = 0; j < 7; j++) candidates[j] = candidates[j + 1];
            PCMCandidate& c = candidates[7];
            c.index = i; c.obj = obj; c.flags = obj_flags;
            c.outer_is_pc = outer_is_pc;
            strncpy(c.class_name, cls_name, sizeof(c.class_name) - 1);
        }
    }

    bridge_log("  find_camera_manager: %d non-CDO candidates, %d CDO skipped",
               n_candidates, cdo_skipped);

    if (n_candidates == 0) {
        bridge_log("  find_camera_manager: not found in %d objects -- "
                   "PCM may not be spawned yet; call __cam_mem_find after game loads",
                   num_elems);
        return false;
    }

    /* Log all candidates so cross-validation decisions are traceable */
    for (int c = 0; c < n_candidates; c++) {
        bridge_log("  find_camera_manager: candidate[%d] idx=%d obj=0x%p "
                   "class='%s' outer_pc=%d",
                   c, candidates[c].index, candidates[c].obj,
                   candidates[c].class_name, (int)candidates[c].outer_is_pc);
    }

    /* Selection priority:
     *   1. First candidate whose OuterPrivate is a PlayerController.
     *      (Most reliable: directly identifies the active game PCM.)
     *   2. Oldest (lowest GUA index) non-CDO candidate as fallback.
     *      cross_validate_camera() Path-D corrects if we pick wrong. */
    int best_c = -1;

    for (int c = 0; c < n_candidates; c++) {
        if (candidates[c].outer_is_pc) {
            best_c = c;
            break;
        }
    }

    if (best_c < 0) {
        best_c = 0;
        bridge_log("  CameraManager: no PlayerController outer found -- "
                   "using first (oldest) non-CDO candidate; "
                   "cross_validate_camera Path-D will correct if needed");
    }

    PCMCandidate& best = candidates[best_c];
    g_camera_manager_ptr = best.obj;
    bridge_log("  APlayerCameraManager SELECTED: [%d] obj=0x%p class='%s' "
               "outer_pc=%d (%d candidates)",
               best.index, best.obj, best.class_name,
               (int)best.outer_is_pc, n_candidates);

    if (g_debug_break_armed.exchange(false)) {
        bridge_log("  DEBUG BREAK: CameraManager found -- breaking into debugger");
        __debugbreak();
    }
    return true;
}

/* ---- FMinimalViewInfo direct memory access -------------------------
 *
 * APlayerCameraManager stores the active view in CameraCachePrivate
 * (FCameraCacheEntry).  We locate it at runtime via UClass property
 * reflection so the code is version-independent.
 *
 * UStruct layout (UE4SS PDB verified, UE5.00 - UE5.07, all identical):
 *   UObjectBase:        +0x00  (0x28 bytes)
 *   UField::Next:       +0x28  (UField*, 8 bytes -- UField total 0x30)
 *   UStruct::SuperStruct:  +0x40  (UStruct* -- 0x10 gap for UStruct internals)
 *   UStruct::Children:     +0x48  (UField*, legacy)
 *   UStruct::ChildProperties: +0x50 (FField*, UE4.25+ property chain)
 *
 * FField layout (UE4.25+):
 *   ClassPrivate:  +0x00
 *   Owner:         +0x08  (FFieldVariant, 16 bytes)
 *   Next:          +0x18  (FField*)
 *   NamePrivate:   +0x20  (FName -- ComparisonIndex at +0x20)
 *   FlagsPrivate:  +0x28
 *
 * FProperty extends FField:
 *   ArrayDim:      +0x30
 *   ElementSize:   +0x34
 *   PropertyFlags: +0x38  (uint64)
 *   RepIndex:      +0x40
 *   Condition:     +0x42
 *   [pad2]
 *   Offset_Internal: +0x44  (int32) <-- runtime struct offset we need
 *
 * FCameraCacheEntry:
 *   TimeStamp:  +0x00  (float, 4B)
 *   [pad 4 -- to align FMinimalViewInfo at 8-byte boundary for doubles]
 *   POV:        +0x08  (FMinimalViewInfo)
 *
 * FMinimalViewInfo -- UE5 LWC layout (FVector/FRotator = double):
 *   Location:  +0x00  (3 x double = 24B: X, Y, Z)
 *   Rotation:  +0x18  (3 x double = 24B: Pitch, Yaw, Roll)
 *   FOV:       +0x30  (float, 4B)
 *
 * FMinimalViewInfo -- legacy float layout (UE4 / non-LWC UE5):
 *   Location:  +0x00  (3 x float = 12B)
 *   Rotation:  +0x0C  (3 x float = 12B)
 *   FOV:       +0x18  (float)
 *   POV in FCameraCacheEntry: +0x10 (SIMD) or +0x04 (non-SIMD)
 */

/* Pointer to FMinimalViewInfo inside APlayerCameraManager.
 * Set by find_cam_pov().  Written by write_camera_mem() every tick. */
static uint8_t* g_cam_pov_ptr = nullptr;

/* True when the FMinimalViewInfo at g_cam_pov_ptr uses LWC double layout
 * (UE5 with Large World Coordinates: FVector/FRotator are double).
 * False for legacy float layout (UE4 / non-LWC UE5). */
static bool g_cam_pov_is_lwc = false;

/* Camera override state -- written by TCP cam_write command,
 * applied every tick while g_camera_override is true.
 * x/y/z/pitch/yaw/roll are double to match UE5 LWC precision. */
struct CameraMemState {
    double x, y, z;          /* UE5 cm (double for LWC) */
    double pitch, yaw, roll; /* degrees */
    float fov;
};
static CameraMemState g_cam_override_state = {0,0,0, 0,0,0, 90.0f};
/* g_camera_override declared at top of file (line ~294) -- single definition */

/*
 * ffield_find_offset() -- walk UClass::ChildProperties FField chain
 * and return Offset_Internal for the property matching prop_fname_idx.
 * Returns -1 if not found.
 */
/*
 * FField layout changed between UE5.02 and UE5.03 (FFieldVariant shrank).
 * UE4SS PDB verified:
 *
 *   Era        | Next  | NamePrivate | FProperty::Offset_Internal
 *   -----------|-------|-------------|----------------------------
 *   5.00-5.02  | +0x20 | +0x28       | +0x4C
 *   5.03-5.07  | +0x18 | +0x20       | +0x44
 *
 * We detect at runtime by probing: walk the chain with both layouts,
 * check which one produces a readable, non-zero FName index.
 */
static int32_t ffield_find_offset_era(void* child_props_ptr,
                                      uint32_t prop_fname_idx,
                                      int32_t next_off,
                                      int32_t name_off,
                                      int32_t offset_off)
{
    void* field = child_props_ptr;
    int walked = 0;
    for (int limit = 1024; field && limit > 0; limit--) {
        uint32_t fname_idx = 0;
        __try { fname_idx = *(uint32_t*)((uint8_t*)field + name_off); }
        __except(EXCEPTION_EXECUTE_HANDLER) {
            bridge_log("  ffield_era(name+0x%X): AV at field=0x%p after %d props",
                       name_off, field, walked);
            break;
        }

        if (fname_idx == prop_fname_idx) {
            int32_t off = -1;
            __try { off = *(int32_t*)((uint8_t*)field + offset_off); }
            __except(EXCEPTION_EXECUTE_HANDLER) { return -1; }
            return off;
        }

        walked++;
        uintptr_t next = seh_read_ptr((uint8_t*)field + next_off);
        if (!next || next == (uintptr_t)field) {
            bridge_log("  ffield_era(name+0x%X): chain end after %d props (next=%s)",
                       name_off, walked, !next ? "null" : "self-loop");
            break;
        }
        field = (void*)next;
    }
    return -1;
}

static int32_t ffield_find_offset(void* uclass_or_ustruct,
                                  uint32_t prop_fname_idx)
{
    /* UStruct::ChildProperties -- offset from layout (0x50 all known UE5/UE4.27) */
    uintptr_t child_props = seh_read_ptr((uint8_t*)uclass_or_ustruct + g_ue_layout->ustruct_childprops_off);
    if (!child_props || child_props < 0x10000) {
        bridge_log("  ffield: class=0x%p ChildProperties@+0x50=null/invalid",
                   uclass_or_ustruct);
        return -1;
    }

    /* Log first property to diagnose FField era misdetection */
    uint32_t first_fname_5x = 0, first_fname_4x = 0;
    __try { first_fname_5x = *(uint32_t*)((uint8_t*)child_props + 0x20); } /* UE5.03+ name */
    __except(EXCEPTION_EXECUTE_HANDLER) {}
    __try { first_fname_4x = *(uint32_t*)((uint8_t*)child_props + 0x28); } /* UE5.00-5.02 name */
    __except(EXCEPTION_EXECUTE_HANDLER) {}
    char n5[32]={0}, n4[32]={0};
    resolve_fname(first_fname_5x, n5, sizeof(n5));
    resolve_fname(first_fname_4x, n4, sizeof(n4));
    bridge_log("  ffield: class=0x%p children=0x%llX "
               "first_prop_5x='%s'(0x%X) first_prop_4x='%s'(0x%X)",
               uclass_or_ustruct, (unsigned long long)child_props,
               n5, first_fname_5x, n4, first_fname_4x);

    void* fp = (void*)child_props;

    /* Try layout-specified FField era first */
    int32_t off = ffield_find_offset_era(fp, prop_fname_idx,
                                         g_ue_layout->ffield_next_off,
                                         g_ue_layout->ffield_name_off,
                                         g_ue_layout->fprop_offset_off);
    if (off >= 0) {
        bridge_log("  ffield: found at 0x%X via %s era (next=0x%X,name=0x%X,off=0x%X)",
                   off, g_ue_layout->name,
                   g_ue_layout->ffield_next_off,
                   g_ue_layout->ffield_name_off,
                   g_ue_layout->fprop_offset_off);
        return off;
    }

    /* Fall back to the other era (for games that don't match the layout exactly) */
    bool primary_is_era2 = (g_ue_layout->ffield_next_off == 0x18);
    int alt_next = primary_is_era2 ? 0x20 : 0x18;
    int alt_name = primary_is_era2 ? 0x28 : 0x20;
    int alt_off  = primary_is_era2 ? 0x4C : 0x44;
    off = ffield_find_offset_era(fp, prop_fname_idx, alt_next, alt_name, alt_off);
    if (off >= 0) {
        bridge_log("  ffield: found at 0x%X via alt era (next=0x%X,name=0x%X,off=0x%X) "
                   "-- layout mismatch?",
                   off, alt_next, alt_name, alt_off);
    } else {
        bridge_log("  ffield: property 0x%X not found in either FField era", prop_fname_idx);
    }
    return off;
}

/* forward declaration: defined after find_cam_pov() */
static bool find_cam_pov_scan();

/*
 * find_cam_pov() -- locate FMinimalViewInfo inside g_camera_manager_ptr.
 *
 * Priority order:
 * 1. Layout cam_pov_direct_off (non-zero = confirmed offset for this UE version).
 *    Skips FField + scan entirely.  Fastest path.
 * 2. FField reflection: look up FName("CameraCachePrivate"), walk UClass chain.
 *    Correct path when reflection data is complete.
 * 3. Memory scan fallback: find_cam_pov_scan().
 *    Used when FField chain is truncated (e.g. transient properties stripped).
 */
static bool find_cam_pov()
{
    if (g_cam_pov_ptr) return true;
    if (!g_camera_manager_ptr) return false;

    /* Path 1: direct offset from layout (fastest -- no FField, no scan) */
    if (g_ue_layout->cam_pov_direct_off != 0) {
        uint8_t* pov = (uint8_t*)g_camera_manager_ptr + g_ue_layout->cam_pov_direct_off;
        float fov_val = 0.0f;
        __try { fov_val = *(float*)(pov + g_ue_layout->fmvi_fov); }
        __except(EXCEPTION_EXECUTE_HANDLER) {
            bridge_log("  find_cam_pov: AV at direct offset manager+0x%X",
                       g_ue_layout->cam_pov_direct_off);
            goto fallback_ffield;
        }
        if (!isfinite(fov_val) || fov_val < 1.0f || fov_val > 179.0f) {
            bridge_log("  find_cam_pov: direct offset manager+0x%X FOV=%.2f "
                       "invalid -- falling back to FField",
                       g_ue_layout->cam_pov_direct_off, fov_val);
            goto fallback_ffield;
        }
        g_cam_pov_ptr    = pov;
        g_cam_pov_is_lwc = g_ue_layout->fmvi_is_lwc;
        bridge_log("  find_cam_pov: DIRECT at manager+0x%X FOV=%.1f (%s)",
                   g_ue_layout->cam_pov_direct_off, fov_val,
                   g_cam_pov_is_lwc ? "LWC-double" : "float");
        return true;
    }

    fallback_ffield:

    /* Get UClass of the camera manager */
    void* uclass = (void*)seh_read_ptr((uint8_t*)g_camera_manager_ptr + 0x10);
    if (!uclass || (uintptr_t)uclass < 0x10000) {
        bridge_log("  find_cam_pov: invalid UClass pointer at mgr+0x10");
        return false;
    }
    {
        char cls_name[64] = {0};
        uint32_t cls_fname = 0;
        __try { cls_fname = *(uint32_t*)((uint8_t*)uclass + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) {}
        resolve_fname(cls_fname, cls_name, sizeof(cls_name));
        bridge_log("  find_cam_pov: manager=0x%p class=0x%p('%s')",
                   g_camera_manager_ptr, uclass, cls_name);
    }

    /* Resolve FName for the property we're searching */
    uint32_t cc_fname = get_fname_cmpidx_for("CameraCachePrivate");
    if (cc_fname == 0xFFFFFFFF) {
        bridge_log("  find_cam_pov: FName('CameraCachePrivate') not in FNamePool");
        return false;
    }
    bridge_log("  find_cam_pov: FName('CameraCachePrivate')=0x%X", cc_fname);

    /* Walk UClass and its SuperStruct chain */
    int32_t cc_off = -1;
    void* cls = uclass;
    char cls_name[64];
    for (int depth = 0; cls && depth < 16 && cc_off < 0; depth++) {
        resolve_fname(*(uint32_t*)((uint8_t*)cls + 0x18), cls_name, sizeof(cls_name));
        bridge_log("  find_cam_pov: [depth %d] searching class '%s'(0x%p)",
                   depth, cls_name, cls);
        cc_off = ffield_find_offset(cls, cc_fname);
        if (cc_off >= 0) {
            bridge_log("  find_cam_pov: CameraCachePrivate at offset 0x%X "
                       "(found in class '%s', depth=%d)",
                       cc_off, cls_name, depth);
            break;
        }
        cls = (void*)seh_read_ptr((uint8_t*)cls + g_ue_layout->ustruct_super_off); /* SuperStruct */
        if ((uintptr_t)cls < 0x10000) {
            bridge_log("  find_cam_pov: SuperStruct chain ended at depth %d", depth);
            break;
        }
    }

    if (cc_off < 0) {
        bridge_log("  find_cam_pov: CameraCachePrivate property not found "
                   "in UClass chain -- trying memory scan fallback");
        return find_cam_pov_scan();
    }

    /* Try POV-in-cache offsets. Layout provides the primary; two hardcoded
     * fallbacks cover the other known layout variants. */
    struct { int32_t pov_in_cache; int32_t fov_in_pov; bool is_lwc; } trials[] = {
        { g_ue_layout->fcce_pov_off, g_ue_layout->fmvi_fov, g_ue_layout->fmvi_is_lwc },
        { 0x08, 0x30, true  },   /* LWC double fallback */
        { 0x10, 0x18, false },   /* SIMD float fallback */
        { 0x04, 0x18, false },   /* non-SIMD float fallback */
    };
    /* deduplicate: skip trial[0] copy if it matches trial[1] or [2] */
    int num_trials = 4;

    for (int t = 0; t < num_trials; t++) {
        /* skip duplicate of trial[0] in trials[1..3] */
        if (t > 0 && trials[t].pov_in_cache == trials[0].pov_in_cache) continue;
        int32_t pov_off = cc_off + trials[t].pov_in_cache;
        uint8_t* pov_candidate = (uint8_t*)g_camera_manager_ptr + pov_off;
        float fov_val = 0.0f;
        __try { fov_val = *(float*)(pov_candidate + trials[t].fov_in_pov); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        bridge_log("  find_cam_pov: trial[%d] POV at manager+0x%X "
                   "(fov_off=+0x%X) FOV=%.2f",
                   t, pov_off, trials[t].fov_in_pov, fov_val);

        if (fov_val >= 1.0f && fov_val <= 179.0f) {
            g_cam_pov_ptr    = pov_candidate;
            g_cam_pov_is_lwc = trials[t].is_lwc;
            bridge_log("  FMinimalViewInfo confirmed at 0x%p "
                       "(FOV=%.1f deg, layout=%s)",
                       g_cam_pov_ptr, fov_val,
                       g_cam_pov_is_lwc ? "LWC-double" : "float");
            return true;
        }
    }

    bridge_log("  find_cam_pov: FOV out of range [1,179] at all 3 offsets");
    return false;
}

/*
 * find_cam_pov_scan() -- fallback when FField reflection fails.
 *
 * In some UE5 builds CameraCachePrivate is not reflected (no UPROPERTY),
 * so ffield_find_offset returns -1.  Instead, scan the APlayerCameraManager
 * object for a 7-float sequence that looks like FMinimalViewInfo:
 *   +0x00 Location.X  (finite float, any value)
 *   +0x04 Location.Y
 *   +0x08 Location.Z
 *   +0x0C Rotation.Pitch  (in [-90, 90])
 *   +0x10 Rotation.Yaw    (in [-360, 360])
 *   +0x14 Rotation.Roll   (in [-360, 360])
 *   +0x18 FOV             (in [1, 179])
 *
 * Scans manager+0x200 .. manager+0x900 in 4-byte steps.
 * Logs ALL candidates found (for diagnostics).
 * Picks the first valid candidate that also has a finite Location.
 */
/*
 * Scan pass: try a specific FMinimalViewInfo layout.
 * is_lwc=true:  3 doubles (Location) + 3 doubles (Rotation) + float FOV at +0x30
 * is_lwc=false: 3 floats  (Location) + 3 floats  (Rotation) + float FOV at +0x18
 * step: 8 for LWC (double-aligned), 4 for float.
 */
static bool find_cam_pov_scan_pass(bool is_lwc)
{
    uint8_t* mgr = (uint8_t*)g_camera_manager_ptr;
    const int32_t SCAN_START = 0x200;
    const int32_t SCAN_END   = 0x900;
    const int32_t step       = is_lwc ? 8 : 4;

    int found_count = 0;
    uint8_t* best_nz = nullptr;  /* first candidate with real (non-zero) xyz */
    uint8_t* best_z  = nullptr;  /* first candidate with any valid xyz */

    for (int32_t off = SCAN_START; off <= SCAN_END; off += step) {
        uint8_t* pov = mgr + off;
        float fov = 0.0f;
        double px = 0.0, py = 0.0, pz = 0.0;
        double pitch = 0.0, yaw = 0.0, roll = 0.0;

        if (is_lwc) {
            /* LWC: Location and Rotation are doubles, FOV float at +0x30 */
            __try {
                px    = *(double*)(pov + 0x00);
                py    = *(double*)(pov + 0x08);
                pz    = *(double*)(pov + 0x10);
                pitch = *(double*)(pov + 0x18);
                yaw   = *(double*)(pov + 0x20);
                roll  = *(double*)(pov + 0x28);
                fov   = *(float* )(pov + 0x30);
            }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
        } else {
            /* float: Location and Rotation are floats, FOV float at +0x18 */
            float fx, fy, fz, fp, fy2, fr;
            __try {
                fx  = *(float*)(pov + 0x00);
                fy  = *(float*)(pov + 0x04);
                fz  = *(float*)(pov + 0x08);
                fp  = *(float*)(pov + 0x0C);
                fy2 = *(float*)(pov + 0x10);
                fr  = *(float*)(pov + 0x14);
                fov = *(float*)(pov + 0x18);
            }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
            px = fx; py = fy; pz = fz;
            pitch = fp; yaw = fy2; roll = fr;
        }

        /* Strict validation: reject NaN/Inf in all fields */
        if (!isfinite(fov)   || fov < 1.0f || fov > 179.0f) continue;
        if (!isfinite(pitch) || pitch < -91.0 || pitch > 91.0) continue;
        if (!isfinite(yaw)   || yaw  < -360.0 || yaw  > 360.0) continue;
        if (!isfinite(roll)  || roll < -360.0 || roll > 360.0) continue;
        if (!isfinite(px) || !isfinite(py) || !isfinite(pz)) continue;

        /* Prefer candidates with real (non-zero) world position.
         * Zero-xyz candidates are likely uninitialized cache entries or
         * default-constructed structs that accidentally pass float checks. */
        bool has_real_pos = (fabs(px) > 1.0 || fabs(py) > 1.0 || fabs(pz) > 1.0);

        found_count++;
        bridge_log("  cam_scan(%s) #%d at manager+0x%X: "
                   "xyz=(%.1f,%.1f,%.1f) pyr=(%.2f,%.2f,%.2f) fov=%.1f%s",
                   is_lwc ? "LWC" : "float",
                   found_count, off,
                   (float)px, (float)py, (float)pz,
                   (float)pitch, (float)yaw, (float)roll, fov,
                   has_real_pos ? " <-- REAL POS" : "");

        if (has_real_pos && !best_nz) best_nz = pov;   /* first with real position */
        if (!best_z) best_z = pov;                     /* first valid (any position) */
    }

    uint8_t* best = best_nz ? best_nz : best_z;
    if (!best) return false;

    if (best_nz)
        bridge_log("  cam_scan: selected non-zero-pos candidate (manager+0x%X)",
                   (int32_t)(best - (uint8_t*)g_camera_manager_ptr));
    else
        bridge_log("  cam_scan: no real-pos candidate; using first valid (manager+0x%X)",
                   (int32_t)(best - (uint8_t*)g_camera_manager_ptr));

    g_cam_pov_ptr    = best;
    g_cam_pov_is_lwc = is_lwc;
    bridge_log("  FMinimalViewInfo SCAN found at 0x%p (manager+0x%X, %s). "
               "Run __cam_mem_find again after level loads if wrong.",
               g_cam_pov_ptr,
               (int32_t)(g_cam_pov_ptr - mgr),
               is_lwc ? "LWC-double" : "float");
    return true;
}

static bool find_cam_pov_scan()
{
    if (!g_camera_manager_ptr) return false;

    bridge_log("  find_cam_pov_scan: trying LWC-double layout first "
               "[+0x200..+0x900] step=8");
    if (find_cam_pov_scan_pass(true)) return true;

    bridge_log("  find_cam_pov_scan: LWC pass found nothing -- "
               "trying float layout step=4");
    if (find_cam_pov_scan_pass(false)) return true;

    bridge_log("  find_cam_pov_scan: no candidate in either layout -- "
               "game may be in loading screen (FOV/Rotation are 0)");
    return false;
}

/* Read current camera state directly from FMinimalViewInfo */
static bool read_camera_mem(CameraMemState& out)
{
    if (!g_cam_pov_ptr) return false;
    __try {
        if (g_cam_pov_is_lwc) {
            out.x     = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_x);
            out.y     = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_y);
            out.z     = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_z);
            out.pitch = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_pitch);
            out.yaw   = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_yaw);
            out.roll  = *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_roll);
            out.fov   = *(float* )(g_cam_pov_ptr + g_ue_layout->fmvi_fov);
        } else {
            out.x     = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_x);
            out.y     = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_y);
            out.z     = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_z);
            out.pitch = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_pitch);
            out.yaw   = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_yaw);
            out.roll  = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_roll);
            out.fov   = *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_fov);
        }
        return true;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        bridge_log("  read_camera_mem: AV at 0x%p -- clearing pov ptr",
                   g_cam_pov_ptr);
        g_cam_pov_ptr = nullptr;
        return false;
    }
}

/* Write camera state directly to FMinimalViewInfo.
 * Called from tick thread every frame while g_camera_override is true.
 * This fights the game's per-frame camera update without needing hooks. */
static bool write_camera_mem(const CameraMemState& s)
{
    if (!g_cam_pov_ptr) return false;
    __try {
        if (g_cam_pov_is_lwc) {
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_x) = s.x;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_y) = s.y;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_z) = s.z;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_pitch) = s.pitch;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_yaw)   = s.yaw;
            *(double*)(g_cam_pov_ptr + g_ue_layout->fmvi_roll)  = s.roll;
            *(float* )(g_cam_pov_ptr + g_ue_layout->fmvi_fov)   = s.fov;
        } else {
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_x) = (float)s.x;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_y) = (float)s.y;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_loc_z) = (float)s.z;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_pitch) = (float)s.pitch;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_yaw)   = (float)s.yaw;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_roll)  = (float)s.roll;
            *(float*)(g_cam_pov_ptr + g_ue_layout->fmvi_fov)   = s.fov;
        }
        return true;
    }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        bridge_log("  write_camera_mem: AV at 0x%p -- clearing pov ptr",
                   g_cam_pov_ptr);
        g_cam_pov_ptr = nullptr;
        return false;
    }
}

/* ---- Camera cross-validation: LP chain + GEngine render path ------- *
 *
 * Strategy (user design):
 *   Path A -- GUObjectArray FName scan:
 *     Scan for class FName "PlayerCameraManager" / "BP_PlayerCameraManager_C".
 *     Problem: BP subclass name varies per game.
 *
 *   Path B -- LocalPlayer -> PlayerController pointer walk:
 *     g_localplayer_ptr + 0x30 -> APlayerController*
 *     FField reflection on PC's UClass -> PlayerCameraManager field offset
 *     Read APlayerCameraManager* from that offset.
 *     Advantage: game-agnostic, works with any PC/PCM subclass name.
 *
 *   Path C -- GEngine render viewport sanity check:
 *     GEngine (UGameEngine) + 0x200 -> UGameViewportClient* (stable UE5)
 *     UGameViewportClient + 0x78 -> UWorld*
 *     Compare with g_world_ptr to confirm GEngine is correct.
 *
 * Cross-validation rule:
 *   Both A and B found, same address -> CONFIRMED, high confidence.
 *   Only B found (LP chain) -> use B; A scan found wrong object (wrong FName).
 *   Only A found -> keep A, log warning.
 *   Neither -> no camera control.
 *
 * UPlayer::PlayerController offset derivation (UE4SS PDB, all UE5):
 *   UObjectBase: 0x28 bytes
 *   FExec secondary vptr: +0x28 (= g_fexec_offset, 8 bytes)
 *   PlayerController (TObjectPtr<APlayerController>): +0x30
 *   CurrentNetSpeed: +0x38  <- first listed field in UE4SS template
 *
 * UEngine::GameViewport (UGameViewportClient*): +0x200 (stable UE5.00-5.07)
 * UGameViewportClient::World (UWorld*): +0x78 (stable UE5.00-5.07)
 */
/* All chain offsets now come from g_ue_layout (see UEVersionLayout above).
 * Use g_ue_layout->uplayer_pc_off, ->uengine_gvc_off, ->ugvc_world_off,
 * ->ulp_vc_off instead of the old #defines. */

/* Saved GVC pointer (set by validate_engine_viewport_chain, reused by
 * cross_validate_camera LP cross-check). */
static uintptr_t g_gvc_ptr = 0;

/*
 * get_playercontroller() -- read APlayerController* from ULocalPlayer.
 * UPlayer::PlayerController is at +0x30 (stable across all UE5).
 * Returns nullptr if ULocalPlayer not found or pointer invalid.
 */
static void* get_playercontroller()
{
    if (!g_localplayer_ptr) return nullptr;
    uintptr_t pc = seh_read_ptr((uint8_t*)g_localplayer_ptr + g_ue_layout->uplayer_pc_off);
    if (pc < 0x10000 || pc >= 0x800000000000ULL) return nullptr;
    return (void*)pc;
}

/*
 * find_camera_manager_via_lp() -- walk LocalPlayer -> PlayerController
 * -> FField reflection to find PlayerCameraManager.
 *
 * This is game-agnostic: it uses the actual APlayerController* in memory
 * (not FName scan), so it works regardless of subclass name.
 */
static void* find_camera_manager_via_lp()
{
    void* pc = get_playercontroller();
    if (!pc) {
        bridge_log("  cam_via_lp: PlayerController not found (LP+0x30 null)");
        return nullptr;
    }

    char pc_name[128] = {0}, pc_cls[128] = {0};
    read_obj_names(pc, pc_name, sizeof(pc_name), pc_cls, sizeof(pc_cls));
    bridge_log("  cam_via_lp: PlayerController=0x%p name='%s' class='%s'",
               pc, pc_name, pc_cls);

    /* Resolve FName for PlayerCameraManager property */
    uint32_t pcm_fname = get_fname_cmpidx_for("PlayerCameraManager");
    if (pcm_fname == 0xFFFFFFFF) {
        bridge_log("  cam_via_lp: FName('PlayerCameraManager') not in pool");
        return nullptr;
    }

    /* FField reflection: walk APlayerController UClass + SuperStruct chain */
    uintptr_t pc_class = seh_read_ptr((uint8_t*)pc + 0x10);
    if (pc_class < 0x10000) {
        bridge_log("  cam_via_lp: invalid PC UClass");
        return nullptr;
    }

    int32_t pcm_off = -1;
    void* cls = (void*)pc_class;
    char cls_name[64] = {0};
    for (int depth = 0; cls && depth < 20 && pcm_off < 0; depth++) {
        pcm_off = ffield_find_offset(cls, pcm_fname);
        if (pcm_off >= 0) {
            resolve_fname(*(uint32_t*)((uint8_t*)cls + 0x18), cls_name, sizeof(cls_name));
            bridge_log("  cam_via_lp: PlayerCameraManager at PC+0x%X "
                       "(found in class '%s', depth=%d)",
                       pcm_off, cls_name, depth);
            break;
        }
        cls = (void*)seh_read_ptr((uint8_t*)cls + g_ue_layout->ustruct_super_off); /* SuperStruct */
        if ((uintptr_t)cls < 0x10000) break;
    }

    if (pcm_off < 0) {
        bridge_log("  cam_via_lp: PlayerCameraManager property not found "
                   "in APlayerController UClass chain");
        return nullptr;
    }

    uintptr_t pcm = seh_read_ptr((uint8_t*)pc + pcm_off);
    if (pcm < 0x10000 || pcm >= 0x800000000000ULL) {
        bridge_log("  cam_via_lp: PCM pointer null/invalid at PC+0x%X", pcm_off);
        return nullptr;
    }

    char pcm_name[128] = {0}, pcm_cls[128] = {0};
    read_obj_names((void*)pcm, pcm_name, sizeof(pcm_name),
                   pcm_cls, sizeof(pcm_cls));
    bridge_log("  cam_via_lp: APlayerCameraManager=0x%p name='%s' class='%s'",
               (void*)pcm, pcm_name, pcm_cls);
    return (void*)pcm;
}

/*
 * validate_engine_viewport_chain() -- sanity check via render path.
 *
 * Reads GEngine -> GameViewport -> World and compares with g_world_ptr.
 * If they match, GEngine pointer is confirmed correct.
 * If they differ, log a warning (GEngine may point to wrong object or
 * g_world_ptr may be stale after a map change).
 */
static void validate_engine_viewport_chain()
{
    if (!g_engine_ptr) return;

    uintptr_t gvc = seh_read_ptr((uint8_t*)g_engine_ptr + g_ue_layout->uengine_gvc_off);
    if (gvc < 0x10000) {
        bridge_log("  GVC chain: GameViewport null at GEngine+0x%X",
                   g_ue_layout->uengine_gvc_off);
        return;
    }

    /* Detect TObjectPtr encoding: GEngine+0x200 may hold an encoded handle
     * rather than a raw heap pointer in UE5.4+ builds.
     *
     * Detection: always read LP->ViewportClient (LP+ulp_vc_off, always raw ptr
     * per UE4SS MemberVarLayout_5_07).  If LP gives a valid heap address that
     * differs from GEngine+0x200, GEngine+0x200 is encoded -- use LP value.
     *
     * Also catch the case where GVC is inside ANY module range (not just the
     * main EXE), since on some builds the encoded address falls in a DLL. */
    ModuleRegion rgn;
    bool gvc_in_binary = false;
    if (get_main_module(rgn)) {
        uintptr_t mod_lo = (uintptr_t)rgn.base;
        uintptr_t mod_hi = mod_lo + rgn.size;
        gvc_in_binary = (gvc >= mod_lo && gvc < mod_hi);
    }

    /* Always check LP+0x78 for authoritative GVC */
    uintptr_t lp_gvc = 0;
    bool lp_gvc_valid = false;
    if (g_localplayer_ptr) {
        lp_gvc = seh_read_ptr((uint8_t*)g_localplayer_ptr + g_ue_layout->ulp_vc_off);
        /* Heap pointer: must be in user-space range [64KB, 128 TB] */
        lp_gvc_valid = (lp_gvc >= 0x10000 && lp_gvc < 0x800000000000ULL);
        /* Reject if LP GVC is in binary range too */
        if (lp_gvc_valid && rgn.base &&
            lp_gvc >= (uintptr_t)rgn.base &&
            lp_gvc < (uintptr_t)rgn.base + rgn.size)
            lp_gvc_valid = false;
    }

    /* Prefer LP GVC when GVC from GEngine looks encoded (in binary or mismatches LP) */
    bool use_lp_gvc = false;
    if (lp_gvc_valid) {
        if (gvc_in_binary) {
            use_lp_gvc = true;
            bridge_log("  GVC chain: GEngine+0x%X=0x%p in binary range "
                       "(TObjectPtr-encoded) -- using LP+0x78=0x%p",
                       g_ue_layout->uengine_gvc_off, (void*)gvc, (void*)lp_gvc);
        } else if (lp_gvc != gvc) {
            /* Mismatch: LP raw ptr wins; GEngine value may be encoded DLL handle */
            use_lp_gvc = true;
            bridge_log("  GVC chain: GEngine+0x%X=0x%p != LP+0x78=0x%p -- "
                       "LP is authoritative (raw ptr), adopting LP GVC",
                       g_ue_layout->uengine_gvc_off, (void*)gvc, (void*)lp_gvc);
        }
    } else if (gvc_in_binary) {
        bridge_log("  GVC chain: GEngine+0x%X=0x%p in binary range and no valid LP GVC -- skip",
                   g_ue_layout->uengine_gvc_off, (void*)gvc);
        return;
    }

    if (use_lp_gvc)
        gvc = lp_gvc;

    g_gvc_ptr = gvc;  /* save for LP cross-check in cross_validate_camera */

    uintptr_t gvc_world = seh_read_ptr((void*)(gvc + g_ue_layout->ugvc_world_off));
    bridge_log("  GVC chain: GameViewport=0x%p  GVC->World=0x%p  "
               "g_world_ptr=0x%p",
               (void*)gvc, (void*)gvc_world, g_world_ptr);

    if (!g_world_ptr) {
        /* GVC chain found a world we didn't -- use it and lock it */
        if (gvc_world >= 0x10000 && gvc_world < 0x800000000000ULL) {
            bridge_log("  GVC chain: adopting world 0x%p from render path (locked)",
                       (void*)gvc_world);
            g_world_ptr = (void*)gvc_world;
            g_world_from_gua = true;  /* lock: prevent FExec hook spam */
        }
        return;
    }

    if (gvc_world == (uintptr_t)g_world_ptr) {
        bridge_log("  GVC chain: World CONFIRMED (render path == g_world_ptr)");
        g_world_from_gua = true;  /* re-lock each time we confirm */
    } else {
        bridge_log("  GVC chain: World MISMATCH -- render=0x%p stored=0x%p "
                   "(map change? stale pointer?)",
                   (void*)gvc_world, g_world_ptr);
        /* Prefer the render-path world: it's what's actually being drawn.
         * Set g_world_from_gua=true to prevent FExec sublevel spam. */
        if (gvc_world >= 0x10000 && gvc_world < 0x800000000000ULL) {
            bridge_log("  GVC chain: updating g_world_ptr -> 0x%p (locked)", (void*)gvc_world);
            g_world_ptr = (void*)gvc_world;
            g_world_from_gua = true;
        }
    }
}

/*
 * verify_lp_via_gvc() -- cross-check g_localplayer_ptr using saved GVC.
 *
 * ULocalPlayer::ViewportClient = +0x78 (UE4SS MemberVarLayout_5_07).
 * If LP->ViewportClient == g_gvc_ptr, the LP pointer is independently
 * confirmed via the GEngine render chain.
 */
static bool verify_lp_via_gvc()
{
    if (!g_localplayer_ptr || !g_gvc_ptr) return false;

    uintptr_t lp_gvc = seh_read_ptr((uint8_t*)g_localplayer_ptr + g_ue_layout->ulp_vc_off);
    if (lp_gvc == g_gvc_ptr) {
        bridge_log("  LP cross-check: LP+0x78->GVC=0x%p == g_gvc_ptr CONFIRMED",
                   (void*)lp_gvc);
        return true;
    }
    bridge_log("  LP cross-check: LP+0x78->GVC=0x%p != g_gvc_ptr=0x%p MISMATCH "
               "(stale LP or GVC?)",
               (void*)lp_gvc, (void*)g_gvc_ptr);
    return false;
}

/*
 * find_camera_manager_uuu_style() -- UUU-style fixed-offset probe.
 *
 * UUU uses chain: GEngine->GameViewport->LocalPlayer->PlayerController,
 * then reads PlayerCameraManager at a game-specific fixed offset from PC.
 * The commonly cited value is PC+0x2A8 for UE5 games, but the actual
 * offset shifts upward with each UE5 minor version as new members are added
 * to APlayerController before PlayerCameraManager.
 *
 * Known observed offsets (UE4SS PDB / community reports):
 *   UE4.27:   ~0x2A0
 *   UE5.00-5.03: ~0x2A8
 *   UE5.04-5.05: ~0x2E0-0x300
 *   UE5.06-5.07: ~0x300-0x360
 *
 * We probe 8 candidates in 8-byte steps covering the full range.
 * Used ONLY for cross-validation; Path B (FField reflection) is authoritative.
 *
 * Returns the first valid-looking CameraManager pointer, or nullptr.
 * Logs all candidates found.
 */
static void* find_camera_manager_uuu_style()
{
    void* pc = get_playercontroller();
    if (!pc) {
        bridge_log("  cam_uuu_probe: no PlayerController");
        return nullptr;
    }

    /* Pass 1: layout-defined range, FName class check (UUU-style) */
    bridge_log("  cam_uuu_probe: PC=0x%p range [0x%X..0x%X] step=%d (%s)",
               pc, g_ue_layout->pc_pcm_start, g_ue_layout->pc_pcm_end,
               g_ue_layout->pc_pcm_step, g_ue_layout->name);

    void* best = nullptr;
    for (int32_t probe = g_ue_layout->pc_pcm_start;
         probe <= g_ue_layout->pc_pcm_end;
         probe += g_ue_layout->pc_pcm_step) {
        uintptr_t candidate = 0;
        __try { candidate = *(uintptr_t*)((uint8_t*)pc + probe); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        if (candidate < 0x10000 || candidate >= 0x800000000000ULL) continue;

        /* Must have a valid vtable */
        uintptr_t vt = 0;
        __try { vt = *(uintptr_t*)candidate; }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
        if (vt < 0x10000) continue;

        /* Must have a valid UClass pointer at +0x10 */
        uintptr_t cls = 0;
        __try { cls = *(uintptr_t*)(candidate + 0x10); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
        if (cls < 0x10000) continue;

        /* Check class FName for "Camera" substring */
        uint32_t cls_fname = 0;
        __try { cls_fname = *(uint32_t*)(cls + 0x18); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        char cls_name[64] = {0};
        resolve_fname(cls_fname, cls_name, sizeof(cls_name));

        /* Require "CameraManager" specifically -- this avoids false positives from
         * DebugCameraHUD, DebugCameraController, CameraActor, CameraComponent, etc.
         * APlayerCameraManager and its BP subclasses all contain "CameraManager". */
        bool looks_like_cam = (strstr(cls_name, "CameraManager") != nullptr);
        bridge_log("  cam_uuu_probe: PC+0x%X=0x%p class='%s'%s",
                   probe, (void*)candidate, cls_name,
                   looks_like_cam ? " <-- CAMERA MANAGER" : "");

        if (looks_like_cam && !best) {
            best = (void*)candidate;
        }
    }

    if (best) return best;

    bridge_log("  cam_uuu_probe: FName probe found nothing in [0x%X..0x%X]",
               g_ue_layout->pc_pcm_start, g_ue_layout->pc_pcm_end);

    /*
     * Pass 2: direct pointer scan.
     *
     * If Path A already found g_camera_manager_ptr, scan the entire PC object
     * (offsets 0x100..0x800, step 8) for that exact address.  This cross-
     * validates Path A and discovers the actual PC::PlayerCameraManager field
     * offset even when the FName probe failed (wrong range, TObjectPtr, etc.).
     *
     * This scan also catches any valid-looking camera manager pointer even
     * when Path A has not run yet, by applying the same class-FName check
     * over the full 0x100..0x800 sweep.
     */
    bridge_log("  cam_uuu_probe: pass 2 -- full sweep PC+[0x100..0x800] step=8");

    uintptr_t known_mgr = (uintptr_t)g_camera_manager_ptr;

    for (int32_t probe = 0x100; probe <= 0x800; probe += 8) {
        uintptr_t candidate = 0;
        __try { candidate = *(uintptr_t*)((uint8_t*)pc + probe); }
        __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

        if (candidate < 0x10000 || candidate >= 0x800000000000ULL) continue;

        /* If we have a known manager from Path A, direct match is definitive */
        if (known_mgr && candidate == known_mgr) {
            bridge_log("  cam_uuu_probe: XVAL -- PC+0x%X == Path-A manager 0x%p "
                       "(exact ptr match, cross-validation SUCCESS)",
                       probe, (void*)candidate);
            /* Update layout pc_pcm_start/end so future FName probes hit this offset.
             * Not strictly needed since we return the pointer, but useful for logs. */
            return (void*)candidate;
        }

        /* No known manager yet: apply class FName check over full range */
        if (!known_mgr) {
            uintptr_t vt = 0;
            __try { vt = *(uintptr_t*)candidate; }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
            if (vt < 0x10000) continue;

            uintptr_t cls = 0;
            __try { cls = *(uintptr_t*)(candidate + 0x10); }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }
            if (cls < 0x10000) continue;

            uint32_t cls_fname = 0;
            __try { cls_fname = *(uint32_t*)(cls + 0x18); }
            __except(EXCEPTION_EXECUTE_HANDLER) { continue; }

            char cls_name[64] = {0};
            resolve_fname(cls_fname, cls_name, sizeof(cls_name));

            if (strstr(cls_name, "CameraManager")) {
                bridge_log("  cam_uuu_probe: pass2 PC+0x%X=0x%p class='%s' <-- CAMERA MANAGER",
                           probe, (void*)candidate, cls_name);
                if (!best) best = (void*)candidate;
            }
        }
    }

    if (!best && !known_mgr)
        bridge_log("  cam_uuu_probe: full sweep found no camera-class pointer");
    if (!best && known_mgr)
        bridge_log("  cam_uuu_probe: XVAL FAIL -- Path-A manager 0x%p "
                   "not found anywhere in PC+[0x100..0x800]",
                   (void*)known_mgr);
    return best;
}

/*
 * cross_validate_camera() -- run all four paths and pick best result.
 *
 * Called after find_camera_manager() (Path A, GUObjectArray FName scan)
 * and find_localplayer() are complete.
 *
 * Path A: GUObjectArray FName scan (g_camera_manager_ptr)
 * Path B: LP -> PC -> FField property reflection (find_camera_manager_via_lp)
 * Path C: GEngine -> GVC -> World sanity (validate_engine_viewport_chain)
 *         + LP -> GVC cross-check (verify_lp_via_gvc)
 * Path D: LP -> PC -> fixed-offset probe scan (find_camera_manager_uuu_style)
 *         mirrors UUU's approach; used for comparison only.
 *
 * Priority: B > A > D (FField runtime reflection is most reliable).
 */
static void cross_validate_camera()
{
    /* Path C: render viewport world sanity + save g_gvc_ptr */
    validate_engine_viewport_chain();

    /* Path C cont: LP -> GVC cross-check (verifies g_localplayer_ptr) */
    verify_lp_via_gvc();

    /* Path B: LP -> PC -> FField reflection for PlayerCameraManager offset */
    void* cam_b = find_camera_manager_via_lp();

    /* Path D: LP -> PC -> fixed-offset probe (UUU-style) */
    void* cam_d = find_camera_manager_uuu_style();

    /* Summarize all four paths */
    bridge_log("  camera cross-val summary: "
               "A(FName)=0x%p  B(FField)=0x%p  D(UUU-probe)=0x%p",
               g_camera_manager_ptr, cam_b, cam_d);

    /* Agreement checks */
    if (cam_d && g_camera_manager_ptr && cam_d == g_camera_manager_ptr) {
        bridge_log("  camera cross-val: A==D -- FName result confirmed by "
                   "PC direct-ref scan 0x%p  [XVAL OK]", cam_d);
    } else if (cam_d && g_camera_manager_ptr && cam_d != g_camera_manager_ptr) {
        bridge_log("  camera cross-val: A!=D WARNING -- "
                   "FName picked 0x%p but PC+0x%X refs 0x%p  "
                   "(multiple PCM instances; D is authoritative)",
                   g_camera_manager_ptr,
                   g_ue_layout->pc_pcm_start,   /* printed as hint only */
                   cam_d);
    }
    if (cam_d && cam_b && cam_d != cam_b) {
        bridge_log("  camera cross-val: B!=D -- FField and UUU-probe disagree "
                   "(FField wins; UUU offset may be wrong for this UE version)");
    } else if (cam_d && cam_b && cam_d == cam_b) {
        bridge_log("  camera cross-val: B==D -- FField and UUU-probe AGREE 0x%p",
                   cam_b);
    }

    /*
     * Priority for g_camera_manager_ptr: B > D > A
     *
     * Path D (PC direct-ref) is preferred over Path A (last-non-CDO heuristic)
     * when they disagree.  PC+offset is authoritative: it is the manager the
     * PlayerController actually calls UpdateCamera() on.  Path A's "last non-CDO"
     * heuristic fails when multiple PCM instances exist (e.g. after seamless
     * travel: old PCM lingers, new PCM at higher GUA index gets selected).
     */
    if (!cam_b && !g_camera_manager_ptr) {
        if (cam_d) {
            bridge_log("  camera cross-val: A+B failed, using D(PC-ref)=0x%p", cam_d);
            g_camera_manager_ptr = cam_d;
        } else {
            bridge_log("  camera cross-val: ALL paths failed -- no camera control");
        }
        return;
    }

    if (!g_camera_manager_ptr && cam_b) {
        bridge_log("  camera cross-val: A(FName) missed, using B(FField)=0x%p "
                   "(BP subclass?)", cam_b);
        g_camera_manager_ptr = cam_b;
        return;
    }

    if (cam_b) {
        /* B is authoritative when available */
        if (cam_b != g_camera_manager_ptr) {
            bridge_log("  camera cross-val: A!=B -- using B(FField)=0x%p "
                       "(overrides FName heuristic)", cam_b);
            g_camera_manager_ptr = cam_b;
            g_cam_pov_ptr = nullptr;
        } else {
            bridge_log("  camera cross-val: CONFIRMED -- A==B==0x%p%s",
                       g_camera_manager_ptr,
                       (cam_d == cam_b) ? " (D also agrees)" : "");
        }
        return;
    }

    /* B failed; A found something. Decide between A and D:
     * Prefer D over A when they disagree, but ONLY if D's FOV is valid. */
    if (cam_d && cam_d != g_camera_manager_ptr) {
        /* Prefer D over A when they disagree,
         * but ONLY if D's direct-offset FOV is valid. */
        float d_fov = 0.0f;
        if (g_ue_layout->cam_pov_direct_off) {
            uint8_t* d_pov = (uint8_t*)cam_d + g_ue_layout->cam_pov_direct_off;
            __try { d_fov = *(float*)(d_pov + g_ue_layout->fmvi_fov); }
            __except(EXCEPTION_EXECUTE_HANDLER) { d_fov = 0.0f; }
        }
        bool d_fov_valid = isfinite(d_fov) && d_fov >= 1.0f && d_fov <= 179.0f;
        if (!d_fov_valid) {
            bridge_log("  camera cross-val: A!=D (no B) -- "
                       "D's FOV=%.2f invalid, keeping A(FName)=0x%p",
                       d_fov, g_camera_manager_ptr);
        } else {
            bridge_log("  camera cross-val: A!=D (no B) -- "
                       "switching to D(PC-ref)=0x%p FOV=%.1f (was A=0x%p)",
                       cam_d, d_fov, g_camera_manager_ptr);
            g_camera_manager_ptr = cam_d;
            g_cam_pov_ptr = nullptr; /* invalidate: manager changed */
            return;
        }
    }

    bridge_log("  camera cross-val: B failed, keeping A(FName)=0x%p%s",
               g_camera_manager_ptr,
               (!cam_d) ? " (D also failed)" : " (A==D)");
}

