@echo off
rem WhisperFlow Local installer - installs Python if needed, then deps + shortcuts.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
pause
