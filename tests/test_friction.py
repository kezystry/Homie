"""Friction attribution tests — reversal / remark / repeat map back to a tile.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.tile import Event, Supervisor

ACTOR_HANDLERS = (
    "from core.tile import Context, Event, Tile\n"
    "class Actor(Tile):\n"
    "    async def on_event(self, event, ctx):\n"
    "        await ctx.act('light.x', True)\n"
)
ACTOR_LEARN = (
    "async def learn(state, friction):\n"
    "    seen = list(state.get('seen', []))\n"
    "    seen.append(friction.kind)\n"
    "    await state.put('seen', seen)\n"
)
ACTOR_TOML = (
    '[tile]\nname = "actor"\nsummary = "acts on a light"\n'
    '[subscribes]\nevents = ["trigger"]\n'
    "[provides]\nintents = []\nfunctions = []\n"
    '[acts]\nactuators = ["light.x"]\n'
    '[permissions]\nreads = []\nnetwork = "local"\n'
)


def make_actor(root: Path) -> None:
    d = root / "actor"
    d.mkdir(parents=True)
    (d / "tile.toml").write_text(ACTOR_TOML, "utf-8")
    (d / "handlers.py").write_text(ACTOR_HANDLERS, "utf-8")
    (d / "learn.py").write_text(ACTOR_LEARN, "utf-8")


def learned(root: Path) -> list[str]:
    return json.loads((root / "actor" / "state" / "data.json").read_text("utf-8")).get("seen", [])


class FrictionTests(unittest.IsolatedAsyncioTestCase):
    async def _started(self, root: Path):
        make_actor(root)
        bus = Bus()
        sup = Supervisor(root, bus)
        await sup.start("actor")
        # actor acts on light.x -> a stamp lands in the ledger
        await bus.publish(Event("trigger", 100.0))
        await bus.drain()
        return bus, sup

    async def test_reversal_attributes_to_acting_tile(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup = await self._started(root)
            sig = await sup.note_reversal("light.x", False, at=120.0)  # human turned it off
            self.assertIsNotNone(sig)
            self.assertEqual(sig.target_tile, "actor")
            self.assertEqual(learned(root), ["reversal"])
            await bus.aclose()

    async def test_reversal_ignores_same_value(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup = await self._started(root)
            sig = await sup.note_reversal("light.x", True, at=120.0)  # same state — not a reversal
            self.assertIsNone(sig)
            await bus.aclose()

    async def test_remark_attributes_to_recent_actor(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup = await self._started(root)
            sig = await sup.note_remark("stop doing that", at=110.0)
            self.assertEqual(sig.target_tile, "actor")
            self.assertEqual(learned(root), ["remark"])
            await bus.aclose()

    async def test_repeat_after_threshold(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup = await self._started(root)
            first = await sup.note_manual("light.x", at=130.0, threshold=2)
            self.assertIsNone(first)  # below threshold
            second = await sup.note_manual("light.x", at=131.0, threshold=2)
            self.assertEqual(second.kind, "repeat")
            self.assertEqual(second.target_tile, "actor")
            self.assertEqual(learned(root), ["repeat"])
            await bus.aclose()

    async def test_zone_and_actor_stamped_on_signals(self) -> None:
        # BACKLOG #9: the runtime stamps where/who a correction came from so
        # downstream can attribute per-person and apply the privacy exclusions.
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup = await self._started(root)
            rev = await sup.note_reversal("light.x", False, at=120.0, zone="kitchen", actor="alice")
            self.assertEqual((rev.zone, rev.actor), ("kitchen", "alice"))
            rem = await sup.note_remark("not now", at=121.0, zone="hallway", actor="bob")
            self.assertEqual((rem.zone, rem.actor), ("hallway", "bob"))
            rep = await sup.note_manual("light.x", at=131.0, threshold=1, zone="entry", actor="guest")
            self.assertEqual((rep.zone, rep.actor), ("entry", "guest"))
            await bus.aclose()

    async def test_signals_default_unknown_context(self) -> None:
        # additive + backward compatible: unstamped signals carry None context.
        with TemporaryDirectory() as d:
            root = Path(d)
            bus, sup = await self._started(root)
            sig = await sup.note_reversal("light.x", False, at=120.0)
            self.assertEqual((sig.zone, sig.actor), (None, None))
            await bus.aclose()


if __name__ == "__main__":
    unittest.main()
