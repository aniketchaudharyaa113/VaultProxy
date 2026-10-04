import json
import logging
from typing import Dict, Any
import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from vaultproxy.config import settings
from vaultproxy.vault import RequestVault
from vaultproxy.restore import restore_text, StreamRestorer

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
    vault = RequestVault()

    # Mask incoming request (FAIL CLOSED on any masking error)
    try:
        body_bytes = await request.body()
        body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

        if "messages" in body_json and isinstance(body_json["messages"], list):
            body_json["messages"] = vault.mask_messages(body_json["messages"])

        masked_body = json.dumps(body_json).encode("utf-8")
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

    try:
        client = httpx.AsyncClient(timeout=60.0)
        req = client.build_request("POST", url, headers=headers, content=masked_body)
        upstream_resp = await client.send(req, stream=True)

        if upstream_resp.headers.get("content-type", "").startswith(
            "text/event-stream"
        ):

            async def stream_wrapper():
                restorer = StreamRestorer(vault)
                line_buffer = ""

                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        line_buffer += chunk.decode("utf-8", errors="replace")
                        lines = line_buffer.split("\n")
                        line_buffer = lines.pop()  # Keep partial last line in buffer

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

                    # Handle remaining buffer after stream ends
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
