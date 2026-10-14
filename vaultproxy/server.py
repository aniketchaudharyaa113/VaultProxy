import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from vaultproxy.config import settings
from vaultproxy.demo_api import router as demo_router
from vaultproxy.gemma_layer import GemmaLayerError, circuit_breaker
from vaultproxy.health import is_authenticated_request
from vaultproxy.health import router as health_router
from vaultproxy.masking import MaskingEngine, has_non_text_parts
from vaultproxy.metrics import (
    METRICS_AVAILABLE,
    generate_latest,
    record_request_metrics,
)
from vaultproxy.report import create_vault_report_header
from vaultproxy.restore import (
    process_sse_stream,
    restore_json_text,
    restore_text,
)
from vaultproxy.vault import RequestVault

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vaultproxy")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_httpx_client: httpx.AsyncClient | None = None


async def startup_event() -> None:
    protection_str = (
        "rules only"
        if settings.GEMMA_BACKEND.lower() == "off"
        else f"rules + {settings.GEMMA_MODEL}"
    )
    logger.info(f"Protection: {protection_str}")
    logger.info(
        f"VaultProxy starting up. Profile: {settings.VAULT_PROFILE}. "
        "Maximum SLM input size: 24,000 chars (4 chunks x 6,000 chars with 300-char overlap). "
        "Inputs exceeding limit fail-closed with 503 in STRICT_MODE, or mark degraded=true in non-STRICT mode."
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await startup_event()
    yield
    global _httpx_client
    if _httpx_client is not None and not _httpx_client.is_closed:
        await _httpx_client.aclose()


app = FastAPI(title="VaultProxy", lifespan=lifespan)
app.include_router(demo_router)
app.include_router(health_router)


@app.exception_handler(HTTPException)
async def _http_exception_with_request_id(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Wrap all HTTPException responses with an x-request-id header and ensure
    the body is an OpenAI-compatible error object for 4xx/5xx responses."""
    req_id = str(uuid.uuid4())
    detail = exc.detail
    if isinstance(detail, str):
        body = {
            "error": {
                "message": detail,
                "type": "invalid_request_error" if exc.status_code < 500 else "server_error",
            },
            "detail": detail,
        }
    elif isinstance(detail, dict) and "error" in detail:
        body = dict(detail)
        body.setdefault("detail", detail["error"].get("message", str(detail)))
    else:
        body = {
            "error": {"message": str(detail), "type": "server_error"},
            "detail": str(detail),
        }
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers={"x-request-id": req_id},
    )

if os.path.exists("demo/console"):
    app.mount(
        "/demo/console",
        StaticFiles(directory="demo/console", html=True),
        name="console_static",
    )

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

CLIENT_HEADER_ALLOWLIST = {
    "content-type",
    "accept",
    "user-agent",
    "openai-organization",
    "openai-project",
    "openai-beta",
}

RESPONSE_DROP_HEADERS = HOP_BY_HOP_HEADERS | {
    "set-cookie",
    "content-encoding",
    "content-length",
    "transfer-encoding",
}

PRODUCTION_ALLOWED_ROUTES = {
    ("POST", "/v1/chat/completions"),
    ("POST", "/chat/completions"),
    ("POST", "/v1/embeddings"),
    ("POST", "/embeddings"),
    ("GET", "/v1/models"),
    ("GET", "/models"),
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("GET", "/metrics"),
}

_concurrency_semaphore: asyncio.Semaphore | None = None


def build_upstream_url(base_url: str, endpoint: str) -> str:
    """Build upstream URL following OpenAI SDK conventions.

    Treats UPSTREAM_BASE_URL like base_url: appends endpoint (e.g. chat/completions,
    embeddings, models). If base_url has no path component at all, /v1 is added.
    """
    from urllib.parse import urlparse

    parsed = urlparse(base_url.rstrip("/"))
    clean_endpoint = endpoint.lstrip("/")
    base_path = parsed.path.rstrip("/")

    # If the URL has no path at all (e.g. https://api.openai.com), add /v1
    if not base_path:
        path = f"/v1/{clean_endpoint}"
    else:
        path = f"{base_path}/{clean_endpoint}"

    port_str = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port_str}{path}"


def get_httpx_client() -> httpx.AsyncClient:
    global _httpx_client
    if _httpx_client is None or _httpx_client.is_closed:
        timeout_cfg = httpx.Timeout(
            connect=settings.REQUEST_TIMEOUT_SECONDS,
            read=settings.REQUEST_TIMEOUT_SECONDS,
            write=settings.REQUEST_TIMEOUT_SECONDS,
            pool=settings.REQUEST_TIMEOUT_SECONDS,
        )
        _httpx_client = httpx.AsyncClient(timeout=timeout_cfg, verify=True)
    return _httpx_client


def get_concurrency_semaphore() -> asyncio.Semaphore:
    global _concurrency_semaphore
    if _concurrency_semaphore is None:
        _concurrency_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)
    return _concurrency_semaphore


@app.middleware("http")
async def production_route_filter(request: Request, call_next: Any) -> Response:
    if settings.VAULT_PROFILE.lower() == "production":
        if (request.method.upper(), request.url.path) not in PRODUCTION_ALLOWED_ROUTES:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "message": "Route not permitted in production profile.",
                        "type": "not_found_error",
                    }
                },
            )
    res: Response = await call_next(request)
    return res


def clean_headers(request_headers: Any) -> dict[str, str]:
    headers = {
        k.lower(): v
        for k, v in request_headers.items()
        if k.lower() in CLIENT_HEADER_ALLOWLIST
    }
    if settings.UPSTREAM_API_KEY:
        headers["authorization"] = f"Bearer {settings.UPSTREAM_API_KEY}"
    return headers


def clean_response_headers(upstream_headers: Any) -> dict[str, str]:
    return {
        k: v
        for k, v in upstream_headers.items()
        if k.lower() not in RESPONSE_DROP_HEADERS
    }


def restore_json_payload(obj: Any, vault: RequestVault, parent_key: str = "") -> Any:
    if isinstance(obj, dict):
        return {k: restore_json_payload(v, vault, k) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [restore_json_payload(item, vault, parent_key) for item in obj]
    elif isinstance(obj, str):
        if parent_key == "arguments":
            return restore_json_text(obj, vault)
        if (
            parent_key == "content"
            and obj.strip().startswith("{")
            and obj.strip().endswith("}")
        ):
            try:
                json.loads(obj)
                return restore_json_text(obj, vault)
            except Exception:
                pass
        return restore_text(obj, vault)
    return obj


async def parse_and_validate_request_body(request: Request) -> tuple[bytes, dict[str, Any]]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.MAX_BODY_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Request body size exceeds maximum allowed limit.",
                )
        except ValueError:
            pass

    body_chunks = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > settings.MAX_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Request body size exceeds maximum allowed limit.",
            )
        body_chunks.append(chunk)

    body_bytes = b"".join(body_chunks)
    if not body_bytes:
        return b"", {}

    try:
        body_json = json.loads(body_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400, detail="Invalid UTF-8 encoding in request body."
        )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400, detail="Request body is not valid JSON."
        )

    return body_bytes, body_json


@app.get("/metrics")
async def get_metrics(request: Request) -> Response:
    if settings.VAULT_AUTH_TOKEN and not is_authenticated_request(request):
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "message": "Invalid API key provided.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )

    if not METRICS_AVAILABLE:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "message": "Metrics feature not installed.",
                    "type": "not_found_error",
                }
            },
        )


    return Response(content=generate_latest(), media_type="text/plain; version=0.0.4")


@app.get("/v1/models")
@app.get("/models")
async def get_models(request: Request) -> Response:
    t0 = time.perf_counter()
    req_id = str(uuid.uuid4())

    if settings.VAULT_AUTH_TOKEN and not is_authenticated_request(request):
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "message": "Invalid API key provided.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )

    headers = clean_headers(request.headers)
    url = build_upstream_url(settings.UPSTREAM_BASE_URL, "models")
    client = get_httpx_client()

    try:
        resp = await client.get(url, headers=headers)
        status_code = resp.status_code
        res = Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=clean_response_headers(resp.headers),
            media_type=resp.headers.get("content-type"),
        )
    except Exception as e:
        logger.error(f"Error fetching models: {type(e).__name__}")
        status_code = 503
        raise HTTPException(
            status_code=503,
            detail="VaultProxy fail-closed: Upstream models endpoint error.",
        )

    ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        json.dumps(
            {
                "request_id": req_id,
                "status": status_code,
                "milliseconds": ms,
                "counts": {},
                "degraded": False,
                "strict": settings.STRICT_MODE,
            }
        )
    )
    record_request_metrics(ms / 1000.0, 0, False, circuit_breaker.state)
    return res


@app.post("/v1/embeddings")
@app.post("/embeddings")
async def embeddings(request: Request) -> Response:
    t0 = time.perf_counter()
    req_id = str(uuid.uuid4())

    if settings.VAULT_AUTH_TOKEN and not is_authenticated_request(request):
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "message": "Invalid API key provided.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )

    sem = get_concurrency_semaphore()
    if sem.locked():
        return JSONResponse(
            status_code=429,
            headers={"retry-after": "5"},
            content={
                "error": {
                    "message": "Too many concurrent requests.",
                    "type": "rate_limit_error",
                }
            },
        )

    async with sem:
        vault = RequestVault()
        degraded = False
        counts: dict[str, int] = {}
        try:
            _, body_json = await parse_and_validate_request_body(request)

            if settings.VAULT_PROFILE.lower() == "production" and (
                not isinstance(body_json, dict) or "input" not in body_json
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request body shape for embeddings. Must contain 'input'.",
                )

            inp = body_json.get("input") if isinstance(body_json, dict) else None
            is_token_ids = (
                isinstance(inp, list) and len(inp) > 0 and isinstance(inp[0], int)
            )
            token_id_warning = None

            if is_token_ids:
                if settings.VAULT_PROFILE.lower() == "production":
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "message": "Token ID embeddings input cannot be inspected for sensitive data in production profile.",
                                "type": "invalid_request_error",
                            }
                        },
                    )
                else:
                    token_id_warning = "Token ID embeddings input uninspected"

            engine = MaskingEngine(vault)
            (
                masked_body_json,
                degraded,
                gemma_used,
                slm_chunks,
            ) = await engine.mask_payload(body_json)
            counts = vault.type_counts
            masked_bytes = json.dumps(masked_body_json).encode("utf-8")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in embeddings masking: {type(e).__name__}")
            raise HTTPException(
                status_code=503,
                detail="VaultProxy fail-closed: Internal masking failure.",
            )

        headers = clean_headers(request.headers)
        headers["content-type"] = "application/json"
        url = build_upstream_url(settings.UPSTREAM_BASE_URL, "embeddings")
        report_header = create_vault_report_header(
            masked_counts=vault.type_counts,
            degraded=degraded,
            gemma_used=gemma_used,
            slm_chunks=slm_chunks,
        )

        client = get_httpx_client()
        try:
            resp = await client.post(url, headers=headers, content=masked_bytes)
            status_code = resp.status_code
            resp_headers = clean_response_headers(resp.headers)
            resp_headers["x-vault-report"] = report_header
            resp_headers["x-vault-warning"] = (
                f"{token_id_warning}; Embeddings of masked text are not comparable across requests"
                if token_id_warning
                else "Embeddings of masked text are not comparable across requests"
            )
            res = Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("content-type"),
            )
        except Exception as e:
            logger.error(f"Upstream embeddings error: {type(e).__name__}")
            status_code = 503
            raise HTTPException(
                status_code=503,
                detail="VaultProxy fail-closed: Upstream connection error.",
            )

        ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            json.dumps(
                {
                    "request_id": req_id,
                    "status": status_code,
                    "milliseconds": ms,
                    "counts": counts,
                    "degraded": degraded,
                    "strict": settings.STRICT_MODE,
                }
            )
        )
        record_request_metrics(
            ms / 1000.0, sum(counts.values()), degraded, circuit_breaker.state
        )
        return res


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_completions(request: Request) -> Response:
    t0 = time.perf_counter()
    req_id = str(uuid.uuid4())

    if settings.VAULT_AUTH_TOKEN and not is_authenticated_request(request):
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "message": "Invalid API key provided.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )

    sem = get_concurrency_semaphore()
    if sem.locked():
        return JSONResponse(
            status_code=429,
            headers={"retry-after": "5"},
            content={
                "error": {
                    "message": "Too many concurrent requests.",
                    "type": "rate_limit_error",
                }
            },
        )

    await sem.acquire()
    slot_held = True

    try:
        vault = RequestVault()
        degraded = False
        counts: dict[str, int] = {}
        try:
            _, body_json = await parse_and_validate_request_body(request)

            if settings.VAULT_PROFILE.lower() == "production" and (
                not isinstance(body_json, dict)
                or "messages" not in body_json
                or not isinstance(body_json.get("messages"), list)
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request body shape for chat completions. Must contain a 'messages' array.",
                )

            warning_header = None
            if has_non_text_parts(body_json):
                if settings.effective_non_text_policy == "block":
                    raise HTTPException(
                        status_code=400,
                        detail="Non-text content (image_url, input_audio, file) cannot be inspected for sensitive data in this profile.",
                    )
                else:
                    warning_header = "Uninspected non-text content present"

            engine = MaskingEngine(vault)
            (
                masked_body_json,
                degraded,
                gemma_used,
                slm_chunks,
            ) = await engine.mask_payload(body_json)
            counts = vault.type_counts

            if settings.DEMO_MODE:
                from vaultproxy.health import LAST_MASKED_REQUEST

                LAST_MASKED_REQUEST.clear()
                LAST_MASKED_REQUEST.update(masked_body_json)

            masked_body = json.dumps(masked_body_json).encode("utf-8")
        except HTTPException:
            raise
        except GemmaLayerError as gle:
            logger.error(f"Fail-closed: Gemma layer error in STRICT_MODE: {gle}")
            raise HTTPException(
                status_code=503,
                detail=f"VaultProxy fail-closed: Gemma layer error in STRICT_MODE. {gle}",
            )
        except Exception as e:
            logger.error(f"Fail-closed: Error during request masking: {type(e).__name__}")
            raise HTTPException(
                status_code=503,
                detail="VaultProxy fail-closed: Internal masking failure.",
            )

        headers = clean_headers(request.headers)
        headers["content-type"] = "application/json"
        url = build_upstream_url(settings.UPSTREAM_BASE_URL, "chat/completions")
        report_header = create_vault_report_header(
            masked_counts=vault.type_counts,
            degraded=degraded,
            gemma_used=gemma_used,
            slm_chunks=slm_chunks,
        )

        client = get_httpx_client()
        try:
            req = client.build_request("POST", url, headers=headers, content=masked_body)
            upstream_resp = await client.send(req, stream=True)
            status_code = upstream_resp.status_code

            resp_headers = clean_response_headers(upstream_resp.headers)
            resp_headers["x-vault-report"] = report_header
            if warning_header:
                resp_headers["x-vault-warning"] = warning_header

            res: Response
            if upstream_resp.headers.get("content-type", "").startswith("text/event-stream"):
                model_name = body_json.get("model", "proxy-model")

                async def sem_holding_stream() -> AsyncGenerator[str, None]:
                    # Note: slot_held is NOT checked here — we unconditionally
                    # release because the outer finally already set slot_held=False
                    # to signal it handed ownership to this generator.
                    try:
                        async for chunk in process_sse_stream(
                            upstream_resp, client, vault, model_name
                        ):
                            yield chunk
                    finally:
                        # Always release: this generator now owns the slot.
                        sem.release()
                        ms = round((time.perf_counter() - t0) * 1000, 2)
                        logger.info(
                            json.dumps(
                                {
                                    "request_id": req_id,
                                    "status": status_code,
                                    "milliseconds": ms,
                                    "counts": counts,
                                    "degraded": degraded,
                                    "strict": settings.STRICT_MODE,
                                }
                            )
                        )
                        record_request_metrics(
                            ms / 1000.0,
                            sum(counts.values()),
                            degraded,
                            circuit_breaker.state,
                        )

                # Transfer slot ownership to the generator; clear slot_held so
                # the outer finally does NOT double-release.
                slot_held = False
                res = StreamingResponse(
                    sem_holding_stream(),
                    status_code=upstream_resp.status_code,
                    headers=resp_headers,
                    media_type="text/event-stream",
                )
                return res

            else:
                content = await upstream_resp.aread()
                await upstream_resp.aclose()

                try:
                    resp_json = json.loads(content.decode("utf-8"))
                    restored_json = restore_json_payload(resp_json, vault)
                    restored_content = json.dumps(restored_json).encode("utf-8")
                except Exception:
                    restored_content = content

                res = Response(
                    content=restored_content,
                    status_code=upstream_resp.status_code,
                    headers=resp_headers,
                    media_type=upstream_resp.headers.get("content-type"),
                )
        except Exception as e:
            logger.error(f"Error in proxy server: {type(e).__name__}")
            status_code = 503
            raise HTTPException(
                status_code=503,
                detail="VaultProxy fail-closed: Upstream connection error or internal failure.",
            )

        ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            json.dumps(
                {
                    "request_id": req_id,
                    "status": status_code,
                    "milliseconds": ms,
                    "counts": counts,
                    "degraded": degraded,
                    "strict": settings.STRICT_MODE,
                }
            )
        )
        record_request_metrics(
            ms / 1000.0, sum(counts.values()), degraded, circuit_breaker.state
        )
        return res
    finally:
        if slot_held:
            sem.release()
            slot_held = False



def main() -> None:
    from vaultproxy.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
