from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import Settings
from worker.selfcheck import run_startup_self_check


class StartupSelfCheckTests(unittest.TestCase):
    def test_reports_versions_tools_and_valid_cookie_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cookies = Path(temp) / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\nsecret=value\n")
            with patch("worker.selfcheck.shutil.which", return_value="/usr/bin/tool"):
                with self.assertLogs("worker.selfcheck", level=logging.INFO) as logs:
                    run_startup_self_check(Settings(cookies_path=cookies))
            output = "\n".join(logs.output)
            self.assertIn("yt-dlp version", output)
            self.assertIn("deno found", output)
            self.assertIn("ffmpeg found", output)
            self.assertIn("ffprobe found", output)
            self.assertIn("supported Netscape header", output)
            self.assertNotIn("secret=value", output)
            self.assertNotIn(str(cookies), output)

    def test_missing_tools_and_invalid_cookies_warn_with_fix_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cookies = Path(temp) / "cookies.txt"
            cookies.write_text("not a cookie header")
            with patch("worker.selfcheck.shutil.which", return_value=None):
                with self.assertLogs("worker.selfcheck", level=logging.INFO) as logs:
                    run_startup_self_check(Settings(cookies_path=cookies))
            output = "\n".join(logs.output)
            self.assertIn("deno not found; fix:", output)
            self.assertIn("ffmpeg not found; fix:", output)
            self.assertIn("ffprobe not found; fix:", output)
            self.assertIn("no supported Netscape header; fix:", output)

    def test_missing_cookie_file_does_not_raise(self) -> None:
        with patch("worker.selfcheck.shutil.which", return_value="/usr/bin/tool"):
            with self.assertLogs("worker.selfcheck", level=logging.INFO) as logs:
                run_startup_self_check(Settings(cookies_path=None))
        self.assertIn("cookies file not present; fix:", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
