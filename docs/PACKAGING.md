# VaultProxy Universal Packaging & Distribution Guide

VaultProxy provides first-class, cross-platform packaging and distribution options for developers and DevOps engineers on **Linux**, **macOS**, and **Windows**, as well as zero-dependency tools for Python and Node.js environments.

---

## 1. Quick Install for Developers (Cross-Platform)

### Python Ecosystem (`pipx` / `uv` / `pip`)

The easiest way to run VaultProxy on any platform is via standalone CLI package tools:

```bash
# 1. Using pipx (isolated application environment)
pipx install vaultproxy
# or run directly without installing:
pipx run vaultproxy run

# 2. Using uv / uvx (extremely fast)
uv tool install vaultproxy
# or run directly:
uvx vaultproxy run

# 3. Standard pip
pip install vaultproxy
```

### Node.js Ecosystem (`npx` / `npm`)

Developers in JavaScript, TypeScript, React, and Node.js ecosystems can run VaultProxy without manually configuring Python:

```bash
# Direct zero-install execution via npx:
npx vaultproxy run
npx vaultproxy check --file .env
npx vaultproxy scan --fail-on-secrets

# Or install globally:
npm install -g vaultproxy
```

---

## 2. macOS Packaging (Homebrew & Launchd)

### Homebrew Formula
VaultProxy provides a native Homebrew formula in [`packaging/homebrew/vaultproxy.rb`](file:///home/aniket/october/packaging/homebrew/vaultproxy.rb) supporting both Apple Silicon (M1/M2/M3/M4) and Intel architectures.

```bash
# Install via tap
brew install aniketchaudharyaa113/tap/vaultproxy

# Manage background service with brew services
brew services start vaultproxy
brew services stop vaultproxy
```

### Launchd Daemon
For production background execution on macOS without Homebrew, use the launchd plist configuration at [`packaging/launchd/com.vaultproxy.daemon.plist`](file:///home/aniket/october/packaging/launchd/com.vaultproxy.daemon.plist):

```bash
cp packaging/launchd/com.vaultproxy.daemon.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.vaultproxy.daemon.plist
```

---

## 3. Windows Packaging (PowerShell, Batch & WinSW Service)

### PowerShell Automated Installer
VaultProxy includes a Windows installer script in [`packaging/windows/install.ps1`](file:///home/aniket/october/packaging/windows/install.ps1):

```powershell
# Run in PowerShell
.\packaging\windows\install.ps1
```

### Windows Command Runner
For Command Prompt (`cmd.exe`) users, [`packaging/windows/vaultproxy.cmd`](file:///home/aniket/october/packaging/windows/vaultproxy.cmd) automatically delegates to Python or the installed binary.

### Native Windows Service (Enterprise & DevOps)
To run VaultProxy as an unprivileged, automatic background service on Windows Server or workstations, use the WinSW definition in [`packaging/windows/winsw.xml`](file:///home/aniket/october/packaging/windows/winsw.xml):

```powershell
# Using WinSW (Windows Service Wrapper)
winsw.exe install packaging\windows\winsw.xml
winsw.exe start vaultproxy
```

---

## 4. Linux Distribution Packaging (Arch, Debian, Fedora)

VaultProxy provides first-class native Linux packaging for primary distribution families:
- **Arch Linux** (`pacman` / AUR): [`packaging/arch/PKGBUILD`](file:///home/aniket/october/packaging/arch/PKGBUILD)
- **Debian / Ubuntu** (`apt` / `.deb`): [`packaging/debian/`](file:///home/aniket/october/packaging/debian/)
- **Fedora / RHEL / CentOS** (`dnf` / `.rpm`): [`packaging/fedora/vaultproxy.spec`](file:///home/aniket/october/packaging/fedora/vaultproxy.spec)

### Debian & Ubuntu (.deb)
```bash
python3 packaging/build_deb.py
sudo apt install -y ./dist/vaultproxy_0.2.1_all.deb
```

### Fedora, RHEL & CentOS (.rpm)
```bash
python3 packaging/build_rpm.py
sudo dnf install -y dist/rpmbuild/RPMS/noarch/vaultproxy-0.2.1-1*.rpm
```

### Arch Linux (AUR / PKGBUILD)
```bash
cd packaging/arch && makepkg -si
```

### Linux Systemd Service Sandbox
All Linux packages install the systemd unit [`packaging/systemd/vaultproxy.service`](file:///home/aniket/october/packaging/systemd/vaultproxy.service) with full privilege isolation (`User=vaultproxy`, `ProtectSystem=full`, `ProtectHome=true`, `NoNewPrivileges=true`).

```bash
sudo systemctl enable --now vaultproxy
sudo systemctl status vaultproxy
```

---

## 5. DevOps & CI/CD Secret Scanning

To prevent team members from accidentally committing or sending `.env` files and credentials to external LLMs, use pre-commit hooks or CI/CD pipelines.

### Git Pre-Commit Hook Integration

Add VaultProxy to your repository's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/aniketchaudharyaa113/vaultproxy
    rev: v0.2.1
    hooks:
      - id: vaultproxy-scan
```

### CI/CD Pipeline Scanning
In GitHub Actions, GitLab CI, or Jenkins:

```bash
# Scan working directory for leaked .env files and cloud secrets; exits with code 1 if found
vaultproxy scan . --fail-on-secrets

# Dry-run check on specific configuration files with JSON output
vaultproxy check --file .env --fail-on-secrets --json
```
