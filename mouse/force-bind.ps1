# Runs as administrator (started by start.ps1). Force-shares the Bluetooth chip, then
# restarts it so Windows' Bluetooth driver lets go right away (otherwise that only
# happens after a reboot).
param([string]$HwId)
& usbipd bind --force --hardware-id $HwId
$vid, $pid_ = $HwId.Split(':')
$pattern = "USB\VID_$($vid.ToUpper())&PID_$($pid_.ToUpper())*"
foreach ($d in (Get-PnpDevice -InstanceId $pattern -ErrorAction SilentlyContinue)) {
    & pnputil /restart-device "$($d.InstanceId)" | Out-Null
}
Start-Sleep 3
