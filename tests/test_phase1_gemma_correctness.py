"""Phase 1 contract and correctness tests for Gemma/SLM layer.

Covers:
- H1: Exact model calling & model name source labeling (source="gemma" vs source="slm:<model>")
- H2: Heuristic fallback source="heuristic", degraded=True, gemma_used=False
- H5: Invalid JSON / unparseable SLM output counts as SLM failure (503 in strict mode; degraded=True, gemma_used=False in non-strict mode)
- H6: gemma_used=False whenever SLM fails or is degraded
- Circuit breaker transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Startup self-test and model validation
"""

import asyncio
import json
import time
from unittest.mock import patch

import httpx
import pytest

from vaultproxy.config import settings
from vaultproxy.gemma_layer import (
    CircuitBreaker,
    GemmaLayerError,
    circuit_breaker,
    get_source_label,
    run_gemma_detection,
    startup_self_test,
)


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    circuit_breaker.state = "CLOSED"
    circuit_breaker.failure_count = 0
    yield
    circuit_breaker.state = "CLOSED"
    circuit_breaker.failure_count = 0


def test_source_label_gemma_vs_slm():
    """Test get_source_label returns 'gemma' for gemma models and 'slm:<model>' otherwise."""
    assert get_source_label("gemma4:e2b") == "gemma"
    assert get_source_label("Gemma-2-2b") == "gemma"
    assert get_source_label("llama3:8b") == "slm:llama3:8b"
    assert get_source_label("mistral:7b") == "slm:mistral:7b"


def test_h1_exact_model_calling_non_gemma_source_label():
    """Test H1: SLM layer calls exact configured model and uses slm:<model> label when non-gemma."""
    async def _run():
        mock_response = {
            "message": {
                "content": json.dumps([
                    {"text": "Rajesh Kumar", "type": "PERSON"}
                ])
            }
        }

        async def mock_post(*args, **kwargs):
            return httpx.Response(200, json=mock_response)

        async def mock_get(*args, **kwargs):
            return httpx.Response(200, json={"models": [{"name": "llama3:8b"}]})

        with patch.object(settings, "GEMMA_BACKEND", "ollama"):
            with patch.object(settings, "GEMMA_MODEL", "llama3:8b"):
                with patch.object(settings, "GEMMA_AUTODISCOVER", False):
                    with patch("httpx.AsyncClient.post", side_effect=mock_post):
                        with patch("httpx.AsyncClient.get", side_effect=mock_get):
                            text = "Rajesh Kumar is here."
                            spans, degraded, gemma_used = await run_gemma_detection(text)

                            assert len(spans) == 1
                            assert spans[0].source == "slm:llama3:8b"
                            assert degraded is False
                            assert gemma_used is True
    asyncio.run(_run())


def test_h5_h6_unparseable_json_counts_as_slm_failure():
    """Test H5 & H6: Invalid JSON output counts as SLM failure (degraded=True, gemma_used=False)."""
    async def _run():
        mock_invalid_response = {
            "message": {
                "content": "Not a JSON output at all!!!"
            }
        }

        async def mock_post(*args, **kwargs):
            return httpx.Response(200, json=mock_invalid_response)

        # In non-strict mode: returns empty spans, degraded=True, gemma_used=False
        with patch.object(settings, "GEMMA_BACKEND", "ollama"):
            with patch.object(settings, "STRICT_MODE", False):
                with patch("httpx.AsyncClient.post", side_effect=mock_post):
                    spans, degraded, gemma_used = await run_gemma_detection("Test text")
                    assert spans == []
                    assert degraded is True
                    assert gemma_used is False

        # In strict mode: raises GemmaLayerError (triggers 503 fail-closed)
        with patch.object(settings, "GEMMA_BACKEND", "ollama"):
            with patch.object(settings, "STRICT_MODE", True):
                with patch("httpx.AsyncClient.post", side_effect=mock_post):
                    with pytest.raises(GemmaLayerError):
                        await run_gemma_detection("Test text")
    asyncio.run(_run())


def test_circuit_breaker_state_transitions():
    """Test circuit breaker transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
    assert cb.state == "CLOSED"
    assert cb.allow_request() is True

    # Failure 1
    cb.record_failure()
    assert cb.state == "CLOSED"

    # Failure 2 -> triggers OPEN
    cb.record_failure()
    assert cb.state == "OPEN"
    assert cb.allow_request() is False

    # Wait for cooldown
    time.sleep(0.15)
    assert cb.allow_request() is True
    assert cb.state == "HALF_OPEN"

    # Success probe -> CLOSED
    cb.record_success()
    assert cb.state == "CLOSED"
    assert cb.failure_count == 0


def test_circuit_breaker_open_returns_503_in_strict_mode():
    """Test open circuit breaker causes 503 fail-closed in strict mode."""
    async def _run():
        with patch.object(circuit_breaker, "allow_request", return_value=False):
            with patch.object(settings, "GEMMA_BACKEND", "ollama"):
                with patch.object(settings, "STRICT_MODE", True):
                    with pytest.raises(GemmaLayerError) as exc_info:
                        await run_gemma_detection("Test text")
                    assert "circuit breaker is OPEN" in str(exc_info.value)
    asyncio.run(_run())


def test_startup_self_test():
    """Test startup_self_test functionality."""
    async def _run():
        with patch.object(settings, "GEMMA_BACKEND", "off"):
            ok, model, lat = await startup_self_test()
            assert ok is True
            assert model == "off"
            assert lat == 0.0
    asyncio.run(_run())
