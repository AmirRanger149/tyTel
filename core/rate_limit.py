from __future__ import annotations

import time
from collections.abc import Callable

from redis.asyncio import Redis

from core.config import Settings


class RateLimiter:
    """Fixed-window link counters backed by Redis."""

    def __init__(
        self, redis: Redis, settings: Settings, clock: Callable[[], float] = time.time
    ) -> None:
        self.redis = redis
        self.settings = settings
        self.clock = clock

    async def allow(self, *, user_id: int, chat_id: int) -> bool:
        window = int(self.clock() // 60)
        if not await self._allow(
            f"tytel:rate:user:{user_id}:{window}", self.settings.user_rate_limit
        ):
            return False
        if self.settings.group_rate_limit and not await self._allow(
            f"tytel:rate:group:{chat_id}:{window}", self.settings.group_rate_limit
        ):
            return False
        return True

    async def _allow(self, key: str, limit: int) -> bool:
        count = int(await self.redis.incr(key))
        if count == 1:
            # Expire only newly created counters; do not extend active windows.
            await self.redis.expire(key, 61, nx=True)
        return count <= limit
