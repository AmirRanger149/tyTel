from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers.media import quality_keyboard
from bot.handlers.quality import handle_quality_selection, parse_quality_callback
from core.cache import Database
from core.config import Settings
from core.messages import QUALITY_EXPIRED, QUALITY_NOT_YOURS, QUALITY_SELECTED
from core.pending import PendingDownload, store_pending_download
from tests.test_pending import FakeRedis

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
CHAT_ID = -100123


def _callback(token: str, height: int, *, user_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        data=f"tyq:{token}:{height}",
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=CHAT_ID),
            message_id=99,
            edit_text=AsyncMock(),
        ),
        answer=AsyncMock(),
        bot=SimpleNamespace(send_video=AsyncMock(), send_audio=AsyncMock()),
    )


class KeyboardTests(unittest.TestCase):
    def test_keyboard_offers_each_height_within_callback_limit(self) -> None:
        keyboard = quality_keyboard("abcdef012345")
        buttons = keyboard.inline_keyboard[0]
        self.assertEqual(
            [b.text for b in buttons], ["1080p", "720p", "480p", "360p"]
        )
        for button in buttons:
            self.assertTrue(button.callback_data.startswith("tyq:abcdef012345:"))
            # Telegram rejects callback data longer than 64 bytes.
            self.assertLessEqual(len(button.callback_data.encode()), 64)


class ParseCallbackTests(unittest.TestCase):
    def test_valid_and_invalid_callback_data(self) -> None:
        self.assertEqual(
            parse_quality_callback("tyq:abcdef012345:480"), ("abcdef012345", 480)
        )
        for bad in (None, "", "tyq:", "tyq:abc", "tyq:abc:1440", "tyq:abc:xyz",
                    "other:abc:480", "tyq:abc:480:extra"):
            with self.subTest(bad=bad):
                self.assertIsNone(parse_quality_callback(bad))


class QualitySelectionTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self, temp: str) -> tuple[Database, FakeRedis, str]:
        db = Database(Path(temp) / "cache.db")
        await db.initialize()
        redis = FakeRedis()
        token = await store_pending_download(
            redis,
            PendingDownload(
                chat_id=CHAT_ID, message_id=42, user_id=7,
                url=URL, max_duration=600,
            ),
            ttl_seconds=600,
        )
        return db, redis, token  # type: ignore[return-value]

    async def test_owner_selection_enqueues_at_chosen_quality(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db, redis, token = await self._setup(temp)
            queue = SimpleNamespace(enqueue_job=AsyncMock())
            callback = _callback(token, 480)
            await handle_quality_selection(
                callback, queue=queue, settings=Settings(), db=db, redis=redis
            )
            queue.enqueue_job.assert_awaited_once()
            args, kwargs = queue.enqueue_job.call_args
            self.assertEqual(args[0], "download_and_send")
            self.assertEqual(kwargs["quality"], "video-480p")
            self.assertEqual(kwargs["url"], URL)
            self.assertEqual(kwargs["message_id"], 42)
            self.assertFalse(kwargs["audio_only"])
            callback.message.edit_text.assert_awaited_once_with(
                QUALITY_SELECTED.format(height=480)
            )
            # The prompt was claimed: tapping again reports it as expired.
            second = _callback(token, 480)
            await handle_quality_selection(
                second, queue=queue, settings=Settings(), db=db, redis=redis
            )
            second.answer.assert_awaited_once_with(
                QUALITY_EXPIRED, show_alert=True
            )
            queue.enqueue_job.assert_awaited_once()

    async def test_stranger_tap_does_not_consume_the_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db, redis, token = await self._setup(temp)
            queue = SimpleNamespace(enqueue_job=AsyncMock())
            stranger = _callback(token, 720, user_id=999)
            await handle_quality_selection(
                stranger, queue=queue, settings=Settings(), db=db, redis=redis
            )
            stranger.answer.assert_awaited_once_with(
                QUALITY_NOT_YOURS, show_alert=True
            )
            queue.enqueue_job.assert_not_awaited()
            # The real sender can still pick afterwards.
            owner = _callback(token, 360)
            await handle_quality_selection(
                owner, queue=queue, settings=Settings(), db=db, redis=redis
            )
            queue.enqueue_job.assert_awaited_once()
            self.assertEqual(
                queue.enqueue_job.call_args.kwargs["quality"], "video-360p"
            )

    async def test_expired_prompt_enqueues_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            queue = SimpleNamespace(enqueue_job=AsyncMock())
            callback = _callback("abcdef012345", 720)
            await handle_quality_selection(
                callback, queue=queue, settings=Settings(),
                db=db, redis=FakeRedis(),
            )
            callback.answer.assert_awaited_once_with(
                QUALITY_EXPIRED, show_alert=True
            )
            queue.enqueue_job.assert_not_awaited()

    async def test_cached_quality_is_sent_without_queueing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db, redis, token = await self._setup(temp)
            await db.store_cached(URL, "video-360p", "cached-file", "video")
            queue = SimpleNamespace(enqueue_job=AsyncMock())
            callback = _callback(token, 360)
            await handle_quality_selection(
                callback, queue=queue, settings=Settings(), db=db, redis=redis
            )
            queue.enqueue_job.assert_not_awaited()
            callback.bot.send_video.assert_awaited_once()
            self.assertEqual(
                callback.bot.send_video.await_args.kwargs["video"], "cached-file"
            )


if __name__ == "__main__":
    unittest.main()
