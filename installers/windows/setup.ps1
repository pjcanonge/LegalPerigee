# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee v1.1 — Windows Setup & Conflict Resolver (PowerShell)
#
# Handles: fresh install, upgrade, reinstall, and all common conflicts.
# Right-click → "Run with PowerShell"
#   OR: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass; .\setup.ps1
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Continue"   # Don't exit on non-critical errors
$Version    = "1.1"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$VenvDir    = Join-Path $ProjectDir ".venv"
$VenvPy     = Join-Path $VenvDir "Scripts\python.exe"
$ReqFile    = Join-Path $ProjectDir "requirements.txt"
$LogFile    = "$env:TEMP\LegalPerigee_setup.log"

function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    "$ts  $msg" | Tee-Object -FilePath $LogFile -Append | Out-Null
    Write-Host "     $msg" -ForegroundColor Gray
}
function OK($msg)   { Write-Host "  ✅  $msg" -ForegroundColor Green;  Log "OK: $msg" }
function Warn($msg) { Write-Host "  ⚠️   $msg" -ForegroundColor Yellow; Log "WARN: $msg" }
function Fail($msg) { Write-Host "  ❌  $msg" -ForegroundColor Red;    Log "FAIL: $msg" }
function Header($msg) { Write-Host "`n  $msg" -ForegroundColor Cyan }

Clear-Host
Write-Host ""
Write-Host "  ⚖  LegalPerigee v$Version — Windows Setup" -ForegroundColor Cyan
Write-Host "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host "  Legal Case Intelligence Platform" -ForegroundColor Gray
Write-Host "  Log: $LogFile" -ForegroundColor DarkGray
Write-Host ""

# ── Detect existing installation ──────────────────────────────────────────────
Header "Checking for existing installation..."

$IsUpgrade    = $false
$IsReinstall  = $false
$ExistingVer  = ""

$VerFile = Join-Path $VenvDir ".legalperigee_version"
if (Test-Path $VerFile) {
    $ExistingVer = (Get-Content $VerFile).Trim()
    if ($ExistingVer -eq $Version) {
        $IsReinstall = $true
        Warn "v$Version already installed — will repair/reinstall"
    } else {
        $IsUpgrade = $true
        OK "Upgrading from v$ExistingVer → v$Version (user data preserved)"
    }
} elseif (Test-Path $VenvDir) {
    $IsReinstall = $true
    Warn "Existing environment found (unknown version) — will rebuild"
} else {
    OK "Fresh installation"
}

# ── Preserve user data before any rebuild ─────────────────────────────────────
$DbFile    = Join-Path $ProjectDir "data\cases.db"
$DbBackup  = ""
$EnvFile   = Join-Path $ProjectDir ".env"
$EnvBackup = ""

if (($IsUpgrade -or $IsReinstall) -and (Test-Path $DbFile)) {
    $DbBackup = "$env:TEMP\legalperigee_cases_$(Get-Date -Format 'yyyyMMdd_HHmmss').db"
    Copy-Item $DbFile $DbBackup
    Log "Database backed up to $DbBackup"
}
if (($IsUpgrade -or $IsReinstall) -and (Test-Path $EnvFile)) {
    $EnvBackup = "$env:TEMP\legalperigee_env_backup.txt"
    Copy-Item $EnvFile $EnvBackup
    Log ".env backed up"
}

# ── 1. Python ─────────────────────────────────────────────────────────────────
Header "1/7  Checking Python..."

$PythonCmd = $null
$PythonVer = ""
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)\.(\d+)") {
            $minor = [int]$Matches[1]
            $patch = [int]$Matches[2]
            if ($minor -lt 9) {
                Warn "Found Python 3.$minor.$patch — too old (need 3.9+)"
                continue
            }
            $PythonCmd = $cmd
            $PythonVer = "3.$minor.$patch"
            OK "Python $PythonVer found"
            break
        }
    } catch { }
}

