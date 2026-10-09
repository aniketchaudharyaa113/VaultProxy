import asyncio
import json
import sys
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Mock Upstream OpenAI API")


def extract_last_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Extract text parts
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                return "".join(text_parts)
    return ""


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    model = body.get("model", "mock-model")

    # Print exact text received ("what the cloud saw")
    print(
        "\n--- [MOCK UPSTREAM RECEIVED REQUEST] ---",
        file=sys.stderr,
        flush=True,
    )
    print(json.dumps(body, indent=2), file=sys.stderr, flush=True)
    print("----------------------------------------\n", file=sys.stderr, flush=True)

    last_text = extract_last_user_message(messages)

    if not stream:
        resp = {
            "id": "chatcmpl-mock123",
            "object": "chat.completion",
            "created": 1700000000,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": last_text,
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        return JSONResponse(content=resp)

    # Stream mode: SSE chunks of 3-5 chars
    async def sse_generator():
        chunk_size = 4
        for i in range(0, len(last_text), chunk_size):
            piece = last_text[i : i + chunk_size]
            chunk_data = {
                "id": "chatcmpl-mock123",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": piece},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk_data)}\n\n"
            await asyncio.sleep(0.01)

        # Final choice chunk with finish_reason
        final_chunk = {
            "id": "chatcmpl-mock123",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
