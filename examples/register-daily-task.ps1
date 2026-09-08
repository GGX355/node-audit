# Register a daily 04:00 isolated audit. ASCII only (Windows PowerShell 5.1).
# Usage: powershell -ExecutionPolicy Bypass -File examples\register-daily-task.ps1
$ErrorActionPreference = "Stop"
$examples = $PSScriptRoot
$root = Split-Path $examples -Parent
$bat = Join-Path $examples "audit-daily.bat"
if (-not (Test-Path $bat)) { throw "missing audit-daily.bat" }

$tr = '"' + $bat + '"'
schtasks /Create /TN "node-audit-daily" /SC DAILY /ST 04:00 /RL LIMITED /F /TR $tr
if ($LASTEXITCODE -ne 0) { throw "schtasks failed: $LASTEXITCODE" }

Write-Host "Registered task node-audit-daily (daily 04:00)."
Write-Host "Repo: $root"
Write-Host "Report: $root\node-audit-report\latest.html"
Write-Host "Run now: schtasks /Run /TN node-audit-daily"
Write-Host "Remove:  schtasks /Delete /TN node-audit-daily /F"
