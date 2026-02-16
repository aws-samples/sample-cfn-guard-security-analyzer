"""Unit tests for the callbacks router.

Tests cover the POST /callbacks/progress endpoint, verifying that
progress updates are broadcast to subscribed WebSocket connections
via the ConnectionManager.

Requirements: 3.5, 5.1, 5.2
"""

import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

os.environ.setdefault("ANALYSIS_TABLE_NAME", "test-analysis-table")
os.environ.setdefault("CONNECTION_TABLE_NAME", "test-connection-table")
os.environ.setdefault("REPORTS_BUCKET_NAME", "test-reports-bucket")
os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm")

from service.connection_manager import ConnectionManager


@pytest.fixture()
def mock_manager():
    """Create a fresh ConnectionManager with a mocked broadcast method."""
    mgr = ConnectionManager()
    mgr.broadcast = AsyncMock()
    return mgr


@pytest.fixture()
def client(mock_manager):
    with patch("service.routers.callbacks.manager", mock_manager):
        from fastapi.testclient import TestClient
        from service.main import app
        yield TestClient(app)


# ---------------------------------------------------------------------------
# POST /callbacks/progress — Requirement 3.5, 5.1, 5.2
# ---------------------------------------------------------------------------


def test_progress_broadcasts_update(client, mock_manager):
    """A valid progress update should be broadcast to subscribers."""
    payload = {
        "analysisId": "analysis-abc",
        "updateData": {"status": "IN_PROGRESS", "progress": 42},
    }
    resp = client.post("/callbacks/progress", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["analysisId"] == "analysis-abc"

    mock_manager.broadcast.assert_awaited_once_with(
        "analysis-abc", {"status": "IN_PROGRESS", "progress": 42}
    )


def test_progress_returns_correct_response_shape(client, mock_manager):
    """Response should contain status, analysisId, and message."""
    payload = {"analysisId": "a1", "updateData": {"step": "crawl"}}
    resp = client.post("/callbacks/progress", json=payload)

    body = resp.json()
    assert "status" in body
    assert "analysisId" in body
    assert "message" in body


def test_progress_with_empty_update_data(client, mock_manager):
    """An empty updateData dict should still succeed."""
    payload = {"analysisId": "a1", "updateData": {}}
    resp = client.post("/callbacks/progress", json=payload)

    assert resp.status_code == 200
    mock_manager.broadcast.assert_awaited_once_with("a1", {})


def test_progress_missing_analysis_id_returns_422(client, mock_manager):
    """Missing analysisId should return a validation error."""
    payload = {"updateData": {"progress": 50}}
    resp = client.post("/callbacks/progress", json=payload)
    assert resp.status_code == 422


def test_progress_missing_update_data_returns_422(client, mock_manager):
    """Missing updateData should return a validation error."""
    payload = {"analysisId": "a1"}
    resp = client.post("/callbacks/progress", json=payload)
    assert resp.status_code == 422


def test_progress_empty_body_returns_422(client, mock_manager):
    """An empty body should return a validation error."""
    resp = client.post("/callbacks/progress", json={})
    assert resp.status_code == 422


def test_progress_with_nested_update_data(client, mock_manager):
    """Nested updateData should be passed through to broadcast."""
    nested = {
        "step": "aggregate",
        "findings": [{"severity": "HIGH", "count": 3}],
        "metadata": {"elapsed": 12.5},
    }
    payload = {"analysisId": "deep-analysis", "updateData": nested}
    resp = client.post("/callbacks/progress", json=payload)

    assert resp.status_code == 200
    mock_manager.broadcast.assert_awaited_once_with("deep-analysis", nested)


def test_progress_no_subscribers_still_succeeds(client, mock_manager):
    """Broadcasting to an analysis with no subscribers should still return 200."""
    payload = {"analysisId": "no-subs", "updateData": {"done": True}}
    resp = client.post("/callbacks/progress", json=payload)

    assert resp.status_code == 200
    mock_manager.broadcast.assert_awaited_once()
