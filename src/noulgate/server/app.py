"""
noulgate.server.app
===================
FastAPI application factory and instance for NoulGate proxy.
"""

from __future__ import annotations

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from noulgate.server.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)


def create_app() -> FastAPI:
    """Create and configure the NoulGate FastAPI application."""
    application = FastAPI(
        title="NoulGate",
        description="High-speed System 1 MCP tool gateway powered by TypeSafe AI's Jev.",
        version="0.1.0",
        docs_url="/docs",
    )

    # Enable CORS for browser frontends, extensions, and web dashboards
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    application.include_router(router)

    return application


# Global application instance for uvicorn
app = create_app()
