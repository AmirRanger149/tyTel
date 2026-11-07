from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from bot.handlers.settings import COMMAND_NOT_FOUND

router = Router(name="unknown-command")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    """Reply to commands no other handler claimed.

    This router is included last, so known commands (and messages with
    links) are handled before anything reaches this fallback. Commands
    addressed to a different bot in the group are ignored.
    """

    token = (message.text or "").split(maxsplit=1)[0]
    if "@" in token:
        me = await message.bot.me()
        if token.split("@", 1)[1].lower() != (me.username or "").lower():
            return
    await message.reply(COMMAND_NOT_FOUND)
