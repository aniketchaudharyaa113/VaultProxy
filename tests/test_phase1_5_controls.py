import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from vaultproxy.gemma_layer import (
    CircuitBreaker,
    GemmaLayerError,
    circuit_breaker,
    get_semaphore,
    get_source_label,
    parse_gemma_json,
    reset_semaphore,
    run_gemma_detection,
)
from vaultproxy.server import app


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    circuit_breaker.state = "CLOSED"
    circuit_breaker.failure_count = 0
    reset_semaphore()
    yield
    circuit_breaker.state = "CLOSED"
    circuit_breaker.failure_count = 0
    reset_semaphore()


# ---------------------------------------------------------------------------
# 1. Circuit Breaker Transitions
# ---------------------------------------------------------------------------
def test_circuit_breaker_transitions():
    """Test CLOSED -> OPEN after 3 failures, OPEN -> HALF_OPEN after cooldown,

    HALF_OPEN -> CLOSED on success, HALF_OPEN -> OPEN on failure.
    """
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)
    assert cb.state == "CLOSED"
    assert cb.allow_request() is True

    # 3 failures move to OPEN
    cb.record_failure()
    assert cb.state == "CLOSED"
    cb.record_failure()
    assert cb.state == "CLOSED"
    cb.record_failure()
    assert cb.state == "OPEN"
    assert cb.allow_request() is False

    # Simulate clock advancing past cooldown
    with patch("time.monotonic", return_value=1000.0):
        cb.cooldown_until = 900.0  # past cooldown
        assert cb.allow_request() is True
        assert cb.state == "HALF_OPEN"

    # HALF_OPEN -> CLOSED on success
    cb.record_success()
    assert cb.state == "CLOSED"
    assert cb.failure_count == 0

    # Move back to OPEN
    cb.state = "OPEN"
    with patch("time.monotonic", return_value=1000.0):
        cb.cooldown_until = 900.0
        assert cb.allow_request() is True
        assert cb.state == "HALF_OPEN"

        # HALF_OPEN -> OPEN on failure
        cb.record_failure()
        assert cb.state == "OPEN"


# ---------------------------------------------------------------------------
# 2. Invalid JSON and Schema Violations through Real HTTP Path
# ---------------------------------------------------------------------------
def test_e2e_invalid_json_strict_mode():
    """Real HTTP path: Strict mode returns 503 and forwards nothing when SLM produces unparseable JSON."""
    client = TestClient(app)
    upstream_called = False

    async def mock_ollama_post(*args, **kwargs):
        return httpx.Response(200, json={"message": {"content": "INVALID NOT JSON"}})

    async def mock_ollama_get(*args, **kwargs):
        return httpx.Response(200, json={"models": [{"name": "gemma4:e2b"}]})

    orig_send = httpx.AsyncClient.send

    async def mock_selective_send(req, *args, **kwargs):
        if "8001" in str(req.url):
            nonlocal upstream_called
            upstream_called = True
            return httpx.Response(200, json={"choices": []})
        return await orig_send(req, *args, **kwargs)

    with patch("vaultproxy.config.settings.STRICT_MODE", True), \
         patch("vaultproxy.config.settings.GEMMA_BACKEND", "ollama"), \
         patch("httpx.AsyncClient.post", side_effect=mock_ollama_post), \
         patch("httpx.AsyncClient.get", side_effect=mock_ollama_get), \
         patch("httpx.AsyncClient.send", side_effect=mock_selective_send):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": [{"role": "user", "content": "My name is Rajesh"}]},
        )
        assert resp.status_code == 503
        assert "VaultProxy fail-closed" in resp.json()["detail"]
        assert not upstream_called


def test_e2e_invalid_json_non_strict_degraded():
    """Real HTTP path: Non-strict mode uses rules only, sets degraded=true, gemma_used=false when SLM fails."""
    client = TestClient(app)

    async def mock_ollama_post(*args, **kwargs):
        return httpx.Response(200, json={"message": {"content": "CORRUPTED JSON"}})

    async def mock_ollama_get(*args, **kwargs):
        return httpx.Response(200, json={"models": [{"name": "gemma4:e2b"}]})

    orig_send = httpx.AsyncClient.send

    async def mock_selective_send(req, *args, **kwargs):
        if "8001" in str(req.url):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "Hello [PAN_1]"}}]},
                headers={"content-type": "application/json"},
            )
        return await orig_send(req, *args, **kwargs)

    with patch("vaultproxy.config.settings.STRICT_MODE", False), \
         patch("vaultproxy.config.settings.GEMMA_BACKEND", "ollama"), \
         patch("httpx.AsyncClient.post", side_effect=mock_ollama_post), \
         patch("httpx.AsyncClient.get", side_effect=mock_ollama_get), \
         patch("httpx.AsyncClient.send", side_effect=mock_selective_send):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": [{"role": "user", "content": "My PAN is ABCPB1234F and my name is Rajesh"}]},
        )
        assert resp.status_code == 200
        vault_report_str = resp.headers.get("x-vault-report", "{}")
        report_data = json.loads(vault_report_str)
        assert report_data["degraded"] is True
        assert report_data["gemma_used"] is False


