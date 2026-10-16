import argparse
import asyncio

import uvicorn
from fastapi import FastAPI

app = FastAPI()
DELAY_SECONDS = 2.0

@app.get("/api/tags")
async def get_tags():
    return {"models": [{"name": "gemma4:e2b"}]}

@app.post("/api/chat")
async def chat_endpoint(request_data: dict):
    if DELAY_SECONDS > 0:
        await asyncio.sleep(DELAY_SECONDS)
    content = '{"entities": [{"type": "PERSON", "text": "Rajesh Sharma"}]}'
    return {"message": {"role": "assistant", "content": content}}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock Ollama Server")
    parser.add_argument("--port", type=int, default=11434, help="Port to run on")
    parser.add_argument("--delay", type=float, default=2.0, help="Response delay in seconds")
    args = parser.parse_args()

    DELAY_SECONDS = args.delay
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="error")
