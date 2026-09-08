@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8
if exist "node-audit.exe" (
  "node-audit.exe" run --yes --no-open
  exit /b %ERRORLEVEL%
)
if exist "dist\node-audit.exe" (
  "dist\node-audit.exe" run --yes --no-open
  exit /b %ERRORLEVEL%
)
set PYTHONPATH=src
where python >nul 2>&1
if errorlevel 1 (
  echo python not found in PATH, and no node-audit.exe
  exit /b 1
)
python -m node_audit run --yes --no-open
exit /b %ERRORLEVEL%
