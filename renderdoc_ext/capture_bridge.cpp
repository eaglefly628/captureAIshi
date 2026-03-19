/**
 * capture_bridge.cpp — Native bridge implementation.
 *
 * Links against RenderDoc's replay library for texture extraction
 * and uses the in-application API for capture triggering.
 */

#include "capture_bridge.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>

// RenderDoc API headers
#include "renderdoc/renderdoc/api/app/renderdoc_app.h"
#include "renderdoc/renderdoc/api/replay/renderdoc_replay.h"

#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace captureai {

// ── In-Application API globals ──────────────────────────────────────────────

static RENDERDOC_API_1_6_0 *s_rdoc_api = nullptr;
static bool s_api_initialized = false;
static int s_capture_count = 0;

bool init_capture_api()
{
    if(s_api_initialized)
        return s_rdoc_api != nullptr;

    s_api_initialized = true;

#ifdef _WIN32
    // Try to get the API from an already-loaded renderdoc.dll
    HMODULE mod = GetModuleHandleA("renderdoc.dll");
    if(!mod)
    {
        // Try loading from common paths
        const char *paths[] = {
            "C:\\Program Files\\RenderDoc\\renderdoc.dll",
            "C:\\Program Files (x86)\\RenderDoc\\renderdoc.dll",
            nullptr,
        };
        for(int i = 0; paths[i]; i++)
        {
            mod = LoadLibraryA(paths[i]);
            if(mod)
                break;
        }
    }
    if(!mod)
        return false;

    pRENDERDOC_GetAPI getApi =
        (pRENDERDOC_GetAPI)GetProcAddress(mod, "RENDERDOC_GetAPI");
#else
    // Linux: try to find the already-loaded librenderdoc.so
    void *mod = dlopen("librenderdoc.so", RTLD_NOW | RTLD_NOLOAD);
    if(!mod)
    {
        // Try common install paths
        const char *paths[] = {
            "/usr/lib/librenderdoc.so",
            "/usr/local/lib/librenderdoc.so",
            "/opt/renderdoc/lib/librenderdoc.so",
            nullptr,
        };
        for(int i = 0; paths[i]; i++)
        {
            mod = dlopen(paths[i], RTLD_NOW);
            if(mod)
                break;
        }
    }
    if(!mod)
        return false;

    pRENDERDOC_GetAPI getApi =
        (pRENDERDOC_GetAPI)dlsym(mod, "RENDERDOC_GetAPI");
#endif

    if(!getApi)
        return false;

    int ret = getApi(eRENDERDOC_API_Version_1_6_0, (void **)&s_rdoc_api);
    return ret == 1 && s_rdoc_api != nullptr;
}

std::string trigger_capture(const std::string &capture_dir)
{
    if(!s_rdoc_api)
    {
        if(!init_capture_api())
            return "";
    }

    if(!s_rdoc_api)
        return "";

    // Set capture file path
    std::string path_template = capture_dir + "/frame";
    s_rdoc_api->SetCaptureFilePathTemplate(path_template.c_str());

    // Trigger capture for next frame
    s_rdoc_api->TriggerCapture();

    s_capture_count++;

    // Get the path of the latest capture
    uint32_t num_captures = s_rdoc_api->GetNumCaptures();
    if(num_captures > 0)
    {
        uint32_t path_len = 0;
        s_rdoc_api->GetCapture(num_captures - 1, nullptr, &path_len, nullptr);
        std::string path(path_len, '\0');
        s_rdoc_api->GetCapture(num_captures - 1, &path[0], &path_len, nullptr);
        // Remove trailing null
        if(!path.empty() && path.back() == '\0')
            path.pop_back();
        return path;
    }

    return "";
}

bool start_capture()
{
    if(!s_rdoc_api && !init_capture_api())
        return false;
    s_rdoc_api->StartFrameCapture(nullptr, nullptr);
    return true;
}

bool end_capture()
{
    if(!s_rdoc_api)
        return false;
    return s_rdoc_api->EndFrameCapture(nullptr, nullptr) == 1;
}

void set_capture_path(const std::string &path_template)
{
    if(s_rdoc_api)
        s_rdoc_api->SetCaptureFilePathTemplate(path_template.c_str());
}

bool is_renderdoc_attached()
{
    if(!s_rdoc_api && !init_capture_api())
        return false;
    return s_rdoc_api != nullptr;
}

// ── Replay Session Implementation ───────────────────────────────────────────

