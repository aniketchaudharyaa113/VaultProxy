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

    time.sleep(2)  # Give servers time to boot

    try:
        # Non-streaming request
        print("\n--- [DEMO 1: Non-Streaming Request via Proxy] ---")
        client = httpx.Client(timeout=10)
        req_body = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "Hello! My PAN is ABCPB1234F and mobile is 9876543210.",
                }
            ],
            "stream": False,
        }
        res_non_stream = client.post(
            "http://localhost:8000/v1/chat/completions", json=req_body
        )
        print(f"Status Code: {res_non_stream.status_code}")
        print(f"Response Body: {res_non_stream.text}")

        # Streaming request
        print("\n--- [DEMO 2: Streaming Request via Proxy] ---")
        req_body_stream = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "Streaming test: Aadhaar 367598341208",
                }
            ],
            "stream": True,
        }
        with client.stream(
            "POST", "http://localhost:8000/v1/chat/completions", json=req_body_stream
        ) as res_stream:
            print(f"Status Code: {res_stream.status_code}")
            print("Stream chunks:")
            for line in res_stream.iter_lines():
                if line:
                    print(line)

    finally:
        proxy_proc.terminate()
        mock_proc.terminate()
        proxy_proc.wait()
        mock_proc.wait()

        # Print mock upstream stderr to show "what the cloud saw"
        _, mock_err = mock_proc.communicate()
        print("\n--- [MOCK UPSTREAM LOGS: WHAT THE CLOUD SAW] ---")
        print(mock_err.decode())


if __name__ == "__main__":
    run_demo()
