from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import yt_dlp

from core.config import Settings
from core.sanitize import sanitize_message, settings_secrets
from core.url_utils import DEFAULT_VIDEO_HEIGHT, video_format
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
]

logger = logging.getLogger(__name__)


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
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": False,
            "logger": YtDlpLogger(self.sensitive_values),
            "outtmpl": str(directory / "%(title).80B-%(id)s.%(ext)s"),
            "restrictfilenames": True,
            "format": (
                "bestaudio/best" if audio_only else video_format(max_height)
            ),
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
        try:
            with yt_dlp.YoutubeDL(
                self._options(directory, audio_only, cookie_file, max_height=max_height)
            ) as ydl:
                info = ydl.extract_info(url, download=False)
                self._validate_info(info, max_duration)
                result = ydl.process_ie_result(info, download=True)
                path = self._find_downloaded_file(result, directory, ydl)
        except (MediaTooLong, UnsupportedMedia):
            raise
        except yt_dlp.utils.DownloadError as exc:
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

        duration = float(result["duration"]) if result.get("duration") is not None else None
        return DownloadedMedia(
            path=path,
            title=str(result.get("title") or "media"),
            duration=duration,
            media_type="audio" if audio_only else "video",
        )

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
