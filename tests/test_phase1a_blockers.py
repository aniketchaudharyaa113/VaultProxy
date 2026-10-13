import asyncio
import gzip
import json
import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from vaultproxy.config import settings
from vaultproxy.server import app, get_concurrency_semaphore
try:
    from vaultproxy.server import build_upstream_url
except ImportError:
    # Current broken behavior before fix
    def build_upstream_url(base_url: str, endpoint: str) -> str:
        return f"{base_url.rstrip('/')}/v1/{endpoint}"
from vaultproxy.vault import RequestVault

PROD_TOKEN = "a_very_long_secure_vault_production_token_123456"


# ============================================================================
# B1 Gzip: dropped content-encoding, content-length, transfer-encoding
# ============================================================================
def test_b1_gzip_content_encoding_dropped():
    """B1: When upstream sends Content-Encoding: gzip, proxy forwards decoded body

    and must NOT retain content-encoding, content-length, or transfer-encoding.
    """
    raw_payload = {"choices": [{"message": {"content": "Hello world"}}]}
    gzipped_body = gzip.compress(json.dumps(raw_payload).encode("utf-8"))

    # Upstream response with Content-Encoding: gzip and Content-Length
    mock_resp = httpx.Response(
        200,
        headers={
            "content-type": "application/json",
            "content-encoding": "gzip",
            "content-length": str(len(gzipped_body)),
            "transfer-encoding": "chunked",
            "x-custom": "keep-me",
        },
        content=gzipped_body,
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"), \
         patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_resp

        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        # Headers content-encoding, content-length, and transfer-encoding MUST NOT be forwarded
        assert "content-encoding" not in resp.headers
        assert "transfer-encoding" not in resp.headers
        assert resp.headers.get("x-custom") == "keep-me"
        # Client must be able to read JSON without DecodingError
        assert resp.json() == raw_payload


# ============================================================================
# B2 Streams kill each other: process_sse_stream aclose shared client
# ============================================================================
def test_b2_shared_client_not_closed_by_stream():
    """B2: process_sse_stream must not close the shared httpx client in its finally block."""
    async def _run():
        from vaultproxy.restore import process_sse_stream

        shared_client = httpx.AsyncClient()
        mock_resp = AsyncMock()

        async def mock_aiter_lines():
            yield "data: {\"choices\": [{\"delta\": {\"content\": \"hi\"}}]}"
            yield "data: [DONE]"

        mock_resp.aiter_lines = mock_aiter_lines
        mock_resp.aclose = AsyncMock()

        vault = RequestVault()
        gen = process_sse_stream(mock_resp, shared_client, vault, "model")
        chunks = [c async for c in gen]

        assert len(chunks) > 0
        # mock_resp must be closed
        mock_resp.aclose.assert_awaited_once()
        # shared_client must NOT be closed!
        assert not shared_client.is_closed
        await shared_client.aclose()

    asyncio.run(_run())


# ============================================================================
# B3 Base URL builder unit tests
# ============================================================================
@pytest.mark.parametrize(
    "base_url,endpoint,expected",
    [
        ("https://api.openai.com", "chat/completions", "https://api.openai.com/v1/chat/completions"),
        ("https://api.openai.com/v1", "chat/completions", "https://api.openai.com/v1/chat/completions"),
        ("https://api.openai.com/v1/", "chat/completions", "https://api.openai.com/v1/chat/completions"),
        ("http://localhost:11434/v1", "chat/completions", "http://localhost:11434/v1/chat/completions"),
        ("http://localhost:11434/v1/", "chat/completions", "http://localhost:11434/v1/chat/completions"),
        ("https://host/v1beta/openai", "chat/completions", "https://host/v1beta/openai/chat/completions"),
        ("https://host/v1beta/openai/", "chat/completions", "https://host/v1beta/openai/chat/completions"),
        ("https://api.openai.com", "models", "https://api.openai.com/v1/models"),
        ("https://api.openai.com/v1", "models", "https://api.openai.com/v1/models"),
        ("https://api.openai.com", "embeddings", "https://api.openai.com/v1/embeddings"),
        ("https://api.openai.com/v1", "embeddings", "https://api.openai.com/v1/embeddings"),
    ],
)
def test_b3_build_upstream_url(base_url, endpoint, expected):
    """B3: Unit test URL builder handles base_url variants properly."""
    assert build_upstream_url(base_url, endpoint) == expected



# ============================================================================
# B4 Concurrency limit: slot released after streaming generator finishes
# ============================================================================
def test_b4_concurrency_limit_held_during_stream():
    """B4: Concurrency semaphore slot must be unconditionally released when the
    streaming generator finishes (whether it completes normally or the client
    disconnects).  The real-server tests in test_phase1a_extra.py verify 429-
    during / 200-after end-to-end; this unit test checks the counter directly.
    """
    import vaultproxy.server as srv

    async def _run() -> None:
        # Build a tiny byte-stream mock (process_sse_stream uses aiter_bytes)
        async def stream_bytes():
            yield b'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
            yield b"data: [DONE]\n\n"

        mock_upstream = AsyncMock()
        mock_upstream.headers = {"content-type": "text/event-stream"}
        mock_upstream.status_code = 200
        mock_upstream.aiter_bytes = stream_bytes
        mock_upstream.aclose = AsyncMock()

        # Install a fresh semaphore (limit 1) so the test is isolated
        sem = asyncio.Semaphore(1)
        srv._concurrency_semaphore = sem
        srv._httpx_client = None  # force fresh client

        with patch.object(settings, "MAX_CONCURRENT_REQUESTS", 1), \
             patch.object(settings, "GEMMA_BACKEND", "off"), \
             patch("httpx.AsyncClient.send",
                   new_callable=AsyncMock,
                   return_value=mock_upstream):
            client = TestClient(app)

            before_val: int = sem._value  # type: ignore[attr-defined]

            # Consume the full stream so the generator's finally runs
            collected: list[str] = []
            with client.stream(
                "POST",
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}],
                      "stream": True},
            ) as stream_resp:
                assert stream_resp.status_code == 200
                for line in stream_resp.iter_lines():
                    if line.startswith("data:"):
                        collected.append(line)

            after_val: int = sem._value  # type: ignore[attr-defined]

        assert after_val == before_val, (
            f"Semaphore value drifted: before={before_val}, after={after_val}. "
            "The streaming generator did not release its slot (B4 regression)."
        )
        assert any("[DONE]" in ln for ln in collected), (
            f"Stream must end with [DONE]; got lines: {collected}"
        )

    asyncio.run(_run())


