from __future__ import annotations

import unittest
from typing import Any

from core.pending import (
    PendingDownload,
    claim_pending_download,
    store_pending_download,
)


class FakeRedis:
    """Minimal in-memory stand-in for the async Redis client."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, name: str, value: str, **kwargs: Any) -> bool:
        if kwargs.get("nx") and name in self.values:
            return False
        self.values[name] = value
        return True

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def getdel(self, name: str) -> str | None:
        return self.values.pop(name, None)


def _pending(**overrides: object) -> PendingDownload:
    values: dict[str, object] = {
        "chat_id": -100123,
        "message_id": 42,
        "user_id": 7,
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "max_duration": 600,
    }
    values.update(overrides)
    return PendingDownload(**values)  # type: ignore[arg-type]


class PendingDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_and_claim_round_trip_is_one_shot(self) -> None:
        redis = FakeRedis()
        token = await store_pending_download(redis, _pending(), ttl_seconds=600)
        self.assertEqual(len(token), 12)
        self.assertEqual(await claim_pending_download(redis, token), _pending())
        # A second claim (double tap / replay) finds nothing.
        self.assertIsNone(await claim_pending_download(redis, token))

    async def test_claim_rejects_unknown_and_malformed_tokens(self) -> None:
        redis = FakeRedis()
        self.assertIsNone(await claim_pending_download(redis, "deadbeefdead"))
        self.assertIsNone(await claim_pending_download(redis, ""))
        self.assertIsNone(await claim_pending_download(redis, "../etc/passwd"))
        self.assertIsNone(await claim_pending_download(redis, "not-hex-token!"))

    async def test_corrupt_stored_value_claims_as_none(self) -> None:
        redis = FakeRedis()
        redis.values["tytel:pending-quality:abcdef012345"] = "{not json"
        self.assertIsNone(await claim_pending_download(redis, "abcdef012345"))

    async def test_json_round_trip(self) -> None:
        pending = _pending()
        self.assertEqual(PendingDownload.from_json(pending.to_json()), pending)
        self.assertIsNone(PendingDownload.from_json("{}"))
        self.assertIsNone(PendingDownload.from_json("[]"))


if __name__ == "__main__":
    unittest.main()
