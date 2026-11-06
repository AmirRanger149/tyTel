from __future__ import annotations

import unittest

from worker.downloader import MediaTooLong, UnsupportedMedia, MediaDownloader


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


if __name__ == "__main__":
    unittest.main()
