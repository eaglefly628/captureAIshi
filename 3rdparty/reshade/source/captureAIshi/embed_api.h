/*
 * Embedded frame-capture subsystem -- public ABI seen by bridge.cpp.
 *
 * The four functions below are the ONLY symbols frame_capture.cpp exports
 * to its host. Everything else in that translation unit lives in an
 * anonymous namespace so it cannot collide with bridge.cpp or any other
 * .cpp linked into the same DLL.
 *
 * Lifecycle (called from bridge.cpp DllMain / its bootstrap thread):
 *
 *   DLL_PROCESS_ATTACH (DllMain, loader-lock held):
 *     fc_embed::register_events()    -- ReShade event registration only;
 *                                       no thread creation, no I/O.
 *
 *   bootstrap thread (started by bridge.cpp, NOT in DllMain):
 *     fc_embed::start_workers()      -- spawns 4 save-worker threads.
 *                                       Deferred out of DllMain to avoid
 *                                       loader-lock interaction with the
 *                                       newly-created threads' own DLL
 *                                       attaches.
 *
 *   DLL_PROCESS_DETACH (DllMain):
 *     fc_embed::stop_workers()       -- signals + joins worker threads.
 *     fc_embed::unregister_events()  -- removes ReShade event handlers.
 *
 * Calling start_workers() before register_events() is harmless (workers
 * idle on an empty queue). The reverse -- events firing before workers
 * start -- is also safe: tasks queue up and drain when workers come up.
 */

#pragma once

namespace fc_embed {

void register_events();
void unregister_events();

void start_workers();
void stop_workers();

// One-shot trigger -- fires a single capture next frame regardless of
// FC_EnableCapture or the FPS gate. Called from bridge.cpp when the
// __fc_capture TCP command is received, mirroring grabber.trigger_capture()
// flow (trigger from UI / trajectory per pose).
void trigger_oneshot();

} // namespace fc_embed
