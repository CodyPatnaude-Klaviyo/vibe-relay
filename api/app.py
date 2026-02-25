"""FastAPI application for vibe-relay.

Provides REST endpoints for board operations and websocket for live updates.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="vibe-relay",
        description="Multi-agent coding orchestration system",
        version="0.1.0",
    )

    # Enable CORS for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/hello")
    async def hello() -> dict[str, str]:
        """Simple hello-world endpoint."""
        return {"message": "Hello, world!"}

    return app


# Create the app instance
app = create_app()
