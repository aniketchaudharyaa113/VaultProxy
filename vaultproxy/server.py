import json
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from vaultproxy.config import settings
from vaultproxy.demo_api import router as demo_router
from vaultproxy.gemma_layer import GemmaLayerError
from vaultproxy.report import create_vault_report_header
from vaultproxy.restore import StreamRestorer, restore_text
from vaultproxy.vault import RequestVault

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


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    global LAST_MASKED_REQUEST
    vault = RequestVault()

    # Mask incoming request (FAIL CLOSED on any masking/gemma error in strict mode)
    try:
        body_bytes = await request.body()
        body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

        degraded = False
        gemma_used = False

        if "messages" in body_json and isinstance(body_json["messages"], list):
            (
                body_json["messages"],
                degraded,
                gemma_used,
            ) = await vault.mask_messages(body_json["messages"])

        if settings.DEMO_MODE:
            LAST_MASKED_REQUEST = body_json

        masked_body = json.dumps(body_json).encode("utf-8")
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

        if upstream_resp.headers.get("content-type", "").startswith(
            "text/event-stream"
        ):

            async def stream_wrapper() -> Any:
                restorer = StreamRestorer(vault)
                line_buffer = ""

                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        line_buffer += chunk.decode("utf-8", errors="replace")
                        lines = line_buffer.split("\n")
                        line_buffer = lines.pop()

                        for line in lines:
                            line_str = line.strip()
                            if not line_str:
                                continue
                            if line_str.startswith("data: "):
                                payload = line_str[6:].strip()
                                if payload == "[DONE]":
                                    flushed = restorer.flush()
                                    if flushed:
                                        final_chunk = {
                                            "id": "chatcmpl-restored",
                                            "object": "chat.completion.chunk",
                                            "created": 1700000000,
                                            "model": body_json.get("model", "proxy-model"),
                                            "choices": [
                                                {
                                                    "index": 0,
                                                    "delta": {"content": flushed},
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
                                            delta = choices[0].get("delta", {})
                                            content = delta.get("content", "")
                                            if content:
                                                restored_part = restorer.feed(content)
                                                if restored_part:
                                                    choices[0]["delta"]["content"] = restored_part
                                                    yield f"data: {json.dumps(data_obj)}\n\n"
                                            else:
                                                yield f"data: {json.dumps(data_obj)}\n\n"
                                        else:
                                            yield f"data: {payload}\n\n"
                                    except Exception:
                                        yield f"data: {payload}\n\n"
                            else:
                                yield f"{line_str}\n\n"

                    if line_buffer.strip():
                        lb = line_buffer.strip()
                        if lb.startswith("data: "):
                            p = lb[6:].strip()
                            if p == "[DONE]":
                                flushed = restorer.flush()
                                if flushed:
                                    final_chunk = {
                                        "id": "chatcmpl-restored",
                                        "object": "chat.completion.chunk",
                                        "created": 1700000000,
                                        "model": body_json.get("model", "proxy-model"),
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {"content": flushed},
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
                if "choices" in resp_json and isinstance(resp_json["choices"], list):
                    for choice in resp_json["choices"]:
                        msg = choice.get("message", {})
                        if "content" in msg and isinstance(msg["content"], str):
                            msg["content"] = restore_text(msg["content"], vault)
                restored_content = json.dumps(resp_json).encode("utf-8")
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
