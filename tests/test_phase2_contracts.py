import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from vaultproxy.config import settings
from vaultproxy.detectors import Span
from vaultproxy.gemma_layer import GemmaLayerError
from vaultproxy.masking import (
    SLM_MAX_CHUNKS,
    MaskingEngine,
    is_candidate_for_slm,
)
from vaultproxy.restore import (
    StreamRestorer,
    process_sse_stream,
    restore_json_text,
    restore_text,
)
from vaultproxy.server import app
from vaultproxy.vault import RequestVault


@pytest.fixture
def client():
    return TestClient(app)


# -------------------------------------------------------------------
# 2a. Structural Allowlist Test
# -------------------------------------------------------------------
def test_allowlist_comprehensive_scanning(client):
    fake_pan = "ABCPB1234F"
    fake_aadhaar = "367598341203"
    fake_mobile = "9876543210"

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": [{"message": {"role": "assistant", "content": "Ok"}}]}).encode("utf-8"),
    )

    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": f"My phone is {fake_mobile}"}
        ],
        "metadata": {
            "id": fake_pan,
            "type": fake_aadhaar,
            "mode": fake_mobile,
        },
        "user": fake_pan,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": f"Lookup PAN {fake_pan} and Aadhaar {fake_aadhaar}",
                    "parameters": {
                        "properties": {
                            "id": {"type": "string", "description": fake_pan},
                            "type": {"type": "string", "description": fake_aadhaar},
                            "object": {"type": "string", "description": fake_mobile},
                            "mode": {"type": "string", "description": fake_pan},
                            "role": {"type": "string", "description": fake_aadhaar},
                        }
                    },
                },
            }
        ],
    }

    with patch.object(settings, "GEMMA_BACKEND", "off"), patch.object(settings, "VAULT_PROFILE", "production"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            resp = client.post("/v1/chat/completions", json=payload)
            assert resp.status_code == 200

            sent_req = mock_send.call_args[0][0]
            sent_body = json.loads(sent_req.content.decode("utf-8"))

            assert sent_body["model"] == "gpt-4o"
            assert sent_body["messages"][1]["role"] == "user"

            # Assert NONE of the raw PII strings reach upstream
            body_str = json.dumps(sent_body)
            assert fake_pan not in body_str
            assert fake_aadhaar not in body_str
            assert fake_mobile not in body_str
            assert "[PAN_" in body_str
            assert "[AADHAAR_" in body_str
            assert "[MOBILE_" in body_str


# -------------------------------------------------------------------
# 2b & 4. SLM Candidate Filter, One Call, Chunking & Boundaries
# -------------------------------------------------------------------
def test_slm_candidate_filter_and_chunking():
    import anyio

    # Candidate filter rules
    assert is_candidate_for_slm("abc") is False  # < 4 chars
    assert is_candidate_for_slm("12345") is False  # no letters
    assert is_candidate_for_slm("0123456789abcdef0123456789abcdef") is False  # hex
    assert is_candidate_for_slm("QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=") is False  # base64
    assert is_candidate_for_slm("This is a valid prompt string for SLM.") is True

    async def _test():
        vault = RequestVault()
        engine = MaskingEngine(vault)

        # 40 string fields + 20,000 char tools list (within 4 chunks of 6000 chars)
        large_tools = [
            {"type": "function", "function": {"name": f"fn_{i}", "description": "Detailed tool description with words " * 15}}
            for i in range(32)
        ]
        payload = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Test prompt text"}],
            "tools": large_tools,
        }

        with patch("vaultproxy.masking.run_gemma_detection", new_callable=AsyncMock) as mock_gemma:
            mock_gemma.return_value = ([], False, True)

            # Execution under chunk limit (requires ~4 chunks <= SLM_MAX_CHUNKS)
            res_payload, degraded, gemma_used, slm_chunks = await engine.mask_payload(payload)
            assert mock_gemma.call_count <= SLM_MAX_CHUNKS
            assert degraded is False
            assert gemma_used is True
            assert slm_chunks > 0

        # Test exceeding max chunks (>4 chunks)
        huge_tools = [
            {"type": "function", "function": {"name": f"fn_{i}", "description": "Exceeding chunk text content with words " * 50}}
            for i in range(50)
        ]
        huge_payload = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Test text"}],
            "tools": huge_tools,
        }

        with patch("vaultproxy.masking.run_gemma_detection", new_callable=AsyncMock) as mock_gemma:
            mock_gemma.return_value = ([], False, True)
            with patch.object(settings, "STRICT_MODE", False):
                _, degraded, _, _ = await engine.mask_payload(huge_payload)
                assert degraded is True

            with patch.object(settings, "STRICT_MODE", True):
                with pytest.raises(GemmaLayerError):
                    await engine.mask_payload(huge_payload)

    anyio.run(_test)


