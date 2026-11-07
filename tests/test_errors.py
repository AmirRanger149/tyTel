from __future__ import annotations

import errno
import unittest

from yt_dlp.utils import DownloadError

from worker.errors import (
    AuthenticationRequired,
    MediaTooLarge,
    MediaTooLong,
    TransientMediaError,
    UnsupportedMedia,
    is_authentication_error,
    is_retryable,
)


class ErrorClassificationTests(unittest.TestCase):
    def test_authentication_and_permanent_errors_do_not_retry(self) -> None:
        permanent = (
            DownloadError("Sign in to confirm you're not a bot"),
            DownloadError("ERROR: Private video"),
            DownloadError("Video unavailable"),
            DownloadError("This video is age-restricted"),
            DownloadError("Video not available in your country"),
            DownloadError("Unsupported URL"),
            DownloadError("This is a live stream"),
            MediaTooLong("too long"),
            MediaTooLarge("too large"),
            UnsupportedMedia("unsupported"),
            OSError(errno.EROFS, "Read-only file system"),
            PermissionError(errno.EACCES, "Permission denied"),
        )
        for exc in permanent:
            with self.subTest(exc=str(exc)):
                self.assertFalse(is_retryable(exc))

    def test_only_transient_errors_retry(self) -> None:
        transient = (
            TransientMediaError("temporary ffmpeg failure"),
            DownloadError("The read operation timed out"),
            DownloadError("HTTP Error 429: Too Many Requests"),
            DownloadError("HTTP Error 503: Service Unavailable"),
            ConnectionError("connection reset"),
            TimeoutError("timeout"),
        )
        for exc in transient:
            with self.subTest(exc=str(exc)):
                self.assertTrue(is_retryable(exc))
        self.assertFalse(is_retryable(DownloadError("unknown extractor failure")))

    def test_authentication_is_detected_separately(self) -> None:
        self.assertTrue(is_authentication_error(AuthenticationRequired("sign in")))
        self.assertTrue(
            is_authentication_error(DownloadError("Sign in to confirm you're not a bot"))
        )
        self.assertFalse(is_authentication_error(DownloadError("Private video")))


if __name__ == "__main__":
    unittest.main()
