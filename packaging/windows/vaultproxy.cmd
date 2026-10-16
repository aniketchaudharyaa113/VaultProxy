@echo off
REM VaultProxy Windows CMD Launcher
REM Forwards execution to Python or installed vaultproxy binary

where vaultproxy >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    vaultproxy %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -m vaultproxy %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python -m vaultproxy %*
    exit /b %ERRORLEVEL%
)

echo [FAIL] Python or vaultproxy command not found in PATH.
echo Please run packaging\windows\install.ps1 or install Python 3.10+ from python.org.
exit /b 1
