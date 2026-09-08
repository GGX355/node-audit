# Build dist\node-audit.exe (one file, console).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$py = $null
foreach ($c in @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "python"
)) {
    if ($c -eq "python") { $py = "python"; break }
    if (Test-Path $c) { $py = $c; break }
}
if (-not $py) { throw "python not found" }

& $py -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }

$launch = Join-Path $root "scripts\launch.py"
$src = Join-Path $root "src"
& $py -m PyInstaller --noconfirm --clean --onefile --console --name node-audit --paths $src --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build") --specpath (Join-Path $root "build") $launch
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$exe = Join-Path $root "dist\node-audit.exe"
if (-not (Test-Path $exe)) { throw "missing $exe" }
Write-Host "OK $exe"
Write-Host "Double-click the exe. It will create node-audit.ini next to itself."
