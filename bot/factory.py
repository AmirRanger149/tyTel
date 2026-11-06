from __future__ import annotations

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from core.config import Settings


def create_bot(settings: Settings) -> Bot:
    if not settings.bot_token:
        raise ValueError("BOT_TOKEN is required")
    session: AiohttpSession | None = None
    if settings.local_bot_api_url:
        api = TelegramAPIServer.from_base(settings.local_bot_api_url, is_local=True)
        session = AiohttpSession(api=api)
    return Bot(token=settings.bot_token, session=session)
