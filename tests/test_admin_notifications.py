from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from core.cache import Database
from core.config import Settings
from core.messages import ADMIN_COOKIE_WARNING, SERVICE_UNAVAILABLE
from worker.errors import AuthenticationRequired
from worker.tasks import (
    ADMIN_COOKIE_NOTICE_KEY,
    _notify_cookie_expiry,
    download_and_send,
)
from tests.test_worker import FakeLock


class AuthenticationFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_retry_group_notice_and_hourly_admin_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = Database(root / "cache.db")
            await db.initialize()
            redis = Mock()
            redis.lock.return_value = FakeLock()
            redis.set = AsyncMock(return_value=True)
            send_message = AsyncMock()
            settings = Settings(temp_dir=root / "tmp", admin_chat_id=12345)
            ctx = {
                "bot": SimpleNamespace(send_message=send_message),
                "db": db,
                "redis": redis,
                "settings": settings,
                "downloader": SimpleNamespace(
                    download=AsyncMock(
                        side_effect=AuthenticationRequired(
                            "Sign in to confirm you're not a bot"
                        )
                    )
                ),
                "job_try": 1,
            }
            await download_and_send(
                ctx,
                chat_id=-100123,
                message_id=42,
                user_id=7,
                url="https://www.youtube.com/watch?v=video123",
                audio_only=False,
                quality="video-720p",
                max_duration=600,
            )
            self.assertEqual(send_message.await_count, 2)
            group_call, admin_call = send_message.await_args_list
            self.assertEqual(group_call.args[:2], (-100123, SERVICE_UNAVAILABLE))
            self.assertNotIn("کوکی", group_call.args[1])
            self.assertEqual(admin_call.args, (12345, ADMIN_COOKIE_WARNING))
            redis.set.assert_awaited_once_with(
                ADMIN_COOKIE_NOTICE_KEY, "1", ex=3600, nx=True
            )
            self.assertEqual(list((root / "tmp").iterdir()), [])

    async def test_second_notice_within_hour_is_suppressed(self) -> None:
        redis = SimpleNamespace(set=AsyncMock(side_effect=[True, False]))
        send_message = AsyncMock()
        ctx = {"redis": redis, "bot": SimpleNamespace(send_message=send_message)}
        settings = Settings(admin_chat_id=12345)
        await _notify_cookie_expiry(ctx, settings)
        await _notify_cookie_expiry(ctx, settings)
        send_message.assert_awaited_once_with(12345, ADMIN_COOKIE_WARNING)
        self.assertEqual(redis.set.await_count, 2)


if __name__ == "__main__":
    unittest.main()
