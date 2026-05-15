/* ue5_actions.h -- Camera actions, timestop, HUD toggle, hotsampling.
 * INCLUDED FROM ue5_engine.h ONLY -- do not include directly. */


/* -- Timestop / Game Speed ----------------------------------------- */

static bool set_game_speed(float speed)
{
    g_game_speed = speed;
    g_paused = (speed == 0.0f);

    char cmd[64];
    snprintf(cmd, sizeof(cmd), "slomo %.4f", speed);
    return exec_console_command(cmd);
}

static bool toggle_pause()
{
    if (g_paused) {
        return set_game_speed(1.0f);
    } else {
        return set_game_speed(0.0001f);  /* near-zero, not true 0 */
    }
}

/* -- HUD Toggle ---------------------------------------------------- */

static bool g_hud_visible = true;

static bool toggle_hud()
{
    g_hud_visible = !g_hud_visible;
    if (g_hud_visible) {
        exec_console_command("ShowHUD 1");
        exec_console_command("stat none");
    } else {
        exec_console_command("ShowHUD 0");
        exec_console_command("stat none");
        /* Do NOT disable PostProcessing -- it affects GBuffer output
         * (depth, normals) which we need for capture. ShowHUD 0 alone
         * is sufficient to hide the game HUD. */
    }
    bridge_log("HUD %s", g_hud_visible ? "shown" : "hidden");
    return true;
}

/* -- Free Camera --------------------------------------------------- */

static bool set_camera_location(float x, float y, float z)
{
    g_camera.x = x;
    g_camera.y = y;
    g_camera.z = z;

    char cmd[128];
    snprintf(cmd, sizeof(cmd), "SetViewLocation %.2f %.2f %.2f", x, y, z);
    return exec_console_command(cmd);
}

static bool set_camera_rotation(float pitch, float yaw, float roll)
{
    g_camera.pitch = pitch;
    g_camera.yaw = yaw;
    g_camera.roll = roll;

    char cmd[128];
    snprintf(cmd, sizeof(cmd), "SetViewRotation %.2f %.2f %.2f",
             pitch, yaw, roll);
    return exec_console_command(cmd);
}

static bool set_fov(float fov)
{
    g_camera.fov = fov;

    char cmd[64];
    snprintf(cmd, sizeof(cmd), "FOV %.1f", fov);
    return exec_console_command(cmd);
}

/* -- Hotsampling (Window Resize) ----------------------------------- */

static bool hotsample(int width, int height)
{
    HWND game_wnd = find_game_window();
    if (!game_wnd) {
        bridge_log("ERROR: Could not find game window for hotsampling");
        return false;
    }

    /* Remove window borders for exact pixel dimensions */
    LONG style = GetWindowLongA(game_wnd, GWL_STYLE);
    SetWindowLongA(game_wnd, GWL_STYLE, style & ~(WS_CAPTION | WS_THICKFRAME));

    /* Resize */
    SetWindowPos(game_wnd, HWND_TOP, 0, 0, width, height,
                 SWP_NOMOVE | SWP_FRAMECHANGED);

    /* Tell UE5 to update its rendering resolution */
    char cmd[128];
    snprintf(cmd, sizeof(cmd), "r.SetRes %dx%d", width, height);
    exec_console_command(cmd);

    bridge_log("Hotsampled to %dx%d", width, height);
    return true;
}

