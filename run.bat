@echo off
:: captureAIshi — Launch with embedded Python
:: Run bootstrap.bat first if this is a new machine.

set PYTHON_EXE=%~dp0python\python.exe

if not exist "%PYTHON_EXE%" (
    echo Embedded Python not found. Running bootstrap first...
    call "%~dp0bootstrap.bat"
    if errorlevel 1 exit /b 1
)

"%PYTHON_EXE%" "%~dp0desktop_app.py" %*
