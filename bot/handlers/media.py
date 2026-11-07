from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from arq.connections import ArqRedis
from redis.asyncio import Redis

from core.cache import Database, GroupSettings
from core.config import Settings
from core.messages import (
    DOWNLOADING,
    QUALITY_PROMPT,
    QUEUE_ERROR,
    RATE_LIMITED,
    UNSUPPORTED,
)
from core.pending import PendingDownload, store_pending_download
from core.rate_limit import RateLimiter
from core.telegram import send_cached_media
from core.url_utils import URL_RE, VIDEO_HEIGHTS, cache_quality, extract_urls

logger = logging.getLogger(__name__)
router = Router(name="media")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

# Callback-data prefix for quality buttons; see bot/handlers/quality.py.
QUALITY_CALLBACK_PREFIX = "tyq"


def quality_keyboard(token: str) -> InlineKeyboardMarkup:
    """One row of quality buttons for a pending download token."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{height}p",
                    callback_data=f"{QUALITY_CALLBACK_PREFIX}:{token}:{height}",
                )
                for height in VIDEO_HEIGHTS
            ]
        ]
    )


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
    max_duration = min(
        settings.max_duration_seconds,
        group_settings.max_duration or settings.max_duration_seconds,
    )
    enqueued = 0
    queue_failed = False
    rate_notice_sent = False
    for url in urls:
        # The rate limit is charged when the link is accepted, before any
        # quality prompt is shown, so prompts cannot be used to flood a
        # group and a selection never charges the user twice.
        if not await rate_limiter.allow(
            user_id=message.from_user.id, chat_id=message.chat.id
        ):
            if not rate_notice_sent:
                await message.reply(RATE_LIMITED)
                rate_notice_sent = True
            continue

        if not audio_only:
            # Video: ask for a quality first. Nothing is queued (and no
            # cache entry can be picked) until the sender taps a button;
            # the callback handler in bot/handlers/quality.py takes it
            # from there. Audio-only groups keep the immediate flow below,
            # since there is no video quality to choose.
            try:
                token = await store_pending_download(
                    redis,
                    PendingDownload(
                        chat_id=message.chat.id,
                        message_id=message.message_id,
                        user_id=message.from_user.id,
                        url=url,
                        max_duration=max_duration,
                    ),
                    ttl_seconds=settings.quality_prompt_ttl_seconds,
                )
                await message.reply(
                    QUALITY_PROMPT, reply_markup=quality_keyboard(token)
                )
            except Exception:
                queue_failed = True
                logger.exception(
                    "could not create quality prompt",
                    extra={"event": "quality_prompt_failed"},
                )
            continue

        quality = cache_quality(audio_only)
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
