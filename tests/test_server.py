import pytest
import httpx
from fastapi.testclient import TestClient
from vaultproxy.server import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
