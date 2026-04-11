@echo off
setlocal

:: ---- 修改这两个路径 ----
set UE_ROOT=D:\UnrealVersion\UE_5.7
set PROJECT=D:\StackOBot\StackOBot.uproject
:: ------------------------

set GEN=%UE_ROOT%\Engine\Build\BatchFiles\GenerateProjectFiles.bat
set BUILD=%UE_ROOT%\Engine\Build\BatchFiles\Build.bat

echo === Step 1: Generate VS project files (skip IntelliSense) ===
call "%GEN%" -project="%PROJECT%" -game -nointellisense
echo GenerateProjectFiles exited with code %ERRORLEVEL% (non-zero is OK if .sln was created)

echo.
echo === Step 2: Build StackOBotEditor Development Win64 ===
"%BUILD%" StackOBotEditor Development Win64 -Project="%PROJECT%" -WaitMutex
if errorlevel 1 (
    echo.
    echo BUILD FAILED
    pause
    exit /b 1
)

echo.
echo === Done! Open StackOBot.sln in Visual Studio ===
pause
