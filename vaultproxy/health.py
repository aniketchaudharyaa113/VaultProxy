import hmac
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from vaultproxy.config import settings

router = APIRouter()

LAST_MASKED_REQUEST: dict[str, Any] = {}


def is_authenticated_request(request: Request) -> bool:
    if not settings.VAULT_AUTH_TOKEN:
        return True
    auth_header = request.headers.get("authorization")
    if not auth_header:
        return False
    parts = auth_header.split(maxsplit=1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    token = parts[1].strip()
    return hmac.compare_digest(token.encode("utf-8"), settings.VAULT_AUTH_TOKEN.encode("utf-8"))


@router.get("/health")
@router.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, Any]:
    from vaultproxy.gemma_layer import (
        LAST_SLM_LATENCY_MS,
        LAST_SLM_MODEL_NAME,
        circuit_breaker,
    )

    status_val = "ready" if circuit_breaker.state != "OPEN" else "degraded"
    if settings.VAULT_AUTH_TOKEN:
        if not is_authenticated_request(request):
            return {"status": status_val}


    return {
        "status": status_val,
        "slm_backend": settings.GEMMA_BACKEND,
        "slm_model": LAST_SLM_MODEL_NAME or settings.GEMMA_MODEL,
        "slm_latency_ms": LAST_SLM_LATENCY_MS,
        "circuit_breaker": circuit_breaker.state,
        "strict_mode": settings.STRICT_MODE,
        "profile": settings.VAULT_PROFILE,
    }


@router.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@router.get("/demo/last")
async def demo_last(request: Request) -> dict[str, Any]:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")
    if settings.VAULT_AUTH_TOKEN and not is_authenticated_request(request):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid API key provided.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )
    return LAST_MASKED_REQUEST


@router.get("/demo", response_class=HTMLResponse)
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
