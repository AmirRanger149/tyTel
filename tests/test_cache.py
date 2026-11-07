from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.cache import CacheEntry, Database


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "cache.db")
        await self.db.initialize()

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def test_sqlite_uses_wal_and_busy_timeout(self) -> None:
        async with self.db.connect() as connection:
            journal = await connection.execute("PRAGMA journal_mode")
            busy = await connection.execute("PRAGMA busy_timeout")
            self.assertEqual((await journal.fetchone())[0].lower(), "wal")
            self.assertEqual((await busy.fetchone())[0], 30000)

    async def test_cache_is_scoped_by_url_and_quality(self) -> None:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.assertIsNone(await self.db.get_cached(url, "video-720p"))
        await self.db.store_cached(url, "video-720p", "video-id", "video")
        await self.db.store_cached(url, "audio", "audio-id", "audio")
        self.assertEqual(
            await self.db.get_cached(url, "video-720p"), CacheEntry("video-id", "video")
        )
        self.assertEqual(await self.db.get_cached(url, "audio"), CacheEntry("audio-id", "audio"))

    async def test_group_settings_default_and_persist(self) -> None:
        defaults = await self.db.get_group_settings(-1001)
        self.assertTrue(defaults.enabled)
        self.assertFalse(defaults.audio_only)
        self.assertIsNone(defaults.max_duration)
        await self.db.set_group_enabled(-1001, False)
        await self.db.set_group_duration(-1001, 300)
        await self.db.set_group_audio_only(-1001, True)
        updated = await self.db.get_group_settings(-1001)
        self.assertFalse(updated.enabled)
        self.assertTrue(updated.audio_only)
        self.assertEqual(updated.max_duration, 300)

    async def test_stale_cache_entry_can_be_replaced_and_deleted(self) -> None:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        await self.db.store_cached(url, "video-720p", "old", "video")
        await self.db.store_cached(url, "video-720p", "new", "video")
        self.assertEqual((await self.db.get_cached(url, "video-720p")).file_id, "new")
        await self.db.delete_cached(url, "video-720p")
        self.assertIsNone(await self.db.get_cached(url, "video-720p"))


if __name__ == "__main__":
    unittest.main()
