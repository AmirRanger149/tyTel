from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus

from bot.handlers.settings import (
    ADMIN_ONLY,
    COMMAND_NOT_FOUND,
    control_group,
    group_status,
)
from bot.handlers.unknown import unknown_command
from core.cache import Database, GroupSettings
from core.config import Settings


def _message(text: str, *, admin: bool = True) -> SimpleNamespace:
    status = (
        ChatMemberStatus.ADMINISTRATOR if admin else ChatMemberStatus.MEMBER
    )
    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=-1001),
        from_user=SimpleNamespace(id=7),
        bot=SimpleNamespace(
            get_chat_member=AsyncMock(
                return_value=SimpleNamespace(status=status)
            ),
            me=AsyncMock(return_value=SimpleNamespace(username="tytel_bot")),
        ),
        reply=AsyncMock(),
    )


async def _status(message, db) -> None:
    await group_status(
        message,
        db=db,
        settings=Settings(),
        group_settings=GroupSettings(chat_id=-1001),
    )


class StatusHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_is_no_longer_a_group_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            for command in ("/status audio on", "/status audio off"):
                message = _message(command)
                await _status(message, db)
                message.reply.assert_awaited_once_with(COMMAND_NOT_FOUND)

    async def test_duration_setting_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            message = _message("/status duration 300")
            await _status(message, db)
            self.assertEqual(
                (await db.get_group_settings(-1001)).max_duration, 300
            )
            message.reply.assert_awaited_once()

    async def test_bare_status_shows_state_without_command_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            message = _message("/status")
            await _status(message, db)
            reply_text = message.reply.await_args.args[0]
            self.assertIn("وضعیت: فعال", reply_text)
            self.assertNotIn("فرمت دستور", reply_text)

    async def test_malformed_status_commands_are_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            for command in (
                "/status duration",
                "/status duration abc",
                "/status volume 3",
                "/status duration 300 extra",
            ):
                message = _message(command)
                await _status(message, db)
                message.reply.assert_awaited_once_with(COMMAND_NOT_FOUND)


class CtlHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ctl_off_and_on_toggle_the_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            off = _message("/ctl off")
            await control_group(
                off, db=db, group_settings=GroupSettings(chat_id=-1001)
            )
            self.assertFalse((await db.get_group_settings(-1001)).enabled)
            on = _message("/ctl on")
            await control_group(
                on, db=db, group_settings=GroupSettings(chat_id=-1001)
            )
            self.assertTrue((await db.get_group_settings(-1001)).enabled)

    async def test_ctl_requires_admin_to_change_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            message = _message("/ctl off", admin=False)
            await control_group(
                message, db=db, group_settings=GroupSettings(chat_id=-1001)
            )
            message.reply.assert_awaited_once_with(ADMIN_ONLY)
            self.assertTrue((await db.get_group_settings(-1001)).enabled)

    async def test_ctl_bare_reports_state_and_bad_action_is_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "cache.db")
            await db.initialize()
            bare = _message("/ctl")
            await control_group(
                bare, db=db, group_settings=GroupSettings(chat_id=-1001)
            )
            self.assertIn("فعال", bare.reply.await_args.args[0])
            bad = _message("/ctl banana")
            await control_group(
                bad, db=db, group_settings=GroupSettings(chat_id=-1001)
            )
            bad.reply.assert_awaited_once_with(COMMAND_NOT_FOUND)


class UnknownCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_command_gets_not_found_reply(self) -> None:
        message = _message("/frobnicate")
        await unknown_command(message)
        message.reply.assert_awaited_once_with(COMMAND_NOT_FOUND)

    async def test_command_for_another_bot_is_ignored(self) -> None:
        message = _message("/frobnicate@some_other_bot")
        await unknown_command(message)
        message.reply.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
