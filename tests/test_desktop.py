"""Desktop hands — safe, capability-gated control of the main PC.

Proves the security ruling in code: control is a FIXED allowlist of media verbs (an unknown
verb is refused, never run as a shell), it flows through the ONE capability gate (a forged
request with no handle is refused), and the CompositeHome routes desktop verbs to the executor
while real-home commands still reach Home Assistant.

Run: python3 -m unittest discover -s tests
"""
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.act import Act, ActMap, CommandLog
from core.bus import Bus
from core.capability import CapabilityRegistry
from core.desktop import CompositeHome, DesktopExecutor
from core.tile import Event, Supervisor

ROOT = Path(__file__).resolve().parents[1]

_DESKTOP_MAP = {
    "desktop.play_pause": "desktop:play_pause",
    "desktop.next": "desktop:next",
    "desktop.prev": "desktop:prev",
    "desktop.seek_fwd": "desktop:seek_fwd",
    "desktop.seek_back": "desktop:seek_back",
    "desktop.stop": "desktop:stop",
    "desktop.close": "desktop:close",
}


class _FakeHA:
    def __init__(self) -> None:
        self.driven: list = []

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        return


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_allowlisted_verb_runs_fixed_argv(self) -> None:
        runs: list = []
        exe = DesktopExecutor(run=lambda args: runs.append(args))
        await exe.drive("desktop:play_pause", {})
        self.assertEqual(runs, [["xdotool", "key", "--clearmodifiers", "space"]])
        self.assertIsInstance(runs[0], list)            # fixed ARGV, never a shell string

    async def test_unknown_verb_is_refused_not_run(self) -> None:
        runs: list = []
        exe = DesktopExecutor(run=lambda args: runs.append(args))
        with self.assertRaises(ValueError):
            await exe.drive("desktop:rm_rf_home", {})   # arbitrary "verb" → refused
        self.assertEqual(runs, [])                       # nothing executed

    async def test_close_active_window_is_a_fixed_window_action(self) -> None:
        runs: list = []
        exe = DesktopExecutor(run=lambda args: runs.append(args))
        await exe.drive("desktop:close", {})             # no target → active window
        self.assertEqual(runs, [["xdotool", "getactivewindow", "windowclose"]])

    async def test_close_named_app_uses_its_allowlisted_argv(self) -> None:
        runs: list = []
        exe = DesktopExecutor(run=lambda args: runs.append(args))
        await exe.drive("desktop:close", {"target": "Stremio"})   # case-insensitive
        self.assertEqual(runs, [["xdotool", "search", "--class", "stremio", "windowclose"]])

    async def test_close_unknown_app_is_refused_not_run(self) -> None:
        runs: list = []
        exe = DesktopExecutor(run=lambda args: runs.append(args))
        with self.assertRaises(ValueError):
            await exe.drive("desktop:close", {"target": "online_banking"})
        self.assertEqual(runs, [])                        # an un-allowlisted app never closes

    async def test_no_runner_is_a_safe_noop(self) -> None:
        exe = DesktopExecutor()                          # not wired on this host
        await exe.drive("desktop:next", {})              # records intent, executes nothing
        self.assertEqual(exe.driven, ["next"])

    async def test_composite_routes_desktop_vs_home(self) -> None:
        runs: list = []
        ha = _FakeHA()
        home = CompositeHome(ha, DesktopExecutor(run=lambda a: runs.append(a)))
        await home.drive("desktop:play_pause", {})
        await home.drive("light.kitchen", {"state": "on"})
        self.assertEqual(len(runs), 1)                   # desktop verb went to the executor
        self.assertEqual(ha.driven, [("light.kitchen", {"state": "on"})])  # the rest to HA


class GatedEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self, root: Path):
        shutil.copytree(ROOT / "tiles" / "desktop", root / "desktop")
        bus = Bus()
        registry = CapabilityRegistry()
        sup = Supervisor(root, bus, registry=registry)
        await sup.start("desktop")
        runs: list = []
        exe = DesktopExecutor(run=lambda a: runs.append(a))
        act = Act(bus, CompositeHome(_FakeHA(), exe), CommandLog(),
                  ActMap.from_forward(_DESKTOP_MAP), registry=registry)
        await act.start()
        return bus, sup, exe, runs

    async def test_function_drives_through_the_gate(self) -> None:
        with TemporaryDirectory() as d:
            bus, sup, exe, runs = await self._setup(Path(d))
            await sup.call_function("play_pause")
            await bus.drain()
            self.assertEqual(exe.driven, ["play_pause"])  # the cortex/voice can pause the film
            await bus.aclose()

    async def test_close_command_event_drives_through_the_gate(self) -> None:
        with TemporaryDirectory() as d:
            bus, sup, exe, runs = await self._setup(Path(d))
            # what /close stremio publishes — routed by the tile to the gated close actuator
            await bus.publish(Event("desktop.control", 0.0,
                                    {"verb": "close", "target": "stremio"}, source="commands"))
            await bus.drain()
            self.assertEqual(exe.driven, ["close:stremio"])
            self.assertEqual(runs, [["xdotool", "search", "--class", "stremio", "windowclose"]])
            await bus.aclose()

    async def test_forged_request_without_a_capability_is_refused(self) -> None:
        with TemporaryDirectory() as d:
            bus, sup, exe, runs = await self._setup(Path(d))
            failed: list = []
            bus.subscribe("actuator.failed", lambda e: failed.append(e))
            # a raw publish with NO capability handle (a forged/escalation attempt)
            await bus.publish(Event("actuator.requested", 0.0,
                                    {"actuator": "desktop.play_pause", "value": {}}, source="forge"))
            await bus.drain()
            self.assertEqual(exe.driven, [])              # nothing executed
            self.assertTrue(failed and failed[-1].payload["reason"] == "no_capability")
            await bus.aclose()


if __name__ == "__main__":
    unittest.main()
