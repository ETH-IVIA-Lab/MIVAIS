"""MongoDB connection lifecycle."""
from __future__ import annotations

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from studio.models import ALL_DOCUMENTS
from studio.settings import get_settings


_client: AsyncIOMotorClient | None = None


async def connect() -> None:
    """Open the Mongo connection and register Beanie documents."""
    global _client
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongo_url)
    await init_beanie(database=_client[settings.mongo_db], document_models=ALL_DOCUMENTS)


async def disconnect() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def client() -> AsyncIOMotorClient:
    if _client is None:
        raise RuntimeError("MongoDB not connected — call connect() first")
    return _client
