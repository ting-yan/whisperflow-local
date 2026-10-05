@echo off
rem WhisperFlow Local updater - quit the app first, then run this.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update.ps1"
pause
