@echo off
setlocal

:: ---- 修改这两个路径 ----
set UE_ROOT=D:\UnrealVersion\UE_5.7
set PROJECT=D:\StackOBot\StackOBot.uproject
:: ------------------------

set BUILD=%UE_ROOT%\Engine\Build\BatchFiles\Build.bat
set EDITOR=%UE_ROOT%\Engine\Binaries\Win64\UnrealEditor.exe

echo === Building StackOBot (skip project file generation) ===
"%BUILD%" StackOBotEditor Development Win64 ^
    -Project="%PROJECT%" ^
    -WaitMutex ^
    -NoHotReloadFromIDE
if errorlevel 1 (
    echo.
    echo BUILD FAILED -- see errors above
    pause
    exit /b 1
)

echo.
echo === Build OK. Launch editor? Press any key to open... ===
pause
start "" "%EDITOR%" "%PROJECT%"
