"""Cockpit client tests — the line protocol, framing, and chat encoding.

Also an end-to-end check against the real CockpitBridge over a unix socket: a
chat line in reaches the bus, and a forwarded event comes back out.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cockpit.client import CockpitClient, LineBuffer, encode_chat
from core.bus import Bus
from core.cockpit_bridge import CockpitBridge
from core.tile import Event


class LineBufferTests(unittest.TestCase):
    def test_single_frame(self) -> None:
        b = LineBuffer()
        self.assertEqual(b.feed(b'{"topic":"a","ts":0,"payload":{}}\n'),
                         [{"topic": "a", "ts": 0, "payload": {}}])

    def test_partial_then_complete(self) -> None:
        b = LineBuffer()
        self.assertEqual(b.feed(b'{"topic":"a",'), [])      # incomplete — nothing yet
        self.assertEqual(b.feed(b'"ts":0}\n'), [{"topic": "a", "ts": 0}])

    def test_multiple_frames_in_one_chunk(self) -> None:
        b = LineBuffer()
        out = b.feed(b'{"x":1}\n{"y":2}\n')
        self.assertEqual(out, [{"x": 1}, {"y": 2}])

    def test_blank_and_garbage_lines_skipped(self) -> None:
        b = LineBuffer()
        out = b.feed(b'\n\nnot json\n{"ok":1}\n')
        self.assertEqual(out, [{"ok": 1}])

    def test_encode_chat(self) -> None:
        obj = json.loads(encode_chat("hi there"))
        self.assertEqual(obj, {"topic": "chat.message", "payload": {"text": "hi there"}})


class ClientBridgeRoundTripTests(unittest.TestCase):
    """The client (sync sockets, as it runs under curses) against the real async
    bridge — exercised across a thread boundary like the real UI."""

    def test_chat_in_and_event_out(self) -> None:
        tmp = TemporaryDirectory()
        sock = Path(tmp.name) / "cockpit.sock"
        received: list = []
        chat_seen = threading.Event()

        async def server() -> None:
            bus = Bus()
            bridge = CockpitBridge(bus, path=sock)
            await bridge.start()

            async def on_chat(e: Event) -> None:
                received.append(e)
                # reply so the client has an inbound event to read
                await bus.publish(Event("chat.reply", 0.0, {"text": "ack"}, source="reason"))
                chat_seen.set()

            bus.subscribe("chat.message", on_chat)

            # run until the client has done its round-trip
            for _ in range(200):
                await asyncio.sleep(0.01)
                if chat_seen.is_set():
                    break
            await asyncio.sleep(0.05)
            await bridge.stop()
            await bus.aclose()

        def run_server() -> None:
            asyncio.run(server())

        t = threading.Thread(target=run_server)
        t.start()
        try:
            # wait for the socket to appear
            client = CockpitClient(sock)
            for _ in range(200):
                try:
                    client.connect()
                    break
                except OSError:
                    import time
                    time.sleep(0.01)
            client.send_chat("lights please")
            # read the reply the server publishes back
            reply = None
            for obj in client.events():
                if obj.get("topic") == "chat.reply":
                    reply = obj
                    break
            client.close()
            self.assertIsNotNone(reply)
            self.assertEqual(reply["payload"]["text"], "ack")
        finally:
            t.join(timeout=5)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].payload["text"], "lights please")
        self.assertEqual(received[0].source, "cockpit")
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
