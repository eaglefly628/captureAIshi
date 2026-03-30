@echo off
:: captureAIshi — CLI mode with embedded Python
:: Usage: run_cli.bat --driver manual --dry-run

set PYTHON_EXE=%~dp0python\python.exe

if not exist "%PYTHON_EXE%" (
    echo Embedded Python not found. Running bootstrap first...
    call "%~dp0bootstrap.bat"
    if errorlevel 1 exit /b 1
)

"%PYTHON_EXE%" "%~dp0main.py" %*
