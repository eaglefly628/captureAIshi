@echo off
setlocal

:: ---- 修改这两个路径 ----
set UE_ROOT=D:\project\UnrealEngine
set PROJECT=D:\StackOBot\StackOBot.uproject
:: ------------------------

set GEN=%UE_ROOT%\Engine\Build\BatchFiles\GenerateProjectFiles.bat

echo === Generate VSCode project files ===
call "%GEN%" -project="%PROJECT%" -game -VSCode
echo.

echo === Done! Open the folder in VSCode and build manually. ===
pause
