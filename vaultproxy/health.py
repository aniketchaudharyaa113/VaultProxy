import os
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse

from vaultproxy.config import settings

router = APIRouter()

LAST_MASKED_REQUEST: dict[str, Any] = {}


@router.get("/health")
@router.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
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
        "profile": settings.VAULT_PROFILE,
    }


@router.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@router.get("/demo/last")
async def demo_last() -> dict[str, Any]:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode disabled.")
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
