# Stops the phone mouse and gives the Bluetooth chip back to Windows.
. (Join-Path $PSScriptRoot 'common.ps1')
Refresh-Path

Write-Host 'Giving Bluetooth back to Windows' -ForegroundColor Cyan
[void](Send-Mouse 'quit')
if (Test-Path $PidFile) {
    Stop-Process -Id (Get-Content $PidFile) -Force -ErrorAction SilentlyContinue
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}
$bt = Get-Bluetooth
if ($bt) { & usbipd detach --hardware-id $bt.HwId 2>$null | Out-Null }
if (Has-Distro) { In-Linux 'pkill -f bt_mouse.py; pkill -x bluetoothd; true' 2>$null | Out-Null }
if ($bt -and $bt.State -match 'forced|Shared|Attached') {
    Info 'Giving the chip back to Windows'' Bluetooth driver (asks for administrator permission)...'
    Start-Process usbipd -Verb RunAs -Wait -ArgumentList @('unbind', '--hardware-id', $bt.HwId)
}
$bt = Get-Bluetooth
if ($bt -and $bt.State -match 'forced|Attached') {
    Fail "The chip is still taken (state: $($bt.State)). Run this again, or restart Windows."
} else {
    Ok 'Done. Windows Bluetooth should come back within a few seconds (if not, toggle Bluetooth off/on in Settings).'
}
WaitEnter 'Press Enter to close'
