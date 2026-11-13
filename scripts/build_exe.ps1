# Build single-file HostsKeeper.exe (PyInstaller onefile).
# Usage (from repo root):
#   .\scripts\build_exe.ps1
#   .\scripts\build_exe.ps1 -Console   # show console for debug

param(
    [switch]$Console
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Error "Missing .venv. Create it and: pip install -e `".[desktop]`""
}

Write-Host "Installing build deps..."
& $Py -m pip install -e ".[desktop]" "pyinstaller>=6.3" -q

$Spec = Join-Path $Root "packaging\HostsKeeper.spec"
if ($Console) {
    Write-Host "Note: -Console rebuilds with console=True (edit spec temporarily if needed)."
}

Write-Host "Running PyInstaller (onefile, windowed)..."
& $Py -m PyInstaller --noconfirm --clean --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build\pyinstaller") $Spec
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$Exe = Join-Path $Root "dist\HostsKeeper.exe"
if (-not (Test-Path $Exe)) {
    Write-Error "Build finished but exe not found: $Exe"
}

$sizeMb = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
Write-Host "OK: $Exe ($sizeMb MB)"
Write-Host "Smoke: start HostsKeeper.exe, unlock vault, Open Tab, MCP."
