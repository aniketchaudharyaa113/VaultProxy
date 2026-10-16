# VaultProxy Windows PowerShell Installer
# Installs VaultProxy and configures environment on Windows

$ErrorActionPreference = "Stop"

Write-Host "=== Installing VaultProxy for Windows ===" -ForegroundColor Cyan

# 1. Check for Python or uv
$hasPython = Get-Command python -ErrorAction SilentlyContinue
$hasUv = Get-Command uv -ErrorAction SilentlyContinue
$hasPipx = Get-Command pipx -ErrorAction SilentlyContinue

if ($hasUv) {
    Write-Host "[INFO] Detected uv. Installing VaultProxy via uv tool..." -ForegroundColor Green
    uv tool install vaultproxy
} elseif ($hasPipx) {
    Write-Host "[INFO] Detected pipx. Installing VaultProxy via pipx..." -ForegroundColor Green
    pipx install vaultproxy
} elseif ($hasPython) {
    Write-Host "[INFO] Detected Python. Installing VaultProxy via pip..." -ForegroundColor Green
    python -m pip install --upgrade pip
    python -m pip install vaultproxy
} else {
    Write-Host "[FAIL] Python 3.10+ or uv is required to install VaultProxy on Windows." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/ or uv from https://astral.sh/uv"
    exit 1
}

# 2. Verify installation
$vpCmd = Get-Command vaultproxy -ErrorAction SilentlyContinue
if ($vpCmd) {
    Write-Host "[PASS] VaultProxy successfully installed at: $($vpCmd.Source)" -ForegroundColor Green
    & vaultproxy version
    Write-Host "\nRun 'vaultproxy doctor' to verify system health or 'vaultproxy run' to start the proxy." -ForegroundColor Cyan
} else {
    Write-Host "[WARN] VaultProxy installed, but not yet in PATH. Please restart your PowerShell session." -ForegroundColor Yellow
}
