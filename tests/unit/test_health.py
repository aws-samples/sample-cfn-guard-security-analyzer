"""Unit tests for the health check endpoint."""

from fastapi.testclient import TestClient
from service.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_healthy_status():
    response = client.get("/health")
    assert response.json() == {"status": "healthy"}
