"""FastAPI application entry point.

Creates the FastAPI app, configures CORS middleware, and registers routers.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="CloudFormation Security Analyzer")

# CORS middleware — Requirement 10.1
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Amz-Date",
        "X-Api-Key",
        "X-Amz-Security-Token",
    ],
)

# Router registration — routers are created in subsequent tasks.
# Each import is guarded so the app can start even before all routers exist.
try:
    from service.routers import health

    app.include_router(health.router)
except ImportError:
    pass

try:
    from service.routers import analysis

    app.include_router(analysis.router)
except ImportError:
    pass

try:
    from service.routers import reports

    app.include_router(reports.router)
except ImportError:
    pass

try:
    from service.routers import websocket

    app.include_router(websocket.router)
except ImportError:
    pass

try:
    from service.routers import callbacks

    app.include_router(callbacks.router)
except ImportError:
    pass
