import json
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from vaultproxy.config import settings
from vaultproxy.demo_api import router as demo_router
from vaultproxy.gemma_layer import GemmaLayerError
from vaultproxy.health import router as health_router
from vaultproxy.masking import MaskingEngine, has_non_text_parts
from vaultproxy.report import create_vault_report_header
from vaultproxy.restore import (
    process_sse_stream,
    restore_json_text,
    restore_text,
)
from vaultproxy.vault import RequestVault

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vaultproxy")

app = FastAPI(title="VaultProxy")
app.include_router(demo_router)
app.include_router(health_router)

if os.path.exists("demo/console"):
    app.mount("/demo/console", StaticFiles(directory="demo/console", html=True), name="console_static")

HOP_BY_HOP_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "keep-alive", "proxy-authorization", "proxy-authenticate",
    "te", "trailer", "upgrade",
}

PRODUCTION_ALLOWED_ROUTES = {
    ("POST", "/v1/chat/completions"), ("POST", "/v1/embeddings"),
    ("GET", "/v1/models"), ("GET", "/healthz"), ("GET", "/readyz"),
}


@app.middleware("http")
async def production_route_filter(request: Request, call_next: Any) -> Response:
    if settings.VAULT_PROFILE.lower() == "production":
        if (request.method.upper(), request.url.path) not in PRODUCTION_ALLOWED_ROUTES:
            return JSONResponse(
                status_code=404,
                content={"error": {"message": "Route not permitted in production profile.", "type": "not_found_error"}},
            )
    res: Response = await call_next(request)
    return res


def clean_headers(request_headers: Any) -> dict[str, str]:
    headers = {k: v for k, v in request_headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}
    if settings.UPSTREAM_API_KEY:
        headers["authorization"] = f"Bearer {settings.UPSTREAM_API_KEY}"
    return headers


