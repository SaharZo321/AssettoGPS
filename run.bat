@echo off
setlocal enabledelayedexpansion
title Assetto Corsa GPS Minimap (uv powered)

:start_server
cls
echo ===================================================
echo   ASSETTO CORSA WAZE/GPS MINIMAP (uv LAUNCHER)
echo ===================================================
echo.

:: 1. Search for uv executable
set "UVCMD="

uv --version >nul 2>&1
if %errorlevel% equ 0 set "UVCMD=uv"

if not defined UVCMD (
    for %%U in (
        "%USERPROFILE%\.local\bin\uv.exe"
        "%USERPROFILE%\.cargo\bin\uv.exe"
        "%LocalAppData%\uv\uv.exe"
    ) do (
        if exist %%U (
            set "UVCMD=%%~U"
            goto :found_uv
        )
    )
)

:found_uv
if not defined UVCMD (
    echo [*] 'uv' was not found. Installing uv in 2 seconds via official script...
    powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "UVCMD=%USERPROFILE%\.local\bin\uv.exe"
    ) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
        set "UVCMD=%USERPROFILE%\.cargo\bin\uv.exe"
    ) else (
        echo [!] Could not auto-locate uv. Trying winget...
        winget install --id astral-sh.uv -e --source winget
        set "UVCMD=uv"
    )
)

echo [*] Using uv: !UVCMD!
echo.

:: 2. Launch browser after 2 seconds
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8080"

:: 3. Run server with uv
echo [*] Starting GPS Minimap Server...
"!UVCMD!" run backend\server.py

echo.
echo ===================================================
echo   Server stopped. Press [R] to restart or [X] to exit.
echo ===================================================
choice /c rx /n /m "Select (R=Restart, X=Exit): "
if %errorlevel% equ 1 goto :start_server
exit /b
