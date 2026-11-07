from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from arq.connections import ArqRedis
from redis.asyncio import Redis

from core.cache import Database
from core.config import Settings
from core.messages import (
    AUDIO_SELECTED,
    QUALITY_EXPIRED,
    QUALITY_INVALID,
    QUALITY_NOT_YOURS,
    QUALITY_SELECTED,
)
from core.pending import PENDING_KEY_PREFIX, PendingDownload, claim_pending_download
from core.telegram import send_cached_media
from core.url_utils import VIDEO_HEIGHTS, cache_quality

logger = logging.getLogger(__name__)
router = Router(name="quality")


def parse_quality_callback(data: str | None) -> tuple[str, int | None] | None:
    """Parse ``tyq:<token>:<selection>`` callback data, or None if invalid.

    The selection is a video height (``1080``, ``720``, ...) or the
    literal ``audio`` for audio-only, which is returned as height None.
    """

    if not data:
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "tyq":
        return None
    if parts[2] == "audio":
        return parts[1], None
    try:
        height = int(parts[2])
    except ValueError:
        return None
    if height not in VIDEO_HEIGHTS:
        return None
    return parts[1], height


@router.callback_query(F.data.startswith("tyq:"))
async def handle_quality_selection(
    callback: CallbackQuery,
    queue: ArqRedis,
    settings: Settings,
    db: Database,
    redis: Redis,
) -> None:
    parsed = parse_quality_callback(callback.data)
    if parsed is None:
        await callback.answer(QUALITY_INVALID, show_alert=True)
        return
    token, height = parsed

    if callback.message is None or callback.from_user is None:
        await callback.answer(QUALITY_EXPIRED, show_alert=True)
        return

    # Peek before claiming: a stranger's tap must not burn the sender's
    # one-shot selection, so ownership is checked against the stored
    # request first and the atomic claim only happens for the owner.
    pending_raw = await redis.get(f"{PENDING_KEY_PREFIX}:{token}")
    if pending_raw is None:
        await callback.answer(QUALITY_EXPIRED, show_alert=True)
        return
    peeked = PendingDownload.from_json(pending_raw)
    if peeked is None:
        await callback.answer(QUALITY_EXPIRED, show_alert=True)
        return
    if peeked.user_id != callback.from_user.id or peeked.chat_id != callback.message.chat.id:
        await callback.answer(QUALITY_NOT_YOURS, show_alert=True)
        return

    group_settings = await db.get_group_settings(peeked.chat_id)
    if not group_settings.enabled:
        await callback.answer(QUALITY_EXPIRED, show_alert=True)
        return

    # One-shot claim: from here on, a second tap finds nothing and is
    # told the selection has expired instead of queueing a duplicate.
    pending = await claim_pending_download(redis, token)
    if pending is None:
        await callback.answer(QUALITY_EXPIRED, show_alert=True)
        return

    audio_only = height is None
    quality = cache_quality(audio_only=audio_only, max_height=height)
    cached = await db.get_cached(pending.url, quality)
    if cached:
        try:
            await send_cached_media(
                callback.bot,
                chat_id=pending.chat_id,
                message_id=pending.message_id,
                file_id=cached.file_id,
                media_type=cached.media_type,
            )
            await _confirm_selection(callback, height)
            return
        except TelegramBadRequest:
            await db.delete_cached(pending.url, quality)

    try:
        await queue.enqueue_job(
            "download_and_send",
            chat_id=pending.chat_id,
            message_id=pending.message_id,
            user_id=pending.user_id,
            url=pending.url,
            audio_only=audio_only,
            quality=quality,
            max_duration=pending.max_duration,
        )
    except Exception:
        logger.exception(
            "could not enqueue media job", extra={"event": "enqueue_failed"}
        )
        await callback.answer(QUALITY_EXPIRED, show_alert=True)
        return
    await _confirm_selection(callback, height)


async def _confirm_selection(callback: CallbackQuery, height: int | None) -> None:
    await callback.answer()
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                AUDIO_SELECTED
                if height is None
                else QUALITY_SELECTED.format(height=height)
            )
        except TelegramBadRequest:
            # The prompt may already have been edited or deleted; the
            # download itself is already queued/cached, so this is cosmetic.
            logger.debug(
                "could not edit quality prompt",
                extra={"event": "quality_prompt_edit_failed"},
            )
