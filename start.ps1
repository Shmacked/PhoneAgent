# Starts UxPlay (AirPlay) if needed, the bundled phone mouse if needed, then the agent.
# -Calibrate writes data/mouse.json instead of leaving the agent running.
param([switch]$Calibrate)
$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
Set-Location $Here

$configPath = Join-Path $Here 'config.json'
$mouseDir = Join-Path $Here 'mouse'
$airplayName = ''
$mirrorTitle = 'Direct3D12 Renderer'
$msysShell = 'C:\msys64\msys2_shell.cmd'
$uxplayExe = ''
$videoSink = ''
if (Test-Path $configPath) {
    $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($cfg.phone_mouse_dir) {
        $raw = [string]$cfg.phone_mouse_dir
        if ([IO.Path]::IsPathRooted($raw)) { $mouseDir = $raw } else { $mouseDir = Join-Path $Here $raw }
    }
    if ($cfg.airplay_name) { $airplayName = ([string]$cfg.airplay_name).Trim() }
    if ($cfg.mirror_title) { $mirrorTitle = [string]$cfg.mirror_title }
    if ($cfg.msys_shell) { $msysShell = [string]$cfg.msys_shell }
    if ($cfg.uxplay_exe) { $uxplayExe = [string]$cfg.uxplay_exe }
    if ($cfg.videosink) { $videoSink = ([string]$cfg.videosink).Trim() }
}
if (-not $videoSink) { $videoSink = 'd3d12videosink' }
if (-not $airplayName) {
    Write-Host 'Set "airplay_name" in config.json. That is the name the iPhone shows under Screen Mirroring.' -ForegroundColor Red
    exit 1
}

function Test-Mouse {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ar = $c.BeginConnect('127.0.0.1', 7777, $null, $null)
        if (-not $ar.AsyncWaitHandle.WaitOne(800)) { $c.Close(); return $null }
        $c.EndConnect($ar)
        $s = $c.GetStream()
        $w = New-Object System.IO.StreamWriter($s); $w.NewLine = "`n"; $w.AutoFlush = $true
        $r = New-Object System.IO.StreamReader($s)
        $w.WriteLine('status')
        $ans = $r.ReadLine()
        $c.Close()
        return $ans
    } catch { return $null }
}

function Find-UxPlay {
    if ($uxplayExe -and (Test-Path $uxplayExe)) { return $uxplayExe }
    $cmd = Get-Command uxplay -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $fallback = 'C:\msys64\ucrt64\bin\uxplay.exe'
    if (Test-Path $fallback) { return $fallback }
    return $null
}

function Start-UxPlay {
    $ux = Find-UxPlay
    if (-not $ux) {
        Write-Host "UxPlay was not found." -ForegroundColor Red
        Write-Host "Install MSYS2 from https://www.msys2.org/ then double-click Build UxPlay.bat."
        return $false
    }
    $running = Get-Process -Name uxplay -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host "UxPlay is already running (pid $($running.Id -join ', '))." -ForegroundColor Green
        Write-Host "It keeps the name it was started with. Close that window and run this again to broadcast as '$airplayName'."
        return $true
    }
    if (-not (Test-Path $msysShell)) {
        Write-Host "MSYS2 shell not found at $msysShell" -ForegroundColor Red
        Write-Host "Set msys_shell in config.json, or install MSYS2 and run Build UxPlay.bat."
        return $false
    }
    $bat = Join-Path $Here 'run_uxplay.bat'
    Write-Host "Starting AirPlay receiver as '$airplayName'..." -ForegroundColor Cyan
    Start-Process -FilePath $bat -ArgumentList @($airplayName, $msysShell, $videoSink) -WindowStyle Minimized
    return $true
}

# --- 1. AirPlay receiver ---
if (-not (Start-UxPlay)) { exit 1 }
Write-Host "On the iPhone: Control Center > Screen Mirroring > $airplayName" -ForegroundColor Yellow

# --- 2. Phone mouse ---
$st = Test-Mouse
if (-not $st) {
    Write-Host "Phone mouse is not running on :7777." -ForegroundColor Yellow
    Write-Host "Starting it from: $mouseDir"
    $bat = Join-Path $mouseDir 'Start phone mouse.bat'
    if (-not (Test-Path $bat)) {
        Write-Host "Missing $bat" -ForegroundColor Red
        exit 1
    }
    Start-Process -FilePath $bat
    Write-Host "Waiting for phone mouse (pair/reconnect iPhone if needed)..."
    $t = 0
    while (-not (Test-Mouse) -and $t -lt 120) { Start-Sleep 2; $t += 2 }
    $st = Test-Mouse
    if (-not $st) {
        Write-Host "Still no mouse on :7777. Finish pairing, then re-run." -ForegroundColor Red
        exit 1
    }
}
Write-Host "Phone mouse: $st" -ForegroundColor $(if ($st -eq 'connected') { 'Green' } else { 'Yellow' })
if ($st -ne 'connected') {
    Write-Host "Waiting for iPhone to connect to Phone Mouse (AssistiveTouch + Bluetooth)..." -ForegroundColor Yellow
    $t = 0
    while (((Test-Mouse) -ne 'connected') -and $t -lt 90) { Start-Sleep 2; $t += 2 }
    $st = Test-Mouse
    Write-Host "Phone mouse: $st" -ForegroundColor $(if ($st -eq 'connected') { 'Green' } else { 'Yellow' })
}

# --- 3. Python agent ---
$venvPy = Join-Path $Here '.venv\Scripts\python.exe'
$uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating .venv and installing deps..."
    if (Test-Path $uv) {
        & $uv venv (Join-Path $Here '.venv')
        & $uv pip install -e $Here --python $venvPy
    } else {
        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if (-not $pyLauncher) { Write-Host "Need uv or the Windows py launcher" -ForegroundColor Red; exit 1 }
        & py -3 -m venv (Join-Path $Here '.venv')
        & $venvPy -m pip install -e $Here -q
    }
    if (-not (Test-Path $venvPy)) { Write-Host "venv python missing" -ForegroundColor Red; exit 1 }
}

if ($Calibrate) {
    Write-Host ""
    Write-Host "Calibrating the pointer against '$mirrorTitle'." -ForegroundColor Cyan
    Write-Host "Keep the phone still. AssistiveTouch on, pointer visible, nothing animating."
    & $venvPy -m phone_remote --title $mirrorTitle calibrate
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Agent running. Mirror to '$airplayName', then leave this window open." -ForegroundColor Cyan
Write-Host "Window match: '$mirrorTitle' (change mirror_title in config.json if shots miss)."
Write-Host "Write data\remote\cmd.txt ; shots land in data\remote\shot.png"
& $venvPy -m phone_remote --title $mirrorTitle agent
