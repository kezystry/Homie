"""Keystone wiring contracts — the invariants that keep the shipped graph == the
tested graph. Each test FAILS if its bug returns.

  * Act is wired (C1: actuation exists in production, not just the demo).
  * Remember attaches LAST (C4: an event is evaluated before it joins history).
  * A novel event is not self-masked (C4, behaviorally, on the real graph).
  * run.py and spine_demo.py both route through build_daemon (no second wiring).
  * The anchor answers chat with no cortex; the cortex owns chat with no double reply.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest
from datetime import datetime
from pathlib import Path

from core.daemon import DaemonConfig, build_daemon
from core.reason import Proposal
from core.tile import Event

ROOT = Path(__file__).resolve().parents[1]


class FakeHome:
    def __init__(self) -> None:
        self.driven: list = []
        self._handler = None

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        self._handler = handler


class FakeLLM:
    """A present cortex: always says something, so chat gets exactly one reply."""

    async def propose(self, *, system, context, tools) -> Proposal:
        return Proposal(say="from the cortex")


def at(hour: int, day: int = 20) -> float:
    return datetime(2026, 6, day, hour, 0, 0).timestamp()


async def _started(config: DaemonConfig | None = None):
    home = FakeHome()
    daemon = build_daemon(home, None, config=config or DaemonConfig(housekeep=False))
    await daemon.start()
    return daemon, home


class WiringTests(unittest.TestCase):
    def test_act_subscribes_actuator_requested(self) -> None:
        async def run() -> None:
            d, _ = await _started()
            try:
                self.assertTrue(
                    any(s.owner == "act" and s.regex.match("actuator.requested") for s in d.bus._subs),
                    "Act must subscribe actuator.requested in the production graph (C1)",
                )
            finally:
                await d.stop()
        asyncio.run(run())

    def test_remember_attached_last(self) -> None:
        async def run() -> None:
            d, _ = await _started()
            try:
                owners = [s.owner for s in d.bus._subs]
                tile_idx = [i for i, o in enumerate(owners) if o and o.startswith("tile:")]
                rem_idx = [i for i, o in enumerate(owners) if o == "core:remember"]
                self.assertTrue(rem_idx, "Remember must be attached to the bus")
                self.assertTrue(tile_idx, "tiles must be subscribed")
                self.assertGreater(
                    min(rem_idx), max(tile_idx),
                    "Remember must attach AFTER every tile (C4: evaluate-then-commit)",
                )
            finally:
                await d.stop()
        asyncio.run(run())

    def test_novel_event_not_self_masked(self) -> None:
        async def run() -> None:
            d, _ = await _started()
            alerts: list = []
            d.bus.subscribe("security.alert", lambda e: alerts.append(e))
            try:
                await d.bus.publish(Event("presence.unknown", at(3), {"zone": "back_door"}))
                await d.bus.drain()
                self.assertTrue(
                    alerts,
                    "a first-sighting novel presence must alert — Remember must not record it "
                    "before Security evaluates it (C4)",
                )
            finally:
                await d.stop()
        asyncio.run(run())

    def test_entrypoints_share_graph(self) -> None:
        run_src = (ROOT / "scripts" / "run.py").read_text("utf-8")
        demo_src = (ROOT / "scripts" / "spine_demo.py").read_text("utf-8")
        for name, src in (("run.py", run_src), ("spine_demo.py", demo_src)):
            self.assertIn("build_daemon(", src, f"{name} must route through build_daemon")
        # the production entrypoint must not hand-wire the core itself
        self.assertNotIn("Supervisor(", run_src, "run.py must not construct the Supervisor directly")
        self.assertNotIn("Act(", run_src, "run.py must not construct Act directly")

    def test_anchor_answers_chat_without_cortex(self) -> None:
        async def run() -> None:
            d, _ = await _started()
            self.assertIsNotNone(d.anchor, "the anchor voice must be wired when there is no cortex")
            replies: list = []
            d.bus.subscribe("chat.reply", lambda e: replies.append(e.payload.get("text")))
            try:
                await d.bus.publish(Event("chat.message", at(12), {"text": "are you there?"}, source="cockpit"))
                await d.bus.drain()
                self.assertEqual(len(replies), 1, "the anchor must answer exactly once")
                self.assertTrue(replies[0])
            finally:
                await d.stop()
        asyncio.run(run())

    def test_cortex_owns_chat_no_double_reply(self) -> None:
        async def run() -> None:
            d, _ = await _started(DaemonConfig(housekeep=False, llm=FakeLLM()))
            self.assertIsNone(d.anchor, "the anchor must be unwired when a real cortex is present")
            replies: list = []
            d.bus.subscribe("chat.reply", lambda e: replies.append(e.payload.get("text")))
            try:
                await d.bus.publish(Event("chat.message", at(12), {"text": "hello"}, source="cockpit"))
                await d.bus.drain()
                self.assertEqual(len(replies), 1, "exactly one reply (the cortex), never a double")
            finally:
                await d.stop()
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
