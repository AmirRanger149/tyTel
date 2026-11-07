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
    PhotoPostUnsupported,
    UnsupportedMedia,
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


if __name__ == "__main__":
    unittest.main()
