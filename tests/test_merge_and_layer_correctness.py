import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from vaultproxy.config import settings
from vaultproxy.detectors import Span
from vaultproxy.merge import merge_spans
from vaultproxy.server import app


# -------------------------------------------------------------------
# P2 & P1 Mutation 5: Merge Spans Behavior & Priority Tests
# -------------------------------------------------------------------
def test_merge_spans_rule_vs_gemma_priority():
    """Verify rule spans take precedence over gemma spans for identical bounds."""
    span_rule = Span(start=5, end=15, type="PAN", source="rule", score=1.0)
    span_gemma = Span(start=5, end=15, type="NAME", source="gemma", score=1.0)

    merged1 = merge_spans([span_gemma, span_rule])
    assert len(merged1) == 1
    assert merged1[0].source == "rule"
    assert merged1[0].type == "PAN"

    merged2 = merge_spans([span_rule, span_gemma])
    assert len(merged2) == 1
    assert merged2[0].source == "rule"


def test_merge_spans_overlapping_and_nested():
    """Test overlapping, nested, and longer-span-wins rules."""
    # Nested spans: (0, 10) vs (2, 8) -> longer span wins
    span_outer = Span(start=0, end=10, type="SECRET", source="rule")
    span_inner = Span(start=2, end=8, type="PAN", source="rule")
    merged = merge_spans([span_inner, span_outer])
    assert len(merged) == 1
    assert merged[0].start == 0 and merged[0].end == 10

    # Overlapping spans: (0, 5) vs (4, 9)
    s1 = Span(start=0, end=5, type="PAN", source="rule", score=1.0)
    s2 = Span(start=4, end=9, type="MOBILE", source="rule", score=0.8)
    merged_overlap = merge_spans([s1, s2])
    assert len(merged_overlap) == 1
    assert merged_overlap[0].type == "PAN"


def test_merge_spans_identical_adjacent_equal_scores():
    """Test identical, adjacent, and equal score span merging."""
    # Identical spans: pick higher score or first
    s1 = Span(start=0, end=5, type="A", source="rule", score=0.5)
    s2 = Span(start=0, end=5, type="B", source="rule", score=0.9)
    merged_ident = merge_spans([s1, s2])
    assert len(merged_ident) == 1
    assert merged_ident[0].type == "B"

    # Adjacent spans: (0, 5) and (5, 10) -> kept distinct
    adj1 = Span(start=0, end=5, type="A", source="rule")
    adj2 = Span(start=5, end=10, type="B", source="rule")
    merged_adj = merge_spans([adj1, adj2])
    assert len(merged_adj) == 2
    assert merged_adj[0].end == 5 and merged_adj[1].start == 5


def test_merge_spans_unicode_text():
    """Test span merging on Indic / Unicode text."""
    unic_str = "मेरा आधार 367598341203 है"
    span_aadhaar = Span(start=10, end=22, type="AADHAAR", source="rule")
    merged = merge_spans([span_aadhaar])
    assert len(merged) == 1
    assert unic_str[merged[0].start : merged[0].end] == "367598341203"


# -------------------------------------------------------------------
# P2: Health & Readyz Endpoint Behavior Tests
# -------------------------------------------------------------------
def test_health_and_readyz_behavior():
    client = TestClient(app)
    # GET /healthz
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    # GET /readyz
    resp_ready = client.get("/readyz")
    assert resp_ready.status_code == 200
    assert resp_ready.json()["status"] in ["ready", "degraded"]

    # GET /favicon.ico
    resp_fav = client.get("/favicon.ico")
    assert resp_fav.status_code == 204

    # GET /demo/last when DEMO_MODE is False
    with patch.object(settings, "DEMO_MODE", False):
        resp_last = client.get("/demo/last")
        assert resp_last.status_code == 404
        resp_demo = client.get("/demo")
        assert resp_demo.status_code == 404

    # GET /demo when DEMO_MODE is True
    with patch.object(settings, "DEMO_MODE", True):
        resp_last_ok = client.get("/demo/last")
        assert resp_last_ok.status_code == 200


def test_gemma_layer_error_paths_behavior():
    import anyio

    from vaultproxy.gemma_layer import (
        GemmaLayerError,
        circuit_breaker,
        run_gemma_detection,
    )

    async def _test():
        # Circuit breaker open in STRICT_MODE
        circuit_breaker.state = "OPEN"
        circuit_breaker.cooldown_until = time.monotonic() + 1000.0
        with patch.object(settings, "GEMMA_BACKEND", "ollama"), patch.object(settings, "STRICT_MODE", True):
            with pytest.raises(GemmaLayerError, match="circuit breaker is OPEN"):
                await run_gemma_detection("My name is Ramesh")

        # Circuit breaker open in non-STRICT mode
        with patch.object(settings, "GEMMA_BACKEND", "ollama"), patch.object(settings, "STRICT_MODE", False):
            spans, degraded, gemma_used = await run_gemma_detection("My name is Ramesh")
            assert degraded is True
            assert gemma_used is False
            assert spans == []

        # Reset circuit breaker
        circuit_breaker.record_success()

        # Queue timeout in STRICT_MODE
        with patch.object(settings, "GEMMA_BACKEND", "ollama"), patch.object(settings, "STRICT_MODE", True):
            with patch("asyncio.wait_for", side_effect=TimeoutError()):
                with pytest.raises(GemmaLayerError, match="queue timeout"):
                    await run_gemma_detection("My name is Ramesh")

        circuit_breaker.record_success()

        # Queue timeout in non-STRICT mode
        with patch.object(settings, "GEMMA_BACKEND", "ollama"), patch.object(settings, "STRICT_MODE", False):
            with patch("asyncio.wait_for", side_effect=TimeoutError()):
                spans, degraded, gemma_used = await run_gemma_detection("My name is Ramesh")
                assert degraded is True
                assert gemma_used is False
                assert spans == []

        circuit_breaker.record_success()

    anyio.run(_test)



