from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus

from bot.handlers.settings import INVALID_SETTINGS, group_settings
from core.cache import Database, GroupSettings
from core.config import Settings


def _message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=-1001),
        from_user=SimpleNamespace(id=7),
        bot=SimpleNamespace(
            get_chat_member=AsyncMock(
                return_value=SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR)
            )
        ),
        reply=AsyncMock(),
    )


class SettingsHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_is_no_longer_a_group_setting(self) -> None:
        # The help text no longer advertises an audio setting...
        self.assertNotIn("audio", INVALID_SETTINGS)
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            for command in ("/settings audio on", "/settings audio off"):
                message = _message(command)
                await group_settings(
                    message,
                    db=db,
                    settings=Settings(),
                    group_settings=GroupSettings(chat_id=-1001),
                )
                # ...and the old commands are rejected with the new syntax.
                message.reply.assert_awaited_once_with(INVALID_SETTINGS)

    async def test_duration_setting_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            message = _message("/settings duration 300")
            await group_settings(
                message,
                db=db,
                settings=Settings(),
                group_settings=GroupSettings(chat_id=-1001),
            )
            self.assertEqual(
                (await db.get_group_settings(-1001)).max_duration, 300
            )
            message.reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
