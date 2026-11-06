from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from arq.connections import ArqRedis
from redis.asyncio import Redis

from core.cache import Database, GroupSettings
from core.config import Settings
from core.messages import DOWNLOADING, QUEUE_ERROR, RATE_LIMITED, UNSUPPORTED
from core.rate_limit import RateLimiter
from core.telegram import send_cached_media
from core.url_utils import URL_RE, cache_quality, extract_urls

logger = logging.getLogger(__name__)
router = Router(name="media")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


@router.message(F.text | F.caption)
async def handle_media_links(
    message: Message,
    queue: ArqRedis,
    settings: Settings,
    db: Database,
    redis: Redis,
    group_settings: GroupSettings,
) -> None:
    if not message.from_user:
        return
    text = message.text or message.caption
    urls = extract_urls(text)
    if not urls:
        if text and URL_RE.search(text):
            await message.reply(UNSUPPORTED)
        return

    rate_limiter = RateLimiter(redis, settings)
    audio_only = group_settings.audio_only
    quality = cache_quality(audio_only)
    max_duration = min(
        settings.max_duration_seconds,
        group_settings.max_duration or settings.max_duration_seconds,
    )
    enqueued = 0
    queue_failed = False
    rate_notice_sent = False
    for url in urls:
        if not await rate_limiter.allow(
            user_id=message.from_user.id, chat_id=message.chat.id
        ):
            if not rate_notice_sent:
                await message.reply(RATE_LIMITED)
                rate_notice_sent = True
            continue

        cached = await db.get_cached(url, quality)
        if cached:
            try:
                await send_cached_media(
                    message.bot,
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    file_id=cached.file_id,
                    media_type=cached.media_type,
                )
                continue
            except TelegramBadRequest:
                await db.delete_cached(url, quality)
        try:
            await queue.enqueue_job(
                "download_and_send",
                chat_id=message.chat.id,
                message_id=message.message_id,
                user_id=message.from_user.id,
                url=url,
                audio_only=audio_only,
                quality=quality,
                max_duration=max_duration,
            )
            enqueued += 1
        except Exception:
            queue_failed = True
            logger.exception("could not enqueue media job", extra={"event": "enqueue_failed"})

    if enqueued:
        await message.reply(DOWNLOADING)
    elif queue_failed:
        await message.reply(QUEUE_ERROR)