# ---------------------------------------------------------------------------
# 3. Span Source Label Rules
# ---------------------------------------------------------------------------
def test_span_source_label_rules():
    """Test model 'gemma4:e2b' -> 'gemma', model 'qwen2.5' -> 'slm:qwen2.5'."""
    assert get_source_label("gemma4:e2b") == "gemma"
    assert get_source_label("GEMMA2:9B") == "gemma"
    assert get_source_label("qwen2.5") == "slm:qwen2.5"
    assert get_source_label("llama3.2") == "slm:llama3.2"

    spans, valid = parse_gemma_json(
        '{"entities": [{"text": "Rajesh", "type": "PERSON"}]}',
        "My name is Rajesh",
        source_label=get_source_label("qwen2.5"),
    )
    assert valid is True
    assert len(spans) == 1
    assert spans[0].source == "slm:qwen2.5"


# ---------------------------------------------------------------------------
# 4. GEMMA_AUTODISCOVER Default Off & Missing Model Error
# ---------------------------------------------------------------------------
def test_gemma_autodiscover_off_missing_model_error():
    """Verify error when GEMMA_AUTODISCOVER=False and configured model is not installed."""
    async def _run():
        async def mock_ollama_get(*args, **kwargs):
            return httpx.Response(200, json={"models": [{"name": "mistral:7b"}]})

        with patch("vaultproxy.config.settings.GEMMA_BACKEND", "ollama"), \
             patch("vaultproxy.config.settings.GEMMA_MODEL", "gemma4:e2b"), \
             patch("vaultproxy.config.settings.GEMMA_AUTODISCOVER", False), \
             patch("httpx.AsyncClient.get", side_effect=mock_ollama_get):

            with patch("vaultproxy.config.settings.STRICT_MODE", True):
                with pytest.raises(GemmaLayerError, match="(?i)not installed"):
                    await run_gemma_detection("My name is Rajesh")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5. Concurrency Control & Queue Timeout
# ---------------------------------------------------------------------------
def test_semaphore_concurrency_limit_10_requests():
    """Verify max concurrency semaphore processes 10 parallel requests safely."""
    async def _run():
        concurrent_active = 0
        max_concurrent_seen = 0

        async def mock_slow_post(*args, **kwargs):
            nonlocal concurrent_active, max_concurrent_seen
            concurrent_active += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_active)
            await asyncio.sleep(0.02)
            concurrent_active -= 1
            return httpx.Response(200, json={"message": {"content": '{"entities": []}'}})

        async def mock_get(*args, **kwargs):
            return httpx.Response(200, json={"models": [{"name": "gemma4:e2b"}]})

        with patch("vaultproxy.config.settings.GEMMA_BACKEND", "ollama"), \
             patch("vaultproxy.config.settings.GEMMA_CONCURRENCY_LIMIT", 4), \
             patch("httpx.AsyncClient.post", side_effect=mock_slow_post), \
             patch("httpx.AsyncClient.get", side_effect=mock_get):

            reset_semaphore()
            tasks = [run_gemma_detection("Sample text") for _ in range(10)]
            results = await asyncio.gather(*tasks)

            assert len(results) == 10
            # Concurrency limit is 4
            assert max_concurrent_seen <= 4

    asyncio.run(_run())


def test_gemma_queue_timeout_exceeded():
    """Verify GEMMA_QUEUE_TIMEOUT_SECONDS failure when concurrency slot is blocked."""
    async def _run():
        with patch("vaultproxy.config.settings.GEMMA_BACKEND", "ollama"), \
             patch("vaultproxy.config.settings.GEMMA_CONCURRENCY_LIMIT", 4), \
             patch("vaultproxy.config.settings.GEMMA_QUEUE_TIMEOUT_SECONDS", 0.05), \
             patch("vaultproxy.config.settings.STRICT_MODE", True):

            reset_semaphore()
            sem = get_semaphore()

            # Acquire all 4 slots manually
            for _ in range(4):
                await sem.acquire()

            try:
                with pytest.raises(GemmaLayerError, match="(?i)queue timeout"):
                    await run_gemma_detection("Testing queue timeout")
            finally:
                for _ in range(4):
                    sem.release()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 6. Demo /demo/analyze True Source Labeling & Not Assessed Response
# ---------------------------------------------------------------------------
def test_demo_analyze_sources_and_not_assessed():
    """Test /demo/analyze labels spans by true source and returns 'Not assessed' when SLM is off/failed."""
    client = TestClient(app)

    with patch("vaultproxy.config.settings.DEMO_MODE", True), \
         patch("vaultproxy.config.settings.GEMMA_BACKEND", "off"):
        resp = client.post("/demo/analyze", json={"text": "My PAN is ABCPB1234F", "use_gemma": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["gemma"]["status"] == "Not assessed"
        assert data["spans"][0]["source"] == "RULE"
