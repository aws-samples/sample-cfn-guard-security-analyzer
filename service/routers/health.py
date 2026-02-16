"""Health check router.

Exposes GET /health for ALB and Kubernetes liveness/readiness probes.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}
