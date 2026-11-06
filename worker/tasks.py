from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from arq import Retry

from core.cache import Database
from core.messages import ERROR, TOO_LARGE, TOO_LONG, UNSUPPORTED
from core.redis import lock_key
from core.telegram import send_cached_media, send_local_media, sent_file_id
from worker.compressor import MediaCompressor
from worker.downloader import (
    MediaDownloader,
    MediaTooLarge,
    MediaTooLong,
    UnsupportedMedia,
)

logger = logging.getLogger(__name__)
MAX_TRIES = 3


async def _reply_failure(bot: Bot, chat_id: int, message_id: int, text: str) -> None:
    try:
        await bot.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            allow_sending_without_reply=True,
        )
    except Exception:
        logger.exception("could not send failure notice", extra={"event": "error_reply_failed"})


async def download_and_send(
    ctx: dict[str, Any],
    *,
    chat_id: int,
    message_id: int,
    user_id: int,
    url: str,
    audio_only: bool,
    quality: str,
    max_duration: int,
) -> None:
    bot: Bot = ctx["bot"]
    settings = ctx["settings"]
    db: Database = ctx["db"]
    attempt = int(ctx.get("job_try", 1))
    directory: Path | None = None
    try:
        # Locking the normalized URL serializes duplicates across all workers.
        async with ctx["redis"].lock(
            lock_key(url), timeout=settings.dedup_lock_timeout_seconds
        ):
            cached = await db.get_cached(url, quality)
            if cached:
                try:
                    await send_cached_media(
                        bot,
                        chat_id=chat_id,
                        message_id=message_id,
                        file_id=cached.file_id,
                        media_type=cached.media_type,
                    )
                    return
                except TelegramBadRequest:
                    await db.delete_cached(url, quality)

            temp_root = Path(settings.temp_dir)
            temp_root.mkdir(parents=True, exist_ok=True)
            directory = Path(
                tempfile.mkdtemp(prefix=f"{ctx.get('job_id', 'job')}-", dir=temp_root)
            )
            downloader: MediaDownloader = ctx["downloader"]
            media = await downloader.download(
                url, directory, audio_only=audio_only, max_duration=max_duration
            )
            compressor: MediaCompressor = ctx["compressor"]
            output = await compressor.compress_if_needed(
                media.path, media_type=media.media_type, duration=media.duration
            )
            delivery_type = media.media_type
            if delivery_type == "video" and output.suffix.lower() != ".mp4":
                # Telegram sendVideo accepts MPEG-4; preserve other formats as documents.
                delivery_type = "document"
            sent = await send_local_media(
                bot,
                chat_id=chat_id,
                message_id=message_id,
                path=output,
                media_type=delivery_type,
            )
            await db.store_cached(
                url, quality, sent_file_id(sent, delivery_type), delivery_type
            )
            logger.info(
                "media delivered",
                extra={"event": "media_delivered", "chat_id": chat_id, "attempt": attempt},
            )
    except (MediaTooLong, UnsupportedMedia, MediaTooLarge) as exc:
        text = (
            TOO_LONG
            if isinstance(exc, MediaTooLong)
            else TOO_LARGE
            if isinstance(exc, MediaTooLarge)
            else UNSUPPORTED
        )
        await _reply_failure(bot, chat_id, message_id, text)
    except Exception as exc:
        if attempt < MAX_TRIES:
            delay = 2**attempt
            logger.warning(
                "media job failed; retrying in %ss (%s)",
                delay,
                type(exc).__name__,
                extra={"event": "job_retry", "chat_id": chat_id, "attempt": attempt},
            )
            raise Retry(defer=delay) from exc
        logger.error(
            "media job permanently failed (%s)",
            type(exc).__name__,
            extra={"event": "job_failed", "chat_id": chat_id, "attempt": attempt},
        )
        await _reply_failure(bot, chat_id, message_id, ERROR)
    finally:
        if directory is not None:
            await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)
