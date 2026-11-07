from __future__ import annotations

import errno
import unittest

from yt_dlp.utils import DownloadError

from worker.errors import (
    AuthenticationRequired,
    MediaTooLarge,
    MediaTooLong,
    PhotoPostUnsupported,
    TransientMediaError,
    UnsupportedMedia,
    is_authentication_error,
    is_photo_post_error,
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

    def test_instagram_photo_post_errors(self) -> None:
        for message in (
            "ERROR: [Instagram] DOJWDMBCTTX: There is no video in this post",
            "ERROR: [Instagram] Dc_FW3tDi12: No video formats found!",
        ):
            with self.subTest(message=message):
                exc = DownloadError(message)
                self.assertTrue(is_photo_post_error(exc))
                self.assertFalse(is_retryable(exc))
        # The same phrasing without the Instagram extractor is not
        # treated as a photo post.
        self.assertFalse(
            is_photo_post_error(DownloadError("There is no video in this post"))
        )
        self.assertTrue(is_photo_post_error(PhotoPostUnsupported("photo")))

    def test_instagram_checkpoint_and_rate_limit(self) -> None:
        self.assertTrue(
            is_authentication_error(
                DownloadError("[Instagram] checkpoint_required: login required")
            )
        )
        self.assertTrue(
            is_retryable(
                DownloadError(
                    "Instagram rate limit: please wait a few minutes "
                    "before you try again"
                )
            )
        )

    def test_authentication_is_detected_separately(self) -> None:
        self.assertTrue(is_authentication_error(AuthenticationRequired("sign in")))
        self.assertTrue(
            is_authentication_error(DownloadError("Sign in to confirm you're not a bot"))
        )
        self.assertFalse(is_authentication_error(DownloadError("Private video")))


if __name__ == "__main__":
    unittest.main()
