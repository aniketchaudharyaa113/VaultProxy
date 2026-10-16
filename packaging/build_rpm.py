#!/usr/bin/env python3
"""Build an RPM package or prepare RPM build sources for Fedora / RHEL / CentOS.

Prepares dist/vaultproxy-0.2.1.tar.gz and builds RPM with rpmbuild if available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

VERSION = "0.2.1"
PKG_NAME = "vaultproxy"
REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"
SOURCE_TAR = DIST_DIR / f"{PKG_NAME}-{VERSION}.tar.gz"
SPEC_FILE = REPO_ROOT / "packaging" / "fedora" / "vaultproxy.spec"


def create_source_tarball() -> Path:
    """Create a pristine source tarball suitable for rpmbuild."""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{PKG_NAME}-{VERSION}"

    print(f"Creating source tarball {SOURCE_TAR.name}...")
    with tarfile.open(SOURCE_TAR, "w:gz") as tar:
        # Add repository files under the prefix
        for item in ["vaultproxy", "packaging", "pyproject.toml", "LICENSE", "README.md"]:
            src_path = REPO_ROOT / item
            if not src_path.exists():
                continue
            if src_path.is_file():
                tar.add(src_path, arcname=f"{prefix}/{item}")
            else:
                for root, dnames, files in os.walk(src_path):
                    dnames[:] = [d for d in dnames if d != "__pycache__"]
                    rel_dir = Path(root).relative_to(REPO_ROOT)
                    for f in files:
                        if f.endswith((".pyc", ".pyo")):
                            continue
                        f_path = Path(root) / f
                        arcname = f"{prefix}/{rel_dir}/{f}"
                        tar.add(f_path, arcname=arcname)

    size = SOURCE_TAR.stat().st_size
    print(f"Source tarball created: {SOURCE_TAR} ({size:,} bytes)")
    return SOURCE_TAR


def build_rpm() -> None:
    source_tar = create_source_tarball()

    if not shutil.which("rpmbuild"):
        print("\nNote: 'rpmbuild' is not installed on this system.")
        print("To build the RPM on Fedora/RHEL, run:")
        print("  mkdir -p ~/rpmbuild/SOURCES ~/rpmbuild/SPECS")
        print(f"  cp {source_tar} ~/rpmbuild/SOURCES/")
        print(f"  cp {SPEC_FILE} ~/rpmbuild/SPECS/")
        print("  rpmbuild -ba ~/rpmbuild/SPECS/vaultproxy.spec")
        print(f"  sudo dnf install ~/rpmbuild/RPMS/noarch/vaultproxy-{VERSION}-1*.rpm")
        return

    print("rpmbuild found! Building RPM...")
    rpmbuild_dir = DIST_DIR / "rpmbuild"
    for d in ["SOURCES", "SPECS", "BUILD", "RPMS", "SRPMS"]:
        (rpmbuild_dir / d).mkdir(parents=True, exist_ok=True)

    shutil.copy2(source_tar, rpmbuild_dir / "SOURCES")
    shutil.copy2(SPEC_FILE, rpmbuild_dir / "SPECS")

    cmd = [
        "rpmbuild",
        "--define", f"_topdir {rpmbuild_dir}",
        "-ba",
        str(rpmbuild_dir / "SPECS" / "vaultproxy.spec"),
    ]
    subprocess.run(cmd, check=True)
    print("RPM build successful!")


if __name__ == "__main__":
    build_rpm()
