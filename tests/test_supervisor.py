"""Tile runtime tests — manifest loading, discovery, in-process channel,
permission enforcement, supervision/quarantine, function calls, friction.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.tile import (
    Event,
    FrictionSignal,
    InvalidManifest,
    Manifest,
    Supervisor,
    SupervisionPolicy,
    TileContext,
    load_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def make_tile(root: Path, name: str, *, toml: str, handlers: str, learn: str | None = None) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "tile.toml").write_text(toml, "utf-8")
    (d / "handlers.py").write_text(handlers, "utf-8")
    if learn is not None:
        (d / "learn.py").write_text(learn, "utf-8")


def toml_for(name: str, *, subscribes=(), functions=(), actuators=(), network="local") -> str:
    return (
        f'[tile]\nname = "{name}"\nsummary = "test tile"\n'
        f"[subscribes]\nevents = {list(subscribes)!r}\n"
        f"[provides]\nintents = []\nfunctions = {list(functions)!r}\n"
        f"[acts]\nactuators = {list(actuators)!r}\n"
        f'[permissions]\nreads = []\nnetwork = "{network}"\n'
    )


class ManifestTests(unittest.TestCase):
    def test_load_valid_personal(self) -> None:
        m = load_manifest(ROOT / "tiles" / "personal" / "tile.toml")
        self.assertIsInstance(m, Manifest)
        self.assertEqual(m.name, "personal")
        self.assertIn("presence.arrived", m.subscribes)
        self.assertEqual(m.network, "local")

    def test_invalid_name_mismatch(self) -> None:
        with TemporaryDirectory() as d:
            make_tile(Path(d), "foo", toml=toml_for("bar"), handlers="x = 1\n")
            m = load_manifest(Path(d) / "foo" / "tile.toml")
            self.assertIsInstance(m, InvalidManifest)
            self.assertTrue(any("name" in e for e in m.errors))

    def test_invalid_network_and_pattern(self) -> None:
        with TemporaryDirectory() as d:
            bad = toml_for("z", subscribes=["Bad Pattern"], network="cloud")
            make_tile(Path(d), "z", toml=bad, handlers="")
            m = load_manifest(Path(d) / "z" / "tile.toml")
            self.assertIsInstance(m, InvalidManifest)
            self.assertTrue(any("network" in e for e in m.errors))
            self.assertTrue(any("subscribe" in e for e in m.errors))


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_act_permission(self) -> None:
        acted = []

        async def act(actuator, value):
            acted.append((actuator, value))

        async def noop(*a):
            return None

        ctx = TileContext(
            Manifest("t", "s", actuators=("light.x",)),
            emit=noop,
            act=act,
            speak=noop,
            log_fn=lambda *a: None,
        )
        await ctx.act("light.x", True)
        self.assertEqual(acted, [("light.x", True)])
        with self.assertRaises(PermissionError):
            await ctx.act("light.y", True)


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_skips_template(self) -> None:
        sup = Supervisor(ROOT / "tiles", Bus())
        names = [m.name for m in sup.discover() if isinstance(m, Manifest)]
        self.assertIn("personal", names)
        self.assertNotIn("template", names)
        self.assertNotIn("_template", names)

    async def test_event_reaction_end_to_end(self) -> None:
        with TemporaryDirectory() as d:
            make_tile(
                Path(d),
                "echo",
                toml=toml_for("echo", subscribes=["ping.*"]),
                handlers=(
                    "from core.tile import Context, Event, Tile\n"
                    "class Echo(Tile):\n"
                    "    async def on_event(self, event, ctx):\n"
                    "        await ctx.emit(Event(topic='echo.done', ts=event.ts, payload={'saw': event.topic}))\n"
                ),
            )
            bus = Bus()
            got = []

            async def collect(e):
                got.append(e)

            bus.subscribe("echo.done", collect)
            sup = Supervisor(Path(d), bus)
            await sup.start("echo")
            await bus.publish(Event("ping.now", 0.0))
            await bus.drain()
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0].payload["saw"], "ping.now")
            await bus.aclose()

    async def test_quarantine_after_faults(self) -> None:
        with TemporaryDirectory() as d:
            make_tile(
                Path(d),
                "boom",
                toml=toml_for("boom", subscribes=["x.*"]),
                handlers=(
                    "from core.tile import Tile\n"
                    "class Boom(Tile):\n"
                    "    async def on_event(self, event, ctx):\n"
                    "        raise RuntimeError('boom')\n"
                ),
            )
            bus = Bus()
            sup = Supervisor(Path(d), bus, SupervisionPolicy(quarantine_after=2))
            await sup.start("boom")
            await bus.publish(Event("x.1", 0.0))
            await bus.drain()
            await bus.publish(Event("x.2", 0.0))
            await bus.drain()
            self.assertEqual(sup.status()["boom"], "QUARANTINED")
            await bus.aclose()

    async def test_call_function(self) -> None:
        with TemporaryDirectory() as d:
            make_tile(
                Path(d),
                "calc",
                toml=toml_for("calc", functions=["ping"]),
                handlers=(
                    "from core.tile import Tile\n"
                    "class Calc(Tile):\n"
                    "    async def on_event(self, event, ctx): ...\n"
                    "    async def ping(self, ctx):\n"
                    "        return 'pong'\n"
                ),
            )
            sup = Supervisor(Path(d), Bus())
            await sup.start("calc")
            self.assertEqual(await sup.call_function("ping"), "pong")

    async def test_friction_delivery(self) -> None:
        with TemporaryDirectory() as d:
            make_tile(
                Path(d),
                "learner",
                toml=toml_for("learner"),
                handlers=(
                    "from core.tile import Tile\n"
                    "class Learner(Tile):\n"
                    "    async def on_event(self, event, ctx): ...\n"
                ),
                learn="async def learn(state, friction):\n    await state.put('last', friction.kind)\n",
            )
            sup = Supervisor(Path(d), Bus())
            await sup.start("learner")
            await sup.deliver_friction(FrictionSignal(kind="remark", at=0.0, target_tile="learner"))
            data = json.loads((Path(d) / "learner" / "state" / "data.json").read_text("utf-8"))
            self.assertEqual(data["last"], "remark")


if __name__ == "__main__":
    unittest.main()
