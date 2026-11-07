from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


async def update_ytdlp(ctx: dict[str, Any]) -> None:
    """Daily arq cron job; container entrypoints also run this at startup."""

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade",
        "yt-dlp[default]",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=300)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        raise RuntimeError("scheduled yt-dlp update failed")
    logger.info("yt-dlp update completed", extra={"event": "ytdlp_updated"})
