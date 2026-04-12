@echo off
:: Fix UE 5.7 binary install bug: CoreUObjectSharedPCH.h missing
:: The Engine\Source directory may not exist at all in binary installs.

set UE_ROOT=D:\UnrealVersion\UE_5.7
set STUB_DIR=%UE_ROOT%\Engine\Source\Runtime\CoreUObject\Public
set STUB=%STUB_DIR%\CoreUObjectSharedPCH.h

if exist "%STUB%" (
    echo Already exists: %STUB%
    goto :done
)

echo Creating directory: %STUB_DIR%
mkdir "%STUB_DIR%" 2>nul
if errorlevel 1 (
    echo FAILED to create directory.
    echo Try running this bat as Administrator ^(right-click -^> Run as administrator^).
    pause
    exit /b 1
)

echo Creating stub: %STUB%
(
echo // Copyright Epic Games, Inc. All Rights Reserved.
echo // Stub for UE 5.7 binary install -- CoreUObjectSharedPCH.h missing from Epic package.
echo // Only needed by UBT IntelliSense; not used in actual compilation.
echo #pragma once
echo #include "CoreMinimal.h"
) > "%STUB%"

echo Done.

:done
pause
