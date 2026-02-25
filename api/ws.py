"""WebSocket connection manager and event broadcaster for vibe-relay."""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

from api.deps import (
    enrich_event_payload,
    get_unconsumed_events,
    mark_event_consumed,
)
from db.client import get_connection

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected clients."""
        dead: list[WebSocket] = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active_connections.remove(ws)


manager = ConnectionManager()


async def broadcast_events(db_path: str) -> None:
    """Background task that polls events table and broadcasts to websocket clients.

    Runs every 500ms. Opens its own DB connection per poll cycle.
    """
    while True:
        try:
            conn = get_connection(db_path)
            try:
                events = get_unconsumed_events(conn)
                for event in events:
                    enriched = enrich_event_payload(conn, event)
                    await manager.broadcast(enriched)
                    mark_event_consumed(conn, event["id"])
            finally:
                conn.close()
        except Exception:
            logger.exception("Error in event broadcaster")
        await asyncio.sleep(0.5)
