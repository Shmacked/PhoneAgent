# Starts the phone mouse: runs bt_mouse.py in Ubuntu, hands it the Bluetooth chip,
# and waits for the iPhone to pair/connect.
. (Join-Path $PSScriptRoot 'common.ps1')
Refresh-Path

Write-Host 'Starting the phone mouse' -ForegroundColor Cyan
if (-not (Has 'usbipd') -or -not (Has-Distro)) { Fail 'Run "Set up phone mouse.bat" first.'; WaitEnter 'Press Enter to close'; exit 1 }
$bt = Get-Bluetooth
if (-not $bt) { Fail "No Bluetooth chip in 'usbipd list'."; WaitEnter 'Press Enter to close'; exit 1 }
# Windows' own Bluetooth driver holds the chip, so it has to be "force" shared: that
# swaps Windows' driver out until "Give Bluetooth back to Windows.bat" swaps it back.
$forceHelper = Join-Path $Here 'force-bind.ps1'
function Force-Take {
    Info 'Taking the Bluetooth chip away from Windows (asks for administrator permission)...'
    Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$forceHelper`" -HwId $($bt.HwId)"
}
if ($bt.State -notmatch 'forced|Attached') {
    Force-Take
    $bt = Get-Bluetooth
    if ($bt.State -notmatch 'forced|Attached') {
        Fail "Couldn't take the chip from Windows (state: $($bt.State)). Permission cancelled?"
        WaitEnter 'Press Enter to close'; exit 1
    }
    Ok 'Windows let go of the Bluetooth chip'
}

# 1. The Linux half, in its own window (closing that window stops the mouse).
if (Send-Mouse 'status') { Ok 'The mouse program is already running' } else {
    [void](Copy-ToLinux)
    Info 'Opening the mouse program window (leave it open)...'
    Start-Process wsl -ArgumentList "-d $Distro -u root -e bash -c `"python3 /opt/phone-mouse/bt_mouse.py; read -p 'Mouse stopped. Press Enter to close. '`""
    $t = 0
    while (-not (Send-Mouse 'status') -and $t -lt 40) { Start-Sleep 1; $t++ }
    if (-not (Send-Mouse 'status')) {
        Fail "The mouse program didn't start. Look at its window for the error."
        WaitEnter 'Press Enter to close'; exit 1
    }
    Ok 'Mouse program running'
}

# 2. Hand the Bluetooth chip to Linux. --auto-attach keeps it there when the chip
#    restarts itself (it does that after loading its firmware).
# usbipd attaches through the *default* WSL Linux; yours was Docker's, so make it Ubuntu.
$default = (& wsl -l -v 2>$null) | Where-Object { "$_" -match '^\s*\*' } | ForEach-Object { ("$_" -replace '^\s*\*\s*', '').Split(' ')[0] }
if ($default -ne $Distro) {
    Info "Making $Distro the default WSL Linux (was: $default) so usbipd can use it..."
    & wsl --set-default $Distro | Out-Null
}
if (Test-Path $PidFile) {
    Stop-Process -Id (Get-Content $PidFile) -Force -ErrorAction SilentlyContinue
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}
function Attach-Chip {
    if ((Get-Bluetooth).State -notmatch '^Attached') {
        Info 'Handing the Bluetooth chip to Linux (Windows Bluetooth turns off meanwhile)...'
        $outLog = Join-Path $Here 'attach-out.txt'; $errLog = Join-Path $Here 'attach-err.txt'
        $p = Start-Process usbipd -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
            -ArgumentList @('attach', '--wsl', '--hardware-id', $bt.HwId, '--auto-attach')
        Set-Content $PidFile $p.Id
        $t = 0
        while ((Get-Bluetooth).State -notmatch '^Attached' -and $t -lt 15) { Start-Sleep 1; $t++ }
        if ((Get-Bluetooth).State -notmatch '^Attached') {
            Fail "usbipd couldn't hand the chip to Linux. Its messages:"
            Get-Content $outLog, $errLog -ErrorAction SilentlyContinue | Out-Host
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            Remove-Item $PidFile -ErrorAction SilentlyContinue
            Info 'Trying once more in the foreground:'
            $o = & usbipd attach --wsl --hardware-id $bt.HwId 2>&1 | ForEach-Object { "$_" }
            $o | Out-Host
            if ((Get-Bluetooth).State -notmatch '^Attached' -and ($o -join ' ') -match 'used by Windows') {
                # Windows' driver still has it: restart the chip and try once more.
                Force-Take
                & usbipd attach --wsl --hardware-id $bt.HwId 2>&1 | ForEach-Object { "$_" } | Out-Host
            }
            if ((Get-Bluetooth).State -notmatch '^Attached') {
                Fail 'Still not attached. Restart Windows (the forced sharing stays on), then run this again.'
                Info "Chip state now: $((Get-Bluetooth).State)"
                Info 'If it fails after a restart too, run "Bluetooth check.bat" and keep bt-check.txt.'
                WaitEnter 'Press Enter to close'; exit 1
            }
        }
    }
}
Attach-Chip
Ok 'Bluetooth chip handed to Linux'

