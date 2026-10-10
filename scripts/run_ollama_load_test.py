import asyncio
import json
import os
import time
from typing import NamedTuple

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import httpx
import uvicorn

from vaultproxy.server import app as proxy_app
from vaultproxy.config import settings

# 1. Mock Upstream Cloud LLM Server (port 8001)
mock_upstream_app = FastAPI()

@mock_upstream_app.post("/v1/chat/completions")
async def mock_chat():
    return JSONResponse({
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "choices": [{"message": {"role": "assistant", "content": "Processed response for Rajesh Sharma."}}]
    })

# 2. Mock Ollama Server (port 11434)
mock_ollama_app = FastAPI()

@mock_ollama_app.get("/api/tags")
async def get_tags():
    return {"models": [{"name": "gemma4:e2b"}]}

@mock_ollama_app.post("/api/chat")
async def mock_ollama_chat(payload: dict):
    await asyncio.sleep(2.0)
    content = '{"entities": [{"type": "PERSON", "text": "Rajesh Sharma"}]}'
    return {"message": {"role": "assistant", "content": content}}

class Result(NamedTuple):
    status_code: int
    latency_ms: float
    degraded: bool

async def send_single_request(client: httpx.AsyncClient, url: str, headers: dict, payload: dict) -> Result:
    t0 = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, headers=headers)
        latency = (time.perf_counter() - t0) * 1000.0
        report_hdr = resp.headers.get("x-vault-report", "")
        degraded = False
        if report_hdr:
            try:
                hdr_obj = json.loads(report_hdr)
                degraded = bool(hdr_obj.get("degraded", False))
            except Exception:
                degraded = '"degraded": true' in report_hdr.lower() or "degraded=true" in report_hdr.lower()
        return Result(resp.status_code, latency, degraded)
    except Exception:
        latency = (time.perf_counter() - t0) * 1000.0
        return Result(503, latency, False)

async def run_concurrency_batch(url: str, headers: dict, payload: dict, num_requests: int, concurrency: int) -> dict:
    sem = asyncio.Semaphore(concurrency)
    results: list[Result] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        async def worker():
            async with sem:
                res = await send_single_request(client, url, headers, payload)
                results.append(res)

        tasks = [asyncio.create_task(worker()) for _ in range(num_requests)]
        await asyncio.gather(*tasks)

    latencies = sorted([r.latency_ms for r in results])
    c200 = sum(1 for r in results if r.status_code == 200)
    c429 = sum(1 for r in results if r.status_code == 429)
    c503 = sum(1 for r in results if r.status_code == 503)
    c_degraded = sum(1 for r in results if r.degraded)

    p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
    p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)] if latencies else 0.0
    p99 = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)] if latencies else 0.0

    return {
        "concurrency": concurrency,
        "total": len(results),
        "count_200": c200,
        "count_429": c429,
        "count_503": c503,
        "count_degraded": c_degraded,
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
    }

async def main():
    # Setup background servers
    upstream_srv = uvicorn.Server(uvicorn.Config(mock_upstream_app, host="127.0.0.1", port=8001, log_level="error"))
    ollama_srv = uvicorn.Server(uvicorn.Config(mock_ollama_app, host="127.0.0.1", port=11435, log_level="error"))
    proxy_srv = uvicorn.Server(uvicorn.Config(proxy_app, host="127.0.0.1", port=8000, log_level="error"))

    t_up = asyncio.create_task(upstream_srv.serve())
    t_ol = asyncio.create_task(ollama_srv.serve())
    t_pr = asyncio.create_task(proxy_srv.serve())

    await asyncio.sleep(1.5)

    url = "http://127.0.0.1:8000/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "My name is Rajesh Sharma and PAN is ABCPB1234F."}]
    }

    # Configure proxy settings for Ollama load test
    settings.GEMMA_BACKEND = "ollama"
    settings.OLLAMA_URL = "http://127.0.0.1:11435"
    settings.GEMMA_MODEL = "gemma4:e2b"
    settings.GEMMA_CONCURRENCY_LIMIT = 4
    settings.GEMMA_QUEUE_TIMEOUT_SECONDS = 2.0
    settings.GEMMA_TIMEOUT_SECONDS = 8.0

    print("==========================================================")
    print(" OLLAMA REAL SLM LOAD BENCHMARK (100 Requests/Level, 2s SLM Delay)")
    print(" Settings: GEMMA_CONCURRENCY_LIMIT=4, QUEUE_TIMEOUT=2.0s")
    print("==========================================================")

    for strict in [False, True]:
        settings.STRICT_MODE = strict
        mode_str = "STRICT_MODE=true" if strict else "STRICT_MODE=false"
        print(f"\n--- Running Mode: {mode_str} ---")
        print(f"{'Concurrency':<12} | {'Total':<6} | {'200':<5} | {'429':<5} | {'503':<5} | {'Degraded':<8} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'p99 (ms)':<9}")
        print("-" * 95)

        for level in [1, 5, 10, 20]:
            stats = await run_concurrency_batch(url, headers, payload, num_requests=100, concurrency=level)
            print(
                f"{stats['concurrency']:<12} | {stats['total']:<6} | {stats['count_200']:<5} | "
                f"{stats['count_429']:<5} | {stats['count_503']:<5} | {stats['count_degraded']:<8} | "
                f"{stats['p50_ms']:<9.2f} | {stats['p95_ms']:<9.2f} | {stats['p99_ms']:<9.2f}"
            )

    upstream_srv.should_exit = True
    ollama_srv.should_exit = True
    proxy_srv.should_exit = True
    await asyncio.gather(t_up, t_ol, t_pr, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())
