import json
import re
from collections.abc import AsyncGenerator, Callable
from typing import Any

from vaultproxy.vault import RequestVault


def _make_repl(v: str) -> Callable[[re.Match[str]], str]:
    return lambda _: v


def restore_text(text: str, vault: RequestVault) -> str:
    """Restore tokens in text using vault (case-insensitive token matching)."""
    if not text or not vault.token_to_value:
        return text

    res = text
    sorted_tokens = sorted(vault.token_to_value.keys(), key=len, reverse=True)
    for token in sorted_tokens:
        val = vault.token_to_value[token]
        pattern = re.compile(re.escape(token), re.IGNORECASE)
        res = pattern.sub(_make_repl(val), res)
    return res


def restore_json_text(text: str, vault: RequestVault) -> str:
    """Restore tokens inside a JSON string value, properly JSON-escaping restored values."""
    if not text or not vault.token_to_value:
        return text

    res = text
    sorted_tokens = sorted(vault.token_to_value.keys(), key=len, reverse=True)
    for token in sorted_tokens:
        val = vault.token_to_value[token]
        escaped_val = json.dumps(val)[1:-1]
        pattern = re.compile(re.escape(token), re.IGNORECASE)
        res = pattern.sub(_make_repl(escaped_val), res)
    return res




class StreamRestorer:
    """Buffers streaming token output to restore tokens split across SSE chunks."""

    def __init__(
        self,
        vault: RequestVault,
        json_escape: bool = False,
        trace: Callable[[str, str, str], None] | None = None,
    ):
        self.vault = vault
        self.json_escape = json_escape
        self.buffer = ""
        self.trace = trace

    def _restore(self, text: str) -> str:
        if self.json_escape:
            return restore_json_text(text, self.vault)
        return restore_text(text, self.vault)

    def feed(self, text: str) -> str:
        self.buffer += text
        last_bracket = self.buffer.rfind("[")
        if last_bracket != -1:
            closing_bracket = self.buffer.find("]", last_bracket)
            if closing_bracket == -1:
                held_len = len(self.buffer) - last_bracket
                if held_len <= 24:
                    to_process = self.buffer[:last_bracket]
                    self.buffer = self.buffer[last_bracket:]
                    emitted = self._restore(to_process)
                    if self.trace:
                        self.trace(text, self.buffer, emitted)
                    return emitted

        to_process = self.buffer
        self.buffer = ""
        emitted = self._restore(to_process)
        if self.trace:
            self.trace(text, self.buffer, emitted)
        return emitted

    def flush(self) -> str:
        to_process = self.buffer
        self.buffer = ""
        emitted = self._restore(to_process)
        if self.trace:
            self.trace("", self.buffer, emitted)
        return emitted


async def process_sse_stream(
    upstream_resp: Any, client: Any, vault: RequestVault, model_name: str
) -> AsyncGenerator[str, None]:
    restorers: dict[tuple[int, int, str], StreamRestorer] = {}
    line_buffer = ""

    def get_restorer(
        choice_idx: int, tool_idx: int, field: str, json_escape: bool = False
    ) -> StreamRestorer:
        key = (choice_idx, tool_idx, field)
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
                            for (c_idx, _, field), val in flushed_chunks:
                                delta_dict: dict[str, Any] = (
                                    {"content": val} if field == "content" else {}
                                )
                                final_chunk = {
                                    "id": "chatcmpl-restored",
                                    "object": "chat.completion.chunk",
                                    "created": 1700000000,
                                    "model": model_name,
                                    "choices": [
                                        {
                                            "index": c_idx,
                                            "delta": delta_dict,
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
                                    if "content" in delta and isinstance(
                                        delta["content"], str
                                    ):
                                        r = get_restorer(
                                            c_idx, 0, "content", json_escape=False
                                        )
                                        restored_part = r.feed(delta["content"])
                                        delta["content"] = restored_part
                                    if "tool_calls" in delta and isinstance(
                                        delta["tool_calls"], list
                                    ):
                                        for t_idx, tc in enumerate(delta["tool_calls"]):
                                            tc_idx = tc.get("index", t_idx)
                                            func = tc.get("function", {})
                                            if "arguments" in func and isinstance(
                                                func["arguments"], str
                                            ):
                                                r = get_restorer(
                                                    c_idx,
                                                    tc_idx,
                                                    "arguments",
                                                    json_escape=True,
                                                )
                                                func["arguments"] = r.feed(
                                                    func["arguments"]
                                                )
                                    if "function_call" in delta and isinstance(
                                        delta["function_call"], dict
                                    ):
                                        fc = delta["function_call"]
                                        if "arguments" in fc and isinstance(
                                            fc["arguments"], str
                                        ):
                                            r = get_restorer(
                                                c_idx,
                                                0,
                                                "function_call_arguments",
                                                json_escape=True,
                                            )
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
                        for (c_idx, _, field), val in flushed_chunks:
                            delta_dict = {"content": val} if field == "content" else {}
                            final_chunk = {
                                "id": "chatcmpl-restored",
                                "object": "chat.completion.chunk",
                                "created": 1700000000,
                                "model": model_name,
                                "choices": [
                                    {
                                        "index": c_idx,
                                        "delta": delta_dict,
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(final_chunk)}\n\n"
                    yield "data: [DONE]\n\n"

    except Exception as exc:
        flushed_chunks = []
        for key, r in restorers.items():
            flushed_val = r.flush()
            if flushed_val:
                flushed_chunks.append((key, flushed_val))
        if flushed_chunks:
            for (c_idx, _, field), val in flushed_chunks:
                flushed_delta: dict[str, Any] = (
                    {"content": val} if field == "content" else {}
                )
                final_chunk = {
                    "id": "chatcmpl-restored",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": model_name,
                    "choices": [
                        {
                            "index": c_idx,
                            "delta": flushed_delta,
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
        yield f"data: {json.dumps({'error': {'message': f'Stream error or timeout: {type(exc).__name__}', 'type': 'stream_error'}})}\n\n"

    finally:
        for r in restorers.values():
            r.flush()
        await upstream_resp.aclose()
        await client.aclose()