# 3. Wait for Linux to bring the chip up.
function Wait-Adapter($secs) {
    $t = 0
    while ((Send-Mouse 'status') -eq 'no-adapter' -and $t -lt $secs) {
        Start-Sleep 1; $t++
        # Stuck in its bootloader (no firmware loaded: Linux here has no firmware file for it)?
        if ($t -ge 15 -and $t % 5 -eq 0) {
            $log = In-Linux 'dmesg | tail -30'
            if (($log -join ' ') -match 'Failed to load Intel firmware|Bootloader timestamp') { return 'no-firmware' }
        }
    }
    return Send-Mouse 'status'
}
$st = Wait-Adapter 90
if ($st -eq 'no-firmware') {
    # After Windows restarts, the forced sharing keeps Windows' driver off the chip, so nothing
    # loads its firmware and it stays in its bootloader. Let Windows' driver start it once
    # (that loads the firmware), then take it back: the firmware stays loaded.
    Info 'The Bluetooth chip has no firmware loaded yet (normal after a Windows restart).'
    Info 'Letting Windows start it once, then taking it back (asks for administrator permission once)...'
    if (Test-Path $PidFile) {
        Stop-Process -Id (Get-Content $PidFile) -Force -ErrorAction SilentlyContinue
        Remove-Item $PidFile -ErrorAction SilentlyContinue
    }
    & usbipd detach --hardware-id $bt.HwId 2>$null | Out-Null
    $warm = Join-Path $Here 'warm-bind.ps1'
    Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$warm`" -HwId $($bt.HwId)"
    $bt = Get-Bluetooth
    if ($bt.State -notmatch 'forced|Attached') {
        Fail "Couldn't take the chip back from Windows (state: $($bt.State)). Permission cancelled?"
        WaitEnter 'Press Enter to close'; exit 1
    }
    Ok 'Windows started the chip; taken back'
    In-Linux 'dmesg -C' | Out-Null      # (so the old firmware error isn't read again)
    Attach-Chip
    Ok 'Bluetooth chip handed to Linux again'
    $st = Wait-Adapter 90
}
if ($st -eq 'no-adapter' -or $st -eq 'no-firmware' -or -not $st) {
    Fail "Linux didn't get the Bluetooth chip working. Details:"
    In-Linux 'lsusb 2>/dev/null | grep -i -e 8087 -e bluetooth; dmesg | grep -i -e bluetooth -e btusb -e btintel -e firmware -e usbip | tail -40'
    WaitEnter 'Press Enter to close'; exit 1
}
Ok 'Bluetooth chip is working in Linux'

# 4. Pair / connect.
if ($st -ne 'connected') {
    Write-Host ''
    Todo 'On the iPhone (first time only):'
    Info '    1. Settings > Accessibility > Touch > AssistiveTouch > On'
    Info '    2. Settings > Bluetooth > under "Other Devices" tap "Phone Mouse"'
    Info '       (if it is not listed: Settings > Accessibility > Touch > AssistiveTouch > Devices > Bluetooth Devices)'
    Info '    Already paired before? Just make sure Bluetooth is on; it reconnects by itself.'
    Info 'Waiting for the iPhone... (Ctrl+C to stop waiting)'
    while ((Send-Mouse 'status') -ne 'connected') { Start-Sleep 1 }
}
Ok 'iPhone connected. You should see a round pointer on the phone.'
Info 'Run "Test mouse.bat" to move it around.'
WaitEnter 'Press Enter to close this window (the mouse keeps running)'
