@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test-mouse.ps1"
if errorlevel 1 pause
