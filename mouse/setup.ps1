# One-time setup for the phone mouse: Ubuntu in WSL, Bluetooth software, and
# permission to hand the PC's Bluetooth chip to Linux. Safe to run again.
. (Join-Path $PSScriptRoot 'common.ps1')

function Step($n, $title) { Write-Host ''; Write-Host "=== Step $n of 4: $title ===" -ForegroundColor Cyan }

Write-Host 'Phone mouse setup' -ForegroundColor Cyan
Write-Host 'Makes your PC show up to the iPhone as a Bluetooth mouse. Nothing is installed on the phone.'

# ---------------------------------------------------------------- 1. usbipd
Step 1 'usbipd (hands a USB device from Windows to Linux)'
Refresh-Path
if (Has 'usbipd') { Ok 'usbipd is installed' } else {
    Info 'Installing usbipd-win (a Windows prompt may ask for permission)...'
    & winget install --id dorssel.usbipd-win -e --accept-package-agreements --accept-source-agreements | Out-Host
    Refresh-Path
    if (-not (Has 'usbipd')) { Fail 'usbipd did not install. Close this window, open a new one and run setup again.'; WaitEnter 'Press Enter to close'; exit 1 }
    Ok 'usbipd installed'
}
$bt = Get-Bluetooth
if (-not $bt) { Fail "No Bluetooth chip shows up in 'usbipd list'. Is Bluetooth turned on in Windows?"; WaitEnter 'Press Enter to close'; exit 1 }
Ok "Bluetooth chip: $($bt.Name) ($($bt.HwId))"

# ---------------------------------------------------------------- 2. Ubuntu
Step 2 "Ubuntu Linux in WSL ($Distro)"
if (Has-Distro) { Ok "$Distro is installed" } else {
    Todo 'Ubuntu will install now. When it asks, make up a Linux username and password'
    Todo '(they are only for this Linux, any will do). When you see a prompt ending in $, type:  exit'
    WaitEnter 'Press Enter to start'
    & wsl --install -d $Distro
    if (-not (Has-Distro)) {
        Fail 'Ubuntu did not finish installing. If Windows asked to restart, restart and run setup again.'
        WaitEnter 'Press Enter to close'; exit 1
    }
    Ok "$Distro installed"
}

# ---------------------------------------------------------------- 3. Linux packages
Step 3 'Bluetooth software inside Ubuntu (BlueZ)'
In-Linux 'dpkg -s bluez python3-dbus python3-gi zstd >/dev/null 2>&1' | Out-Null
if ($LASTEXITCODE -eq 0) { Ok 'BlueZ and helpers are installed' } else {
    Info 'Installing (takes a minute or two)...'
    In-Linux 'export DEBIAN_FRONTEND=noninteractive; apt-get update -q && apt-get install -y -q bluez python3-dbus python3-gi zstd usbutils' | Out-Host
    In-Linux 'dpkg -s bluez python3-dbus python3-gi >/dev/null 2>&1' | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail 'Installing BlueZ failed (see above). Check your internet connection and run setup again.'; WaitEnter 'Press Enter to close'; exit 1 }
    Ok 'Installed'
}
# The phone mouse runs its own copy of bluetoothd with special settings; keep Ubuntu's from competing.
In-Linux 'systemctl disable --now bluetooth >/dev/null 2>&1; systemctl mask bluetooth >/dev/null 2>&1; true'
if (Copy-ToLinux) { Ok 'Phone mouse program copied into Ubuntu' }

# ---------------------------------------------------------------- 4. permission to share the chip
Step 4 'Allow sharing the Bluetooth chip with Linux'
$bt = Get-Bluetooth
if ($bt.State -match '^(Shared|Attached)') { Ok 'Already allowed' } else {
    Info 'Windows will ask for administrator permission once.'
    Start-Process usbipd -Verb RunAs -Wait -ArgumentList @('bind', '--hardware-id', $bt.HwId)
    $bt = Get-Bluetooth
    if ($bt.State -match '^(Shared|Attached)') { Ok 'Allowed' } else { Fail 'Sharing was not allowed (permission cancelled?). Run setup again.'; WaitEnter 'Press Enter to close'; exit 1 }
}
Info 'Note: while the phone mouse runs, Windows itself has no Bluetooth (headphones etc.).'
Info '      "Give Bluetooth back to Windows.bat" returns it.'

Write-Host ''
Write-Host 'Setup done.' -ForegroundColor Green
$ans = Read-Host '  Start the phone mouse now? [Y/n]'
if ($ans -notmatch '^[nN]') { & (Join-Path $Here 'start.ps1') }
