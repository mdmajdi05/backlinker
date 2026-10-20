<#
.SYNOPSIS
    Build the backend sidecar that is bundled with the desktop application.

.DESCRIPTION
    The result is written to:
        src-tauri\binaries\autobacklinker-api-<target-triple>.exe

    Tauri looks the binary up by that exact name, so this script has to be
    executed on every platform that is going to be shipped.

.PARAMETER ApiDir
    Directory that contains the "app" package (default: ..\..\api).

.PARAMETER NoPlaywright
    Skip the Playwright browser step.

.PARAMETER PlaywrightPath
    Folder with the Playwright browsers that is copied next to the sidecar.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-sidecar.ps1
#>
[CmdletBinding()]
param(
    [string]$ApiDir = "",
    [switch]$NoPlaywright,
    [string]$PlaywrightPath = $env:PLAYWRIGHT_BROWSERS_PATH
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$RepoDir = Split-Path -Parent (Split-Path -Parent $DesktopDir)

if (-not $ApiDir) {
    $ApiDir = Join-Path $RepoDir "apps\api"
}

$BinariesDir = Join-Path $DesktopDir "src-tauri\binaries"
$VenvDir = Join-Path $DesktopDir ".sidecar-venv"
$BuildDir = Join-Path $DesktopDir ".sidecar-build"

if (-not (Test-Path (Join-Path $ApiDir "app"))) {
    throw "The API sources were not found in $ApiDir"
}

function Get-TargetTriple {
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($arch -eq "ARM64") { $archPart = "aarch64" } else { $archPart = "x86_64" }
    return "$archPart-pc-windows-msvc"
}

$Triple = Get-TargetTriple
$Target = Join-Path $BinariesDir "autobacklinker-api-$Triple.exe"

Write-Host "==> Building the backend sidecar for $Triple"

$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "==> Creating the build virtual environment ($VenvDir)"
    python -m venv $VenvDir
}

Write-Host "==> Installing the backend dependencies"
& $VenvPy -m pip install --upgrade pip wheel | Out-Null
$Requirements = Join-Path $ApiDir "requirements.txt"
if (Test-Path $Requirements) {
    & $VenvPy -m pip install -r $Requirements
} else {
    & $VenvPy -m pip install fastapi "uvicorn[standard]" sqlalchemy pydantic pydantic-settings httpx pyjwt python-multipart openpyxl beautifulsoup4 lxml
}
& $VenvPy -m pip install pyinstaller

New-Item -ItemType Directory -Force -Path $BinariesDir | Out-Null
if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

$SpecPath = Join-Path $BuildDir "sidecar.spec"
@"
# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_submodules

api_dir = os.environ.get("AUTOBL_API_DIR", r"$ApiDir")

# Every module of the backend package is collected explicitly: the API uses
# lazy imports inside functions, which the static analysis alone misses.
hiddenimports = collect_submodules("app") + [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite",
    "playwright.sync_api",
]

a = Analysis(
    [r"$ScriptDir\sidecar_launcher.py"],
    pathex=[api_dir],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="autobacklinker-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
"@ | Set-Content -Path $SpecPath -Encoding UTF8

Write-Host "==> Running PyInstaller"
$env:AUTOBL_API_DIR = $ApiDir
& $VenvPy -m PyInstaller --noconfirm --clean --distpath (Join-Path $BuildDir "dist") --workpath (Join-Path $BuildDir "work") --specpath $BuildDir $SpecPath | Out-Null

$Built = Join-Path $BuildDir "dist\autobacklinker-api.exe"
if (-not (Test-Path $Built)) {
    throw "PyInstaller did not produce $Built"
}

Copy-Item $Built $Target -Force
Write-Host "==> Wrote $Target"

if (-not $NoPlaywright) {
    if ($PlaywrightPath) {
        Write-Host "==> Copying the Playwright browsers from $PlaywrightPath"
        $BrowsersTarget = Join-Path $BinariesDir "playwright-browsers"
        if (Test-Path $BrowsersTarget) { Remove-Item -Recurse -Force $BrowsersTarget }
        New-Item -ItemType Directory -Force -Path $BrowsersTarget | Out-Null
        Copy-Item -Recurse -Force (Join-Path $PlaywrightPath "*") $BrowsersTarget
        Write-Host "    Add 'binaries/playwright-browsers' to bundle.resources in tauri.conf.json"
    } else {
        Write-Host ""
        Write-Host "==> Playwright browsers are NOT bundled."
        Write-Host "    Install them on the target machine with: python -m playwright install chromium"
    }
}

Write-Host ""
Write-Host "Done. The desktop bundle now contains:"
Get-ChildItem $BinariesDir | Format-Table Name, Length, LastWriteTime
