/* ue5_exec_hook.h -- FExec vtable multi-hook, console exec, gamethread dispatch.
 * INCLUDED FROM ue5_engine.h ONLY -- do not include directly. */

/* -- FExec multi-hook: scan GUObjectArray for FExec objects -------- */

/*
 * Install a hook on vtable[1] of a secondary FExec vtable.
 * Returns true if newly installed, false if already hooked.
 *
 * Reuses hooked_fexec_exec (defined later) which:
 *   1. Captures UWorld from the `world` parameter.
 *   2. Looks up the correct original in g_fexec_hook_table.
 *   3. Forwards to the original.
 */
static bool __fastcall hooked_fexec_exec(  /* forward decl */
    void* this_fexec, void* world, const wchar_t* cmd, void* ar);

static bool install_fexec_hook_on(uintptr_t fexec_vtable,
                                   uintptr_t primary_vptr,
                                   uintptr_t mod_start, uintptr_t mod_end)
{
    if (g_fexec_hook_count >= 64) {
        /* Silent: table full, stop scanning */
        return false;
    }

    /* Reject primary vtable */
    if (fexec_vtable == primary_vptr) return false;

    /* Check if already hooked */
    for (int i = 0; i < g_fexec_hook_count; i++) {
        if (g_fexec_hook_table[i].vtable_base == fexec_vtable)
            return false;  /* already done */
    }

    /* vtable[1] = Exec (the function we want to intercept) */
    uintptr_t* slot = (uintptr_t*)(fexec_vtable + 8);
    FExecExecFn orig = (FExecExecFn)seh_read_ptr((void*)slot);
    if (!orig || orig == (FExecExecFn)hooked_fexec_exec) return false;
    if (!validate_function_ptr((void*)orig)) return false;

    /* Make vtable page writable */
    DWORD old_prot = 0;
    if (!VirtualProtect(slot, 8, PAGE_READWRITE, &old_prot)) {
        bridge_log("  FExec hook: VirtualProtect failed (%d)",
                   GetLastError());
        return false;
    }
    *slot = (uintptr_t)hooked_fexec_exec;
    VirtualProtect(slot, 8, old_prot, &old_prot);

    FExecHookEntry& e = g_fexec_hook_table[g_fexec_hook_count++];
    e.vtable_base = fexec_vtable;
    e.slot        = slot;
    e.original    = orig;
    return true;
}

/*
 * Scan GUObjectArray for all UObjects that have a secondary FExec vtable
 * at offset 0x28 (= sizeof(UObject) = UE4SS default FExecVTableOffsetInLocalPlayer).
 *
 * This finds UGameEngine (already hooked), ULocalPlayer, and any other
 * FExec implementors. We hook all unique vtables.
 *
 * Caps at 200,000 objects to avoid blocking the game thread too long.
 * ULocalPlayer is created early and typically has index < 10,000.
 */
