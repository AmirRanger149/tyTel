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


def _has_instagram_session(content: bytes) -> bool:
    """True when a Netscape cookie dump carries an Instagram sessionid.

    Only the cookie's presence is reported — its value is never logged.
    Netscape lines are tab-separated: domain, flag, path, secure,
    expiry, name, value. Some exporters prefix cookie lines with
    ``#HttpOnly_``; those lines are cookies, not comments.
    """

    for line in content.decode("utf-8", errors="ignore").splitlines():
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain, name, value = fields[0].lower(), fields[5], fields[6]
        if domain.endswith("instagram.com") and name == "sessionid" and value:
            return True
    return False


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
            # Cookie files are small; the cap only guards against a
            # mis-mounted large file being read whole at startup.
            content = cookie_file.read(2_000_001)
        if content[:512].startswith(NETSCAPE_HEADERS):
            logger.info(
                "Startup check: cookies file present with a supported Netscape header",
                extra={"event": "startup_cookies_valid"},
            )
            if _has_instagram_session(content):
                logger.info(
                    "Startup check: Instagram session cookie found",
                    extra={"event": "startup_instagram_session"},
                )
            else:
                logger.warning(
                    "Startup check: no Instagram session cookie in the cookies "
                    "file; Instagram may reject downloads; fix: export cookies "
                    "from a browser signed in to Instagram with a separate "
                    "account and merge them into the same file",
                    extra={"event": "startup_instagram_session_missing"},
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
