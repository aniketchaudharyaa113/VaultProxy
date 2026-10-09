"""Characterization test suite for gemma_layer.py with mocked backends.

Covers:
- Backend off
- Mocked Ollama success
- Mocked Gemini success
- Timeout handling
- Invalid JSON output from SLM
- Text-not-found (hallucinated spans)
- Fallback path CURRENT behavior (KNOWN HONESTY BUG)
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from vaultproxy.config import settings
from vaultproxy.gemma_layer import (
    GemmaLayerError,
    _heuristic_gemma_fallback,
    parse_gemma_json,
    run_gemma_detection,
)


def test_gemma_backend_off():
    """Test backend=off returns empty spans immediately."""
    async def _run():
        with patch.object(settings, "GEMMA_BACKEND", "off"):
            spans, degraded, gemma_used = await run_gemma_detection("Rajesh lives in Delhi")
            assert spans == []
            assert degraded is False
            assert gemma_used is False
    asyncio.run(_run())


def test_gemma_ollama_success():
    """Test successful Ollama backend response parsing."""
    async def _run():
        mock_ollama_response = {
            "message": {
                "content": json.dumps([
                    {"text": "Rajesh Sharma", "type": "PERSON"},
                    {"text": "Bengaluru", "type": "ADDRESS"},
                ])
            }
        }
        mock_tags_response = {"models": [{"name": "gemma4:e2b"}]}

        async def mock_get(*args, **kwargs):
            return httpx.Response(200, json=mock_tags_response)

        async def mock_post(*args, **kwargs):
            return httpx.Response(200, json=mock_ollama_response)

        with patch.object(settings, "GEMMA_BACKEND", "ollama"):
            with patch("httpx.AsyncClient.get", side_effect=mock_get):
                with patch("httpx.AsyncClient.post", side_effect=mock_post):
                    text = "Rajesh Sharma lives in Bengaluru."
                    spans, degraded, gemma_used = await run_gemma_detection(text)

                    assert len(spans) == 2
                    assert degraded is False
                    assert gemma_used is True
                    assert spans[0].type == "PERSON"
                    assert spans[0].source == "gemma"
                    assert text[spans[0].start : spans[0].end] == "Rajesh Sharma"
                    assert spans[1].type == "ADDRESS"
                    assert text[spans[1].start : spans[1].end] == "Bengaluru"
    asyncio.run(_run())


def test_gemma_gemini_success():
    """Test successful Gemini backend response parsing."""
    async def _run():
        mock_gemini_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps([
                                    {"text": "Aarav", "type": "PERSON"}
                                ])
                            }
                        ]
                    }
                }
            ]
        }

        req = httpx.Request("POST", "https://generativelanguage.googleapis.com")

        async def mock_post(*args, **kwargs):
            return httpx.Response(200, json=mock_gemini_response, request=req)

        with patch.object(settings, "GEMMA_BACKEND", "gemini"):
            with patch.object(settings, "GEMINI_API_KEY", "test_key"):
                with patch("httpx.AsyncClient.post", side_effect=mock_post):
                    text = "Aarav is here."
                    spans, degraded, gemma_used = await run_gemma_detection(text)

                    assert len(spans) == 1
                    assert spans[0].type == "PERSON"
                    assert text[spans[0].start : spans[0].end] == "Aarav"
    asyncio.run(_run())


def test_gemma_timeout_strict_mode():
    """Test timeout in strict mode raises GemmaLayerError."""
    async def _run():
        with patch.object(settings, "GEMMA_BACKEND", "ollama"):
            with patch.object(settings, "STRICT_MODE", True):
                with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout")):
                    with pytest.raises(GemmaLayerError):
                        await run_gemma_detection("Test sentence")
    asyncio.run(_run())


def test_gemma_invalid_json_handling():
    """Test handling of invalid JSON response from SLM."""
    raw_invalid = "This is not valid JSON at all"
    spans = parse_gemma_json(raw_invalid, "Some text")
    assert spans == []


def test_gemma_dict_format_variations():
    """Test parse_gemma_json handling of dict formats (entities array, dict mapping)."""
    text = "Ramesh Kumar lives at Flat 101, MG Road, Delhi."
    json_entities = json.dumps({"entities": [{"text": "Ramesh Kumar", "type": "PERSON"}]})
    spans1 = parse_gemma_json(json_entities, text)
    assert len(spans1) == 1

    json_dict_map = json.dumps({"PERSON": "Ramesh Kumar", "ADDRESS": "Flat 101, MG Road, Delhi"})
    spans2 = parse_gemma_json(json_dict_map, text)
    assert len(spans2) == 2

    json_dict_lists = json.dumps({"PERSON": ["Ramesh Kumar"], "ADDRESS": ["Flat 101, MG Road, Delhi"]})
    spans3 = parse_gemma_json(json_dict_lists, text)
    assert len(spans3) == 2


def test_gemma_text_not_found_hallucination_discarded():
    """Test that entities not found in original text are discarded."""
    text = "Vikram lives in Mumbai."
    raw_gemma_json = json.dumps([
        {"text": "Vikram", "type": "PERSON"},
        {"text": "NonExistent Person", "type": "PERSON"},
    ])
    spans = parse_gemma_json(raw_gemma_json, text)
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == "Vikram"


def test_gemma_fallback_path_current_behaviour():
    """KNOWN HONESTY BUG, changes in Phase 1:
    Currently, _heuristic_gemma_fallback labels spans with source="gemma" and degraded=False.
    This test freezes current behaviour until Phase 1 applies honesty fixes H1 & H2.
    """
    async def _run():
        text = "Rajesh Sharma lives at Flat 402, Green Glen Layout, Bellandur, Bengaluru."
        spans = _heuristic_gemma_fallback(text)

        assert len(spans) >= 1
        # KNOWN HONESTY BUG: currently source is marked "gemma" instead of "heuristic"
        assert spans[0].source == "gemma"

        with patch.object(settings, "GEMMA_BACKEND", "auto"):
            with patch.object(settings, "STRICT_MODE", False):
                with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Ollama down")):
                    res_spans, degraded, gemma_used = await run_gemma_detection(text)
                    # KNOWN HONESTY BUG: currently degraded is False on fallback path
                    assert degraded is False
                    assert gemma_used is True
                    assert len(res_spans) >= 1
    asyncio.run(_run())
