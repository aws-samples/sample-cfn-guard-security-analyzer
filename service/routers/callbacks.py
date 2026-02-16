"""Callbacks router for Step Functions progress notifications.

Receives HTTP progress updates from the Step Functions workflow
and broadcasts them to subscribed WebSocket connections via the
in-memory ConnectionManager.

Requirements: 3.5, 5.1, 5.2
"""

from fastapi import APIRouter
from pydantic import BaseModel

from service.connection_manager import manager

router = APIRouter()


class ProgressUpdate(BaseModel):
    analysisId: str
    updateData: dict


@router.post("/callbacks/progress")
async def receive_progress(update: ProgressUpdate):
    """Receive a progress update and broadcast to subscribed WebSocket clients."""
    await manager.broadcast(update.analysisId, update.updateData)
    return {
        "status": "ok",
        "analysisId": update.analysisId,
        "message": "Progress update broadcast successfully",
    }
