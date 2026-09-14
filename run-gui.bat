@echo off
setlocal
cd /d "%~dp0"

uv run --extra gui retro-tools-gui
if errorlevel 1 (
    echo.
    echo retro-tools gui exited with an error.
    pause
)
