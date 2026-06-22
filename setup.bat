@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Mihono-Bourbon - one-time setup
echo ============================================
echo.
echo This installs Python 3.10, Visual C++, ADB, creates a venv and installs
echo all dependencies. Run it once. For daily use, run start.bat afterwards.
echo.
pause

REM --- 1. Python 3.10 ---
echo.
echo [1/5] Installing Python 3.10 (skips if already installed)...
winget install -e --id Python.Python.3.10 --accept-package-agreements --accept-source-agreements

REM --- 2. Visual C++ Redistributable (needed for OCR / paddle) ---
echo.
echo [2/5] Installing Visual C++ Redistributable...
winget install -e --id Microsoft.VCRedist.2015+.x64 --accept-package-agreements --accept-source-agreements

REM --- 3. ADB platform-tools ---
echo.
echo [3/5] Installing ADB platform-tools...
winget install -e --id Google.PlatformTools --accept-package-agreements --accept-source-agreements

REM --- 4. Locate Python 3.10 and create the venv ---
REM winget just added Python to PATH, but THIS window still has the old PATH,
REM so we call Python by its explicit install path instead of relying on PATH.
echo.
echo [4/5] Creating virtual environment (venv)...
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3.10"
)
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo.
    echo Could not find Python 3.10 in this session.
    echo Close this window, open a NEW terminal, and run setup.bat again.
    pause
    exit /b 1
)

if not exist venv (
    %PY% -m venv venv
) else (
    echo venv already exists, reusing it.
)

REM --- 5. Install dependencies into the venv ---
echo.
echo [5/5] Installing dependencies (this can take several minutes)...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python bake_templates.py

echo.
echo ============================================
echo   Setup complete.
echo.
echo   Next steps:
echo   1) Configure your emulator (MuMu): 720x1280, DPI 180, ADB ON.
echo   2) In-game, pick your Uma / Legacy Uma / Support Cards.
echo   3) Run start.bat to launch the bot.
echo ============================================
pause
