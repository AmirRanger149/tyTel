from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from core.cache import Database, GroupSettings


class GroupGuardMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.chat.type not in {"group", "supergroup"}:
            return await handler(event, data)
        db: Database = data["db"]
        group_settings = await db.get_group_settings(event.chat.id)
        data["group_settings"] = group_settings
        command = (event.text or "").split(maxsplit=1)[0].split("@")[0].lower()
        if not group_settings.enabled and command not in {"/enable", "/settings"}:
            return None
        return await handler(event, data)
