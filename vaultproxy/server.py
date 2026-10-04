import logging
from typing import Dict, Any
import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from vaultproxy.config import settings

# Configure basic logging - NEVER log raw prompts or values
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vaultproxy")

app = FastAPI(title="VaultProxy")

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
async def health():
    return {"status": "ok"}


def clean_headers(request_headers: Request.headers) -> Dict[str, str]:
    headers = {}
    for key, value in request_headers.items():
        if key.lower() not in HOP_BY_HOP_HEADERS:
            headers[key] = value
    if settings.UPSTREAM_API_KEY:
        headers["authorization"] = f"Bearer {settings.UPSTREAM_API_KEY}"
    return headers


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.body()
        headers = clean_headers(request.headers)
        url = f"{settings.UPSTREAM_BASE_URL.rstrip('/')}/v1/chat/completions"

        client = httpx.AsyncClient(timeout=60.0)

        # Forward request to upstream
        req = client.build_request("POST", url, headers=headers, content=body)
        upstream_resp = await client.send(req, stream=True)

        if upstream_resp.headers.get("content-type", "").startswith(
            "text/event-stream"
        ):

            async def stream_wrapper():
                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        yield chunk
                finally:
                    await upstream_resp.aclose()
                    await client.aclose()

            resp_headers = {
                k: v
                for k, v in upstream_resp.headers.items()
                if k.lower() not in HOP_BY_HOP_HEADERS
            }
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
            resp_headers = {
                k: v
                for k, v in upstream_resp.headers.items()
                if k.lower() not in HOP_BY_HOP_HEADERS
            }
            return Response(
                content=content,
                status_code=upstream_resp.status_code,
                headers=resp_headers,
                media_type=upstream_resp.headers.get("content-type"),
            )

    except Exception as e:
        logger.error(f"Error in proxy server: {type(e).__name__}")
        raise HTTPException(
            status_code=503,
            detail="VaultProxy fail-closed: Upstream connection error or internal masking failure.",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
