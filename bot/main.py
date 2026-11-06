from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher
from arq import create_pool

from bot.factory import create_bot
from bot.handlers import build_router
from core.cache import Database
from core.config import get_settings
from core.logging import configure_logging
from core.redis import arq_redis_settings, create_redis

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    bot = create_bot(settings)
    queue = await create_pool(arq_redis_settings(settings.redis_url))
    redis = create_redis(settings.redis_url)
    db = Database(settings.database_path)
    await db.initialize()
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    dispatcher["queue"] = queue
    dispatcher["settings"] = settings
    dispatcher["redis"] = redis
    dispatcher["db"] = db

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("bot polling started", extra={"event": "bot_started"})
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        logger.info("stopping bot", extra={"event": "bot_stopping"})
        await queue.aclose()
        await redis.aclose()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
