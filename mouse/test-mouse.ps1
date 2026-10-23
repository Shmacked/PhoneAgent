# Moves the iPhone's pointer around so you can see the phone mouse working.
. (Join-Path $PSScriptRoot 'common.ps1')

Write-Host 'Phone mouse test' -ForegroundColor Cyan
$st = Send-Mouse 'status'
if (-not $st) { Fail 'The phone mouse is not running. Run "Start phone mouse.bat" first.'; WaitEnter 'Press Enter to close'; exit 1 }
if ($st -ne 'connected') { Fail "The iPhone isn't connected yet (status: $st). Run ""Start phone mouse.bat""."; WaitEnter 'Press Enter to close'; exit 1 }

Info 'Watch the phone: the pointer goes to the top-left corner, then draws a square. No taps.'
WaitEnter 'Press Enter to start'
function Run-Cmd($cmd) {
    $ans = Send-Mouse $cmd 30000
    if ($ans -ne 'ok') { Fail "$cmd -> $ans" } else { Info "$cmd" }
}
Run-Cmd 'home'
Start-Sleep -Milliseconds 500
Run-Cmd 'move 150 250'
foreach ($m in 'move 200 0', 'move 0 200', 'move -200 0', 'move 0 -200') { Run-Cmd $m; Start-Sleep -Milliseconds 300 }

Write-Host ''
Info 'Try commands yourself. Examples:  move 100 0   move 0 -50   home   click   scroll -3   pace 4 10'
Info '(click taps wherever the pointer is.)  Empty line quits.'
while ($true) {
    $cmd = Read-Host '  command'
    if (-not $cmd.Trim()) { break }
    Info ('-> ' + (Send-Mouse $cmd 30000))
}
