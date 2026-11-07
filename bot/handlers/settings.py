from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command
from aiogram.types import Message

from core.cache import Database, GroupSettings
from core.config import Settings

router = Router(name="group-settings")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

ADMIN_ONLY = "فقط مدیران گروه می‌توانند این تنظیم را تغییر دهند."
INVALID_SETTINGS = "فرمت دستور:\n/settings duration 300"


async def _is_admin(message: Message) -> bool:
    if not message.from_user:
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}


@router.message(Command("enable"))
async def enable_group(message: Message, db: Database) -> None:
    if not await _is_admin(message):
        await message.reply(ADMIN_ONLY)
        return
    await db.set_group_enabled(message.chat.id, True)
    await message.reply("ربات با توکل به خدا فعال شد.")


@router.message(Command("disable"))
async def disable_group(message: Message, db: Database) -> None:
    if not await _is_admin(message):
        await message.reply(ADMIN_ONLY)
        return
    await db.set_group_enabled(message.chat.id, False)
    await message.reply("ربات در این گروه غیرفعال شد.")


@router.message(Command("settings"))
async def group_settings(
    message: Message, db: Database, settings: Settings, group_settings: GroupSettings
) -> None:
    parts = (message.text or "").split()
    if len(parts) == 1:
        duration = group_settings.max_duration or settings.max_duration_seconds
        enabled = "فعال" if group_settings.enabled else "غیرفعال"
        await message.reply(
            f"وضعیت: {enabled}\nحداکثر مدت: {duration} ثانیه\n\n"
            + INVALID_SETTINGS
        )
        return

    if not await _is_admin(message):
        await message.reply(ADMIN_ONLY)
        return
    if len(parts) != 3:
        await message.reply(INVALID_SETTINGS)
        return

    setting, value = parts[1].lower(), parts[2].lower()
    if setting == "duration":
        try:
            seconds = int(value)
        except ValueError:
            await message.reply(INVALID_SETTINGS)
            return
        if not 30 <= seconds <= settings.max_duration_seconds:
            await message.reply(
                f"مدت باید بین ۳۰ و {settings.max_duration_seconds} ثانیه باشد."
            )
            return
        await db.set_group_duration(message.chat.id, seconds)
        await message.reply(f"حداکثر مدت روی {seconds} ثانیه تنظیم شد.")
        return

    await message.reply(INVALID_SETTINGS)
