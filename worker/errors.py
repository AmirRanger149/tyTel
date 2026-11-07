from __future__ import annotations

import errno
import re

from aiogram.exceptions import (
    TelegramEntityTooLarge,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)


class DownloadError(Exception):
    """Base class for expected media failures; not transient by default."""


class TransientMediaError(DownloadError):
    pass


class PermanentMediaError(DownloadError):
    pass


class AuthenticationRequired(PermanentMediaError):
    pass


class MediaTooLong(PermanentMediaError):
    pass


class UnsupportedMedia(PermanentMediaError):
    pass


class PhotoPostUnsupported(UnsupportedMedia):
    """An Instagram post with no video (photo post or photo carousel).

    yt-dlp is a video extractor and refuses these during extraction;
    they get their own user message until image support lands.
    """


class MediaTooLarge(PermanentMediaError):
    pass


AUTH_PATTERNS = (
    "sign in to confirm",
    "sign-in to confirm",
    "sign in required",
    "login required",
    "cookies are no longer valid",
    "cookies have expired",
    # Instagram login checkpoints surface with this API code.
    "checkpoint_required",
)
PERMANENT_PATTERNS = (
    "private video",
    "this video is private",
    "video unavailable",
    "this video is unavailable",
    "unsupported url",
    "unsupported media",
    "age-restricted",
    "age restricted",
    "confirm your age",
    "region restricted",
    "region-restricted",
    "not available in your country",
    "geo-restricted",
    "live stream",
    "live event",
    "no supported javascript runtime",
    "file is too large",
    "read-only file system",
    "permission denied",
    # yt-dlp's Instagram extractor on image-only posts.
    "there is no video in this post",
    "no video formats found",
)
TRANSIENT_PATTERNS = (
    "timed out",
    "timeout",
    "temporary failure",
    "temporarily unavailable",
    "connection reset",
    "connection error",
    "network error",
    "remote end closed",
    "server disconnected",
    "try again later",
    "http error 429",
    "too many requests",
    # Meta's own rate-limit wording, and generic rate-limit phrasings.
    "please wait a few minutes before you try again",
    "rate limit",
)
HTTP_5XX_RE = re.compile(r"(?i)(?:HTTP(?: Error)?[ :]*|status[ =])(5\d\d)\b")


def is_photo_post_error(exc: BaseException) -> bool:
    """True for yt-dlp's Instagram 'this post has no video' failures.

    Both observed messages ("There is no video in this post" and
    "No video formats found!") only mean 'photo post' when they come
    from the Instagram extractor, so its name must appear too.
    """

    if isinstance(exc, PhotoPostUnsupported):
        return True
    message = str(exc).lower()
    return "instagram" in message and (
        "there is no video in this post" in message
        or "no video formats found" in message
    )


def is_authentication_error(exc: BaseException) -> bool:
    if isinstance(exc, AuthenticationRequired):
        return True
    message = str(exc).lower()
    return any(pattern in message for pattern in AUTH_PATTERNS)


def is_retryable(exc: BaseException) -> bool:
    """Return True only for explicitly transient network/server failures."""

    if isinstance(exc, TransientMediaError):
        return True
    if isinstance(exc, (MediaTooLong, MediaTooLarge, UnsupportedMedia, PermanentMediaError)):
        return False
    if isinstance(exc, (TelegramNetworkError, TelegramRetryAfter, TelegramServerError)):
        return True
    if isinstance(exc, TelegramEntityTooLarge):
        return False
    if isinstance(exc, OSError):
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True
        if exc.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            return False
        return False

    message = str(exc).lower()
    if any(pattern in message for pattern in AUTH_PATTERNS + PERMANENT_PATTERNS):
        return False
    return HTTP_5XX_RE.search(message) is not None or any(
        pattern in message for pattern in TRANSIENT_PATTERNS
    )
