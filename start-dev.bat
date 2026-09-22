@echo off
rem googletranslate-2api dev launcher (Windows)
rem all logic and messages live in start.ps1
setlocal
cd /d "%~dp0"
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
exit /b %errorlevel%
