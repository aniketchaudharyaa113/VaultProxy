#!/usr/bin/env python3
import asyncio
import argparse
import sys
import time
from typing import NamedTuple

import httpx

class Result(NamedTuple):
    status_code: int
    latency_ms: float

async def send_request(client: httpx.AsyncClient, url: str, headers: dict, payload: dict) -> Result:
    t0 = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, headers=headers)
        latency = (time.perf_counter() - t0) * 1000.0
        return Result(resp.status_code, latency)
    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000.0
        return Result(503, latency)

async def run_concurrency_level(url: str, headers: dict, payload: dict, num_requests: int, concurrency: int) -> dict:
    sem = asyncio.Semaphore(concurrency)
    results: list[Result] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        async def worker():
            async with sem:
                res = await send_request(client, url, headers, payload)
                results.append(res)

        tasks = [asyncio.create_task(worker()) for _ in range(num_requests)]
        await asyncio.gather(*tasks)

    latencies = sorted([r.latency_ms for r in results])
    c200 = sum(1 for r in results if r.status_code == 200)
    c429 = sum(1 for r in results if r.status_code == 429)
    c503 = sum(1 for r in results if r.status_code == 503)

    p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
    p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)] if latencies else 0.0

    return {
        "concurrency": concurrency,
        "total": len(results),
        "count_200": c200,
        "count_429": c429,
        "count_503": c503,
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
    }

async def main():
    parser = argparse.ArgumentParser(description="VaultProxy Load Check Tool")
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions", help="Target endpoint")
    parser.add_argument("--token", default="", help="Vault auth token if required")
    parser.add_argument("--requests", type=int, default=20, help="Number of requests per level")
    parser.add_argument("--levels", nargs="+", type=int, default=[1, 5, 10, 20], help="Concurrency levels")
    args = parser.parse_args()

    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "Load test query with PAN ABCPB1234F and name Rajesh Sharma."}],
    }

    print(f"Running load check against {args.url}")
    print(f"Requests per level: {args.requests}")
    print(f"{'Concurrency':<12} | {'Total':<6} | {'200':<5} | {'429':<5} | {'503':<5} | {'p50 (ms)':<9} | {'p95 (ms)':<9}")
    print("-" * 70)

    for level in args.levels:
        stats = await run_concurrency_level(args.url, headers, payload, args.requests, level)
        print(
            f"{stats['concurrency']:<12} | {stats['total']:<6} | {stats['count_200']:<5} | "
            f"{stats['count_429']:<5} | {stats['count_503']:<5} | {stats['p50_ms']:<9.2f} | {stats['p95_ms']:<9.2f}"
        )

if __name__ == "__main__":
    asyncio.run(main())
