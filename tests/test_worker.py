from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from arq import Retry

from core.cache import Database
from core.config import Settings
from core.messages import ERROR
from worker.downloader import DownloadError
from worker.errors import TransientMediaError
from worker.tasks import download_and_send


class FakeLock:
    async def __aenter__(self) -> "FakeLock":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class WorkerCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_job_skips_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            await db.store_cached(url, "video-720p", "cached-file", "video")
            redis = Mock()
            redis.lock.return_value = FakeLock()
            bot = SimpleNamespace(send_video=AsyncMock())
            downloader = SimpleNamespace(download=AsyncMock())
            ctx = {
                "bot": bot,
                "db": db,
                "redis": redis,
                "downloader": downloader,
                "settings": Settings(temp_dir=Path(temp)),
                "job_try": 1,
            }
            await download_and_send(
                ctx,
                chat_id=-100123,
                message_id=42,
                user_id=7,
                url=url,
                audio_only=False,
                quality="video-720p",
                max_duration=600,
            )
            downloader.download.assert_not_awaited()
            bot.send_video.assert_awaited_once()
            self.assertEqual(bot.send_video.await_args.kwargs["video"], "cached-file")


class WorkerRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_failure_retries_with_backoff_and_cleans_up(self) -> None:
        send_message = AsyncMock()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = Database(root / "cache.db")
            await db.initialize()
            redis = Mock()
            redis.lock.return_value = FakeLock()
            downloader = SimpleNamespace(
                download=AsyncMock(side_effect=TransientMediaError("network timeout"))
            )
            ctx = {
                "bot": SimpleNamespace(send_message=send_message),
                "db": db,
                "redis": redis,
                "downloader": downloader,
                "settings": Settings(temp_dir=root / "tmp"),
                "job_try": 1,
            }
            with self.assertRaises(Retry) as raised:
                await download_and_send(
                    ctx, chat_id=-100123, message_id=42, user_id=7,
                    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    audio_only=False, quality="video-720p", max_duration=600,
                )
            self.assertEqual(raised.exception.defer_score, 2000)
            self.assertEqual(list((root / "tmp").iterdir()), [])
            send_message.assert_not_awaited()

    async def test_selected_quality_forwards_max_height_to_downloader(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = Database(root / "cache.db")
            await db.initialize()
            redis = Mock()
            redis.lock.return_value = FakeLock()
            downloader = SimpleNamespace(
                download=AsyncMock(side_effect=TransientMediaError("network timeout"))
            )
            ctx = {
                "bot": SimpleNamespace(send_message=AsyncMock()),
                "db": db,
                "redis": redis,
                "downloader": downloader,
                "settings": Settings(temp_dir=root / "tmp"),
                "job_try": 1,
            }
            with self.assertRaises(Retry):
                await download_and_send(
                    ctx, chat_id=-100123, message_id=42, user_id=7,
                    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    audio_only=False, quality="video-480p", max_duration=600,
                )
            self.assertEqual(
                downloader.download.await_args.kwargs["max_height"], 480
            )

    async def test_final_failure_replies_in_persian_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = Database(root / "cache.db")
            await db.initialize()
            redis = Mock()
            redis.lock.return_value = FakeLock()
            send_message = AsyncMock()
            downloader = SimpleNamespace(download=AsyncMock(side_effect=DownloadError()))
            ctx = {
                "bot": SimpleNamespace(send_message=send_message),
                "db": db,
                "redis": redis,
                "downloader": downloader,
                "settings": Settings(temp_dir=root / "tmp"),
                "job_try": 3,
            }
            await download_and_send(
                ctx, chat_id=-100123, message_id=42, user_id=7,
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                audio_only=False, quality="video-720p", max_duration=600,
            )
            send_message.assert_awaited_once()
            self.assertEqual(send_message.await_args.args[1], ERROR)
            self.assertEqual(list((root / "tmp").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
