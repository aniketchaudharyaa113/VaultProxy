import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from vaultproxy.config import settings
from vaultproxy.gemma_layer import (
    GemmaLayerError,
    parse_gemma_json,
    run_gemma_detection,
)
from vaultproxy.report import create_vault_report_header


def test_report_header_generation():
    masked_counts = {"PAN": 1, "MOBILE": 2}
    header_str = create_vault_report_header(
        masked_counts=masked_counts, degraded=False, gemma_used=True
    )
    data = json.loads(header_str)
    assert data["masked"] == {"PAN": 1, "MOBILE": 2}
    assert data["degraded"] is False
    assert data["gemma_used"] is True


def test_gemma_backend_off():
    with patch.object(settings, "GEMMA_BACKEND", "off"):
        spans, degraded, gemma_used = asyncio.run(
            run_gemma_detection("Aarav lives in Mumbai")
        )
        assert spans == []
        assert degraded is False
        assert gemma_used is False


def test_gemma_parse_verbatim_only():
    text = "Ramesh Kumar lives at Flat 302, MG Road, Bengaluru."
    raw_gemma_json = json.dumps(
        [
            {"text": "Ramesh Kumar", "type": "PERSON"},
            {"text": "Flat 302, MG Road, Bengaluru", "type": "ADDRESS"},
            {"text": "NonExistent Name", "type": "PERSON"},  # Rewritten / hallucinated name
        ]
    )

    spans = parse_gemma_json(raw_gemma_json, text)
    assert len(spans) == 2
    assert spans[0].type == "PERSON"
    assert text[spans[0].start : spans[0].end] == "Ramesh Kumar"
    assert spans[1].type == "ADDRESS"
    assert text[spans[1].start : spans[1].end] == "Flat 302, MG Road, Bengaluru"


def test_gemma_timeout_strict_mode_true():
    with patch.object(settings, "GEMMA_BACKEND", "ollama"):
        with patch.object(settings, "STRICT_MODE", True):
            with patch(
                "httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Timeout")
            ):
                with pytest.raises(GemmaLayerError):
                    asyncio.run(run_gemma_detection("Test sentence"))


def test_gemma_timeout_strict_mode_false():
    with patch.object(settings, "GEMMA_BACKEND", "ollama"):
        with patch.object(settings, "STRICT_MODE", False):
            with patch(
                "httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Timeout")
            ):
                spans, degraded, gemma_used = asyncio.run(
                    run_gemma_detection("Test sentence")
                )
                assert spans == []
                assert degraded is True
                assert gemma_used is True
