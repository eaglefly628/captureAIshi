@echo off
REM Build captureAIshi_bridge.dll
REM Output goes directly to 3rdparty/bridge/captureAIshi_bridge.dll

cd /d "%~dp0src"

if not exist build mkdir build
cd build

cmake .. -G "Visual Studio 17 2022" -A x64
if errorlevel 1 (
    echo.
    echo CMake configure failed. Make sure Visual Studio 2022 is installed.
    exit /b 1
)

cmake --build . --config Release
if errorlevel 1 (
    echo.
    echo Build failed.
    exit /b 1
)

echo.
echo Build OK. DLL at: %~dp0captureAIshi_bridge.dll
dir "%~dp0captureAIshi_bridge.dll"