def test_slm_chunk_boundary_cross_detection():
    """P3 straddle test: prove a full name straddling chunk boundary is detected as ONE complete span."""
    import anyio

    async def _test():
        vault = RequestVault()
        engine = MaskingEngine(vault)

        # Patch small chunk size and overlap
        small_chunk_size = 50
        small_overlap = 20

        # Create text where "Rajesh Sharma" straddles index 50
        # "Context padding text to fill up first chunk. Raje" is 47 chars
        # "sh Sharma" starts at index 47. Index 50 cuts right through "Rajesh" ("Raje" | "sh Sharma")
        full_name = "Rajesh Sharma"
        part1 = "Context padding text to fill up first chunk. Raje"
        part2 = "sh Sharma and more text after name."
        full_text = part1 + part2
        assert full_name in full_text
        name_idx = full_text.find(full_name)
        assert name_idx < 50 < name_idx + len(full_name)  # Confirms straddling boundary

        payload = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": full_text}],
        }

        async def mock_chunk_detect(chunk_text: str):
            spans = []
            idx = chunk_text.find(full_name)
            print(f"MOCK DETECT chunk_text={chunk_text!r} -> idx={idx}")
            if idx != -1:
                spans.append(Span(start=idx, end=idx + len(full_name), type="NAME", source="gemma", score=1.0))
            return spans, False, True

        with patch("vaultproxy.masking.SLM_CHUNK_CHARS", small_chunk_size), \
             patch("vaultproxy.masking.SLM_OVERLAP_CHARS", small_overlap), \
             patch("vaultproxy.masking.run_gemma_detection", side_effect=mock_chunk_detect):

            res_payload, degraded, gemma_used, slm_chunks = await engine.mask_payload(payload)
            masked_text = res_payload["messages"][1]["content"]

            assert full_name not in masked_text
            assert "[NAME_1]" in masked_text
            assert slm_chunks >= 2
            # Verify exact vault token maps to exact full span text
            token_val = vault.token_to_value["[NAME_1]"]
            assert token_val == full_name

    anyio.run(_test)


# -------------------------------------------------------------------
# 2c. Streaming Parallel Tools, Errors & Cancellation Exit Paths
# -------------------------------------------------------------------
def test_streaming_parallel_tools_resiliency_exit_paths(client):
    chunk1 = json.dumps({"choices": [
        {"index": 0, "delta": {
            "tool_calls": [
                {"index": 0, "function": {"arguments": '{"phone": "'}},
                {"index": 1, "function": {"arguments": '{"pan": "'}},
            ]
        }}
    ]})
    chunk2 = json.dumps({"choices": [
        {"index": 0, "delta": {
            "tool_calls": [
                {"index": 0, "function": {"arguments": '[MOBILE_1]"}'}},
                {"index": 1, "function": {"arguments": '[PAN_1]"}'}},
            ]
        }}
    ]})

    sse_chunks = [": keepalive\n\n", f"data: {chunk1}\n\n", f"data: {chunk2}\n\n", "data: [DONE]\n\n"]
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(sse_chunks).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Phone 9876543210 and PAN ABCPB1234F"}],
                "stream": True,
            }
            resp = client.post("/v1/chat/completions", json=payload)
            assert resp.status_code == 200
            assert "9876543210" in resp.text
            assert "ABCPB1234F" in resp.text

    # Mid-stream error & disconnect exit paths test
    import anyio

    async def _test_generator_exit():
        vault = RequestVault()
        vault.get_or_create_token("9876543210", "MOBILE")

        async def mock_stream_bytes():
            yield f'data: {json.dumps({"choices": [{"index": 0, "delta": {"content": "Partial token [MOB"}}]})}\n\n'.encode()
            raise httpx.ReadError("Mid-stream disconnect")

        mock_upstream = AsyncMock()
        mock_upstream.headers = {"content-type": "text/event-stream"}
        mock_upstream.status_code = 200
        mock_upstream.aiter_bytes = mock_stream_bytes
        mock_upstream.aclose = AsyncMock()
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()

        gen = process_sse_stream(mock_upstream, mock_client, vault, "gpt-4o")
        items = []
        async for item in gen:
            items.append(item)

        assert len(items) >= 2
        assert any("stream_error" in item for item in items)

        # Verify exit path cleanup: upstream response closed, client not closed (B2 fix)
        mock_upstream.aclose.assert_called_once()
        mock_client.aclose.assert_not_called()

    anyio.run(_test_generator_exit)



