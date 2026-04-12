@echo off
:: Fix UE 5.7 binary install bug: CoreUObjectSharedPCH.h missing
:: Run as Administrator if writing to D:\UnrealVersion\ requires it.

set STUB_DIR=D:\UnrealVersion\UE_5.7\Engine\Source\Runtime\CoreUObject\Public
set STUB=%STUB_DIR%\CoreUObjectSharedPCH.h

if exist "%STUB%" (
    echo Already exists: %STUB%
    goto :done
)

echo Creating: %STUB_DIR%
md "%STUB_DIR%"
echo mkdir result: %ERRORLEVEL%

echo Writing stub file...
(
echo // Stub for UE 5.7 binary install -- CoreUObjectSharedPCH.h missing from Epic package.
echo // Only needed by UBT IntelliSense; not used in actual compilation.
echo #pragma once
echo #include "CoreMinimal.h"
) > "%STUB%"
echo Write result: %ERRORLEVEL%

if exist "%STUB%" (
    echo SUCCESS: %STUB%
) else (
    echo FAILED: file not created
)

:done
pause
