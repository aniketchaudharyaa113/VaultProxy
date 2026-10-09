"""End-to-end characterization test suite freezing current VaultProxy server behaviour.

Covers:
- Non-stream request/response
- Streamed response across chunk sizes
- X-Vault-Report headers for both non-stream and stream
- Strict-mode 503 when SLM layer fails
- Non-strict degraded path
- Invalid JSON body
- Missing messages field
- Upstream error status
- Upstream timeout
- Request with assistant tool_calls and image_url part (KNOWN LEAK)
- Non-JSON upstream body fallback
- SSE buffer flush without final newline & flushed token at DONE
- Demo page route
"""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from vaultproxy.config import settings
from vaultproxy.gemma_layer import GemmaLayerError
from vaultproxy.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_e2e_non_stream_request_response(client):
    """Test non-stream chat completion request masking and restoration."""
    upstream_response_json = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Received PAN [PAN_1] and Mobile [MOBILE_1].",
                },
                "finish_reason": "stop",
            }
        ],
    }

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps(upstream_response_json).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "user",
                        "content": "My PAN is ABCPB1234F and mobile is 9876543210.",
                    }
                ],
            }

            response = client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            assert "x-vault-report" in response.headers
            report = json.loads(response.headers["x-vault-report"])
            assert report["masked"]["PAN"] == 1
            assert report["masked"]["MOBILE"] == 1

            body = response.json()
            assert (
                body["choices"][0]["message"]["content"]
                == "Received PAN ABCPB1234F and Mobile 9876543210."
            )

            sent_req = mock_send.call_args[0][0]
            sent_body = json.loads(sent_req.content.decode("utf-8"))
            sent_content = sent_body["messages"][1]["content"]
            assert "[PAN_1]" in sent_content
            assert "[MOBILE_1]" in sent_content
            assert "ABCPB1234F" not in sent_content


def test_e2e_streaming_response_chunks(client):
    """Test SSE streaming response restoration with chunked delivery."""
    sse_lines = [
        'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n',
        ": sse comment\n\n",
        'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"Received [PAN_"}}]}\n\n',
        'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"1]."}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    async def aiter_bytes_mock():
        for line in sse_lines:
            yield line.encode("utf-8")

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
    )
    mock_resp.aiter_bytes = aiter_bytes_mock

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "PAN ABCPB1234F"}],
                "stream": True,
            }

            response = client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            assert "x-vault-report" in response.headers
            assert "text/event-stream" in response.headers["content-type"]

            content = response.text
            assert "data: [DONE]" in content
            assert "ABCPB1234F" in content


def test_e2e_streaming_flushed_token_at_done(client):
    """Test SSE stream flushes held token buffer upon receiving [DONE]."""
    sse_lines = [
        'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"Hold token [PAN_1]"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    async def aiter_bytes_mock():
        for line in sse_lines:
            yield line.encode("utf-8")

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
    )
    mock_resp.aiter_bytes = aiter_bytes_mock

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "PAN ABCPB1234F"}],
                "stream": True,
            }

            response = client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            assert "ABCPB1234F" in response.text


def test_e2e_streaming_buffer_flush_no_newline(client):
    """Test SSE stream buffer line flush when stream ends without trailing newline."""
    async def aiter_bytes_mock():
        yield b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"Hold [PAN_1]"}}]}'
        yield b"\ndata: [DONE]"

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
    )
    mock_resp.aiter_bytes = aiter_bytes_mock

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "PAN ABCPB1234F"}],
                "stream": True,
            }

            response = client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            assert "ABCPB1234F" in response.text


def test_e2e_non_json_upstream_body(client):
    """Test proxy handles non-JSON upstream response bodies gracefully."""
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "text/plain"},
        content=b"Plain non-JSON upstream response",
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            }
            response = client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            assert response.text == "Plain non-JSON upstream response"