if (-not $PythonCmd) {
    Warn "Python 3.9+ not found — installing Python 3.11..."
    try {
        winget install -e --id Python.Python.3.11 `
            --accept-package-agreements --accept-source-agreements `
            --silent 2>&1 | Out-Null
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path","User")
        $PythonCmd = "python"
        OK "Python 3.11 installed"
    } catch {
        Fail "Could not auto-install Python."
        Write-Host "     Install Python 3.11 from https://www.python.org/downloads/" -ForegroundColor Yellow
        Write-Host "     ⚠️  Check 'Add Python to PATH' during install, then re-run this script." -ForegroundColor Yellow
        Read-Host "     Press Enter after installing Python, then we'll continue..."
        # Retry
        try {
            $ver = & python --version 2>&1
            if ($ver -match "Python 3\.(\d+)") { $PythonCmd = "python" }
        } catch { }
        if (-not $PythonCmd) {
            Write-Host "  ❌  Python still not found. Cannot continue." -ForegroundColor Red
            exit 1
        }
    }
}

# ── 2. Edge WebView2 (required for native window) ─────────────────────────────
Header "2/7  Checking Microsoft Edge WebView2..."

$wv2Paths = @(
    "${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application",
    "${env:ProgramFiles}\Microsoft\EdgeWebView\Application",
    "${env:LocalAppData}\Microsoft\EdgeWebView\Application"
)
$wv2Found = $wv2Paths | Where-Object { Test-Path $_ }

if ($wv2Found) {
    OK "Edge WebView2 runtime present"
} else {
    Warn "Edge WebView2 not found — downloading (~2 MB)..."
    try {
        $installer = "$env:TEMP\MicrosoftEdgeWebview2Setup.exe"
        Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" `
                          -OutFile $installer -UseBasicParsing
        Start-Process $installer -ArgumentList "/silent /install" -Wait
        OK "Edge WebView2 installed"
    } catch {
        Warn "Could not auto-install WebView2. The app window may not open."
        Write-Host "     Download manually: https://developer.microsoft.com/microsoft-edge/webview2/" -ForegroundColor Gray
    }
}

# ── 3. Port conflict check ────────────────────────────────────────────────────
Header "3/7  Checking port 8501..."

$portInUse = netstat -ano 2>$null | Select-String ":8501\s"
if ($portInUse) {
    Warn "Port 8501 already in use — killing stale process..."
    $portInUse | ForEach-Object {
        $pid = ($_ -split '\s+')[-1]
        if ($pid -match '^\d+$' -and $pid -ne '0') {
            Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue
            Log "Killed PID $pid"
        }
    }
    Start-Sleep -Seconds 1
    OK "Port 8501 freed"
} else {
    OK "Port 8501 available"
}

# ── 4. ffmpeg (optional — for video forensics) ───────────────────────────────
Header "4/7  Checking ffmpeg..."

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    OK "ffmpeg present — video analysis enabled"
} else {
    Warn "ffmpeg not found — video analysis will be limited"
    Write-Host "     To enable: winget install -e --id Gyan.FFmpeg" -ForegroundColor Gray
}

# ── 5. Virtual environment ────────────────────────────────────────────────────
Header "5/7  Setting up Python environment..."

$RebuildVenv = $false

if (-not (Test-Path $VenvPy)) {
    Log "No valid .venv — building fresh"
    $RebuildVenv = $true
} else {
    # Test core imports
    $testResult = & $VenvPy -c "import streamlit, anthropic, pydantic" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Warn "Core packages missing or broken — rebuilding environment"
        $RebuildVenv = $true
    } elseif ($IsUpgrade) {
        Log "Upgrade: will update packages"
        $RebuildVenv = $false   # Just pip install, don't wipe
    }
}

if ($RebuildVenv) {
    if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
    & $PythonCmd -m venv $VenvDir 2>&1 | Out-Null
    if (-not (Test-Path $VenvPy)) {
        Fail "Virtual environment creation failed."
        exit 1
    }
}

# Install / upgrade dependencies
Write-Host "     Installing packages (~2-4 min on first run)..." -ForegroundColor Gray
& $VenvPy -m pip install --upgrade pip --quiet 2>&1 | Out-Null
$pipResult = & $VenvPy -m pip install -r $ReqFile 2>&1
if ($LASTEXITCODE -ne 0) {
    Fail "Package installation failed. Details:"
    $pipResult | Select-Object -Last 10 | ForEach-Object { Write-Host "     $_" -ForegroundColor Red }
    Write-Host "     Full log: $LogFile" -ForegroundColor Gray
    exit 1
}

# Windows-specific: pywebview with WebView2 backend
& $VenvPy -m pip install "pywebview[mshtml]" --quiet 2>&1 | Out-Null
OK "Python environment ready"

