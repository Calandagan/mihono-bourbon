@echo off
setlocal
cd /d "%~dp0"
git pull --autostash -X ours --no-edit

winget install -e --id Google.PlatformTools --accept-package-agreements --accept-source-agreements

adb kill-server
adb start-server

set UAT_AUTORESTART=1

REM Use the venv created by setup.bat so pip + run all happen inside it.
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo [start] venv not found - falling back to system Python.
    echo [start] Run setup.bat once for a clean venv-based install.
)

pip install -r requirements.txt
python bake_templates.py
python main.py