static void scan_guobjectarray_for_fexec_hooks()
{
    if (!g_guobjectarray_found || !g_guobjectarray) return;
    if (!g_engine_ptr) return;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;
    uintptr_t primary_vptr = seh_read_ptr(g_engine_ptr);  /* GEngine vtable */

    int32_t num_elems = guobjectarray_num_elements();
    int32_t scan_limit = (num_elems < 200000) ? num_elems : 200000;

    bridge_log("=== GUObjectArray FExec scan (%d objects, limit %d) ===",
               num_elems, scan_limit);

    int checked = 0;
    int hooked_new = 0;

    for (int32_t i = 0; i < scan_limit; i++) {
        void* obj = guobjectarray_get(i);
        if (!obj || (uintptr_t)obj < 0x10000) continue;
        if ((uintptr_t)obj >= 0x7F0000000000ULL) continue;

        checked++;

        /* Check for FExec vtable at UE4SS default offset 0x28 (= 40) */
        uintptr_t fexec_off = 0x28;
        uintptr_t fexec_vptr = seh_read_ptr((uint8_t*)obj + fexec_off);
        if (fexec_vptr < mod_start || fexec_vptr >= mod_end) continue;
        if (fexec_vptr == primary_vptr) continue;  /* skip primary */

        /* Validate: vtable[0] and vtable[1] must be valid functions
         * in module; 3-8 total entries (FExec signature). */
        void* fn0 = (void*)seh_read_ptr((void*)fexec_vptr);
        void* fn1 = (void*)seh_read_ptr((void*)(fexec_vptr + 8));
        if (!validate_function_ptr(fn0) || !validate_function_ptr(fn1))
            continue;

        int vcnt = 2;
        for (int vi = 2; vi < 9; vi++) {
            void* fn = (void*)seh_read_ptr((void*)(fexec_vptr + vi * 8));
            if (!validate_function_ptr(fn)) break;
            vcnt++;
        }
        if (vcnt < 3 || vcnt > 8) continue;

        /* This object has a valid FExec vtable -- hook it */
        if (install_fexec_hook_on(fexec_vptr, primary_vptr,
                                   mod_start, mod_end))
            hooked_new++;
    }

    bridge_log("  GUObjectArray scan done: checked=%d, new_hooks=%d "
               "total_hooks=%d", checked, hooked_new, g_fexec_hook_count);
}


/* -- FExec multi-hook: actual hook function and management --------- */

/*
 * THE hook function installed on all FExec vtable[1] slots.
 *
 * This implements UE4SS's ULocalPlayerExecPreCallback pattern:
 *   ULocalPlayer::Exec(UWorld* InWorld, cmd, ar) -- UWorld is param 2.
 *   GEngine::Exec  (UWorld* InWorld, cmd, ar)    -- same calling convention.
 *
 * When the game calls any registered FExec::Exec (GEngine or ULocalPlayer),
 * InWorld (rdx) is the live UWorld pointer.  We capture it here.
 *
 * Lookup: find the correct original by matching this_fexec's vtable
 * against g_fexec_hook_table[].vtable_base.
 */
static bool __fastcall hooked_fexec_exec(
    void* this_fexec, void* world, const wchar_t* cmd, void* ar)
{
    /* Capture UWorld from Exec parameter -- only as a FALLBACK when the
     * GUObjectArray scan has not found it yet.  The GUA scan is reliable
     * (validates class FName + outer chain); the hook sees many different
     * pointers per frame, most of which are NOT the real game UWorld. */
    if (!g_world_from_gua &&
        world && (uintptr_t)world > 0x10000 &&
        (uintptr_t)world < 0x7F0000000000ULL)
    {
        if (g_world_ptr != world) {
            g_world_ptr = world;
            bridge_log("HOOK: UWorld captured 0x%p (this_fexec=0x%p) [fallback]",
                       world, this_fexec);
        }
    }

    /* Dispatch to correct original via vtable lookup.
     * this_fexec points to the FExec subobject; its first qword is
     * the secondary vtable pointer (same key we stored at install). */
    uintptr_t vtable = seh_read_ptr(this_fexec);
    for (int i = 0; i < g_fexec_hook_count; i++) {
        if (g_fexec_hook_table[i].vtable_base == vtable)
            return g_fexec_hook_table[i].original(
                this_fexec, world, cmd, ar);
    }

    /* Fallback: vtable not in table (should not happen).
     * Return false rather than crashing. */
    bridge_log("HOOK: vtable 0x%llX not in hook table -- no-op",
               (unsigned long long)vtable);
    return false;
}

/*
 * Install FExec hook on GEngine (called after find_fexec_vtable()).
 * Also installs via GUObjectArray scan if available.
 * This replaces the old install_exec_hook().
 */
