from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yt_dlp.utils import DownloadError as YtDlpDownloadError

from core.config import Settings
from worker.downloader import (
    MediaDownloader,
    MediaTooLong,
    PermanentMediaError,
    PhotoPostUnsupported,
    UnsupportedMedia,
    instagram_format,
)


class DownloaderLimitTests(unittest.TestCase):
    def test_accepts_media_at_duration_limit(self) -> None:
        MediaDownloader._validate_info({"duration": 600}, 600)

    def test_rejects_long_media(self) -> None:
        with self.assertRaises(MediaTooLong):
            MediaDownloader._validate_info({"duration": 601}, 600)

    def test_rejects_playlists_and_live_streams(self) -> None:
        with self.assertRaises(UnsupportedMedia):
            MediaDownloader._validate_info({"entries": [{"id": "one"}]}, 600)
        with self.assertRaises(MediaTooLong):
            MediaDownloader._validate_info({"is_live": True}, 600)

    def test_instagram_info_without_duration_is_accepted(self) -> None:
        # Instagram's extractor usually reports no duration; None must
        # not be treated as over (or under) the limit.
        MediaDownloader._validate_info(
            {"extractor": "Instagram", "duration": None, "ext": "mp4"}, 600
        )


class DownloaderErrorConversionTests(unittest.TestCase):
    def test_instagram_photo_error_becomes_photo_post_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            downloader = MediaDownloader(Settings())
            with patch(
                "worker.downloader.yt_dlp.YoutubeDL",
                side_effect=YtDlpDownloadError(
                    "[Instagram] ABC123: There is no video in this post"
                ),
            ):
                with self.assertRaises(PhotoPostUnsupported):
                    downloader._download_sync(
                        "https://www.instagram.com/p/ABC123/",
                        Path(temp),
                        audio_only=False,
                        max_duration=600,
                    )


FORMAT_NOT_AVAILABLE = YtDlpDownloadError(
    "[Instagram] ABC123: Requested format is not available. "
    "Use --list-formats for a list of available formats"
)


class _FakeYoutubeDL:
    """Minimal YoutubeDL stand-in: optionally fails format selection,
    otherwise "downloads" a small file into the job directory."""

    instances: list["_FakeYoutubeDL"] = []
    fail_first_attempt = False
    fail_all_attempts: Exception | None = None

    def __init__(self, options: dict) -> None:
        self.options = options
        type(self).instances.append(self)

    def __enter__(self) -> "_FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def extract_info(self, url: str, download: bool = False) -> dict:
        return {"id": "ABC123", "title": "Reel", "duration": 12}

    def process_ie_result(self, info: dict, download: bool = True) -> dict:
        if type(self).fail_all_attempts is not None:
            raise type(self).fail_all_attempts
        if type(self).fail_first_attempt and len(type(self).instances) == 1:
            raise FORMAT_NOT_AVAILABLE
        path = Path(self.options["outtmpl"]).parent / "Reel-ABC123.mp4"
        path.write_bytes(b"media")
        return {**info, "requested_downloads": [{"filepath": str(path)}]}

    def prepare_filename(self, info: dict) -> str:
        return str(Path(self.options["outtmpl"]).parent / "Reel-ABC123.mp4")


class DownloaderFallbackRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeYoutubeDL.instances = []
        _FakeYoutubeDL.fail_first_attempt = False
        _FakeYoutubeDL.fail_all_attempts = None

    def _download(self, temp: str):
        downloader = MediaDownloader(Settings())
        with patch("worker.downloader.yt_dlp.YoutubeDL", _FakeYoutubeDL):
            return downloader._download_sync(
                "https://www.instagram.com/reel/ABC123/",
                Path(temp),
                audio_only=False,
                max_duration=600,
                max_height=720,
            )

    def test_format_error_retries_once_with_best(self) -> None:
        _FakeYoutubeDL.fail_first_attempt = True
        with tempfile.TemporaryDirectory() as temp:
            result = self._download(temp)
            self.assertTrue(result.path.is_file())
            self.assertEqual(len(_FakeYoutubeDL.instances), 2)
            first, second = _FakeYoutubeDL.instances
            self.assertEqual(first.options["format"], instagram_format(720))
            self.assertEqual(second.options["format"], "best")

    def test_successful_first_attempt_does_not_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self._download(temp)
            self.assertEqual(len(_FakeYoutubeDL.instances), 1)

    def test_other_errors_do_not_retry(self) -> None:
        _FakeYoutubeDL.fail_all_attempts = YtDlpDownloadError("Video unavailable")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(PermanentMediaError):
                self._download(temp)
            self.assertEqual(len(_FakeYoutubeDL.instances), 1)

    def test_format_error_on_retry_raises_after_one_retry(self) -> None:
        _FakeYoutubeDL.fail_all_attempts = FORMAT_NOT_AVAILABLE
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(PermanentMediaError):
                self._download(temp)
            self.assertEqual(len(_FakeYoutubeDL.instances), 2)


if __name__ == "__main__":
    unittest.main()
