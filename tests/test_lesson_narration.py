"""M4 — the hour-shaped lesson, spoken back (the first goosebumps).

When a reversal teaches Lighting to stop auto-lighting a room at an hour, the home
SAYS so — once, naming the room and the hour — and the lesson survives a restart.
Runs on the real graph via build_daemon, so the narration path is the shipped one.

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
    def __init__(self) -> None:
        self.driven: list = []
        self._handler = None

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        self._handler = handler


def at(hour: int, day: int = 20) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


def _kitchen_reversal() -> FrictionSignal:
    ref = ActionRef("x", "lighting", "light.kitchen", {"state": "on"}, at(19))
    return FrictionSignal(kind="reversal", at=at(19), target_tile="lighting",
                          reverses=ref, zone="kitchen", actor="owner")


class LessonNarrationTests(unittest.TestCase):
    def test_learn_commit_emits_one_line(self) -> None:
        async def run() -> None:
            tmp = Path(tempfile.mkdtemp(prefix="homie-lesson-"))
            cfg = lambda: DaemonConfig(state=tmp, housekeep=False, compact_threshold=0,
                                       act_map=ActMap.from_forward({"light.kitchen": "light.k"}))
            daemon = build_daemon(FakeHome(), None, config=cfg())
            said: list = []
            try:
                await daemon.start()
                daemon.bus.subscribe("interface.say", lambda e: said.append(e.payload.get("text")))

                # a household reversal at 7pm teaches Lighting to stay dark — it says so, once.
                await daemon.sup.deliver_friction(_kitchen_reversal())
                await daemon.bus.drain()
                self.assertEqual(len(said), 1, "exactly one spoken line when the lesson forms")
                self.assertIn("kitchen", said[0])
                self.assertIn("7pm", said[0])

                # the SAME correction again forms no new lesson -> no second line (no chatter).
                await daemon.sup.deliver_friction(_kitchen_reversal())
                await daemon.bus.drain()
                self.assertEqual(len(said), 1, "a repeat correction must not re-narrate")
            finally:
                await daemon.stop()

            # restart on the same state: the lesson persisted (no re-narration AND the
            # 7pm kitchen arrival stays dark) — the suppression outlives the process.
            home2 = FakeHome()
            daemon2 = build_daemon(home2, None, config=cfg())
            said2: list = []
            try:
                await daemon2.start()
                daemon2.bus.subscribe("interface.say", lambda e: said2.append(e.payload.get("text")))

                await daemon2.sup.deliver_friction(_kitchen_reversal())
                await daemon2.bus.drain()
                self.assertEqual(said2, [], "a lesson learned before the restart is still known")

                await daemon2.bus.publish(Event("presence.arrived", at(19, 21), {"zone": "kitchen"}))
                await daemon2.bus.drain()
                self.assertEqual(home2.driven, [], "the persisted suppression keeps the kitchen dark at 7pm")
            finally:
                await daemon2.stop()
                shutil.rmtree(tmp, ignore_errors=True)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