static bool install_all_fexec_hooks()
{
    if (!g_engine_ptr || !g_fexec_offset) return false;

    ModuleRegion rgn;
    if (!get_main_module(rgn)) return false;
    uintptr_t mod_start = (uintptr_t)rgn.base;
    uintptr_t mod_end   = mod_start + rgn.size;
    uintptr_t primary_vptr = seh_read_ptr(g_engine_ptr);

    bridge_log("=== Installing FExec hooks ===");

    /* Always hook GEngine's FExec (already found by find_fexec_vtable) */
    uint8_t* eng = (uint8_t*)g_engine_ptr;
    uintptr_t engine_fexec_vtable = seh_read_ptr(eng + g_fexec_offset);
    int n = g_fexec_hook_count;
    install_fexec_hook_on(engine_fexec_vtable, primary_vptr,
                          mod_start, mod_end);
    if (g_fexec_hook_count > n)
        bridge_log("  GEngine FExec hooked (vtable=0x%llX)",
                   (unsigned long long)engine_fexec_vtable);

    /* Scan GUObjectArray for additional FExec objects (ULocalPlayer etc.) */
    if (g_guobjectarray_found)
        scan_guobjectarray_for_fexec_hooks();

    bridge_log("  Total FExec hooks: %d", g_fexec_hook_count);
    return g_fexec_hook_count > 0;
}

static void uninstall_all_fexec_hooks()
{
    bridge_log("=== Uninstalling FExec hooks (%d) ===", g_fexec_hook_count);
    for (int i = 0; i < g_fexec_hook_count; i++) {
        FExecHookEntry& e = g_fexec_hook_table[i];
        DWORD old_prot = 0;
        VirtualProtect(e.slot, 8, PAGE_READWRITE, &old_prot);
        *e.slot = (uintptr_t)e.original;
        VirtualProtect(e.slot, 8, old_prot, &old_prot);
        bridge_log("  Restored vtable=0x%llX",
                   (unsigned long long)e.vtable_base);
    }
    g_fexec_hook_count = 0;
}

/* -- Console command execution ------------------------------------- */

/*
 * ProcessConsoleExec = ProcessEvent + 3 (always).
 */

static bool validate_function_ptr(void* fn)
{
    return seh_validate_function(fn);
}

/* -- Game-thread command dispatch ----------------------------------- */

/*
 * UE5 requires most console commands to run on the game thread.
 * Calling Exec() from our TCP handler thread causes assertion failures
 * (IsInGameThread check in AsyncLoading2.cpp etc.).
 *
 * Solution: subclass the game window's WndProc. The game thread runs
 * the Windows message pump, so PostMessage + custom WM delivers
 * execution to the game thread. TCP thread pushes commands to a
 * queue and posts a message; WndProc hook drains the queue and
 * calls exec_console_command_internal().
 */

static const int CMD_QUEUE_MAX = 256;
static char     g_cmd_queue[CMD_QUEUE_MAX][512];
static volatile LONG g_cmd_queue_head = 0;   /* write index (TCP thread) */
static volatile LONG g_cmd_queue_tail = 0;   /* read index (game thread) */

static HWND    g_game_hwnd = NULL;
static WNDPROC g_original_wndproc = NULL;
static UINT    g_wm_bridge_exec = 0;
static std::atomic<bool> g_gamethread_dispatch_ready{false};

/* The actual Exec call -- only called from game thread via WndProc */
static bool exec_console_command_internal(const char* cmd);

static void gamethread_drain_queue()
{
    while (g_cmd_queue_tail != g_cmd_queue_head) {
        LONG idx = g_cmd_queue_tail % CMD_QUEUE_MAX;
        exec_console_command_internal(g_cmd_queue[idx]);
        InterlockedIncrement(&g_cmd_queue_tail);
    }
}

static LRESULT CALLBACK bridge_wndproc(HWND hwnd, UINT msg,
                                        WPARAM wp, LPARAM lp)
{
    if (msg == g_wm_bridge_exec) {
        gamethread_drain_queue();
        return 0;
    }
    return CallWindowProcA(g_original_wndproc, hwnd, msg, wp, lp);
}

