from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

from aiogram.types import Chat, Message, User

from bot.middlewares.group_guard import GroupGuardMiddleware
from core.cache import Database


def _message(text: str) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=-1001, type="supergroup"),
        from_user=User(id=7, is_bot=False, first_name="Alex"),
        text=text,
    )


class GroupGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_group_only_lets_control_commands_through(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            await db.set_group_enabled(-1001, False)
            guard = GroupGuardMiddleware()
            handler = AsyncMock(return_value="handled")
            data = {"db": db}
            for command in ("/ctl on", "/ctl", "/status", "/enable"):
                handler.reset_mock()
                result = await guard(handler, _message(command), dict(data))
                self.assertEqual(result, "handled", command)
            for command in ("/disable", "/settings", "https://youtu.be/abc"):
                handler.reset_mock()
                result = await guard(handler, _message(command), dict(data))
                self.assertIsNone(result, command)

    async def test_enabled_group_lets_everything_through(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            guard = GroupGuardMiddleware()
            handler = AsyncMock(return_value="handled")
            result = await guard(
                handler, _message("https://youtu.be/abc"), {"db": db}
            )
            self.assertEqual(result, "handled")


if __name__ == "__main__":
    unittest.main()
