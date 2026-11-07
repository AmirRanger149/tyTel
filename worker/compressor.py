from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path

from core.sanitize import sanitize_message
from worker.errors import (
    DownloadError,
    MediaTooLarge,
    PermanentMediaError,
    TransientMediaError,
    is_retryable,
)

logger = logging.getLogger(__name__)


class MediaCompressor:
    def __init__(self, size_limit_bytes: int) -> None:
        self.size_limit_bytes = size_limit_bytes

    async def compress_if_needed(
        self, source: Path, *, media_type: str, duration: float | None
    ) -> Path:
        if source.stat().st_size <= self.size_limit_bytes:
            return source
        if media_type == "audio":
            return await self._compress_audio(source)
        if not duration or not math.isfinite(duration) or duration <= 0:
            raise MediaTooLarge("cannot calculate a video bitrate")
        return await self._compress_video(source, duration)

    async def _run(self, arguments: list[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            detail = sanitize_message(
                stderr.decode("utf-8", errors="replace")[-2000:]
            )
            failure = DownloadError(
                f"ffmpeg exited with {process.returncode}: {detail}"
            )
            if is_retryable(failure):
                raise TransientMediaError(str(failure))
            raise PermanentMediaError(str(failure))

    async def _compress_audio(self, source: Path) -> Path:
        output = source.with_name(f"{source.stem}-compressed.mp3")
        await self._run(
            [
                "ffmpeg", "-y", "-i", str(source), "-vn", "-c:a", "libmp3lame",
                "-b:a", "96k", str(output),
            ]
        )
        self._check_size(output)
        return output

    async def _compress_video(self, source: Path, duration: float) -> Path:
        output = source.with_name(f"{source.stem}-compressed.mp4")
        # Two passes trade resolution for a second chance to fit the limit.
        for attempt, max_height in enumerate((720, 480), start=1):
            audio_bps = 96_000
            target_bps = int(self.size_limit_bytes * 8 * 0.92 / duration)
            video_bps = max(80_000, target_bps - audio_bps)
            await self._run(
                [
                    "ffmpeg", "-y", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                    "-vf", f"scale=-2:'min({max_height},ih)'", "-c:v", "libx264",
                    "-preset", "veryfast", "-b:v", str(video_bps), "-maxrate", str(video_bps),
                    "-bufsize", str(video_bps * 2), "-c:a", "aac", "-b:a", "96k",
                    "-movflags", "+faststart", str(output),
                ]
            )
            if output.stat().st_size <= self.size_limit_bytes:
                return output
            logger.info(
                "compressed video still too large", extra={"event": "compression_retry", "attempt": attempt}
            )
        raise MediaTooLarge("media remains above the upload limit")

    def _check_size(self, output: Path) -> None:
        if not output.is_file() or output.stat().st_size > self.size_limit_bytes:
            raise MediaTooLarge("media remains above the upload limit")