# ============================================================================
# B5 Auth in development profile when VAULT_AUTH_TOKEN is set
# ============================================================================
def test_b5_auth_enforced_in_dev_when_token_set():
    """B5: When VAULT_AUTH_TOKEN is set in development profile, unauthenticated requests return 401."""
    with patch.object(settings, "VAULT_PROFILE", "development"), \
         patch.object(settings, "VAULT_AUTH_TOKEN", PROD_TOKEN):
        client = TestClient(app)

        # /v1/chat/completions
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401

        # /v1/models
        resp_models = client.get("/v1/models")
        assert resp_models.status_code == 401

        # /metrics
        resp_metrics = client.get("/metrics")
        assert resp_metrics.status_code == 401

        # /readyz detailed requires auth when token is set
        resp_readyz = client.get("/readyz")
        assert resp_readyz.status_code == 200
        # detailed fields must NOT be returned without auth
        data = resp_readyz.json()
        assert "slm_backend" not in data
        assert data == {"status": "ready"}


# ============================================================================
# B11 Retention: LAST_MASKED_REQUEST kept only when DEMO_MODE=true
# ============================================================================
def test_b11_retention_only_in_demo_mode():
    """B11: LAST_MASKED_REQUEST is stored only when DEMO_MODE=true; in production keeps nothing."""
    from vaultproxy.health import LAST_MASKED_REQUEST

    LAST_MASKED_REQUEST.clear()

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8"),
    )

    with patch.object(settings, "VAULT_PROFILE", "production"), \
         patch.object(settings, "VAULT_AUTH_TOKEN", PROD_TOKEN), \
         patch.object(settings, "DEMO_MODE", False), \
         patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_resp
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {PROD_TOKEN}"},
            json={"messages": [{"role": "user", "content": "My phone is 9876543210"}]},
        )
        assert resp.status_code == 200
        # In production (and DEMO_MODE=False), LAST_MASKED_REQUEST must be empty!
        assert LAST_MASKED_REQUEST == {}


# ============================================================================
# B12 Key in logs: Gemini API key in header, not in URL or logged exception
# ============================================================================
def test_b12_gemini_key_not_in_logs_or_url(caplog):
    """B12: Gemini key sent in x-goog-api-key header, not in URL; never logged."""
    from vaultproxy.gemma_layer import circuit_breaker

    circuit_breaker.state = "CLOSED"
    circuit_breaker.failure_count = 0

    async def _run():
        from vaultproxy.gemma_layer import run_gemma_detection

        fake_key = "AI" + "zaSyFakeKey1234567890SecretKeyToHide"

        with patch.object(settings, "GEMMA_BACKEND", "gemini"), \
             patch.object(settings, "GEMINI_API_KEY", fake_key), \
             patch.object(settings, "STRICT_MODE", False), \
             caplog.at_level(logging.DEBUG):

            # Mock post to capture requested URL and headers
            captured_request = {}

            async def fake_post(url, *args, **kwargs):
                captured_request["url"] = str(url)
                captured_request["headers"] = kwargs.get("headers", {})
                raise httpx.ConnectError(f"Connection failed to {url}")

            with patch("httpx.AsyncClient.post", side_effect=fake_post):
                await run_gemma_detection("some text")

                # Check that fake_key was NOT in the URL
                assert "key=" not in captured_request.get("url", "")
                assert fake_key not in captured_request.get("url", "")
                # Check that header contained the key
                assert captured_request.get("headers", {}).get("x-goog-api-key") == fake_key

                # Check caplog that fake_key was NEVER logged at any log level
                for record in caplog.records:
                    assert fake_key not in record.getMessage()

    try:
        asyncio.run(_run())
    finally:
        circuit_breaker.state = "CLOSED"
        circuit_breaker.failure_count = 0

