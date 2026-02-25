"""FastAPI application for vibe-relay."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import set_db_path
from api.routes import router
from api.ws import broadcast_events


def create_app(db_path: str) -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        task = asyncio.create_task(broadcast_events(db_path))
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    set_db_path(db_path)

    app = FastAPI(title="vibe-relay", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app