# -------------------------------------------------------------------
# 2d. Official OpenAI Python SDK Contract Test Suite
# -------------------------------------------------------------------
def test_openai_sdk_full_contract_suite(client):
    complex_secret = 'user"name\nwithnewline\\andbackslash'
    pan_val = "ABCPB1234F"

    async def mock_gemma_detect(text: str):
        spans = []
        idx = text.find(complex_secret)
        if idx != -1:
            spans.append(Span(start=idx, end=idx + len(complex_secret), type="SECRET", source="gemma", score=1.0))
        return spans, False, True

    class LocalTransport(httpx.BaseTransport):
        def handle_request(self, request):
            req_bytes = request.content
            req_json = json.loads(req_bytes.decode("utf-8")) if req_bytes else {}
            is_stream = req_json.get("stream", False)
            response_format = req_json.get("response_format", {})
            n_choices = req_json.get("n", 1)

            if is_stream:
                chunk1 = json.dumps({"choices": [
                    {"index": i, "delta": {"content": "Found [PAN_1] in choice "}} for i in range(n_choices)
                ]})
                chunk2 = json.dumps({"choices": [
                    {"index": i, "delta": {"content": f"{i}"}} for i in range(n_choices)
                ]})
                sse_data = f"data: {chunk1}\n\n" f"data: {chunk2}\n\n" "data: [DONE]\n\n"
                mock_upstream = httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=sse_data.encode("utf-8"),
                )
            else:
                choices = []
                for i in range(n_choices):
                    if response_format.get("type") == "json_object":
                        content_val = '{"secret": "[SECRET_1]", "pan": "[PAN_1]"}'
                    else:
                        content_val = "Found [PAN_1]"

                    choices.append({
                        "index": i,
                        "message": {
                            "role": "assistant",
                            "content": content_val,
                            "tool_calls": [{
                                "id": f"call_{i}",
                                "type": "function",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"pan": "[PAN_1]", "secret": "[SECRET_1]"}'
                                }
                            }]
                        },
                        "finish_reason": "stop"
                    })

                resp_body = {
                    "id": "chatcmpl-123",
                    "object": "chat.completion",
                    "created": 1700000000,
                    "model": "gpt-4o",
                    "choices": choices
                }
                mock_upstream = httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    content=json.dumps(resp_body).encode("utf-8")
                )

            with patch("vaultproxy.masking.run_gemma_detection", side_effect=mock_gemma_detect):
                with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
                    mock_send.return_value = mock_upstream
                    fastapi_resp = client.post(request.url.path, content=req_bytes, headers=dict(request.headers))
                    return httpx.Response(
                        status_code=fastapi_resp.status_code,
                        headers=fastapi_resp.headers,
                        content=fastapi_resp.content,
                    )

    oai_client = OpenAI(api_key="test-key", base_url="http://test/v1", http_client=httpx.Client(transport=LocalTransport()))

    # 1. Normal chat completion with escaped secret value
    comp = oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"PAN is {pan_val} and secret is {complex_secret}"}]
    )
    assert pan_val in comp.choices[0].message.content
    parsed_args = json.loads(comp.choices[0].message.tool_calls[0].function.arguments)
    assert parsed_args["pan"] == pan_val
    assert parsed_args["secret"] == complex_secret

    # 2. Streaming completion
    stream_comp = oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"PAN is {pan_val}"}],
        stream=True
    )
    stream_chunks = [c.choices[0].delta.content for c in stream_comp if c.choices and c.choices[0].delta.content]
    full_streamed = "".join(stream_chunks)
    assert pan_val in full_streamed

    # 3. JSON mode with quotes, newline, backslash in restored value
    json_comp = oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"PAN is {pan_val} and secret is {complex_secret}"}],
        response_format={"type": "json_object"}
    )
    parsed_json_body = json.loads(json_comp.choices[0].message.content)
    assert parsed_json_body["pan"] == pan_val
    assert parsed_json_body["secret"] == complex_secret

    # 4. Multi-choice n=2
    n2_comp = oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"PAN is {pan_val}"}],
        n=2
    )
    assert len(n2_comp.choices) == 2
    assert pan_val in n2_comp.choices[0].message.content
    assert pan_val in n2_comp.choices[1].message.content


