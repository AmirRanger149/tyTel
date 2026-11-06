from __future__ import annotations

from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile, Message

REPLY_ARGS = {"allow_sending_without_reply": True}


async def send_cached_media(
    bot: Bot, *, chat_id: int, message_id: int, file_id: str, media_type: str
) -> Message:
    kwargs: dict[str, Any] = {
        "chat_id": chat_id,
        "reply_to_message_id": message_id,
        **REPLY_ARGS,
    }
    if media_type == "audio":
        return await bot.send_audio(audio=file_id, **kwargs)
    if media_type == "video":
        return await bot.send_video(video=file_id, **kwargs)
    return await bot.send_document(document=file_id, **kwargs)


async def send_local_media(
    bot: Bot, *, chat_id: int, message_id: int, path: Path, media_type: str
) -> Message:
    media = FSInputFile(path)
    kwargs: dict[str, Any] = {
        "chat_id": chat_id,
        "reply_to_message_id": message_id,
        **REPLY_ARGS,
    }
    if media_type == "audio":
        return await bot.send_audio(audio=media, **kwargs)
    if media_type == "video":
        return await bot.send_video(video=media, supports_streaming=True, **kwargs)
    return await bot.send_document(document=media, **kwargs)


def sent_file_id(message: Message, media_type: str) -> str:
    media = getattr(message, media_type, None)
    if media is None or not media.file_id:
        raise RuntimeError("Telegram response did not contain a file_id")
    return str(media.file_id)
