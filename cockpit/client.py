"""The cockpit's socket client — the line protocol to the bus bridge.

A small synchronous client (plain `socket`, no asyncio) so it can run in a
background thread under the curses UI. It speaks the same newline-delimited JSON
the bridge does: inbound frames are bus events (dicts), outbound is a single
`chat.message`.

The byte-buffering is split out as `feed()` so it is unit-testable without a real
socket (partial frames, multiple frames per recv, blank lines).
"""
from __future__ import annotations

import json
import socket
from pathlib import Path


class LineBuffer:
    """Accumulates bytes and yields complete newline-delimited JSON objects."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[dict]:
        """Add bytes; return every complete event now available (possibly none)."""
        self._buf += data
        out: list[dict] = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
        return out


def encode_chat(text: str) -> bytes:
    """The single outbound frame: a chat line for the brain."""
    return (json.dumps({"topic": "chat.message", "payload": {"text": text}}) + "\n").encode("utf-8")


class CockpitClient:
    """Connects to the cockpit bridge's unix socket; streams events in, sends chat
    out. Not thread-safe for concurrent sends; the UI uses one reader thread and
    sends from the main thread."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._sock: socket.socket | None = None
        self._lines = LineBuffer()

    def connect(self, timeout: float = 5.0) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(timeout)
            s.connect(self.path)
            s.settimeout(None)
        except OSError:
            s.close()  # don't leak the fd on a failed/retried connect
            raise
        self._sock = s

    def send_chat(self, text: str) -> None:
        if self._sock is None:
            raise RuntimeError("not connected")
        self._sock.sendall(encode_chat(text))

    def events(self):
        """Blocking generator: yields each event dict as it arrives; ends on EOF."""
        if self._sock is None:
            raise RuntimeError("not connected")
        while True:
            try:
                data = self._sock.recv(4096)
            except OSError:
                return
            if not data:
                return
            for obj in self._lines.feed(data):
                yield obj

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
