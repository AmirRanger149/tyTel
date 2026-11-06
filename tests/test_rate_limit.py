from __future__ import annotations

import unittest

from core.config import Settings
from core.rate_limit import RateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int, nx: bool = False) -> bool:
        if nx and key in self.expirations:
            return False
        self.expirations[key] = seconds
        return True


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_five_links_per_user_per_minute(self) -> None:
        now = [120.0]
        redis = FakeRedis()
        limiter = RateLimiter(redis, Settings(), clock=lambda: now[0])
        results = [
            await limiter.allow(user_id=42, chat_id=-100)
            for _ in range(6)
        ]
        self.assertEqual(results, [True] * 5 + [False])
        self.assertTrue(all(ttl == 61 for ttl in redis.expirations.values()))
        now[0] += 60
        self.assertTrue(await limiter.allow(user_id=42, chat_id=-100))

    async def test_users_have_independent_counters(self) -> None:
        limiter = RateLimiter(FakeRedis(), Settings(user_rate_limit=1))
        self.assertTrue(await limiter.allow(user_id=1, chat_id=-100))
        self.assertFalse(await limiter.allow(user_id=1, chat_id=-100))
        self.assertTrue(await limiter.allow(user_id=2, chat_id=-100))

    async def test_optional_group_limit(self) -> None:
        limiter = RateLimiter(
            FakeRedis(), Settings(user_rate_limit=10, group_rate_limit=2)
        )
        self.assertTrue(await limiter.allow(user_id=1, chat_id=-100))
        self.assertTrue(await limiter.allow(user_id=2, chat_id=-100))
        self.assertFalse(await limiter.allow(user_id=3, chat_id=-100))
        self.assertTrue(await limiter.allow(user_id=3, chat_id=-200))

    async def test_zero_disables_group_limit(self) -> None:
        limiter = RateLimiter(
            FakeRedis(), Settings(user_rate_limit=10, group_rate_limit=0)
        )
        for _ in range(5):
            self.assertTrue(await limiter.allow(user_id=1, chat_id=-100))


if __name__ == "__main__":
    unittest.main()
