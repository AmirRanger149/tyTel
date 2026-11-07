from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from core.cache import Database
from core.config import Settings
from worker.downloader import MediaDownloader
from worker.tasks import download_and_send
from worker.compressor import MediaCompressor
from tests.test_worker import FakeLock

COOKIE_CONTENT = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\ttopsecret\n"


class FakeYoutubeDL:
    cookie_copy: Path | None = None
    copy_mode: int | None = None

    def __init__(self, options: dict[str, object]) -> None:
        self.options = options
        self.directory = Path(str(options["outtmpl"])).parent
        type(self).cookie_copy = Path(str(options["cookiefile"]))
        type(self).copy_mode = type(self).cookie_copy.stat().st_mode & 0o777

    def __enter__(self) -> "FakeYoutubeDL":
        self.options["logger"].warning(  # type: ignore[attr-defined]
            "Cookie: SID=topsecret"
        )
        self.options["logger"].error(  # type: ignore[attr-defined]
            f"cookie save path: {type(self).cookie_copy}"
        )
        return self

    def __exit__(self, *args: object) -> None:
        assert type(self).cookie_copy is not None
        type(self).cookie_copy.write_text("modified by yt-dlp", encoding="utf-8")

    def extract_info(self, url: str, download: bool) -> dict[str, object]:
        return {"id": "video123", "title": "test", "duration": 1, "ext": "mp4"}

    def process_ie_result(self, info: dict[str, object], download: bool) -> dict[str, object]:
        output = self.directory / "video.mp4"
        output.write_bytes(b"small video")
        return {**info, "requested_downloads": [{"filepath": str(output)}]}

    def prepare_filename(self, info: dict[str, object]) -> str:
        return str(self.directory / "video.mp4")


class CookieCopyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_is_read_only_copy_is_removed_and_secrets_not_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source-cookies.txt"
            source.write_text(COOKIE_CONTENT, encoding="utf-8")
            source.chmod(0o444)
            settings = Settings(cookies_path=source, temp_dir=root / "tmp")
            db = Database(root / "cache.db")
            await db.initialize()
            redis = Mock()
            redis.lock.return_value = FakeLock()
            bot = SimpleNamespace(
                send_video=AsyncMock(
                    return_value=SimpleNamespace(
                        video=SimpleNamespace(file_id="telegram-file")
                    )
                )
            )
            ctx = {
                "bot": bot,
                "db": db,
                "redis": redis,
                "settings": settings,
                "downloader": MediaDownloader(settings),
                "compressor": MediaCompressor(settings.upload_limit_bytes),
                "job_try": 1,
                "job_id": "cookie-test",
            }
            with patch("worker.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL):
                with self.assertLogs("worker", level=logging.INFO) as logs:
                    await download_and_send(
                        ctx,
                        chat_id=-100123,
                        message_id=42,
                        user_id=7,
                        url="https://www.youtube.com/watch?v=video123",
                        audio_only=False,
                        quality="video-720p",
                        max_duration=600,
                    )
            self.assertEqual(source.read_text(encoding="utf-8"), COOKIE_CONTENT)
            self.assertEqual(FakeYoutubeDL.copy_mode, 0o600)
            self.assertIsNotNone(FakeYoutubeDL.cookie_copy)
            assert FakeYoutubeDL.cookie_copy is not None
            self.assertFalse(FakeYoutubeDL.cookie_copy.exists())
            self.assertEqual(list((root / "tmp").iterdir()), [])
            output = "\n".join(logs.output)
            self.assertNotIn("topsecret", output)
            self.assertNotIn(str(source), output)
            self.assertNotIn(str(FakeYoutubeDL.cookie_copy), output)


if __name__ == "__main__":
    unittest.main()
