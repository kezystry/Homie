"""Live camera rendering for the cockpit — a curses-native thumbnail.

The owner wants a *graphic* cam view inside the terminal (no web, no mouse). A
bare Linux console can't host sixel/kitty graphics, and curses can't safely print
raw `chafa` ANSI (the escape codes corrupt curses' own screen model). So the
thumbnail is rendered the only way that composes cleanly with curses: each frame
is downsampled to one 256-colour cell per character and drawn as coloured blocks
via curses colour pairs. It reads as a recognisable picture — enough to see who's
at the door — at a few frames a second and a trivial CPU cost.

The crisp FULL view is a separate fullscreen surface (`mpv --vo=drm`), launched
from the cockpit like any other app — terminal art is for the glance, mpv is for
the look. See `cockpit/launcher.py`.

Capture is on-demand single-frame grabs (no v4l2loopback, no second reader): a
background thread periodically asks `ffmpeg` for one frame scaled to the current
pane size. Everything degrades gracefully — no `ffmpeg`, no camera, or a bad
frame just shows an "offline" pane; the cockpit never blocks or crashes on it.

Pixels read straight off the local `/dev/video*` device and are rendered locally;
a frame never crosses the bus (the standing privacy rule: imagery stays on-node).
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

# xterm-256 6×6×6 colour cube breakpoints. We map each pixel to the nearest cube
# colour and draw it as a filled cell, so the whole thumbnail needs only the 216
# cube pairs — well inside any 256-colour console's pair budget.
_LEVELS = (0, 95, 135, 175, 215, 255)


def nearest_256(r: int, g: int, b: int) -> int:
    """Map an RGB pixel to the nearest xterm-256 colour-cube index (16–231).

    The cube index is ``16 + 36*R + 6*G + B`` where R/G/B are each snapped to the
    nearest of the six cube levels. Use this when the terminal reports ≥256
    colours (e.g. a phone SSH client); it gives a recognisable picture."""
    def lvl(v: int) -> int:
        return min(range(6), key=lambda i: abs(_LEVELS[i] - v))

    return 16 + 36 * lvl(r) + 6 * lvl(g) + lvl(b)


# The 16 standard ANSI colours, as xterm's default RGB. On a bare Linux VT
# console (which can't do 256-colour) we quantise to these so the thumbnail still
# renders — coarse, but enough to read motion/presence at a glance.
_ANSI16 = (
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
    (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
    (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
)


def nearest_ansi(r: int, g: int, b: int, n: int = 16) -> int:
    """Map an RGB pixel to the nearest of the first ``n`` ANSI colours (n=8 or 16).
    Used on low-colour consoles where the 256-cube isn't available."""
    palette = _ANSI16[:n]
    return min(range(len(palette)),
               key=lambda i: (palette[i][0] - r) ** 2
               + (palette[i][1] - g) ** 2
               + (palette[i][2] - b) ** 2)


def frame_to_cells(rgb: bytes, cols: int, rows: int, quantize=nearest_256) -> list[list[int]]:
    """Turn a raw rgb24 frame already scaled to ``cols×rows`` into a grid of
    terminal colour indices (one per character cell), using ``quantize`` to pick
    the colour space (``nearest_256`` for rich terminals, ``nearest_ansi`` for a
    bare console). Raises ValueError if the buffer isn't exactly ``cols*rows*3``
    bytes, so a short/garbled grab is caught rather than smearing the pane."""
    if cols <= 0 or rows <= 0:
        return []
    want = cols * rows * 3
    if len(rgb) != want:
        raise ValueError(f"frame is {len(rgb)} bytes, expected {want} ({cols}×{rows} rgb24)")
    grid: list[list[int]] = []
    i = 0
    for _ in range(rows):
        line: list[int] = []
        for _ in range(cols):
            line.append(quantize(rgb[i], rgb[i + 1], rgb[i + 2]))
            i += 3
        grid.append(line)
    return grid


def _ffmpeg_grab(device: str, cols: int, rows: int, *, timeout: float = 4.0) -> Optional[bytes]:
    """Grab ONE frame from ``device`` scaled to ``cols×rows`` as raw rgb24, or
    None if ffmpeg is missing / the device can't be read / it times out. No shell,
    fixed argv — the device path is the only variable and it's not interpolated
    into a command string."""
    if shutil.which("ffmpeg") is None:
        return None
    argv = [
        "ffmpeg", "-loglevel", "quiet",
        "-f", "v4l2", "-i", device,
        "-frames:v", "1",
        "-vf", f"scale={cols}:{rows}",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ]
    try:
        out = subprocess.run(argv, capture_output=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out if len(out) == cols * rows * 3 else None


class CameraSource:
    """Periodically grabs and renders the latest frame in a background thread.

    The pane size is read fresh each tick from ``size_fn`` so the thumbnail tracks
    terminal resizes. ``grab`` is injectable (tests pass a fake; production uses
    ffmpeg). The UI calls ``cells()`` each redraw — it never blocks, returning the
    most recent grid or None when the camera is offline.
    """

    def __init__(
        self,
        device: str = "/dev/video0",
        *,
        size_fn: Callable[[], tuple[int, int]],
        interval: float = 0.4,
        grab: Optional[Callable[[str, int, int], Optional[bytes]]] = None,
        quantize=nearest_256,
    ) -> None:
        self.device = device
        self._size_fn = size_fn
        self._interval = interval
        self._grab = grab or _ffmpeg_grab
        self._quantize = quantize
        self._cells: Optional[list[list[int]]] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="cockpit-cam", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def cells(self) -> Optional[list[list[int]]]:
        with self._lock:
            return self._cells

    def online(self) -> bool:
        return self.cells() is not None

    def _loop(self) -> None:
        while self._running:
            cols, rows = self._size_fn()
            grid = None
            if cols > 0 and rows > 0:
                rgb = self._grab(self.device, cols, rows)
                if rgb is not None:
                    try:
                        grid = frame_to_cells(rgb, cols, rows, self._quantize)
                    except ValueError:
                        grid = None
            with self._lock:
                self._cells = grid
            time.sleep(self._interval)
