@echo off
setlocal
cd /d "%~dp0"
git pull --autostash -X ours --no-edit

where winget >nul 2>nul
if ERRORLEVEL 1 (
    echo winget not found
    exit /b 1
)

where adb >nul 2>nul
if ERRORLEVEL 1 (
    winget install -e --id Google.PlatformTools --accept-package-agreements --accept-source-agreements
)

adb kill-server
adb start-server

pip install -r requirements.txt

set UAT_AUTORESTART=1

where python3 >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python3 main.py
    if %ERRORLEVEL% EQU 0 goto :end
)

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
    python main.py
) else (
    python main.py
)

:end
