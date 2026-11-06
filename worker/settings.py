from __future__ import annotations

import logging
from typing import Any

from core.cache import Database
from arq import cron

from core.config import get_settings
from core.logging import configure_logging
from core.redis import arq_redis_settings
from worker.compressor import MediaCompressor
from worker.downloader import MediaDownloader
from worker.maintenance import update_ytdlp
from worker.tasks import download_and_send

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    from bot.factory import create_bot

    ctx["settings"] = settings
    ctx["db"] = Database(settings.database_path)
    await ctx["db"].initialize()
    ctx["bot"] = create_bot(settings)
    ctx["downloader"] = MediaDownloader(settings)
    ctx["compressor"] = MediaCompressor(settings.upload_limit_bytes)
    logger.info("worker started", extra={"event": "worker_started"})


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["bot"].session.close()
    logger.info("worker stopped", extra={"event": "worker_stopped"})


class WorkerSettings:
    functions = [download_and_send]
    cron_jobs = [cron(update_ytdlp, hour=0, minute=0, second=0)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = arq_redis_settings(settings.redis_url)
    max_jobs = settings.worker_concurrency
    max_tries = 3
    job_timeout = settings.job_timeout_seconds
    keep_result = 0
