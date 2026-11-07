from __future__ import annotations

import unittest

from worker.compressor import MediaCompressor


class CompressionHeightTests(unittest.TestCase):
    def test_ladder_starts_at_chosen_quality_and_steps_down(self) -> None:
        self.assertEqual(
            MediaCompressor.compression_heights(1080), (1080, 720, 480, 360)
        )
        self.assertEqual(
            MediaCompressor.compression_heights(720), (720, 480, 360)
        )
        self.assertEqual(MediaCompressor.compression_heights(480), (480, 360))
        self.assertEqual(MediaCompressor.compression_heights(360), (360,))

    def test_ladder_rejects_unknown_heights(self) -> None:
        with self.assertRaises(ValueError):
            MediaCompressor.compression_heights(1440)


if __name__ == "__main__":
    unittest.main()
