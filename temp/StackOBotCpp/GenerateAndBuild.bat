@echo off
setlocal

:: ---- 修改这两个路径 ----
set UE_ROOT=D:\project\UnrealEngine
set PROJECT=D:\StackOBot\StackOBot.uproject
:: ------------------------

set GEN=%UE_ROOT%\Engine\Build\BatchFiles\GenerateProjectFiles.bat
set BUILD=%UE_ROOT%\Engine\Build\BatchFiles\Build.bat

echo === Step 1: Generate VS project files ===
call "%GEN%" -project="%PROJECT%" -game
echo.

echo === Step 2: Build Editor ===
"%BUILD%" StackOBotEditor Development Win64 -Project="%PROJECT%" -WaitMutex
if errorlevel 1 (
    echo BUILD FAILED
    pause
    exit /b 1
)

echo === Done! ===
pause
