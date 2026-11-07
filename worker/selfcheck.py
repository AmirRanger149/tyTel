from __future__ import annotations

import logging
import shutil

import yt_dlp

from core.config import Settings

logger = logging.getLogger(__name__)
NETSCAPE_HEADERS = (b"# Netscape HTTP Cookie File", b"# HTTP Cookie File")


def run_startup_self_check(settings: Settings) -> None:
    """Log actionable runtime diagnostics without preventing worker startup."""

    logger.info(
        "Startup check: yt-dlp version %s",
        yt_dlp.version.__version__,
        extra={"event": "startup_ytdlp"},
    )
    _check_executable(
        "deno",
        "install Deno and ensure it is on PATH (the Docker image includes it)",
    )
    _check_executable("ffmpeg", "install ffmpeg and ensure it is on PATH")
    _check_executable("ffprobe", "install ffmpeg/ffprobe and ensure it is on PATH")
    _check_cookies(settings)


def _check_executable(name: str, hint: str) -> None:
    if shutil.which(name):
        logger.info(
            "Startup check: %s found",
            name,
            extra={"event": f"startup_{name}"},
        )
    else:
        logger.warning(
            "Startup check: %s not found; fix: %s",
            name,
            hint,
            extra={"event": f"startup_{name}_missing"},
        )


def _check_cookies(settings: Settings) -> None:
    path = settings.cookies_path
    try:
        if not path or not path.is_file():
            logger.warning(
                "Startup check: cookies file not present; fix: mount a Netscape-format "
                "cookies file read-only and set COOKIES_PATH",
                extra={"event": "startup_cookies_missing"},
            )
            return
        with path.open("rb") as cookie_file:
            header = cookie_file.read(512)
        if header.startswith(NETSCAPE_HEADERS):
            logger.info(
                "Startup check: cookies file present with a supported Netscape header",
                extra={"event": "startup_cookies_valid"},
            )
        else:
            logger.warning(
                "Startup check: cookies file has no supported Netscape header; fix: "
                "export cookies in Netscape format",
                extra={"event": "startup_cookies_invalid"},
            )
    except OSError as exc:
        # Never include the exception text: it can contain the cookie path.
        logger.warning(
            "Startup check: cookies file could not be read (%s); fix: make it readable "
            "by the non-root worker",
            type(exc).__name__,
            extra={"event": "startup_cookies_unreadable"},
        )
