@echo off
REM Двойной клик или запуск из cmd: поднимает backend, затем frontend.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dev.ps1"
pause