# -------------------------------------------------------------------
# 2e. JSON Escaping for Quotes, Backslashes, and Newlines
# -------------------------------------------------------------------
def test_json_escaping_quotes_backslashes_newlines():
    vault = RequestVault()
    secret = 'user"name\nwithnewline\\andbackslash'
    vault.get_or_create_token(secret, "SECRET")

    # Non-stream JSON argument restoration
    raw_json_arg = '{"secret": "[SECRET_1]"}'
    restored = restore_json_text(raw_json_arg, vault)
    parsed = json.loads(restored)
    assert parsed["secret"] == secret

    # Stream restorer JSON escaping
    restorer = StreamRestorer(vault, json_escape=True)
    part1 = restorer.feed('{"secret": "[SEC')
    part2 = restorer.feed('RET_1]"}')
    flushed = restorer.flush()

    full_restored = part1 + part2 + flushed
    parsed_stream = json.loads(full_restored)
    assert parsed_stream["secret"] == secret


# -------------------------------------------------------------------
# 2f. Default Request Universal Deep Scope (H7)
# -------------------------------------------------------------------
def test_default_request_deep_scope(client):
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": []}).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"), patch.object(settings, "VAULT_PROFILE", "development"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "My phone is 9876543210"}],
                "metadata": {"user_id": "ABCPB1234F"}
            }

            resp = client.post("/v1/chat/completions", json=payload)
            assert resp.status_code == 200

            sent_req = mock_send.call_args[0][0]
            sent_body = json.loads(sent_req.content.decode("utf-8"))

            # Deep scope applies universally: metadata is masked
            assert sent_body["messages"][1]["content"] == "My phone is [MOBILE_1]"
            assert sent_body["metadata"]["user_id"] == "[PAN_1]"


# -------------------------------------------------------------------
# 2g. Embeddings Warning Header & Token-ID Input
# -------------------------------------------------------------------
def test_embeddings_warning_and_token_ids(client):
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"data": [{"embedding": [0.1]}]}).encode("utf-8")
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp

            resp_str = client.post("/v1/embeddings", json={"model": "text-emb", "input": "Hello"})
            assert resp_str.status_code == 200
            assert "Embeddings of masked text are not comparable across requests" in resp_str.headers.get("x-vault-warning", "")

            with patch.object(settings, "VAULT_PROFILE", "development"):
                resp_dev = client.post("/v1/embeddings", json={"model": "text-emb", "input": [101, 2045]})
                assert resp_dev.status_code == 200
                assert "Token ID embeddings input uninspected" in resp_dev.headers.get("x-vault-warning", "")

            with patch.object(settings, "VAULT_PROFILE", "production"):
                resp_prod = client.post("/v1/embeddings", json={"model": "text-emb", "input": [101, 2045]})
                assert resp_prod.status_code == 400
                assert "Token ID embeddings input cannot be inspected" in resp_prod.json()["error"]["message"]


