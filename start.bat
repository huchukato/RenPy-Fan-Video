@echo off
REM RenPy-Fan-Video - Windows Launcher

set SCRIPT_DIR=%~dp0

where uv >nul 2>nul
if errorlevel 1 (
    echo [FanVideo] uv not found. Installing uv...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
)

echo [FanVideo] Starting...
cd /d "%SCRIPT_DIR%"
uv run fv_tool.py
pause
