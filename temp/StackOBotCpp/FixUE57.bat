@echo off
:: Fix UE 5.7 binary install bug: CoreUObjectSharedPCH.h missing
:: This file is only needed for IntelliSense, not actual compilation.
:: Creating a minimal stub so UBT doesn't crash during project generation.

set UE_ROOT=D:\UnrealVersion\UE_5.7
set STUB=%UE_ROOT%\Engine\Source\Runtime\CoreUObject\Public\CoreUObjectSharedPCH.h

if exist "%STUB%" (
    echo File already exists: %STUB%
    goto :done
)

echo Creating stub: %STUB%

(
echo // Copyright Epic Games, Inc. All Rights Reserved.
echo // AUTO-GENERATED STUB for UE 5.7 binary install -- missing from Epic's package.
echo // Required by UBT IntelliSense generation only; not used in actual compilation.
echo #pragma once
echo #include "CoreMinimal.h"
) > "%STUB%"

if errorlevel 1 (
    echo FAILED to create file. Run this bat as Administrator.
    pause
    exit /b 1
)

echo Done. Now re-run GenerateAndBuild.bat

:done
pause
