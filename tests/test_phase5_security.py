import json
import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from vaultproxy.config import settings
from vaultproxy.server import app

PROD_TOKEN = "a_very_long_secure_vault_production_token_123456"


@pytest.fixture
def prod_client():
    with patch.object(settings, "VAULT_PROFILE", "production"), \
         patch.object(settings, "VAULT_AUTH_TOKEN", PROD_TOKEN):
        yield TestClient(app)


def test_auth_bypass_attempts(prod_client):
    """Test auth bypass attempts (missing, wrong, empty, very long, odd-case Bearer)."""
    # 1. Missing Authorization header -> 401
    resp_missing = prod_client.get("/v1/models")
    assert resp_missing.status_code == 401
    assert resp_missing.json()["error"]["code"] == "invalid_api_key"

    # 2. Wrong token -> 401
    resp_wrong = prod_client.get(
        "/v1/models", headers={"Authorization": "Bearer wrong_token_12345"}
    )
    assert resp_wrong.status_code == 401
    assert resp_wrong.json()["error"]["code"] == "invalid_api_key"

    # 3. Empty Bearer -> 401
    resp_empty = prod_client.get(
        "/v1/models", headers={"Authorization": "Bearer "}
    )
    assert resp_empty.status_code == 401

    # 4. Very long wrong token -> 401
    resp_long = prod_client.get(
        "/v1/models", headers={"Authorization": "Bearer " + "A" * 5000}
    )
    assert resp_long.status_code == 401

    # 5. Odd-case Bearer ("bearer", "BEARER") with valid token -> 200
    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"data": []}).encode("utf-8"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        resp_lower = prod_client.get(
            "/v1/models", headers={"Authorization": f"bearer {PROD_TOKEN}"}
        )
        assert resp_lower.status_code == 200

        resp_upper = prod_client.get(
            "/v1/models", headers={"Authorization": f"BEARER {PROD_TOKEN}"}
        )
        assert resp_upper.status_code == 200


def test_oversize_body_and_invalid_utf8(prod_client):
    """Test request body size cap and invalid UTF-8 bytes handling."""
    # Oversize body exceeding MAX_BODY_BYTES
    with patch.object(settings, "MAX_BODY_BYTES", 100):
        large_payload = {"model": "gpt-4", "messages": [{"role": "user", "content": "X" * 200}]}
        resp_size = prod_client.post(
            "/v1/chat/completions",
            json=large_payload,
            headers={"Authorization": f"Bearer {PROD_TOKEN}"},
        )
        assert resp_size.status_code in (413, 400)

    # Invalid UTF-8 bytes body -> 400
    invalid_bytes = b"\x80\x81\x82\xff"
    resp_utf8 = prod_client.post(
        "/v1/chat/completions",
        content=invalid_bytes,
        headers={
            "Authorization": f"Bearer {PROD_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    assert resp_utf8.status_code == 400


def test_deeply_nested_json_and_header_injection(prod_client):
    """Test deeply nested JSON structure and header injection protection."""
    # Deeply nested JSON
    deep_dict: dict = {"content": "Deep prompt text"}
    for _ in range(100):
        deep_dict = {"nested": deep_dict}

    payload = {"model": "gpt-4", "messages": [{"role": "user", "content": "Hello", "extra": deep_dict}]}

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": [{"message": {"role": "assistant", "content": "Hi"}}]}).encode("utf-8"),
    )

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            resp_nest = prod_client.post(
                "/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {PROD_TOKEN}"},
            )
            assert resp_nest.status_code == 200

    # Header injection attempt: client sends malicious authorization or host header
    with patch.object(settings, "UPSTREAM_API_KEY", "secret_upstream_key_999"):
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_resp

            prod_client.post(
                "/v1/chat/completions",
                json={"model": "gpt-4", "messages": [{"role": "user", "content": "Test"}]},
                headers={
                    "Authorization": f"Bearer {PROD_TOKEN}",
                    "X-Injected-Header": "injected\r\nHeader: bad",
                },
            )

            sent_req = mock_send.call_args[0][0]
            # Verify client auth was NOT passed upstream, upstream key was used
            assert sent_req.headers.get("authorization") == "Bearer secret_upstream_key_999"


def test_log_privacy_zero_sensitive_data_leakage(caplog):
    """Log privacy test: verify fake PII/secrets NEVER appear in logs or error responses."""
    fake_pan = "ABCPB1234F"
    fake_aadhaar = "367598341203"
    fake_key = "sk-fakekey123456789"
    fake_name = "Rajesh Sharma"

    client = TestClient(app)

    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": f"My name is {fake_name}, PAN is {fake_pan}, Aadhaar is {fake_aadhaar}, key is {fake_key}.",
            }
        ],
    }

    mock_resp = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"choices": [{"message": {"role": "assistant", "content": f"Found {fake_pan}"}}]}).encode("utf-8"),
    )

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        with patch.object(settings, "GEMMA_BACKEND", "off"):
            with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = mock_resp

                resp = client.post("/v1/chat/completions", json=payload)
                assert resp.status_code == 200

                # Capture ALL log output text
                log_text = caplog.text

                # Assert NONE of the raw sensitive values appear anywhere in logs
                assert fake_pan not in log_text
                assert fake_aadhaar not in log_text
                assert fake_key not in log_text
                assert fake_name not in log_text

                # Also verify error responses do not leak sensitive input
                err_resp = client.post(
                    "/v1/chat/completions",
                    content=b"Invalid JSON with " + fake_pan.encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                assert fake_pan not in err_resp.text


def test_unexpected_masking_exceptions_fail_closed_with_503(caplog):
    """Test that unexpected errors inside masking step, vault, or SLM chunk/merge step return HTTP 503 and forward nothing upstream."""
    client = TestClient(app)
    fake_pan = "ABCPB1234F"
    payload = {"model": "gpt-4", "messages": [{"role": "user", "content": f"PAN is {fake_pan}"}]}

    with patch.object(settings, "GEMMA_BACKEND", "off"):
        # 1. Error inside masking step (MaskingEngine.mask_payload)
        with patch("vaultproxy.masking.MaskingEngine.mask_payload", side_effect=RuntimeError("Unexpected masking failure")):
            with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
                caplog.clear()
                resp = client.post("/v1/chat/completions", json=payload)
                assert resp.status_code == 503
                assert mock_send.call_count == 0
                assert fake_pan not in resp.text
                assert fake_pan not in caplog.text

        # 2. Error inside vault (RequestVault.mask_text)
        with patch("vaultproxy.vault.RequestVault.mask_text", side_effect=RuntimeError("Unexpected vault error")):
            with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
                caplog.clear()
                resp = client.post("/v1/chat/completions", json=payload)
                assert resp.status_code == 503
                assert mock_send.call_count == 0
                assert fake_pan not in resp.text
                assert fake_pan not in caplog.text

        # 3. Error inside merge step (merge_spans)
        with patch("vaultproxy.masking.merge_spans", side_effect=RuntimeError("Unexpected merge error")):
            with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
                caplog.clear()
                resp = client.post("/v1/chat/completions", json=payload)
                assert resp.status_code == 503
                assert mock_send.call_count == 0
                assert fake_pan not in resp.text
                assert fake_pan not in caplog.text


def test_stream_timeout_and_long_healthy_stream():
    """Item 3: REQUEST_TIMEOUT_SECONDS resilience - long healthy streams succeed, silent streams end cleanly with error event."""
    import anyio
    from vaultproxy.restore import process_sse_stream
    from vaultproxy.vault import RequestVault

    async def _test():
        vault = RequestVault()
        tok = vault.get_or_create_token("ABCPB1234F", "PAN")

        # 1. Healthy stream producing chunks continuously for longer than timeout
        async def healthy_chunks():
            for i in range(5):
                chunk_json = json.dumps({"choices": [{"index": 0, "delta": {"content": f"Chunk {i} with {tok} "}}]})
                yield f"data: {chunk_json}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"

        mock_resp = AsyncMock()
        mock_resp.headers = {"content-type": "text/event-stream"}
        mock_resp.status_code = 200
        mock_resp.aiter_bytes = healthy_chunks
        mock_resp.aclose = AsyncMock()
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()

        gen = process_sse_stream(mock_resp, mock_client, vault, "gpt-4o")
        results = [chunk async for chunk in gen]
        full_text = "".join(results)

        assert "ABCPB1234F" in full_text
        assert mock_resp.aclose.called

        # 2. Mock stream that goes silent / raises ReadTimeout mid-stream
        async def silent_stream():
            chunk_json = json.dumps({"choices": [{"index": 0, "delta": {"content": f"Partial {tok}"}}]})
            yield f"data: {chunk_json}\n\n".encode("utf-8")
            raise httpx.ReadTimeout("Stream idle timeout exceeded")

        mock_resp_silent = AsyncMock()
        mock_resp_silent.headers = {"content-type": "text/event-stream"}
        mock_resp_silent.status_code = 200
        mock_resp_silent.aiter_bytes = silent_stream
        mock_resp_silent.aclose = AsyncMock()

        gen_silent = process_sse_stream(mock_resp_silent, mock_client, vault, "gpt-4o")
        results_silent = [chunk async for chunk in gen_silent]
        full_silent_text = "".join(results_silent)

        assert "ABCPB1234F" in full_silent_text
        assert "stream_error" in full_silent_text
        assert mock_resp_silent.aclose.called

    anyio.run(_test)


def test_chunked_body_stream_max_bytes_enforcement(prod_client):
    """Item 4: Enforce MAX_BODY_BYTES while reading body stream incrementally."""
    with patch.object(settings, "MAX_BODY_BYTES", 100):
        # 1. Content-Length header exceeding limit -> 413
        oversized_data = json.dumps({"model": "gpt-4", "messages": [{"role": "user", "content": "A" * 200}]}).encode("utf-8")
        resp_over = prod_client.post(
            "/v1/chat/completions",
            content=oversized_data,
            headers={"Authorization": f"Bearer {PROD_TOKEN}", "Content-Type": "application/json"},
        )
        assert resp_over.status_code == 413

        # 2. Chunked request (generator body without Content-Length) exceeding limit -> 413
        def chunk_gen_over():
            yield b'{"model": "gpt-4", "messages": [{"role": "user", "content": "'
            yield b'A' * 200
            yield b'"}]}'

        resp_chunked_over = prod_client.post(
            "/v1/chat/completions",
            content=chunk_gen_over(),
            headers={"Authorization": f"Bearer {PROD_TOKEN}", "Content-Type": "application/json"},
        )
        assert resp_chunked_over.status_code == 413

        # 3. Chunked request under limit -> 200
        def chunk_gen_ok():
            yield b'{"model": "gpt-4", "messages": [{"role": "user", "content": "Hi"}]}'

        with patch.object(settings, "GEMMA_BACKEND", "off"):
            mock_upstream = httpx.Response(200, json={"choices": []})
            with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = mock_upstream
                resp_ok = prod_client.post(
                    "/v1/chat/completions",
                    content=chunk_gen_ok(),
                    headers={"Authorization": f"Bearer {PROD_TOKEN}", "Content-Type": "application/json"},
                )
                assert resp_ok.status_code == 200


def test_header_forwarding_allowlist_and_response_filtering(prod_client):
    """Item 5: Client header allowlisting and response header denylisting."""
    mock_resp = httpx.Response(
        200,
        headers={
            "content-type": "application/json",
            "set-cookie": "session=secret_cookie_123",
            "connection": "close",
            "x-custom-upstream": "custom_val",
        },
        content=json.dumps({"data": []}).encode("utf-8"),
    )

    with patch.object(settings, "UPSTREAM_API_KEY", "secret_upstream_key_123"):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            client_headers = {
                "Authorization": f"Bearer {PROD_TOKEN}",
                "User-Agent": "TestClient/1.0",
                "Cookie": "user_session=bad_cookie",
                "X-User-Email": "attacker@example.com",
                "X-Forwarded-For": "10.0.0.1",
                "OpenAI-Organization": "org-12345",
            }

            resp = prod_client.get("/v1/models", headers=client_headers)
            assert resp.status_code == 200

            # Verify client request headers passed upstream
            sent_req_headers = mock_get.call_args[1]["headers"]
            assert "user-agent" in sent_req_headers
            assert "openai-organization" in sent_req_headers
            assert "cookie" not in sent_req_headers
            assert "x-user-email" not in sent_req_headers
            assert "x-forwarded-for" not in sent_req_headers
            # Verify upstream API key was used
            assert sent_req_headers["authorization"] == "Bearer secret_upstream_key_123"

            # Verify client response headers filtered Set-Cookie and connection
            assert "set-cookie" not in resp.headers
            assert "connection" not in resp.headers


def test_auth_before_work_short_circuit():
    """Item 6: Unauthenticated request in production profile short-circuits before body, SLM, or detectors."""
    with patch.object(settings, "VAULT_PROFILE", "production"), \
         patch.object(settings, "VAULT_AUTH_TOKEN", PROD_TOKEN):

        client = TestClient(app)

        with patch("vaultproxy.server.parse_and_validate_request_body", new_callable=AsyncMock) as mock_body, \
             patch("vaultproxy.gemma_layer.run_gemma_detection", new_callable=AsyncMock) as mock_slm, \
             patch("vaultproxy.masking.MaskingEngine.mask_payload", new_callable=AsyncMock) as mock_mask, \
             patch("vaultproxy.detectors.pan.detect_pan") as mock_pan:

            # Unauthenticated request with 5MB body
            large_content = "X" * (5 * 1024 * 1024)
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "gpt-4", "messages": [{"role": "user", "content": large_content}]},
            )

            assert resp.status_code == 401
            assert mock_body.call_count == 0
            assert mock_slm.call_count == 0
            assert mock_mask.call_count == 0
            assert mock_pan.call_count == 0


