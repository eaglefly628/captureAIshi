/**
 * capture_bridge.h — Native C++ bridge between captureAIshi and RenderDoc.
 *
 * Provides:
 *   - In-process capture triggering via the RenderDoc In-Application API
 *   - Filtered replay: skip UI draw calls and extract clean RGB + depth
 *   - Depth format auto-detection from pipeline state
 *
 * This links against RenderDoc's replay library (librenderdoc.so / renderdoc.dll)
 * and is exposed to Python via pybind11.
 */

#pragma once

#include <cstdint>
#include <memory>
#include <set>
#include <string>
#include <vector>

namespace captureai {

// ── Structures ──────────────────────────────────────────────────────────────

struct FrameBuffer {
    std::vector<uint8_t> rgb_data;   // HxWx3 uint8
    std::vector<float> depth_data;   // HxW float32
    int width = 0;
    int height = 0;
    bool has_rgb = false;
    bool has_depth = false;
};

enum class DepthFormat {
    Unknown,
    ReverseZFloat32,    // UE5 default
    LinearFloat32,
    UNorm24Bit,
    UNorm16Bit,
};

struct DrawCallInfo {
    uint32_t event_id;
    uint32_t action_id;
    std::string name;
    uint32_t num_indices;
    bool is_ui_candidate;  // true if heuristics suggest this is UI
};

// ── In-Application API (for capture triggering) ─────────────────────────────

/**
 * Load the RenderDoc in-application API from a running or injected instance.
 * Returns true if the API was found and initialized.
 */
bool init_capture_api();

/**
 * Trigger a single-frame capture.
 * The capture file will be written to the configured capture directory.
 * Returns the path to the .rdc file, or empty string on failure.
 */
std::string trigger_capture(const std::string &capture_dir);

/**
 * Start a multi-frame capture (call end_capture() to stop).
 */
bool start_capture();

/**
 * End a multi-frame capture started with start_capture().
 */
bool end_capture();

/**
 * Set the capture file path template.
 * E.g., "/path/to/captures/frame" -> produces frame_0001.rdc, etc.
 */
void set_capture_path(const std::string &path_template);

/**
 * Check if RenderDoc is currently attached to this process.
 */
bool is_renderdoc_attached();

// ── Replay API (for texture extraction + UI filtering) ───────────────────────

class ReplaySession {
public:
    ReplaySession();
    ~ReplaySession();

    // Non-copyable
    ReplaySession(const ReplaySession &) = delete;
    ReplaySession &operator=(const ReplaySession &) = delete;

    /**
     * Open an .rdc capture file for replay.
     * Returns true on success.
     */
    bool open(const std::string &rdc_path);

    /**
     * Close the current replay session.
     */
    void close();

    /**
     * Check if a replay session is currently open.
     */
    bool is_open() const;

    // ── Draw call analysis ──

    /**
     * Get all top-level draw calls / actions in the capture.
     */
    std::vector<DrawCallInfo> get_actions() const;

    /**
     * Classify draw calls as UI/HUD using heuristics:
     *   - Last N% of draw calls (configurable, default 20%)
     *   - Keyword matching in action names
     *   - Small index count (quad draws)
     *   - Orthographic projection detection from pipeline state
     *
     * Returns set of event IDs to exclude.
     */
    std::set<uint32_t> classify_ui_events(
        float tail_fraction = 0.2f,
        const std::vector<std::string> &extra_keywords = {}
    ) const;

    // ── Texture extraction ──

    /**
     * Extract the RGB backbuffer at a specific event (or last event if 0).
     * If excluded_events is non-empty, replays up to the target event
     * while skipping excluded draw calls.
     *
     * Returns FrameBuffer with rgb_data populated.
     */
    FrameBuffer extract_backbuffer(
        uint32_t target_event = 0,
        const std::set<uint32_t> &excluded_events = {}
    ) const;

    /**
     * Extract the depth buffer at a specific event.
     * Depth is always returned as float32 (converted from whatever format).
     */
    FrameBuffer extract_depth(uint32_t target_event = 0) const;

    /**
     * Extract both RGB and depth in a single replay pass.
     * More efficient than calling extract_backbuffer + extract_depth separately.
     */
    FrameBuffer extract_frame(
        uint32_t target_event = 0,
        const std::set<uint32_t> &excluded_events = {}
    ) const;

    /**
     * Auto-detect the depth buffer format from pipeline state.
     */
    DepthFormat detect_depth_format() const;

    // ── Pipeline state queries ──

    /**
     * Get the projection matrix at a given event.
     * Useful for detecting orthographic (UI) vs perspective (scene) rendering.
     * Returns a 4x4 matrix as a flat 16-element array (row-major).
     */
    std::vector<float> get_projection_matrix(uint32_t event_id) const;

    /**
     * Check if the projection at event_id is orthographic.
     */
    bool is_orthographic(uint32_t event_id) const;

private:
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};

}  // namespace captureai
