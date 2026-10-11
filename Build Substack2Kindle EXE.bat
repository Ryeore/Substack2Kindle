@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    echo Python 3 was not found. Install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

py -3 -m pip install -r requirements-build.txt
if errorlevel 1 (
    echo Could not install the executable build requirements.
    pause
    exit /b 1
)

py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name Substack2Kindle --add-data ".env.example;." desktop_app.py
if errorlevel 1 (
    echo Could not build the executable.
    pause
    exit /b 1
)

copy ".env.example" "dist\.env.example" >nul
echo.
echo Standalone app created: %CD%\dist\Substack2Kindle.exe
echo Double-click Start Substack2Kindle.bat to launch it.
pause
