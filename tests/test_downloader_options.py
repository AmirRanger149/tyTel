from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import Settings
from core.url_utils import video_format
from worker.downloader import (
    MediaDownloader,
    build_format_selector,
    instagram_format,
    is_instagram_url,
)


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
            self.assertIn("height<=?720", options["format"])
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
            self.assertEqual(options["format"], video_format(360))
            self.assertNotIn("720", options["format"])
            options_1080 = downloader._options(Path(temp), False, max_height=1080)
            self.assertIn("height<=?1080", options_1080["format"])
            with self.assertRaises(ValueError):
                downloader._options(Path(temp), False, max_height=1440)

    def test_empty_cookie_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cookies = Path(temp) / "cookies.txt"
            cookies.touch()
            options = MediaDownloader(Settings(cookies_path=cookies))._options(
                Path(temp), audio_only=True
            )
            self.assertNotIn("cookiefile", options)
            self.assertEqual(options["postprocessors"][0]["key"], "FFmpegExtractAudio")


class FormatSelectorBuilderTests(unittest.TestCase):
    def test_youtube_uses_the_orientation_aware_selector(self) -> None:
        selector = build_format_selector(
            "https://www.youtube.com/watch?v=abc", audio_only=False, max_height=720
        )
        self.assertEqual(selector, video_format(720))
        self.assertIn("height<=?720", selector)
        self.assertTrue(selector.endswith("/b/best"))

    def test_instagram_uses_the_bv_star_selector(self) -> None:
        selector = build_format_selector(
            "https://www.instagram.com/reel/ABC123/",
            audio_only=False,
            max_height=720,
        )
        self.assertEqual(selector, instagram_format(720))
        self.assertTrue(selector.startswith("bv*[height<=?720]+ba"))
        self.assertIn("width<=?720", selector)
        self.assertTrue(selector.endswith("/bv*/b/best"))

    def test_audio_only_ignores_platform_and_height(self) -> None:
        for url in (
            "https://www.youtube.com/watch?v=abc",
            "https://www.instagram.com/reel/ABC123/",
        ):
            self.assertEqual(
                build_format_selector(url, audio_only=True, max_height=720),
                "bestaudio/best",
            )

    def test_options_use_the_platform_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            downloader = MediaDownloader(Settings())
            options = downloader._options(
                Path(temp),
                False,
                url="https://www.instagram.com/reel/ABC123/",
                max_height=720,
            )
            self.assertEqual(options["format"], instagram_format(720))

    def test_is_instagram_url(self) -> None:
        self.assertTrue(is_instagram_url("https://www.instagram.com/reel/x/"))
        self.assertTrue(is_instagram_url("https://instagram.com/p/x/"))
        self.assertFalse(is_instagram_url("https://www.youtube.com/watch?v=x"))
        self.assertFalse(is_instagram_url("https://notinstagram.com/reel/x/"))


if __name__ == "__main__":
    unittest.main()
