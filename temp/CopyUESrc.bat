@echo off
setlocal

set UE_ROOT=D:\project\UnrealEngine
set DEST=%~dp0ue5src

echo Creating %DEST%...
md "%DEST%" 2>nul

echo Copying Engine.h...
copy /Y "%UE_ROOT%\Engine\Source\Runtime\Engine\Classes\Engine\Engine.h" "%DEST%\Engine.h"

echo Copying GameViewportClient.h...
copy /Y "%UE_ROOT%\Engine\Source\Runtime\Engine\Classes\Engine\GameViewportClient.h" "%DEST%\GameViewportClient.h"

echo Copying UObjectBase.h...
copy /Y "%UE_ROOT%\Engine\Source\Runtime\CoreUObject\Public\UObject\UObjectBase.h" "%DEST%\UObjectBase.h"

echo Done. Files in: %DEST%
pause