# ── 6. Database integrity ─────────────────────────────────────────────────────
Header "6/7  Checking database..."

if (Test-Path $DbFile) {
    $dbCheck = & $VenvPy -c @"
import sqlite3, sys
try:
    c = sqlite3.connect(r'$($DbFile.Replace("'","''"))')
    result = c.execute('PRAGMA integrity_check').fetchone()[0]
    c.close()
    print('ok' if result == 'ok' else 'corrupt:' + result)
except Exception as e:
    print('error:' + str(e))
"@ 2>&1

    if ($dbCheck -eq "ok") {
        $count = & $VenvPy -c @"
import sqlite3
c = sqlite3.connect(r'$($DbFile.Replace("'","''"))')
print(c.execute('SELECT COUNT(*) FROM cases').fetchone()[0])
c.close()
"@ 2>&1
        OK "Database OK — $count cases indexed"
    } else {
        Warn "Database issue ($dbCheck) — resetting. Your cases will re-sync on next use."
        Rename-Item $DbFile "$DbFile.corrupt.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    }
} else {
    Log "No database yet — will be created on first run"
    OK "Database will be created on first launch"
}

# Restore backed-up data
if ($DbBackup -and (Test-Path $DbBackup) -and -not (Test-Path $DbFile)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $DbFile) | Out-Null
    Copy-Item $DbBackup $DbFile
    OK "Previous case library restored"
}
if ($EnvBackup -and (Test-Path $EnvBackup) -and -not (Test-Path $EnvFile)) {
    Copy-Item $EnvBackup $EnvFile
    OK ".env settings restored"
}

# ── 7. Shortcuts ──────────────────────────────────────────────────────────────
Header "7/7  Creating shortcuts..."

$LauncherPath = Join-Path $ProjectDir "installers\windows\LegalPerigee.bat"
$IcoPath      = Join-Path $PSScriptRoot "LegalPerigee.ico"

# Write launcher
@"
@echo off
title LegalPerigee v$Version
cd /d "$ProjectDir"
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
)
"$VenvPy" window.py
"@ | Set-Content -Path $LauncherPath -Encoding UTF8

$WShell = New-Object -ComObject WScript.Shell

# Desktop shortcut
$DesktopPath  = [Environment]::GetFolderPath("Desktop")
$sc = $WShell.CreateShortcut("$DesktopPath\LegalPerigee.lnk")
$sc.TargetPath = $LauncherPath; $sc.WorkingDirectory = $ProjectDir
$sc.Description = "LegalPerigee v$Version"
if (Test-Path $IcoPath) { $sc.IconLocation = $IcoPath }
$sc.WindowStyle = 7; $sc.Save()
OK "Desktop shortcut created"

# Start Menu
$StartDir = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\LegalPerigee"
New-Item -ItemType Directory -Force -Path $StartDir | Out-Null
$sm = $WShell.CreateShortcut("$StartDir\LegalPerigee.lnk")
$sm.TargetPath = $LauncherPath; $sm.WorkingDirectory = $ProjectDir
$sm.Description = "LegalPerigee v$Version"
if (Test-Path $IcoPath) { $sm.IconLocation = $IcoPath }
$sm.Save()
OK "Start Menu shortcut created"

# Write version file so future installs know what's here
"$Version" | Set-Content -Path $VerFile -Encoding UTF8

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
if ($IsUpgrade)   { Write-Host "  🎉  Upgraded to LegalPerigee v$Version!" -ForegroundColor Green }
elseif ($IsReinstall) { Write-Host "  🔧  LegalPerigee v$Version repaired!" -ForegroundColor Green }
else              { Write-Host "  🎉  LegalPerigee v$Version installed!" -ForegroundColor Green }
Write-Host ""
Write-Host "  ➤  Double-click LegalPerigee on your Desktop" -ForegroundColor Cyan
Write-Host "  ➤  First launch: add your Anthropic API key in the sidebar" -ForegroundColor Gray
Write-Host "  ➤  Setup log saved to: $LogFile" -ForegroundColor DarkGray
Write-Host ""

$launch = Read-Host "  Launch LegalPerigee now? [Y/n]"
if ($launch -ne "n" -and $launch -ne "N") { Start-Process $LauncherPath }