struct ReplaySession::Impl {
    ICaptureFile *capture_file = nullptr;
    IReplayController *controller = nullptr;
    bool open = false;
};

ReplaySession::ReplaySession() : m_impl(std::make_unique<Impl>()) {}

ReplaySession::~ReplaySession()
{
    close();
}

bool ReplaySession::open(const std::string &rdc_path)
{
    close();

    m_impl->capture_file = RENDERDOC_OpenCaptureFile();
    if(!m_impl->capture_file)
        return false;

    ResultDetails result = m_impl->capture_file->OpenFile(rdc_path.c_str(), "rdc", nullptr);
    if(result.code != ResultCode::Succeeded)
    {
        std::cerr << "capture_bridge: Failed to open " << rdc_path << std::endl;
        m_impl->capture_file->Shutdown();
        m_impl->capture_file = nullptr;
        return false;
    }

    ReplayOptions opts;
    opts.apiValidation = false;    // faster replay
    opts.forceGPUVendor = GPUVendor::Unknown;
    opts.optimisation = ReplayOptimisationLevel::Fastest;

    auto [open_result, ctrl] = m_impl->capture_file->OpenCapture(opts, nullptr);
    if(open_result.code != ResultCode::Succeeded || !ctrl)
    {
        std::cerr << "capture_bridge: Failed to create replay controller" << std::endl;
        m_impl->capture_file->Shutdown();
        m_impl->capture_file = nullptr;
        return false;
    }

    m_impl->controller = ctrl;
    m_impl->open = true;
    return true;
}

void ReplaySession::close()
{
    if(m_impl->controller)
    {
        m_impl->controller->Shutdown();
        m_impl->controller = nullptr;
    }
    if(m_impl->capture_file)
    {
        m_impl->capture_file->Shutdown();
        m_impl->capture_file = nullptr;
    }
    m_impl->open = false;
}

bool ReplaySession::is_open() const
{
    return m_impl->open;
}

// ── Draw call analysis ──────────────────────────────────────────────────────

static void collect_actions_recursive(
    const rdcarray<ActionDescription> &actions,
    std::vector<DrawCallInfo> &out,
    int depth = 0)
{
    for(const auto &action : actions)
    {
        DrawCallInfo info;
        info.event_id = action.eventId;
        info.action_id = action.actionId;
        info.name = action.customName.c_str();
        info.num_indices = action.numIndices;
        info.is_ui_candidate = false;
        out.push_back(info);

        // Recurse into children
        if(!action.children.empty())
            collect_actions_recursive(action.children, out, depth + 1);
    }
}

std::vector<DrawCallInfo> ReplaySession::get_actions() const
{
    std::vector<DrawCallInfo> result;
    if(!m_impl->controller)
        return result;

    const auto &actions = m_impl->controller->GetRootActions();
    collect_actions_recursive(actions, result);
    return result;
}

static bool name_has_ui_keyword(const std::string &name,
                                const std::vector<std::string> &extra_keywords)
{
    // Convert to lowercase
    std::string lower = name;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    static const std::vector<std::string> builtin_keywords = {
        "ui", "hud", "widget", "slate", "imgui", "overlay",
        "minimap", "crosshair", "text", "font", "2d",
        "umg",     // UE5 UMG widgets
        "canvas",  // Unity Canvas
    };

    for(const auto &kw : builtin_keywords)
    {
        if(lower.find(kw) != std::string::npos)
            return true;
    }
    for(const auto &kw : extra_keywords)
    {
        std::string lower_kw = kw;
        std::transform(lower_kw.begin(), lower_kw.end(), lower_kw.begin(), ::tolower);
        if(lower.find(lower_kw) != std::string::npos)
            return true;
    }
    return false;
}

std::set<uint32_t> ReplaySession::classify_ui_events(
    float tail_fraction,
    const std::vector<std::string> &extra_keywords) const
{
    std::set<uint32_t> excluded;
    if(!m_impl->controller)
        return excluded;

    auto all_actions = get_actions();
    if(all_actions.empty())
        return excluded;

    size_t total = all_actions.size();
    size_t ui_start = static_cast<size_t>(total * (1.0f - tail_fraction));

    for(size_t i = 0; i < total; i++)
    {
        auto &action = all_actions[i];
        bool is_late = i >= ui_start;
        bool has_keyword = name_has_ui_keyword(action.name, extra_keywords);
        bool is_small_draw = action.num_indices > 0 && action.num_indices <= 6;

        // Check orthographic projection for late draws
        bool is_ortho = false;
        if(is_late)
            is_ortho = is_orthographic(action.event_id);

        if(has_keyword || (is_late && (is_small_draw || is_ortho)))
        {
            action.is_ui_candidate = true;
            excluded.insert(action.event_id);
        }
    }

    return excluded;
}

