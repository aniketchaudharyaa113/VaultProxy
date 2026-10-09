import json
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from vaultproxy.config import settings
from vaultproxy.detectors.registry import run_rule_detectors
from vaultproxy.detectors.verhoeff import validate_verhoeff
from vaultproxy.gemma_layer import GemmaLayerError, run_gemma_detection
from vaultproxy.merge import merge_spans
from vaultproxy.restore import StreamRestorer, restore_text
from vaultproxy.vault import RequestVault

router = APIRouter(prefix="/demo", tags=["demo"])

SIMULATED_GEMMA_DOWN = False


def is_simulated_gemma_down() -> bool:
    return SIMULATED_GEMMA_DOWN


@router.get("/status")
async def demo_status() -> dict[str, Any]:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")

    backend = settings.GEMMA_BACKEND.lower()
    reachable = False
    model_name = settings.GEMMA_MODEL

    if backend in ("ollama", "auto"):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{settings.OLLAMA_URL.rstrip('/')}/api/tags")
                if resp.status_code == 200:
                    models_data = resp.json().get("models", [])
                    model_names = [m.get("name", "") for m in models_data]
                    if model_names:
                        reachable = True
                        if not any(settings.GEMMA_MODEL in name for name in model_names):
                            model_name = model_names[0]
        except Exception:
            reachable = (backend == "auto")
    elif backend == "gemini":
        reachable = bool(settings.GEMINI_API_KEY)
    else:
        reachable = False

    upstream_host = urlparse(settings.UPSTREAM_BASE_URL).netloc or settings.UPSTREAM_BASE_URL

    return {
        "gemma_backend": settings.GEMMA_BACKEND,
        "model_name": model_name,
        "reachable": reachable,
        "strict_mode": settings.STRICT_MODE,
        "demo_mode": settings.DEMO_MODE,
        "upstream_host": upstream_host,
        "simulated_gemma_down": SIMULATED_GEMMA_DOWN,
    }


