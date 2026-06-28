"""Cockpit bridge tests — the capability-scoped unix-socket window onto the bus.

Covers the load-bearing invariants from the cockpit council: read+chat only,
no actuator authority, privacy fences the boundary, a 0600 unix socket (never
TCP), and no origin spoofing on inbound events.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import json
import os
import socket
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.cockpit_bridge import CockpitBridge, CockpitPolicy, decode_inbound, encode
from core.tile import Event


def collect(sink: list):
    async def handler(e: Event) -> None:
        sink.append(e)

    return handler


class PolicyTests(unittest.TestCase):
    def test_outbound_allowlist(self) -> None:
        p = CockpitPolicy()
        # the cockpit may SEE these
        self.assertTrue(p.may_send("interface.spoken"))  # GOVERNED speech the owner hears
        self.assertTrue(p.may_send("security.alert"))
        self.assertTrue(p.may_send("presence.arrived"))
        self.assertTrue(p.may_send("actuator.done"))
        self.assertTrue(p.may_send("chat.reply"))
        self.assertTrue(p.may_send("wake.decision"))  # cortex wake telemetry (M3)
        # the cockpit may SEE wake telemetry but may never PUBLISH it back
        self.assertFalse(p.may_receive("wake.decision"))
        # but NOT the raw, ungoverned speech channel — only the VoiceGate's output renders,
        # so a tile can never reach the owner without passing the speech budget (Phase A).
        self.assertFalse(p.may_send("interface.say"))
        # ...nor raw perception internals or the act *request*
        self.assertFalse(p.may_send("actuator.requested"))
        self.assertFalse(p.may_send("sensor.camera.frame"))
        self.assertFalse(p.may_send("confirm.requested"))

    def test_inbound_is_chat_only(self) -> None:
        p = CockpitPolicy()
        self.assertTrue(p.may_receive("chat.message"))
        # the cockpit may drive NOTHING
        self.assertFalse(p.may_receive("actuator.requested"))
        self.assertFalse(p.may_receive("confirm.response"))
        self.assertFalse(p.may_receive("presence.arrived"))
        self.assertFalse(p.may_receive("interface.say"))


class DecodeTests(unittest.TestCase):
    def test_sanitizes_inbound(self) -> None:
        # a client cannot forge source/id/origin/ttl — only topic+payload honored
        line = json.dumps(
            {"topic": "chat.message", "payload": {"text": "hi"},
             "source": "perception", "origin": "evil-node", "id": "x", "ttl": 9}
        )
        ev = decode_inbound(line)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.topic, "chat.message")
        self.assertEqual(ev.payload, {"text": "hi"})
        self.assertEqual(ev.source, "cockpit")  # forced
        self.assertIsNone(ev.origin)            # not honored
        self.assertIsNone(ev.id)
        self.assertIsNone(ev.ttl)

    def test_rejects_malformed(self) -> None:
        self.assertIsNone(decode_inbound("not json"))
        self.assertIsNone(decode_inbound(json.dumps([1, 2, 3])))     # not an object
        self.assertIsNone(decode_inbound(json.dumps({"payload": {}})))  # no topic
        self.assertIsNone(decode_inbound(json.dumps({"topic": ""})))    # empty topic
        self.assertIsNone(decode_inbound(json.dumps({"topic": "chat.message", "payload": 5})))

    def test_encode_roundtrips(self) -> None:
        data = encode(Event("interface.say", 1.5, {"text": "hello"}, source="reason"))
        self.assertTrue(data.endswith(b"\n"))
        obj = json.loads(data)
        self.assertEqual(obj["topic"], "interface.say")
        self.assertEqual(obj["payload"], {"text": "hello"})


class BridgeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.sock = Path(self._tmp.name) / "cockpit.sock"
        self.bus = Bus()
        self.bridge = CockpitBridge(self.bus, path=self.sock)
        await self.bridge.start()

    async def asyncTearDown(self) -> None:
        await self.bridge.stop()
        await self.bus.aclose()
        self._tmp.cleanup()

    async def _readline(self, reader, timeout=1.0):
        return await asyncio.wait_for(reader.readline(), timeout)

    async def _connect(self):
        """Connect and wait until the server has registered the client, so a
        subsequent publish actually has somewhere to fan out to."""
        reader, writer = await asyncio.open_unix_connection(path=str(self.sock))
        for _ in range(100):
            if self.bridge._clients:
                break
            await asyncio.sleep(0.01)
        return reader, writer

    async def test_socket_is_0600_unix_not_tcp(self) -> None:
        mode = stat.S_IMODE(os.stat(self.sock).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertTrue(stat.S_ISSOCK(os.stat(self.sock).st_mode))
        # the listening socket is AF_UNIX — never a TCP port
        self.assertEqual(self.bridge._server.sockets[0].family, socket.AF_UNIX)

    async def test_forwards_allowed_event(self) -> None:
        reader, writer = await self._connect()
        await self.bus.publish(Event("interface.spoken", 0.0, {"text": "evening"}, source="reason"))
        await self.bus.drain()
        line = await self._readline(reader)
        obj = json.loads(line)
        self.assertEqual(obj["topic"], "interface.spoken")
        self.assertEqual(obj["payload"]["text"], "evening")
        writer.close()

    async def test_does_not_forward_forbidden(self) -> None:
        reader, writer = await self._connect()
        # a forbidden (frame) topic is not even in the allowlist; and the guard
        # would block it regardless. Publish one, then an allowed one, and assert
        # only the allowed one arrives.
        await self.bus.publish(Event("sensor.camera.frame", 0.0, {"raw": "x"}))
        await self.bus.publish(Event("security.alert", 0.0, {"reason": "novel"}))
        await self.bus.drain()
        obj = json.loads(await self._readline(reader))
        self.assertEqual(obj["topic"], "security.alert")
        writer.close()

    async def test_inbound_chat_reaches_bus(self) -> None:
        chat = []
        self.bus.subscribe("chat.message", collect(chat))
        reader, writer = await asyncio.open_unix_connection(path=str(self.sock))
        writer.write(json.dumps({"topic": "chat.message", "payload": {"text": "are the doors locked?"}}).encode() + b"\n")
        await writer.drain()
        await asyncio.sleep(0.05)
        await self.bus.drain()
        self.assertEqual(len(chat), 1)
        self.assertEqual(chat[0].payload["text"], "are the doors locked?")
        self.assertEqual(chat[0].source, "cockpit")
        writer.close()

    async def test_inbound_actuator_is_refused(self) -> None:
        acts = []
        self.bus.subscribe("actuator.**", collect(acts))
        reader, writer = await asyncio.open_unix_connection(path=str(self.sock))
        # a malicious cockpit tries to drive a lock — must be dropped server-side
        writer.write(json.dumps({"topic": "actuator.requested",
                                 "payload": {"actuator": "lock.front_door", "value": "unlock"}}).encode() + b"\n")
        await writer.drain()
        await asyncio.sleep(0.05)
        await self.bus.drain()
        self.assertEqual(acts, [])  # never published
        writer.close()


if __name__ == "__main__":
    unittest.main()
