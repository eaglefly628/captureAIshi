@echo off
setlocal

:: ---- 修改这两个路径 ----
set UE_ROOT=D:\UnrealVersion\UE_5.7
set PROJECT=D:\StackOBot\StackOBot.uproject
:: ------------------------

set UBT=%UE_ROOT%\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.exe
set GEN=%UE_ROOT%\Engine\Build\BatchFiles\GenerateProjectFiles.bat

echo === Step 1: Generate VS project files ===
call "%GEN%" -project="%PROJECT%" -game -engine
if errorlevel 1 (
    echo WARNING: GenerateProjectFiles failed, trying direct UBT...
    "%UBT%" -projectfiles -project="%PROJECT%" -game -engine
)

echo.
echo === Step 2: Build Development Editor ===
"%UE_ROOT%\Engine\Build\BatchFiles\Build.bat" StackOBotEditor Development Win64 -Project="%PROJECT%" -WaitMutex -FromMsBuild
if errorlevel 1 (
    echo BUILD FAILED
    pause
    exit /b 1
)

echo.
echo === Done! Open .uproject to launch editor ===
pause
