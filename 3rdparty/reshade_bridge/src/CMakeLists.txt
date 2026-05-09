cmake_minimum_required(VERSION 3.16)
project(captureAIshi_reshade_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Path B: ReShade addon DLL (.addon).
#
# One binary embeds two subsystems compiled together (Phase 1 decision,
# 2026-05-09):
#   1. bridge.cpp  -- TCP 9998 protocol + GEngine scan + camera/HUD/path
#                     control. Owns DllMain. Identical feature set to Path A
#                     bridge.dll, just hosted as a ReShade addon instead of
#                     renderdoc-injected.
#   2. frame_capture.cpp -- color BMP/PNG + depth/normal EXR via ReShade
#                     events (vendored from unicap, treated as ours). Its
#                     init/shutdown wrappers are called from bridge.cpp's
#                     DllMain so the host DLL stays single-entry.
#
# Output: captureAIshi_bridge.addon (deploy alongside dxgi.dll proxy).

set(RESHADE_SDK_INCLUDE
    "${CMAKE_CURRENT_SOURCE_DIR}/../sdk"
    CACHE PATH "ReShade addon SDK headers (reshade.hpp + reshade_*.hpp)"
)

if(NOT EXISTS "${RESHADE_SDK_INCLUDE}/reshade.hpp")
    message(FATAL_ERROR
        "ReShade SDK headers not found at ${RESHADE_SDK_INCLUDE}. "
        "Expected vendored copy at 3rdparty/reshade_bridge/sdk/reshade.hpp.")
endif()

set(FC_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../frame_capture")
set(DEPS_DIR      "${CMAKE_CURRENT_SOURCE_DIR}/../deps")

if(NOT EXISTS "${FC_SOURCE_DIR}/frame_capture.cpp")
    message(FATAL_ERROR
        "frame_capture.cpp not found at ${FC_SOURCE_DIR}.")
endif()

add_library(captureAIshi_reshade_bridge SHARED
    bridge.cpp
    pattern_scan.h
    ue5_engine.h
    camera_path.h
    "${FC_SOURCE_DIR}/frame_capture.cpp"
    "${FC_SOURCE_DIR}/FormatEnum.h"
)

target_include_directories(captureAIshi_reshade_bridge PRIVATE
    "${RESHADE_SDK_INCLUDE}"
    "${FC_SOURCE_DIR}"
    "${DEPS_DIR}/imgui"
    "${DEPS_DIR}/stb"
    "${DEPS_DIR}/tinyexr"
)

# imgui_src needed by reshade_overlay.hpp's inline ImGui usage.
# stb_image / tinyexr / miniz are header-only with TU-private impls (FC owns).
file(GLOB IMGUI_SOURCES "${DEPS_DIR}/imgui/*.cpp")
target_sources(captureAIshi_reshade_bridge PRIVATE ${IMGUI_SOURCES})

target_link_libraries(captureAIshi_reshade_bridge PRIVATE ws2_32 psapi)

if(MSVC)
    # /utf-8 + ASCII-only source -> avoids C4819. /EHa for __try/__except.
    # Drop /WX because reshade + tinyexr + miniz spill warnings under /W4.
    target_compile_options(captureAIshi_reshade_bridge PRIVATE /W3 /utf-8 /EHa)
    # Silence the inevitable C4244/C4267 etc. from third-party headers.
    target_compile_definitions(captureAIshi_reshade_bridge PRIVATE
        _CRT_SECURE_NO_WARNINGS
        WIN32_LEAN_AND_MEAN
        NOMINMAX
    )
endif()

# Output as captureAIshi_bridge.addon next to dxgi.dll proxy. Suffix .addon is
# the convention ReShade scans for at game-exe directory load time.
set_target_properties(captureAIshi_reshade_bridge PROPERTIES
    PREFIX ""
    OUTPUT_NAME "captureAIshi_bridge"
    SUFFIX ".addon"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
    RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}/.."
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/.."
    RUNTIME_OUTPUT_DIRECTORY_RELWITHDEBINFO "${CMAKE_CURRENT_SOURCE_DIR}/.."
    RUNTIME_OUTPUT_DIRECTORY_MINSIZEREL "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
