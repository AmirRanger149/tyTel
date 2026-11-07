from __future__ import annotations

import unittest

from core.sanitize import sanitize_message
from worker.downloader import YtDlpLogger


class SanitizationTests(unittest.TestCase):
    def test_redacts_credentials_cookies_paths_and_queries(self) -> None:
        source_path = "/private/secrets/cookies.txt"
        raw = (
            "Authorization: Bearer super-secret "
            "Cookie: SID=very-secret; HSID=also-secret "
            "token=abc123 https://youtube.com/watch?v=video123&utm_source=x"
            f" {source_path} 123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        )
        clean = sanitize_message(raw, (source_path, "super-secret"))
        for secret in (
            "super-secret", "very-secret", "also-secret", "abc123", "utm_source",
            source_path, "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        ):
            self.assertNotIn(secret, clean)
        self.assertIn("v=video123", clean)
        self.assertNotIn("standalone-secret", sanitize_message("SAPISID=standalone-secret"))

    def test_ytdlp_events_include_sanitized_message(self) -> None:
        logger = YtDlpLogger(("/secret/cookies.txt",))
        with self.assertLogs("worker.downloader", level="WARNING") as captured:
            logger.warning("failed /secret/cookies.txt? no: Cookie: SID=secret")
            logger.error("https://youtu.be/video123?token=secret")
        output = "\n".join(captured.output)
        self.assertIn("yt-dlp warning", output)
        self.assertIn("yt-dlp error", output)
        self.assertNotIn("SID=secret", output)
        self.assertNotIn("token=secret", output)
        self.assertNotIn("/secret/cookies.txt", output)


if __name__ == "__main__":
    unittest.main()
