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
    target_compile_options(captureAIshi_bridge PRIVATE /W4 /WX /utf-8)
    # Structured exception handling needed for __try/__except
    target_compile_options(captureAIshi_bridge PRIVATE /EHa)
endif()

# Output name without lib prefix
set_target_properties(captureAIshi_bridge PROPERTIES
    PREFIX ""
    OUTPUT_NAME "captureAIshi_bridge"
)
