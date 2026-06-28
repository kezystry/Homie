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
    TileState,
    load_manifest,
)


class TileStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_atomic_put_persists_and_leaves_no_tmp(self) -> None:
        with TemporaryDirectory() as d:
            s = TileState(Path(d) / "state")
            await s.put("seen", ["a", "b"])
            again = TileState(Path(d) / "state")  # fresh read
            self.assertEqual(again.get("seen"), ["a", "b"])
            self.assertFalse((Path(d) / "state" / "data.json.tmp").exists())  # no stray temp


def rich_toml(name: str, function_blocks: str) -> str:
    return (
        f'[tile]\nname = "{name}"\nsummary = "rich tile"\n'
        f"[subscribes]\nevents = []\n"
        f"[provides]\nintents = []\n{function_blocks}\n"
        f"[acts]\nactuators = []\n"
        f'[permissions]\nreads = []\nnetwork = "local"\n'
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

    def test_invalid_actuator_name_rejected(self) -> None:
        with TemporaryDirectory() as d:
            # uppercase / non-canonical actuator must be flagged (it would never match act-map keys)
            bad = toml_for("z", actuators=["light.Kitchen"])
            make_tile(Path(d), "z", toml=bad, handlers="")
            m = load_manifest(Path(d) / "z" / "tile.toml")
            self.assertIsInstance(m, InvalidManifest)
            self.assertTrue(any("actuator" in e for e in m.errors))

    def test_valid_dotted_actuator_accepted(self) -> None:
        with TemporaryDirectory() as d:
            ok = toml_for("z", actuators=["light.kitchen", "desktop.play_pause"])
            make_tile(Path(d), "z", toml=ok, handlers="")
            m = load_manifest(Path(d) / "z" / "tile.toml")
            self.assertNotIsInstance(m, InvalidManifest)

    def test_bare_functions_backcompat(self) -> None:
        with TemporaryDirectory() as d:
            make_tile(Path(d), "x", toml=toml_for("x", functions=["a", "b"]), handlers="")
            m = load_manifest(Path(d) / "x" / "tile.toml")
            self.assertEqual(m.functions, ("a", "b"))
            self.assertEqual(len(m.function_specs), 2)
            self.assertEqual(m.function_specs[0].description, "")
            self.assertEqual(m.function_specs[0].params, ())

    def test_rich_functions_parse(self) -> None:
        blocks = (
            '[[provides.functions]]\nname = "add_reminder"\ndescription = "Add a reminder."\n'
            '[[provides.functions.params]]\nname = "text"\ntype = "string"\nrequired = true\n'
        )
        with TemporaryDirectory() as d:
            make_tile(Path(d), "r", toml=rich_toml("r", blocks), handlers="")
            m = load_manifest(Path(d) / "r" / "tile.toml")
            self.assertEqual(m.functions, ("add_reminder",))
            spec = m.function_specs[0]
            self.assertEqual(spec.description, "Add a reminder.")
            self.assertEqual(spec.params[0].name, "text")
            self.assertEqual(spec.params[0].type, "string")
            self.assertTrue(spec.params[0].required)

    def test_invalid_param_type(self) -> None:
        blocks = (
            '[[provides.functions]]\nname = "f"\ndescription = "x"\n'
            '[[provides.functions.params]]\nname = "n"\ntype = "str"\n'  # not allowed
        )
        with TemporaryDirectory() as d:
            make_tile(Path(d), "r", toml=rich_toml("r", blocks), handlers="")
            m = load_manifest(Path(d) / "r" / "tile.toml")
            self.assertIsInstance(m, InvalidManifest)
            self.assertTrue(any("param type" in e for e in m.errors))

    def test_personal_rich_names_unchanged(self) -> None:
        m = load_manifest(ROOT / "tiles" / "personal" / "tile.toml")
        self.assertIsInstance(m, Manifest)
        self.assertEqual(m.functions, ("agenda", "add_reminder", "add_task"))
        add_reminder = next(s for s in m.function_specs if s.name == "add_reminder")
        self.assertEqual(add_reminder.params[0].name, "text")

    def test_priority_default_and_override(self) -> None:
        toml = (
            '[tile]\nname = "p"\nsummary = "s"\n[subscribes]\nevents = []\n'
            "[provides]\nintents = []\nfunctions = []\n"
            '[acts]\nactuators = ["light.a", "lock.b"]\npriority = "convenience"\n'
            '[acts.priorities]\n"lock.b" = "safety"\n'
            '[permissions]\nreads = []\nnetwork = "local"\n'
        )
        with TemporaryDirectory() as d:
            make_tile(Path(d), "p", toml=toml, handlers="")
            m = load_manifest(Path(d) / "p" / "tile.toml")
            self.assertIsInstance(m, Manifest)
            self.assertEqual(m.default_priority, "convenience")
            self.assertEqual(m.priority_for("light.a"), "convenience")  # default
            self.assertEqual(m.priority_for("lock.b"), "safety")  # per-actuator override

    def test_invalid_priority_rejected(self) -> None:
        toml = (
            '[tile]\nname = "p"\nsummary = "s"\n[subscribes]\nevents = []\n'
            "[provides]\nintents = []\nfunctions = []\n"
            '[acts]\nactuators = ["light.a"]\npriority = "urgent"\n'  # not a Priority level
            '[permissions]\nreads = []\nnetwork = "local"\n'
        )
        with TemporaryDirectory() as d:
            make_tile(Path(d), "p", toml=toml, handlers="")
            m = load_manifest(Path(d) / "p" / "tile.toml")
            self.assertIsInstance(m, InvalidManifest)
            self.assertTrue(any("priority" in e for e in m.errors))


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_act_permission(self) -> None:
        acted = []

        async def act(actuator, value, priority="automation"):
            acted.append((actuator, value, priority))

        async def noop(*a):
            return None

        ctx = TileContext(
            Manifest("t", "s", actuators=("light.x",), default_priority="security"),
            emit=noop,
            act=act,
            speak=noop,
            log_fn=lambda *a: None,
        )
        await ctx.act("light.x", True)
        self.assertEqual(acted, [("light.x", True, "security")])  # priority resolved from manifest
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

    async def test_tool_catalog_roundtrip(self) -> None:
        blocks = (
            '[[provides.functions]]\nname = "ping"\ndescription = "Say pong."\n'
            '[[provides.functions]]\nname = "echo"\ndescription = "Echo text."\n'
            '[[provides.functions.params]]\nname = "text"\ntype = "string"\nrequired = true\n'
        )
        with TemporaryDirectory() as d:
            (Path(d) / "calc").mkdir(parents=True)
            (Path(d) / "calc" / "tile.toml").write_text(rich_toml("calc", blocks), "utf-8")
            (Path(d) / "calc" / "handlers.py").write_text(
                "from core.tile import Tile\n"
                "class Calc(Tile):\n"
                "    async def on_event(self, event, ctx): ...\n"
                "    async def ping(self, ctx): return 'pong'\n"
                "    async def echo(self, ctx, text): return text\n",
                "utf-8",
            )
            sup = Supervisor(Path(d), Bus())
            await sup.start("calc")
            catalog = sup.tool_catalog()
            by_name = {t["function"]["name"]: t["function"] for t in catalog}
            self.assertEqual(set(by_name), {"ping", "echo"})
            self.assertEqual(by_name["ping"]["parameters"], {"type": "object", "properties": {}})
            self.assertEqual(by_name["echo"]["parameters"]["required"], ["text"])
            self.assertEqual(by_name["echo"]["parameters"]["properties"]["text"]["type"], "string")
            # the catalog name is actually callable
            self.assertEqual(await sup.call_function("echo", text="hi"), "hi")

    async def test_duplicate_function_name_across_tiles_refused(self) -> None:
        blocks = '[[provides.functions]]\nname = "agenda"\ndescription = "x"\n'
        with TemporaryDirectory() as d:
            for n in ("one", "two"):
                (Path(d) / n).mkdir(parents=True)
                (Path(d) / n / "tile.toml").write_text(rich_toml(n, blocks), "utf-8")
                (Path(d) / n / "handlers.py").write_text(
                    "from core.tile import Tile\n"
                    "class T(Tile):\n"
                    "    async def on_event(self, event, ctx): ...\n"
                    "    async def agenda(self, ctx): return 1\n",
                    "utf-8",
                )
            sup = Supervisor(Path(d), Bus())
            await sup.start("one")
            await sup.start("two")  # collides on 'agenda'
            self.assertEqual(sup.status()["one"], "READY")
            self.assertEqual(sup.status()["two"], "INVALID")

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
