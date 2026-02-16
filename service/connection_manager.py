"""In-memory WebSocket connection manager.

Tracks active WebSocket connections and analysis subscriptions.
Used by the WebSocket router and callbacks router to manage
real-time communication with clients.

Requirements: 3.1, 3.2, 3.4, 3.5, 3.6
"""

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and analysis subscriptions in memory.

    Since the service runs as a single pod, an in-memory dict maps
    connection_id -> WebSocket object, allowing direct message sending
    without the API Gateway Management API.
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}
        self.subscriptions: dict[str, set[str]] = {}  # analysisId -> set of connection_ids

    async def connect(self, connection_id: str, ws: WebSocket) -> None:
        """Register a new WebSocket connection."""
        self.active_connections[connection_id] = ws

    def disconnect(self, connection_id: str) -> None:
        """Remove a connection and clean up all its subscriptions."""
        self.active_connections.pop(connection_id, None)
        for analysis_id in list(self.subscriptions):
            self.subscriptions[analysis_id].discard(connection_id)
            if not self.subscriptions[analysis_id]:
                del self.subscriptions[analysis_id]

    async def subscribe(self, connection_id: str, analysis_id: str) -> None:
        """Subscribe a connection to an analysis ID for broadcast updates."""
        self.subscriptions.setdefault(analysis_id, set()).add(connection_id)

    async def broadcast(self, analysis_id: str, message: dict) -> None:
        """Broadcast a message to all connections subscribed to an analysis.

        Stale connections that fail to receive the message are automatically
        disconnected and cleaned up.
        """
        connection_ids = self.subscriptions.get(analysis_id, set()).copy()
        stale: list[str] = []
        for cid in connection_ids:
            ws = self.active_connections.get(cid)
            if ws:
                try:
                    await ws.send_json(message)
                except Exception:
                    stale.append(cid)
        for cid in stale:
            self.disconnect(cid)


# Module-level singleton for use by routers
manager = ConnectionManager()
