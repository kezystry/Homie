"""The golden loop — the alive arc as enforced invariants on the REAL graph.

This is scripts/spine_demo.py's narrative converted from prints into assertions,
driven through `build_daemon` (not a bespoke demo wiring). It proves the keystone:
on the production graph a tile drives the home on arrival, the home's echo is
suppressed (and confirmed done) by the StateReconciler, and a human reversal makes
the tile go quiet on the next identical arrival. If any of Act / StateReconciler /
the friction path is unwired (the C1 regression), this test fails.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.act import ActMap
from core.daemon import DaemonConfig, build_daemon
from core.tile import ActionRef, Event, FrictionSignal


class FakeHome:
    """Records drives and replays the home's echoes / a human's manual change."""

    def __init__(self) -> None:
        self.driven: list = []
        self._handler = None

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        self._handler = handler

    async def emit(self, entity_id, value) -> None:
        if self._handler:
            await self._handler(entity_id, value)


def at(hour: int, day: int = 20) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


class GoldenLoopTests(unittest.TestCase):
    def test_arrival_drives_reversal_makes_tile_quiet(self) -> None:
        async def run() -> None:
            tmp = Path(tempfile.mkdtemp(prefix="homie-golden-"))
            home = FakeHome()
            config = DaemonConfig(
                state=tmp,
                housekeep=False,
                compact_threshold=0,
                act_map=ActMap.from_forward({"light.living_room": "light.lr"}),
            )
            daemon = build_daemon(home, None, config=config)
            done: list = []
            try:
                await daemon.start()
                daemon.bus.subscribe("actuator.done", lambda e: done.append(e))

                # 1) evening arrival -> Lighting drives the bulb on (tiles + Act wired)
                await daemon.bus.publish(Event("presence.arrived", at(21), {"zone": "living"}))
                await daemon.bus.drain()
                self.assertTrue(home.driven, "Lighting should drive the bulb on an after-dark arrival")
                entity, value = home.driven[-1]
                self.assertEqual(entity, "light.lr")

                # 2) the home echoes our own command -> suppressed, confirmed done
                #    (StateReconciler + CommandLog + Act.confirm all wired)
                await home.emit("light.lr", value)
                await daemon.bus.drain()
                self.assertTrue(
                    any(e.payload.get("actuator") == "light.living_room" for e in done),
                    "the echo of Homie's own command must be confirmed as actuator.done, "
                    "not read as a human reversal (StateReconciler wired)",
                )

                # 3) a human reversal -> friction teaches Lighting to stay dark at this hour
                ref = ActionRef("test", "lighting", "light.living_room", {"state": "on"}, at(21))
                await daemon.sup.deliver_friction(
                    FrictionSignal(kind="reversal", at=at(21), target_tile="lighting",
                                   reverses=ref, zone="living", actor="owner"))
                await daemon.bus.drain()

                # 4) the next identical arrival -> Lighting stays quiet (friction -> learn wired)
                before = len(home.driven)
                await daemon.bus.publish(Event("presence.arrived", at(21, 21), {"zone": "living"}))
                await daemon.bus.drain()
                self.assertEqual(
                    len(home.driven), before,
                    "after the reversal Lighting must stay dark at this hour (friction loop wired)",
                )
            finally:
                await daemon.stop()
                shutil.rmtree(tmp, ignore_errors=True)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
