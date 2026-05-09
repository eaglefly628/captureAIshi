cmake_minimum_required(VERSION 3.16)
project(captureAIshi_reshade_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Path B: ReShade addon DLL (.addon).
# Same logic as 3rdparty/bridge/ but loaded inside the game via ReShade
# instead of via renderdoccmd inject. The addon registers with ReShade so
# dxgi.dll proxy picks it up; the embedded TCP server then exposes the
# bridge protocol on port 9998 just like Path A.
#
# Phase 0: bridge logic only. No render-pipeline event hooks yet.
# Phase 1: hook reshade::addon_event::reshade_present etc. for frame export.

# ReShade SDK headers come from the unicap submodule (which already pins a
# known-good v6 ReShade source we consume in Path B). If you want to swap
# ReShade versions, update the submodule pin -- do not vendor headers here.
set(RESHADE_SDK_INCLUDE
    "${CMAKE_CURRENT_SOURCE_DIR}/../../unicap/reshade-addons/deps/reshade/include"
    CACHE PATH "ReShade addon SDK headers (reshade.hpp + reshade_*.hpp)"
)

if(NOT EXISTS "${RESHADE_SDK_INCLUDE}/reshade.hpp")
    message(FATAL_ERROR
        "ReShade SDK headers not found at ${RESHADE_SDK_INCLUDE}. "
        "Run: git submodule update --init --recursive 3rdparty/unicap")
endif()

add_library(captureAIshi_reshade_bridge SHARED
    bridge.cpp
    pattern_scan.h
    ue5_engine.h
    camera_path.h
)

target_include_directories(captureAIshi_reshade_bridge PRIVATE
    "${RESHADE_SDK_INCLUDE}"
)

target_link_libraries(captureAIshi_reshade_bridge PRIVATE ws2_32 psapi)

if(MSVC)
    # /utf-8 + ASCII-only source -> avoids C4819. /EHa for __try/__except.
    # Drop /WX (unlike Path A) because reshade headers spill warnings under /W4.
    target_compile_options(captureAIshi_reshade_bridge PRIVATE /W4 /utf-8 /EHa)
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
