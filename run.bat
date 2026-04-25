@echo off
:: captureAIshi — Launch with embedded Python
:: Run bootstrap.bat first if this is a new machine.

set PYTHON_EXE=%~dp0python\python.exe

if not exist "%PYTHON_EXE%" (
    echo Embedded Python not found. Running bootstrap first...
    call "%~dp0bootstrap.bat"
    if errorlevel 1 exit /b 1
)

:: Refresh dependencies on every launch so additions to requirements.txt
:: (e.g. opencv-python for EXR depth) propagate without making the user
:: re-bootstrap. Already-installed deps are a no-op via pip's resolver.
"%PYTHON_EXE%" -m pip install -q -r "%~dp0requirements.txt" --disable-pip-version-check --no-warn-script-location

"%PYTHON_EXE%" "%~dp0desktop_app.py" %*
