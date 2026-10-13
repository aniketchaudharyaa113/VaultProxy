import os
import subprocess
import sys


def test_b15_production_startup_readable_error():
    """B15: Misconfigured production startup must print a readable error to stderr and exit without traceback."""
    env = dict(os.environ, VAULT_PROFILE="production", GEMMA_BACKEND="off")
    env.pop("VAULT_AUTH_TOKEN", None)
    proc = subprocess.run(
        [sys.executable, "-m", "uvicorn", "vaultproxy.server:app", "--port", "0"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "Traceback" not in output
    assert "VAULT_AUTH_TOKEN" in output
    assert "VAULT_AUTH_TOKEN is required in production profile and must be at least 24 characters long" in output