static bool setup_gamethread_dispatch()
{
    /* Register a unique window message */
    g_wm_bridge_exec = RegisterWindowMessageA("captureAIshi_bridge_exec");
    if (!g_wm_bridge_exec) {
        bridge_log("ERROR: RegisterWindowMessage failed");
        return false;
    }

    /* Find the game window (same logic as hotsample) */
    struct FindCtx { DWORD pid; HWND result; };
    FindCtx ctx = { GetCurrentProcessId(), NULL };

    EnumWindows([](HWND hwnd, LPARAM lp) -> BOOL {
        FindCtx* c = (FindCtx*)lp;
        DWORD wnd_pid = 0;
        GetWindowThreadProcessId(hwnd, &wnd_pid);
        if (wnd_pid == c->pid && IsWindowVisible(hwnd)) {
            char title[256];
            GetWindowTextA(hwnd, title, sizeof(title));
            if (strlen(title) > 0) {
                c->result = hwnd;
                return FALSE;
            }
        }
        return TRUE;
    }, (LPARAM)&ctx);

    g_game_hwnd = ctx.result;
    if (!g_game_hwnd) {
        bridge_log("WARNING: Game window not found for dispatch hook. "
                   "Commands will run on TCP thread (may crash).");
        return false;
    }

    /* Subclass the window */
    g_original_wndproc = (WNDPROC)SetWindowLongPtrA(
        g_game_hwnd, GWLP_WNDPROC, (LONG_PTR)bridge_wndproc);

    if (!g_original_wndproc) {
        bridge_log("WARNING: SetWindowLongPtr failed (%d). "
                   "Commands will run on TCP thread.", GetLastError());
        g_game_hwnd = NULL;
        return false;
    }

    g_gamethread_dispatch_ready = true;
    bridge_log("Game-thread dispatch ready (hwnd=0x%p, WM=0x%X)",
               g_game_hwnd, g_wm_bridge_exec);
    return true;
}

/*
 * Public API: queue a command for game-thread execution.
 * If dispatch is not ready, falls back to direct call (risky).
 */
static bool exec_console_command(const char* cmd)
{
    if (g_gamethread_dispatch_ready && g_game_hwnd) {
        /* Reject if the ring buffer is full; otherwise a slow game
         * thread (stuck in a loading screen, blocking sync) would let
         * the TCP thread wrap head past tail and silently overwrite
         * unconsumed commands. */
        LONG head = g_cmd_queue_head;
        LONG tail = g_cmd_queue_tail;
        if ((LONG)(head - tail) >= CMD_QUEUE_MAX) {
            bridge_log("CMD: '%s' DROPPED -- queue full (%d pending)",
                       cmd, (int)(head - tail));
            return false;
        }

        /* Push to queue */
        LONG idx = head % CMD_QUEUE_MAX;
        strncpy(g_cmd_queue[idx], cmd, 511);
        g_cmd_queue[idx][511] = '\0';
        InterlockedIncrement(&g_cmd_queue_head);

        /* Wake the game thread */
        PostMessageA(g_game_hwnd, g_wm_bridge_exec, 0, 0);

        bridge_log("CMD: %s (queued for game thread)", cmd);
        return true;
    }

    /* Fallback: direct call (may crash on some commands) */
    bridge_log("CMD: %s (direct call -- no dispatch hook)", cmd);
    return exec_console_command_internal(cmd);
}

/*
 * Internal: call FExec::Exec() on GEngine. Must be on game thread.
 *
 * FExec::Exec is the universal command router.  It handles CVars,
 * stat, showflag, and routes to world/player controllers for game
 * commands like ToggleDebugCamera.
 *
 * The this pointer must be adjusted to the FExec subobject:
 *   this_fexec = (uint8_t*)g_engine_ptr + g_fexec_offset
 * The vtable thunk then adjusts it back to UEngine base.
 */
