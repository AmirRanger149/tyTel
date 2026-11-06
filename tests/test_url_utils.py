from __future__ import annotations

import unittest

from core.url_utils import extract_urls, normalize_url


class YouTubeUrlTests(unittest.TestCase):
    def test_extracts_and_normalizes_youtube_variants(self) -> None:
        text = (
            "first https://youtu.be/dQw4w9WgXcQ?t=10, then "
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=abc and "
            "https://youtube.com/shorts/dQw4w9WgXcQ"
        )
        self.assertEqual(
            extract_urls(text), ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
        )

    def test_bare_media_links_and_persian_punctuation(self) -> None:
        self.assertEqual(
            extract_urls("youtu.be/dQw4w9WgXcQ، instagram.com/p/ABC123؛"),
            [
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://www.instagram.com/p/ABC123",
            ],
        )

    def test_embed_and_live_are_supported(self) -> None:
        for path in ("embed", "live"):
            with self.subTest(path=path):
                self.assertEqual(
                    normalize_url(f"https://www.youtube.com/{path}/abcDEF_1234?x=1"),
                    "https://www.youtube.com/watch?v=abcDEF_1234",
                )

    def test_rejects_youtube_playlist_channel_and_lookalikes(self) -> None:
        invalid = (
            "https://youtube.com/playlist?list=abc",
            "https://youtube.com/@channel",
            "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
            "https://evil-youtube.com/watch?v=dQw4w9WgXcQ",
            "https://user:secret@youtube.com/watch?v=dQw4w9WgXcQ",
            "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/",
        )
        for url in invalid:
            with self.subTest(url=url):
                self.assertIsNone(normalize_url(url))

    def test_instagram_posts_reels_tv_and_stories(self) -> None:
        cases = {
            "https://instagram.com/p/ABC_123/?utm_source=share": "https://www.instagram.com/p/ABC_123",
            "https://www.instagram.com/reel/ABC-123/": "https://www.instagram.com/reel/ABC-123",
            "https://instagram.com/reels/ABC123?igsh=secret": "https://www.instagram.com/reels/ABC123",
            "https://instagram.com/tv/ABC123": "https://www.instagram.com/tv/ABC123",
            "https://instagram.com/stories/some.user/123456/": "https://www.instagram.com/stories/some.user/123456",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_url(raw), expected)

    def test_rejects_instagram_profiles_and_lookalikes(self) -> None:
        for url in (
            "https://instagram.com/some.profile/",
            "https://instagram.com/explore/",
            "https://instagram.com.evil.example/p/ABC123",
        ):
            with self.subTest(url=url):
                self.assertIsNone(normalize_url(url))

    def test_ignores_non_urls_and_unsupported_domains(self) -> None:
        self.assertEqual(extract_urls("hello https://example.com/video"), [])


if __name__ == "__main__":
    unittest.main()