// ── Texture extraction ──────────────────────────────────────────────────────

FrameBuffer ReplaySession::extract_backbuffer(
    uint32_t target_event,
    const std::set<uint32_t> &excluded_events) const
{
    FrameBuffer fb;
    if(!m_impl->controller)
        return fb;

    // If no specific event, go to the last event
    if(target_event == 0)
    {
        const auto &actions = m_impl->controller->GetRootActions();
        if(!actions.empty())
        {
            // Find the last non-excluded event
            auto all = get_actions();
            for(auto it = all.rbegin(); it != all.rend(); ++it)
            {
                if(excluded_events.find(it->event_id) == excluded_events.end())
                {
                    target_event = it->event_id;
                    break;
                }
            }
        }
    }

    if(target_event == 0)
        return fb;

    // Move to target event
    m_impl->controller->SetFrameEvent(target_event, true);

    // Find the swapchain / backbuffer texture
    const auto &textures = m_impl->controller->GetTextures();
    for(const auto &tex : textures)
    {
        if(tex.creationFlags & TextureCategory::SwapBuffer)
        {
            bytebuf data = m_impl->controller->GetTextureData(tex.resourceId, Subresource());
            if(!data.empty())
            {
                fb.width = tex.width;
                fb.height = tex.height;
                fb.has_rgb = true;

                // Convert RGBA -> RGB
                size_t pixel_count = static_cast<size_t>(fb.width) * fb.height;
                fb.rgb_data.resize(pixel_count * 3);

                size_t src_stride = 4;  // RGBA
                for(size_t p = 0; p < pixel_count && (p * src_stride + 2) < data.size(); p++)
                {
                    fb.rgb_data[p * 3 + 0] = data[p * src_stride + 0];
                    fb.rgb_data[p * 3 + 1] = data[p * src_stride + 1];
                    fb.rgb_data[p * 3 + 2] = data[p * src_stride + 2];
                }
            }
            break;
        }
    }

    return fb;
}

FrameBuffer ReplaySession::extract_depth(uint32_t target_event) const
{
    FrameBuffer fb;
    if(!m_impl->controller)
        return fb;

    if(target_event == 0)
    {
        const auto &actions = m_impl->controller->GetRootActions();
        if(!actions.empty())
        {
            auto all = get_actions();
            if(!all.empty())
                target_event = all.back().event_id;
        }
    }

    if(target_event == 0)
        return fb;

    m_impl->controller->SetFrameEvent(target_event, true);

    const auto &textures = m_impl->controller->GetTextures();
    for(const auto &tex : textures)
    {
        if(tex.creationFlags & TextureCategory::DepthTarget)
        {
            bytebuf data = m_impl->controller->GetTextureData(tex.resourceId, Subresource());
            if(!data.empty())
            {
                fb.width = tex.width;
                fb.height = tex.height;
                fb.has_depth = true;

                size_t pixel_count = static_cast<size_t>(fb.width) * fb.height;
                fb.depth_data.resize(pixel_count);

                // Determine format and convert to float32
                DepthFormat fmt = detect_depth_format();
                if(fmt == DepthFormat::ReverseZFloat32 || fmt == DepthFormat::LinearFloat32)
                {
                    // Data is already float32
                    if(data.size() >= pixel_count * sizeof(float))
                    {
                        std::memcpy(fb.depth_data.data(), data.data(),
                                    pixel_count * sizeof(float));

                        // Convert reverse-Z to linear if needed
                        if(fmt == DepthFormat::ReverseZFloat32)
                        {
                            for(size_t i = 0; i < pixel_count; i++)
                                fb.depth_data[i] = 1.0f - fb.depth_data[i];
                        }
                    }
                }
                else if(fmt == DepthFormat::UNorm24Bit)
                {
                    // 24-bit packed: 3 bytes per pixel
                    for(size_t i = 0; i < pixel_count && (i * 3 + 2) < data.size(); i++)
                    {
                        uint32_t d = (uint32_t(data[i * 3 + 2]) << 16) |
                                     (uint32_t(data[i * 3 + 1]) << 8) |
                                     uint32_t(data[i * 3 + 0]);
                        fb.depth_data[i] = float(d) / 16777215.0f;
                    }
                }
                else if(fmt == DepthFormat::UNorm16Bit)
                {
                    const uint16_t *src = reinterpret_cast<const uint16_t *>(data.data());
                    for(size_t i = 0; i < pixel_count && (i * 2 + 1) < data.size(); i++)
                        fb.depth_data[i] = float(src[i]) / 65535.0f;
                }
                else
                {
                    // Unknown format: try float32
                    if(data.size() >= pixel_count * sizeof(float))
                        std::memcpy(fb.depth_data.data(), data.data(),
                                    pixel_count * sizeof(float));
                }
            }
            break;
        }
    }

    return fb;
}

