cmake_minimum_required(VERSION 3.16)
project(captureAIshi_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)

# Bridge DLL
add_library(captureAIshi_bridge SHARED
    bridge.cpp
    # Headers (for IDE visibility)
    pattern_scan.h
    ue5_engine.h
    camera_path.h
)

target_link_libraries(captureAIshi_bridge PRIVATE ws2_32 psapi)

# MSVC settings: warnings as errors, ASCII compliance
if(MSVC)
    # Strip default /EHsc before adding /EHa; otherwise __try/__except in
    # functions with C++ objects fails with C2712 (MSVC keeps /EHsc).
    string(REGEX REPLACE "/EHsc" "" CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")
    string(REGEX REPLACE "/EHs-c-" "" CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")
    target_compile_options(captureAIshi_bridge PRIVATE
        /W4 /WX /utf-8 /EHa
        /wd4100  # unreferenced formal parameter (Win32 callbacks, DllMain)
    )
    target_compile_definitions(captureAIshi_bridge PRIVATE
        _CRT_SECURE_NO_WARNINGS      # getenv/sscanf/fopen deprecation
        _WINSOCK_DEPRECATED_NO_WARNINGS  # inet_addr deprecation
    )
endif()

# Output directly to 3rdparty/bridge/ (no manual copy needed)
set_target_properties(captureAIshi_bridge PROPERTIES
    PREFIX ""
    OUTPUT_NAME "captureAIshi_bridge"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
    RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}/.."
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/.."
    RUNTIME_OUTPUT_DIRECTORY_RELWITHDEBINFO "${CMAKE_CURRENT_SOURCE_DIR}/.."
    RUNTIME_OUTPUT_DIRECTORY_MINSIZEREL "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
