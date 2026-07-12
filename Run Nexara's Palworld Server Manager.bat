@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Nexara's Palworld Server Manager

set "ROOT=%~dp0"
set "PY_VERSION=3.12.6"
set "PY_SHORT=312"
set "PY_INSTALLER_URL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-amd64.exe"
set "PY_INSTALLER=%TEMP%\pwsm_python_installer_%PY_SHORT%.exe"
set "INSTALL_LOG=%TEMP%\pwsm_python_install_%PY_SHORT%.log"

REM Standard per-user install location that python.org's installer uses --
REM far more reliable than a custom TargetDir, and still doesn't touch
REM any system-wide/other Python you may already have.
set "RUNTIME=%LocalAppData%\Programs\Python\Python%PY_SHORT%"
set "PYEXE=%RUNTIME%\python.exe"
set "PYW=%RUNTIME%\pythonw.exe"
set "MARKER=%ROOT%.setup_complete"
set "INSTALLER_ARGS=/quiet /log "%INSTALL_LOG%" InstallAllUsers=0 PrependPath=0 Shortcuts=0 AssociateFiles=0 Include_launcher=0 Include_test=0 Include_pip=1 Include_tcltk=1"

REM Already fully set up -> launch immediately, no console flashing about.
if exist "%MARKER%" (
    if exist "%PYW%" (
        start "" "%PYW%" "%ROOT%main.py"
        exit /b 0
    )
    REM Marker exists but runtime vanished somehow -- fall through and redo setup.
    del "%MARKER%" >nul 2>&1
)

echo ============================================================
echo  Nexara's Palworld Server Manager - first-time setup
echo.
echo  This app needs a small private Python runtime to run. This
echo  window will download and set it up automatically - it will
echo  NOT touch any other Python already on your PC, and you don't
echo  need to type or install anything yourself. This only happens
echo  once and may take a few minutes depending on your connection.
echo ============================================================
echo.

if exist "%PYEXE%" goto :install_deps

echo [1/3] Downloading Python runtime...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Invoke-WebRequest -Uri '%PY_INSTALLER_URL%' -OutFile '%PY_INSTALLER%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"

if not exist "%PY_INSTALLER%" (
    echo.
    echo ERROR: Could not download the Python runtime.
    echo Please check your internet connection and try again.
    pause
    exit /b 1
)

echo [2/3] Installing runtime ^(per-user, standard location^)...
"%PY_INSTALLER%" %INSTALLER_ARGS%
set "INSTALL_EXIT=%errorlevel%"
echo        installer exit code: %INSTALL_EXIT%

if not exist "%PYEXE%" (
    echo        Python wasn't found where expected after that attempt.
    echo        This can happen if Windows had a stale/broken record of a
    echo        previous install. Attempting a clean repair...
    "%PY_INSTALLER%" /quiet /uninstall
    timeout /t 3 >nul
    "%PY_INSTALLER%" %INSTALLER_ARGS%
    set "INSTALL_EXIT=%errorlevel%"
    echo        repair attempt exit code: %INSTALL_EXIT%
)

if not exist "%PYEXE%" (
    echo.
    echo ERROR: Python runtime installation failed ^(exit code %INSTALL_EXIT%^).
    echo.
    echo A detailed installer log was saved to:
    echo   %INSTALL_LOG%
    echo Open that file in Notepad and check near the end for the actual
    echo error ^(search for "Error" or a non-zero result code^). Common
    echo causes are antivirus quarantining the installer, or restricted
    echo permissions on:
    echo   %RUNTIME%
    pause
    exit /b 1
)
del "%PY_INSTALLER%" >nul 2>&1

:install_deps
echo [3/3] Installing required components...
"%PYEXE%" -m pip install --quiet --disable-pip-version-check -r "%ROOT%requirements.txt"

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install required components.
    pause
    exit /b 1
)

echo done> "%MARKER%"
echo.
echo Setup complete! Launching Nexara's Palworld Server Manager...
timeout /t 2 >nul

start "" "%PYW%" "%ROOT%main.py"
exit /b 0
