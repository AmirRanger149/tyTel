from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import yt_dlp

from core.config import Settings

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """A safe, expected download failure."""


class MediaTooLong(DownloadError):
    pass


class UnsupportedMedia(DownloadError):
    pass


class MediaTooLarge(DownloadError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadedMedia:
    path: Path
    title: str
    duration: float | None
    media_type: str


class YtDlpLogger:
    # Raw extractor messages can contain request or cookie-file details.
    def debug(self, message: str) -> None:
        return

    def warning(self, message: str) -> None:
        logger.warning("yt-dlp emitted a warning", extra={"event": "ytdlp_warning"})

    def error(self, message: str) -> None:
        logger.error("yt-dlp emitted an error", extra={"event": "ytdlp_error"})


class MediaDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def download(
        self, url: str, directory: Path, *, audio_only: bool, max_duration: int
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
            ),
        )

    def _options(self, directory: Path, audio_only: bool) -> dict[str, Any]:
        options: dict[str, Any] = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": False,
            "logger": YtDlpLogger(),
            "outtmpl": str(directory / "%(title).80B-%(id)s.%(ext)s"),
            "restrictfilenames": True,
            "format": (
                "bestaudio/best"
                if audio_only
                else "bestvideo[height<=720]+bestaudio/best[height<=720]"
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

        cookies = self.settings.cookies_path
        if cookies and cookies.is_file() and cookies.stat().st_size > 0:
            # The option is intentionally never included in application logs.
            options["cookiefile"] = str(cookies)
        if self.settings.proxy_url:
            options["proxy"] = self.settings.proxy_url
        return options

    def _download_sync(
        self, url: str, directory: Path, *, audio_only: bool, max_duration: int
    ) -> DownloadedMedia:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            with yt_dlp.YoutubeDL(self._options(directory, audio_only)) as ydl:
                info = ydl.extract_info(url, download=False)
                self._validate_info(info, max_duration)
                result = ydl.process_ie_result(info, download=True)
                path = self._find_downloaded_file(result, directory, ydl)
        except (MediaTooLong, UnsupportedMedia):
            raise
        except yt_dlp.utils.DownloadError as exc:
            # Do not log exception text: extractor messages can contain request details.
            logger.info("yt-dlp rejected a media download", extra={"event": "download_failed"})
            raise DownloadError("download failed") from exc

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
            if path.is_file() and path.suffix not in {".part", ".ytdl"}
        ]
        if not files:
            raise DownloadError("yt-dlp produced no media file")
        return max(files, key=lambda path: path.stat().st_size)
