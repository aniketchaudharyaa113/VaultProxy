import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from vaultproxy.config import settings
from vaultproxy.detectors import Span
from vaultproxy.gemma_layer import GemmaLayerError
from vaultproxy.masking import SLM_MAX_COMBINED_CHARS, MaskingEngine
from vaultproxy.restore import restore_json_text
from vaultproxy.server import app
from vaultproxy.vault import RequestVault


@pytest.fixture
def client():
    return TestClient(app)


def test_restorer_json_escaping():
    vault = RequestVault()
    secret = 'user"name\nwithnewline\\andbackslash'
    vault.get_or_create_token(secret, "PAN")
    raw_text = '{"pan": "[PAN_1]"}'
    restored = restore_json_text(raw_text, vault)
    parsed = json.loads(restored)
    assert parsed["pan"] == secret


def test_structural_allowlist_scanning(client):
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": [{"message": {"role": "assistant", "content": "Ok"}}]}).encode("utf-8"),
    )

    fake_pan = "ABCPB1234F"
    fake_aadhaar = "367598341203"
    fake_mobile = "9876543210"

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
                    "description": f"Lookup PAN {fake_pan}",
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

            # Ensure metadata, user, and tool schema strings were ALL scanned and masked
            assert fake_pan not in json.dumps(sent_body)
            assert fake_aadhaar not in json.dumps(sent_body)
            assert fake_mobile not in json.dumps(sent_body)
            assert "[PAN_" in json.dumps(sent_body)
            assert "[AADHAAR_" in json.dumps(sent_body)
            assert "[MOBILE_" in json.dumps(sent_body)


def test_slm_layer_single_call_and_cap():
    import anyio

    async def _test():
        vault = RequestVault()
        engine = MaskingEngine(vault)

        # 40 string fields + 20,000 char tools list (using prose text with spaces so it is not mistaken for base64)
        large_tools = [{"type": "function", "function": {"name": f"fn_{i}", "description": "This is a detailed description of tool with spaces " * 15}} for i in range(40)]

        payload = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Test text"}],
            "tools": large_tools,
        }

        with patch("vaultproxy.masking.run_gemma_detection", new_callable=AsyncMock) as mock_gemma:
            mock_gemma.return_value = ([], False, True)

            # 1 call under cap (approx 21,000 chars <= SLM_MAX_COMBINED_CHARS = 50000)
            res_payload, degraded, gemma_used = await engine.mask_payload(payload, scope="deep")
            assert mock_gemma.call_count == 1
            assert degraded is False
            assert gemma_used is True

        # Now test when cap is exceeded (>50000 chars)
        huge_tools = [{"type": "function", "function": {"name": f"fn_{i}", "description": "Exceeding cap text content with spaces " * 50}} for i in range(50)]
        huge_payload = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Test text"}],
            "tools": huge_tools,
        }

        with patch("vaultproxy.masking.run_gemma_detection", new_callable=AsyncMock) as mock_gemma:
            mock_gemma.return_value = ([], False, True)
            with patch.object(settings, "STRICT_MODE", False):
                _, degraded, _ = await engine.mask_payload(huge_payload, scope="deep")
                assert degraded is True

            with patch.object(settings, "STRICT_MODE", True):
                with pytest.raises(GemmaLayerError):
                    await engine.mask_payload(huge_payload, scope="deep")

    anyio.run(_test)


def test_streaming_parallel_tools_and_resiliency(client):
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

    sse_chunks = [f"data: {chunk1}\n\n", f"data: {chunk2}\n\n", "data: [DONE]\n\n"]
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


def test_embeddings_token_ids_and_warning_header(client):
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


def test_default_development_request_unchanged(client):
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": []}).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"), patch.object(settings, "VAULT_PROFILE", "development"), patch.object(settings, "MASK_SCOPE", ""):
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

            assert sent_body["messages"][1]["content"] == "My phone is [MOBILE_1]"
            assert sent_body["metadata"]["user_id"] == "ABCPB1234F"
