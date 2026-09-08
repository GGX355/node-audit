@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONPATH=src
set PYTHONIOENCODING=utf-8
where python >nul 2>&1
if errorlevel 1 (
  echo python not found in PATH
  exit /b 1
)
python -m node_audit audit --mode isolated --yes --out node-audit-report
exit /b %ERRORLEVEL%
