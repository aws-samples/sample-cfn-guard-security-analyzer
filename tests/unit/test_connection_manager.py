"""Unit tests for the in-memory ConnectionManager.

Tests cover connect, disconnect, subscribe, and broadcast methods,
including stale connection cleanup.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from service.connection_manager import ConnectionManager, manager


@pytest.fixture
def cm():
    """Fresh ConnectionManager for each test."""
    return ConnectionManager()


def _make_ws(*, fail_send: bool = False) -> MagicMock:
    """Create a mock WebSocket. If fail_send is True, send_json raises."""
    ws = MagicMock()
    if fail_send:
        ws.send_json = AsyncMock(side_effect=Exception("connection closed"))
    else:
        ws.send_json = AsyncMock()
    return ws


# --- connect ---

@pytest.mark.asyncio
async def test_connect_stores_connection(cm):
    ws = _make_ws()
    await cm.connect("conn-1", ws)
    assert "conn-1" in cm.active_connections
    assert cm.active_connections["conn-1"] is ws


@pytest.mark.asyncio
async def test_connect_multiple_connections(cm):
    ws1, ws2 = _make_ws(), _make_ws()
    await cm.connect("a", ws1)
    await cm.connect("b", ws2)
    assert len(cm.active_connections) == 2


# --- disconnect ---

@pytest.mark.asyncio
async def test_disconnect_removes_connection(cm):
    ws = _make_ws()
    await cm.connect("conn-1", ws)
    cm.disconnect("conn-1")
    assert "conn-1" not in cm.active_connections


def test_disconnect_nonexistent_is_noop(cm):
    cm.disconnect("does-not-exist")  # should not raise


@pytest.mark.asyncio
async def test_disconnect_removes_from_all_subscriptions(cm):
    ws = _make_ws()
    await cm.connect("conn-1", ws)
    await cm.subscribe("conn-1", "analysis-a")
    await cm.subscribe("conn-1", "analysis-b")
    cm.disconnect("conn-1")
    assert "conn-1" not in cm.subscriptions.get("analysis-a", set())
    assert "conn-1" not in cm.subscriptions.get("analysis-b", set())


@pytest.mark.asyncio
async def test_disconnect_cleans_up_empty_subscription_sets(cm):
    ws = _make_ws()
    await cm.connect("conn-1", ws)
    await cm.subscribe("conn-1", "analysis-a")
    cm.disconnect("conn-1")
    # The subscription set for analysis-a should be removed entirely
    assert "analysis-a" not in cm.subscriptions


@pytest.mark.asyncio
async def test_disconnect_preserves_other_subscribers(cm):
    ws1, ws2 = _make_ws(), _make_ws()
    await cm.connect("c1", ws1)
    await cm.connect("c2", ws2)
    await cm.subscribe("c1", "analysis-x")
    await cm.subscribe("c2", "analysis-x")
    cm.disconnect("c1")
    assert cm.subscriptions["analysis-x"] == {"c2"}


# --- subscribe ---

@pytest.mark.asyncio
async def test_subscribe_creates_subscription(cm):
    ws = _make_ws()
    await cm.connect("conn-1", ws)
    await cm.subscribe("conn-1", "analysis-1")
    assert "conn-1" in cm.subscriptions["analysis-1"]


@pytest.mark.asyncio
async def test_subscribe_multiple_connections_to_same_analysis(cm):
    ws1, ws2 = _make_ws(), _make_ws()
    await cm.connect("c1", ws1)
    await cm.connect("c2", ws2)
    await cm.subscribe("c1", "analysis-1")
    await cm.subscribe("c2", "analysis-1")
    assert cm.subscriptions["analysis-1"] == {"c1", "c2"}


@pytest.mark.asyncio
async def test_subscribe_same_connection_to_multiple_analyses(cm):
    ws = _make_ws()
    await cm.connect("conn-1", ws)
    await cm.subscribe("conn-1", "a1")
    await cm.subscribe("conn-1", "a2")
    assert "conn-1" in cm.subscriptions["a1"]
    assert "conn-1" in cm.subscriptions["a2"]


@pytest.mark.asyncio
async def test_subscribe_idempotent(cm):
    ws = _make_ws()
    await cm.connect("conn-1", ws)
    await cm.subscribe("conn-1", "a1")
    await cm.subscribe("conn-1", "a1")
    assert cm.subscriptions["a1"] == {"conn-1"}


# --- broadcast ---

@pytest.mark.asyncio
async def test_broadcast_sends_to_subscribed_connections(cm):
    ws1, ws2 = _make_ws(), _make_ws()
    await cm.connect("c1", ws1)
    await cm.connect("c2", ws2)
    await cm.subscribe("c1", "analysis-1")
    await cm.subscribe("c2", "analysis-1")

    msg = {"status": "IN_PROGRESS", "progress": 50}
    await cm.broadcast("analysis-1", msg)

    ws1.send_json.assert_awaited_once_with(msg)
    ws2.send_json.assert_awaited_once_with(msg)


@pytest.mark.asyncio
async def test_broadcast_does_not_send_to_unsubscribed(cm):
    ws1, ws2 = _make_ws(), _make_ws()
    await cm.connect("c1", ws1)
    await cm.connect("c2", ws2)
    await cm.subscribe("c1", "analysis-1")
    # c2 is NOT subscribed to analysis-1

    await cm.broadcast("analysis-1", {"data": "test"})

    ws1.send_json.assert_awaited_once()
    ws2.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_to_nonexistent_analysis_is_noop(cm):
    await cm.broadcast("no-such-analysis", {"data": "test"})
    # Should not raise


@pytest.mark.asyncio
async def test_broadcast_removes_stale_connections(cm):
    live_ws = _make_ws()
    stale_ws = _make_ws(fail_send=True)
    await cm.connect("live", live_ws)
    await cm.connect("stale", stale_ws)
    await cm.subscribe("live", "a1")
    await cm.subscribe("stale", "a1")

    await cm.broadcast("a1", {"update": True})

    # Live connection received the message
    live_ws.send_json.assert_awaited_once()
    # Stale connection was removed
    assert "stale" not in cm.active_connections
    assert "stale" not in cm.subscriptions.get("a1", set())


@pytest.mark.asyncio
async def test_broadcast_stale_cleanup_removes_from_all_subscriptions(cm):
    stale_ws = _make_ws(fail_send=True)
    await cm.connect("stale", stale_ws)
    await cm.subscribe("stale", "a1")
    await cm.subscribe("stale", "a2")

    # Broadcast on a1 triggers stale detection
    await cm.broadcast("a1", {"update": True})

    # Stale connection removed from both subscriptions
    assert "stale" not in cm.subscriptions.get("a1", set())
    assert "stale" not in cm.subscriptions.get("a2", set())
    assert "stale" not in cm.active_connections


@pytest.mark.asyncio
async def test_broadcast_skips_connection_not_in_active(cm):
    """If a subscription references a connection_id that's not in active_connections,
    broadcast should skip it without error."""
    cm.subscriptions["a1"] = {"ghost-conn"}
    await cm.broadcast("a1", {"data": "test"})
    # No error raised, ghost-conn just skipped


# --- singleton ---

def test_module_level_singleton_exists():
    assert isinstance(manager, ConnectionManager)
