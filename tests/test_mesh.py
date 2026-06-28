"""Mesh tests — node-transparent bridging, default-deny, privacy, loop suppression.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.bus import Bus
from core.mesh import MeshBridge, MeshPolicy, PrivacyGuard
from core.tile import Event


class InMemoryLink:
    """A paired in-memory Link standing in for the encrypted transport."""

    def __init__(self) -> None:
        self._peer: InMemoryLink | None = None
        self._handler = None

    @staticmethod
    def pair() -> tuple["InMemoryLink", "InMemoryLink"]:
        a, b = InMemoryLink(), InMemoryLink()
        a._peer, b._peer = b, a
        return a, b

    def on_receive(self, handler) -> None:
        self._handler = handler

    async def send(self, frame: dict) -> None:
        if self._peer and self._peer._handler:
            await self._peer._handler(frame)


def collect(sink: list):
    async def handler(e: Event) -> None:
        sink.append(e)

    return handler


def ev(topic: str, **payload) -> Event:
    return Event(topic=topic, ts=0.0, payload=payload)


class GuardTests(unittest.TestCase):
    def test_permits_only_declared_emittable(self) -> None:
        g = PrivacyGuard()
        # a declared life-shape signal crosses
        self.assertTrue(g.permits(ev("presence.arrived", zone="kitchen")))
        # an identity vector is refused — no field declares it, at any name or depth
        self.assertFalse(g.permits(ev("presence.unknown", vector=[1, 2, 3])))
        self.assertFalse(g.permits(ev("presence.arrived", zone="k", data={"vector": [0.1, 0.2]})))
        # an undeclared topic is refused fail-closed (positive schema, not a denylist)
        self.assertFalse(g.permits(ev("sensor.camera.frame")))
        self.assertFalse(g.permits(ev("x.y", blob="z" * 5000)))

    def test_policy_default_deny(self) -> None:
        p = MeshPolicy()
        self.assertTrue(p.is_meshed("presence.arrived"))
        self.assertTrue(p.is_meshed("security.alert"))
        self.assertFalse(p.is_meshed("interface.say"))  # voice stays node-local


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def _two_nodes(self):
        bus_a, bus_b = Bus(), Bus()
        link_a, link_b = InMemoryLink.pair()
        bridge_a = MeshBridge("a", bus_a, link_a)
        bridge_b = MeshBridge("b", bus_b, link_b)
        await bridge_a.start()
        await bridge_b.start()
        return bus_a, bus_b, bridge_a, bridge_b

    async def test_event_crosses_to_peer(self) -> None:
        bus_a, bus_b, *_ = await self._two_nodes()
        got_b: list[Event] = []
        bus_b.subscribe("presence.arrived", collect(got_b))
        await bus_a.publish(ev("presence.arrived", zone="kitchen"))
        await bus_a.drain()
        await bus_b.drain()
        self.assertEqual(len(got_b), 1)
        self.assertEqual(got_b[0].payload["zone"], "kitchen")
        self.assertEqual(got_b[0].origin, "a")  # source preserved
        await bus_a.aclose()
        await bus_b.aclose()

    async def test_no_loop_back(self) -> None:
        bus_a, bus_b, *_ = await self._two_nodes()
        got_a, got_b = [], []
        bus_a.subscribe("presence.arrived", collect(got_a))
        bus_b.subscribe("presence.arrived", collect(got_b))
        await bus_a.publish(ev("presence.arrived", zone="hall"))
        await bus_a.drain()
        await bus_b.drain()
        await bus_a.drain()  # settle any bounce-back attempt
        self.assertEqual(len(got_a), 1)  # the original, not a duplicate
        self.assertEqual(len(got_b), 1)
        await bus_a.aclose()
        await bus_b.aclose()

    async def test_non_allowlisted_topic_stays_local(self) -> None:
        bus_a, bus_b, *_ = await self._two_nodes()
        got_b: list[Event] = []
        bus_b.subscribe("interface.say", collect(got_b))
        await bus_a.publish(ev("interface.say", text="hello"))
        await bus_a.drain()
        await bus_b.drain()
        self.assertEqual(got_b, [])  # default-deny
        await bus_a.aclose()
        await bus_b.aclose()

    async def test_privacy_blocks_meshed_but_forbidden(self) -> None:
        # The default mesh allowlist (presence/motion/occupancy/security/node) is meshed; the
        # positive schema then permits only the DECLARED shape — a vector-bearing event of an
        # otherwise-meshed topic is refused, a clean life-shape signal crosses.
        bus_a, bus_b = Bus(), Bus()
        link_a, link_b = InMemoryLink.pair()
        a = MeshBridge("a", bus_a, link_a)
        b = MeshBridge("b", bus_b, link_b)
        await a.start()
        await b.start()
        got_b: list[Event] = []
        bus_b.subscribe("presence.**", collect(got_b))
        await bus_a.publish(ev("presence.unknown", zone="back", faceprint=[1, 2, 3]))  # forbidden
        await bus_a.publish(ev("presence.arrived", zone="kitchen"))  # allowed
        await bus_a.drain()
        await bus_b.drain()
        self.assertEqual([e.topic for e in got_b], ["presence.arrived"])
        await bus_a.aclose()
        await bus_b.aclose()

    async def test_dedup_drops_repeat_frame(self) -> None:
        bus_a, bus_b, _, bridge_b = await self._two_nodes()
        got_b: list[Event] = []
        bus_b.subscribe("presence.arrived", collect(got_b))
        frame = {"event": {"topic": "presence.arrived", "ts": 0.0, "payload": {}}, "origin": "a", "seq": 7}
        await bridge_b._on_remote(frame)
        await bridge_b._on_remote(frame)  # same (origin, seq)
        await bus_b.drain()
        self.assertEqual(len(got_b), 1)
        await bus_a.aclose()
        await bus_b.aclose()


class FailingLink:
    def on_receive(self, handler) -> None:
        self._handler = handler

    async def send(self, frame: dict) -> None:
        raise ConnectionError("link down")


class MeshHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_error_surfaced_not_swallowed(self) -> None:
        bus = Bus()
        downs: list[Event] = []
        bus.subscribe("node.link.down", collect(downs))
        bridge = MeshBridge("a", bus, FailingLink())
        await bridge.start()
        await bus.publish(ev("presence.arrived", zone="kitchen"))  # meshed → link.send fails
        await bus.drain()
        self.assertEqual(len(downs), 1)  # the link fault is announced, not hidden as a tile fault
        await bus.publish(ev("presence.arrived", zone="hall"))  # bus still alive
        await bus.drain()
        await bridge.stop()
        await bus.aclose()

    async def test_boot_nonce_avoids_post_restart_false_dedup(self) -> None:
        bus = Bus()
        got: list[Event] = []
        bus.subscribe("presence.arrived", collect(got))
        bridge = MeshBridge("b", bus, InMemoryLink())
        await bridge.start()
        base = {"event": {"topic": "presence.arrived", "ts": 0.0, "payload": {}}, "origin": "a", "seq": 1}
        await bridge._on_remote({**base, "boot": "BOOT1"})
        await bridge._on_remote({**base, "boot": "BOOT1"})  # exact dup → dropped
        await bridge._on_remote({**base, "boot": "BOOT2"})  # peer restarted: same seq, new boot → delivered
        await bus.drain()
        self.assertEqual(len(got), 2)
        await bridge.stop()
        await bus.aclose()


if __name__ == "__main__":
    unittest.main()