def test_production_startup_refusal_constraints():
    """Item 7: Production startup refusal checks for token, length, and demo mode."""
    from vaultproxy.config import Settings
    import os

    with patch.dict(os.environ, {"VAULT_AUTH_TOKEN": "", "DEMO_MODE": "false"}, clear=False):
        # Missing token -> ValueError mentioning VAULT_AUTH_TOKEN
        with pytest.raises(ValueError, match="VAULT_AUTH_TOKEN"):
            Settings(_env_file=None, VAULT_PROFILE="production", VAULT_AUTH_TOKEN="")

    with patch.dict(os.environ, {"VAULT_AUTH_TOKEN": "short_token_123", "DEMO_MODE": "false"}, clear=False):
        # Short token -> ValueError mentioning VAULT_AUTH_TOKEN
        with pytest.raises(ValueError, match="VAULT_AUTH_TOKEN"):
            Settings(_env_file=None, VAULT_PROFILE="production", VAULT_AUTH_TOKEN="short_token_123")

    with patch.dict(os.environ, {"VAULT_AUTH_TOKEN": PROD_TOKEN, "DEMO_MODE": "true"}, clear=False):
        # DEMO_MODE=true -> ValueError mentioning DEMO_MODE
        with pytest.raises(ValueError, match="DEMO_MODE"):
            Settings(_env_file=None, VAULT_PROFILE="production", DEMO_MODE=True, VAULT_AUTH_TOKEN=PROD_TOKEN)


def test_heuristic_fallback_disabled_in_production():
    """Item 7: Heuristic fallback returns empty list in production profile."""
    from vaultproxy.gemma_layer import _heuristic_gemma_fallback

    with patch.object(settings, "VAULT_PROFILE", "production"):
        spans = _heuristic_gemma_fallback("My name is Rajesh Sharma residing at Flat 101, Mumbai")
        assert spans == []


def test_readyz_and_metrics_unauthenticated_minimal_or_401(prod_client):
    """Item 7: /readyz without token returns minimal info, /metrics without token returns 401."""
    # /readyz unauthenticated -> {"status": "ready"}
    resp_ready = prod_client.get("/readyz")
    assert resp_ready.status_code == 200
    data_ready = resp_ready.json()
    assert data_ready == {"status": "ready"}
    assert "slm_backend" not in data_ready

    # /metrics unauthenticated -> 401
    with patch("vaultproxy.server.METRICS_AVAILABLE", True):
        resp_metrics = prod_client.get("/metrics")
        assert resp_metrics.status_code == 401


