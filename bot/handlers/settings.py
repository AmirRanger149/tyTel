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
COMMAND_NOT_FOUND = "کامند یافت نشد!"
ENABLED_REPLY = "ربات با توکل به خدا فعال شد."
DISABLED_REPLY = "ربات در این گروه غیرفعال شد."


async def _is_admin(message: Message) -> bool:
    if not message.from_user:
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}


async def _set_enabled(message: Message, db: Database, enabled: bool) -> None:
    if not await _is_admin(message):
        await message.reply(ADMIN_ONLY)
        return
    await db.set_group_enabled(message.chat.id, enabled)
    await message.reply(ENABLED_REPLY if enabled else DISABLED_REPLY)


@router.message(Command("enable"))
async def enable_group(message: Message, db: Database) -> None:
    await _set_enabled(message, db, True)


@router.message(Command("disable"))
async def disable_group(message: Message, db: Database) -> None:
    await _set_enabled(message, db, False)


@router.message(Command("ctl"))
async def control_group(
    message: Message, db: Database, group_settings: GroupSettings
) -> None:
    """General bot control for the group: ``/ctl on`` and ``/ctl off``.

    Bare ``/ctl`` reports the current state, like ``/status``.
    """

    parts = (message.text or "").split()
    if len(parts) == 1:
        enabled = "فعال" if group_settings.enabled else "غیرفعال"
        await message.reply(f"وضعیت ربات: {enabled}")
        return
    if len(parts) != 2:
        await message.reply(COMMAND_NOT_FOUND)
        return
    action = parts[1].lower()
    if action in {"on", "enable"}:
        await _set_enabled(message, db, True)
    elif action in {"off", "disable"}:
        await _set_enabled(message, db, False)
    else:
        await message.reply(COMMAND_NOT_FOUND)


@router.message(Command("status"))
async def group_status(
    message: Message, db: Database, settings: Settings, group_settings: GroupSettings
) -> None:
    parts = (message.text or "").split()
    if len(parts) == 1:
        duration = group_settings.max_duration or settings.max_duration_seconds
        enabled = "فعال" if group_settings.enabled else "غیرفعال"
        await message.reply(f"وضعیت: {enabled}\nحداکثر مدت: {duration} ثانیه")
        return

    if not await _is_admin(message):
        await message.reply(ADMIN_ONLY)
        return
    if len(parts) != 3:
        await message.reply(COMMAND_NOT_FOUND)
        return

    setting, value = parts[1].lower(), parts[2].lower()
    if setting == "duration":
        try:
            seconds = int(value)
        except ValueError:
            await message.reply(COMMAND_NOT_FOUND)
            return
        if not 30 <= seconds <= settings.max_duration_seconds:
            await message.reply(
                f"مدت باید بین ۳۰ و {settings.max_duration_seconds} ثانیه باشد."
            )
            return
        await db.set_group_duration(message.chat.id, seconds)
        await message.reply(f"حداکثر مدت روی {seconds} ثانیه تنظیم شد.")
        return

    await message.reply(COMMAND_NOT_FOUND)
