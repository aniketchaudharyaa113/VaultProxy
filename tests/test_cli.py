import os
import subprocess
import sys
from pathlib import Path

import pytest

from vaultproxy import __version__
from vaultproxy.cli import build_parser, main


def test_cli_version(capsys):
    ret = main(["version"])
    assert ret == 0
    captured = capsys.readouterr()
    assert f"vaultproxy {__version__}" in captured.out


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "vaultproxy" in captured.out
    assert "run" in captured.out
    assert "init" in captured.out
    assert "doctor" in captured.out
    assert "check" in captured.out


def test_cli_check_text(capsys):
    ret = main(["check", "My PAN is ABCPB1234F and mobile 9876543210"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Detected entities" in captured.out
    assert "PAN: 1" in captured.out
    assert "[PAN_1]" in captured.out


def test_cli_check_file(tmp_path, capsys):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("Contact me at test@example.com with Aadhaar 367598341203", encoding="utf-8")
    ret = main(["check", "--file", str(test_file)])
    assert ret == 0
    captured = capsys.readouterr()
    assert "AADHAAR: 1" in captured.out
    assert "[AADHAAR_1]" in captured.out


def test_cli_init_and_no_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    assert not env_file.exists()

    # 1. First init creates .env
    ret = main(["init"])
    assert ret == 0
    assert env_file.exists()
    content = env_file.read_text(encoding="utf-8")
    assert "VAULT_AUTH_TOKEN=" in content
    assert "VAULT_PROFILE=development" in content
    captured = capsys.readouterr()
    assert "[PASS]" in captured.out

    # 2. Second init refuses to overwrite
    ret2 = main(["init"])
    assert ret2 == 0
    captured2 = capsys.readouterr()
    assert "[WARN] .env already exists; will not overwrite." in captured2.out


def test_cli_doctor(capsys):
    ret = main(["doctor"])
    captured = capsys.readouterr()
    assert "VaultProxy Doctor Diagnostics" in captured.out
    assert "Python version" in captured.out


def test_python_m_vaultproxy_exec():
    proc = subprocess.run(
        [sys.executable, "-m", "vaultproxy", "version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert f"vaultproxy {__version__}" in proc.stdout
