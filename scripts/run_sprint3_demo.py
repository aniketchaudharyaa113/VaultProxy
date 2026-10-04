import os
import subprocess
import time
import sys
import httpx


def run_demo():
    print("=== Starting Mock Upstream (port 8001) ===")
    mock_env = os.environ.copy()
    mock_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "demo.mock_upstream:app",
            "--port",
            "8001",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=mock_env,
    )

    print("=== Starting VaultProxy Server in GEMMA_BACKEND=off mode ===")
    proxy_env = os.environ.copy()
    proxy_env["GEMMA_BACKEND"] = "off"
    proxy_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "vaultproxy.server:app",
            "--port",
            "8000",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=proxy_env,
    )

    time.sleep(2)

    try:
        print("\n--- [DEMO 1: Request with X-Vault-Report Header] ---")
        client = httpx.Client(timeout=10)
        req_body = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "Aarav Kumar ka PAN hai ABCPB1234F and phone 9876543210.",
                }
            ],
            "stream": False,
        }
        res = client.post("http://localhost:8000/v1/chat/completions", json=req_body)
        print(f"Status Code: {res.status_code}")
        print(f"X-Vault-Report Header: {res.headers.get('x-vault-report')}")
        print(f"Restored Response: {res.json()['choices'][0]['message']['content']}")

    finally:
        proxy_proc.terminate()
        proxy_proc.wait()

    print("\n=== Starting VaultProxy Server in STRICT_MODE=true with Failed Ollama Backend ===")
    strict_env = os.environ.copy()
    strict_env["GEMMA_BACKEND"] = "ollama"
    strict_env["OLLAMA_URL"] = "http://localhost:9999"  # Non-existent port
    strict_env["STRICT_MODE"] = "true"

    proxy_strict_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "vaultproxy.server:app",
            "--port",
            "8000",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=strict_env,
    )

    time.sleep(2)

    try:
        print("\n--- [DEMO 2: Strict Mode Returns 503 on Gemma Failure] ---")
        res_fail = client.post("http://localhost:8000/v1/chat/completions", json=req_body)
        print(f"Status Code: {res_fail.status_code}")
        print(f"Error Detail: {res_fail.text}")

    finally:
        proxy_strict_proc.terminate()
        mock_proc.terminate()
        proxy_strict_proc.wait()
        mock_proc.wait()


if __name__ == "__main__":
    run_demo()