@router.post("/simulate")
async def demo_simulate(payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")

    global SIMULATED_GEMMA_DOWN
    mode = payload.get("mode")
    if mode == "gemma_down":
        SIMULATED_GEMMA_DOWN = True
    elif mode == "reset":
        SIMULATED_GEMMA_DOWN = False
    else:
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")

    return {"status": "ok", "simulated_gemma_down": SIMULATED_GEMMA_DOWN}


@router.post("/analyze")
async def demo_analyze(payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")

    text = payload.get("text", "")
    use_gemma = payload.get("use_gemma", False)

    # 1. Rules detection
    t0 = time.perf_counter()
    rule_spans = run_rule_detectors(text)
    rules_ms = (time.perf_counter() - t0) * 1000

    # 2. Gemma detection
    t1 = time.perf_counter()
    gemma_spans: list[Any] = []
    gemma_used = False
    gemma_err = None

    if use_gemma and settings.GEMMA_BACKEND != "off" and not SIMULATED_GEMMA_DOWN:
        try:
            gemma_spans, g_deg, gemma_used = await run_gemma_detection(text)
            if g_deg:
                gemma_err = "Gemma detection degraded"
        except Exception as e:
            gemma_err = str(e)
    elif SIMULATED_GEMMA_DOWN and use_gemma:
        gemma_err = "Simulated Gemma connection timeout"

    gemma_ms = (time.perf_counter() - t1) * 1000

    # 3. Merge spans
    t2 = time.perf_counter()
    merged_spans = merge_spans(rule_spans + gemma_spans)
    merge_ms = (time.perf_counter() - t2) * 1000

    vault = RequestVault()
    masked_text = vault.mask_text(text, merged_spans)

    spans_out = []
    for span in merged_spans:
        val = text[span.start : span.end]
        chk_valid = validate_verhoeff(val) if span.type == "AADHAAR" else True
        spans_out.append(
            {
                "start": span.start,
                "end": span.end,
                "type": span.type,
                "source": span.source,
                "score": span.score,
                "text": val,
                "checksum_valid": chk_valid,
            }
        )

    return {
        "spans": spans_out,
        "masked_text": masked_text,
        "timings_ms": {
            "rules": round(rules_ms, 2),
            "gemma": round(gemma_ms, 2),
            "merge": round(merge_ms, 2),
        },
        "gemma": {
            "used": gemma_used,
            "error": gemma_err,
        },
    }


@router.post("/run")
async def demo_run(payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")

    text = payload.get("text", "")
    proxy = payload.get("proxy", True)
    use_gemma = payload.get("use_gemma", False)
    strict = payload.get("strict", False)
    stream = payload.get("stream", False)

    url = f"{settings.UPSTREAM_BASE_URL.rstrip('/')}/v1/chat/completions"

    if not proxy:
        # Send raw text directly to upstream to demonstrate the leak!
        req_payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": text}],
            "stream": stream,
        }
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=req_payload)
            upstream_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"Upstream error: {resp.text}")

            if stream:
                reply_text = ""
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    try:
                        cdata = json.loads(line[6:])
                        delta = cdata.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            reply_text += delta
                    except Exception:
                        pass
            else:
                resp_data = resp.json()
                reply_text = (
                    resp_data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

        return {
            "typed_text": text,
            "cloud_saw": json.dumps(req_payload, indent=2, ensure_ascii=False),
            "restored_reply": reply_text,
            "receipt": {"masked": {}, "degraded": False, "gemma_used": False},
            "timings_ms": {
                "rules": 0.0,
                "gemma": 0.0,
                "upstream": round(upstream_ms, 2),
                "restore": 0.0,
            },
        }

    # Proxy mode = True
    vault = RequestVault()

    # Rule detection timing
    t0 = time.perf_counter()
    rule_spans = run_rule_detectors(text)
    rules_ms = (time.perf_counter() - t0) * 1000

    # Gemma detection timing
    t1 = time.perf_counter()
    gemma_spans: list[Any] = []
    degraded = False
    gemma_used = False

    if SIMULATED_GEMMA_DOWN and use_gemma:
        if strict:
            raise HTTPException(
                status_code=503,
                detail="VaultProxy fail-closed: Gemma layer connection error in STRICT_MODE.",
            )
        else:
            degraded = True
            gemma_used = True
    elif use_gemma and settings.GEMMA_BACKEND != "off":
        try:
            gemma_spans, degraded, gemma_used = await run_gemma_detection(text)
        except GemmaLayerError as gle:
            if strict:
                raise HTTPException(
                    status_code=503,
                    detail=f"VaultProxy fail-closed: Gemma layer error in STRICT_MODE. {gle}",
                )
            degraded = True
            gemma_used = True

    gemma_ms = (time.perf_counter() - t1) * 1000

    all_spans = merge_spans(rule_spans + gemma_spans)
    masked_content = vault.mask_text(text, all_spans)

    system_msg = {
        "role": "system",
        "content": "IMPORTANT: Keep all token placeholders formatted like [TYPE_N] (e.g. [PAN_1], [AADHAAR_1]) EXACTLY as they are in your response. Do not modify, translate, or remove them.",
    }
    req_messages = [system_msg, {"role": "user", "content": masked_content}]

    upstream_payload = {
        "model": "gpt-4",
        "messages": req_messages,
        "stream": stream,
    }

    t2 = time.perf_counter()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=upstream_payload)
        upstream_ms = (time.perf_counter() - t2) * 1000
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"Upstream error: {resp.text}")

        if stream:
            reply_raw = ""
            restorer = StreamRestorer(vault)
            restored_chunks = []
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                try:
                    cdata = json.loads(line[6:])
                    delta = cdata.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        reply_raw += delta
                        restored_chunks.append(restorer.feed(delta))
                except Exception:
                    pass
            restored_chunks.append(restorer.flush())
            restored_reply = "".join(restored_chunks)
        else:
            resp_data = resp.json()
            reply_raw = (
                resp_data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            restored_reply = restore_text(reply_raw, vault)

    t3 = time.perf_counter()
    restore_ms = (time.perf_counter() - t3) * 1000

    return {
        "typed_text": text,
        "cloud_saw": json.dumps(upstream_payload, indent=2, ensure_ascii=False),
        "restored_reply": restored_reply,
        "receipt": {
            "masked": vault.type_counts,
            "degraded": degraded,
            "gemma_used": gemma_used,
        },
        "timings_ms": {
            "rules": round(rules_ms, 2),
            "gemma": round(gemma_ms, 2),
            "upstream": round(upstream_ms, 2),
            "restore": round(restore_ms, 2),
        },
    }


@router.post("/stream-trace")
async def demo_stream_trace(payload: dict[str, Any]) -> StreamingResponse:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")

    text = payload.get("text", "")
    vault = RequestVault()
    spans = merge_spans(run_rule_detectors(text))
    masked_text = vault.mask_text(text, spans)

    async def event_generator() -> Any:
        trace_events = []

        def trace_cb(upstream_chunk: str, held_buffer: str, emitted: str) -> None:
            trace_events.append(
                {
                    "upstream_chunk": upstream_chunk,
                    "held_buffer": held_buffer,
                    "emitted": emitted,
                }
            )

        restorer = StreamRestorer(vault, trace=trace_cb)

        chunk_size = 4
        for i in range(0, len(masked_text), chunk_size):
            chunk = masked_text[i : i + chunk_size]
            emitted = restorer.feed(chunk)
            event_data = {
                "upstream_chunk": chunk,
                "held_buffer": restorer.buffer,
                "emitted": emitted,
            }
            yield f"data: {json.dumps(event_data)}\n\n"

        final_emitted = restorer.flush()
        if final_emitted:
            yield f"data: {json.dumps({'upstream_chunk': '', 'held_buffer': '', 'emitted': final_emitted})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/benchmark")
async def demo_benchmark() -> dict[str, Any]:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")

    res_path = "bench/results.json"
    if os.path.exists(res_path):
        with open(res_path, encoding="utf-8") as f:
            res_dict: dict[str, Any] = json.load(f)
            return res_dict

    return {"error": "Benchmark results not found. Run benchmark script first."}
