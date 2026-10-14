"""Tests for Linux distribution packaging (Arch, Debian, Fedora trio)."""

from __future__ import annotations

import tarfile
from pathlib import Path

import importlib.util
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_script(file_path: Path):
    spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deb_builder = _import_script(REPO_ROOT / "packaging" / "build_deb.py")
rpm_builder = _import_script(REPO_ROOT / "packaging" / "build_rpm.py")


def test_arch_packaging_files():
    """Verify Arch Linux PKGBUILD, .SRCINFO, and install scriptlet."""
    pkgbuild = REPO_ROOT / "packaging" / "arch" / "PKGBUILD"
    srcinfo = REPO_ROOT / "packaging" / "arch" / ".SRCINFO"
    install_script = REPO_ROOT / "packaging" / "arch" / "vaultproxy.install"

    assert pkgbuild.exists(), "PKGBUILD is missing"
    assert srcinfo.exists(), ".SRCINFO is missing"
    assert install_script.exists(), "vaultproxy.install is missing"

    content = pkgbuild.read_text(encoding="utf-8")
    assert "pkgname=vaultproxy" in content
    assert "pkgver=0.2.1" in content
    assert "vaultproxy.service" in content
    assert "config.env" in content

    srcinfo_content = srcinfo.read_text(encoding="utf-8")
    assert "pkgbase = vaultproxy" in srcinfo_content
    assert "pkgver = 0.2.1" in srcinfo_content


def test_debian_packaging_and_build():
    """Verify Debian control files and test .deb generation."""
    deb_dir = REPO_ROOT / "packaging" / "debian"
    control_file = deb_dir / "control"
    postinst_file = deb_dir / "postinst"
    prerm_file = deb_dir / "prerm"
    conffiles = deb_dir / "conffiles"

    assert control_file.exists(), "Debian control file is missing"
    assert postinst_file.exists(), "Debian postinst script is missing"
    assert prerm_file.exists(), "Debian prerm script is missing"
    assert conffiles.exists(), "Debian conffiles is missing"

    control_text = control_file.read_text(encoding="utf-8")
    assert "Package: vaultproxy" in control_text
    assert "Version: 0.2.1" in control_text
    assert "Architecture: all" in control_text

    # Generate .deb package
    deb_path = deb_builder.build_deb()
    assert deb_path.exists()
    assert deb_path.stat().st_size > 5000

    # Verify ar archive structure
    with deb_path.open("rb") as f:
        magic = f.read(8)
        assert magic == b"!<arch>\n"


def test_fedora_packaging_and_source_tarball():
    """Verify Fedora spec file and source tarball generation."""
    spec_file = REPO_ROOT / "packaging" / "fedora" / "vaultproxy.spec"
    assert spec_file.exists(), "Fedora spec file is missing"

    spec_text = spec_file.read_text(encoding="utf-8")
    assert "Name:           vaultproxy" in spec_text
    assert "Version:        0.2.1" in spec_text
    assert "License:        MIT" in spec_text
    assert "Requires:       python3 >= 3.10" in spec_text

    tar_path = rpm_builder.create_source_tarball()
    assert tar_path.exists()
    assert tar_path.stat().st_size > 10000

    # Verify contents of tarball
    with tarfile.open(tar_path, "r:gz") as tar:
        names = tar.getnames()
        assert "vaultproxy-0.2.1/pyproject.toml" in names
        assert "vaultproxy-0.2.1/vaultproxy/server.py" in names
        assert "vaultproxy-0.2.1/packaging/fedora/vaultproxy.spec" in names


def test_systemd_units():
    """Verify systemd service unit and default environment file."""
    svc = REPO_ROOT / "packaging" / "systemd" / "vaultproxy.service"
    cfg = REPO_ROOT / "packaging" / "systemd" / "config.env"

    assert svc.exists()
    assert cfg.exists()

    svc_text = svc.read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/vaultproxy run" in svc_text
    assert "User=vaultproxy" in svc_text
    assert "ProtectSystem=full" in svc_text

    cfg_text = cfg.read_text(encoding="utf-8")
    assert "VAULT_PROFILE=" in cfg_text
    assert "UPSTREAM_BASE_URL=" in cfg_text