def test_e2e_strict_mode_503_on_slm_failure(client):
    """Test strict mode returns 503 and forwards nothing when SLM fails."""
    with patch.object(settings, "STRICT_MODE", True):
        with patch(
            "vaultproxy.vault.run_gemma_detection",
            side_effect=GemmaLayerError("SLM offline"),
        ):
            with patch("httpx.AsyncClient.send") as mock_send:
                payload = {
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "My PAN is ABCPB1234F"}],
                }
                response = client.post("/v1/chat/completions", json=payload)
                assert response.status_code == 503
                assert "VaultProxy fail-closed" in response.json()["detail"]
                mock_send.assert_not_called()


def test_e2e_non_strict_degraded_path(client):
    """Test non-strict mode continues on rules and sets degraded=True when SLM fails."""
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Verified [PAN_1]",
                        }
                    }
                ]
            }
        ).encode("utf-8"),
    )

    with patch.object(settings, "STRICT_MODE", False):
        with patch.object(settings, "GEMMA_BACKEND", "ollama"):
            with patch(
                "httpx.AsyncClient.post",
                side_effect=httpx.TimeoutException("Ollama timeout"),
            ):
                with patch(
                    "httpx.AsyncClient.send", new_callable=AsyncMock
                ) as mock_send:
                    mock_send.return_value = mock_resp

                    payload = {
                        "model": "gpt-4",
                        "messages": [
                            {"role": "user", "content": "My PAN is ABCPB1234F"}
                        ],
                    }
                    response = client.post("/v1/chat/completions", json=payload)
                    assert response.status_code == 200
                    report = json.loads(response.headers["x-vault-report"])
                    assert report["degraded"] is True
                    # Applied H6: gemma_used is False when SLM call fails
                    assert report["gemma_used"] is False


def test_e2e_invalid_json_body(client):
    """Test invalid non-JSON body triggers 503 fail-closed."""
    response = client.post(
        "/v1/chat/completions",
        content="Invalid raw string",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 503
    assert "VaultProxy fail-closed" in response.json()["detail"]


def test_e2e_missing_messages_field(client):
    """Test request without messages field passes through safely."""
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": []}).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {"model": "gpt-4"}
            response = client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            report = json.loads(response.headers["x-vault-report"])
            assert report["masked"] == {}


def test_e2e_upstream_error_status(client):
    """Test proxy passes upstream HTTP error statuses (e.g. 500)."""
    mock_resp = httpx.Response(
        500,
        headers={"content-type": "application/json"},
        content=json.dumps({"error": "Internal upstream error"}).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            }
            response = client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 500
            assert "x-vault-report" in response.headers


def test_e2e_upstream_timeout(client):
    """Test upstream network timeout triggers 503 fail-closed."""
    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch(
            "httpx.AsyncClient.send",
            side_effect=httpx.TimeoutException("Upstream timeout"),
        ):
            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            }
            response = client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 503
            assert "VaultProxy fail-closed" in response.json()["detail"]


def test_e2e_tool_calls_and_image_url_unmasked_leak(client):
    """Updated in Phase 2:
    Assistant tool_calls arguments are now masked under deep masking.
    Non-text parts (image_url) in development profile trigger an X-Vault-Warning header.
    """
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": []}).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"), patch.object(settings, "MASK_SCOPE", "deep"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "lookup_user",
                                    "arguments": '{"pan": "ABCPB1234F"}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "My phone is 9876543210"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "https://example.com/id_card.png"
                                },
                            },
                        ],
                    },
                ],
            }

            response = client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            assert response.headers.get("x-vault-warning") == "Uninspected non-text content present"

            sent_req = mock_send.call_args[0][0]
            sent_body = json.loads(sent_req.content.decode("utf-8"))

            asst_msg = sent_body["messages"][1]
            assert (
                asst_msg["tool_calls"][0]["function"]["arguments"]
                == '{"pan": "[PAN_1]"}'
            )

            user_msg = sent_body["messages"][2]
            assert user_msg["content"][0]["text"] == "My phone is [MOBILE_1]"
            assert (
                user_msg["content"][1]["image_url"]["url"]
                == "https://example.com/id_card.png"
            )



def test_e2e_demo_page_route(client):
    """Test /demo page route."""
    with patch.object(settings, "DEMO_MODE", True):
        resp = client.get("/demo")
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text or "<html" in resp.text
