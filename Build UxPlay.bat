@echo off
cd /d "%~dp0"
set "MSYS=C:\msys64\msys2_shell.cmd"
if not exist "%MSYS%" (
  echo MSYS2 was not found at C:\msys64. Install it from https://www.msys2.org/ and try again.
  pause & exit /b 1
)
echo === Updating MSYS2 (pass 1 of 2) ===
call "%MSYS%" -ucrt64 -defterm -no-start -here -c "pacman -Syuu --noconfirm"
echo === Updating MSYS2 (pass 2 of 2) ===
call "%MSYS%" -ucrt64 -defterm -no-start -here -c "pacman -Syuu --noconfirm"
echo === Building UxPlay ===
call "%MSYS%" -ucrt64 -defterm -no-start -here -c "bash ./build_uxplay.sh 2>&1 | tee build_uxplay.log"
echo.
echo Finished. If anything failed, the log is build_uxplay.log
pause
