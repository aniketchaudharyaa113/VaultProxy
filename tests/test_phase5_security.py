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
