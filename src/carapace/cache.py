from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from carapace.models import CacheConfig


class SessionListCache:
    def __init__(self, config: CacheConfig):
        self._ttl_seconds = config.ttl_seconds
        self._redis_url = config.redis_url
        self._redis_client: Redis | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._redis_client is not None:
            return

        client = Redis.from_url(self._redis_url, decode_responses=True)
        try:
            await client.ping()
        except (OSError, RedisError, ValueError) as exc:
            await client.aclose()
            raise RuntimeError(f"Failed to connect session list cache to Redis at {self._redis_url}: {exc}") from exc

        self._redis_client = client
        logger.info(f"Session list cache enabled (redis={self._redis_url}, ttl={self._ttl_seconds}s)")

    async def close(self) -> None:
        if self._redis_client is not None:
            await self._redis_client.aclose()
            self._redis_client = None

    async def get_session_ids(self, *, include_archived: bool, loader: Callable[[], list[str]]) -> list[str]:
        cache_key = self._cache_key(include_archived)

        redis_cached = await self._redis_get(cache_key)
        if redis_cached is not None:
            return redis_cached

        session_ids = loader()
        await self._redis_set(cache_key, session_ids)
        return session_ids

    async def invalidate(self) -> None:
        if self._redis_client is None:
            raise RuntimeError("Session list cache has not been started")
        try:
            await self._redis_client.delete(self._cache_key(False), self._cache_key(True))
        except (OSError, RedisError) as exc:
            logger.warning(f"Failed to invalidate Redis session list cache: {exc}")

    def invalidate_sync(self) -> None:
        if self._redis_client is None or self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(lambda: self._loop.create_task(self.invalidate()))

    def _cache_key(self, include_archived: bool) -> str:
        return f"carapace:sessions:sorted:{int(include_archived)}"

    async def _redis_get(self, cache_key: str) -> list[str] | None:
        if self._redis_client is None:
            raise RuntimeError("Session list cache has not been started")
        try:
            cached = await self._redis_client.get(cache_key)
        except (OSError, RedisError) as exc:
            logger.warning(f"Failed to read Redis session list cache: {exc}")
            return None
        if cached is None:
            return None
        try:
            decoded = json.loads(cached)
        except json.JSONDecodeError as exc:
            logger.warning(f"Ignoring malformed Redis session list cache entry {cache_key}: {exc}")
            return None
        if not isinstance(decoded, list) or not all(isinstance(session_id, str) for session_id in decoded):
            logger.warning(f"Ignoring unexpected Redis session list cache payload for {cache_key}")
            return None
        return decoded

    async def _redis_set(self, cache_key: str, session_ids: list[str]) -> None:
        if self._redis_client is None:
            raise RuntimeError("Session list cache has not been started")
        try:
            await self._redis_client.set(cache_key, json.dumps(session_ids), ex=self._ttl_seconds)
        except (OSError, RedisError) as exc:
            logger.warning(f"Failed to write Redis session list cache: {exc}")
