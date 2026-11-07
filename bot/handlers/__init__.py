from aiogram import Router

from bot.handlers.media import router as media_router
from bot.handlers.quality import router as quality_router
from bot.handlers.settings import router as settings_router
from bot.handlers.unknown import router as unknown_router
from bot.middlewares import GroupGuardMiddleware


def build_router() -> Router:
    router = Router()
    router.include_router(settings_router)
    router.include_router(media_router)
    router.include_router(quality_router)
    # Last on purpose: the unknown-command fallback may only see
    # commands that no earlier router claimed.
    router.include_router(unknown_router)
    router.message.middleware(GroupGuardMiddleware())
    return router
