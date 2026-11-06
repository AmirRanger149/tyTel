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
            options = MediaDownloader(settings)._options(Path(temp), audio_only=False)
            self.assertTrue(options["noplaylist"])
            self.assertIn("height<=720", options["format"])
            self.assertEqual(options["cookiefile"], str(cookies))
            self.assertEqual(options["proxy"], settings.proxy_url)
            self.assertNotIn("cookiefile", repr({k: v for k, v in options.items() if k != "cookiefile"}))

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
