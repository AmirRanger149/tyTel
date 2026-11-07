from __future__ import annotations

import unittest

from core.url_utils import (
    cache_quality,
    extract_urls,
    normalize_url,
    parse_video_height,
    video_format,
)


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


class QualityTests(unittest.TestCase):
    def test_cache_quality_per_height(self) -> None:
        self.assertEqual(cache_quality(True), "audio")
        # The default stays 720p even though 1080p is now offered.
        self.assertEqual(cache_quality(False), "video-720p")
        self.assertEqual(cache_quality(False, 1080), "video-1080p")
        self.assertEqual(cache_quality(False, 480), "video-480p")
        self.assertEqual(cache_quality(False, 360), "video-360p")
        with self.assertRaises(ValueError):
            cache_quality(False, 1440)

    def test_parse_video_height(self) -> None:
        self.assertEqual(parse_video_height("video-1080p"), 1080)
        self.assertEqual(parse_video_height("video-720p"), 720)
        self.assertEqual(parse_video_height("video-480p"), 480)
        self.assertIsNone(parse_video_height("video-1440p"))
        self.assertIsNone(parse_video_height("audio"))
        self.assertIsNone(parse_video_height(""))
        self.assertIsNone(parse_video_height("video-abc"))

    def test_video_format_caps_height(self) -> None:
        self.assertEqual(
            video_format(480),
            "bestvideo[height<=?480][width>=?480]+bestaudio"
            "/best[width<=?480][height>=?480]"
            "/bestvideo[width<=?480]+bestaudio"
            "/best[height<=?480]"
            "/bestvideo+bestaudio"
            "/bv*"
            "/b"
            "/best",
        )
        self.assertIn("height<=?720", video_format(720))
        self.assertIn("width<=?720", video_format(720))
        self.assertTrue(video_format(1080).endswith("/best"))
        with self.assertRaises(ValueError):
            video_format(200)


def _synthetic_format(format_id: str, width, height, vcodec: str, acodec: str, tbr: int) -> dict:
    return {
        "format_id": format_id,
        "ext": "mp4",
        "width": width,
        "height": height,
        "vcodec": vcodec,
        "acodec": acodec,
        "tbr": tbr,
        "protocol": "https",
        "url": "https://example.invalid/media",
    }


def _combined(width: int, height: int, tbr: int) -> dict:
    return _synthetic_format(
        f"c{width}x{height}", width, height, "avc1.640028", "mp4a.40.2", tbr
    )


def _video_only(width: int, height: int, tbr: int) -> dict:
    return _synthetic_format(
        f"v{width}x{height}", width, height, "avc1.640028", "none", tbr
    )


_AUDIO_ONLY = _synthetic_format("audio", None, None, "none", "mp4a.40.2", 128)


def _select_format_id(selector: str, formats: list[dict]) -> str:
    """Run yt-dlp's real format selection over synthetic formats."""

    import yt_dlp

    ydl = yt_dlp.YoutubeDL(
        {"quiet": True, "no_warnings": True, "format": selector, "simulate": True}
    )
    info = {
        "id": "x",
        "title": "t",
        "extractor": "test",
        "extractor_key": "Test",
        "webpage_url": "https://example.invalid/",
        "formats": [dict(item) for item in formats],
    }
    result = ydl.process_video_result(info, download=False)
    requested = result.get("requested_formats")
    if requested:
        return "+".join(item["format_id"] for item in requested)
    return str(result.get("format_id"))


class VideoFormatSelectionTests(unittest.TestCase):
    """The selector must work for portrait (Instagram/Shorts) formats,
    not just landscape ones: portrait frames report their long side as
    the height, so a height-only cap can match nothing."""

    def test_portrait_combined_formats_pick_width_capped_best(self) -> None:
        formats = [
            _combined(1080, 1920, 4000),
            _combined(720, 1280, 2200),
            _combined(480, 854, 1100),
        ]
        self.assertEqual(
            _select_format_id(video_format(720), formats), "c720x1280"
        )
        self.assertEqual(
            _select_format_id(video_format(480), formats), "c480x854"
        )

    def test_portrait_split_formats_pick_width_capped_best(self) -> None:
        formats = [
            _video_only(1080, 1920, 3800),
            _video_only(720, 1280, 2000),
            _video_only(480, 854, 1000),
            _AUDIO_ONLY,
        ]
        self.assertEqual(
            _select_format_id(video_format(720), formats), "v720x1280+audio"
        )

    def test_landscape_formats_still_pick_height_capped_best(self) -> None:
        formats = [
            _video_only(1920, 1080, 4500),
            _video_only(1280, 720, 2500),
            _video_only(854, 480, 1200),
            _combined(1280, 720, 2600),
            _AUDIO_ONLY,
        ]
        self.assertEqual(
            _select_format_id(video_format(720), formats), "v1280x720+audio"
        )
        self.assertEqual(
            _select_format_id(video_format(480), formats), "v854x480+audio"
        )


if __name__ == "__main__":
    unittest.main()
