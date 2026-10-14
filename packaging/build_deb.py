#!/usr/bin/env python3
"""Build a Debian package (.deb) for VaultProxy without needing dpkg-deb.

Generates a standard Debian binary package complying with Debian Policy.
Output: dist/vaultproxy_<version>_all.deb
"""

from __future__ import annotations

import io
import os
import shutil
import stat
import tarfile
import time
from pathlib import Path

VERSION = "0.2.1"
PKG_NAME = "vaultproxy"
REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"
DEB_FILE = DIST_DIR / f"{PKG_NAME}_{VERSION}_all.deb"


def make_tarinfo(name: str, size: int, mode: int, mtime: int, is_dir: bool = False) -> tarfile.TarInfo:
    ti = tarfile.TarInfo(name=name)
    ti.size = 0 if is_dir else size
    ti.type = tarfile.DIRTYPE if is_dir else tarfile.REGTYPE
    ti.mode = mode
    ti.mtime = mtime
    ti.uid = 0
    ti.gid = 0
    ti.uname = "root"
    ti.gname = "root"
    return ti


def create_control_archive() -> bytes:
    """Build control.tar.gz containing control, postinst, prerm, and conffiles."""
    buf = io.BytesIO()
    deb_dir = REPO_ROOT / "packaging" / "debian"
    now = int(time.time())

    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        # control
        control_path = deb_dir / "control"
        control_data = control_path.read_bytes()
        ti = make_tarinfo("./control", len(control_data), 0o644, now)
        tar.addfile(ti, io.BytesIO(control_data))

        # conffiles
        conffiles_path = deb_dir / "conffiles"
        if conffiles_path.exists():
            data = conffiles_path.read_bytes()
            ti = make_tarinfo("./conffiles", len(data), 0o644, now)
            tar.addfile(ti, io.BytesIO(data))

        # postinst
        postinst_path = deb_dir / "postinst"
        if postinst_path.exists():
            data = postinst_path.read_bytes()
            ti = make_tarinfo("./postinst", len(data), 0o755, now)
            tar.addfile(ti, io.BytesIO(data))

        # prerm
        prerm_path = deb_dir / "prerm"
        if prerm_path.exists():
            data = prerm_path.read_bytes()
            ti = make_tarinfo("./prerm", len(data), 0o755, now)
            tar.addfile(ti, io.BytesIO(data))

    return buf.getvalue()


def create_data_archive() -> bytes:
    """Build data.tar.gz containing the filesystem layout."""
    buf = io.BytesIO()
    now = int(time.time())

    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        # Standard directories
        dirs = [
            "./usr",
            "./usr/bin",
            "./usr/lib",
            "./usr/lib/python3",
            "./usr/lib/python3/dist-packages",
            "./usr/lib/python3/dist-packages/vaultproxy",
            "./lib",
            "./lib/systemd",
            "./lib/systemd/system",
            "./etc",
            "./etc/vaultproxy",
            "./var",
            "./var/lib",
            "./var/lib/vaultproxy",
        ]
        for d in dirs:
            tar.addfile(make_tarinfo(d, 0, 0o755, now, is_dir=True))

        # 1. Executable wrapper in /usr/bin/vaultproxy
        wrapper_script = (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "from vaultproxy.cli import main\n"
            "if __name__ == '__main__':\n"
            "    sys.exit(main())\n"
        ).encode("utf-8")
        ti = make_tarinfo("./usr/bin/vaultproxy", len(wrapper_script), 0o755, now)
        tar.addfile(ti, io.BytesIO(wrapper_script))

        # 2. Python package files from vaultproxy/
        pkg_src = REPO_ROOT / "vaultproxy"
        for root, dnames, files in os.walk(pkg_src):
            dnames[:] = [d for d in dnames if d != "__pycache__"]
            rel_dir = Path(root).relative_to(pkg_src)
            target_parent = f"./usr/lib/python3/dist-packages/vaultproxy/{rel_dir}".rstrip("/.")
            if target_parent != "./usr/lib/python3/dist-packages/vaultproxy":
                tar.addfile(make_tarinfo(target_parent, 0, 0o755, now, is_dir=True))
            for f in sorted(files):
                if f.endswith((".pyc", ".pyo")) or f == "__pycache__":
                    continue
                file_path = Path(root) / f
                content = file_path.read_bytes()
                target_path = f"{target_parent}/{f}"
                ti = make_tarinfo(target_path, len(content), 0o644, now)
                tar.addfile(ti, io.BytesIO(content))

        # 3. Systemd unit
        svc_src = REPO_ROOT / "packaging" / "systemd" / "vaultproxy.service"
        if svc_src.exists():
            svc_data = svc_src.read_bytes()
            ti = make_tarinfo("./lib/systemd/system/vaultproxy.service", len(svc_data), 0o644, now)
            tar.addfile(ti, io.BytesIO(svc_data))

        # 4. Config file
        cfg_src = REPO_ROOT / "packaging" / "systemd" / "config.env"
        if cfg_src.exists():
            cfg_data = cfg_src.read_bytes()
            ti = make_tarinfo("./etc/vaultproxy/config.env", len(cfg_data), 0o600, now)
            tar.addfile(ti, io.BytesIO(cfg_data))

    return buf.getvalue()


def write_ar_archive(dest_path: Path, members: list[tuple[str, bytes]]) -> None:
    """Write standard ar archive format for Debian packaging."""
    with dest_path.open("wb") as out:
        out.write(b"!<arch>\n")
        mtime = int(time.time())
        for name, data in members:
            # ar header is 60 bytes:
            # name: 16 chars
            # mtime: 12 chars
            # uid: 6 chars
            # gid: 6 chars
            # mode: 8 chars
            # size: 10 chars
            # trailer: `\n
            hdr = (
                f"{name:<16}"
                f"{mtime:<12}"
                f"{'0':<6}"
                f"{'0':<6}"
                f"{'100644':<8}"
                f"{len(data):<10}"
                "`\n"
            ).encode("ascii")
            out.write(hdr)
            out.write(data)
            if len(data) % 2 != 0:
                out.write(b"\n")


def build_deb() -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    print("Building Debian control archive...")
    control_gz = create_control_archive()

    print("Building Debian data archive...")
    data_gz = create_data_archive()

    print(f"Assembling {DEB_FILE.name}...")
    members = [
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", control_gz),
        ("data.tar.gz", data_gz),
    ]
    write_ar_archive(DEB_FILE, members)

    size = DEB_FILE.stat().st_size
    print(f"Successfully generated {DEB_FILE} ({size:,} bytes)")
    return DEB_FILE


if __name__ == "__main__":
    build_deb()
