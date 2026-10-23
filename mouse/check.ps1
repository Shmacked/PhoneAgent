# Collects Bluetooth details into bt-check.txt (in this folder) for troubleshooting.
. (Join-Path $PSScriptRoot 'common.ps1')
Refresh-Path
$out = Join-Path $Here 'bt-check.txt'
Write-Host 'Collecting Bluetooth details...' -ForegroundColor Cyan
$report = @()
$report += '=== usbipd list ==='; $report += (& usbipd list 2>&1)
$report += ''; $report += '=== wsl -l -v ==='; $report += (& wsl -l -v 2>&1)
$report += ''; $report += '=== attach log ==='; $report += (Get-Content (Join-Path $Here 'attach-out.txt'), (Join-Path $Here 'attach-err.txt') -ErrorAction SilentlyContinue)
$report += ''; $report += "=== mouse status: $(Send-Mouse 'status') ==="
$report += ''; $report += (In-Linux @'
echo '=== processes ==='; ps aux | grep -e bluetoothd -e bt_mouse | grep -v grep
echo; echo '=== btmgmt info ==='; timeout 5 btmgmt info 2>&1
echo; echo '=== bluetoothctl show ==='; timeout 5 bluetoothctl show 2>&1
echo; echo '=== bluetoothctl devices ==='; timeout 5 bluetoothctl devices 2>&1
echo; echo '=== hciconfig -a ==='; hciconfig -a 2>&1
echo; echo '=== dmesg ==='; dmesg | grep -i -e bluetooth -e btusb -e btintel -e firmware -e usbip | tail -40
echo; echo '=== mouse log ==='; tail -150 /opt/phone-mouse/log.txt 2>&1
'@ 2>$null)
$report | Out-File -Encoding utf8 $out
Ok "Saved $out"
Info 'Attach bt-check.txt if you ask for help.'
WaitEnter 'Press Enter to close'
