@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check.ps1"
if errorlevel 1 pause
