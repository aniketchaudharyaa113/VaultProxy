import asyncio
import subprocess
import sys
from unittest.mock import patch

import httpx
import pytest

from vaultproxy.config import Settings, settings
from vaultproxy.gemma_layer import GemmaLayerError, circuit_breaker, run_gemma_detection
from vaultproxy.masking import MaskingEngine
from vaultproxy.server import startup_event


def test_b14_default_backend_is_off():
    """Default GEMMA_BACKEND must be 'off'."""
    s = Settings(_env_file=None)
    assert s.GEMMA_BACKEND == "off"


def test_b14_heuristic_fallback_deleted():
    """_heuristic_gemma_fallback must not exist in vaultproxy.gemma_layer."""
    import vaultproxy.gemma_layer as gl
    assert not hasattr(gl, "_heuristic_gemma_fallback")


def test_b14_invalid_gemma_backend_error():
    """Unknown backend raises ValueError listing allowed values."""
    with pytest.raises(ValueError, match="Allowed values are: gemini, off, ollama|Allowed values are: off, ollama, gemini"):
        Settings(_env_file=None, GEMMA_BACKEND="unknown")

    with pytest.raises(ValueError):
        Settings(_env_file=None, GEMMA_BACKEND="auto")


def test_b14_invalid_gemma_backend_no_traceback():
    """Starting with an unknown GEMMA_BACKEND prints readable error with allowed values and no traceback."""
    cmd = [
        sys.executable,
        "-c",
        "import os; os.environ['GEMMA_BACKEND'] = 'invalid_backend'; import vaultproxy.config",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "Traceback" not in (res.stdout + res.stderr)
    output = res.stdout + res.stderr
    assert "Invalid GEMMA_BACKEND" in output
    for allowed in ["off", "ollama", "gemini"]:
        assert allowed in output


def test_b14_no_hardcoded_name_masking_with_default_settings():
    """With default settings (GEMMA_BACKEND='off'), names like Aniket Chaudhary or Vikram are not masked."""
    from vaultproxy.vault import RequestVault
    engine = MaskingEngine(vault=RequestVault())
    text = "Hello, I am Aniket Chaudhary and my friend Vikram says hi."
    payload = {"messages": [{"role": "user", "content": text}]}
    with patch.object(settings, "GEMMA_BACKEND", "off"):
        masked_payload, degraded, gemma_used, _ = asyncio.run(engine.mask_payload(payload))
        masked_text = masked_payload["messages"][0]["content"]
        assert "Aniket Chaudhary" in masked_text
        assert "Vikram" in masked_text
        assert not engine.vault.has_tokens


def test_b14_startup_log_message(caplog):
    """Startup log must log 'Protection: rules only' when off, or 'rules + <model>' when enabled."""
    with patch.object(settings, "GEMMA_BACKEND", "off"):
        with caplog.at_level("INFO"):
            asyncio.run(startup_event())
            assert "Protection: rules only" in caplog.text

    caplog.clear()
    with patch.object(settings, "GEMMA_BACKEND", "ollama"), patch.object(settings, "GEMMA_MODEL", "gemma:2b"):
        with caplog.at_level("INFO"):
            asyncio.run(startup_event())
            assert "Protection: rules + gemma:2b" in caplog.text


def test_b14_failure_strict_vs_non_strict():
    """When ollama is configured but fails: strict raises GemmaLayerError, non-strict continues on rules (degraded=True)."""
    text = "Hello Rajesh Sharma"
    try:
        with patch.object(settings, "GEMMA_BACKEND", "ollama"), \
             patch.object(settings, "STRICT_MODE", True), \
             patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("down")), \
             patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("down")):
            with pytest.raises(GemmaLayerError):
                asyncio.run(run_gemma_detection(text))

        with patch.object(settings, "GEMMA_BACKEND", "ollama"), \
             patch.object(settings, "STRICT_MODE", False), \
             patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("down")), \
             patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("down")):
            spans, degraded, gemma_used = asyncio.run(run_gemma_detection(text))
            assert spans == []
            assert degraded is True
            assert gemma_used is False
    finally:
        circuit_breaker.record_success()
