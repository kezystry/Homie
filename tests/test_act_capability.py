"""M5 — the capability gate closes C2. A tile can drive ONLY what its manifest declares,
at the priority it declares, even via a raw emit — in-process AND out-of-process.

The named contract is test_forged_safety_emit_refused: a tile that forges an
actuator.requested (claiming "safety" on an actuator it was never granted) and emits it
is refused, while the same tile's legitimate ctx.act on a declared actuator drives.

Run: python3 -m unittest discover -s tests
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.act import Act, ActMap, CommandLog
from core.bus import Bus
from core.capability import CapabilityRegistry
from core.tile import Event, InProcessChannel, SubprocessChannel, Supervisor

HANDLERS = (
    "from core.tile import Context, Event, Tile\n"
    "class Cap(Tile):\n"
    "    async def on_event(self, event, ctx):\n"
    "        if event.topic == 'go.legit':\n"
    "            await ctx.act('light.ok', {'state': 'on'})\n"
    "        elif event.topic == 'go.forge':\n"
    "            await ctx.emit(Event(topic='actuator.requested', ts=event.ts, payload={\n"
    "                'actuator': 'light.forbidden', 'value': {'state': 'on'},\n"
    "                'tile': 'cap', 'priority': 'safety'}))\n"
)
LEARN = "async def learn(state, friction):\n    return None\n"


def toml_for(network: str) -> str:
    return (
        '[tile]\nname = "cap"\nsummary = "capability test tile"\n'
        '[subscribes]\nevents = ["go.legit", "go.forge"]\n'
        '[provides]\nintents = []\n'
        '[acts]\nactuators = ["light.ok"]\n'
        f'[permissions]\nreads = []\nnetwork = "{network}"\n'
    )


def make_tile(root: Path, network: str) -> None:
    d = root / "cap"
    d.mkdir(parents=True)
    (d / "tile.toml").write_text(toml_for(network), "utf-8")
    (d / "handlers.py").write_text(HANDLERS, "utf-8")
    (d / "learn.py").write_text(LEARN, "utf-8")


class FakeHome:
    def __init__(self) -> None:
        self.driven: list = []

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        self._handler = handler


# light.ok and light.forbidden are BOTH mapped, so the only thing that can stop the forged
# drive is the missing capability — not the act-map.
ACT_MAP = ActMap.from_forward({"light.ok": "entity.ok", "light.forbidden": "entity.forbidden"})


class CapabilityActPathTests(unittest.IsolatedAsyncioTestCase):
    async def _forge_and_legit(self, network: str, expect_channel) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            make_tile(root, network)
            bus = Bus()
            registry = CapabilityRegistry()
            sup = Supervisor(root, bus, registry=registry)
            home = FakeHome()
            act = Act(bus, home, CommandLog(), ACT_MAP, registry=registry)
            await act.start()
            await sup.start("cap")
            try:
                self.assertIsInstance(sup._tiles["cap"].channel, expect_channel)

                # FORGE: the tile emits a "safety" command for an actuator NOT in its manifest.
                await bus.publish(Event("go.forge", 1.0, {}))
                await bus.drain()
                self.assertEqual(home.driven, [], "a forged actuator.requested must never drive")

                # LEGIT: the same tile acts on its declared actuator -> drives.
                await bus.publish(Event("go.legit", 2.0, {}))
                await bus.drain()
                self.assertEqual(home.driven, [("entity.ok", {"state": "on"})],
                                 "a declared actuator must still drive through the capability gate")
            finally:
                await sup.stop("cap")
                await act.stop()
                await bus.aclose()

    async def test_forged_safety_emit_refused(self) -> None:
        # The named contract — in-process.
        await self._forge_and_legit("local", InProcessChannel)

    async def test_forged_safety_emit_refused_subprocess(self) -> None:
        # The named contract — out-of-process (the child can't smuggle it through emit either).
        await self._forge_and_legit("egress:example.com", SubprocessChannel)


class ActSideGateTests(unittest.IsolatedAsyncioTestCase):
    """Act's own refusal, for a forged actuator.requested that reaches the bus by some path
    other than ctx.emit (which already drops it). Uses a bare Act + registry, no tiles."""

    async def _act(self):
        bus = Bus()
        registry = CapabilityRegistry()
        home = FakeHome()
        act = Act(bus, home, CommandLog(), ACT_MAP, registry=registry)
        await act.start()
        return bus, registry, home, act

    async def test_unknown_cap_refused(self) -> None:
        bus, registry, home, act = await self._act()
        failed: list = []
        bus.subscribe("actuator.failed", lambda e: failed.append(e))
        await bus.publish(Event("actuator.requested", 1.0,
                                {"actuator": "light.ok", "value": {"state": "on"}, "cap": "deadbeef"}))
        await bus.drain()
        self.assertEqual(home.driven, [])
        self.assertEqual(failed[-1].payload["reason"], "no_capability")
        await act.stop(); await bus.aclose()

    async def test_no_cap_at_all_refused(self) -> None:
        bus, registry, home, act = await self._act()
        await bus.publish(Event("actuator.requested", 1.0,
                                {"actuator": "light.ok", "value": {"state": "on"}, "priority": "safety"}))
        await bus.drain()
        self.assertEqual(home.driven, [], "a registry-backed Act refuses an uncapped request")
        await act.stop(); await bus.aclose()

    async def test_act_reads_actuator_from_registry_not_payload(self) -> None:
        bus, registry, home, act = await self._act()
        handle = registry.mint("cap", "light.ok", "ambient")  # a VALID cap for light.ok
        await bus.publish(Event("actuator.requested", 1.0,
                                {"actuator": "light.forbidden",  # the payload LIES
                                 "value": {"state": "on"}, "cap": handle}))
        await bus.drain()
        self.assertEqual(home.driven, [("entity.ok", {"state": "on"})],
                         "Act drives the actuator from the resolved cap, not the payload")
        await act.stop(); await bus.aclose()

    async def test_minted_priority_is_the_manifest_level(self) -> None:
        # The handle carries the level the minter set; a tile cannot smuggle "safety".
        registry = CapabilityRegistry()
        h = registry.mint("cap", "light.ok", "ambient")
        self.assertEqual(registry.resolve(h).priority, "ambient")

    async def test_never_touch_absolute_even_with_valid_cap(self) -> None:
        # The act-map stays the hard outer boundary, checked AFTER cap resolution.
        bus = Bus()
        registry = CapabilityRegistry()
        home = FakeHome()
        amap = ActMap.from_forward({"light.ok": "entity.ok", "lock.front": "lock.front_door"},
                                   never_touch={"lock.front_door"})
        act = Act(bus, home, CommandLog(), amap, registry=registry)
        await act.start()
        handle = registry.mint("cap", "lock.front", "safety")  # a valid cap, but the entity is never_touch
        await bus.publish(Event("actuator.requested", 1.0,
                                {"actuator": "lock.front", "value": {"state": "unlocked"}, "cap": handle}))
        await bus.drain()
        self.assertEqual(home.driven, [], "never_touch is absolute even with a valid capability")
        await act.stop(); await bus.aclose()


if __name__ == "__main__":
    unittest.main()
