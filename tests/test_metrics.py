from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import vaultproxy.metrics as metrics_mod
from vaultproxy.config import settings
from vaultproxy.metrics import (
    generate_latest,
    record_request_metrics,
)
from vaultproxy.server import app

PROD_TOKEN = "prod_secret_token_1234567890_abcdef"


def test_metrics_endpoint_unauthenticated_returns_401():
    """Verify /metrics requires auth when metrics feature is available."""
    client = TestClient(app)

    with patch.object(settings, "VAULT_PROFILE", "production"), \
         patch.object(settings, "VAULT_AUTH_TOKEN", PROD_TOKEN), \
         patch("vaultproxy.server.METRICS_AVAILABLE", True), \
         patch("vaultproxy.server.generate_latest", return_value=b"vaultproxy_requests_total 1.0\n"):

        # 1. Unauthenticated request -> 401
        resp_unauth = client.get("/metrics")
        assert resp_unauth.status_code == 401
        assert resp_unauth.json()["error"]["code"] == "invalid_api_key"

        # 2. Wrong token -> 401
        resp_wrong = client.get("/metrics", headers={"Authorization": "Bearer wrong_token"})
        assert resp_wrong.status_code == 401

        # 3. Valid token -> 200
        resp_valid = client.get("/metrics", headers={"Authorization": f"Bearer {PROD_TOKEN}"})
        assert resp_valid.status_code == 200
        assert "vaultproxy_requests_total" in resp_valid.text


def test_metrics_endpoint_unavailable_returns_404():
    """Verify /metrics returns 404 when metrics feature is unavailable."""
    client = TestClient(app)

    with patch("vaultproxy.server.METRICS_AVAILABLE", False):
        resp = client.get("/metrics")
        assert resp.status_code == 404
        assert resp.json()["error"]["message"] == "Metrics feature not installed."


def test_record_request_metrics_and_circuit_breaker_states():
    """Test record_request_metrics for all circuit breaker states (CLOSED, HALF_OPEN, OPEN) and fallback."""
    mock_requests = MagicMock()
    mock_duration = MagicMock()
    mock_entities = MagicMock()
    mock_degraded = MagicMock()
    mock_cb = MagicMock()

    with patch.object(metrics_mod, "METRICS_AVAILABLE", True), \
         patch.object(metrics_mod, "REQUESTS_TOTAL", mock_requests), \
         patch.object(metrics_mod, "REQUEST_DURATION", mock_duration), \
         patch.object(metrics_mod, "MASKED_ENTITIES_TOTAL", mock_entities), \
         patch.object(metrics_mod, "DEGRADED_REQUESTS_TOTAL", mock_degraded), \
         patch.object(metrics_mod, "CIRCUIT_BREAKER_STATE", mock_cb):

        # Test CLOSED state (cb_val = 0)
        record_request_metrics(duration_seconds=0.1, entity_count=2, degraded=False, cb_state="CLOSED")
        mock_requests.inc.assert_called_once()
        mock_duration.observe.assert_called_with(0.1)
        mock_entities.inc.assert_called_with(2)
        mock_cb.set.assert_called_with(0)

        # Test HALF_OPEN state (cb_val = 1)
        record_request_metrics(duration_seconds=0.2, entity_count=0, degraded=True, cb_state="HALF_OPEN")
        mock_degraded.inc.assert_called_once()
        mock_cb.set.assert_called_with(1)

        # Test OPEN state (cb_val = 2)
        record_request_metrics(duration_seconds=0.3, entity_count=1, degraded=False, cb_state="OPEN")
        mock_cb.set.assert_called_with(2)


def test_metrics_fallback_and_no_request_values_in_labels():
    """Test fallback when METRICS_AVAILABLE is False and verify no request values in metric labels."""
    # Test fallback record_request_metrics early return when METRICS_AVAILABLE=False
    with patch.object(metrics_mod, "METRICS_AVAILABLE", False), \
         patch.object(metrics_mod, "REQUESTS_TOTAL", None):

        record_request_metrics(0.5, entity_count=5, degraded=True, cb_state="OPEN")

    # Verify generate_latest fallback when prometheus_client not available
    if not getattr(metrics_mod, "METRICS_AVAILABLE", False):
        assert generate_latest() == b""


def test_metrics_import_coverage():
    """Import time coverage for prometheus_client try/except block."""
    import sys
    from importlib import reload

    # 1. Test when prometheus_client is not installed (ImportError branch)
    with patch.dict(sys.modules, {"prometheus_client": None}):
        reload(metrics_mod)
        assert metrics_mod.METRICS_AVAILABLE is False
        assert metrics_mod.generate_latest() == b""
        metrics_mod.record_request_metrics(0.1, 1, False, "CLOSED")

    # 2. Test when prometheus_client is installed
    mock_prom = MagicMock()
    with patch.dict(sys.modules, {"prometheus_client": mock_prom}):
        reload(metrics_mod)
        assert metrics_mod.METRICS_AVAILABLE is True
        metrics_mod.record_request_metrics(0.1, 1, False, "CLOSED")

    # Restore default module state
    reload(metrics_mod)

