import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from vaultproxy.config import settings
from vaultproxy.server import app

client = TestClient(app)


def test_demo_endpoints_disabled_when_demo_mode_false():
    with patch.object(settings, "DEMO_MODE", False):
        res = client.get("/demo/status")
        assert res.status_code == 404

        res = client.post("/demo/analyze", json={"text": "test"})
        assert res.status_code == 404


def test_demo_status_endpoint():
    with patch.object(settings, "DEMO_MODE", True):
        res = client.get("/demo/status")
        assert res.status_code == 200
        data = res.json()
        assert "gemma_backend" in data
        assert "reachable" in data
        assert "demo_mode" in data


def test_demo_analyze_endpoint():
    with patch.object(settings, "DEMO_MODE", True):
        text = "My PAN is ABCPB1234F and phone is 9876543210."
        res = client.post("/demo/analyze", json={"text": text, "use_gemma": False})
        assert res.status_code == 200
        data = res.json()
        assert "spans" in data
        assert len(data["spans"]) == 2
        assert "masked_text" in data
        assert "[PAN_1]" in data["masked_text"]
        assert "timings_ms" in data


def test_demo_simulate_endpoint():
    with patch.object(settings, "DEMO_MODE", True):
        res = client.post("/demo/simulate", json={"mode": "gemma_down"})
        assert res.status_code == 200
        assert res.json()["simulated_gemma_down"] is True

        res_reset = client.post("/demo/simulate", json={"mode": "reset"})
        assert res_reset.status_code == 200
        assert res_reset.json()["simulated_gemma_down"] is False


def test_demo_benchmark_endpoint():
    with patch.object(settings, "DEMO_MODE", True):
        res = client.get("/demo/benchmark")
        assert res.status_code == 200
        data = res.json()
        assert "metrics" in data or "error" in data


def test_demo_stream_trace_endpoint():
    with patch.object(settings, "DEMO_MODE", True):
        text = "Test stream ABCPB1234F"
        res = client.post("/demo/stream-trace", json={"text": text})
        assert res.status_code == 200
        assert "data: " in res.text
