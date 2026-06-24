"""Act + StateReconciler tests — the home gateway and the friction producer.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.act import Act, ActMap, CommandLog
from core.bus import Bus
from core.reconcile import StateReconciler
from core.tile import Event, Supervisor


class FakeHomeClient:
    """Stand-in for the MQTT/HA client. Records drives; lets a test emit echoes
    and human state changes by hand — fully deterministic, no broker, no time."""

    def __init__(self) -> None:
        self.driven: list[tuple[str, object]] = []
        self._handler = None

    async def drive(self, entity_id: str, command: object) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        self._handler = handler

    async def emit(self, entity_id: str, value: object) -> None:
        if self._handler:
            await self._handler(entity_id, value)


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


MAP = ActMap.from_forward(
    {"light.living_room": "light.lr", "light.kitchen": "light.kit"},
    never_touch=["lock.front_door"],
)


def collect(sink: list):
    async def handler(e: Event) -> None:
        sink.append(e)

    return handler


class ActMapTests(unittest.TestCase):
    def test_forward_reverse_and_never_touch(self) -> None:
        m = ActMap.from_forward(
            {"light.living_room": "light.lr", "x": "lock.front_door"},
            never_touch=["lock.front_door"],
        )
        self.assertEqual(m.entity_for("light.living_room"), "light.lr")
        self.assertEqual(m.reverse["light.lr"], "light.living_room")
        self.assertIsNone(m.entity_for("x"))  # mapped to a never-touch entity → dropped

    def test_load_from_toml(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "act_map.toml"
            p.write_text(
                '[actuators]\n"light.k" = "light.kit"\n[never_touch]\nentities = ["lock.x"]\n',
                "utf-8",
            )
            m = ActMap.load(p)
            self.assertEqual(m.entity_for("light.k"), "light.kit")
            self.assertIn("lock.x", m.never_touch)


class ActTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_drives_mapped_entity(self) -> None:
        bus, home = Bus(), FakeHomeClient()
        act = Act(bus, home, CommandLog(), MAP)
        await act.start()
        await bus.publish(Event("actuator.requested", 1.0, {"actuator": "light.kitchen", "value": "on", "tile": "lighting"}))
        await bus.drain()
        self.assertEqual(home.driven, [("light.kit", "on")])
        await act.stop()
        await bus.aclose()

    async def test_unmapped_refused(self) -> None:
        bus, home = Bus(), FakeHomeClient()
        failed: list[Event] = []
        bus.subscribe("actuator.failed", collect(failed))
        act = Act(bus, home, CommandLog(), MAP)
        await act.start()
        await bus.publish(Event("actuator.requested", 1.0, {"actuator": "light.garage", "value": "on", "tile": "x"}))
        await bus.drain()
        self.assertEqual(home.driven, [])  # never driven
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].payload["reason"], "unmapped")
        await act.stop()
        await bus.aclose()


class CommandLogTests(unittest.TestCase):
    def test_echo_match_pop_and_window(self) -> None:
        clk = FakeClock()
        log = CommandLog(window=5.0, clock=clk)
        log.record("light.lr", "on", "lighting")
        # an unrelated change is not an echo
        self.assertIsNone(log.take_echo("light.kit", "on"))
        # the matching change within the window is an echo, and is consumed
        self.assertIsNotNone(log.take_echo("light.lr", "on"))
        self.assertIsNone(log.take_echo("light.lr", "on"))  # popped — only once
        # a record that ages past the window is evicted
        log.record("light.lr", "off", "lighting")
        clk.t += 6.0
        self.assertIsNone(log.take_echo("light.lr", "off"))


class ReconcilerTests(unittest.IsolatedAsyncioTestCase):
    async def test_echo_suppressed_and_confirmed(self) -> None:
        bus, home = Bus(), FakeHomeClient()
        commands = CommandLog()
        act = Act(bus, home, commands, MAP)
        await act.start()
        done: list[Event] = []
        bus.subscribe("actuator.done", collect(done))
        rec = StateReconciler(_SpySupervisor(), commands, MAP.reverse, on_echo=act.confirm)
        rec.attach(home)

        await bus.publish(Event("actuator.requested", 1.0, {"actuator": "light.living_room", "value": "on", "tile": "lighting"}))
        await bus.drain()
        await home.emit("light.lr", "on")  # the echo of our own command
        await bus.drain()
        self.assertEqual(len(done), 1)  # confirmed done
        self.assertEqual(rec.sup.reversals, [])  # no friction from our own act
        self.assertEqual(rec.sup.manuals, [])
        await act.stop()
        await bus.aclose()

    async def test_human_manual_action_notes_manual(self) -> None:
        sup = _SpySupervisor()
        commands = CommandLog()
        home = FakeHomeClient()
        rec = StateReconciler(sup, commands, MAP.reverse)
        rec.attach(home)
        await home.emit("light.kit", "on")  # human flipped it; no Homie command pending
        # note_reversal is consulted (returns None — no recent tile act), then it
        # falls through to note_manual. The manual action is what matters.
        self.assertEqual(sup.manuals, [("light.kitchen",)])

    async def test_never_touch_entity_ignored(self) -> None:
        sup = _SpySupervisor()
        rec = StateReconciler(sup, CommandLog(), MAP.reverse)
        home = FakeHomeClient()
        rec.attach(home)
        await home.emit("lock.front_door", "unlocked")  # not in reverse map
        self.assertEqual(sup.manuals, [])
        self.assertEqual(sup.reversals, [])


class _SpySupervisor:
    """Records note_* calls; note_reversal returns None (no tile act) so the
    reconciler falls through to note_manual."""

    def __init__(self) -> None:
        self.reversals: list = []
        self.manuals: list = []

    async def note_reversal(self, actuator, value, at):
        self.reversals.append((actuator, value))
        return None

    async def note_manual(self, actuator, at):
        self.manuals.append((actuator,))
        return None


# --- the full friction loop, end to end, with a REAL Supervisor + a learning tile ---
ACTOR_HANDLERS = (
    "from core.tile import Context, Event, Tile\n"
    "class Actor(Tile):\n"
    "    async def on_event(self, event, ctx):\n"
    "        await ctx.act('light.living_room', 'on')\n"
)
ACTOR_LEARN = (
    "async def learn(state, friction):\n"
    "    seen = list(state.get('seen', []))\n"
    "    seen.append(friction.kind)\n"
    "    await state.put('seen', seen)\n"
)
ACTOR_TOML = (
    '[tile]\nname = "actor"\nsummary = "acts on the living-room light"\n'
    '[subscribes]\nevents = ["trigger"]\n'
    "[provides]\nintents = []\nfunctions = []\n"
    '[acts]\nactuators = ["light.living_room"]\n'
    '[permissions]\nreads = []\nnetwork = "local"\n'
)


def make_actor(root: Path) -> None:
    d = root / "actor"
    d.mkdir(parents=True)
    (d / "tile.toml").write_text(ACTOR_TOML, "utf-8")
    (d / "handlers.py").write_text(ACTOR_HANDLERS, "utf-8")
    (d / "learn.py").write_text(ACTOR_LEARN, "utf-8")


def learned(root: Path) -> list[str]:
    f = root / "actor" / "state" / "data.json"
    if not f.exists():  # no friction delivered yet ⇒ the tile never wrote state
        return []
    return json.loads(f.read_text("utf-8")).get("seen", [])


class FrictionLoopEndToEnd(unittest.IsolatedAsyncioTestCase):
    async def test_tile_act_echo_then_human_reversal(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            make_actor(root)
            bus, home = Bus(), FakeHomeClient()
            commands = CommandLog()
            sup = Supervisor(root, bus)
            await sup.start("actor")
            act = Act(bus, home, commands, MAP)
            await act.start()
            rec = StateReconciler(sup, commands, MAP.reverse, on_echo=act.confirm)
            rec.attach(home)

            # 1) tile reacts -> ctx.act -> actuator.requested -> Act drives the home
            await bus.publish(Event("trigger", 1.0))
            await bus.drain()
            self.assertEqual(home.driven, [("light.lr", "on")])

            # 2) the home echoes our own command -> suppressed, no friction
            await home.emit("light.lr", "on")
            await bus.drain()
            self.assertEqual(learned(root), [])  # the tile learned nothing from its own act

            # 3) a human turns it off -> a reversal of the tile's act -> learn()
            await home.emit("light.lr", "off")
            await bus.drain()
            self.assertEqual(learned(root), ["reversal"])

            await act.stop()
            await sup.stop("actor")
            await bus.aclose()


class ArbitrationTests(unittest.IsolatedAsyncioTestCase):
    """Act wires the bus as the safety referee: priority + recency decide conflicts."""

    async def _act(self):
        bus, home = Bus(), FakeHomeClient()
        act = Act(bus, home, CommandLog(), MAP, hold_window=5.0)
        await act.start()
        return bus, home, act

    def _req(self, actuator, value, priority, ts):
        return Event("actuator.requested", ts, {"actuator": actuator, "value": value, "tile": "t", "priority": priority})

    async def test_higher_priority_holds_suppresses_lower(self) -> None:
        bus, home, act = await self._act()
        await bus.publish(self._req("light.living_room", "on", "security", 1.0))
        await bus.publish(self._req("light.living_room", "off", "convenience", 1.5))  # within window, lower
        await bus.drain()
        self.assertEqual(home.driven, [("light.lr", "on")])  # the loser was not driven
        await act.stop()
        await bus.aclose()

    async def test_recency_breaks_ties(self) -> None:
        bus, home, act = await self._act()
        await bus.publish(self._req("light.living_room", "on", "automation", 1.0))
        await bus.publish(self._req("light.living_room", "off", "automation", 2.0))  # equal priority, newer
        await bus.drain()
        self.assertEqual(home.driven[-1], ("light.lr", "off"))  # newer wins the tie
        await act.stop()
        await bus.aclose()

    async def test_distinct_actuators_independent(self) -> None:
        bus, home, act = await self._act()
        await bus.publish(self._req("light.living_room", "on", "convenience", 1.0))
        await bus.publish(self._req("light.kitchen", "on", "convenience", 1.0))
        await bus.drain()
        self.assertEqual(set(home.driven), {("light.lr", "on"), ("light.kit", "on")})
        await act.stop()
        await bus.aclose()

    async def test_missing_priority_defaults(self) -> None:
        bus, home, act = await self._act()
        await bus.publish(Event("actuator.requested", 1.0, {"actuator": "light.kitchen", "value": "on", "tile": "t"}))
        await bus.drain()
        self.assertEqual(home.driven, [("light.kit", "on")])
        await act.stop()
        await bus.aclose()


if __name__ == "__main__":
    unittest.main()
