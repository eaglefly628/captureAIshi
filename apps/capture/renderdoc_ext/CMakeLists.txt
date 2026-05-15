cmake_minimum_required(VERSION 3.16)
project(captureai_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ── Options ─────────────────────────────────────────────────────────────────

option(BUILD_PYBIND "Build Python bindings via pybind11" ON)
option(BUILD_RENDERDOC_FROM_SOURCE "Build RenderDoc replay library from source" OFF)

# ── RenderDoc paths ─────────────────────────────────────────────────────────

# Root of the RenderDoc source tree (vendor at <repo>/3rdparty/renderdoc/)
set(RENDERDOC_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../3rdparty/renderdoc"
    CACHE PATH "Path to RenderDoc source")

# Include paths — we only need the API headers for compilation
set(RENDERDOC_API_DIR "${RENDERDOC_SOURCE_DIR}/renderdoc/api")

if(NOT EXISTS "${RENDERDOC_API_DIR}/app/renderdoc_app.h")
    message(FATAL_ERROR
        "RenderDoc API headers not found at ${RENDERDOC_API_DIR}.\n"
        "Vendor tree expected at <repo>/3rdparty/renderdoc/")
endif()

# ── Find RenderDoc library ──────────────────────────────────────────────────

# The replay library (librenderdoc.so / renderdoc.dll)
# Users must provide this either from a system install or by building from source
if(BUILD_RENDERDOC_FROM_SOURCE)
    # Build RenderDoc's replay library as part of our build
    # This requires all of RenderDoc's build dependencies (Qt is NOT needed)
    add_subdirectory(${RENDERDOC_SOURCE_DIR} renderdoc_build EXCLUDE_FROM_ALL)
    set(RENDERDOC_LIB renderdoc)
else()
    # Find pre-installed renderdoc library
    find_library(RENDERDOC_LIB
        NAMES renderdoc librenderdoc
        HINTS
            /usr/lib
            /usr/local/lib
            /opt/renderdoc/lib
            "$ENV{RENDERDOC_DIR}/lib"
            "$ENV{RENDERDOC_DIR}"
            "C:/Program Files/RenderDoc"
            "C:/Program Files (x86)/RenderDoc"
    )

    if(NOT RENDERDOC_LIB)
        message(WARNING
            "RenderDoc library not found. The bridge will compile but link at runtime.\n"
            "Set RENDERDOC_DIR environment variable or pass -DRENDERDOC_LIB=/path/to/librenderdoc.so")
        # Create an imported target that will resolve at runtime
        add_library(renderdoc_runtime SHARED IMPORTED)
        set(RENDERDOC_LIB renderdoc_runtime)
        set(RENDERDOC_LINK_AT_RUNTIME TRUE)
    endif()
endif()

# ── Bridge library ──────────────────────────────────────────────────────────

add_library(captureai_bridge SHARED
    capture_bridge.cpp
    capture_bridge.h
)

# Platform defines required by RenderDoc API headers (apidefs.h)
if(WIN32)
    target_compile_definitions(captureai_bridge PUBLIC RENDERDOC_PLATFORM_WIN32)
elseif(APPLE)
    target_compile_definitions(captureai_bridge PUBLIC RENDERDOC_PLATFORM_APPLE)
elseif(UNIX)
    target_compile_definitions(captureai_bridge PUBLIC RENDERDOC_PLATFORM_LINUX)
endif()

target_include_directories(captureai_bridge PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../3rdparty  # for "renderdoc/renderdoc/api/..." includes
    ${CMAKE_CURRENT_SOURCE_DIR}
)

if(NOT RENDERDOC_LINK_AT_RUNTIME)
    target_link_libraries(captureai_bridge PRIVATE ${RENDERDOC_LIB})
endif()

if(UNIX AND NOT APPLE)
    target_link_libraries(captureai_bridge PRIVATE dl)
endif()

# ── Python bindings ─────────────────────────────────────────────────────────

if(BUILD_PYBIND)
    # Try to find pybind11 (pip install pybind11 or system package)
    find_package(pybind11 CONFIG QUIET)

    if(NOT pybind11_FOUND)
        # Try to find pybind11 via Python
        execute_process(
            COMMAND python3 -m pybind11 --cmakedir
            OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
            OUTPUT_STRIP_TRAILING_WHITESPACE
            ERROR_QUIET
            RESULT_VARIABLE PYBIND11_RESULT
        )
        if(PYBIND11_RESULT EQUAL 0)
            set(pybind11_DIR ${PYBIND11_CMAKE_DIR})
            find_package(pybind11 CONFIG REQUIRED)
        else()
            message(WARNING
                "pybind11 not found. Python bindings will not be built.\n"
                "Install with: pip install pybind11")
            set(BUILD_PYBIND OFF)
        endif()
    endif()
endif()

if(BUILD_PYBIND)
    pybind11_add_module(capture_bridge_py pybind_bridge.cpp)

    target_link_libraries(capture_bridge_py PRIVATE captureai_bridge)

    target_include_directories(capture_bridge_py PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/..
        ${CMAKE_CURRENT_SOURCE_DIR}
    )

    # Output the module next to the Python sources for easy import
    set_target_properties(capture_bridge_py PROPERTIES
        OUTPUT_NAME "capture_bridge"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../"
    )

    message(STATUS "Python bindings will be built (pybind11 found)")
endif()

# ── Install ─────────────────────────────────────────────────────────────────

install(TARGETS captureai_bridge
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
    RUNTIME DESTINATION bin
)

if(BUILD_PYBIND)
    install(TARGETS capture_bridge_py
        LIBRARY DESTINATION lib/python
    )
endif()
