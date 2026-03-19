#!/usr/bin/env bash
# Build the captureAIshi native RenderDoc bridge.
#
# Usage:
#   ./renderdoc_ext/build.sh              # standard build
#   ./renderdoc_ext/build.sh --from-source # also build RenderDoc replay lib
#   ./renderdoc_ext/build.sh --clean       # clean and rebuild
#
# Prerequisites:
#   - CMake >= 3.16
#   - C++17 compiler (g++ >= 7, clang >= 5, MSVC 2017+)
#   - pybind11: pip install pybind11
#   - RenderDoc installed OR built from source (--from-source)
#
# After building, `import capture_bridge` will work from the project root.

set -euo pipefail
cd "$(dirname "$0")/.."

BUILD_DIR="build"
FROM_SOURCE=OFF
CLEAN=false

for arg in "$@"; do
    case "$arg" in
        --from-source) FROM_SOURCE=ON ;;
        --clean)       CLEAN=true ;;
        --help|-h)
            echo "Usage: $0 [--from-source] [--clean]"
            exit 0
            ;;
    esac
done

# Check submodule
if [ ! -f "renderdoc/renderdoc/api/app/renderdoc_app.h" ]; then
    echo "Initializing RenderDoc submodule..."
    git submodule update --init renderdoc
fi

# Clean
if $CLEAN && [ -d "$BUILD_DIR" ]; then
    echo "Cleaning build directory..."
    rm -rf "$BUILD_DIR"
fi

# Configure
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

echo "Configuring..."
cmake ../renderdoc_ext \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_RENDERDOC_FROM_SOURCE=$FROM_SOURCE \
    -DRENDERDOC_SOURCE_DIR="$(pwd)/../renderdoc"

# Build
echo "Building..."
cmake --build . --config Release -j "$(nproc 2>/dev/null || echo 4)"

echo ""
echo "Build complete!"
echo ""

# Check if the Python module was built
if [ -f "../capture_bridge"*.so ] || [ -f "../capture_bridge"*.pyd ]; then
    echo "Python module ready: import capture_bridge"
else
    echo "WARNING: Python module not found. Check pybind11 installation:"
    echo "  pip install pybind11"
fi
