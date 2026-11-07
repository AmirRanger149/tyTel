from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from redis.asyncio import Redis

from core.cache import GroupSettings
from core.config import Settings
from core.messages import QUALITY_PROMPT, QUEUE_ERROR, RATE_LIMITED, UNSUPPORTED
from core.pending import PendingDownload, store_pending_download
from core.rate_limit import RateLimiter
from core.url_utils import URL_RE, VIDEO_HEIGHTS, extract_urls

logger = logging.getLogger(__name__)
router = Router(name="media")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

# Callback-data prefix for selection buttons; see bot/handlers/quality.py.
QUALITY_CALLBACK_PREFIX = "tyq"
# Callback value for the audio-only button below the quality buttons.
AUDIO_CALLBACK_VALUE = "audio"


def quality_keyboard(token: str) -> InlineKeyboardMarkup:
    """Quality buttons in one row, with an audio-only button below them."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{height}p",
                    callback_data=f"{QUALITY_CALLBACK_PREFIX}:{token}:{height}",
                )
                for height in VIDEO_HEIGHTS
            ],
            [
                InlineKeyboardButton(
                    text="🎵 فقط آهنگ",
                    callback_data=(
                        f"{QUALITY_CALLBACK_PREFIX}:{token}:{AUDIO_CALLBACK_VALUE}"
                    ),
                )
            ],
        ]
    )


@router.message(F.text | F.caption)
async def handle_media_links(
    message: Message,
    settings: Settings,
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
    max_duration = min(
        settings.max_duration_seconds,
        group_settings.max_duration or settings.max_duration_seconds,
    )
    queue_failed = False
    rate_notice_sent = False
    for url in urls:
        # The rate limit is charged when the link is accepted, before any
        # selection prompt is shown, so prompts cannot be used to flood a
        # group and a selection never charges the user twice.
        if not await rate_limiter.allow(
            user_id=message.from_user.id, chat_id=message.chat.id
        ):
            if not rate_notice_sent:
                await message.reply(RATE_LIMITED)
                rate_notice_sent = True
            continue

        # Every link gets a selection prompt: a video quality, or audio
        # only. Nothing is queued (and no cache entry can be picked)
        # until the sender taps a button; the callback handler in
        # bot/handlers/quality.py takes it from there.
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

    if queue_failed:
        await message.reply(QUEUE_ERROR)
