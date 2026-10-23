# Shared helpers for the phone mouse scripts (dot-sourced, not run directly).
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$env:WSL_UTF8 = '1'          # make `wsl -l` print normal text instead of UTF-16
$Distro = 'Ubuntu-24.04'
$Here = $PSScriptRoot
$PidFile = Join-Path $Here 'attach.pid'

function Ok($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "  $msg" }
function Todo($msg) { Write-Host "  >>  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  !!  $msg" -ForegroundColor Red }
function WaitEnter($msg = 'Press Enter when done') { [void](Read-Host "  $msg") }
function Has($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Has-Distro {
    $names = (& wsl -l -q 2>$null) | ForEach-Object { "$_".Trim([char]0, ' ') } | Where-Object { $_ }
    return @($names) -contains $Distro
}

# Run a bash command in Ubuntu as root. Don't put double quotes in $cmd.
# -e runs bash directly (with `--` WSL would first pass everything through a shell,
# which eats backslashes and $variables).
function In-Linux($cmd) { & wsl -d $Distro -u root -e bash -c $cmd }

function Linux-Path($winPath) {
    # C:\Users\Me\x -> /mnt/c/Users/Me/x
    $full = [IO.Path]::GetFullPath($winPath)
    return '/mnt/' + $full.Substring(0, 1).ToLower() + ($full.Substring(2) -replace '\\', '/')
}

function Get-Bluetooth {
    # Finds the Bluetooth chip in `usbipd list`, e.g. "2-14  8087:0036  Intel(R) Wireless Bluetooth(R)  Not shared"
    foreach ($line in (& usbipd list 2>$null)) {
        if ($line -match '^\s*(\d+-[\d.]+)\s+([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+(.+?)\s{2,}(\S.*?)\s*$') {
            $m = $Matches.Clone()   # the next -match would overwrite $Matches
            if ($m[3] -like '*Bluetooth*') {
                return [pscustomobject]@{ BusId = $m[1]; HwId = $m[2]; Name = $m[3]; State = $m[4] }
            }
        }
    }
    return $null
}

function Send-Mouse($cmd, $timeoutMs = 3000) {
    # One command to bt_mouse.py running in WSL; returns its one-line answer or $null.
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ar = $c.BeginConnect('127.0.0.1', 7777, $null, $null)
        if (-not $ar.AsyncWaitHandle.WaitOne(1500)) { $c.Close(); return $null }
        $c.EndConnect($ar)
        $c.ReceiveTimeout = $timeoutMs
        $s = $c.GetStream()
        $w = New-Object System.IO.StreamWriter($s); $w.NewLine = "`n"; $w.AutoFlush = $true
        $r = New-Object System.IO.StreamReader($s)
        $w.WriteLine($cmd)
        $ans = $r.ReadLine()
        $c.Close()
        return $ans
    } catch { return $null }
}

function Copy-ToLinux {
    # Copies the Linux half (bt_mouse.py, main.conf) into Ubuntu, fixing Windows line endings.
    $src = Linux-Path $Here
    In-Linux "mkdir -p /opt/phone-mouse && for f in bt_mouse.py main.conf; do tr -d '\r' < '$src'/`$f > /opt/phone-mouse/`$f || exit 1; done" | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "Couldn't copy the mouse program into Linux (from $src)."; return $false }
    return $true
}
