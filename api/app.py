"""FastAPI application for vibe-relay."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import set_db_path
from api.routes import router, set_config
from api.ws import broadcast_events


def create_app(db_path: str, config: dict[str, Any] | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_path: Path to the SQLite database.
        config: Full vibe-relay config dict. If provided, enables the
                trigger processor for automatic agent dispatch.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        tasks: list[asyncio.Task[None]] = []
        tasks.append(asyncio.create_task(broadcast_events(db_path)))

        if config is not None:
            from runner.triggers import process_triggers

            tasks.append(asyncio.create_task(process_triggers(db_path, config)))

        yield

        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    set_db_path(db_path)
    set_config(config)

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