def restore_json_payload(obj: Any, vault: RequestVault, parent_key: str = "") -> Any:
    if isinstance(obj, dict):
        return {k: restore_json_payload(v, vault, k) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [restore_json_payload(item, vault, parent_key) for item in obj]
    elif isinstance(obj, str):
        return restore_json_text(obj, vault) if parent_key == "arguments" else restore_text(obj, vault)
    return obj


@app.get("/v1/models")
async def get_models(request: Request) -> Response:
    headers = clean_headers(request.headers)
    url = f"{settings.UPSTREAM_BASE_URL.rstrip('/')}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            return Response(
                content=resp.content, status_code=resp.status_code,
                headers={k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS},
                media_type=resp.headers.get("content-type"),
            )
    except Exception as e:
        logger.error(f"Error fetching models: {type(e).__name__}")
        raise HTTPException(status_code=503, detail="VaultProxy fail-closed: Upstream models endpoint error.")


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> Response:
    vault = RequestVault()
    try:
        body_bytes = await request.body()
        body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

        if settings.VAULT_PROFILE.lower() == "production" and (not isinstance(body_json, dict) or "input" not in body_json):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "Invalid request body shape for embeddings. Must contain 'input'.", "type": "invalid_request_error"}},
            )

        inp = body_json.get("input") if isinstance(body_json, dict) else None
        is_token_ids = isinstance(inp, list) and len(inp) > 0 and isinstance(inp[0], int)
        token_id_warning = None

        if is_token_ids:
            if settings.VAULT_PROFILE.lower() == "production":
                return JSONResponse(
                    status_code=400,
                    content={"error": {"message": "Token ID embeddings input cannot be inspected for sensitive data in production profile.", "type": "invalid_request_error"}},
                )
            else:
                token_id_warning = "Token ID embeddings input uninspected"

        engine = MaskingEngine(vault)
        masked_body_json, degraded, gemma_used = await engine.mask_payload(body_json, scope=settings.effective_mask_scope)
        masked_bytes = json.dumps(masked_body_json).encode("utf-8")
    except Exception as e:
        logger.error(f"Error in embeddings masking: {type(e).__name__}")
        raise HTTPException(status_code=503, detail="VaultProxy fail-closed: Internal masking failure.")

    headers = clean_headers(request.headers)
    headers["content-type"] = "application/json"
    url = f"{settings.UPSTREAM_BASE_URL.rstrip('/')}/v1/embeddings"
    report_header = create_vault_report_header(masked_counts=vault.type_counts, degraded=degraded, gemma_used=gemma_used)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, content=masked_bytes)
            resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}
            resp_headers["x-vault-report"] = report_header
            resp_headers["x-vault-warning"] = token_id_warning or "Embeddings of masked text are not comparable across requests"
            return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers, media_type=resp.headers.get("content-type"))
    except Exception as e:
        logger.error(f"Upstream embeddings error: {type(e).__name__}")
        raise HTTPException(status_code=503, detail="VaultProxy fail-closed: Upstream connection error.")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    vault = RequestVault()
    try:
        body_bytes = await request.body()
        body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

        if settings.VAULT_PROFILE.lower() == "production" and (not isinstance(body_json, dict) or "messages" not in body_json or not isinstance(body_json.get("messages"), list)):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "Invalid request body shape for chat completions. Must contain a 'messages' array.", "type": "invalid_request_error"}},
            )

        warning_header = None
        if has_non_text_parts(body_json):
            if settings.effective_non_text_policy == "block":
                return JSONResponse(
                    status_code=400,
                    content={"error": {"message": "Non-text content (image_url, input_audio, file) cannot be inspected for sensitive data in this profile.", "type": "invalid_request_error"}},
                )
            else:
                warning_header = "Uninspected non-text content present"

        engine = MaskingEngine(vault)
        masked_body_json, degraded, gemma_used = await engine.mask_payload(body_json, scope=settings.effective_mask_scope)

        from vaultproxy.health import LAST_MASKED_REQUEST
        LAST_MASKED_REQUEST.clear()
        LAST_MASKED_REQUEST.update(masked_body_json)

        masked_body = json.dumps(masked_body_json).encode("utf-8")
    except GemmaLayerError as gle:
        logger.error(f"Fail-closed: Gemma layer error in STRICT_MODE: {gle}")
        raise HTTPException(status_code=503, detail=f"VaultProxy fail-closed: Gemma layer error in STRICT_MODE. {gle}")
    except Exception as e:
        logger.error(f"Fail-closed: Error during request masking: {type(e).__name__}")
        raise HTTPException(status_code=503, detail="VaultProxy fail-closed: Internal masking failure.")

    headers = clean_headers(request.headers)
    headers["content-type"] = "application/json"
    url = f"{settings.UPSTREAM_BASE_URL.rstrip('/')}/v1/chat/completions"
    report_header = create_vault_report_header(masked_counts=vault.type_counts, degraded=degraded, gemma_used=gemma_used)

    try:
        client = httpx.AsyncClient(timeout=60.0)
        req = client.build_request("POST", url, headers=headers, content=masked_body)
        upstream_resp = await client.send(req, stream=True)

        resp_headers = {k: v for k, v in upstream_resp.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}
        resp_headers["x-vault-report"] = report_header
        if warning_header:
            resp_headers["x-vault-warning"] = warning_header

        if upstream_resp.headers.get("content-type", "").startswith("text/event-stream"):
            model_name = body_json.get("model", "proxy-model")
            return StreamingResponse(process_sse_stream(upstream_resp, client, vault, model_name), status_code=upstream_resp.status_code, headers=resp_headers, media_type="text/event-stream")
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

            return Response(content=restored_content, status_code=upstream_resp.status_code, headers=resp_headers, media_type=upstream_resp.headers.get("content-type"))
    except Exception as e:
        logger.error(f"Error in proxy server: {type(e).__name__}")
        raise HTTPException(status_code=503, detail="VaultProxy fail-closed: Upstream connection error or internal failure.")


if __name__ == "__main__":
    import uvicorn  # type: ignore[import-not-found]
    uvicorn.run(app, host="0.0.0.0", port=8000)
