/**
 * pybind_bridge.cpp — Python bindings for the capture bridge.
 *
 * Exposes the captureai::ReplaySession and capture API to Python via pybind11.
 * After building, the module can be imported as:
 *
 *   import capture_bridge
 *   session = capture_bridge.ReplaySession()
 *   session.open("frame_000001.rdc")
 *   fb = session.extract_frame()
 *   rgb = np.frombuffer(fb.rgb_data, dtype=np.uint8).reshape(fb.height, fb.width, 3)
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include "capture_bridge.h"

namespace py = pybind11;
using namespace captureai;

PYBIND11_MODULE(capture_bridge, m)
{
    m.doc() = "captureAIshi native bridge to RenderDoc";

    // ── Enums ──

    py::enum_<DepthFormat>(m, "DepthFormat")
        .value("Unknown", DepthFormat::Unknown)
        .value("ReverseZFloat32", DepthFormat::ReverseZFloat32)
        .value("LinearFloat32", DepthFormat::LinearFloat32)
        .value("UNorm24Bit", DepthFormat::UNorm24Bit)
        .value("UNorm16Bit", DepthFormat::UNorm16Bit);

    // ── FrameBuffer ──

    py::class_<FrameBuffer>(m, "FrameBuffer")
        .def(py::init<>())
        .def_readonly("width", &FrameBuffer::width)
        .def_readonly("height", &FrameBuffer::height)
        .def_readonly("has_rgb", &FrameBuffer::has_rgb)
        .def_readonly("has_depth", &FrameBuffer::has_depth)
        .def_property_readonly("rgb", [](const FrameBuffer &fb) -> py::object {
            if(!fb.has_rgb || fb.rgb_data.empty())
                return py::none();
            // Return as numpy array (H, W, 3) uint8
            return py::array_t<uint8_t>(
                {fb.height, fb.width, 3},
                {fb.width * 3, 3, 1},
                fb.rgb_data.data()
            );
        })
        .def_property_readonly("depth", [](const FrameBuffer &fb) -> py::object {
            if(!fb.has_depth || fb.depth_data.empty())
                return py::none();
            // Return as numpy array (H, W) float32
            return py::array_t<float>(
                {fb.height, fb.width},
                {static_cast<int>(fb.width * sizeof(float)), static_cast<int>(sizeof(float))},
                fb.depth_data.data()
            );
        });

    // ── DrawCallInfo ──

    py::class_<DrawCallInfo>(m, "DrawCallInfo")
        .def(py::init<>())
        .def_readonly("event_id", &DrawCallInfo::event_id)
        .def_readonly("action_id", &DrawCallInfo::action_id)
        .def_readonly("name", &DrawCallInfo::name)
        .def_readonly("num_indices", &DrawCallInfo::num_indices)
        .def_readonly("is_ui_candidate", &DrawCallInfo::is_ui_candidate);

    // ── In-Application API ──

    m.def("init_capture_api", &init_capture_api,
          "Initialize the RenderDoc in-application API. Returns True if successful.");

    m.def("trigger_capture", &trigger_capture,
          py::arg("capture_dir") = "./captures",
          "Trigger a single-frame capture. Returns path to .rdc file.");

    m.def("start_capture", &start_capture,
          "Start a multi-frame capture.");

    m.def("end_capture", &end_capture,
          "End a multi-frame capture.");

    m.def("set_capture_path", &set_capture_path,
          py::arg("path_template"),
          "Set the capture file path template.");

    m.def("is_renderdoc_attached", &is_renderdoc_attached,
          "Check if RenderDoc is attached to this process.");

    // ── ReplaySession ──

    py::class_<ReplaySession>(m, "ReplaySession")
        .def(py::init<>())
        .def("open", &ReplaySession::open,
             py::arg("rdc_path"),
             "Open an .rdc capture file for replay.")
        .def("close", &ReplaySession::close,
             "Close the current replay session.")
        .def("is_open", &ReplaySession::is_open,
             "Check if a replay session is open.")
        .def("__enter__", [](ReplaySession &self) -> ReplaySession& { return self; })
        .def("__exit__", [](ReplaySession &self, py::object, py::object, py::object) {
            self.close();
        })

        // Draw call analysis
        .def("get_actions", &ReplaySession::get_actions,
             "Get all draw calls / actions in the capture.")
        .def("classify_ui_events", &ReplaySession::classify_ui_events,
             py::arg("tail_fraction") = 0.2f,
             py::arg("extra_keywords") = std::vector<std::string>{},
             "Classify UI draw calls. Returns set of event IDs to exclude.")

        // Texture extraction
        .def("extract_backbuffer", &ReplaySession::extract_backbuffer,
             py::arg("target_event") = 0,
             py::arg("excluded_events") = std::set<uint32_t>{},
             "Extract the RGB backbuffer. Returns FrameBuffer.")
        .def("extract_depth", &ReplaySession::extract_depth,
             py::arg("target_event") = 0,
             "Extract the depth buffer. Returns FrameBuffer.")
        .def("extract_frame", &ReplaySession::extract_frame,
             py::arg("target_event") = 0,
             py::arg("excluded_events") = std::set<uint32_t>{},
             "Extract RGB + depth in one call. Returns FrameBuffer.")
        .def("detect_depth_format", &ReplaySession::detect_depth_format,
             "Auto-detect depth buffer format.")

        // Pipeline state
        .def("get_projection_matrix", &ReplaySession::get_projection_matrix,
             py::arg("event_id"),
             "Get the 4x4 projection matrix at an event.")
        .def("is_orthographic", &ReplaySession::is_orthographic,
             py::arg("event_id"),
             "Check if projection at event is orthographic.");
}
