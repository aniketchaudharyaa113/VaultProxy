import json
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from vaultproxy.config import settings
from vaultproxy.demo_api import router as demo_router
from vaultproxy.gemma_layer import GemmaLayerError
from vaultproxy.report import create_vault_report_header
from vaultproxy.restore import (
    StreamRestorer,
    restore_json_text,
    restore_text,
)
from vaultproxy.vault import RequestVault, has_non_text_parts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vaultproxy")

app = FastAPI(title="VaultProxy")

app.include_router(demo_router)

if os.path.exists("demo/console"):
    app.mount("/demo/console", StaticFiles(directory="demo/console", html=True), name="console_static")

LAST_MASKED_REQUEST: dict[str, Any] = {}

HOP_BY_HOP_HEADERS = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "proxy-authorization",
    "proxy-authenticate",
    "te",
    "trailer",
    "upgrade",
}

PRODUCTION_ALLOWED_ROUTES = {
    ("POST", "/v1/chat/completions"),
    ("POST", "/v1/embeddings"),
    ("GET", "/v1/models"),
    ("GET", "/healthz"),
    ("GET", "/readyz"),
}


@app.middleware("http")
async def production_route_filter(request: Request, call_next: Any) -> Response:
    if settings.PROFILE.lower() == "production":
        route_key = (request.method.upper(), request.url.path)
        if route_key not in PRODUCTION_ALLOWED_ROUTES:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "message": "Route not permitted in production profile.",
                        "type": "not_found_error",
                    }
                },
            )
    return await call_next(request)


@app.get("/health")
@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    from vaultproxy.gemma_layer import (
        LAST_SLM_LATENCY_MS,
        LAST_SLM_MODEL_NAME,
        circuit_breaker,
    )
    return {
        "status": "ready" if circuit_breaker.state != "OPEN" else "degraded",
        "slm_backend": settings.GEMMA_BACKEND,
        "slm_model": LAST_SLM_MODEL_NAME or settings.GEMMA_MODEL,
        "slm_latency_ms": LAST_SLM_LATENCY_MS,
        "circuit_breaker": circuit_breaker.state,
        "strict_mode": settings.STRICT_MODE,
        "profile": settings.PROFILE,
    }


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/demo/last")
async def demo_last() -> dict[str, Any]:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")
    return LAST_MASKED_REQUEST


