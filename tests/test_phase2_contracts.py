import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from vaultproxy.config import settings
from vaultproxy.restore import StreamRestorer, restore_json_text, restore_text
from vaultproxy.server import app
from vaultproxy.vault import RequestVault


@pytest.fixture
def client():
    return TestClient(app)


def test_restorer_json_escaping():
    vault = RequestVault()
    secret = 'user"name\nwithnewline'
    vault.get_or_create_token(secret, "PAN")
    raw_text = '{"pan": "[PAN_1]"}'
    restored = restore_json_text(raw_text, vault)
    # Valid JSON parsing proves quotes and newlines were safely escaped
    parsed = json.loads(restored)
    assert parsed["pan"] == secret


def test_deep_masking_scope(client):
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": [{"message": {"role": "assistant", "content": "Ok"}}]}).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"), patch.object(settings, "PROFILE", "production"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hello"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "search",
                            "description": "Search user with PAN ABCPB1234F or email test@example.com",
                        },
                    }
                ],
            }

            resp = client.post("/v1/chat/completions", json=payload)
            assert resp.status_code == 200

            sent_req = mock_send.call_args[0][0]
            sent_body = json.loads(sent_req.content.decode("utf-8"))
            tool_desc = sent_body["tools"][0]["function"]["description"]
            assert "[PAN_1]" in tool_desc
            assert "[EMAIL_1]" in tool_desc


def test_non_text_policy_block(client):
    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Check image"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
                ],
            }
        ],
    }

    with patch.object(settings, "PROFILE", "production"):
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 400
        assert "Non-text content" in resp.json()["error"]["message"]


def test_production_route_filtering(client):
    with patch.object(settings, "PROFILE", "production"):
        resp = client.get("/demo")
        assert resp.status_code == 404
        assert "Route not permitted" in resp.json()["error"]["message"]

        health_resp = client.get("/healthz")
        assert health_resp.status_code == 200

        ready_resp = client.get("/readyz")
        assert ready_resp.status_code == 200
        assert ready_resp.json()["profile"] == "production"


def test_production_invalid_body_shape(client):
    with patch.object(settings, "PROFILE", "production"):
        resp = client.post("/v1/chat/completions", json={"model": "gpt-4o"})
        assert resp.status_code == 400
        assert "Invalid request body shape" in resp.json()["error"]["message"]

        resp_emb = client.post("/v1/embeddings", json={"model": "text-embedding-3"})
        assert resp_emb.status_code == 400
        assert "Invalid request body shape for embeddings" in resp_emb.json()["error"]["message"]


def test_embeddings_endpoint_masking(client):
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"data": [{"embedding": [0.1, 0.2]}]}).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp

            payload = {"model": "text-embedding-3", "input": "My email is user@example.com"}
            resp = client.post("/v1/embeddings", json=payload)
            assert resp.status_code == 200
            assert "x-vault-report" in resp.headers

            sent_req_body = json.loads(mock_post.call_args[1]["content"].decode("utf-8"))
            assert sent_req_body["input"] == "My email is [EMAIL_1]"


def test_streaming_n_equals_2_and_tool_calls(client):
    vault = RequestVault()
    t1 = vault.get_or_create_token("9876543210", "MOBILE")

    chunk1 = json.dumps({"choices": [{"index": 0, "delta": {"content": "Call "}}, {"index": 1, "delta": {"content": "Phone is "}}]})
    chunk2 = json.dumps({"choices": [{"index": 0, "delta": {"content": t1}}, {"index": 1, "delta": {"content": t1}}]})
    chunk3 = json.dumps({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"num": "'}}]}}, {"index": 1, "delta": {}}]})
    chunk4 = json.dumps({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": t1 + '"}'}}]}}, {"index": 1, "delta": {}}]})

    sse_chunks = [
        ": keep-alive\n\n",
        f"data: {chunk1}\n\n",
        f"data: {chunk2}\n\n",
        f"data: {chunk3}\n\n",
        f"data: {chunk4}\n\n",
        "data: [DONE]\n\n",
    ]

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(sse_chunks).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "My phone is 9876543210"}], "stream": True}
            resp = client.post("/v1/chat/completions", json=payload)
            assert resp.status_code == 200

            text_output = resp.text
            assert ": keep-alive" in text_output
            assert "9876543210" in text_output
