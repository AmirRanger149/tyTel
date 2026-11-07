from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import Settings
from worker.downloader import MediaDownloader


class DownloaderOptionTests(unittest.TestCase):
    def test_cookies_proxy_and_safety_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cookies = Path(temp) / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            settings = Settings(
                cookies_path=cookies,
                proxy_url="http://proxy.example:8080",
            )
            downloader = MediaDownloader(settings)
            cookie_copy = downloader._copy_cookies(Path(temp))
            self.assertIsNotNone(cookie_copy)
            assert cookie_copy is not None
            options = downloader._options(Path(temp), False, cookie_copy)
            self.assertTrue(options["noplaylist"])
            self.assertIn("height<=720", options["format"])
            self.assertEqual(options["cookiefile"], str(cookie_copy))
            self.assertNotEqual(options["cookiefile"], str(cookies))
            self.assertEqual(cookie_copy.stat().st_mode & 0o777, 0o600)
            self.assertEqual(cookies.read_text(encoding="utf-8"), "# Netscape HTTP Cookie File\n")
            self.assertEqual(options["proxy"], settings.proxy_url)
            self.assertNotIn("cookiefile", repr({k: v for k, v in options.items() if k != "cookiefile"}))

    def test_selected_height_changes_format_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            downloader = MediaDownloader(Settings())
            options = downloader._options(Path(temp), False, max_height=360)
            self.assertEqual(
                options["format"],
                "bestvideo[height<=360]+bestaudio/best[height<=360]",
            )
            self.assertNotIn("720", options["format"])
            with self.assertRaises(ValueError):
                downloader._options(Path(temp), False, max_height=1080)

    def test_empty_cookie_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cookies = Path(temp) / "cookies.txt"
            cookies.touch()
            options = MediaDownloader(Settings(cookies_path=cookies))._options(
                Path(temp), audio_only=True
            )
            self.assertNotIn("cookiefile", options)
            self.assertEqual(options["postprocessors"][0]["key"], "FFmpegExtractAudio")


if __name__ == "__main__":
    unittest.main()
