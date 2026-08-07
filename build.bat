@echo off
title Nameweaver — Build
echo ============================================
echo   Nameweaver  Build + Installer
echo ============================================
echo.

:: ── Verify Python ────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found in PATH.
    echo  Install Python 3.10+ from https://python.org
    pause & exit /b 1
)

:: ── Install dependencies ─────────────────────────────────────────────────────
echo  [1/4] Installing dependencies...
pip install -r requirements-dev.txt --quiet --upgrade
if errorlevel 1 ( echo  ERROR: pip failed. & pause & exit /b 1 )

:: ── Generate icon ─────────────────────────────────────────────────────────────
echo  [2/4] Generating icon...
python tools\make_icon.py
if errorlevel 1 ( echo  WARNING: Icon generation failed, building without icon. )

:: ── Inject version into file_version_info.txt ────────────────────────────────
for /f %%v in ('python -c "from version import __version__; print(__version__)"') do set APP_VER=%%v
powershell -Command " ^
  $v = '%APP_VER%'; ^
  $vt = $v -replace '\.', ', '; ^
  (Get-Content file_version_info.txt) ^
    -replace 'filevers=\(.*?\)', \"filevers=($vt, 0)\" ^
    -replace 'prodvers=\(.*?\)', \"prodvers=($vt, 0)\" ^
    -replace \"'FileVersion',\s*'.*?'\", \"'FileVersion', '$v.0'\" ^
    -replace \"'ProductVersion',\s*'.*?'\", \"'ProductVersion', '$v.0'\" ^
  | Set-Content file_version_info.txt"

:: ── Build exe (onedir via Nameweaver.spec) ─────────────────────────────────────
echo  [3/4] Building Nameweaver.exe...
python -m PyInstaller Nameweaver.spec --noconfirm
if errorlevel 1 ( echo  ERROR: PyInstaller build failed. & pause & exit /b 1 )

:: ── Create installer with Inno Setup ─────────────────────────────────────────
echo  [4/4] Creating installer...

:: Try PATH first, then common install locations
set ISCC=
where iscc >nul 2>&1 && set ISCC=iscc
if not defined ISCC (
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
    if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)

if defined ISCC (
    for /f %%v in ('python -c "from version import __version__; print(__version__)"') do set APP_VER=%%v
    %ISCC% /DAppVersion=%APP_VER% nameweaver.iss
    if errorlevel 1 ( echo  ERROR: Inno Setup failed. & pause & exit /b 1 )
    echo.
    echo  ============================================
    echo   Done!  installer\Nameweaver_Setup.exe
    echo  ============================================
    echo.
) else (
    echo.
    echo  Inno Setup not found — skipping installer.
    echo  Portable exe: dist\Nameweaver.exe
    echo.
    echo  To create a proper installer:
    echo    1. Download Inno Setup from https://jrsoftware.org/isinfo.php
    echo    2. Run this build.bat again
)
pause
