from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlparse

import yt_dlp

from core.config import Settings
from core.sanitize import sanitize_message, settings_secrets
from core.url_utils import DEFAULT_VIDEO_HEIGHT, VIDEO_HEIGHTS, video_format
from worker.errors import (
    AuthenticationRequired,
    DownloadError,
    MediaTooLarge,
    MediaTooLong,
    PermanentMediaError,
    PhotoPostUnsupported,
    TransientMediaError,
    UnsupportedMedia,
    is_authentication_error,
    is_photo_post_error,
    is_retryable,
)

__all__ = [
    "DownloadError",
    "MediaDownloader",
    "MediaTooLarge",
    "MediaTooLong",
    "PhotoPostUnsupported",
    "UnsupportedMedia",
    "DownloadedMedia",
    "build_format_selector",
    "instagram_format",
    "is_instagram_url",
]

logger = logging.getLogger(__name__)

AUDIO_FORMAT_SELECTOR = "bestaudio/best"
# Last-resort selector for the one automatic retry: it matches any
# downloadable format, so it can only fail if there is truly nothing
# to download.
FALLBACK_FORMAT_SELECTOR = "best"
FORMAT_NOT_AVAILABLE = "requested format is not available"


def is_instagram_url(url: str) -> bool:
    hostname = urlparse(url).hostname or ""
    return hostname == "instagram.com" or hostname.endswith(".instagram.com")


def instagram_format(max_height: int) -> str:
    """Format selector for Instagram, tolerant of missing metadata.

    Instagram's extractor often returns formats without reliable
    height/width fields, and its combined formats are the norm, so this
    leads with ``bv*`` (any format carrying video) instead of the
    split-stream ``bestvideo``. All filters use the ``?`` form so a
    format with no height/width still passes; the chain ends with
    ``/b/best`` so selection degrades to the best available format
    rather than failing. The height cap still applies whenever the
    height is known; the width branches cap portrait frames by their
    short side.
    """

    if max_height not in VIDEO_HEIGHTS:
        raise ValueError(f"unsupported video height: {max_height}")
    return (
        f"bv*[height<=?{max_height}]+ba"
        f"/bv*[width<=?{max_height}]+ba"
        f"/b[width<=?{max_height}][height>=?{max_height}]"
        f"/b[height<=?{max_height}]"
        f"/bv*"
        f"/b"
        f"/best"
    )


def build_format_selector(
    url: str, *, audio_only: bool, max_height: int = DEFAULT_VIDEO_HEIGHT
) -> str:
    """The yt-dlp format selector for one download job."""

    if audio_only:
        return AUDIO_FORMAT_SELECTOR
    if is_instagram_url(url):
        return instagram_format(max_height)
    return video_format(max_height)


def is_format_not_available(exc: BaseException) -> bool:
    return FORMAT_NOT_AVAILABLE in str(exc).lower()


@dataclass(frozen=True, slots=True)
class DownloadedMedia:
    path: Path
    title: str
    duration: float | None
    media_type: str


class YtDlpLogger:
    def __init__(self, sensitive_values: tuple[str, ...] = ()) -> None:
        self.sensitive_values = sensitive_values

    def debug(self, message: str) -> None:
        return

    def warning(self, message: str) -> None:
        logger.warning(
            "yt-dlp warning: %s",
            sanitize_message(message, self.sensitive_values),
            extra={"event": "ytdlp_warning"},
        )

    def error(self, message: str) -> None:
        logger.error(
            "yt-dlp error: %s",
            sanitize_message(message, self.sensitive_values),
            extra={"event": "ytdlp_error"},
        )


class MediaDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sensitive_values = settings_secrets(
            (settings.bot_token, settings.cookies_path, settings.proxy_url)
        )

    async def download(
        self,
        url: str,
        directory: Path,
        *,
        audio_only: bool,
        max_duration: int,
        max_height: int = DEFAULT_VIDEO_HEIGHT,
    ) -> DownloadedMedia:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                self._download_sync,
                url,
                directory,
                audio_only=audio_only,
                max_duration=max_duration,
                max_height=max_height,
            ),
        )

    def _options(
        self,
        directory: Path,
        audio_only: bool,
        cookie_file: Path | None = None,
        *,
        max_height: int = DEFAULT_VIDEO_HEIGHT,
        url: str | None = None,
        format_selector: str | None = None,
    ) -> dict[str, Any]:
        if format_selector is None:
            format_selector = build_format_selector(
                url or "", audio_only=audio_only, max_height=max_height
            )
        options: dict[str, Any] = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": False,
            "logger": YtDlpLogger(self.sensitive_values),
            "outtmpl": str(directory / "%(title).80B-%(id)s.%(ext)s"),
            "restrictfilenames": True,
            "format": format_selector,
            "socket_timeout": 30,
            "retries": 2,
            "continuedl": True,
            "overwrites": True,
        }
        if audio_only:
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        else:
            options["merge_output_format"] = "mp4"

        if cookie_file is not None:
            # Only the writable per-job copy is passed to yt-dlp, never logged.
            options["cookiefile"] = str(cookie_file)
        if self.settings.proxy_url:
            options["proxy"] = self.settings.proxy_url
        return options

    def _copy_cookies(self, directory: Path) -> Path | None:
        source = self.settings.cookies_path
        if not source or not source.is_file() or source.stat().st_size == 0:
            return None
        destination = directory / ".yt-dlp-cookies.txt"
        descriptor = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with source.open("rb") as source_file, os.fdopen(descriptor, "wb") as target:
            shutil.copyfileobj(source_file, target)
        return destination

    def _download_sync(
        self,
        url: str,
        directory: Path,
        *,
        audio_only: bool,
        max_duration: int,
        max_height: int = DEFAULT_VIDEO_HEIGHT,
    ) -> DownloadedMedia:
        directory.mkdir(parents=True, exist_ok=True)
        cookie_file = self._copy_cookies(directory)
        selector = build_format_selector(
            url, audio_only=audio_only, max_height=max_height
        )
        logger.debug(
            "format selector for %s: %s",
            urlparse(url).hostname or "unknown host",
            selector,
            extra={"event": "format_selector"},
        )
        try:
            return self._attempt_download(
                url,
                directory,
                audio_only=audio_only,
                max_duration=max_duration,
                max_height=max_height,
                cookie_file=cookie_file,
                selector=selector,
            )
        except (MediaTooLong, UnsupportedMedia):
            raise
        except yt_dlp.utils.DownloadError as exc:
            if selector == FALLBACK_FORMAT_SELECTOR or not is_format_not_available(
                exc
            ):
                self._raise_classified(exc)
            # The platform offered formats, but none matched the
            # selector. Retry exactly once with the unconstrained
            # selector, inside this same job execution — this does not
            # consume any of the job's normal (arq) retries.
            logger.warning(
                "no format matched selector %r; retrying once with %r",
                selector,
                FALLBACK_FORMAT_SELECTOR,
                extra={"event": "format_selector_fallback"},
            )
            self._clean_partial_files(directory, cookie_file)
            try:
                return self._attempt_download(
                    url,
                    directory,
                    audio_only=audio_only,
                    max_duration=max_duration,
                    max_height=max_height,
                    cookie_file=cookie_file,
                    selector=FALLBACK_FORMAT_SELECTOR,
                )
            except (MediaTooLong, UnsupportedMedia):
                raise
            except yt_dlp.utils.DownloadError as retry_exc:
                self._raise_classified(retry_exc)

    def _attempt_download(
        self,
        url: str,
        directory: Path,
        *,
        audio_only: bool,
        max_duration: int,
        max_height: int,
        cookie_file: Path | None,
        selector: str,
    ) -> DownloadedMedia:
        with yt_dlp.YoutubeDL(
            self._options(
                directory,
                audio_only,
                cookie_file,
                max_height=max_height,
                url=url,
                format_selector=selector,
            )
        ) as ydl:
            info = ydl.extract_info(url, download=False)
            self._validate_info(info, max_duration)
            result = ydl.process_ie_result(info, download=True)
            path = self._find_downloaded_file(result, directory, ydl)
        duration = float(result["duration"]) if result.get("duration") is not None else None
        return DownloadedMedia(
            path=path,
            title=str(result.get("title") or "media"),
            duration=duration,
            media_type="audio" if audio_only else "video",
        )

    def _raise_classified(self, exc: yt_dlp.utils.DownloadError) -> NoReturn:
        """Log a yt-dlp failure and raise the matching DownloadError."""

        message = sanitize_message(exc, self.sensitive_values)
        logger.error(
            "yt-dlp download failed (%s): %s",
            type(exc).__name__,
            message,
            extra={"event": "download_failed"},
        )
        if is_authentication_error(exc):
            raise AuthenticationRequired(message) from exc
        if is_photo_post_error(exc):
            raise PhotoPostUnsupported(message) from exc
        if is_retryable(exc):
            raise TransientMediaError(message) from exc
        raise PermanentMediaError(message) from exc

    @staticmethod
    def _clean_partial_files(directory: Path, keep: Path | None) -> None:
        """Remove partial output before the fallback retry, so a stale
        ``.part`` from the failed attempt cannot be resumed or picked
        up as the result. The per-job cookie copy is kept."""

        for path in directory.iterdir():
            if path.is_file() and path != keep:
                path.unlink(missing_ok=True)

    @staticmethod
    def _validate_info(info: dict[str, Any], max_duration: int) -> None:
        if info.get("_type") in {"playlist", "multi_video"} or info.get("entries"):
            raise UnsupportedMedia("playlists are not supported")
        if info.get("is_live"):
            raise MediaTooLong("live media has no bounded duration")
        duration = info.get("duration")
        if duration is not None and float(duration) > max_duration:
            raise MediaTooLong("media exceeds duration limit")

    @staticmethod
    def _find_downloaded_file(
        info: dict[str, Any], directory: Path, ydl: yt_dlp.YoutubeDL
    ) -> Path:
        candidates: list[Path] = []
        for download in info.get("requested_downloads") or []:
            if download.get("filepath"):
                candidates.append(Path(download["filepath"]))
        if info.get("filepath"):
            candidates.append(Path(info["filepath"]))
        candidates.append(Path(ydl.prepare_filename(info)))
        for candidate in candidates:
            if candidate.is_file():
                return candidate
            # Audio extraction changes the extension after prepare_filename().
            for sibling in candidate.parent.glob(f"{candidate.stem}.*"):
                if sibling.is_file() and sibling.suffix not in {".part", ".ytdl"}:
                    return sibling

        files = [
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix not in {".part", ".ytdl"}
            and path.name != ".yt-dlp-cookies.txt"
        ]
        if not files:
            raise DownloadError("yt-dlp produced no media file")
        return max(files, key=lambda path: path.stat().st_size)
