# Linux Distribution Packaging Guide (Arch, Debian, Fedora)

VaultProxy provides first-class native Linux packaging for the primary distribution families:
- **Arch Linux** (`pacman` / AUR)
- **Debian / Ubuntu** (`apt` / `.deb`)
- **Fedora / RHEL / CentOS** (`dnf` / `.rpm`)

All packages include a hardened, isolated systemd service running under an unprivileged `vaultproxy` system user.

---

## 1. Arch Linux (`pacman` / AUR)

The Arch Linux package is defined in [`packaging/arch/PKGBUILD`](file:///home/aniket/october/packaging/arch/PKGBUILD).

### Installing via AUR Helper (`yay` or `paru`)
```bash
yay -S vaultproxy
# or
paru -S vaultproxy
```

### Manual Build with `makepkg`
```bash
git clone https://github.com/aniketchaudharyaa113/vaultproxy.git
cd vaultproxy/packaging/arch
makepkg -si
```

### Direct `pacman` Install
If you have a compiled `.pkg.tar.zst`:
```bash
sudo pacman -U vaultproxy-0.2.1-1-any.pkg.tar.zst
```

The Arch installation scriptlet [`packaging/arch/vaultproxy.install`](file:///home/aniket/october/packaging/arch/vaultproxy.install) automatically registers the `vaultproxy` daemon system account, creates `/var/lib/vaultproxy`, and secures the configuration file.

---

## 2. Debian & Ubuntu (`apt` / `.deb`)

Debian package metadata is configured in [`packaging/debian/`](file:///home/aniket/october/packaging/debian/).

### Building the `.deb` Package
VaultProxy includes a zero-dependency package builder ([`packaging/build_deb.py`](file:///home/aniket/october/packaging/build_deb.py)) that produces a compliant Debian binary package on any system:
```bash
python3 packaging/build_deb.py
```
This generates `dist/vaultproxy_0.2.1_all.deb`.

### Installing with `apt` or `dpkg`
```bash
# Install via apt (automatically resolves system dependencies)
sudo apt update
sudo apt install -y ./dist/vaultproxy_0.2.1_all.deb

# Or install via dpkg
sudo dpkg -i dist/vaultproxy_0.2.1_all.deb
sudo apt-get install -f  # resolve any missing runtime libraries
```

### Package Contents
- Binary: `/usr/bin/vaultproxy`
- Python Library: `/usr/lib/python3/dist-packages/vaultproxy/`
- Systemd Unit: `/lib/systemd/system/vaultproxy.service`
- Configuration: `/etc/vaultproxy/config.env` (managed as a protected `conffile`)
- State Directory: `/var/lib/vaultproxy` (`drwxr-x--- vaultproxy:vaultproxy`)

---

## 3. Fedora, RHEL & CentOS (`dnf` / `.rpm`)

The RPM specification is provided in [`packaging/fedora/vaultproxy.spec`](file:///home/aniket/october/packaging/fedora/vaultproxy.spec).

### Building the RPM
Run the helper script [`packaging/build_rpm.py`](file:///home/aniket/october/packaging/build_rpm.py):
```bash
python3 packaging/build_rpm.py
```
On a Fedora/RHEL system with `rpm-build` installed, this compiles the `.rpm` directly into `dist/rpmbuild/RPMS/noarch/`.

### Manual RPM Build on Fedora
```bash
sudo dnf install -y rpm-build python3-devel python3-setuptools systemd-rpm-macros
mkdir -p ~/rpmbuild/{SOURCES,SPECS}
python3 packaging/build_rpm.py  # creates dist/vaultproxy-0.2.1.tar.gz
cp dist/vaultproxy-0.2.1.tar.gz ~/rpmbuild/SOURCES/
cp packaging/fedora/vaultproxy.spec ~/rpmbuild/SPECS/
rpmbuild -ba ~/rpmbuild/SPECS/vaultproxy.spec
```

### Installing with `dnf`
```bash
sudo dnf install -y ~/rpmbuild/RPMS/noarch/vaultproxy-0.2.1-1*.rpm
```

---

## 4. Systemd Service & Management

All three package formats install the hardened systemd unit [`packaging/systemd/vaultproxy.service`](file:///home/aniket/october/packaging/systemd/vaultproxy.service).

### Security Sandbox
The service runs with extensive Linux kernel privilege restrictions:
- `User=vaultproxy` & `Group=vaultproxy` (isolated system daemon account)
- `ProtectSystem=full` (read-only `/usr`, `/boot`, `/etc`)
- `ProtectHome=true` (inaccessible `/root`, `/home`)
- `NoNewPrivileges=true` (prevents privilege escalation)
- `PrivateTmp=true` (dedicated `/tmp` namespace)

### Configuration
Edit `/etc/vaultproxy/config.env` to configure your upstream provider and secrets:
```bash
sudo nano /etc/vaultproxy/config.env
```
Example configuration:
```env
VAULT_PROFILE=production
VAULT_AUTH_TOKEN=your_strong_secret_token_here
UPSTREAM_BASE_URL=https://api.openai.com/v1
UPSTREAM_API_KEY=your_openai_or_anthropic_api_key
GEMMA_BACKEND=off
STRICT_MODE=false
```

### Managing the Service
```bash
# Reload systemd configuration
sudo systemctl daemon-reload

# Start and enable VaultProxy on system boot
sudo systemctl enable --now vaultproxy

# View live service logs
sudo journalctl -u vaultproxy -f

# Check status and health
sudo systemctl status vaultproxy
curl http://127.0.0.1:8000/healthz
```
