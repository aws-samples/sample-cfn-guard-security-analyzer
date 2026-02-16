"""WebSocket router for real-time client communication.

Ports the WebSocket lifecycle from lambda/websocket_handler.py to
FastAPI's native WebSocket support. Connections are tracked both in
DynamoDB (Connection_Store) and in the in-memory ConnectionManager.

Requirements: 3.1, 3.2, 3.3, 3.4
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from service.aws_clients import connection_table
from service.connection_manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    connection_id = str(uuid.uuid4())

    # Store connection in DynamoDB with 2-hour TTL (Requirement 3.1)
    ttl = int((datetime.utcnow() + timedelta(hours=2)).timestamp())
    connection_table.put_item(
        Item={
            "connectionId": connection_id,
            "connectedAt": datetime.utcnow().isoformat(),
            "ttl": ttl,
        }
    )

    # Register in the in-memory manager
    await manager.connect(connection_id, ws)

    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            if action == "subscribe":
                # Requirement 3.2
                analysis_id = data.get("analysisId")
                if not analysis_id:
                    await ws.send_json({"error": "Missing analysisId"})
                    continue

                connection_table.update_item(
                    Key={"connectionId": connection_id},
                    UpdateExpression="SET analysisId = :aid",
                    ExpressionAttributeValues={":aid": analysis_id},
                )
                await manager.subscribe(connection_id, analysis_id)
                await ws.send_json(
                    {"message": f"Subscribed to analysis {analysis_id}"}
                )

            elif action == "ping":
                # Requirement 3.3
                await ws.send_json({"message": "pong"})

            else:
                await ws.send_json({"error": f"Unknown action: {action}"})

    except WebSocketDisconnect:
        pass
    finally:
        # Requirement 3.4 — clean up on disconnect
        try:
            connection_table.delete_item(Key={"connectionId": connection_id})
        except Exception:
            pass
        manager.disconnect(connection_id)