FrameBuffer ReplaySession::extract_frame(
    uint32_t target_event,
    const std::set<uint32_t> &excluded_events) const
{
    FrameBuffer rgb_fb = extract_backbuffer(target_event, excluded_events);
    FrameBuffer depth_fb = extract_depth(target_event);

    // Merge
    if(depth_fb.has_depth)
    {
        rgb_fb.depth_data = std::move(depth_fb.depth_data);
        rgb_fb.has_depth = true;
        if(!rgb_fb.has_rgb)
        {
            rgb_fb.width = depth_fb.width;
            rgb_fb.height = depth_fb.height;
        }
    }

    return rgb_fb;
}

DepthFormat ReplaySession::detect_depth_format() const
{
    if(!m_impl->controller)
        return DepthFormat::Unknown;

    // Check textures for depth target format info
    const auto &textures = m_impl->controller->GetTextures();
    for(const auto &tex : textures)
    {
        if(tex.creationFlags & TextureCategory::DepthTarget)
        {
            // Use format info to determine depth type
            // ResourceFormat gives us the component type and byte width
            if(tex.format.compType == CompType::Float && tex.format.compByteWidth == 4)
                return DepthFormat::ReverseZFloat32;   // UE5 default
            else if(tex.format.compType == CompType::UNorm && tex.format.compByteWidth == 3)
                return DepthFormat::UNorm24Bit;
            else if(tex.format.compType == CompType::UNorm && tex.format.compByteWidth == 2)
                return DepthFormat::UNorm16Bit;
            else if(tex.format.compType == CompType::Float)
                return DepthFormat::LinearFloat32;

            break;
        }
    }

    return DepthFormat::Unknown;
}

// ── Pipeline state queries ──────────────────────────────────────────────────

std::vector<float> ReplaySession::get_projection_matrix(uint32_t event_id) const
{
    std::vector<float> matrix(16, 0.0f);
    // Identity fallback
    matrix[0] = matrix[5] = matrix[10] = matrix[15] = 1.0f;

    if(!m_impl->controller)
        return matrix;

    m_impl->controller->SetFrameEvent(event_id, true);

    // Try to extract projection from constant buffers
    // This is API-specific; we try the common patterns
    const PipeState &pipe = m_impl->controller->GetPipelineState();

    // Check for vertex shader constant buffers that might contain ViewProjection
    ShaderReflection *vs_refl = pipe.GetShaderReflection(ShaderStage::Vertex);
    if(vs_refl)
    {
        for(const auto &cb : vs_refl->constantBlocks)
        {
            std::string name = cb.name.c_str();
            std::string lower = name;
            std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

            if(lower.find("proj") != std::string::npos ||
               lower.find("viewproj") != std::string::npos ||
               lower.find("mvp") != std::string::npos)
            {
                // Found a likely projection buffer
                // The actual matrix extraction depends on the buffer layout
                // For now, return identity — proper implementation requires
                // reading the constant buffer data and parsing the layout
                break;
            }
        }
    }

    return matrix;
}

bool ReplaySession::is_orthographic(uint32_t event_id) const
{
    auto mat = get_projection_matrix(event_id);
    // A perspective projection has mat[3][2] != 0 and mat[2][3] == -1
    // An orthographic projection has mat[3][2] == 0 and mat[3][3] == 1
    // Index mapping: mat[row][col] = matrix[row * 4 + col]
    float m32 = mat[3 * 4 + 2];  // mat[3][2]
    float m33 = mat[3 * 4 + 3];  // mat[3][3]

    // Orthographic: m32 is the Z translation, m33 is 1.0
    // Perspective: m32 is -(2*far*near)/(far-near), m33 is 0.0
    return std::abs(m33 - 1.0f) < 0.01f && std::abs(m32) < 0.01f;
}

}  // namespace captureai
