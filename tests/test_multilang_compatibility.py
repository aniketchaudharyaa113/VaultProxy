import json
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from vaultproxy.config import settings
from vaultproxy.server import app

client = TestClient(app)


def test_route_aliases_work_with_and_without_v1():
    """Verify that clients setting baseURL to either host/v1 or bare host route properly."""
    fake_pan = "ABCPB1234F"
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": [{"message": {"role": "assistant", "content": "Ok"}}]}).encode("utf-8"),
    )

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": f"My PAN is {fake_pan}"}],
    }

    with patch.object(settings, "GEMMA_BACKEND", "off"), \
         patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_resp

        # 1. With /v1 prefix
        r1 = client.post("/v1/chat/completions", json=payload)
        assert r1.status_code == 200

        # 2. Without /v1 prefix (direct /chat/completions)
        r2 = client.post("/chat/completions", json=payload)
        assert r2.status_code == 200


def test_models_and_embeddings_route_aliases():
    """Verify /models and /embeddings aliases work without /v1 prefix."""
    mock_models_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"data": [{"id": "gpt-4"}]}).encode("utf-8"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_models_resp

        r_v1 = client.get("/v1/models")
        assert r_v1.status_code == 200

        r_bare = client.get("/models")
        assert r_bare.status_code == 200

    mock_emb_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"data": [{"embedding": [0.1, 0.2]}]}).encode("utf-8"),
    )
    emb_payload = {"model": "text-embedding-ada-002", "input": "Hello world"}
    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_emb_resp

        r_v1_emb = client.post("/v1/embeddings", json=emb_payload)
        assert r_v1_emb.status_code == 200

        r_bare_emb = client.post("/embeddings", json=emb_payload)
        assert r_bare_emb.status_code == 200


def test_node_and_spring_header_compatibility():
    """Verify standard headers from Node.js (undici/fetch) and Spring Boot (RestClient/WebClient) pass through."""
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": [{"message": {"role": "assistant", "content": "Done"}}]}).encode("utf-8"),
    )

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    # Simulate Node.js undici / Spring Boot headers
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Spring-AI/1.0.0-M1 (Java 21)",
    }

    with patch.object(settings, "GEMMA_BACKEND", "off"), \
         patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_resp

        resp = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert resp.status_code == 200
        sent_req = mock_send.call_args[0][0]
        # Verify user-agent and content-type reached upstream
        assert sent_req.headers.get("user-agent") == "Spring-AI/1.0.0-M1 (Java 21)"
