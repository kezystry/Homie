"""The Voice waist (Phase A) — the muzzle wired into the real graph.

Two layers of proof:
  * The VoiceGate transforms interface.say -> interface.spoken (governed) / speech.deferred
    (held), exempts safety, and obeys the everyday mute.
  * The red team's missing test, on the REAL graph: the TOTAL proactive speech reaching the
    owner across ALL tiles+cortex is bounded by the one global budget; overflow defers and
    is never dropped; a safety line is never capped. A per-tile "quiet by default" could not
    prove this — only a single cross-tile governor can.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest
from datetime import datetime

from core.bus import Bus
from core.daemon import DaemonConfig, build_daemon
from core.speech_budget import SpeechBudget, SpeechGovernor
from core.tile import Event
from core.voice import VoiceGate


def at(hour: int, minute: int = 0, day: int = 20) -> float:
    return datetime(2026, 6, day, hour, minute, 0).timestamp()


class FakeHome:
    def __init__(self) -> None:
        self.driven: list = []

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        self._handler = handler


class GateUnitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = Bus()
        self.spoken: list = []
        self.deferred: list = []
        self.bus.subscribe("interface.spoken", lambda e: self.spoken.append(e))
        self.bus.subscribe("speech.deferred", lambda e: self.deferred.append(e))

    async def asyncTearDown(self) -> None:
        await self.bus.aclose()

    async def _gate(self, governor=None) -> VoiceGate:
        gate = VoiceGate(self.bus, governor=governor)
        await gate.start()
        return gate

    async def test_within_budget_is_spoken(self) -> None:
        await self._gate()
        await self.bus.publish(Event("interface.say", at(8), {"text": "morning"}, source="tile:personal"))
        await self.bus.drain()
        self.assertEqual([e.payload["text"] for e in self.spoken], ["morning"])
        self.assertEqual(self.deferred, [])

    async def test_safety_bypasses_a_zero_budget(self) -> None:
        gate = await self._gate(SpeechGovernor(budget=SpeechBudget(per_hour=0.0, per_day=0)))
        await self.bus.publish(Event("interface.say", at(3), {"text": "smoke!", "kind": "safety"},
                                     source="tile:security"))
        await self.bus.drain()
        self.assertEqual([e.payload["text"] for e in self.spoken], ["smoke!"])

    async def test_mute_defers_proactive_keeps_safety(self) -> None:
        gate = await self._gate()
        await self.bus.publish(Event("voice.mute", at(9), {"seconds": 3600}, source="cockpit"))
        await self.bus.drain()
        await self.bus.publish(Event("interface.say", at(9, 10), {"text": "chatter"}, source="tile:lighting"))
        await self.bus.publish(Event("interface.say", at(9, 11), {"text": "alarm", "kind": "alert"},
                                     source="tile:security"))
        await self.bus.drain()
        self.assertEqual([e.payload["text"] for e in self.spoken], ["alarm"])
        self.assertEqual([e.payload["text"] for e in self.deferred], ["chatter"])

    async def test_unmute_restores_speech(self) -> None:
        gate = await self._gate()
        await self.bus.publish(Event("voice.mute", at(9), {"seconds": 3600}, source="cockpit"))
        await self.bus.publish(Event("voice.unmute", at(9, 5), {}, source="cockpit"))
        await self.bus.drain()
        await self.bus.publish(Event("interface.say", at(9, 10), {"text": "hi"}, source="tile:lighting"))
        await self.bus.drain()
        self.assertEqual([e.payload["text"] for e in self.spoken], ["hi"])


class CrossTileCapTests(unittest.IsolatedAsyncioTestCase):
    """The red team's test_total_proactive_speech_is_capped_across_tiles, on build_daemon."""

    async def test_total_proactive_speech_is_capped_across_tiles(self) -> None:
        home = FakeHome()
        daemon = build_daemon(home, None, config=DaemonConfig(housekeep=False))
        # Pin a generous per-hour burst but a small DAILY ceiling, so this test isolates the
        # global daily cap across tiles (the per-hour smoothing is exercised separately).
        daemon.voice.gov = SpeechGovernor(budget=SpeechBudget(per_hour=20.0, per_day=4))
        await daemon.start()
        spoken, deferred = [], []
        daemon.bus.subscribe("interface.spoken", lambda e: spoken.append(e))
        daemon.bus.subscribe("speech.deferred", lambda e: deferred.append(e))
        try:
            # Ten DIFFERENT tiles each try to say one proactive line within the same hour —
            # the exact "N independent mouths on the same morning" the red team warned about.
            for i in range(10):
                await daemon.bus.publish(Event("interface.say", at(7, i),
                                               {"text": f"line {i}"}, source=f"tile:mouth{i}"))
            # ...plus one genuine safety line, which must always get through.
            await daemon.bus.publish(Event("interface.say", at(7, 30),
                                           {"text": "intruder", "kind": "safety"}, source="tile:security"))
            await daemon.bus.drain()
        finally:
            await daemon.stop()

        proactive_spoken = [e for e in spoken if e.payload.get("kind") != "safety"]
        safety_spoken = [e for e in spoken if e.payload.get("kind") == "safety"]
        # The SUM across all tiles is bounded by the one global daily ceiling (4), not 10.
        self.assertEqual(len(proactive_spoken), 4)
        # The other six are deferred to the recap, never dropped.
        self.assertEqual(len(deferred), 6)
        self.assertEqual(len(proactive_spoken) + len(deferred), 10)
        # Safety is never capped.
        self.assertEqual([e.payload["text"] for e in safety_spoken], ["intruder"])

    async def test_raw_say_never_reaches_the_cockpit_channel(self) -> None:
        # The coherence invariant: the cockpit's outbound allowlist forwards the GOVERNED
        # channel only. A tile cannot reach the owner by emitting interface.say directly.
        from core.cockpit_bridge import CockpitPolicy
        p = CockpitPolicy()
        self.assertTrue(p.may_send("interface.spoken"))
        self.assertFalse(p.may_send("interface.say"))


if __name__ == "__main__":
    unittest.main()
