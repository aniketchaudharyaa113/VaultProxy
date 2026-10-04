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

    print("=== Starting VaultProxy Server in DEMO_MODE=true ===")
    proxy_env = os.environ.copy()
    proxy_env["DEMO_MODE"] = "true"
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
        client = httpx.Client(timeout=10)

        print("\n--- [DEMO J1-1: Testing GET /demo/status] ---")
        res_status = client.get("http://localhost:8000/demo/status")
        print(f"Status Code: {res_status.status_code}")
        print(f"Status Payload: {res_status.text}")

        print("\n--- [DEMO J1-2: Testing POST /demo/analyze] ---")
        req_text = "Loan application for Rajesh Sharma, PAN ABCPB1234F, Aadhaar 367598341203."
        res_analyze = client.post("http://localhost:8000/demo/analyze", json={"text": req_text, "use_gemma": False})
        print(f"Status Code: {res_analyze.status_code}")
        print(f"Analyze Output: {res_analyze.text}")

        print("\n--- [DEMO J1-3: Testing POST /demo/run (Proxy ON vs OFF)] ---")
        res_off = client.post("http://localhost:8000/demo/run", json={"text": req_text, "proxy": False})
        print(f"Proxy OFF Cloud Saw: {res_off.json()['cloud_saw']}")

        res_on = client.post("http://localhost:8000/demo/run", json={"text": req_text, "proxy": True})
        print(f"Proxy ON Cloud Saw: {res_on.json()['cloud_saw']}")
        print(f"Proxy ON Restored: {res_on.json()['restored_reply']}")

        print("\n--- [DEMO J1-4: Testing POST /demo/stream-trace] ---")
        res_trace = client.post("http://localhost:8000/demo/stream-trace", json={"text": "Stream test ABCPB1234F"})
        print(f"Trace events snippet:\n{res_trace.text[:300]}...")

        print("\n--- [DEMO J1-5: Testing GET /demo/benchmark] ---")
        res_bench = client.get("http://localhost:8000/demo/benchmark")
        print(f"Benchmark metrics overall: {res_bench.json().get('overall')}")

    finally:
        proxy_proc.terminate()
        mock_proc.terminate()
        proxy_proc.wait()
        mock_proc.wait()


if __name__ == "__main__":
    run_demo()
