"""A minimal RFC 6455 WebSocket client on stdlib asyncio — no third-party dependency.

Home Assistant's native push channel is its WebSocket API. There is no stdlib
WebSocket client, and the project's discipline is "stdlib-only where feasible": a
headless NixOS box should not need a pip/venv layer just to hear a light change.
This module is that missing piece — small enough to read, with the parts that can
be tested without a live server (the handshake-accept hash and the frame codec)
factored out as pure functions and exercised in tests/test_ws.py.

Scope is deliberately the subset HA speaks: small UTF-8 **text** frames, client
masking (mandatory per spec), fragmentation reassembly, and ping/close control
frames. Binary frames and per-message compression are not needed and not handled.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import struct
from urllib.parse import urlsplit

# The magic GUID from RFC 6455 §1.3 — concatenated with the client key to derive
# the server's expected Sec-WebSocket-Accept.
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def accept_key(client_key: str) -> str:
    """The Sec-WebSocket-Accept value the server must return for `client_key`."""
    digest = hashlib.sha1((client_key + _GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(payload: bytes, *, opcode: int = OP_TEXT, mask_key: bytes | None = None) -> bytes:
    """Encode a single (final) client frame. Client→server frames MUST be masked
    (RFC 6455 §5.3); `mask_key` is injectable so the codec is deterministically
    testable, else a fresh random 4-byte key is used."""
    if mask_key is None:
        mask_key = os.urandom(4)
    n = len(payload)
    header = bytearray([0x80 | opcode])  # FIN=1, RSV=0
    if n < 126:
        header.append(0x80 | n)  # MASK=1
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", n)
    header += mask_key
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return bytes(header) + masked


def parse_frame(data: bytes) -> tuple[bool, int, bytes] | None:
    """Parse one frame from the front of `data`. Returns (fin, opcode, payload) or
    None if `data` does not yet hold a whole frame. Pure — used by tests and as the
    decode half of the stream reader. Server→client frames are not masked."""
    if len(data) < 2:
        return None
    b0, b1 = data[0], data[1]
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    off = 2
    if length == 126:
        if len(data) < off + 2:
            return None
        length = struct.unpack("!H", data[off:off + 2])[0]
        off += 2
    elif length == 127:
        if len(data) < off + 8:
            return None
        length = struct.unpack("!Q", data[off:off + 8])[0]
        off += 8
    mask_key = b""
    if masked:
        if len(data) < off + 4:
            return None
        mask_key = data[off:off + 4]
        off += 4
    if len(data) < off + length:
        return None
    payload = bytearray(data[off:off + length])
    if masked:
        for i in range(length):
            payload[i] ^= mask_key[i % 4]
    return fin, opcode, bytes(payload)


class WSClient:
    """A connected WebSocket. Construct via `await WSClient.connect(url)`. Text in,
    text out; control frames (ping/close) are handled inside `recv_text`."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._r = reader
        self._w = writer
        self._send_lock = asyncio.Lock()  # one writer; frames must not interleave

    @classmethod
    async def connect(cls, url: str, *, headers: dict[str, str] | None = None) -> "WSClient":
        parts = urlsplit(url)
        secure = parts.scheme == "wss"
        host = parts.hostname or "localhost"
        port = parts.port or (443 if secure else 80)
        reader, writer = await asyncio.open_connection(host, port, ssl=secure)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        for k, v in (headers or {}).items():
            lines.append(f"{k}: {v}")
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
        await writer.drain()

        status = await reader.readline()
        if b" 101 " not in status:
            writer.close()
            raise ConnectionError(f"WebSocket upgrade refused: {status!r}")
        got_accept = None
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"sec-websocket-accept":
                got_accept = value.strip().decode("ascii")
        if got_accept != accept_key(key):
            writer.close()
            raise ConnectionError("WebSocket accept hash mismatch")
        return cls(reader, writer)

    async def send_text(self, text: str) -> None:
        frame = encode_frame(text.encode("utf-8"), opcode=OP_TEXT)
        async with self._send_lock:
            self._w.write(frame)
            await self._w.drain()

    async def _read_frame(self) -> tuple[bool, int, bytes]:
        head = await self._r.readexactly(2)
        length = head[1] & 0x7F
        ext = b""
        if length == 126:
            ext = await self._r.readexactly(2)
            length = struct.unpack("!H", ext)[0]
        elif length == 127:
            ext = await self._r.readexactly(8)
            length = struct.unpack("!Q", ext)[0]
        masked = bool(head[1] & 0x80)
        mask = await self._r.readexactly(4) if masked else b""
        body = await self._r.readexactly(length)
        frame = parse_frame(head + ext + mask + body)
        assert frame is not None  # we read exactly one whole frame
        return frame

    async def recv_text(self) -> str:
        """Return the next text message, reassembling fragments and transparently
        answering pings. Raises ConnectionError when the peer closes."""
        chunks: list[bytes] = []
        while True:
            fin, opcode, payload = await self._read_frame()
            if opcode == OP_CLOSE:
                raise ConnectionError("WebSocket closed by peer")
            if opcode == OP_PING:
                async with self._send_lock:
                    self._w.write(encode_frame(payload, opcode=OP_PONG))
                    await self._w.drain()
                continue
            if opcode == OP_PONG:
                continue
            chunks.append(payload)
            if fin:
                return b"".join(chunks).decode("utf-8")

    async def close(self) -> None:
        try:
            async with self._send_lock:
                self._w.write(encode_frame(b"", opcode=OP_CLOSE))
                await self._w.drain()
        except Exception:
            pass
        self._w.close()
        try:
            await self._w.wait_closed()
        except Exception:
            pass
