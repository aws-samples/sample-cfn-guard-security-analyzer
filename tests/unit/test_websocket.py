"""Unit tests for the WebSocket router.

Uses moto for DynamoDB mocking and FastAPI's TestClient WebSocket support.
"""

import os
import boto3
import pytest
from moto import mock_aws
from unittest.mock import patch

os.environ.setdefault("ANALYSIS_TABLE_NAME", "test-analysis-table")
os.environ.setdefault("CONNECTION_TABLE_NAME", "test-connection-table")
os.environ.setdefault("REPORTS_BUCKET_NAME", "test-reports-bucket")
os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm")

from service.connection_manager import ConnectionManager


def _create_connection_table(dynamodb_resource):
    """Create the mocked DynamoDB connection table."""
    table = dynamodb_resource.create_table(
        TableName=os.environ["CONNECTION_TABLE_NAME"],
        KeySchema=[{"AttributeName": "connectionId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "connectionId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


@pytest.fixture()
def aws_env():
    """Spin up moto DynamoDB and patch the connection_table used by the router."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_connection_table(ddb)

        # Fresh ConnectionManager for each test
        fresh_manager = ConnectionManager()

        with (
            patch("service.aws_clients.connection_table", table),
            patch("service.routers.websocket.connection_table", table),
            patch("service.routers.websocket.manager", fresh_manager),
        ):
            yield table, fresh_manager


@pytest.fixture()
def client(aws_env):
    from fastapi.testclient import TestClient
    from service.main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Connect — Requirement 3.1
# ---------------------------------------------------------------------------


def test_connect_stores_record_in_dynamodb(client, aws_env):
    table, mgr = aws_env
    with client.websocket_connect("/ws") as ws:
        # While connected, there should be exactly one record
        items = table.scan()["Items"]
        assert len(items) == 1
        item = items[0]
        assert "connectionId" in item
        assert "connectedAt" in item
        assert "ttl" in item


def test_connect_registers_in_manager(client, aws_env):
    _, mgr = aws_env
    with client.websocket_connect("/ws"):
        assert len(mgr.active_connections) == 1


def test_connect_ttl_is_approximately_2_hours(client, aws_env):
    from datetime import datetime, timedelta

    table, _ = aws_env
    expected_ttl = int((datetime.utcnow() + timedelta(hours=2)).timestamp())
    with client.websocket_connect("/ws"):
        items = table.scan()["Items"]
        ttl = int(items[0]["ttl"])
        # TTL should be within 60s of the expected value
        assert abs(ttl - expected_ttl) < 60


# ---------------------------------------------------------------------------
# Subscribe — Requirement 3.2
# ---------------------------------------------------------------------------


def test_subscribe_updates_dynamodb_and_manager(client, aws_env):
    table, mgr = aws_env
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "analysisId": "analysis-123"})
        resp = ws.receive_json()
        assert resp["message"] == "Subscribed to analysis analysis-123"

        # DynamoDB record should have analysisId
        items = table.scan()["Items"]
        assert items[0]["analysisId"] == "analysis-123"

        # Manager should track the subscription
        assert "analysis-123" in mgr.subscriptions
        conn_ids = mgr.subscriptions["analysis-123"]
        assert len(conn_ids) == 1


def test_subscribe_missing_analysis_id_returns_error(client, aws_env):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe"})
        resp = ws.receive_json()
        assert "error" in resp
        assert "Missing analysisId" in resp["error"]


# ---------------------------------------------------------------------------
# Ping — Requirement 3.3
# ---------------------------------------------------------------------------


def test_ping_returns_pong(client, aws_env):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "ping"})
        resp = ws.receive_json()
        assert resp["message"] == "pong"


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------


def test_unknown_action_returns_error(client, aws_env):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "foobar"})
        resp = ws.receive_json()
        assert "error" in resp
        assert "Unknown action: foobar" in resp["error"]


# ---------------------------------------------------------------------------
# Disconnect — Requirement 3.4
# ---------------------------------------------------------------------------


def test_disconnect_removes_from_dynamodb(client, aws_env):
    table, _ = aws_env
    with client.websocket_connect("/ws"):
        # Verify record exists while connected
        assert len(table.scan()["Items"]) == 1

    # After disconnect, record should be gone
    assert len(table.scan()["Items"]) == 0


def test_disconnect_removes_from_manager(client, aws_env):
    _, mgr = aws_env
    with client.websocket_connect("/ws"):
        assert len(mgr.active_connections) == 1

    assert len(mgr.active_connections) == 0


def test_disconnect_cleans_up_subscriptions(client, aws_env):
    _, mgr = aws_env
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "analysisId": "a1"})
        ws.receive_json()

    # After disconnect, subscription should be cleaned up
    assert "a1" not in mgr.subscriptions


# ---------------------------------------------------------------------------
# Multiple connections
# ---------------------------------------------------------------------------


def test_multiple_connections_tracked_independently(client, aws_env):
    table, mgr = aws_env
    with client.websocket_connect("/ws"):
        with client.websocket_connect("/ws"):
            assert len(table.scan()["Items"]) == 2
            assert len(mgr.active_connections) == 2

        # Inner connection disconnected
        assert len(table.scan()["Items"]) == 1
        assert len(mgr.active_connections) == 1

    # Both disconnected
    assert len(table.scan()["Items"]) == 0
    assert len(mgr.active_connections) == 0