# -------------------------------------------------------------------
# Additional Coverage Boost Tests for Targets (Item 3)
# -------------------------------------------------------------------
def test_vault_token_reuse_and_clearing_behavior():
    vault = RequestVault()
    assert vault.mask_text("", []) == ""
    token1 = vault.get_or_create_token("ABCPB1234F", "PAN")
    token2 = vault.get_or_create_token("ABCPB1234F", "PAN")
    assert token1 == token2 == "[PAN_1]"
    vault.clear()
    assert len(vault.value_to_token) == 0


def test_restore_and_server_edge_cases(client):
    # Test restore_text empty inputs
    vault = RequestVault()
    assert restore_text("", vault) == ""
    assert restore_text("Hello", vault) == "Hello"
    assert restore_json_text("", vault) == ""

    # Test server model list endpoint failure
    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
        resp = client.get("/v1/models")
        assert resp.status_code == 503

    # Test server production route filter
    with patch.object(settings, "VAULT_PROFILE", "production"):
        resp = client.get("/demo/console")
        assert resp.status_code == 404

    # Test server non-text policy block
    with patch.object(settings, "NON_TEXT_POLICY", "block"):
        resp = client.post("/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "http://img"}}]}]
        })
        assert resp.status_code == 400


def test_restore_sse_legacy_function_calls_and_partial_tokens_behavior():
    import anyio

    async def _test():
        vault = RequestVault()
        vault.get_or_create_token("9876543210", "MOBILE")

        # 1. Legacy function_call streaming delta
        # 2. Incomplete token before [DONE] triggering flushed_chunks
        # 3. Trailing EOF line_buffer without trailing newline
        chunk_func = json.dumps({
            "choices": [{
                "index": 0,
                "delta": {
                    "function_call": {"name": "func", "arguments": '{"num": "[MOB'}
                }
            }]
        })
        chunk_func_end = json.dumps({
            "choices": [{
                "index": 0,
                "delta": {
                    "function_call": {"arguments": 'ILE_1]"}'}
                }
            }]
        })

        sse_stream = f"data: {chunk_func}\n\ndata: {chunk_func_end}\n\nevent: ping\n\ndata: invalid-json-string\n\ndata: [DONE]"

        async def mock_stream_bytes():
            yield sse_stream.encode("utf-8")

        mock_upstream = AsyncMock()
        mock_upstream.headers = {"content-type": "text/event-stream"}
        mock_upstream.status_code = 200
        mock_upstream.aiter_bytes = mock_stream_bytes
        mock_upstream.aclose = AsyncMock()
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()

        gen = process_sse_stream(mock_upstream, mock_client, vault, "gpt-4o")
        results = [line async for line in gen]
        full_res = "".join(results)

        assert "9876543210" in full_res
        assert "invalid-json-string" in full_res
        assert "[DONE]" in full_res

        # Test flushed_chunks when token is left in restorer at [DONE]
        vault2 = RequestVault()
        vault2.get_or_create_token("9876543210", "MOBILE")
        chunk_partial = json.dumps({
            "choices": [{
                "index": 0,
                "delta": {"content": "Text with partial [MOB"}
            }]
        })
        sse_partial = f"data: {chunk_partial}\n\ndata: [DONE]\n\n"

        async def mock_stream_partial():
            yield sse_partial.encode("utf-8")

        mock_upstream2 = AsyncMock()
        mock_upstream2.headers = {"content-type": "text/event-stream"}
        mock_upstream2.status_code = 200
        mock_upstream2.aiter_bytes = mock_stream_partial
        mock_upstream2.aclose = AsyncMock()

        gen2 = process_sse_stream(mock_upstream2, mock_client, vault2, "gpt-4o")
        res2 = [l async for l in gen2]
        full2 = "".join(res2)
        assert "[MOB" in full2

    anyio.run(_test)

