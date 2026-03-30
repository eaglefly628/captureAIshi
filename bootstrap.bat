@echo off
setlocal enabledelayedexpansion

:: captureAIshi — Embedded Python Bootstrap
:: Downloads Python embeddable + installs all dependencies locally.
:: Run this once on a new machine. After that, use run.bat.

set PYTHON_VERSION=3.11.9
set PYTHON_ZIP=python-%PYTHON_VERSION%-embed-amd64.zip
set PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/%PYTHON_ZIP%
set PYTHON_DIR=%~dp0python
set PYTHON_EXE=%PYTHON_DIR%\python.exe
set PIP_URL=https://bootstrap.pypa.io/get-pip.py

echo ============================================
echo  captureAIshi Bootstrap
echo  Python %PYTHON_VERSION% Embedded + Dependencies
echo ============================================
echo.

:: Check if already bootstrapped
if exist "%PYTHON_EXE%" (
    echo [OK] Embedded Python already exists at %PYTHON_DIR%
    echo      To re-bootstrap, delete the python\ folder first.
    echo.
    echo Installing/updating dependencies...
    goto :install_deps
)

:: Download Python embeddable
echo [1/4] Downloading Python %PYTHON_VERSION% embeddable...
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"
powershell -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_DIR%\%PYTHON_ZIP%' }"
if errorlevel 1 (
    echo ERROR: Failed to download Python. Check your internet connection.
    exit /b 1
)

:: Extract
echo [2/4] Extracting...
powershell -Command "Expand-Archive -Path '%PYTHON_DIR%\%PYTHON_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force"
del "%PYTHON_DIR%\%PYTHON_ZIP%"

:: Enable pip: uncomment "import site" in python311._pth
echo [3/4] Enabling pip support...
set PTH_FILE=%PYTHON_DIR%\python311._pth
if exist "%PTH_FILE%" (
    powershell -Command "(Get-Content '%PTH_FILE%') -replace '#import site', 'import site' | Set-Content '%PTH_FILE%'"
)

:: Install pip
echo [4/4] Installing pip...
powershell -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PIP_URL%' -OutFile '%PYTHON_DIR%\get-pip.py' }"
"%PYTHON_EXE%" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location >nul 2>&1
del "%PYTHON_DIR%\get-pip.py"

:install_deps
:: Install project dependencies
echo.
echo Installing project dependencies...
"%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt" --no-warn-script-location -q
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    exit /b 1
)

echo.
echo ============================================
echo  Bootstrap complete!
echo  Use run.bat to launch captureAIshi.
echo ============================================
pause
