# Runs as administrator (started by start.ps1). The chip came up without firmware (Windows
# restarted while it was force-shared, so Windows' driver never started it). Give it back
# to Windows' driver so that loads the firmware, wait for Windows Bluetooth to work, then
# force-share it again.
param([string]$HwId)
& usbipd unbind --hardware-id $HwId | Out-Null
$vid, $pid_ = $HwId.Split(':')
$pattern = "USB\VID_$($vid.ToUpper())&PID_$($pid_.ToUpper())*"
foreach ($d in (Get-PnpDevice -InstanceId $pattern -ErrorAction SilentlyContinue)) {
    & pnputil /restart-device "$($d.InstanceId)" | Out-Null
}
# Wait (up to 40 s) for a working Windows Bluetooth radio, then a little longer.
$t = 0
while ($t -lt 40) {
    Start-Sleep 2; $t += 2
    $ok = Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue |
          Where-Object { $_.Status -eq 'OK' -and $_.FriendlyName -match 'Wireless Bluetooth|Bluetooth\(R\)' }
    if ($ok) { break }
}
Start-Sleep 5
# Take it again, the same way force-bind.ps1 does (a device restart makes Windows' driver
# let go; the firmware stays loaded through it - that's how it worked on the first runs).
& usbipd bind --force --hardware-id $HwId | Out-Null
foreach ($d in (Get-PnpDevice -InstanceId $pattern -ErrorAction SilentlyContinue)) {
    & pnputil /restart-device "$($d.InstanceId)" | Out-Null
}
Start-Sleep 3
