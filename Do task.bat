@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: Do task.bat Open the Clock app
  echo The mirror and the phone mouse must already be running.
  echo If Start PhoneAgent.bat is open, use: python -m phone_remote queue 1 do Open the Clock app
  pause
  exit /b 1
)
set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" (
  "%PY%" -m phone_remote do %*
) else (
  py -3 -m phone_remote do %*
)
if errorlevel 1 pause
