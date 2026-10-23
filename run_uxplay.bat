@echo off
rem Starts UxPlay as the AirPlay receiver.
rem The name comes from config.json "airplay_name", unless arg1 is passed.
rem Arg2 = path to msys2_shell.cmd (otherwise config.json "msys_shell").
rem Arg3 = GStreamer videosink (otherwise config.json "videosink", otherwise d3d12videosink).
rem Phone and PC must be on the same Wi-Fi.
rem If the window is black, set videosink to d3d11videosink in config.json.
setlocal
cd /d "%~dp0"
set "NAME=%~1"
set "MSYS=%~2"
set "SINK=%~3"
if "%NAME%"=="" (
  for /f "usebackq delims=" %%N in (`powershell -NoProfile -Command "$c = Get-Content -Raw -LiteralPath '%~dp0config.json' | ConvertFrom-Json; $c.airplay_name"`) do set "NAME=%%N"
)
if "%MSYS%"=="" (
  for /f "usebackq delims=" %%M in (`powershell -NoProfile -Command "$c = Get-Content -Raw -LiteralPath '%~dp0config.json' | ConvertFrom-Json; if ($c.msys_shell) { $c.msys_shell } else { 'C:\msys64\msys2_shell.cmd' }"`) do set "MSYS=%%M"
)
if "%SINK%"=="" (
  for /f "usebackq delims=" %%S in (`powershell -NoProfile -Command "$c = Get-Content -Raw -LiteralPath '%~dp0config.json' | ConvertFrom-Json; if ($c.videosink) { $c.videosink } else { 'd3d12videosink' }"`) do set "SINK=%%S"
)
if "%SINK%"=="" set "SINK=d3d12videosink"
if "%NAME%"=="" (
  echo Set "airplay_name" in config.json. That is the name the iPhone shows under Screen Mirroring.
  exit /b 1
)
if not exist "%MSYS%" (
  echo MSYS2 shell not found at %MSYS%
  exit /b 1
)
call "%MSYS%" -ucrt64 -defterm -no-start -c "uxplay -n \"%NAME%\" -nh -p -vs %SINK%"
