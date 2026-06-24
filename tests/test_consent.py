"""Consent (confirmation gate) tests — stdlib unittest.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.consent import Consent
from core.tile import Event, Supervisor


def collect(sink: list):
    async def handler(e: Event) -> None:
        sink.append(e)

    return handler


def auto_respond(bus: Bus, yes: bool):
    """Answer any confirm.requested with the given verdict — stands in for the
    gesture detector / voice (nod=yes, shake=no)."""

    async def handler(e: Event) -> None:
        await bus.publish(Event("confirm.response", 0.0, {"id": e.payload["id"], "yes": yes}))

    return handler


class ConsentTests(unittest.IsolatedAsyncioTestCase):
    async def test_yes_resolves_true(self) -> None:
        bus = Bus()
        consent = Consent(bus)
        await consent.start()
        bus.subscribe("confirm.requested", auto_respond(bus, True))
        self.assertTrue(await consent.request("ok?"))
        await consent.stop()
        await bus.aclose()

    async def test_no_resolves_false(self) -> None:
        bus = Bus()
        consent = Consent(bus)
        await consent.start()
        bus.subscribe("confirm.requested", auto_respond(bus, False))
        self.assertFalse(await consent.request("ok?"))
        await consent.stop()
        await bus.aclose()

    async def test_timeout_resolves_false(self) -> None:
        bus = Bus()
        consent = Consent(bus, timeout=0.01)
        await consent.start()
        self.assertFalse(await consent.request("ok?"))  # nobody answers → fail safe
        self.assertEqual(consent._pending, {})  # cleaned up
        await consent.stop()
        await bus.aclose()

    async def test_default_override(self) -> None:
        bus = Bus()
        consent = Consent(bus, timeout=0.01, default=True)
        await consent.start()
        self.assertTrue(await consent.request("ok?"))  # default is configurable
        await consent.stop()
        await bus.aclose()

    async def test_stale_response_ignored(self) -> None:
        bus = Bus()
        consent = Consent(bus, timeout=0.05)
        await consent.start()
        # a response for an id we never issued must not resolve anything
        await bus.publish(Event("confirm.response", 0.0, {"id": "bogus", "yes": True}))
        await bus.drain()
        self.assertFalse(await consent.request("ok?"))  # still times out (fail safe)
        await consent.stop()
        await bus.aclose()

    async def test_request_payload_shape(self) -> None:
        bus = Bus()
        consent = Consent(bus)
        await consent.start()
        seen: list[Event] = []
        bus.subscribe("confirm.requested", collect(seen))
        bus.subscribe("confirm.requested", auto_respond(bus, True))
        await consent.request("lock up?", actuator="lock.front", risk="high")
        await bus.drain()
        p = seen[0].payload
        self.assertEqual(p["prompt"], "lock up?")
        self.assertEqual(p["actuator"], "lock.front")
        self.assertEqual(p["risk"], "high")
        self.assertIsInstance(p["id"], str)
        self.assertEqual(seen[0].source, "consent")
        await consent.stop()
        await bus.aclose()


# --- end to end: a tile only acts on a yes ---
GATED_HANDLERS = (
    "from core.tile import Context, Event, Tile\n"
    "class Gated(Tile):\n"
    "    async def on_event(self, event, ctx):\n"
    "        if await ctx.confirm('turn on the heater?', risk='high'):\n"
    "            await ctx.act('heater', 'on')\n"
)
GATED_TOML = (
    '[tile]\nname = "gated"\nsummary = "asks before acting"\n'
    '[subscribes]\nevents = ["trigger"]\n'
    "[provides]\nintents = []\nfunctions = []\n"
    '[acts]\nactuators = ["heater"]\n'
    '[permissions]\nreads = []\nnetwork = "local"\n'
)


def make_gated(root: Path) -> None:
    d = root / "gated"
    d.mkdir(parents=True)
    (d / "tile.toml").write_text(GATED_TOML, "utf-8")
    (d / "handlers.py").write_text(GATED_HANDLERS, "utf-8")


class ConsentEndToEnd(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *, answer, timeout=30.0):
        with TemporaryDirectory() as d:
            root = Path(d)
            make_gated(root)
            bus = Bus()
            consent = Consent(bus, timeout=timeout)
            await consent.start()
            acted: list[Event] = []
            bus.subscribe("actuator.requested", collect(acted))
            if answer is not None:
                bus.subscribe("confirm.requested", auto_respond(bus, answer))
            sup = Supervisor(root, bus, consent=consent)
            await sup.start("gated")
            await bus.publish(Event("trigger", 0.0))
            await bus.drain()
            result = [e.payload["actuator"] for e in acted]
            await sup.stop("gated")
            await consent.stop()
            await bus.aclose()
            return result

    async def test_acts_on_yes(self) -> None:
        self.assertEqual(await self._run(answer=True), ["heater"])

    async def test_does_not_act_on_no(self) -> None:
        self.assertEqual(await self._run(answer=False), [])

    async def test_does_not_act_on_timeout(self) -> None:
        self.assertEqual(await self._run(answer=None, timeout=0.01), [])  # fail safe


if __name__ == "__main__":
    unittest.main()
