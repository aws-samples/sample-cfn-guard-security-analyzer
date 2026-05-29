"""Tests for lambda/websocket_handler.py.

Covers:
  - $connect writes a connection record (with TTL frozen by freezegun)
  - $disconnect deletes the connection record
  - subscribe action attaches an analysisId to the connection
  - ping returns pong
  - send_update_handler broadcasts to subscribers and cleans stale connections
"""
import importlib
import json
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from .conftest import (
    ANALYSIS_TABLE_NAME,
    CONNECTION_TABLE_NAME,
    _purge_handler_module,
)


@pytest.fixture
def ws(monkeypatch, connection_table, analysis_table):
    monkeypatch.setenv("CONNECTION_TABLE_NAME", CONNECTION_TABLE_NAME)
    monkeypatch.setenv("ANALYSIS_TABLE_NAME", ANALYSIS_TABLE_NAME)
    _purge_handler_module("websocket_handler")
    return importlib.import_module("websocket_handler")


def _ws_event(route, connection_id="conn-1", body=None, query=None):
    return {
        "requestContext": {
            "routeKey": route,
            "connectionId": connection_id,
            "domainName": "abcd.execute-api.us-east-1.amazonaws.com",
            "stage": "dev",
        },
        "body": json.dumps(body) if body else None,
        "queryStringParameters": query,
    }


# ── $connect ────────────────────────────────────────────────────────────────


@freeze_time("2026-05-23T00:00:00+00:00")
def test_connect_writes_connection_record_with_ttl(ws, connection_table):
    from datetime import datetime, timezone
    response = ws.lambda_handler(_ws_event("$connect", connection_id="abc"), None)
    assert response["statusCode"] == 200

    item = connection_table.get_item(Key={"connectionId": "abc"}).get("Item")
    assert item is not None
    assert item["connectionId"] == "abc"
    # Handler computes TTL as `now + 2h`. With time frozen at 2026-05-23T00:00:00Z,
    # the expected TTL is the epoch seconds for that instant + 7200.
    frozen = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)
    assert int(item["ttl"]) == int(frozen.timestamp()) + 2 * 3600
    assert item["connectedAt"] == "2026-05-23T00:00:00+00:00"


def test_connect_with_analysis_id_query(ws, connection_table):
    """If the client provides ?analysisId=..., it should be stored on the row."""
    response = ws.lambda_handler(
        _ws_event("$connect", connection_id="abc", query={"analysisId": "analysis-77"}),
        None,
    )
    assert response["statusCode"] == 200
    item = connection_table.get_item(Key={"connectionId": "abc"}).get("Item")
    assert item["analysisId"] == "analysis-77"


# ── $disconnect ─────────────────────────────────────────────────────────────


def test_disconnect_deletes_connection(ws, connection_table):
    connection_table.put_item(Item={"connectionId": "to-delete"})
    response = ws.lambda_handler(_ws_event("$disconnect", connection_id="to-delete"), None)
    assert response["statusCode"] == 200
    assert "Item" not in connection_table.get_item(Key={"connectionId": "to-delete"})


# ── subscribe ───────────────────────────────────────────────────────────────


def test_subscribe_updates_connection_with_analysis_id(ws, connection_table):
    connection_table.put_item(Item={"connectionId": "sub-1"})
    response = ws.lambda_handler(
        _ws_event(
            "$default",
            connection_id="sub-1",
            body={"action": "subscribe", "analysisId": "task-9"},
        ),
        None,
    )
    assert response["statusCode"] == 200
    item = connection_table.get_item(Key={"connectionId": "sub-1"}).get("Item")
    assert item["analysisId"] == "task-9"


def test_subscribe_without_analysis_id_returns_400(ws, connection_table):
    connection_table.put_item(Item={"connectionId": "sub-2"})
    response = ws.lambda_handler(
        _ws_event(
            "$default",
            connection_id="sub-2",
            body={"action": "subscribe"},
        ),
        None,
    )
    assert response["statusCode"] == 400


# ── ping ────────────────────────────────────────────────────────────────────


def test_ping_returns_pong(ws):
    response = ws.lambda_handler(
        _ws_event("$default", connection_id="p", body={"action": "ping"}), None
    )
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["message"] == "pong"


def test_unknown_action_returns_400(ws):
    response = ws.lambda_handler(
        _ws_event("$default", connection_id="p", body={"action": "nonsense"}),
        None,
    )
    assert response["statusCode"] == 400


# ── send_update_handler / broadcast ─────────────────────────────────────────


def test_broadcast_sends_to_all_matching_connections(ws, connection_table):
    """Two connections subscribed to analysis-1 should both receive the update."""
    connection_table.put_item(
        Item={"connectionId": "c1", "analysisId": "analysis-1"}
    )
    connection_table.put_item(
        Item={"connectionId": "c2", "analysisId": "analysis-1"}
    )
    connection_table.put_item(
        Item={"connectionId": "c3", "analysisId": "analysis-OTHER"}
    )

    apigw = MagicMock()
    apigw.exceptions.GoneException = type("GoneException", (Exception,), {})

    with patch("boto3.client", return_value=apigw):
        result = ws.send_update_handler(
            {
                "analysisId": "analysis-1",
                "updateData": {"step": "crawl", "status": "COMPLETED"},
                "connectionEndpoint": "https://abcd.execute-api.us-east-1.amazonaws.com/dev",
            },
            None,
        )

    assert result["statusCode"] == 200
    assert result["successCount"] == 2  # c1, c2
    # apigw.post_to_connection should have been called twice
    assert apigw.post_to_connection.call_count == 2


def test_broadcast_cleans_stale_connection_on_gone(ws, connection_table):
    """A GoneException from post_to_connection should delete the stale row."""
    connection_table.put_item(
        Item={"connectionId": "stale", "analysisId": "analysis-1"}
    )

    # Mock client that raises GoneException for ALL posts.
    apigw = MagicMock()

    class GoneException(Exception):
        pass

    apigw.exceptions.GoneException = GoneException

    def raise_gone(*args, **kwargs):
        raise GoneException("connection gone")

    apigw.post_to_connection.side_effect = raise_gone

    with patch("boto3.client", return_value=apigw):
        result = ws.send_update_handler(
            {
                "analysisId": "analysis-1",
                "updateData": {"step": "crawl"},
                "connectionEndpoint": "https://x.execute-api.us-east-1.amazonaws.com/dev",
            },
            None,
        )

    assert result["statusCode"] == 200
    assert result["successCount"] == 0
    assert "Item" not in connection_table.get_item(Key={"connectionId": "stale"})


def test_unknown_route_returns_400(ws):
    response = ws.lambda_handler(_ws_event("$bogus"), None)
    assert response["statusCode"] == 400