static bool exec_console_command_internal(const char* cmd)
{
    bridge_log("EXEC: '%s'  (engine=0x%p world=0x%p lp=0x%p)",
               cmd, g_engine_ptr, g_world_ptr, g_localplayer_ptr);
    if (!g_fexec_exec) {
        bridge_log("  [SKIP] FExec::Exec not available");
        return false;
    }

    /* Convert UTF-8 to wide string */
    int wlen = MultiByteToWideChar(CP_UTF8, 0, cmd, -1, NULL, 0);
    if (wlen <= 0) {
        bridge_log("  ERROR: UTF-8 to wide conversion failed");
        return false;
    }
    std::vector<wchar_t> wcmd(wlen);
    MultiByteToWideChar(CP_UTF8, 0, cmd, -1, wcmd.data(), wlen);

    void* ar = get_output_device();
    void* this_fexec = (uint8_t*)g_engine_ptr + g_fexec_offset;

    void* world = g_world_ptr;

    /* Use GEngine's original Exec to avoid recursion.
     * GEngine hook is always the first entry in g_fexec_hook_table. */
    FExecExecFn exec_fn = g_fexec_exec;
    if (g_fexec_hook_count > 0)
        exec_fn = g_fexec_hook_table[0].original;

    bool cmd_ret = false;
    bool call_ok = seh_call_fexec(exec_fn, this_fexec,
                                   world, wcmd.data(), ar, &cmd_ret);

    /* If crash with a world pointer, the pointer may be stale (map reload).
     * Clear it and retry with NULL -- CVars/stat work without world. */
    if (!call_ok && world) {
        bridge_log("  RETRY: GEngine crashed (world=0x%p stale?), retrying null", world);
        g_world_ptr = nullptr;
        /* Keep g_world_from_gua=true: do NOT unlock the FExec hook here.
         * Unlocking causes sublevel worlds to flood g_world_ptr.
         * GVC chain re-check on next __bridge_rescan will re-acquire. */
        world = nullptr;
        call_ok = seh_call_fexec(exec_fn, this_fexec,
                                  nullptr, wcmd.data(), ar, &cmd_ret);
    }
    if (!call_ok) {
        bridge_log("  ERROR: GEngine FExec::Exec crashed");
        return false;
    }

    if (cmd_ret) {
        bridge_log("  OK ret=1 (GEngine)");
        return true;
    }

    /* GEngine returned false -- gameplay commands route via ULocalPlayer::Exec.
     * ULocalPlayer is found actively via GUObjectArray + FName scan.
     * Helper lambda: call LP Exec via its FExec subobject. */
    auto try_lp_exec = [&](void* lp_fexec_subobj) -> bool {
        if (!lp_fexec_subobj) return false;
        uintptr_t lp_vtable = seh_read_ptr(lp_fexec_subobj);
        if (!lp_vtable) return false;

        FExecExecFn lp_fn = nullptr;

        /* Look up in hook table first (use original if hooked) */
        for (int i = 0; i < g_fexec_hook_count; i++) {
            if (g_fexec_hook_table[i].vtable_base == lp_vtable) {
                lp_fn = g_fexec_hook_table[i].original;
                break;
            }
        }

        /* Fallback: vtable not hooked (FExec has only 2 entries, scan
         * requires >= 3), so vtable[1] is still the original Exec. */
        if (!lp_fn)
            lp_fn = (FExecExecFn)seh_read_ptr((void*)(lp_vtable + 8));

        if (!lp_fn || !validate_function_ptr((void*)lp_fn)) return false;
        bool lp_ret = false;
        bool lp_ok  = seh_call_fexec(lp_fn, lp_fexec_subobj,
                                      world, wcmd.data(), ar, &lp_ret);
        if (lp_ok) {
            bridge_log("  OK ret=%d (ULocalPlayer)", (int)lp_ret);
            return true;
        }
        bridge_log("  ERROR: ULocalPlayer FExec crashed");
        return false;
    };

    if (!g_localplayer_ptr) find_localplayer();
    if (g_localplayer_ptr) {
        uintptr_t fexec_off = g_fexec_offset ? g_fexec_offset : 0x28;
        void* lp_fexec = (uint8_t*)g_localplayer_ptr + fexec_off;
        if (try_lp_exec(lp_fexec)) return true;
    }

    bridge_log("  OK ret=0 (GEngine rejected, LocalPlayer not found)");
    return false;
}
