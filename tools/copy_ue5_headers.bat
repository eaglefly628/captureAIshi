@echo off
setlocal

set SRC=D:\project\UnrealEngine
set DST=%TEMP%\ue5_headers

echo Creating output directory: %DST%
mkdir "%DST%" 2>nul

echo Copying camera-related headers...

copy "%SRC%\Engine\Source\Runtime\Engine\Classes\Camera\PlayerCameraManager.h"  "%DST%\PlayerCameraManager.h"
copy "%SRC%\Engine\Source\Runtime\Engine\Classes\Camera\CameraTypes.h"          "%DST%\CameraTypes.h"
copy "%SRC%\Engine\Source\Runtime\Engine\Classes\GameFramework\PlayerController.h" "%DST%\PlayerController.h"
copy "%SRC%\Engine\Source\Runtime\Engine\Classes\Engine\LocalPlayer.h"          "%DST%\LocalPlayer.h"

echo.
echo Done. Files in: %DST%
echo.
dir "%DST%"

endlocal
pause
