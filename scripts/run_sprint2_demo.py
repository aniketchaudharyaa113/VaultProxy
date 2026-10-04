import subprocess
import time
import sys
import httpx


def run_demo():
    print("=== Starting Mock Upstream (port 8001) ===")
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
    )

    print("=== Starting VaultProxy Server (port 8000) ===")
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
    )

    time.sleep(2)

    try:
        print("\n--- [DEMO SPRINT 2: Streaming through Proxy with Mask & Restore] ---")
        client = httpx.Client(timeout=10)
        req_body_stream = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "Please verify my PAN ABCPB1234F and mobile 9876543210.",
                }
            ],
            "stream": True,
        }

        received_tokens = []
        with client.stream(
            "POST", "http://localhost:8000/v1/chat/completions", json=req_body_stream
        ) as res_stream:
            print(f"Status Code: {res_stream.status_code}")
            print("Client received stream output:")
            for line in res_stream.iter_lines():
                if line:
                    print(line)

    finally:
        proxy_proc.terminate()
        mock_proc.terminate()
        proxy_proc.wait()
        mock_proc.wait()

        _, mock_err = mock_proc.communicate()
        print("\n--- [MOCK UPSTREAM LOGS: WHAT THE CLOUD SAW] ---")
        print(mock_err.decode())


if __name__ == "__main__":
    run_demo()
