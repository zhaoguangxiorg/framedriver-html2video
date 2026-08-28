@echo off
REM ============================================================
REM Deployment script (Windows)
REM 1. Create virtual environment  2. Install requirements.txt (versions locked)
REM 3. Download Chromium into project-local .playwright-browsers (matches code path)
REM Usage: scripts\setup.bat
REM ============================================================
setlocal
cd /d "%~dp0.."

echo [1/3] Creating virtual environment .venv ...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :err
) else (
    echo      .venv already exists, skipping
)

echo [2/3] Installing Python dependencies (versions locked in requirements.txt)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :err

echo [3/3] Downloading Chromium to project-local .playwright-browsers (matches html_to_image.py path)...
set "PLAYWRIGHT_BROWSERS_PATH=%CD%\.playwright-browsers"
".venv\Scripts\playwright.exe" install chromium
if errorlevel 1 goto :err

echo.
echo ============================================================
echo Deployment complete!
echo Start server: .venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
echo ============================================================
pause
exit /b 0

:err
echo.
echo Deployment failed, please check the error message above.
pause
exit /b 1
