import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

import vaultproxy.gemma_layer as gl
from vaultproxy.config import settings
from vaultproxy.gemma_layer import check_slm_readiness, circuit_breaker
from vaultproxy.server import app


@pytest.fixture(autouse=True)
def reset_probe_state():
    gl._last_probe_time = 0.0
    gl._last_probe_ok = False
    gl._last_probe_model = None
    gl.LAST_SLM_MODEL_NAME = ""
    circuit_breaker.record_success()
    yield
    gl._last_probe_time = 0.0
    gl._last_probe_ok = False
    gl._last_probe_model = None
    gl.LAST_SLM_MODEL_NAME = ""
    circuit_breaker.record_success()


def test_b13_backend_off_is_ready():
    """When GEMMA_BACKEND='off', readiness is ready without probing."""
    with patch.object(settings, "GEMMA_BACKEND", "off"):
        client = TestClient(app)
        resp = client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"


def test_b13_ollama_unreachable_degraded_and_model_hidden():
    """When Ollama is down in non-strict mode, status is degraded."""
    err = httpx.ConnectError("Connection refused")
    with patch.object(settings, "GEMMA_BACKEND", "ollama"), \
         patch.object(settings, "STRICT_MODE", False), \
         patch("httpx.AsyncClient.get", side_effect=err):
        client = TestClient(app)
        resp = client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["slm_model"] is None


def test_b13_ollama_unreachable_strict_not_ready():
    """When Ollama is unreachable in strict mode, status is not_ready."""
    err = httpx.ConnectError("Connection refused")
    with patch.object(settings, "GEMMA_BACKEND", "ollama"), \
         patch.object(settings, "STRICT_MODE", True), \
         patch("httpx.AsyncClient.get", side_effect=err):
        client = TestClient(app)
        resp = client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_ready"
        assert data["slm_model"] is None


def test_b13_ollama_reachable_model_present_is_ready():
    """When Ollama returns tags with configured model, status is ready."""
    mock_resp = httpx.Response(
        200,
        json={"models": [{"name": "gemma2:2b"}]},
    )
    with patch.object(settings, "GEMMA_BACKEND", "ollama"), \
         patch.object(settings, "GEMMA_MODEL", "gemma2:2b"), \
         patch("httpx.AsyncClient.get", return_value=mock_resp):
        client = TestClient(app)
        resp = client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["slm_model"] == "gemma2:2b"


def test_b13_probe_caching_10_seconds():
    """Readiness probe is cached for up to 10 seconds."""
    resp = httpx.Response(200, json={"models": [{"name": "gemma2:2b"}]})
    mock_get = AsyncMock(return_value=resp)
    with patch.object(settings, "GEMMA_BACKEND", "ollama"), \
         patch.object(settings, "GEMMA_MODEL", "gemma2:2b"), \
         patch("httpx.AsyncClient.get", mock_get):
        ok1, model1 = asyncio.run(check_slm_readiness())
        assert ok1 is True
        assert model1 == "gemma2:2b"
        assert mock_get.call_count == 1

        # Second call immediately should use cache
        ok2, model2 = asyncio.run(check_slm_readiness())
        assert ok2 is True
        assert model2 == "gemma2:2b"
        assert mock_get.call_count == 1
