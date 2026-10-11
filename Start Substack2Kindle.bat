@echo off
setlocal
cd /d "%~dp0"

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

if not exist ".env" (
    copy ".env.example" ".env" >nul
    start "" notepad.exe "%CD%\.env"
    echo Configure your Kindle and Gmail settings in the .env file, then come back here.
    pause
)

".venv\Scripts\python.exe" web_app.py --open-browser
if errorlevel 1 (
    echo The web app stopped with an error.
    pause
)
