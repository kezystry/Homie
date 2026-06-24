"""SubprocessChannel tests — an egress tile runs out-of-process over JSON-stdio.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.tile import Event, FrictionSignal, SubprocessChannel, Supervisor

SUB_HANDLERS = (
    "from core.tile import Context, Event, Tile\n"
    "class Sub(Tile):\n"
    "    async def on_event(self, event, ctx):\n"
    "        await ctx.act('light.x', True)\n"
    "        await ctx.emit(Event(topic='sub.done', ts=event.ts, payload={'saw': event.topic}))\n"
    "    async def ping(self, ctx):\n"
    "        return 'pong-sub'\n"
    "    async def boom(self, ctx):\n"
    "        raise RuntimeError('kaboom')\n"
)
SUB_LEARN = "async def learn(state, friction):\n    await state.put('kind', friction.kind)\n"
SUB_TOML = (
    '[tile]\nname = "sub"\nsummary = "an out-of-process tile"\n'
    '[subscribes]\nevents = ["trigger"]\n'
    '[provides]\nintents = []\nfunctions = ["ping", "boom"]\n'
    '[acts]\nactuators = ["light.x"]\n'
    '[permissions]\nreads = []\nnetwork = "egress:example.com"\n'
)


def make_sub(root: Path) -> None:
    d = root / "sub"
    d.mkdir(parents=True)
    (d / "tile.toml").write_text(SUB_TOML, "utf-8")
    (d / "handlers.py").write_text(SUB_HANDLERS, "utf-8")
    (d / "learn.py").write_text(SUB_LEARN, "utf-8")


def collect(sink: list):
    async def handler(e: Event) -> None:
        sink.append(e)

    return handler


class SubprocessChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_egress_tile_runs_out_of_process(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            make_sub(root)
            bus = Bus()
            sup = Supervisor(root, bus)
            await sup.start("sub")
            try:
                # the manifest declares egress, so it must be isolated
                self.assertIsInstance(sup._tiles["sub"].channel, SubprocessChannel)

                done, acted = [], []
                bus.subscribe("sub.done", collect(done))
                bus.subscribe("actuator.requested", collect(acted))
                await bus.publish(Event("trigger", 1.0))
                await bus.drain()

                self.assertEqual(len(done), 1)
                self.assertEqual(done[0].payload["saw"], "trigger")
                self.assertEqual(len(acted), 1)
                self.assertEqual(acted[0].payload["actuator"], "light.x")
            finally:
                await sup.stop("sub")
                await bus.aclose()

    async def test_call_and_error(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            make_sub(root)
            bus = Bus()
            sup = Supervisor(root, bus)
            await sup.start("sub")
            try:
                self.assertEqual(await sup.call_function("ping"), "pong-sub")
                with self.assertRaises(RuntimeError):
                    await sup.call_function("boom")
            finally:
                await sup.stop("sub")
                await bus.aclose()

    async def test_friction_over_subprocess(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            make_sub(root)
            bus = Bus()
            sup = Supervisor(root, bus)
            await sup.start("sub")
            try:
                await sup.deliver_friction(FrictionSignal(kind="remark", at=0.0, target_tile="sub"))
                data = json.loads((root / "sub" / "state" / "data.json").read_text("utf-8"))
                self.assertEqual(data["kind"], "remark")
            finally:
                await sup.stop("sub")
                await bus.aclose()


if __name__ == "__main__":
    unittest.main()
