@echo off
setlocal
cd /d "%~dp0"

if exist "dist\Substack2Kindle.exe" (
    set "APP_DIR=%CD%\dist"
    set "APP_EXE=%CD%\dist\Substack2Kindle.exe"
) else (
    set "APP_DIR=%CD%"
)

if not exist "%APP_DIR%\.env" (
    copy ".env.example" "%APP_DIR%\.env" >nul
    start "" notepad.exe "%APP_DIR%\.env"
    echo Configure your Kindle and Gmail settings in the .env file, then come back here.
    pause
)

if defined APP_EXE (
    start "" "%APP_EXE%"
    exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>&1
    if errorlevel 1 (
        echo Python 3 was not found. Install Python from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Could not create the Python environment.
        pause
        exit /b 1
    )
)

if not exist ".venv\.requirements-installed" (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Could not install the application requirements.
        pause
        exit /b 1
    )
    echo installed>".venv\.requirements-installed"
)

".venv\Scripts\python.exe" desktop_app.py
if errorlevel 1 (
    echo The desktop app stopped with an error.
    pause
)