@app.get("/demo", response_class=HTMLResponse)
async def demo_page() -> Response:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")
    try:
        if os.path.exists("demo/console/index.html"):
            with open("demo/console/index.html", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        with open("demo/index.html", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="demo/console/index.html not found."
        )


def clean_headers(request_headers: Any) -> dict[str, str]:
    headers = {}
    for key, value in request_headers.items():
        if key.lower() not in HOP_BY_HOP_HEADERS:
            headers[key] = value
    if settings.UPSTREAM_API_KEY:
        headers["authorization"] = f"Bearer {settings.UPSTREAM_API_KEY}"
    return headers


def restore_json_payload(obj: Any, vault: RequestVault, parent_key: str = "") -> Any:
    if isinstance(obj, dict):
        res = {}
        for k, v in obj.items():
            if k in ("arguments", "function_call", "tool_calls"):
                res[k] = restore_json_payload(v, vault, k)
            else:
                res[k] = restore_json_payload(v, vault, k)
        return res
    elif isinstance(obj, list):
        return [restore_json_payload(item, vault, parent_key) for item in obj]
    elif isinstance(obj, str):
        if parent_key == "arguments":
            return restore_json_text(obj, vault)
        return restore_text(obj, vault)
    return obj


@app.get("/v1/models")
async def get_models(request: Request) -> Response:
    headers = clean_headers(request.headers)
    url = f"{settings.UPSTREAM_BASE_URL.rstrip('/')}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers={k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS},
                media_type=resp.headers.get("content-type"),
            )
    except Exception as e:
        logger.error(f"Error fetching models: {type(e).__name__}")
        raise HTTPException(
            status_code=503,
            detail="VaultProxy fail-closed: Upstream models endpoint error.",
        )


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> Response:
    vault = RequestVault()
    try:
        body_bytes = await request.body()
        body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

        if settings.PROFILE.lower() == "production":
            if not isinstance(body_json, dict) or "input" not in body_json:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "message": "Invalid request body shape for embeddings. Must contain 'input'.",
                            "type": "invalid_request_error",
                        }
                    },
                )

        masked_body_json, degraded, gemma_used = await vault.mask_payload(
            body_json, scope=settings.effective_mask_scope
        )
        masked_bytes = json.dumps(masked_body_json).encode("utf-8")
    except Exception as e:
        logger.error(f"Error in embeddings masking: {type(e).__name__}")
        raise HTTPException(
            status_code=503,
            detail="VaultProxy fail-closed: Internal masking failure.",
        )

    headers = clean_headers(request.headers)
    headers["content-type"] = "application/json"
    url = f"{settings.UPSTREAM_BASE_URL.rstrip('/')}/v1/embeddings"
    report_header = create_vault_report_header(
        masked_counts=vault.type_counts, degraded=degraded, gemma_used=gemma_used
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, content=masked_bytes)
            resp_headers = {
                k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS
            }
            resp_headers["x-vault-report"] = report_header
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("content-type"),
            )
    except Exception as e:
        logger.error(f"Upstream embeddings error: {type(e).__name__}")
        raise HTTPException(
            status_code=503,
            detail="VaultProxy fail-closed: Upstream connection error.",
        )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    global LAST_MASKED_REQUEST
    vault = RequestVault()

    try:
        body_bytes = await request.body()
        body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

        if settings.PROFILE.lower() == "production":
            if not isinstance(body_json, dict) or "messages" not in body_json or not isinstance(body_json.get("messages"), list):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "message": "Invalid request body shape for chat completions. Must contain a 'messages' array.",
                            "type": "invalid_request_error",
                        }
                    },
                )

        has_non_text = has_non_text_parts(body_json)
        warning_header: str | None = None
        if has_non_text:
            if settings.effective_non_text_policy == "block":
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "message": "Non-text content (image_url, input_audio, file) cannot be inspected for sensitive data in this profile.",
                            "type": "invalid_request_error",
                        }
                    },
                )
            else:
                warning_header = "Uninspected non-text content present"

        masked_body_json, degraded, gemma_used = await vault.mask_payload(
            body_json, scope=settings.effective_mask_scope
        )

        if settings.DEMO_MODE:
            LAST_MASKED_REQUEST = masked_body_json

        masked_body = json.dumps(masked_body_json).encode("utf-8")
    except GemmaLayerError as gle:
        logger.error(f"Fail-closed: Gemma layer error in STRICT_MODE: {gle}")
        raise HTTPException(
            status_code=503,
            detail=f"VaultProxy fail-closed: Gemma layer error in STRICT_MODE. {gle}",
        )
    except Exception as e:
        logger.error(
            f"Fail-closed: Error during request masking: {type(e).__name__}"
        )
        raise HTTPException(
            status_code=503,
            detail="VaultProxy fail-closed: Internal masking failure.",
        )

    headers = clean_headers(request.headers)
    headers["content-type"] = "application/json"
    url = f"{settings.UPSTREAM_BASE_URL.rstrip('/')}/v1/chat/completions"

    report_header = create_vault_report_header(
        masked_counts=vault.type_counts,
        degraded=degraded,
        gemma_used=gemma_used,
    )

    try:
        client = httpx.AsyncClient(timeout=60.0)
        req = client.build_request("POST", url, headers=headers, content=masked_body)
        upstream_resp = await client.send(req, stream=True)

        resp_headers = {
            k: v
            for k, v in upstream_resp.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS
        }
        resp_headers["x-vault-report"] = report_header
        if warning_header:
            resp_headers["x-vault-warning"] = warning_header

        if upstream_resp.headers.get("content-type", "").startswith(
            "text/event-stream"
        ):

            async def stream_wrapper() -> Any:
                restorers: dict[str, StreamRestorer] = {}
                line_buffer = ""

                def get_restorer(key: str, json_escape: bool = False) -> StreamRestorer:
                    if key not in restorers:
                        restorers[key] = StreamRestorer(vault, json_escape=json_escape)
                    return restorers[key]

                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        line_buffer += chunk.decode("utf-8", errors="replace")
                        lines = line_buffer.split("\n")
                        line_buffer = lines.pop()

                        for line in lines:
                            line_str = line.strip()
                            if not line_str:
                                continue
                            if line_str.startswith(":"):
                                yield f"{line_str}\n\n"
                                continue
                            if line_str.startswith("data: "):
                                payload = line_str[6:].strip()
                                if payload == "[DONE]":
                                    flushed_chunks = []
                                    for key, r in restorers.items():
                                        flushed_val = r.flush()
                                        if flushed_val:
                                            flushed_chunks.append((key, flushed_val))
                                    if flushed_chunks:
                                        for key, val in flushed_chunks:
                                            c_idx = int(key.split("_")[0]) if key.split("_")[0].isdigit() else 0
                                            final_chunk = {
                                                "id": "chatcmpl-restored",
                                                "object": "chat.completion.chunk",
                                                "created": 1700000000,
                                                "model": body_json.get("model", "proxy-model"),
                                                "choices": [
                                                    {
                                                        "index": c_idx,
                                                        "delta": {"content": val},
                                                        "finish_reason": None,
                                                    }
                                                ],
                                            }
                                            yield f"data: {json.dumps(final_chunk)}\n\n"
                                    yield "data: [DONE]\n\n"
                                else:
                                    try:
                                        data_obj = json.loads(payload)
                                        choices = data_obj.get("choices", [])
                                        if choices and isinstance(choices, list):
                                            for c in choices:
                                                c_idx = c.get("index", 0)
                                                delta = c.get("delta", {})
                                                if "content" in delta and isinstance(delta["content"], str):
                                                    r = get_restorer(f"{c_idx}_content", json_escape=False)
                                                    restored_part = r.feed(delta["content"])
                                                    delta["content"] = restored_part
                                                if "tool_calls" in delta and isinstance(delta["tool_calls"], list):
                                                    for t_idx, tc in enumerate(delta["tool_calls"]):
                                                        func = tc.get("function", {})
                                                        if "arguments" in func and isinstance(func["arguments"], str):
                                                            r = get_restorer(f"{c_idx}_tool_{t_idx}_args", json_escape=True)
                                                            func["arguments"] = r.feed(func["arguments"])
                                                if "function_call" in delta and isinstance(delta["function_call"], dict):
                                                    fc = delta["function_call"]
                                                    if "arguments" in fc and isinstance(fc["arguments"], str):
                                                        r = get_restorer(f"{c_idx}_func_args", json_escape=True)
                                                        fc["arguments"] = r.feed(fc["arguments"])
                                            yield f"data: {json.dumps(data_obj)}\n\n"
                                        else:
                                            yield f"data: {json.dumps(data_obj)}\n\n"
                                    except Exception:
                                        yield f"data: {payload}\n\n"
                            else:
                                yield f"{line_str}\n\n"

                    if line_buffer.strip():
                        lb = line_buffer.strip()
                        if lb.startswith("data: "):
                            p = lb[6:].strip()
                            if p == "[DONE]":
                                flushed_chunks = []
                                for key, r in restorers.items():
                                    flushed_val = r.flush()
                                    if flushed_val:
                                        flushed_chunks.append((key, flushed_val))
                                if flushed_chunks:
                                    for key, val in flushed_chunks:
                                        c_idx = int(key.split("_")[0]) if key.split("_")[0].isdigit() else 0
                                        final_chunk = {
                                            "id": "chatcmpl-restored",
                                            "object": "chat.completion.chunk",
                                            "created": 1700000000,
                                            "model": body_json.get("model", "proxy-model"),
                                            "choices": [
                                                {
                                                    "index": c_idx,
                                                    "delta": {"content": val},
                                                    "finish_reason": None,
                                                }
                                            ],
                                        }
                                        yield f"data: {json.dumps(final_chunk)}\n\n"
                                yield "data: [DONE]\n\n"

                finally:
                    await upstream_resp.aclose()
                    await client.aclose()

            return StreamingResponse(
                stream_wrapper(),
                status_code=upstream_resp.status_code,
                headers=resp_headers,
                media_type="text/event-stream",
            )
        else:
            content = await upstream_resp.aread()
            await upstream_resp.aclose()
            await client.aclose()

            try:
                resp_json = json.loads(content.decode("utf-8"))
                restored_json = restore_json_payload(resp_json, vault)
                restored_content = json.dumps(restored_json).encode("utf-8")
            except Exception:
                restored_content = content

            return Response(
                content=restored_content,
                status_code=upstream_resp.status_code,
                headers=resp_headers,
                media_type=upstream_resp.headers.get("content-type"),
            )

    except Exception as e:
        logger.error(f"Error in proxy server: {type(e).__name__}")
        raise HTTPException(
            status_code=503,
            detail="VaultProxy fail-closed: Upstream connection error or internal failure.",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
