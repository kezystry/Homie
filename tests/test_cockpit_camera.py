"""Camera-rendering tests — the pure pixel→cell transforms.

The curses drawing and the ffmpeg grab need a real terminal/webcam and aren't
unit-tested (same stance as the TUI render). The colour quantisation, frame
decoding, and the background source's latest-frame behaviour are pure and pinned
here.

Run: python3 -m unittest discover -s tests
"""
import unittest

from cockpit.camera import (
    CameraSource,
    frame_to_cells,
    nearest_256,
    nearest_ansi,
)


class QuantiseTests(unittest.TestCase):
    def test_256_cube_endpoints(self) -> None:
        self.assertEqual(nearest_256(0, 0, 0), 16)        # cube origin
        self.assertEqual(nearest_256(255, 255, 255), 231)  # cube far corner
        # pure red snaps to the red face of the cube (16 + 36*5 = 196)
        self.assertEqual(nearest_256(255, 0, 0), 196)

    def test_256_is_in_cube_range(self) -> None:
        for rgb in [(10, 200, 30), (123, 45, 67), (250, 250, 5)]:
            idx = nearest_256(*rgb)
            self.assertTrue(16 <= idx <= 231, idx)

    def test_ansi16_black_and_white(self) -> None:
        self.assertEqual(nearest_ansi(0, 0, 0), 0)        # black
        self.assertEqual(nearest_ansi(255, 255, 255), 15)  # bright white
        self.assertEqual(nearest_ansi(250, 0, 0), 9)       # bright red

    def test_ansi8_stays_in_low_half(self) -> None:
        for rgb in [(255, 255, 255), (0, 255, 0), (128, 128, 128)]:
            self.assertTrue(0 <= nearest_ansi(*rgb, 8) <= 7)


class FrameTests(unittest.TestCase):
    def test_decodes_grid(self) -> None:
        # 2×1 frame: black pixel then white pixel
        rgb = bytes([0, 0, 0, 255, 255, 255])
        grid = frame_to_cells(rgb, 2, 1)
        self.assertEqual(grid, [[16, 231]])

    def test_quantiser_is_pluggable(self) -> None:
        rgb = bytes([0, 0, 0, 255, 255, 255])
        grid = frame_to_cells(rgb, 2, 1, quantize=nearest_ansi)
        self.assertEqual(grid, [[0, 15]])

    def test_short_buffer_raises(self) -> None:
        with self.assertRaises(ValueError):
            frame_to_cells(bytes([0, 0, 0]), 2, 1)  # only 1 pixel for a 2-wide row

    def test_zero_size_is_empty(self) -> None:
        self.assertEqual(frame_to_cells(b"", 0, 0), [])


class SourceTests(unittest.TestCase):
    def test_offline_until_started(self) -> None:
        src = CameraSource(size_fn=lambda: (2, 1), grab=lambda d, c, r: None)
        self.assertIsNone(src.cells())
        self.assertFalse(src.online())

    def test_one_tick_renders_latest_frame(self) -> None:
        white = bytes([255, 255, 255, 255, 255, 255])
        src = CameraSource(size_fn=lambda: (2, 1), grab=lambda d, c, r: white)
        # drive a single loop iteration directly (no thread) for determinism
        src._running = True
        cols, rows = src._size_fn()
        rgb = src._grab(src.device, cols, rows)
        src._cells = frame_to_cells(rgb, cols, rows)
        self.assertEqual(src.cells(), [[231, 231]])
        self.assertTrue(src.online())

    def test_bad_grab_keeps_offline(self) -> None:
        # a grab that returns a wrong-sized buffer must not crash the caller
        src = CameraSource(size_fn=lambda: (2, 1), grab=lambda d, c, r: b"\x00")
        rgb = src._grab("x", 2, 1)
        with self.assertRaises(ValueError):
            frame_to_cells(rgb, 2, 1)


if __name__ == "__main__":
    unittest.main()
