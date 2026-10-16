import subprocess
import sys

import pytest

from vaultproxy import __version__
from vaultproxy.cli import main


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


def test_cli_check_fail_on_secrets(capsys):
    # Has secret -> exits with 1
    ret1 = main(["check", "DATABASE_URL=postgres://root:secret@db:5432/app", "--fail-on-secrets"])
    assert ret1 == 1
    captured1 = capsys.readouterr()
    assert "SECRET: 1" in captured1.out

    # Clean text -> exits with 0
    ret2 = main(["check", "This is clean safe text.", "--fail-on-secrets"])
    assert ret2 == 0


def test_cli_check_json_output(capsys):
    ret = main(["check", "API_KEY=sk-proj-1234567890abcdef1234567890abcdef", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    assert '"detected": true' in captured.out
    assert '"SECRET": 1' in captured.out


def test_cli_scan_command(tmp_path, capsys):
    # Setup test directory with a clean file and a leaked .env
    clean_file = tmp_path / "app.json"
    clean_file.write_text('{"name": "myapp", "port": 3000}', encoding="utf-8")

    env_file = tmp_path / ".env.production"
    env_file.write_text("DATABASE_URL=postgres://app:dbpass@db:5432/main\nSECRET_KEY=supersecretkey", encoding="utf-8")

    # 1. Scan directory should find the leaked .env file and fail when --fail-on-secrets is set
    ret = main(["scan", str(tmp_path), "--fail-on-secrets"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "=== VaultProxy Scan" in captured.out
    assert ".env.production" in captured.out
    assert "SECRET: 2" in captured.out

    # 2. Scan multiple explicit files directly (pre-commit behavior)
    ret_multi = main(["scan", str(clean_file), str(env_file), "--fail-on-secrets"])
    assert ret_multi == 1

    # 3. Scan clean file passes with 0
    ret_clean = main(["scan", str(clean_file), "--fail-on-secrets"])
    assert ret_clean == 0


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
    assert main(["doctor"]) == 0
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
